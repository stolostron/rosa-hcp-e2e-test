"""
Monitoring Agent
================

Real-time monitoring of test execution output with pattern detection.

This agent hooks into the test suite's line-by-line output streaming to
detect issues as they happen, enabling immediate intervention.

Issue lifecycle per resource:
    DETECTED -> DIAGNOSING -> REMEDIATING -> RESOLVED / FAILED

Author: Tina Fitzgerald
Created: March 3, 2026
"""

import re
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .base_agent import BaseAgent

# Structured context marker emitted by Ansible playbooks.
# Format: #AGENT_CONTEXT: key1=value1 key2=value2
AGENT_CONTEXT_PATTERN = re.compile(r'^#AGENT_CONTEXT:\s+(.+)$')


class IssueState(Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    FAILED = "failed"


class TrackedIssue:
    """Tracks the lifecycle of a single issue for a specific resource."""

    def __init__(self, issue_type: str, resource_key: str, issue: Dict):
        self.issue_type = issue_type
        self.resource_key = resource_key
        self.issue = issue
        self.state = IssueState.DETECTED
        self.detected_at = time.time()
        self.last_updated = self.detected_at
        self.attempts = 0
        self.max_attempts = 3

    def can_retry(self) -> bool:
        return (
            self.state == IssueState.FAILED
            and self.attempts < self.max_attempts
        )

    def should_intervene(self) -> bool:
        return self.state in (IssueState.DETECTED,) or self.can_retry()


class MonitoringAgent(BaseAgent):
    """Real-time monitoring agent for test execution output."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False):
        super().__init__("Monitor", base_dir, enabled, verbose)

        # Callback for when issues are detected
        self.issue_callback: Optional[Callable] = None

        # Buffer for multi-line pattern matching
        self.line_buffer: List[str] = []
        self.buffer_size = 50

        # State tracking
        self.current_task = None
        self.waiting_for_resource = None

        # Per-resource issue tracking (replaces simple debounce)
        # Key: "{issue_type}:{resource_key}", Value: TrackedIssue
        self._tracked_issues: Dict[str, TrackedIssue] = {}

        # Structured context from playbook markers
        self._structured_context: Dict[str, str] = {}

    def set_issue_callback(self, callback: Callable):
        """Set callback function to be called when issues are detected.

        The callback signature must be:
            callback(issue_type: str, context: Dict, issue: Dict) -> None

        The context dict will include a ``resource_key`` field that uniquely
        identifies the resource this issue relates to.  Pass it back to
        ``mark_issue_resolved`` / ``mark_issue_failed`` so the state machine
        resolves the correct tracked issue.
        """
        self.issue_callback = callback
        self.log("Issue callback registered", "debug")

    def process_line(self, line: str) -> bool:
        """
        Process a single line of output from test execution.

        Returns:
            True if line triggered an intervention
        """
        if not self.enabled:
            return False

        # Add to buffer for context
        self.line_buffer.append(line)
        if len(self.line_buffer) > self.buffer_size:
            self.line_buffer.pop(0)

        # Check for structured context markers from playbooks
        self._parse_structured_context(line)

        # Track current execution context
        self._update_execution_context(line)

        # Detect issues using knowledge base patterns only
        issue = self._detect_issue(line)
        if issue:
            return self._handle_detected_issue(issue, line)

        return False

    def _handle_detected_issue(self, issue: Dict, line: str) -> bool:
        """Handle a detected issue through the state machine."""
        issue_type = issue.get("type", "unknown")

        # Build a resource key from structured context or fallback to issue type
        resource_key = self._build_resource_key()
        tracking_key = f"{issue_type}:{resource_key}"

        # Check if we're already tracking this issue for this resource
        tracked = self._tracked_issues.get(tracking_key)

        if tracked:
            if not tracked.should_intervene():
                self.log(
                    f"Issue {issue_type} for {resource_key} already in state "
                    f"{tracked.state.value} (attempt {tracked.attempts}/{tracked.max_attempts})",
                    "debug",
                )
                return False
        else:
            # New issue — start tracking
            tracked = TrackedIssue(issue_type, resource_key, issue)
            self._tracked_issues[tracking_key] = tracked
            self.log(f"Issue detected: {issue_type} for {resource_key}", "warning")

        self.patterns_detected.append(issue)

        if not self.issue_callback or not self.should_intervene(issue):
            return False

        # Transition to DIAGNOSING
        tracked.state = IssueState.DIAGNOSING
        tracked.attempts += 1
        tracked.last_updated = time.time()

        context = {
            "line": line,
            "buffer": self.line_buffer[-30:],
            "current_task": self.current_task,
            "waiting_for": self.waiting_for_resource,
            "resource_key": resource_key,
        }

        # Merge structured context if available
        if self._structured_context:
            context.update(self._structured_context)

        self.issue_callback(issue_type, context, issue)
        return True

    def mark_issue_resolved(self, issue_type: str, resource_key: str = None):
        """Mark an issue as resolved (called by remediation agent on success)."""
        if resource_key is None:
            resource_key = self._build_resource_key()
        tracking_key = f"{issue_type}:{resource_key}"
        tracked = self._tracked_issues.get(tracking_key)
        if tracked:
            tracked.state = IssueState.RESOLVED
            tracked.last_updated = time.time()
            self.log(f"Issue resolved: {issue_type} for {resource_key}", "success")

    def mark_issue_failed(self, issue_type: str, resource_key: str = None):
        """Mark an issue remediation as failed (called by remediation agent on failure)."""
        if resource_key is None:
            resource_key = self._build_resource_key()
        tracking_key = f"{issue_type}:{resource_key}"
        tracked = self._tracked_issues.get(tracking_key)
        if tracked:
            tracked.state = IssueState.FAILED
            tracked.last_updated = time.time()
            self.log(
                f"Issue remediation failed: {issue_type} for {resource_key} "
                f"(attempt {tracked.attempts}/{tracked.max_attempts})",
                "warning",
            )

    def _build_resource_key(self) -> str:
        """Build a resource key from available context."""
        # Prefer structured context
        name = self._structured_context.get("resource_name")
        ns = self._structured_context.get("namespace")
        if name:
            return f"{ns or 'default'}/{name}"

        # Fallback to waiting_for + current_task
        if self.waiting_for_resource:
            return self.waiting_for_resource
        if self.current_task:
            return self.current_task
        return "unknown"

    def _parse_structured_context(self, line: str):
        """Parse structured context markers emitted by Ansible playbooks.

        Format: #AGENT_CONTEXT: resource_name=my-cluster namespace=my-ns resource_type=rosanetwork
        """
        match = AGENT_CONTEXT_PATTERN.match(line.strip())
        if match:
            pairs = match.group(1)
            for pair in pairs.split():
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    self._structured_context[key] = value
            self.log(f"Structured context: {self._structured_context}", "debug")

    def _update_execution_context(self, line: str):
        """Extract execution context from output line."""
        if "TASK [" in line:
            task_match = line.split("TASK [")[1].split("]")[0]
            if task_match:
                self.current_task = task_match
                # Clear structured context from previous task so stale
                # values don't leak into a new task's issue handling
                self._structured_context.clear()
                self.update_context("current_task", task_match)
                self.log(f"Current task: {task_match}", "debug")

        if "Waiting for" in line or "waiting for" in line:
            if "ROSANetwork" in line:
                self.waiting_for_resource = "ROSANetwork"
            elif "ROSAControlPlane" in line:
                self.waiting_for_resource = "ROSAControlPlane"
            elif "ROSARoleConfig" in line:
                self.waiting_for_resource = "ROSARoleConfig"
            self.update_context("waiting_for", self.waiting_for_resource)

    def _detect_issue(self, line: str) -> Optional[Dict]:
        """Detect known issues using knowledge base patterns only.

        All patterns are defined in known_issues.json. No hardcoded
        keyword detection — single source of truth.
        """
        patterns = self.known_issues.get("patterns", [])
        return self.match_pattern(line, patterns)

    def get_statistics(self) -> Dict:
        """Get monitoring statistics."""
        tracked_summary = {}
        for key, tracked in self._tracked_issues.items():
            tracked_summary[key] = {
                "state": tracked.state.value,
                "attempts": tracked.attempts,
            }
        return {
            "patterns_detected": len(self.patterns_detected),
            "interventions_performed": len(self.interventions),
            "current_task": self.current_task,
            "waiting_for": self.waiting_for_resource,
            "tracked_issues": tracked_summary,
        }

    def reset(self):
        """Reset monitoring state for new test run."""
        self.line_buffer.clear()
        self.patterns_detected.clear()
        self.current_task = None
        self.waiting_for_resource = None
        self._tracked_issues.clear()
        self._structured_context.clear()
        self.log("Monitoring state reset", "debug")
