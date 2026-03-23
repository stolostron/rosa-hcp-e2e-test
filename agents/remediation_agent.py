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

        try:
            # Check current stack status
            status_cmd = [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].StackStatus",
                "--output", "text"
            ]
            status_result = subprocess.run(status_cmd, capture_output=True, text=True, timeout=10)

            if status_result.returncode != 0:
                if "does not exist" in status_result.stderr:
                    return True, f"CloudFormation stack {stack_name} already deleted"
                return False, f"Failed to check stack status: {status_result.stderr}"

            stack_status = status_result.stdout.strip()

            if stack_status not in ("DELETE_IN_PROGRESS", "DELETE_FAILED"):
                return False, f"Stack {stack_name} in unexpected state: {stack_status}"

            # For both DELETE_IN_PROGRESS (stuck on VPC deps) and DELETE_FAILED,
            # clean up VPC dependencies then retry/let CF continue.
            cleanup_details = []
            cleanup_errors = []

            # Step 0: Remove finalizers from the K8s ROSANetwork resource so the
            # CAPA controller stops recreating VPC dependencies (endpoints, SGs)
            # while we're trying to clean them up.
            rosanetwork_name = params.get("resource_name")
            rosanetwork_ns = params.get("namespace")
            if rosanetwork_name and rosanetwork_ns:
                self.log(f"Removing finalizers from rosanetwork/{rosanetwork_name} to stop CAPA controller", "info")
                patch_cmd = [
                    "oc", "patch", "rosanetwork", rosanetwork_name,
                    "-n", rosanetwork_ns,
                    "--type=merge",
                    "-p", '{"metadata":{"finalizers":null}}'
                ]
                patch_result = subprocess.run(patch_cmd, capture_output=True, text=True, timeout=30)
                if patch_result.returncode == 0:
                    cleanup_details.append(f"Removed finalizers from rosanetwork/{rosanetwork_name}")
                    self.log(f"Removed finalizers from rosanetwork/{rosanetwork_name}", "info")
                elif "NotFound" in patch_result.stderr or "not found" in patch_result.stderr.lower():
                    self.log(f"rosanetwork/{rosanetwork_name} already gone", "info")
                else:
                    self.log(f"Failed to remove rosanetwork finalizers: {patch_result.stderr}", "warning")

            # Get the VPC ID from the stack to clean up dependencies
            vpc_cmd = [
                "aws", "cloudformation", "list-stack-resources",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "StackResourceSummaries[?ResourceType=='AWS::EC2::VPC'].PhysicalResourceId",
                "--output", "text"
            ]
            vpc_result = subprocess.run(vpc_cmd, capture_output=True, text=True, timeout=10)
            vpc_id = vpc_result.stdout.strip() if vpc_result.returncode == 0 else None

            # If we have a VPC, clean up any lingering dependencies
            if vpc_id and vpc_id.startswith("vpc-"):
                self.log(f"Cleaning up VPC {vpc_id} dependencies before retry", "info")

                # Step 1: Delete VPC endpoints FIRST — they create ela-attach ENIs
                # that cannot be manually detached. Must delete endpoints and wait
                # for ENIs to release before cleaning SGs.
                vpce_cmd = [
                    "aws", "ec2", "describe-vpc-endpoints",
                    "--region", region,
                    "--filters", f"Name=vpc-id,Values={vpc_id}",
                    "--query", "VpcEndpoints[*].VpcEndpointId",
                    "--output", "text"
                ]
                vpce_result = subprocess.run(vpce_cmd, capture_output=True, text=True, timeout=10)
                if vpce_result.returncode == 0 and vpce_result.stdout.strip():
                    vpce_ids = [v for v in vpce_result.stdout.strip().split() if v.startswith("vpce-")]
                    if vpce_ids:
                        self.log(f"Deleting {len(vpce_ids)} VPC endpoint(s)", "info")
                        del_vpce = subprocess.run([
                            "aws", "ec2", "delete-vpc-endpoints",
                            "--region", region,
                            "--vpc-endpoint-ids", *vpce_ids
                        ], capture_output=True, text=True, timeout=60)
                        if del_vpce.returncode == 0:
                            cleanup_details.append(f"Deleted {len(vpce_ids)} VPC endpoint(s)")
                        else:
                            cleanup_errors.append(f"Failed to delete VPC endpoints: {del_vpce.stderr.strip()}")
                        # Wait for ENIs to release after endpoint deletion
                        self.log("Waiting 20s for ENIs to release after VPC endpoint deletion", "info")
                        time.sleep(20)

                # Step 1: Delete any remaining ENIs
                eni_cmd = [
                    "aws", "ec2", "describe-network-interfaces",
                    "--region", region,
                    "--filters", f"Name=vpc-id,Values={vpc_id}",
                    "--query", "NetworkInterfaces[*].[NetworkInterfaceId,Attachment.AttachmentId,Status]",
                    "--output", "text"
                ]
                eni_result = subprocess.run(eni_cmd, capture_output=True, text=True, timeout=10)
                if eni_result.returncode == 0 and eni_result.stdout.strip():
                    for line in eni_result.stdout.strip().split('\n'):
                        parts = line.split('\t')
                        if len(parts) >= 1:
                            eni_id = parts[0]
                            attachment_id = parts[1] if len(parts) > 1 and parts[1] != "None" else None
                            if attachment_id:
                                detach_r = subprocess.run([
                                    "aws", "ec2", "detach-network-interface",
                                    "--region", region,
                                    "--attachment-id", attachment_id, "--force"
                                ], capture_output=True, text=True, timeout=10)
                                if detach_r.returncode != 0:
                                    cleanup_errors.append(f"Failed to detach ENI {eni_id}: {detach_r.stderr.strip()}")
                                time.sleep(2)
                            del_eni_r = subprocess.run([
                                "aws", "ec2", "delete-network-interface",
                                "--region", region,
                                "--network-interface-id", eni_id
                            ], capture_output=True, text=True, timeout=10)
                            if del_eni_r.returncode == 0:
                                cleanup_details.append(f"Deleted ENI {eni_id}")
                            else:
                                cleanup_errors.append(f"Failed to delete ENI {eni_id}: {del_eni_r.stderr.strip()}")

                # Delete non-default security groups (includes ROSA-created ones
                # like *-vpce-private-router that aren't managed by CloudFormation)
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
                        if len(parts) >= 1:
                            sg_id = parts[0]
                            sg_name = parts[1] if len(parts) > 1 else "unknown"
                            del_result = subprocess.run([
                                "aws", "ec2", "delete-security-group",
                                "--region", region,
                                "--group-id", sg_id
                            ], capture_output=True, text=True, timeout=10)
                            if del_result.returncode == 0:
                                cleanup_details.append(f"Deleted security group {sg_id} ({sg_name})")
                                self.log(f"Deleted orphaned security group {sg_id} ({sg_name})", "info")
                            else:
                                cleanup_errors.append(f"Failed to delete SG {sg_id}: {del_result.stderr.strip()}")

                # Delete any remaining subnets (shouldn't exist but check anyway)
                subnet_cmd = [
                    "aws", "ec2", "describe-subnets",
                    "--region", region,
                    "--filters", f"Name=vpc-id,Values={vpc_id}",
                    "--query", "Subnets[*].SubnetId",
                    "--output", "text"
                ]
                subnet_result = subprocess.run(subnet_cmd, capture_output=True, text=True, timeout=10)
                if subnet_result.returncode == 0 and subnet_result.stdout.strip():
                    for subnet_id in subnet_result.stdout.strip().split('\t'):
                        del_sub_r = subprocess.run([
                            "aws", "ec2", "delete-subnet",
                            "--region", region,
                            "--subnet-id", subnet_id
                        ], capture_output=True, text=True, timeout=10)
                        if del_sub_r.returncode == 0:
                            cleanup_details.append(f"Deleted subnet {subnet_id}")
                        else:
                            cleanup_errors.append(f"Failed to delete subnet {subnet_id}: {del_sub_r.stderr.strip()}")

                # Detach and delete any internet gateways
                igw_cmd = [
                    "aws", "ec2", "describe-internet-gateways",
                    "--region", region,
                    "--filters", f"Name=attachment.vpc-id,Values={vpc_id}",
                    "--query", "InternetGateways[*].InternetGatewayId",
                    "--output", "text"
                ]
                igw_result = subprocess.run(igw_cmd, capture_output=True, text=True, timeout=10)
                if igw_result.returncode == 0 and igw_result.stdout.strip():
                    for igw_id in igw_result.stdout.strip().split('\t'):
                        subprocess.run([
                            "aws", "ec2", "detach-internet-gateway",
                            "--region", region,
                            "--internet-gateway-id", igw_id,
                            "--vpc-id", vpc_id
                        ], capture_output=True, text=True, timeout=10)
                        del_igw_r = subprocess.run([
                            "aws", "ec2", "delete-internet-gateway",
                            "--region", region,
                            "--internet-gateway-id", igw_id
                        ], capture_output=True, text=True, timeout=10)
                        if del_igw_r.returncode == 0:
                            cleanup_details.append(f"Deleted internet gateway {igw_id}")
                        else:
                            cleanup_errors.append(f"Failed to delete IGW {igw_id}: {del_igw_r.stderr.strip()}")

                if cleanup_details:
                    self.log(f"VPC cleanup: {'; '.join(cleanup_details)}", "info")
                if cleanup_errors:
                    self.log(f"VPC cleanup errors: {'; '.join(cleanup_errors)}", "warning")

            if stack_status == "DELETE_FAILED":
                # Retry the stack deletion (only needed for DELETE_FAILED;
                # DELETE_IN_PROGRESS will continue on its own after deps are removed)
                delete_cmd = [
                    "aws", "cloudformation", "delete-stack",
                    "--stack-name", stack_name,
                    "--region", region
                ]
                delete_result = subprocess.run(delete_cmd, capture_output=True, text=True, timeout=10)

                if delete_result.returncode != 0:
                    return False, f"Failed to retry stack deletion: {delete_result.stderr}"

                # Verify the stack transitioned to DELETE_IN_PROGRESS (delete-stack is async
                # and always returns rc=0, so we must check the actual status)
                time.sleep(5)
                recheck = subprocess.run(status_cmd, capture_output=True, text=True, timeout=10)
                if recheck.returncode == 0 and "DELETE_FAILED" in recheck.stdout:
                    self.log(f"Stack {stack_name} immediately re-entered DELETE_FAILED after retry", "warning")
                    return False, f"Stack {stack_name} re-entered DELETE_FAILED — dependencies may still exist"

            cleanup_summary = f"; {'; '.join(cleanup_details)}" if cleanup_details else ""
            return True, f"Cleaned up VPC dependencies for {stack_name}{cleanup_summary}"

        except subprocess.TimeoutExpired:
            return False, "Timeout during CloudFormation retry"
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

