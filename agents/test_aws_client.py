#!/usr/bin/env python3
"""
Tests for the AWS client (boto3).

Covers:
    - Availability detection
    - Graceful failure when boto3 not installed
    - All CloudFormation and EC2 operations via mocked boto3
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.aws_client import AWSClient
from botocore.exceptions import ClientError


def _mock_client(mock_service):
    """Patch _client to return a mock AWS service client."""
    return patch.object(AWSClient, "_client", return_value=mock_service)


# ================================================================
# Availability
# ================================================================

def test_available_when_boto3_present():
    with patch("agents.aws_client._BOTO3_AVAILABLE", True):
        client = AWSClient()
        assert client.available is True


def test_unavailable_when_no_boto3():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.available is False


# ================================================================
# Unavailable Returns Safe Defaults
# ================================================================

def test_describe_stack_status_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_stack_status("my-stack") == "UNAVAILABLE"


def test_get_vpc_from_stack_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.get_vpc_from_stack("my-stack") is None


def test_delete_stack_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        ok, msg = client.delete_stack("my-stack")
        assert ok is False
        assert "not installed" in msg


def test_describe_network_interfaces_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        assert AWSClient().describe_network_interfaces("vpc-123") == []


def test_describe_security_groups_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        assert AWSClient().describe_security_groups("vpc-123") == []


def test_describe_vpc_endpoints_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        assert AWSClient().describe_vpc_endpoints("vpc-123") == []


def test_describe_subnets_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        assert AWSClient().describe_subnets("vpc-123") == []


def test_describe_internet_gateways_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        assert AWSClient().describe_internet_gateways("vpc-123") == []


def test_mutating_ops_unavailable():
    with patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.detach_network_interface("att-123")[0] is False
        assert client.delete_network_interface("eni-123")[0] is False
        assert client.delete_security_group("sg-123")[0] is False
        assert client.delete_vpc_endpoints(["vpce-123"])[0] is False
        assert client.delete_subnet("subnet-123")[0] is False
        assert client.detach_internet_gateway("igw-123", "vpc-123")[0] is False
        assert client.delete_internet_gateway("igw-123")[0] is False


# ================================================================
# CloudFormation
# ================================================================

def test_describe_stack_status_success():
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.return_value = {
        "Stacks": [{"StackStatus": "DELETE_IN_PROGRESS"}]
    }
    with _mock_client(mock_cfn):
        assert AWSClient().describe_stack_status("my-stack") == "DELETE_IN_PROGRESS"


def test_describe_stack_status_gone():
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.return_value = {"Stacks": []}
    with _mock_client(mock_cfn):
        assert AWSClient().describe_stack_status("my-stack") == "GONE"


def test_describe_stack_status_not_found_error():
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.side_effect = ClientError(
        {"Error": {"Code": "ValidationError", "Message": "Stack does not exist"}},
        "DescribeStacks"
    )
    with _mock_client(mock_cfn):
        assert AWSClient().describe_stack_status("my-stack") == "GONE"


def test_get_vpc_from_stack():
    mock_cfn = MagicMock()
    mock_cfn.list_stack_resources.return_value = {
        "StackResourceSummaries": [
            {"ResourceType": "AWS::EC2::VPC", "PhysicalResourceId": "vpc-abc123"}
        ]
    }
    with _mock_client(mock_cfn):
        assert AWSClient().get_vpc_from_stack("my-stack") == "vpc-abc123"


def test_get_vpc_from_stack_no_vpc():
    mock_cfn = MagicMock()
    mock_cfn.list_stack_resources.return_value = {
        "StackResourceSummaries": [
            {"ResourceType": "AWS::EC2::Subnet", "PhysicalResourceId": "subnet-123"}
        ]
    }
    with _mock_client(mock_cfn):
        assert AWSClient().get_vpc_from_stack("my-stack") is None


def test_delete_stack():
    mock_cfn = MagicMock()
    with _mock_client(mock_cfn):
        ok, msg = AWSClient().delete_stack("my-stack")
        assert ok is True
        mock_cfn.delete_stack.assert_called_once_with(StackName="my-stack")


# ================================================================
# EC2 — Network Interfaces
# ================================================================

def test_describe_network_interfaces():
    mock_ec2 = MagicMock()
    mock_ec2.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [{
            "NetworkInterfaceId": "eni-111",
            "Attachment": {"AttachmentId": "eni-attach-aaa"},
            "Status": "in-use",
            "Description": "test ENI"
        }]
    }
    with _mock_client(mock_ec2):
        enis = AWSClient().describe_network_interfaces("vpc-123")
        assert len(enis) == 1
        assert enis[0]["id"] == "eni-111"
        assert enis[0]["attachment_id"] == "eni-attach-aaa"
        assert enis[0]["status"] == "in-use"


def test_describe_network_interfaces_with_cluster_filter():
    mock_ec2 = MagicMock()
    mock_ec2.describe_network_interfaces.return_value = {"NetworkInterfaces": []}
    with _mock_client(mock_ec2):
        AWSClient().describe_network_interfaces("vpc-123", cluster_id="my-cluster")
        filters = mock_ec2.describe_network_interfaces.call_args[1]["Filters"]
        assert len(filters) == 2
        assert filters[1]["Name"] == "tag:cluster.x-k8s.io/cluster-name"
        assert filters[1]["Values"] == ["my-cluster"]


def test_describe_eni_no_attachment():
    mock_ec2 = MagicMock()
    mock_ec2.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [{
            "NetworkInterfaceId": "eni-222",
            "Status": "available",
            "Description": "orphaned"
        }]
    }
    with _mock_client(mock_ec2):
        enis = AWSClient().describe_network_interfaces("vpc-123")
        assert enis[0]["attachment_id"] is None


def test_detach_network_interface():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().detach_network_interface("eni-attach-aaa")
        assert ok is True
        mock_ec2.detach_network_interface.assert_called_once_with(
            AttachmentId="eni-attach-aaa", Force=True
        )


def test_delete_network_interface():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().delete_network_interface("eni-111")
        assert ok is True


# ================================================================
# EC2 — Security Groups
# ================================================================

def test_describe_security_groups_filters_default():
    mock_ec2 = MagicMock()
    mock_ec2.describe_security_groups.return_value = {
        "SecurityGroups": [
            {"GroupId": "sg-111", "GroupName": "rosa-sg", "Tags": []},
            {"GroupId": "sg-def", "GroupName": "default", "Tags": []},
        ]
    }
    with _mock_client(mock_ec2):
        sgs = AWSClient().describe_security_groups("vpc-123")
        assert len(sgs) == 1
        assert sgs[0]["id"] == "sg-111"


def test_describe_security_groups_with_cluster_filter():
    mock_ec2 = MagicMock()
    mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
    with _mock_client(mock_ec2):
        AWSClient().describe_security_groups("vpc-123", cluster_id="my-cluster")
        filters = mock_ec2.describe_security_groups.call_args[1]["Filters"]
        assert any(f["Name"] == "tag:red-hat-clustertype" for f in filters)


def test_describe_security_groups_text():
    mock_ec2 = MagicMock()
    mock_ec2.describe_security_groups.return_value = {
        "SecurityGroups": [
            {"GroupId": "sg-aaa", "GroupName": "rosa-sg"},
            {"GroupId": "sg-def", "GroupName": "default"},
        ]
    }
    with _mock_client(mock_ec2):
        sgs = AWSClient().describe_security_groups_text("vpc-123")
        assert len(sgs) == 1
        assert sgs[0] == {"id": "sg-aaa", "name": "rosa-sg"}


def test_delete_security_group():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().delete_security_group("sg-111")
        assert ok is True


def test_delete_security_group_dependency_violation():
    mock_ec2 = MagicMock()
    mock_ec2.delete_security_group.side_effect = ClientError(
        {"Error": {"Code": "DependencyViolation", "Message": "has deps"}},
        "DeleteSecurityGroup"
    )
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().delete_security_group("sg-123")
        assert ok is False
        assert "DependencyViolation" in msg


# ================================================================
# EC2 — VPC Endpoints
# ================================================================

def test_describe_vpc_endpoints():
    mock_ec2 = MagicMock()
    mock_ec2.describe_vpc_endpoints.return_value = {
        "VpcEndpoints": [
            {"VpcEndpointId": "vpce-111", "State": "available"},
            {"VpcEndpointId": "vpce-222", "State": "deleting"},
        ]
    }
    with _mock_client(mock_ec2):
        eps = AWSClient().describe_vpc_endpoints("vpc-123")
        assert len(eps) == 2
        assert eps[0]["id"] == "vpce-111"
        assert eps[1]["state"] == "deleting"


def test_delete_vpc_endpoints():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().delete_vpc_endpoints(["vpce-111", "vpce-222"])
        assert ok is True
        assert "2" in msg


def test_delete_vpc_endpoints_empty_list():
    ok, msg = AWSClient().delete_vpc_endpoints([])
    assert ok is False
    assert "No endpoint" in msg


# ================================================================
# EC2 — Subnets
# ================================================================

def test_describe_subnets():
    mock_ec2 = MagicMock()
    mock_ec2.describe_subnets.return_value = {
        "Subnets": [
            {"SubnetId": "subnet-aaa"},
            {"SubnetId": "subnet-bbb"},
        ]
    }
    with _mock_client(mock_ec2):
        assert AWSClient().describe_subnets("vpc-123") == ["subnet-aaa", "subnet-bbb"]


def test_delete_subnet():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().delete_subnet("subnet-aaa")
        assert ok is True


# ================================================================
# EC2 — Internet Gateways
# ================================================================

def test_describe_internet_gateways():
    mock_ec2 = MagicMock()
    mock_ec2.describe_internet_gateways.return_value = {
        "InternetGateways": [
            {"InternetGatewayId": "igw-aaa"}
        ]
    }
    with _mock_client(mock_ec2):
        assert AWSClient().describe_internet_gateways("vpc-123") == ["igw-aaa"]


def test_detach_internet_gateway():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().detach_internet_gateway("igw-aaa", "vpc-123")
        assert ok is True
        mock_ec2.detach_internet_gateway.assert_called_once_with(
            InternetGatewayId="igw-aaa", VpcId="vpc-123"
        )


def test_delete_internet_gateway():
    mock_ec2 = MagicMock()
    with _mock_client(mock_ec2):
        ok, msg = AWSClient().delete_internet_gateway("igw-aaa")
        assert ok is True


# ================================================================
# Region and Logging
# ================================================================

def test_default_region():
    assert AWSClient().region == "us-west-2"


def test_custom_region():
    assert AWSClient(region="eu-west-1").region == "eu-west-1"


def test_log_function_called():
    logs = []
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.side_effect = Exception("boom")
    client = AWSClient(log_fn=lambda msg, level: logs.append((msg, level)))
    with _mock_client(mock_cfn):
        client.describe_stack_status("my-stack")
    assert any("debug" in log[1] for log in logs)

