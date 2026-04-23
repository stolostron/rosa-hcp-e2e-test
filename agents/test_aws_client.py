#!/usr/bin/env python3
"""
Tests for the AWS client with CLI-first, boto3-fallback.

Covers:
    - Backend detection (CLI, boto3, none)
    - CLI-first behavior with mocked subprocess
    - boto3 fallback when CLI unavailable
    - Graceful failure when neither is available
    - All CloudFormation and EC2 operations
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.aws_client import AWSClient


# ================================================================
# Backend Detection
# ================================================================

def test_backend_reports_cli_when_available():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True):
        client = AWSClient()
        assert client.backend == "cli"
        assert client.has_aws_cli is True
        assert client.has_boto3 is True
        assert client.available is True


def test_backend_reports_boto3_when_no_cli():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True):
        client = AWSClient()
        assert client.backend == "boto3"
        assert client.has_aws_cli is False
        assert client.available is True


def test_backend_reports_none_when_nothing_available():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.backend == "none"
        assert client.available is False


# ================================================================
# Unavailable Returns Safe Defaults
# ================================================================

def test_describe_stack_status_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_stack_status("my-stack") == "UNAVAILABLE"


def test_get_vpc_from_stack_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.get_vpc_from_stack("my-stack") is None


def test_delete_stack_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        ok, msg = client.delete_stack("my-stack")
        assert ok is False
        assert "No AWS access" in msg


def test_describe_network_interfaces_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_network_interfaces("vpc-123") == []


def test_describe_security_groups_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_security_groups("vpc-123") == []


def test_describe_vpc_endpoints_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_vpc_endpoints("vpc-123") == []


def test_describe_subnets_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_subnets("vpc-123") == []


def test_describe_internet_gateways_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()
        assert client.describe_internet_gateways("vpc-123") == []


def test_mutating_ops_unavailable():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False):
        client = AWSClient()

        ok, _ = client.detach_network_interface("eni-attach-123")
        assert ok is False

        ok, _ = client.delete_network_interface("eni-123")
        assert ok is False

        ok, _ = client.delete_security_group("sg-123")
        assert ok is False

        ok, _ = client.delete_vpc_endpoints(["vpce-123"])
        assert ok is False

        ok, _ = client.delete_subnet("subnet-123")
        assert ok is False

        ok, _ = client.detach_internet_gateway("igw-123", "vpc-123")
        assert ok is False

        ok, _ = client.delete_internet_gateway("igw-123")
        assert ok is False


# ================================================================
# CLI-First Behavior
# ================================================================

def _mock_run(stdout="", stderr="", returncode=0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


def test_describe_stack_status_cli_success():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(stdout="DELETE_IN_PROGRESS")):
        client = AWSClient()
        assert client.describe_stack_status("my-stack") == "DELETE_IN_PROGRESS"


def test_describe_stack_status_cli_gone():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(returncode=1, stderr="Stack does not exist")):
        client = AWSClient()
        assert client.describe_stack_status("my-stack") == "GONE"


def test_get_vpc_from_stack_cli():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(stdout="vpc-abc123")):
        client = AWSClient()
        assert client.get_vpc_from_stack("my-stack") == "vpc-abc123"


def test_describe_enis_cli():
    cli_output = "eni-111\teni-attach-aaa\tavailable\ttest ENI"
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(stdout=cli_output)):
        client = AWSClient()
        enis = client.describe_network_interfaces("vpc-123")
        assert len(enis) == 1
        assert enis[0]["id"] == "eni-111"
        assert enis[0]["attachment_id"] == "eni-attach-aaa"
        assert enis[0]["status"] == "available"


def test_describe_security_groups_cli():
    cli_output = '[["sg-111", "my-sg", null]]'
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(stdout=cli_output)):
        client = AWSClient()
        sgs = client.describe_security_groups("vpc-123")
        assert len(sgs) == 1
        assert sgs[0]["id"] == "sg-111"
        assert sgs[0]["name"] == "my-sg"


def test_describe_vpc_endpoints_cli():
    cli_output = "vpce-111\tavailable\nvpce-222\tdeleting"
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(stdout=cli_output)):
        client = AWSClient()
        eps = client.describe_vpc_endpoints("vpc-123")
        assert len(eps) == 2
        assert eps[0]["id"] == "vpce-111"
        assert eps[1]["state"] == "deleting"


def test_delete_stack_cli_success():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run()):
        client = AWSClient()
        ok, msg = client.delete_stack("my-stack")
        assert ok is True


def test_delete_security_group_dependency_violation_cli():
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(
             returncode=1, stderr="DependencyViolation: sg has deps")):
        client = AWSClient()
        ok, msg = client.delete_security_group("sg-123")
        assert ok is False
        assert "DependencyViolation" in msg


# ================================================================
# boto3 Fallback
# ================================================================

def _boto3_client(mock_client):
    """Helper to patch _boto3_client to return a mock AWS service client."""
    return patch.object(AWSClient, "_boto3_client", return_value=mock_client)


def test_describe_stack_status_boto3_fallback():
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.return_value = {
        "Stacks": [{"StackStatus": "DELETE_FAILED"}]
    }
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True), \
         _boto3_client(mock_cfn):
        client = AWSClient()
        assert client.describe_stack_status("my-stack") == "DELETE_FAILED"


def test_get_vpc_from_stack_boto3_fallback():
    mock_cfn = MagicMock()
    mock_cfn.list_stack_resources.return_value = {
        "StackResourceSummaries": [
            {"ResourceType": "AWS::EC2::VPC", "PhysicalResourceId": "vpc-boto3"}
        ]
    }
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True), \
         _boto3_client(mock_cfn):
        client = AWSClient()
        assert client.get_vpc_from_stack("my-stack") == "vpc-boto3"


def test_describe_enis_boto3_fallback():
    mock_ec2 = MagicMock()
    mock_ec2.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [{
            "NetworkInterfaceId": "eni-boto3",
            "Attachment": {"AttachmentId": "eni-attach-boto3"},
            "Status": "in-use",
            "Description": "test"
        }]
    }
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True), \
         _boto3_client(mock_ec2):
        client = AWSClient()
        enis = client.describe_network_interfaces("vpc-123")
        assert len(enis) == 1
        assert enis[0]["id"] == "eni-boto3"


def test_describe_security_groups_boto3_fallback():
    mock_ec2 = MagicMock()
    mock_ec2.describe_security_groups.return_value = {
        "SecurityGroups": [
            {"GroupId": "sg-boto3", "GroupName": "test-sg", "Tags": []},
            {"GroupId": "sg-default", "GroupName": "default", "Tags": []}
        ]
    }
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True), \
         _boto3_client(mock_ec2):
        client = AWSClient()
        sgs = client.describe_security_groups("vpc-123")
        assert len(sgs) == 1
        assert sgs[0]["id"] == "sg-boto3"


def test_describe_vpc_endpoints_boto3_fallback():
    mock_ec2 = MagicMock()
    mock_ec2.describe_vpc_endpoints.return_value = {
        "VpcEndpoints": [
            {"VpcEndpointId": "vpce-boto3", "State": "available"}
        ]
    }
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True), \
         _boto3_client(mock_ec2):
        client = AWSClient()
        eps = client.describe_vpc_endpoints("vpc-123")
        assert len(eps) == 1
        assert eps[0]["id"] == "vpce-boto3"


def test_delete_stack_boto3_fallback():
    mock_cfn = MagicMock()
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", False), \
         patch("agents.aws_client._BOTO3_AVAILABLE", True), \
         _boto3_client(mock_cfn):
        client = AWSClient()
        ok, msg = client.delete_stack("my-stack")
        assert ok is True
        mock_cfn.delete_stack.assert_called_once_with(StackName="my-stack")


# ================================================================
# Region Handling
# ================================================================

def test_client_uses_specified_region():
    client = AWSClient(region="eu-west-1")
    assert client.region == "eu-west-1"


def test_default_region():
    client = AWSClient()
    assert client.region == "us-west-2"


# ================================================================
# Log Function
# ================================================================

def test_log_function_called():
    logs = []
    client = AWSClient(log_fn=lambda msg, level: logs.append((msg, level)))
    with patch("agents.aws_client._AWS_CLI_AVAILABLE", True), \
         patch("agents.aws_client._BOTO3_AVAILABLE", False), \
         patch("subprocess.run", return_value=_mock_run(returncode=1, stderr="error")):
        client.describe_stack_status("my-stack")
    assert any("debug" in log[1] for log in logs)
