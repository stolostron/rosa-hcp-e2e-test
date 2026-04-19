"""
ROSA HCP Diagnostic Agent
==========================

Domain-specific diagnosis methods for ROSA HCP test automation.
Handles CloudFormation, VPC, ROSA cluster, and CAPI/CAPA diagnostics.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...diagnostic_agent import DiagnosticAgent


class RosaHcpDiagnosticAgent(DiagnosticAgent):
    """DiagnosticAgent with ROSA HCP-specific diagnosis methods."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False, kb_dir: Path = None):
        if kb_dir is None:
            kb_dir = Path(__file__).parent / "knowledge_base"
        super().__init__(base_dir, enabled, verbose, kb_dir=kb_dir)

    def _diagnose_issue(self, issue_type: str, context: Dict) -> Optional[Dict]:
        diagnosis_methods = {
            "rosanetwork_stuck_deletion": self._diagnose_stuck_rosanetwork,
            "rosacontrolplane_stuck_deletion": self._diagnose_stuck_rosacontrolplane,
            "rosaroleconfig_stuck_deletion": self._diagnose_stuck_rosaroleconfig,
            "cloudformation_deletion_failure": self._diagnose_cloudformation_failure,
            "ocm_auth_failure": self._diagnose_ocm_auth,
            "capi_not_installed": self._diagnose_capi_missing,
            "api_rate_limit": self._diagnose_rate_limit,
            "repeated_timeouts": self._diagnose_timeouts,
        }

        diagnostic_method = diagnosis_methods.get(issue_type)
        if diagnostic_method:
            return diagnostic_method(context)
        return None

    def _diagnose_stuck_resource(self, context: Dict, resource_type: str, issue_type: str) -> Dict:
        self.log(f"Analyzing {resource_type} deletion issue...", "debug")

        resource_name, namespace = self._extract_resource_info(context, resource_type)
        resource_info = self._get_resource_info(resource_type, resource_name, namespace)

        diagnosis = {
            "issue_type": issue_type,
            "root_cause": f"{resource_type} has finalizers preventing deletion",
            "severity": "high",
            "confidence": 0.9,
            "evidence": [],
            "recommended_fix": "remove_finalizers",
            "fix_parameters": {
                "resource_type": resource_type,
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
            self.log(f"WARNING: Could not get resource info for {resource_type}/{resource_name} in {namespace}", "warning")

        self.log(f"Diagnosis complete. Confidence: {diagnosis['confidence']}", "info")
        return diagnosis

    def _diagnose_stuck_rosanetwork(self, context: Dict) -> Dict:
        resource_name, namespace = self._extract_resource_info(context, "rosanetwork")
        resource_info = self._get_resource_info("rosanetwork", resource_name, namespace)

        stack_name = None
        if resource_info:
            stack_name = resource_info.get("status", {}).get("stackName")
            if not stack_name:
                stack_name = resource_info.get("spec", {}).get("stackName")
            if not stack_name:
                stack_name = f"{resource_name.replace('-network', '')}-rosa-network-stack"

        cfn_status = self._get_cloudformation_stack_status(stack_name, resource_info)

        if cfn_status == "DELETE_IN_PROGRESS":
            vpc_id = self._get_stack_vpc_id(stack_name, resource_info)
            blockers, still_transitioning = self._check_vpc_blocking_dependencies(vpc_id, resource_info) if vpc_id else ([], True)

            if blockers and not still_transitioning:
                self.log(
                    f"CloudFormation stack {stack_name} DELETE_IN_PROGRESS with "
                    f"blocking VPC dependencies: {blockers}", "warning"
                )
                return {
                    "issue_type": "rosanetwork_stuck_deletion",
                    "root_cause": "CloudFormation stack stuck in DELETE_IN_PROGRESS due to ROSA-created VPC dependencies",
                    "severity": "high",
                    "confidence": 0.95,
                    "evidence": [
                        f"CloudFormation stack {stack_name} status: DELETE_IN_PROGRESS",
                        f"Blocking VPC dependencies found: {', '.join(blockers)}",
                    ],
                    "recommended_fix": "retry_cloudformation_delete",
                    "fix_parameters": {
                        "stack_name": stack_name,
                        "region": resource_info.get("spec", {}).get("region", "us-west-2") if resource_info else "us-west-2",
                        "resource_name": resource_name,
                        "namespace": namespace,
                    }
                }

            reason = "resources still transitioning" if still_transitioning else "no blocking dependencies"
            self.log(f"CloudFormation stack {stack_name} is DELETE_IN_PROGRESS — {reason}", "info")
            return {
                "issue_type": "rosanetwork_stuck_deletion",
                "root_cause": "CloudFormation stack is still being deleted by AWS — no intervention needed",
                "severity": "low",
                "confidence": 0.5,
                "evidence": [f"CloudFormation stack {stack_name} status: DELETE_IN_PROGRESS"],
                "recommended_fix": "log_and_continue",
                "fix_parameters": {}
            }
        elif cfn_status == "DELETE_FAILED":
            self.log(f"CloudFormation stack {stack_name} DELETE_FAILED — retrying", "warning")
            return {
                "issue_type": "rosanetwork_stuck_deletion",
                "root_cause": "CloudFormation stack deletion failed, blocking ROSANetwork cleanup",
                "severity": "high",
                "confidence": 0.95,
                "evidence": [f"CloudFormation stack {stack_name} status: DELETE_FAILED"],
                "recommended_fix": "retry_cloudformation_delete",
                "fix_parameters": {
                    "stack_name": stack_name,
                    "region": resource_info.get("spec", {}).get("region", "us-west-2") if resource_info else "us-west-2",
                    "resource_name": resource_name,
                    "namespace": namespace,
                }
            }
        elif cfn_status == "GONE":
            self.log(f"CloudFormation stack {stack_name} is gone — removing finalizers", "info")
            return self._diagnose_stuck_resource(context, "rosanetwork", "rosanetwork_stuck_deletion")
        else:
            self.log(
                f"CloudFormation stack {stack_name} status: {cfn_status} — "
                f"cannot confirm stack is gone, NOT removing finalizers", "warning"
            )
            return {
                "issue_type": "rosanetwork_stuck_deletion",
                "root_cause": f"CloudFormation stack status is {cfn_status} — cannot safely remove finalizers without confirming stack cleanup",
                "severity": "medium",
                "confidence": 0.4,
                "evidence": [
                    f"CloudFormation stack {stack_name} status: {cfn_status}",
                    "aws CLI may not be available — cannot verify stack deletion status",
                ],
                "recommended_fix": "log_and_continue",
                "fix_parameters": {}
            }

    def _get_cloudformation_stack_status(self, stack_name: str, resource_info: Dict = None) -> str:
        if not stack_name:
            return "UNKNOWN"

        if resource_info:
            k8s_stack_status = resource_info.get("status", {}).get("stackStatus")
            if k8s_stack_status:
                self.log(f"CloudFormation status from K8s resource: {k8s_stack_status}", "debug")
                return k8s_stack_status

        region = "us-west-2"
        if resource_info:
            region = resource_info.get("spec", {}).get("region", region)

        try:
            cmd = [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].StackStatus",
                "--output", "text"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                if "does not exist" in result.stderr:
                    return "GONE"
                return "UNKNOWN"
        except subprocess.TimeoutExpired:
            self.log("Timeout checking CloudFormation stack status", "warning")
            return "UNKNOWN"
        except Exception as e:
            self.log(f"Error checking CloudFormation stack: {e}", "error")
            return "UNKNOWN"

    def _get_stack_vpc_id(self, stack_name: str, resource_info: Dict = None) -> Optional[str]:
        region = "us-west-2"
        if resource_info:
            region = resource_info.get("spec", {}).get("region", region)
        try:
            cmd = [
                "aws", "cloudformation", "list-stack-resources",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "StackResourceSummaries[?ResourceType=='AWS::EC2::VPC'].PhysicalResourceId",
                "--output", "text"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            vpc_id = result.stdout.strip() if result.returncode == 0 else None
            if vpc_id and vpc_id.startswith("vpc-"):
                return vpc_id
            return None
        except Exception as e:
            self.log(f"Error getting VPC ID from stack: {e}", "error")
            return None

    def _check_vpc_blocking_dependencies(self, vpc_id: str, resource_info: Dict = None) -> tuple:
        region = "us-west-2"
        if resource_info:
            region = resource_info.get("spec", {}).get("region", region)

        blockers = []
        still_transitioning = False
        try:
            sg_cmd = [
                "aws", "ec2", "describe-security-groups",
                "--region", region,
                "--filters", f"Name=vpc-id,Values={vpc_id}",
                "--query", "SecurityGroups[?GroupName!='default'].[GroupId,GroupName]",
                "--output", "text"
            ]
            sg_result = subprocess.run(sg_cmd, capture_output=True, text=True, timeout=10)
            if sg_result.returncode == 0 and sg_result.stdout.strip():
                for line in sg_result.stdout.strip().split('\n'):
                    parts = line.split('\t')
                    sg_id = parts[0] if parts else "unknown"
                    sg_name = parts[1] if len(parts) > 1 else "unknown"
                    blockers.append(f"SG {sg_id} ({sg_name})")

            vpce_cmd = [
                "aws", "ec2", "describe-vpc-endpoints",
                "--region", region,
                "--filters", f"Name=vpc-id,Values={vpc_id}",
                "--query", "VpcEndpoints[?State!='deleted'].[VpcEndpointId,State]",
                "--output", "text"
            ]
            vpce_result = subprocess.run(vpce_cmd, capture_output=True, text=True, timeout=10)
            if vpce_result.returncode == 0 and vpce_result.stdout.strip():
                for line in vpce_result.stdout.strip().split('\n'):
                    parts = line.split('\t')
                    vpce_id = parts[0] if parts else "unknown"
                    vpce_state = parts[1] if len(parts) > 1 else "unknown"
                    blockers.append(f"VPC endpoint {vpce_id} ({vpce_state})")
                    if vpce_state in ("deleting", "pending"):
                        still_transitioning = True

        except Exception as e:
            self.log(f"Error checking VPC dependencies: {e}", "error")

        return blockers, still_transitioning

    def _diagnose_stuck_rosacontrolplane(self, context: Dict) -> Dict:
        resource_name, namespace = self._extract_resource_info(context, "rosacontrolplane")

        rosa_status = self._get_rosa_cluster_status(resource_name)

        if rosa_status == "gone":
            self.log(f"ROSA cluster {resource_name} is fully gone — safe to remove finalizers", "info")
            result = self._diagnose_stuck_resource(context, "rosacontrolplane", "rosacontrolplane_stuck_deletion")
            result["root_cause"] = "ROSA cluster fully removed — cleaning up remaining K8s resource"
            return result
        else:
            self.log(
                f"ROSA cluster {resource_name} is still {rosa_status} — "
                f"waiting for ROSA to finish before removing finalizers", "info"
            )
            return {
                "issue_type": "rosacontrolplane_stuck_deletion",
                "root_cause": f"ROSA cluster is still {rosa_status} — waiting for full removal",
                "severity": "low",
                "confidence": 0.5,
                "evidence": [f"rosa describe cluster shows state: {rosa_status}"],
                "recommended_fix": "log_and_continue",
                "fix_parameters": {}
            }

    def _get_rosa_cluster_status(self, cluster_name: str) -> str:
        try:
            cmd = ["rosa", "describe", "cluster", "--cluster", cluster_name, "-o", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                stderr = result.stderr.lower()
                if "not found" in stderr or "there is no cluster" in stderr:
                    return "gone"
                return "unknown"
            import json as _json
            cluster_info = _json.loads(result.stdout)
            state = cluster_info.get("status", {}).get("state", "unknown")
            return state
        except subprocess.TimeoutExpired:
            self.log("Timeout checking ROSA cluster status", "warning")
            return "unknown"
        except Exception as e:
            self.log(f"Error checking ROSA cluster status: {e}", "error")
            return "unknown"

    def _diagnose_stuck_rosaroleconfig(self, context: Dict) -> Dict:
        return self._diagnose_stuck_resource(context, "rosaroleconfig", "rosaroleconfig_stuck_deletion")

    def _diagnose_cloudformation_failure(self, context: Dict) -> Dict:
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

    def _extract_resource_info(self, context: Dict, resource_type: str = "rosanetwork") -> Tuple[str, str]:
        resource_name = "unknown-cluster"
        namespace = "default"

        if "resource_name" in context:
            resource_name = context["resource_name"]
        if "namespace" in context:
            namespace = context["namespace"]

        if resource_name != "unknown-cluster":
            self.log(f"Extracted from structured context: {resource_name} in {namespace}", "debug")
            return resource_name, namespace

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

        for i, line in enumerate(buffer):
            if "NAME" in line and "AGE" in line:
                if i + 1 < len(buffer):
                    next_line = buffer[i + 1].strip()
                    parts = next_line.split()
                    if parts:
                        resource_name = parts[0]
                        self.log(f"Extracted from output table: {resource_name}", "debug")
                        return resource_name, namespace

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

    def _get_resource_info(self, resource_type: str, resource_name: str, namespace: str) -> Optional[Dict]:
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
        try:
            cmd = ["oc", "get", "deployment", deployment_name, "-n", namespace]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False
