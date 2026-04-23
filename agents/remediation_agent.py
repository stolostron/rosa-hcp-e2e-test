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

import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .base_agent import BaseAgent
from .aws_client import AWSClient


class RemediationAgent(BaseAgent):
    """Executes autonomous fixes for detected and diagnosed issues."""

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False, dry_run: bool = False):
        super().__init__("Remediation", base_dir, enabled, verbose)

        self.dry_run = dry_run
        self.fix_success_rate = {}
        self._aws = None

    def _get_aws_client(self, region: str = "us-west-2") -> AWSClient:
        if self._aws is None or self._aws.region != region:
            self._aws = AWSClient(region=region, log_fn=self.log)
        return self._aws

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
            "retry_cloudformation_delete": self._fix_retry_cloudformation_delete,
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
            elif "NotFound" in result.stderr or "not found" in result.stderr.lower():
                # Resource is already gone — that's a success (deletion completed on its own)
                return True, f"Resource {resource_type}/{resource_name} already deleted (no finalizer removal needed)"
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
        cluster_id = params.get("cluster_id")
        region = params.get("region", "us-west-2")

        if not vpc_id:
            return False, "VPC ID is required for cleanup"

        if not cluster_id:
            return False, "Cluster ID is required for cleanup (to prevent deleting resources from other clusters in shared VPCs)"

        self.log(f"Cleaning up VPC dependencies for {vpc_id} in {region}", "info")
        self.log(f"Filtering resources by cluster ID: {cluster_id}", "info")

        aws = self._get_aws_client(region)
        if not aws.available:
            return False, "No AWS access available (neither aws CLI nor boto3)"

        outputs = []
        cleanup_count = 0
        sg_cleanup_count = 0

        try:
            # Step 1: Find orphaned ENIs tagged with cluster ID
            self.log("Searching for orphaned ENIs...", "info")
            enis = aws.describe_network_interfaces(vpc_id, cluster_id=cluster_id)

            if enis:
                outputs.append(f"Found {len(enis)} ENI(s) in VPC")
                for eni in enis:
                    eni_id = eni["id"]
                    attachment_id = eni["attachment_id"]
                    status = eni["status"]
                    description = eni["description"]

                    if "lambda" in description.lower() or "rds" in description.lower():
                        outputs.append(f"  Skipping {eni_id}: {description} (managed service)")
                        continue

                    if attachment_id:
                        ok, msg = aws.detach_network_interface(attachment_id)
                        if ok:
                            outputs.append(f"  Detached ENI {eni_id}")
                            time.sleep(2)

                    if status == "available" or not attachment_id:
                        ok, msg = aws.delete_network_interface(eni_id)
                        if ok:
                            outputs.append(f"  Deleted ENI {eni_id}")
                            cleanup_count += 1
                        else:
                            outputs.append(f"  FAILED to delete ENI {eni_id}: {msg}")
            else:
                outputs.append("No orphaned ENIs found")

            # Step 2: Clean up security groups tagged with cluster ID
            self.log("Checking security groups...", "info")
            sgs = aws.describe_security_groups(vpc_id, cluster_id=cluster_id)

            if sgs:
                outputs.append(f"Found {len(sgs)} security group(s) for cluster {cluster_id}")
                for sg in sgs:
                    ok, msg = aws.delete_security_group(sg["id"])
                    if ok:
                        outputs.append(f"  Deleted security group {sg['id']} ({sg['name']})")
                        sg_cleanup_count += 1
                    elif "DependencyViolation" in msg:
                        outputs.append(f"  SKIPPED security group {sg['id']} ({sg['name']}) has dependencies, will be cleaned by CloudFormation")
                    else:
                        outputs.append(f"  FAILED to delete security group {sg['id']}: {msg}")
            else:
                outputs.append("No security groups found matching criteria")

            summary = f"VPC cleanup completed: {cleanup_count} ENI(s) removed, {sg_cleanup_count} security group(s) deleted"
            full_output = "\n".join(outputs)

            self.log(summary, "success" if cleanup_count > 0 else "info")

            return True, f"{summary}\n\nDetails:\n{full_output}"

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

    def _fix_retry_cloudformation_delete(self, params: Dict) -> Tuple[bool, str]:
        """Retry a failed CloudFormation stack deletion.

        When a CloudFormation stack is in DELETE_FAILED state, this method:
        1. Checks for VPC dependencies blocking deletion
        2. Cleans up orphaned ENIs/security groups if found
        3. Retries the stack deletion
        """
        stack_name = params.get("stack_name")
        region = params.get("region", "us-west-2")

        if not stack_name:
            return False, "Stack name is required for CloudFormation retry"

        self.log(f"Retrying CloudFormation stack deletion: {stack_name}", "info")

        aws = self._get_aws_client(region)
        if not aws.available:
            return False, "No AWS access available (neither aws CLI nor boto3)"

        try:
            stack_status = aws.describe_stack_status(stack_name)

            if stack_status == "GONE":
                return True, f"CloudFormation stack {stack_name} already deleted"
            if stack_status == "UNAVAILABLE":
                return False, "Could not check stack status — no AWS access"
            if stack_status not in ("DELETE_IN_PROGRESS", "DELETE_FAILED"):
                return False, f"Stack {stack_name} in unexpected state: {stack_status}"

            cleanup_details = []
            cleanup_errors = []

            vpc_id = aws.get_vpc_from_stack(stack_name)

            if vpc_id:
                self.log(f"Cleaning up VPC {vpc_id} dependencies before retry", "info")

                # Delete VPC endpoints FIRST — they create ela-attach ENIs
                # that cannot be manually detached
                endpoints = aws.describe_vpc_endpoints(vpc_id)
                vpce_ids = [ep["id"] for ep in endpoints]
                if vpce_ids:
                    self.log(f"Deleting {len(vpce_ids)} VPC endpoint(s)", "info")
                    ok, msg = aws.delete_vpc_endpoints(vpce_ids)
                    if ok:
                        cleanup_details.append(msg)
                    else:
                        cleanup_errors.append(msg)
                    self.log("Waiting 20s for ENIs to release after VPC endpoint deletion", "info")
                    time.sleep(20)

                # Delete any remaining ENIs
                enis = aws.describe_network_interfaces(vpc_id)
                for eni in enis:
                    if eni["attachment_id"]:
                        ok, msg = aws.detach_network_interface(eni["attachment_id"])
                        if not ok:
                            cleanup_errors.append(f"Failed to detach ENI {eni['id']}: {msg}")
                        time.sleep(2)
                    ok, msg = aws.delete_network_interface(eni["id"])
                    if ok:
                        cleanup_details.append(f"Deleted ENI {eni['id']}")
                    else:
                        cleanup_errors.append(f"Failed to delete ENI {eni['id']}: {msg}")

                # Delete non-default security groups
                for sg in aws.describe_security_groups_text(vpc_id):
                    ok, msg = aws.delete_security_group(sg["id"])
                    if ok:
                        cleanup_details.append(f"Deleted security group {sg['id']} ({sg['name']})")
                        self.log(f"Deleted orphaned security group {sg['id']} ({sg['name']})", "info")
                    else:
                        cleanup_errors.append(f"Failed to delete SG {sg['id']}: {msg}")

                # Delete any remaining subnets
                for subnet_id in aws.describe_subnets(vpc_id):
                    ok, msg = aws.delete_subnet(subnet_id)
                    if ok:
                        cleanup_details.append(msg)
                    else:
                        cleanup_errors.append(msg)

                # Detach and delete internet gateways
                for igw_id in aws.describe_internet_gateways(vpc_id):
                    aws.detach_internet_gateway(igw_id, vpc_id)
                    ok, msg = aws.delete_internet_gateway(igw_id)
                    if ok:
                        cleanup_details.append(msg)
                    else:
                        cleanup_errors.append(msg)

                if cleanup_details:
                    self.log(f"VPC cleanup: {'; '.join(cleanup_details)}", "info")
                if cleanup_errors:
                    self.log(f"VPC cleanup errors: {'; '.join(cleanup_errors)}", "warning")

            if stack_status == "DELETE_FAILED":
                ok, msg = aws.delete_stack(stack_name)
                if not ok:
                    return False, f"Failed to retry stack deletion: {msg}"

                # Verify the stack transitioned (delete-stack is async)
                time.sleep(5)
                recheck_status = aws.describe_stack_status(stack_name)
                if recheck_status == "DELETE_FAILED":
                    self.log(f"Stack {stack_name} immediately re-entered DELETE_FAILED after retry", "warning")
                    return False, f"Stack {stack_name} re-entered DELETE_FAILED — dependencies may still exist"

            cleanup_summary = f"; {'; '.join(cleanup_details)}" if cleanup_details else ""
            return True, f"Cleaned up VPC dependencies for {stack_name}{cleanup_summary}"

        except Exception as e:
            return False, f"Error retrying CloudFormation delete: {str(e)}"

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

