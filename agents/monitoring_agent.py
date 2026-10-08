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
# May appear bare or inside Ansible debug output like:
#   "msg": "#AGENT_CONTEXT: resource_name=foo namespace=bar"
AGENT_CONTEXT_PATTERN = re.compile(r'#AGENT_CONTEXT:\s+(.+?)(?:"|$)')


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
        # Allow re-intervention for RESOLVED issues if the resource is still
        # stuck (e.g., CF stack was fixed but K8s finalizer still needs removal).
        # Use a longer cooldown (120s) to avoid thrashing.
        if self.state == IssueState.RESOLVED:
            if self.attempts < self.max_attempts and (time.time() - self.last_updated) >= 120:
                return True
            return False
        # Allow re-diagnosis after exhausting max_attempts if enough time has
        # passed (2 min).  The underlying resource status may have changed
        # (e.g., CF stack went from DELETE_IN_PROGRESS to DELETE_FAILED).
        # Grant one more attempt so the diagnostic agent can re-check.
        if (
            self.state == IssueState.FAILED
            and self.attempts >= self.max_attempts
            and (time.time() - self.last_updated) >= 120
        ):
            self.max_attempts += 1
            return True
        if not (self.state in (IssueState.DETECTED,) or self.can_retry()):
            return False
        # Throttle re-checks to at most once per 60 seconds
        if self.attempts > 0 and (time.time() - self.last_updated) < 60:
            return False
        return True


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

        # Guard: skip stale issues that don't match the current structured
        # context.  For example, if the sidecar log still contains old
        # rosanetwork_stuck_deletion lines but the playbook has already
        # moved on to rosaroleconfig, we must not re-trigger the old issue.
        ctx_resource_type = self._structured_context.get("resource_type")
        if ctx_resource_type and "_stuck_deletion" in issue_type:
            expected_prefix = f"{ctx_resource_type}_stuck_deletion"
            if issue_type != expected_prefix:
                self.log(
                    f"Skipping stale issue {issue_type} — structured context says resource_type={ctx_resource_type}",
                    "debug",
                )
                return False

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

    def mark_issue_resolved(self, issue_type: str, resource_key: str = None,
                            verify_fn: Optional[Callable] = None):
        """Mark an issue as resolved (called by remediation agent on success).

        A fix returning True does not always mean the underlying resource is
        actually gone — e.g., rosanetwork_stuck_deletion's CF-retry can report
        success while the CloudFormation stack / VPC is still present (a leaked
        load balancer holding ENIs). Callers may pass ``verify_fn`` — a
        zero-arg callable returning True only when the resource is confirmed
        gone. If it returns False we do NOT flip to RESOLVED, leaving the issue
        in FAILED so the remaining attempts (up to max_attempts) still fire.

        Issue types that don't need verification simply omit ``verify_fn`` and
        behave exactly as before.
        """
        if resource_key is None:
            resource_key = self._build_resource_key()
        tracking_key = f"{issue_type}:{resource_key}"
        tracked = self._tracked_issues.get(tracking_key)
        if tracked:
            if verify_fn is not None:
                try:
                    confirmed_gone = verify_fn()
                except Exception as e:
                    # Verification errors are non-fatal — treat as "not
                    # confirmed gone" and keep retrying rather than crashing.
                    self.log(f"Resolution verification error for {issue_type}: {e}", "warning")
                    confirmed_gone = False
                if not confirmed_gone:
                    # Fix reported success but the resource is still present.
                    # Keep the issue non-terminal so remaining attempts fire.
                    tracked.state = IssueState.FAILED
                    tracked.last_updated = time.time()
                    self.log(
                        f"Fix reported success but {issue_type} for {resource_key} "
                        f"is still present — not marking resolved "
                        f"(attempt {tracked.attempts}/{tracked.max_attempts})",
                        "warning",
                    )
                    return
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
        # A single Ansible result line can contain the marker more than once:
        # the unexpanded `cmd` field (e.g. resource_name=$NETWORK_NAME with a
        # trailing "\n" continuation) and the expanded `stdout`/`stdout_lines`
        # with real values. Field order within the serialized result is NOT
        # guaranteed, so we can't just take the last occurrence — the expanded
        # marker may come before or after the placeholder one. Instead, parse
        # EVERY marker and let real values win: a $-placeholder never overwrites
        # a value already set from an expanded marker on the same line.
        matches = list(AGENT_CONTEXT_PATTERN.finditer(line.strip()))
        if not matches:
            return
        for match in matches:
            for pair in match.group(1).split():
                if '=' not in pair:
                    continue
                key, value = pair.split('=', 1)
                # Values matched from the JSON-serialized `cmd` field can carry
                # trailing escape artifacts — a literal "\n"/"\r"/"\t" line
                # continuation (backslash + letter, not a real newline) or a
                # lone trailing backslash — plus surrounding quotes. Strip them
                # so downstream exact-match logic (resource_type == "rosanetwork")
                # is reliable.
                value = value.strip()
                value = re.sub(r'\\[nrt]$', '', value)  # literal \n \r \t suffix
                value = value.rstrip('\\').strip('"\'')
                # Never let an unexpanded shell placeholder ($NETWORK_NAME) or an
                # empty value clobber a real one — regardless of marker order.
                if not value or value.startswith('$'):
                    continue
                self._structured_context[key] = value
        # Preserve this context across the next TASK boundary so the
        # immediately following wait task can use it.
        self._structured_context["_preserve_for_next_task"] = True
        self.log(f"Structured context: {self._structured_context}", "debug")

    def _update_execution_context(self, line: str):
        """Extract execution context from output line."""
        if "TASK [" in line:
            task_match = line.split("TASK [")[1].split("]")[0]
            if task_match:
                self.current_task = task_match
                # Clear structured context from previous task so stale
                # values don't leak into a new task's issue handling.
                # But preserve context if the previous task was an
                # agent context emitter (the context is meant for the
                # immediately following task).
                if not self._structured_context.get("_preserve_for_next_task"):
                    self._structured_context.clear()
                else:
                    # Consumed — don't preserve again
                    self._structured_context.pop("_preserve_for_next_task", None)
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
