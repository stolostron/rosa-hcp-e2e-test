"""
AWS Client with CLI-first, boto3-fallback
==========================================

Wraps AWS operations used by the agent framework. Tries the aws CLI
first; if the CLI is not installed, falls back to boto3. If neither
is available, returns clear error results.

Author: Tina Fitzgerald
Created: April 23, 2026
"""

import json
import logging
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("agent.aws_client")

# Detect aws CLI availability once at import time
_AWS_CLI_AVAILABLE = shutil.which("aws") is not None

# Detect boto3 availability once at import time
try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False


class AWSClient:
    """AWS operations with CLI-first, boto3-fallback strategy."""

    def __init__(self, region: str = "us-west-2", log_fn=None):
        self.region = region
        self._log_fn = log_fn
        self._boto3_clients = {}

    @property
    def has_aws_cli(self) -> bool:
        return _AWS_CLI_AVAILABLE

    @property
    def has_boto3(self) -> bool:
        return _BOTO3_AVAILABLE

    @property
    def available(self) -> bool:
        return _AWS_CLI_AVAILABLE or _BOTO3_AVAILABLE

    @property
    def backend(self) -> str:
        if _AWS_CLI_AVAILABLE:
            return "cli"
        if _BOTO3_AVAILABLE:
            return "boto3"
        return "none"

    def _log(self, message: str, level: str = "info"):
        if self._log_fn:
            self._log_fn(message, level)
        else:
            getattr(logger, level if level != "success" else "info")(message)

    def _boto3_client(self, service: str):
        if not _BOTO3_AVAILABLE:
            return None
        if service not in self._boto3_clients:
            self._boto3_clients[service] = boto3.client(service, region_name=self.region)
        return self._boto3_clients[service]

    def _run_cli(self, cmd: List[str], timeout: int = 30) -> Tuple[bool, str, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "CLI command timed out"
        except Exception as e:
            return False, "", str(e)

    # ================================================================
    # CloudFormation
    # ================================================================

    def describe_stack_status(self, stack_name: str) -> str:
        """Get CloudFormation stack status.

        Returns: DELETE_IN_PROGRESS, DELETE_FAILED, DELETE_COMPLETE, or
                 GONE (stack doesn't exist), UNKNOWN (error), UNAVAILABLE (no AWS access).
        """
        if not self.available:
            return "UNAVAILABLE"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", self.region,
                "--query", "Stacks[0].StackStatus",
                "--output", "text"
            ], timeout=10)
            if ok and stdout:
                return stdout
            if "does not exist" in stderr:
                return "GONE"
            if not ok:
                self._log(f"CLI failed for describe-stacks: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                cfn = self._boto3_client("cloudformation")
                resp = cfn.describe_stacks(StackName=stack_name)
                stacks = resp.get("Stacks", [])
                if stacks:
                    return stacks[0]["StackStatus"]
                return "GONE"
            except ClientError as e:
                if "does not exist" in str(e):
                    return "GONE"
                self._log(f"boto3 describe-stacks error: {e}", "debug")
            except Exception as e:
                self._log(f"boto3 describe-stacks error: {e}", "debug")

        return "UNKNOWN"

    def get_vpc_from_stack(self, stack_name: str) -> Optional[str]:
        """Get VPC ID from a CloudFormation stack's resources."""
        if not self.available:
            return None

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "cloudformation", "list-stack-resources",
                "--stack-name", stack_name,
                "--region", self.region,
                "--query", "StackResourceSummaries[?ResourceType=='AWS::EC2::VPC'].PhysicalResourceId",
                "--output", "text"
            ], timeout=10)
            if ok and stdout.startswith("vpc-"):
                return stdout
            if not ok:
                self._log(f"CLI failed for list-stack-resources: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                cfn = self._boto3_client("cloudformation")
                resp = cfn.list_stack_resources(StackName=stack_name)
                for r in resp.get("StackResourceSummaries", []):
                    if r["ResourceType"] == "AWS::EC2::VPC":
                        return r["PhysicalResourceId"]
            except Exception as e:
                self._log(f"boto3 list-stack-resources error: {e}", "debug")

        return None

    def delete_stack(self, stack_name: str) -> Tuple[bool, str]:
        """Delete a CloudFormation stack."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "cloudformation", "delete-stack",
                "--stack-name", stack_name,
                "--region", self.region
            ], timeout=10)
            if ok:
                return True, f"Stack deletion initiated for {stack_name}"
            self._log(f"CLI failed for delete-stack: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                cfn = self._boto3_client("cloudformation")
                cfn.delete_stack(StackName=stack_name)
                return True, f"Stack deletion initiated for {stack_name}"
            except Exception as e:
                return False, f"boto3 delete-stack error: {e}"

        return False, f"Failed to delete stack {stack_name}"

    # ================================================================
    # EC2 — Network Interfaces
    # ================================================================

    def describe_network_interfaces(self, vpc_id: str, cluster_id: str = None) -> List[Dict]:
        """List network interfaces in a VPC, optionally filtered by cluster tag.

        Returns list of dicts with keys: id, attachment_id, status, description
        """
        if not self.available:
            return []

        if _AWS_CLI_AVAILABLE:
            filters = [f"Name=vpc-id,Values={vpc_id}"]
            if cluster_id:
                filters.append(f"Name=tag:cluster.x-k8s.io/cluster-name,Values={cluster_id}")
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "describe-network-interfaces",
                "--region", self.region,
                "--filters", *filters,
                "--query", "NetworkInterfaces[*].[NetworkInterfaceId,Attachment.AttachmentId,Status,Description]",
                "--output", "text"
            ])
            if ok and stdout:
                results = []
                for line in stdout.split('\n'):
                    parts = line.split('\t')
                    if parts:
                        results.append({
                            "id": parts[0],
                            "attachment_id": parts[1] if len(parts) > 1 and parts[1] != "None" else None,
                            "status": parts[2] if len(parts) > 2 else "unknown",
                            "description": parts[3] if len(parts) > 3 else ""
                        })
                return results
            if not ok and stderr:
                self._log(f"CLI failed for describe-network-interfaces: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
                if cluster_id:
                    filters.append({"Name": "tag:cluster.x-k8s.io/cluster-name", "Values": [cluster_id]})
                resp = ec2.describe_network_interfaces(Filters=filters)
                results = []
                for eni in resp.get("NetworkInterfaces", []):
                    attachment = eni.get("Attachment", {})
                    results.append({
                        "id": eni["NetworkInterfaceId"],
                        "attachment_id": attachment.get("AttachmentId"),
                        "status": eni.get("Status", "unknown"),
                        "description": eni.get("Description", "")
                    })
                return results
            except Exception as e:
                self._log(f"boto3 describe-network-interfaces error: {e}", "debug")

        return []

    def detach_network_interface(self, attachment_id: str) -> Tuple[bool, str]:
        """Force-detach a network interface."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "detach-network-interface",
                "--region", self.region,
                "--attachment-id", attachment_id,
                "--force"
            ])
            if ok:
                return True, f"Detached {attachment_id}"
            self._log(f"CLI failed for detach-network-interface: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.detach_network_interface(AttachmentId=attachment_id, Force=True)
                return True, f"Detached {attachment_id}"
            except Exception as e:
                return False, f"Failed to detach {attachment_id}: {e}"

        return False, f"Failed to detach {attachment_id}"

    def delete_network_interface(self, eni_id: str) -> Tuple[bool, str]:
        """Delete a network interface."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "delete-network-interface",
                "--region", self.region,
                "--network-interface-id", eni_id
            ])
            if ok:
                return True, f"Deleted ENI {eni_id}"
            self._log(f"CLI failed for delete-network-interface: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.delete_network_interface(NetworkInterfaceId=eni_id)
                return True, f"Deleted ENI {eni_id}"
            except Exception as e:
                return False, f"Failed to delete ENI {eni_id}: {e}"

        return False, f"Failed to delete ENI {eni_id}"

    # ================================================================
    # EC2 — Security Groups
    # ================================================================

    def describe_security_groups(self, vpc_id: str, cluster_id: str = None,
                                 exclude_default: bool = True) -> List[Dict]:
        """List security groups in a VPC.

        Returns list of dicts with keys: id, name, tags
        """
        if not self.available:
            return []

        if _AWS_CLI_AVAILABLE:
            filters = [f"Name=vpc-id,Values={vpc_id}"]
            if cluster_id:
                filters.append(f"Name=tag:red-hat-clustertype,Values={cluster_id}")
            query = "SecurityGroups[?GroupName!='default'].[GroupId,GroupName,Tags]" if exclude_default else "SecurityGroups[*].[GroupId,GroupName,Tags]"
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "describe-security-groups",
                "--region", self.region,
                "--filters", *filters,
                "--query", query,
                "--output", "json"
            ])
            if ok and stdout:
                try:
                    sgs = json.loads(stdout)
                    return [{"id": sg[0], "name": sg[1], "tags": sg[2]} for sg in (sgs or [])]
                except (json.JSONDecodeError, IndexError):
                    pass
            if not ok and stderr:
                self._log(f"CLI failed for describe-security-groups: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
                if cluster_id:
                    filters.append({"Name": "tag:red-hat-clustertype", "Values": [cluster_id]})
                resp = ec2.describe_security_groups(Filters=filters)
                results = []
                for sg in resp.get("SecurityGroups", []):
                    if exclude_default and sg.get("GroupName") == "default":
                        continue
                    results.append({
                        "id": sg["GroupId"],
                        "name": sg.get("GroupName", ""),
                        "tags": sg.get("Tags", [])
                    })
                return results
            except Exception as e:
                self._log(f"boto3 describe-security-groups error: {e}", "debug")

        return []

    def describe_security_groups_text(self, vpc_id: str) -> List[Dict]:
        """List non-default security groups in a VPC (no cluster tag filter).

        Returns list of dicts with keys: id, name
        """
        if not self.available:
            return []

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "describe-security-groups",
                "--region", self.region,
                "--filters", f"Name=vpc-id,Values={vpc_id}",
                "--query", "SecurityGroups[?GroupName!='default'].[GroupId,GroupName]",
                "--output", "text"
            ])
            if ok and stdout:
                results = []
                for line in stdout.split('\n'):
                    parts = line.split('\t')
                    if parts:
                        results.append({
                            "id": parts[0],
                            "name": parts[1] if len(parts) > 1 else "unknown"
                        })
                return results
            if not ok and stderr:
                self._log(f"CLI failed for describe-security-groups: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                resp = ec2.describe_security_groups(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                return [
                    {"id": sg["GroupId"], "name": sg.get("GroupName", "")}
                    for sg in resp.get("SecurityGroups", [])
                    if sg.get("GroupName") != "default"
                ]
            except Exception as e:
                self._log(f"boto3 describe-security-groups error: {e}", "debug")

        return []

    def delete_security_group(self, sg_id: str) -> Tuple[bool, str]:
        """Delete a security group. Returns (success, message)."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "delete-security-group",
                "--region", self.region,
                "--group-id", sg_id
            ])
            if ok:
                return True, f"Deleted security group {sg_id}"
            if "DependencyViolation" in stderr:
                return False, f"DependencyViolation: {sg_id} has dependencies"
            self._log(f"CLI failed for delete-security-group: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.delete_security_group(GroupId=sg_id)
                return True, f"Deleted security group {sg_id}"
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code == "DependencyViolation":
                    return False, f"DependencyViolation: {sg_id} has dependencies"
                return False, f"Failed to delete security group {sg_id}: {e}"
            except Exception as e:
                return False, f"Failed to delete security group {sg_id}: {e}"

        return False, f"Failed to delete security group {sg_id}"

    # ================================================================
    # EC2 — VPC Endpoints
    # ================================================================

    def describe_vpc_endpoints(self, vpc_id: str) -> List[Dict]:
        """List VPC endpoints.

        Returns list of dicts with keys: id, state
        """
        if not self.available:
            return []

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "describe-vpc-endpoints",
                "--region", self.region,
                "--filters", f"Name=vpc-id,Values={vpc_id}",
                "--query", "VpcEndpoints[*].[VpcEndpointId,State]",
                "--output", "text"
            ])
            if ok and stdout:
                results = []
                for line in stdout.split('\n'):
                    parts = line.split('\t')
                    if parts and parts[0].startswith("vpce-"):
                        results.append({
                            "id": parts[0],
                            "state": parts[1] if len(parts) > 1 else "unknown"
                        })
                return results
            if not ok and stderr:
                self._log(f"CLI failed for describe-vpc-endpoints: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                resp = ec2.describe_vpc_endpoints(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                return [
                    {"id": ep["VpcEndpointId"], "state": ep.get("State", "unknown")}
                    for ep in resp.get("VpcEndpoints", [])
                ]
            except Exception as e:
                self._log(f"boto3 describe-vpc-endpoints error: {e}", "debug")

        return []

    def delete_vpc_endpoints(self, vpce_ids: List[str]) -> Tuple[bool, str]:
        """Delete VPC endpoints."""
        if not self.available or not vpce_ids:
            return False, "No AWS access available" if not self.available else "No endpoint IDs"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "delete-vpc-endpoints",
                "--region", self.region,
                "--vpc-endpoint-ids", *vpce_ids
            ], timeout=60)
            if ok:
                return True, f"Deleted {len(vpce_ids)} VPC endpoint(s)"
            self._log(f"CLI failed for delete-vpc-endpoints: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.delete_vpc_endpoints(VpcEndpointIds=vpce_ids)
                return True, f"Deleted {len(vpce_ids)} VPC endpoint(s)"
            except Exception as e:
                return False, f"Failed to delete VPC endpoints: {e}"

        return False, "Failed to delete VPC endpoints"

    # ================================================================
    # EC2 — Subnets
    # ================================================================

    def describe_subnets(self, vpc_id: str) -> List[str]:
        """List subnet IDs in a VPC."""
        if not self.available:
            return []

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "describe-subnets",
                "--region", self.region,
                "--filters", f"Name=vpc-id,Values={vpc_id}",
                "--query", "Subnets[*].SubnetId",
                "--output", "text"
            ])
            if ok and stdout:
                return [s for s in stdout.split('\t') if s.startswith("subnet-")]
            if not ok and stderr:
                self._log(f"CLI failed for describe-subnets: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                resp = ec2.describe_subnets(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                return [s["SubnetId"] for s in resp.get("Subnets", [])]
            except Exception as e:
                self._log(f"boto3 describe-subnets error: {e}", "debug")

        return []

    def delete_subnet(self, subnet_id: str) -> Tuple[bool, str]:
        """Delete a subnet."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "delete-subnet",
                "--region", self.region,
                "--subnet-id", subnet_id
            ])
            if ok:
                return True, f"Deleted subnet {subnet_id}"
            self._log(f"CLI failed for delete-subnet: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.delete_subnet(SubnetId=subnet_id)
                return True, f"Deleted subnet {subnet_id}"
            except Exception as e:
                return False, f"Failed to delete subnet {subnet_id}: {e}"

        return False, f"Failed to delete subnet {subnet_id}"

    # ================================================================
    # EC2 — Internet Gateways
    # ================================================================

    def describe_internet_gateways(self, vpc_id: str) -> List[str]:
        """List internet gateway IDs attached to a VPC."""
        if not self.available:
            return []

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "describe-internet-gateways",
                "--region", self.region,
                "--filters", f"Name=attachment.vpc-id,Values={vpc_id}",
                "--query", "InternetGateways[*].InternetGatewayId",
                "--output", "text"
            ])
            if ok and stdout:
                return [i for i in stdout.split('\t') if i.startswith("igw-")]
            if not ok and stderr:
                self._log(f"CLI failed for describe-internet-gateways: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                resp = ec2.describe_internet_gateways(
                    Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
                )
                return [igw["InternetGatewayId"] for igw in resp.get("InternetGateways", [])]
            except Exception as e:
                self._log(f"boto3 describe-internet-gateways error: {e}", "debug")

        return []

    def detach_internet_gateway(self, igw_id: str, vpc_id: str) -> Tuple[bool, str]:
        """Detach an internet gateway from a VPC."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "detach-internet-gateway",
                "--region", self.region,
                "--internet-gateway-id", igw_id,
                "--vpc-id", vpc_id
            ])
            if ok:
                return True, f"Detached IGW {igw_id}"
            self._log(f"CLI failed for detach-internet-gateway: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                return True, f"Detached IGW {igw_id}"
            except Exception as e:
                return False, f"Failed to detach IGW {igw_id}: {e}"

        return False, f"Failed to detach IGW {igw_id}"

    def delete_internet_gateway(self, igw_id: str) -> Tuple[bool, str]:
        """Delete an internet gateway."""
        if not self.available:
            return False, "No AWS access available"

        if _AWS_CLI_AVAILABLE:
            ok, stdout, stderr = self._run_cli([
                "aws", "ec2", "delete-internet-gateway",
                "--region", self.region,
                "--internet-gateway-id", igw_id
            ])
            if ok:
                return True, f"Deleted IGW {igw_id}"
            self._log(f"CLI failed for delete-internet-gateway: {stderr}", "debug")

        if _BOTO3_AVAILABLE:
            try:
                ec2 = self._boto3_client("ec2")
                ec2.delete_internet_gateway(InternetGatewayId=igw_id)
                return True, f"Deleted IGW {igw_id}"
            except Exception as e:
                return False, f"Failed to delete IGW {igw_id}: {e}"

        return False, f"Failed to delete IGW {igw_id}"
