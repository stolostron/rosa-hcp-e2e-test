#!/usr/bin/env python3
"""Tests for check_cfn_stack_status.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from check_cfn_stack_status import main


class _MockClientError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


def test_prints_stack_status(capsys):
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "DELETE_IN_PROGRESS"}]}
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_cfn

    with patch.dict(sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock()}), \
         patch("sys.argv", ["prog", "my-stack", "us-west-2"]):
        main()
    assert "DELETE_IN_PROGRESS" in capsys.readouterr().out


def test_prints_gone_when_no_stacks(capsys):
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.return_value = {"Stacks": []}
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_cfn

    with patch.dict(sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock()}), \
         patch("sys.argv", ["prog", "my-stack", "us-west-2"]):
        main()
    assert "GONE" in capsys.readouterr().out


def test_prints_gone_on_does_not_exist(capsys):
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.side_effect = _MockClientError("Stack does not exist")
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_cfn

    mock_botocore_exc = MagicMock()
    mock_botocore_exc.ClientError = _MockClientError

    with patch.dict(sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": mock_botocore_exc}), \
         patch("sys.argv", ["prog", "my-stack", "us-west-2"]):
        main()
    assert "GONE" in capsys.readouterr().out


def test_exits_2_without_boto3():
    with patch.dict(sys.modules, {"boto3": None}), \
         patch("builtins.__import__", side_effect=ImportError("no boto3")), \
         patch("sys.argv", ["prog", "my-stack", "us-west-2"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2


def test_exits_1_missing_args():
    with patch("sys.argv", ["prog"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
