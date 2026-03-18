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

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base_agent import BaseAgent


class DiagnosticAgent(BaseAgent):
    """Analyzes issues to determine root cause and fix strategy."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False):
        super().__init__("Diagnostic", base_dir, enabled, verbose)
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

        diagnosis_methods = {
            "rosanetwork_stuck_deletion": self._diagnose_stuck_rosanetwork,
            "cloudformation_deletion_failure": self._diagnose_cloudformation_failure,
            "ocm_auth_failure": self._diagnose_ocm_auth,
            "capi_not_installed": self._diagnose_capi_missing,
            "api_rate_limit": self._diagnose_rate_limit,
            "repeated_timeouts": self._diagnose_timeouts,
        }

        diagnostic_method = diagnosis_methods.get(issue_type)
        if diagnostic_method:
            diagnosis = diagnostic_method(context)
            self.current_diagnosis = diagnosis
            return diagnosis

        return self._diagnose_generic(issue_type, context)

    def _diagnose_stuck_rosanetwork(self, context: Dict) -> Dict:
        """Diagnose ROSANetwork stuck in deletion state."""
        self.log("Analyzing ROSANetwork deletion issue...", "debug")

        resource_name, namespace = self._extract_resource_info(context)
        resource_info = self._get_resource_info("rosanetwork", resource_name, namespace)

        diagnosis = {
            "issue_type": "rosanetwork_stuck_deletion",
            "root_cause": "ROSANetwork has finalizers preventing deletion",
            "severity": "high",
            "confidence": 0.9,
            "evidence": [],
            "recommended_fix": "remove_finalizers",
            "fix_parameters": {
                "resource_type": "rosanetwork",
                "resource_name": resource_name,
                "namespace": namespace,
            }
        }

        if resource_info:
            if resource_info.get("metadata", {}).get("deletionTimestamp"):
                diagnosis["evidence"].append("Resource has deletionTimestamp set")
                diagnosis["confidence"] = 0.95

            finalizers = resource_info.get("metadata", {}).get("finalizers", [])
            if finalizers:
                diagnosis["evidence"].append(f"Resource has {len(finalizers)} finalizer(s): {', '.join(finalizers)}")
                diagnosis["confidence"] = 1.0

            conditions = resource_info.get("status", {}).get("conditions", [])
            for condition in conditions:
                if "delete" in condition.get("type", "").lower():
                    diagnosis["evidence"].append(f"Status: {condition.get('type')} - {condition.get('message', 'N/A')}")
        else:
            diagnosis["confidence"] = 0.7
            diagnosis["evidence"].append(f"Could not retrieve resource info for {resource_name} in namespace {namespace}")
            self.log(f"WARNING: Could not get resource info for rosanetwork/{resource_name} in {namespace}", "warning")

        self.log(f"Diagnosis complete. Confidence: {diagnosis['confidence']}", "info")
        return diagnosis

    def _diagnose_cloudformation_failure(self, context: Dict) -> Dict:
        """Diagnose CloudFormation stack deletion failure."""
        self.log("Analyzing CloudFormation failure...", "debug")
        return {
            "issue_type": "cloudformation_deletion_failure",
            "root_cause": "CloudFormation stack failed to delete, likely due to orphaned resources",
            "severity": "high",
            "confidence": 0.8,
            "evidence": ["CloudFormation deletion failure detected in logs"],
            "recommended_fix": "manual_cloudformation_cleanup",
            "fix_parameters": {
                "action": "inspect_and_report",
                "message": "CloudFormation stack requires manual inspection and cleanup"
            }
        }

    def _diagnose_ocm_auth(self, context: Dict) -> Dict:
        """Diagnose OCM authentication failure."""
        self.log("Analyzing OCM authentication issue...", "debug")
        return {
            "issue_type": "ocm_auth_failure",
            "root_cause": "OCM credentials expired or invalid",
            "severity": "medium",
            "confidence": 0.85,
            "evidence": ["OCM authentication error in output"],
            "recommended_fix": "refresh_ocm_token",
            "fix_parameters": {
                "action": "retry_with_fresh_credentials"
            }
        }

    def _diagnose_capi_missing(self, context: Dict) -> Dict:
        """Diagnose CAPI/CAPA not installed or running."""
        self.log("Checking CAPI/CAPA installation...", "debug")

        capi_running = self._check_deployment("capi-controller-manager", "capi-system")
        capa_running = self._check_deployment("capa-controller-manager", "capa-system")

        evidence = []
        if not capi_running:
            evidence.append("CAPI controller not found in capi-system namespace")
        if not capa_running:
            evidence.append("CAPA controller not found in capa-system namespace")

        return {
            "issue_type": "capi_not_installed",
            "root_cause": "CAPI/CAPA controllers not installed or not running",
            "severity": "high",
            "confidence": 0.95,
            "evidence": evidence,
            "recommended_fix": "install_capi_capa",
            "fix_parameters": {
                "capi_installed": capi_running,
                "capa_installed": capa_running,
            }
        }

    def _diagnose_rate_limit(self, context: Dict) -> Dict:
        """Diagnose API rate limiting."""
        return {
            "issue_type": "api_rate_limit",
            "root_cause": "Hitting API rate limits (AWS/OCM/Kubernetes)",
            "severity": "low",
            "confidence": 0.9,
            "evidence": ["Rate limit error detected"],
            "recommended_fix": "backoff_and_retry",
            "fix_parameters": {
                "backoff_seconds": 60,
                "max_retries": 3
            }
        }

    def _diagnose_timeouts(self, context: Dict) -> Dict:
        """Diagnose repeated timeout issues."""
        return {
            "issue_type": "repeated_timeouts",
            "root_cause": "Operations timing out - resource may be stuck or slow",
            "severity": "medium",
            "confidence": 0.7,
            "evidence": ["Multiple timeout warnings in logs"],
            "recommended_fix": "increase_timeout_and_monitor",
            "fix_parameters": {
                "suggested_timeout_increase": "2x"
            }
        }

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

    def _get_resource_info(self, resource_type: str, resource_name: str, namespace: str) -> Optional[Dict]:
        """Get Kubernetes resource information via oc/kubectl."""
        try:
            cmd = ["oc", "get", resource_type, resource_name, "-n", namespace, "-o", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                self.log(f"Failed to get {resource_type}/{resource_name}: {result.stderr}", "debug")
                return None
        except subprocess.TimeoutExpired:
            self.log(f"Timeout getting {resource_type}/{resource_name}", "warning")
            return None
        except Exception as e:
            self.log(f"Error getting resource info: {e}", "error")
            return None

    def _check_deployment(self, deployment_name: str, namespace: str) -> bool:
        """Check if a deployment exists and is running."""
        try:
            cmd = ["oc", "get", "deployment", deployment_name, "-n", namespace]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def _extract_resource_info(self, context: Dict, resource_type: str = "rosanetwork") -> Tuple[str, str]:
        """
        Extract resource name and namespace from context.

        Priority order:
        1. Structured context fields (from #AGENT_CONTEXT markers)
        2. Explicit context fields (resource_name, namespace)
        3. Buffer parsing (oc/kubectl commands)
        4. Buffer parsing (output tables)
        5. Task name parsing (least reliable)

        Args:
            context: Context dictionary from monitoring agent
            resource_type: Kubernetes resource type to match in oc/kubectl commands

        Returns:
            Tuple of (resource_name, namespace)
        """
        resource_name = "unknown-cluster"
        namespace = "default"

        # 1. Check structured context from playbook markers (most reliable)
        if "resource_name" in context:
            resource_name = context["resource_name"]
        if "namespace" in context:
            namespace = context["namespace"]

        # If structured context gave us a real name, use it
        if resource_name != "unknown-cluster":
            self.log(f"Extracted from structured context: {resource_name} in {namespace}", "debug")
            return resource_name, namespace

        # 2. Parse buffer for oc/kubectl commands
        buffer = context.get("buffer", [])
        for line in buffer:
            oc_match = re.search(
                rf'(?:oc|kubectl)\s+(?:get|patch|delete)\s+{re.escape(resource_type)}\s+(\S+)\s+-n\s+(\S+)',
                line, re.IGNORECASE
            )
            if oc_match:
                resource_name = oc_match.group(1)
                namespace = oc_match.group(2)
                self.log(f"Extracted from oc command: {resource_name} in namespace {namespace}", "debug")
                return resource_name, namespace

        # 3. Parse buffer for output tables
        for i, line in enumerate(buffer):
            if "NAME" in line and "AGE" in line:
                if i + 1 < len(buffer):
                    next_line = buffer[i + 1].strip()
                    parts = next_line.split()
                    if parts:
                        resource_name = parts[0]
                        self.log(f"Extracted from output table: {resource_name}", "debug")
                        return resource_name, namespace

        # 4. Fallback: task name (least reliable)
        # Build a regex for the resource type (e.g., ROSANetwork, ROSAControlPlane)
        type_pattern = resource_type.replace("rosa", "ROSA", 1) if resource_type.startswith("rosa") else resource_type
        current_task = context.get("current_task", "")
        skip_words = {"deletion", "delete", "complete", "stuck", "if", "to", "for", "the", "in"}
        if current_task:
            task_match = re.search(rf'{type_pattern}\s+(\S+)', current_task, re.IGNORECASE)
            if task_match:
                candidate = task_match.group(1)
                if candidate.lower() not in skip_words and '-' in candidate:
                    resource_name = candidate
                    self.log(f"Extracted from task: {resource_name}", "debug")
                    return resource_name, namespace

        if resource_name == "unknown-cluster":
            self.log("WARNING: Could not extract resource name from context", "warning")
            self.log(f"Context available: task='{current_task}', buffer_lines={len(buffer)}", "debug")

        return resource_name, namespace

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
