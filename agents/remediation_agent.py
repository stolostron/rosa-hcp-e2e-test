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

import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .base_agent import BaseAgent


class RemediationAgent(BaseAgent):
    """Executes autonomous fixes for detected and diagnosed issues."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False, dry_run: bool = False):
        super().__init__("Remediation", base_dir, enabled, verbose)

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
        fix_methods = {
            "remove_finalizers": self._fix_remove_finalizers,
            "refresh_ocm_token": self._fix_refresh_ocm_token,
            "backoff_and_retry": self._fix_backoff_retry,
            "cleanup_vpc_dependencies": self._fix_cleanup_vpc_dependencies,
            "manual_cloudformation_cleanup": self._fix_cloudformation_manual,
            "install_capi_capa": self._fix_install_capi,
            "increase_timeout_and_monitor": self._fix_increase_timeout,
            "log_and_continue": self._fix_log_and_continue,
        }

        fix_method = fix_methods.get(recommended_fix)
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

    def _fix_remove_finalizers(self, params: Dict) -> Tuple[bool, str]:
        """Remove finalizers from stuck resource."""
        resource_type = params.get("resource_type")
        resource_name = params.get("resource_name")
        namespace = params.get("namespace", "default")

        self.log(f"Removing finalizers from {resource_type}/{resource_name}", "info")

        try:
            # Patch resource to remove finalizers
            cmd = [
                "oc", "patch", resource_type, resource_name,
                "-n", namespace,
                "--type=merge",
                "-p", '{"metadata":{"finalizers":null}}'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return True, f"Successfully removed finalizers from {resource_type}/{resource_name}"
            else:
                return False, f"Failed to remove finalizers: {result.stderr}"

        except subprocess.TimeoutExpired:
            return False, "Timeout while removing finalizers"
        except Exception as e:
            return False, f"Error removing finalizers: {str(e)}"

    def _fix_refresh_ocm_token(self, params: Dict) -> Tuple[bool, str]:
        """Refresh OCM authentication token."""
        self.log("Refreshing OCM token", "info")

        # This would integrate with OCM credential refresh logic
        # For now, we log that intervention is needed
        return False, "OCM token refresh requires manual intervention - credentials need to be updated"

    def _fix_backoff_retry(self, params: Dict) -> Tuple[bool, str]:
        """Recommend backoff for rate limiting (advisory, non-blocking)."""
        backoff_seconds = params.get("backoff_seconds", 60)
        max_retries = params.get("max_retries", 3)

        self.log(f"Rate limit detected: recommend {backoff_seconds}s backoff before retry", "info")

        # Advisory only — don't block the output stream, which would
        # cause Jenkins to think the process is hung.
        return True, f"Rate limit advisory: wait {backoff_seconds}s before retrying (max {max_retries} retries)"

    def _fix_cleanup_vpc_dependencies(self, params: Dict) -> Tuple[bool, str]:
        """
        Clean up orphaned VPC dependencies blocking deletion.

        This automatically identifies and removes:
        - Orphaned ENIs (Elastic Network Interfaces)
        - Security groups tagged with the ROSA HCP cluster ID
        - Other VPC attachments blocking deletion
        """
        vpc_id = params.get("vpc_id")
        cluster_id = params.get("cluster_id")  # ROSA HCP cluster ID for filtering
        region = params.get("region", "us-west-2")

        if not vpc_id:
            return False, "VPC ID is required for cleanup"

        if not cluster_id:
            return False, "Cluster ID is required for cleanup (to prevent deleting resources from other clusters in shared VPCs)"

        self.log(f"Cleaning up VPC dependencies for {vpc_id} in {region}", "info")
        self.log(f"Filtering resources by cluster ID: {cluster_id}", "info")

        outputs = []
        cleanup_count = 0
        sg_cleanup_count = 0

        try:
            # Step 1: Find orphaned ENIs tagged with cluster ID
            self.log("Searching for orphaned ENIs...", "info")
            cmd = [
                "aws", "ec2", "describe-network-interfaces",
                "--region", region,
                "--filters",
                f"Name=vpc-id,Values={vpc_id}",
                f"Name=tag:cluster.x-k8s.io/cluster-name,Values={cluster_id}",
                "--query", "NetworkInterfaces[*].[NetworkInterfaceId,Attachment.AttachmentId,Status,Description]",
                "--output", "text"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout.strip():
                enis = result.stdout.strip().split('\n')
                outputs.append(f"Found {len(enis)} ENI(s) in VPC")

                for eni_line in enis:
                    parts = eni_line.split('\t')
                    if len(parts) >= 3:
                        eni_id = parts[0]
                        attachment_id = parts[1] if len(parts) > 1 else None
                        status = parts[2] if len(parts) > 2 else "unknown"
                        description = parts[3] if len(parts) > 3 else ""

                        # Skip ENIs that are in-use by critical services
                        if "lambda" in description.lower() or "rds" in description.lower():
                            outputs.append(f"  Skipping {eni_id}: {description} (managed service)")
                            continue

                        # Detach if attached
                        if attachment_id and attachment_id != "None":
                            detach_cmd = [
                                "aws", "ec2", "detach-network-interface",
                                "--region", region,
                                "--attachment-id", attachment_id,
                                "--force"
                            ]
                            detach_result = subprocess.run(detach_cmd, capture_output=True, text=True, timeout=30)
                            if detach_result.returncode == 0:
                                outputs.append(f"  Detached ENI {eni_id}")
                                time.sleep(2)  # Wait for detachment

                        # Delete ENI if available
                        if status == "available" or attachment_id == "None":
                            delete_cmd = [
                                "aws", "ec2", "delete-network-interface",
                                "--region", region,
                                "--network-interface-id", eni_id
                            ]
                            delete_result = subprocess.run(delete_cmd, capture_output=True, text=True, timeout=30)
                            if delete_result.returncode == 0:
                                outputs.append(f"  Deleted ENI {eni_id}")
                                cleanup_count += 1
                            else:
                                outputs.append(f"  FAILED to delete ENI {eni_id}: {delete_result.stderr}")
            else:
                outputs.append("No orphaned ENIs found")

            # Step 2: Clean up security groups tagged with cluster ID
            self.log("Checking security groups...", "info")

            # Build filters for security groups (always filter by cluster ID)
            sg_filters = [
                f"Name=vpc-id,Values={vpc_id}",
                f"Name=tag:red-hat-clustertype,Values={cluster_id}"
            ]

            sg_cmd = [
                "aws", "ec2", "describe-security-groups",
                "--region", region,
                "--filters"
            ] + sg_filters + [
                "--query", "SecurityGroups[?GroupName!='default'].[GroupId,GroupName,Tags]",
                "--output", "json"
            ]

            sg_result = subprocess.run(sg_cmd, capture_output=True, text=True, timeout=30)

            if sg_result.returncode == 0 and sg_result.stdout.strip():
                sgs = json.loads(sg_result.stdout)

                if sgs:
                    outputs.append(f"Found {len(sgs)} security group(s) for cluster {cluster_id}")

                    for sg_data in sgs:
                        sg_id = sg_data[0]
                        sg_name = sg_data[1]

                        # Attempt to delete the security group
                        delete_sg_cmd = [
                            "aws", "ec2", "delete-security-group",
                            "--region", region,
                            "--group-id", sg_id
                        ]

                        delete_sg_result = subprocess.run(delete_sg_cmd, capture_output=True, text=True, timeout=30)
                        if delete_sg_result.returncode == 0:
                            outputs.append(f"  Deleted security group {sg_id} ({sg_name})")
                            sg_cleanup_count += 1
                        else:
                            # Security group might have dependencies, log but continue
                            error_msg = delete_sg_result.stderr.strip()
                            if "DependencyViolation" in error_msg:
                                outputs.append(f"  SKIPPED security group {sg_id} ({sg_name}) has dependencies, will be cleaned by CloudFormation")
                            else:
                                outputs.append(f"  FAILED to delete security group {sg_id}: {error_msg}")
                else:
                    outputs.append("No security groups found matching criteria")
            else:
                outputs.append("No security groups found")

            summary = f"VPC cleanup completed: {cleanup_count} ENI(s) removed, {sg_cleanup_count} security group(s) deleted"
            full_output = "\n".join(outputs)

            self.log(summary, "success" if cleanup_count > 0 else "info")

            return True, f"{summary}\n\nDetails:\n{full_output}"

        except subprocess.TimeoutExpired:
            return False, "Timeout while cleaning up VPC dependencies"
        except Exception as e:
            return False, f"Error during VPC cleanup: {str(e)}"

    def _fix_cloudformation_manual(self, params: Dict) -> Tuple[bool, str]:
        """Handle CloudFormation issues requiring manual intervention."""
        self.log("CloudFormation issue requires manual cleanup", "warning")

        message = params.get("message", "CloudFormation stack requires manual inspection")

        # Log the issue prominently for operator attention
        self.log(f"MANUAL INTERVENTION REQUIRED: {message}", "warning")

        # Continue test execution but flag for review
        return True, f"Logged for manual review: {message}"

    def _fix_install_capi(self, params: Dict) -> Tuple[bool, str]:
        """Install or verify CAPI/CAPA installation."""
        self.log("CAPI/CAPA installation check/fix", "info")

        capi_installed = params.get("capi_installed", False)
        capa_installed = params.get("capa_installed", False)

        if not capi_installed and not capa_installed:
            return False, "CAPI/CAPA not installed - requires manual installation via test suite 10-configure-mce-environment"
        elif not capi_installed:
            return False, "CAPI controller not found - check capi-system namespace"
        elif not capa_installed:
            return False, "CAPA controller not found - check capa-system namespace"

        return True, "CAPI/CAPA installation verified"

    def _fix_increase_timeout(self, params: Dict) -> Tuple[bool, str]:
        """Suggest timeout increase for slow operations."""
        suggested_increase = params.get("suggested_timeout_increase", "2x")

        self.log(f"Timeout issue detected - suggest increasing timeout by {suggested_increase}", "warning")

        # Log recommendation
        return True, f"Recommend increasing timeout by {suggested_increase} for this operation"

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

