"""
Remediation Agent
=================

Executes autonomous fixes for diagnosed issues.

This agent takes diagnosis results and executes appropriate remediation
strategies, including Kubernetes resource patching, credential refresh,
retry logic, and more.

Author: Tina Fitzgerald
Created: March 3, 2026
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

from .base_agent import BaseAgent


class RemediationAgent(BaseAgent):
    """Executes autonomous fixes for detected and diagnosed issues."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False, dry_run: bool = False,
                 kb_dir: Path = None):
        super().__init__("Remediation", base_dir, enabled, verbose, kb_dir=kb_dir)

        self.dry_run = dry_run
        self.fix_success_rate = {}

    def remediate(self, diagnosis: Dict) -> Tuple[bool, str]:
        """
        Execute remediation based on diagnosis.

        Args:
            diagnosis: Diagnosis dictionary from DiagnosticAgent

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.enabled:
            return False, "Remediation agent disabled"

        recommended_fix = diagnosis.get("recommended_fix")
        fix_params = diagnosis.get("fix_parameters", {})
        issue_type = diagnosis.get("issue_type")

        self.log(f"Executing fix: {recommended_fix}", "info")

        if self.dry_run:
            self.log(f"DRY RUN: Would execute {recommended_fix} with params {fix_params}", "warning")
            return True, f"DRY RUN: Fix would be applied: {recommended_fix}"

        # Route to specific fix method
        fix_method = self._get_fix_method(recommended_fix)
        if fix_method:
            try:
                success, message = fix_method(fix_params)

                # Record the fix attempt
                self.record_intervention(recommended_fix, {
                    "issue_type": issue_type,
                    "success": success,
                    "message": message,
                    "parameters": fix_params
                })

                # Update success rate
                if recommended_fix not in self.fix_success_rate:
                    self.fix_success_rate[recommended_fix] = {"successes": 0, "failures": 0}

                if success:
                    self.fix_success_rate[recommended_fix]["successes"] += 1
                    self.log(f"Fix applied successfully: {message}", "success")
                else:
                    self.fix_success_rate[recommended_fix]["failures"] += 1
                    self.log(f"Fix failed: {message}", "error")

                return success, message

            except Exception as e:
                error_msg = f"Exception during fix execution: {str(e)}"
                self.log(error_msg, "error")
                return False, error_msg

        return False, f"No fix method available for: {recommended_fix}"

    def _get_fix_method(self, fix_name: str):
        """Return the callable for a fix name.

        Override in domain subclasses to register domain-specific fix
        methods. Call ``super()._get_fix_method()`` as a fallback to
        include the core fixes.
        """
        core_methods = {
            "log_and_continue": self._fix_log_and_continue,
        }
        return core_methods.get(fix_name)

    def _fix_log_and_continue(self, params: Dict) -> Tuple[bool, str]:
        """Log issue and continue execution."""
        self.log("Issue logged for review - continuing execution", "info")
        return True, "Issue logged, test execution continues"

    def get_success_rate(self, fix_type: Optional[str] = None) -> Dict:
        """
        Get success rate statistics for fixes.

        Args:
            fix_type: Specific fix type, or None for all

        Returns:
            Dictionary with success rate statistics
        """
        if fix_type:
            stats = self.fix_success_rate.get(fix_type, {"successes": 0, "failures": 0})
            total = stats["successes"] + stats["failures"]
            rate = (stats["successes"] / total * 100) if total > 0 else 0
            return {
                "fix_type": fix_type,
                "successes": stats["successes"],
                "failures": stats["failures"],
                "total_attempts": total,
                "success_rate": f"{rate:.1f}%"
            }
        else:
            # Return all stats
            all_stats = {}
            for fix_name, stats in self.fix_success_rate.items():
                total = stats["successes"] + stats["failures"]
                rate = (stats["successes"] / total * 100) if total > 0 else 0
                all_stats[fix_name] = {
                    "successes": stats["successes"],
                    "failures": stats["failures"],
                    "total_attempts": total,
                    "success_rate": f"{rate:.1f}%"
                }
            return all_stats

