"""
AWS Client using boto3
======================

Wraps AWS operations used by the agent framework. Uses boto3 for all
CloudFormation, EC2, IAM, and STS API calls. If boto3 is not installed,
methods return safe defaults.

Author: Tina Fitzgerald
Created: April 23, 2026
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("agent.aws_client")

try:
    import boto3
    from botocore.exceptions import ClientError
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False


class AWSClient:
    """AWS operations via boto3."""

    def __init__(self, region: str, log_fn=None):
        self.region = region
        self._log_fn = log_fn
        self._boto3_clients = {}

    @property
    def available(self) -> bool:
        return _BOTO3_AVAILABLE

    def _log(self, message: str, level: str = "info"):
        if self._log_fn:
            self._log_fn(message, level)
        else:
            getattr(logger, level if level != "success" else "info")(message)

    def _client(self, service: str):
        if not _BOTO3_AVAILABLE:
            return None
        if service not in self._boto3_clients:
            self._boto3_clients[service] = boto3.client(service, region_name=self.region)
        return self._boto3_clients[service]

    # ================================================================
    # CloudFormation
    # ================================================================

    def describe_stack_status(self, stack_name: str) -> str:
        """Get CloudFormation stack status.

        Returns: DELETE_IN_PROGRESS, DELETE_FAILED, DELETE_COMPLETE, or
                 GONE (stack doesn't exist), UNKNOWN (error), UNAVAILABLE (no boto3).
        """
        if not self.available:
            return "UNAVAILABLE"

        try:
            cfn = self._client("cloudformation")
            resp = cfn.describe_stacks(StackName=stack_name)
            stacks = resp.get("Stacks", [])
            if stacks:
                return stacks[0]["StackStatus"]
            return "GONE"
        except ClientError as e:
            if "does not exist" in str(e):
                return "GONE"
            self._log(f"describe-stacks error: {e}", "debug")
        except Exception as e:
            self._log(f"describe-stacks error: {e}", "debug")

        return "UNKNOWN"

    def get_vpc_from_stack(self, stack_name: str) -> Optional[str]:
        """Get VPC ID from a CloudFormation stack's resources."""
        if not self.available:
            return None

        try:
            cfn = self._client("cloudformation")
            resp = cfn.list_stack_resources(StackName=stack_name)
            for r in resp.get("StackResourceSummaries", []):
                if r["ResourceType"] == "AWS::EC2::VPC":
                    return r["PhysicalResourceId"]
        except Exception as e:
            self._log(f"list-stack-resources error: {e}", "debug")

        return None

    def delete_stack(self, stack_name: str) -> Tuple[bool, str]:
        """Delete a CloudFormation stack."""
        if not self.available:
            return False, "No AWS access available (boto3 not installed)"

        try:
            cfn = self._client("cloudformation")
            cfn.delete_stack(StackName=stack_name)
            return True, f"Stack deletion initiated for {stack_name}"
        except Exception as e:
            return False, f"delete-stack error: {e}"

    # ================================================================
    # EC2 — Network Interfaces
    # ================================================================

    def describe_network_interfaces(self, vpc_id: str, cluster_id: str = None) -> List[Dict]:
        """List network interfaces in a VPC, optionally filtered by cluster tag.

        Returns list of dicts with keys: id, attachment_id, status, description
        """
        if not self.available:
            return []

        try:
            ec2 = self._client("ec2")
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
            self._log(f"describe-network-interfaces error: {e}", "debug")

        return []

    def detach_network_interface(self, attachment_id: str) -> Tuple[bool, str]:
        """Force-detach a network interface."""
        if not self.available:
            return False, "No AWS access available"

        try:
            ec2 = self._client("ec2")
            ec2.detach_network_interface(AttachmentId=attachment_id, Force=True)
            return True, f"Detached {attachment_id}"
        except Exception as e:
            return False, f"Failed to detach {attachment_id}: {e}"

    def delete_network_interface(self, eni_id: str) -> Tuple[bool, str]:
        """Delete a network interface."""
        if not self.available:
            return False, "No AWS access available"

        try:
            ec2 = self._client("ec2")
            ec2.delete_network_interface(NetworkInterfaceId=eni_id)
            return True, f"Deleted ENI {eni_id}"
        except Exception as e:
            return False, f"Failed to delete ENI {eni_id}: {e}"

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

        try:
            ec2 = self._client("ec2")
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
            self._log(f"describe-security-groups error: {e}", "debug")

        return []

    def describe_security_groups_text(self, vpc_id: str) -> List[Dict]:
        """List non-default security groups in a VPC (no cluster tag filter).

        Returns list of dicts with keys: id, name
        """
        if not self.available:
            return []

        try:
            ec2 = self._client("ec2")
            resp = ec2.describe_security_groups(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            return [
                {"id": sg["GroupId"], "name": sg.get("GroupName", "")}
                for sg in resp.get("SecurityGroups", [])
                if sg.get("GroupName") != "default"
            ]
        except Exception as e:
            self._log(f"describe-security-groups error: {e}", "debug")

        return []

    def delete_security_group(self, sg_id: str) -> Tuple[bool, str]:
        """Delete a security group. Returns (success, message)."""
        if not self.available:
            return False, "No AWS access available"

        try:
            ec2 = self._client("ec2")
            ec2.delete_security_group(GroupId=sg_id)
            return True, f"Deleted security group {sg_id}"
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "DependencyViolation":
                return False, f"DependencyViolation: {sg_id} has dependencies"
            return False, f"Failed to delete security group {sg_id}: {e}"
        except Exception as e:
            return False, f"Failed to delete security group {sg_id}: {e}"

    # ================================================================
    # EC2 — VPC Endpoints
    # ================================================================

    def describe_vpc_endpoints(self, vpc_id: str) -> List[Dict]:
        """List VPC endpoints.

        Returns list of dicts with keys: id, state
        """
        if not self.available:
            return []

        try:
            ec2 = self._client("ec2")
            resp = ec2.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            return [
                {"id": ep["VpcEndpointId"], "state": ep.get("State", "unknown")}
                for ep in resp.get("VpcEndpoints", [])
            ]
        except Exception as e:
            self._log(f"describe-vpc-endpoints error: {e}", "debug")

        return []

    def delete_vpc_endpoints(self, vpce_ids: List[str]) -> Tuple[bool, str]:
        """Delete VPC endpoints."""
        if not self.available:
            return False, "No AWS access available"
        if not vpce_ids:
            return False, "No endpoint IDs"

        try:
            ec2 = self._client("ec2")
            ec2.delete_vpc_endpoints(VpcEndpointIds=vpce_ids)
            return True, f"Deleted {len(vpce_ids)} VPC endpoint(s)"
        except Exception as e:
            return False, f"Failed to delete VPC endpoints: {e}"

    # ================================================================
    # EC2 — Subnets
    # ================================================================

    def describe_subnets(self, vpc_id: str) -> List[str]:
        """List subnet IDs in a VPC."""
        if not self.available:
            return []

        try:
            ec2 = self._client("ec2")
            resp = ec2.describe_subnets(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            return [s["SubnetId"] for s in resp.get("Subnets", [])]
        except Exception as e:
            self._log(f"describe-subnets error: {e}", "debug")

        return []

    def delete_subnet(self, subnet_id: str) -> Tuple[bool, str]:
        """Delete a subnet."""
        if not self.available:
            return False, "No AWS access available"

        try:
            ec2 = self._client("ec2")
            ec2.delete_subnet(SubnetId=subnet_id)
            return True, f"Deleted subnet {subnet_id}"
        except Exception as e:
            return False, f"Failed to delete subnet {subnet_id}: {e}"

    # ================================================================
    # EC2 — Internet Gateways
    # ================================================================

    def describe_internet_gateways(self, vpc_id: str) -> List[str]:
        """List internet gateway IDs attached to a VPC."""
        if not self.available:
            return []

        try:
            ec2 = self._client("ec2")
            resp = ec2.describe_internet_gateways(
                Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
            )
            return [igw["InternetGatewayId"] for igw in resp.get("InternetGateways", [])]
        except Exception as e:
            self._log(f"describe-internet-gateways error: {e}", "debug")

        return []

    def detach_internet_gateway(self, igw_id: str, vpc_id: str) -> Tuple[bool, str]:
        """Detach an internet gateway from a VPC."""
        if not self.available:
            return False, "No AWS access available"

        try:
            ec2 = self._client("ec2")
            ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
            return True, f"Detached IGW {igw_id}"
        except Exception as e:
            return False, f"Failed to detach IGW {igw_id}: {e}"

    def delete_internet_gateway(self, igw_id: str) -> Tuple[bool, str]:
        """Delete an internet gateway."""
        if not self.available:
            return False, "No AWS access available"

        try:
            ec2 = self._client("ec2")
            ec2.delete_internet_gateway(InternetGatewayId=igw_id)
            return True, f"Deleted IGW {igw_id}"
        except Exception as e:
            return False, f"Failed to delete IGW {igw_id}: {e}"

    # ================================================================
    # IAM — Roles and OIDC Providers
    # ================================================================

    def get_role(self, role_name: str) -> Optional[Dict]:
        """Get IAM role details. Returns the Role dict or None."""
        if not self.available:
            return None

        try:
            iam = self._client("iam")
            resp = iam.get_role(RoleName=role_name)
            return resp.get("Role")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                self._log(f"IAM role {role_name} not found", "debug")
            else:
                self._log(f"get-role error: {e}", "debug")
        except Exception as e:
            self._log(f"get-role error: {e}", "debug")

        return None

    def list_attached_role_policies(self, role_name: str) -> List[Dict]:
        """List policies attached to an IAM role.

        Returns list of dicts with keys: PolicyName, PolicyArn
        """
        if not self.available:
            return []

        try:
            iam = self._client("iam")
            resp = iam.list_attached_role_policies(RoleName=role_name)
            return resp.get("AttachedPolicies", [])
        except Exception as e:
            self._log(f"list-attached-role-policies error: {e}", "debug")

        return []

    def get_open_id_connect_provider(self, arn: str) -> Optional[Dict]:
        """Get OIDC provider details. Returns the provider dict or None."""
        if not self.available:
            return None

        try:
            iam = self._client("iam")
            resp = iam.get_open_id_connect_provider(OpenIDConnectProviderArn=arn)
            resp.pop("ResponseMetadata", None)
            return resp
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                self._log(f"OIDC provider {arn} not found", "debug")
            else:
                self._log(f"get-open-id-connect-provider error: {e}", "debug")
        except Exception as e:
            self._log(f"get-open-id-connect-provider error: {e}", "debug")

        return None

    def list_open_id_connect_provider_tags(self, arn: str) -> List[Dict]:
        """List tags on an OIDC provider.

        Returns list of dicts with keys: Key, Value
        """
        if not self.available:
            return []

        try:
            iam = self._client("iam")
            resp = iam.list_open_id_connect_provider_tags(OpenIDConnectProviderArn=arn)
            return resp.get("Tags", [])
        except Exception as e:
            self._log(f"list-open-id-connect-provider-tags error: {e}", "debug")

        return []

    # ================================================================
    # STS
    # ================================================================

    def get_caller_identity(self) -> Optional[Dict]:
        """Get caller identity (account, ARN, user ID). Returns dict or None."""
        if not self.available:
            return None

        try:
            sts = self._client("sts")
            resp = sts.get_caller_identity()
            resp.pop("ResponseMetadata", None)
            return resp
        except Exception as e:
            self._log(f"get-caller-identity error: {e}", "debug")

        return None
