"""
Learning Agent
==============

Records outcomes from remediation attempts and adjusts the knowledge base
over time based on what works and what doesn't.

Safety model:
    - Auto-learns: confidence adjustments, new diagnostic patterns
    - Human approval required: new remediation actions (logged to pending_learnings.json)

Author: Tina Fitzgerald
Created: March 30, 2026
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .base_agent import BaseAgent


class LearningAgent(BaseAgent):
    """Records remediation outcomes and adjusts the knowledge base."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False):
        super().__init__("Learning", base_dir, enabled, verbose)

        # Outcome history file — append-only log of every remediation result
        self.outcomes_file = self.kb_dir / "remediation_outcomes.json"

        # Pending learnings — new patterns/remediations awaiting human review
        self.pending_file = self.kb_dir / "pending_learnings.json"

        # Session outcomes (flushed to disk at end of run)
        self.session_outcomes: List[Dict] = []

    def record_outcome(self, issue_type: str, diagnosis: Dict, fix_applied: str,
                       success: bool, resource_key: str = "", details: str = ""):
        """
        Record the outcome of a remediation attempt.

        Called by the pipeline after RemediationAgent.remediate() returns.
        """
        if not self.enabled:
            return

        outcome = {
            "timestamp": datetime.now().isoformat(),
            "issue_type": issue_type,
            "recommended_fix": fix_applied,
            "success": success,
            "confidence_used": diagnosis.get("confidence", 0),
            "root_cause": diagnosis.get("root_cause", ""),
            "resource_key": resource_key,
            "details": details,
        }

        self.session_outcomes.append(outcome)

        status = "SUCCESS" if success else "FAILED"
        self.log(f"Outcome recorded: {issue_type} -> {fix_applied} = {status}", "info")

    def end_of_run_summary(self) -> Dict:
        """
        Analyze session outcomes and return a learning summary.

        Called at the end of each test run. Updates confidence scores
        in the knowledge base based on accumulated evidence.
        """
        if not self.session_outcomes:
            return {"adjustments": [], "pending_reviews": []}

        # Group outcomes by issue_type + fix
        fix_stats = {}
        for outcome in self.session_outcomes:
            key = f"{outcome['issue_type']}:{outcome['recommended_fix']}"
            if key not in fix_stats:
                fix_stats[key] = {"successes": 0, "failures": 0, "issue_type": outcome["issue_type"],
                                  "fix": outcome["recommended_fix"]}
            if outcome["success"]:
                fix_stats[key]["successes"] += 1
            else:
                fix_stats[key]["failures"] += 1

        # Capture count before persisting (which clears session_outcomes)
        session_count = len(self.session_outcomes)

        # Persist outcomes to history
        self._append_outcomes()

        # Load historical outcomes for confidence adjustment
        all_outcomes = self._load_all_outcomes()

        # Calculate adjustments
        adjustments = self._calculate_confidence_adjustments(all_outcomes)

        # Apply adjustments to known_issues.json
        if adjustments:
            self._apply_confidence_adjustments(adjustments)

        summary = {
            "session_outcomes": session_count,
            "fix_stats": fix_stats,
            "adjustments": adjustments,
            "pending_reviews": self._get_pending_count(),
        }

        self.log(f"Learning summary: {session_count} outcomes, "
                 f"{len(adjustments)} confidence adjustments", "info")

        return summary

    def suggest_new_pattern(self, log_line: str, diagnosis: Dict, fix_applied: str,
                            success: bool):
        """
        Suggest a new pattern for the knowledge base based on a Claude-diagnosed issue.

        These go to pending_learnings.json for human review — never auto-added
        to known_issues.json because new remediations could be destructive.
        """
        if not self.enabled:
            return

        suggestion = {
            "timestamp": datetime.now().isoformat(),
            "status": "pending_review",
            "trigger_line": log_line[:500],  # Truncate long lines
            "suggested_pattern": {
                "type": diagnosis.get("issue_type", "unknown"),
                "pattern": "",  # Human needs to write the regex
                "severity": diagnosis.get("severity", "medium"),
                "auto_fix": False,  # Default to manual — human must approve auto_fix
                "description": diagnosis.get("root_cause", ""),
                "suggested_fix": fix_applied,
                "fix_success": success,
            },
            "diagnosis_details": {
                "root_cause": diagnosis.get("root_cause", ""),
                "confidence": diagnosis.get("confidence", 0),
                "evidence": diagnosis.get("evidence", []),
                "recommended_fix": diagnosis.get("recommended_fix", ""),
            }
        }

        self._append_pending(suggestion)
        self.log(f"New pattern suggested for review: {diagnosis.get('issue_type', 'unknown')}", "info")

    def _calculate_confidence_adjustments(self, all_outcomes: List[Dict]) -> List[Dict]:
        """
        Calculate confidence adjustments based on historical outcomes.

        Rules:
            - 3+ consecutive successes for a fix -> boost confidence by 0.05 (max 1.0)
            - 2+ consecutive failures -> reduce confidence by 0.1 (min 0.3)
            - Mixed results -> no change (needs more data)
        """
        adjustments = []

        # Group by issue_type
        by_type = {}
        for outcome in all_outcomes:
            issue_type = outcome["issue_type"]
            if issue_type not in by_type:
                by_type[issue_type] = []
            by_type[issue_type].append(outcome)

        for issue_type, outcomes in by_type.items():
            # Sort by timestamp (newest last)
            outcomes.sort(key=lambda x: x.get("timestamp", ""))

            # Look at the last 5 outcomes
            recent = outcomes[-5:]
            successes = sum(1 for o in recent if o["success"])
            failures = len(recent) - successes

            if successes >= 3 and failures == 0:
                adjustments.append({
                    "issue_type": issue_type,
                    "action": "boost",
                    "delta": 0.05,
                    "reason": f"{successes} consecutive successes in last {len(recent)} runs",
                })
            elif failures >= 2 and successes == 0:
                adjustments.append({
                    "issue_type": issue_type,
                    "action": "reduce",
                    "delta": -0.1,
                    "reason": f"{failures} consecutive failures in last {len(recent)} runs",
                })

        return adjustments

    def _apply_confidence_adjustments(self, adjustments: List[Dict]):
        """Apply confidence adjustments to known_issues.json."""
        ki_file = self.kb_dir / "known_issues.json"
        if not ki_file.exists():
            return

        try:
            with open(ki_file, 'r') as f:
                known_issues = json.load(f)

            patterns = known_issues.get("patterns", [])
            modified = False

            for adj in adjustments:
                for pattern in patterns:
                    if pattern.get("type") == adj["issue_type"]:
                        old_confidence = pattern.get("learned_confidence", 0.9)
                        new_confidence = max(0.3, min(1.0, old_confidence + adj["delta"]))

                        if old_confidence != new_confidence:
                            pattern["learned_confidence"] = round(new_confidence, 2)
                            pattern["last_adjusted"] = datetime.now().isoformat()
                            pattern["adjustment_reason"] = adj["reason"]
                            modified = True

                            self.log(
                                f"Adjusted {adj['issue_type']} confidence: "
                                f"{old_confidence} -> {new_confidence} ({adj['reason']})",
                                "info"
                            )

            if modified:
                with open(ki_file, 'w') as f:
                    json.dump(known_issues, f, indent=2)
                    f.write('\n')
                self.log("Knowledge base updated with confidence adjustments", "success")

        except Exception as e:
            self.log(f"Failed to apply confidence adjustments: {e}", "error")

    def _append_outcomes(self):
        """Append session outcomes to the outcomes history file."""
        if not self.session_outcomes:
            return

        try:
            existing = []
            if self.outcomes_file.exists():
                with open(self.outcomes_file, 'r') as f:
                    existing = json.load(f)

            existing.extend(self.session_outcomes)

            # Keep last 500 outcomes to prevent unbounded growth
            if len(existing) > 500:
                existing = existing[-500:]

            with open(self.outcomes_file, 'w') as f:
                json.dump(existing, f, indent=2)
                f.write('\n')

            # Clear session outcomes after persisting to prevent
            # duplicate entries on subsequent end_of_run_summary() calls
            self.session_outcomes = []

        except Exception as e:
            self.log(f"Failed to persist outcomes: {e}", "error")

    def _load_all_outcomes(self) -> List[Dict]:
        """Load all historical outcomes."""
        try:
            if self.outcomes_file.exists():
                with open(self.outcomes_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.log(f"Failed to load outcomes history: {e}", "error")
        return []

    def _append_pending(self, suggestion: Dict):
        """Append a pending learning for human review."""
        try:
            existing = []
            if self.pending_file.exists():
                with open(self.pending_file, 'r') as f:
                    existing = json.load(f)

            existing.append(suggestion)

            with open(self.pending_file, 'w') as f:
                json.dump(existing, f, indent=2)
                f.write('\n')

        except Exception as e:
            self.log(f"Failed to persist pending learning: {e}", "error")

    def _get_pending_count(self) -> int:
        """Get count of pending learnings awaiting review."""
        try:
            if self.pending_file.exists():
                with open(self.pending_file, 'r') as f:
                    return len(json.load(f))
        except Exception:
            pass
        return 0

    def get_learning_stats(self) -> Dict:
        """Get overall learning statistics."""
        all_outcomes = self._load_all_outcomes()

        # Calculate overall success rate by fix type
        fix_stats = {}
        for outcome in all_outcomes:
            fix = outcome.get("recommended_fix", "unknown")
            if fix not in fix_stats:
                fix_stats[fix] = {"successes": 0, "failures": 0}
            if outcome["success"]:
                fix_stats[fix]["successes"] += 1
            else:
                fix_stats[fix]["failures"] += 1

        # Add success rate percentages
        for fix, stats in fix_stats.items():
            total = stats["successes"] + stats["failures"]
            stats["total"] = total
            stats["success_rate"] = f"{(stats['successes'] / total * 100):.0f}%" if total > 0 else "N/A"

        return {
            "total_outcomes": len(all_outcomes),
            "fix_stats": fix_stats,
            "pending_reviews": self._get_pending_count(),
        }
