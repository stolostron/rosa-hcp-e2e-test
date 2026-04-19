"""
Diagnostic Agent
================

Analyzes detected issues to determine root cause and recommended fixes.

This agent performs deep analysis of issues detected by the monitoring agent,
querying Kubernetes resources, checking logs, and determining the best
remediation strategy.

Author: Tina Fitzgerald
Created: March 3, 2026
"""

from pathlib import Path
from typing import Dict, Optional

from .base_agent import BaseAgent


class DiagnosticAgent(BaseAgent):
    """Analyzes issues to determine root cause and fix strategy."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False, kb_dir: Path = None):
        super().__init__("Diagnostic", base_dir, enabled, verbose, kb_dir=kb_dir)
        self.current_diagnosis = None

    def diagnose(self, issue_type: str, context: Dict) -> Optional[Dict]:
        """
        Diagnose an issue and return recommended fix.

        Args:
            issue_type: Type of issue detected
            context: Context from monitoring agent (may include structured fields)

        Returns:
            Diagnosis dictionary with recommended fix
        """
        if not self.enabled:
            return None

        self.log(f"Diagnosing: {issue_type}", "info")

        diagnosis = self._diagnose_issue(issue_type, context)
        if diagnosis is None:
            diagnosis = self._diagnose_generic(issue_type, context)

        diagnosis = self._apply_learned_confidence(diagnosis)
        self.current_diagnosis = diagnosis
        return diagnosis

    def _diagnose_issue(self, issue_type: str, context: Dict) -> Optional[Dict]:
        """Dispatch to domain-specific diagnosis method.

        Override in domain subclasses to provide domain-specific diagnosis.
        Return None to fall through to _diagnose_generic().
        """
        return None

    def _apply_learned_confidence(self, diagnosis: Dict) -> Dict:
        """Apply learned confidence adjustment from the knowledge base.

        If the learning agent has recorded a learned_confidence for this
        issue type, blend it with the diagnostic confidence. The learned
        value acts as a nudge — it can boost or reduce confidence by up
        to 0.1 from the diagnostic value, but never override it entirely.
        """
        issue_type = diagnosis.get("issue_type")
        if not issue_type:
            return diagnosis

        patterns = self.known_issues.get("patterns", [])
        for pattern in patterns:
            if pattern.get("type") == issue_type and "learned_confidence" in pattern:
                learned = pattern["learned_confidence"]
                original = diagnosis.get("confidence", 0.5)

                # Nudge toward learned value, capped at ±0.1
                delta = max(-0.1, min(0.1, learned - original))
                adjusted = max(0.0, min(1.0, round(original + delta, 2)))

                if adjusted != original:
                    diagnosis["confidence"] = adjusted
                    diagnosis.setdefault("evidence", []).append(
                        f"Confidence adjusted {original} -> {adjusted} (learned from {pattern.get('adjustment_reason', 'historical outcomes')})"
                    )
                    self.log(f"Learned confidence adjustment for {issue_type}: {original} -> {adjusted}", "debug")
                break

        return diagnosis

    def _diagnose_generic(self, issue_type: str, context: Dict) -> Dict:
        """Generic diagnosis for unknown issue types."""
        return {
            "issue_type": issue_type,
            "root_cause": "Unknown - requires manual investigation",
            "severity": "medium",
            "confidence": 0.3,
            "evidence": ["Issue detected but no specific diagnostic available"],
            "recommended_fix": "log_and_continue",
            "fix_parameters": {}
        }

    def get_diagnosis_summary(self) -> Optional[str]:
        """Get human-readable summary of current diagnosis."""
        if not self.current_diagnosis:
            return None

        diag = self.current_diagnosis
        evidence_lines = '\n'.join(f'    - {e}' for e in diag['evidence'])
        return (
            f"Diagnosis Summary:\n"
            f"  Issue: {diag['issue_type']}\n"
            f"  Root Cause: {diag['root_cause']}\n"
            f"  Severity: {diag['severity']}\n"
            f"  Confidence: {diag['confidence'] * 100:.0f}%\n"
            f"  Recommended Fix: {diag['recommended_fix']}\n"
            f"  Evidence:\n{evidence_lines}\n"
        )
