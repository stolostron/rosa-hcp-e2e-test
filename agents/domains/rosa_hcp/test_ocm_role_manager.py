#!/usr/bin/env python3
"""Tests for OcmRoleManager."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from agents.domains.rosa_hcp.ocm_role_manager import (
    OcmRoleManager,
    get_ocm_token,
    ensure_ocm_role_from_env,
    SSO_TOKEN_URL,
)


class _MockClientError(Exception):
    """Stand-in for botocore.exceptions.ClientError when boto3 is not installed."""
    def __init__(self, error_response, operation_name):
        self.response = error_response
        self.operation_name = operation_name
        super().__init__(f"{operation_name}: {error_response}")


# Resolve the real ClientError if available, otherwise use our mock
try:
    from botocore.exceptions import ClientError
except ImportError:
    ClientError = _MockClientError


def _make_mgr(**kwargs):
    defaults = dict(
        ocm_client_id="test-id",
        ocm_client_secret="test-secret",
        ocm_api_url="https://api.test.openshift.com",
        aws_account_id="123456789012",
        installer_role_arn="arn:aws:iam::999999999999:role/TestInstaller",
    )
    defaults.update(kwargs)
    mgr = OcmRoleManager(**defaults)
    mgr.iam = MagicMock()
    mgr.sts = MagicMock()
    return mgr


def _mock_urlopen(response_data):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# Patch the module-level boto3 to be truthy for ensure_ocm_role tests
_BOTO3_TRUTHY = MagicMock()


# ================================================================
# get_ocm_token (standalone function)
# ================================================================

class TestGetOcmToken:
    @patch("agents.domains.rosa_hcp.ocm_role_manager.urllib.request.urlopen")
    def test_returns_token(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"access_token": "tok-123"})
        assert get_ocm_token("cid", "csecret") == "tok-123"

    @patch("agents.domains.rosa_hcp.ocm_role_manager.urllib.request.urlopen")
    def test_raises_on_missing_token(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"error_description": "bad creds"})
        with pytest.raises(RuntimeError, match="bad creds"):
            get_ocm_token("cid", "csecret")

    @patch("agents.domains.rosa_hcp.ocm_role_manager.urllib.request.urlopen")
    def test_sends_correct_request(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"access_token": "t"})
        get_ocm_token("my-id", "my-secret")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == SSO_TOKEN_URL
        assert req.get_header("Content-type") == "application/x-www-form-urlencoded"
        body = req.data.decode()
        assert "client_id=my-id" in body
        assert "client_secret=my-secret" in body


# ================================================================
# check_iam_role_exists
# ================================================================

class TestCheckIamRoleExists:
    def test_finds_ocm_role(self):
        mgr = _make_mgr()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Roles": [
                {"RoleName": "some-other-role", "Arn": "arn:aws:iam::123:role/other"},
                {"RoleName": "ManagedOpenShift-OCM-Role-12345678", "Arn": "arn:aws:iam::123:role/ManagedOpenShift-OCM-Role-12345678"},
            ]}
        ]
        mgr.iam.get_paginator.return_value = paginator
        assert mgr.check_iam_role_exists() == "arn:aws:iam::123:role/ManagedOpenShift-OCM-Role-12345678"

    def test_returns_none_when_no_ocm_role(self):
        mgr = _make_mgr()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Roles": [{"RoleName": "unrelated-role", "Arn": "arn:aws:iam::123:role/unrelated"}]}
        ]
        mgr.iam.get_paginator.return_value = paginator
        assert mgr.check_iam_role_exists() is None

    def test_warns_on_multiple_ocm_roles(self):
        mgr = _make_mgr()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Roles": [
                {"RoleName": "ManagedOpenShift-OCM-Role-11111111", "Arn": "arn:aws:iam::123:role/ManagedOpenShift-OCM-Role-11111111"},
                {"RoleName": "ManagedOpenShift-OCM-Role-22222222", "Arn": "arn:aws:iam::123:role/ManagedOpenShift-OCM-Role-22222222"},
            ]}
        ]
        mgr.iam.get_paginator.return_value = paginator
        result = mgr.check_iam_role_exists()
        assert result == "arn:aws:iam::123:role/ManagedOpenShift-OCM-Role-11111111"

    def test_raises_without_iam_client(self):
        mgr = _make_mgr()
        mgr.iam = None
        with pytest.raises(RuntimeError, match="boto3 not available"):
            mgr.check_iam_role_exists()


# ================================================================
# create_iam_role
# ================================================================

class TestCreateIamRole:
    def test_creates_role_and_attaches_policies(self):
        mgr = _make_mgr()
        mgr.iam.create_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::123456789012:role/ManagedOpenShift-OCM-Role-99999999"}
        }
        result = mgr.create_iam_role("ext-id-123")
        assert "ManagedOpenShift-OCM-Role" in result
        mgr.iam.create_role.assert_called_once()
        mgr.iam.put_role_policy.assert_called_once()
        mgr.iam.attach_role_policy.assert_called_once()

    def test_raises_without_installer_role_arn(self):
        mgr = _make_mgr(installer_role_arn="")
        with pytest.raises(RuntimeError, match="installer_role_arn is required"):
            mgr.create_iam_role("ext-id")

    def test_raises_without_iam_client(self):
        mgr = _make_mgr()
        mgr.iam = None
        with pytest.raises(RuntimeError, match="boto3 not available"):
            mgr.create_iam_role("ext-id")

    def test_resolves_account_id_from_sts(self):
        mgr = _make_mgr(aws_account_id="")
        mgr.sts.get_caller_identity.return_value = {"Account": "987654321098"}
        mgr.iam.create_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::987654321098:role/test"}
        }
        mgr.create_iam_role("ext-id")
        assert mgr.aws_account_id == "987654321098"

    def test_raises_when_both_policies_fail(self):
        mgr = _make_mgr()
        mgr.iam.create_role.return_value = {"Role": {"Arn": "arn:aws:iam::123:role/test"}}
        mgr.iam.put_role_policy.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutRolePolicy"
        )
        mgr.iam.attach_role_policy.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no"}}, "AttachRolePolicy"
        )
        with pytest.raises(RuntimeError, match="no policies could be attached"):
            mgr.create_iam_role("ext-id")

    def test_succeeds_with_only_inline_policy(self):
        mgr = _make_mgr()
        mgr.iam.create_role.return_value = {"Role": {"Arn": "arn:aws:iam::123:role/test"}}
        mgr.iam.attach_role_policy.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no"}}, "AttachRolePolicy"
        )
        assert "arn:aws:iam" in mgr.create_iam_role("ext-id")

    def test_trust_policy_uses_installer_role_arn(self):
        mgr = _make_mgr(installer_role_arn="arn:aws:iam::111:role/MyInstaller")
        mgr.iam.create_role.return_value = {"Role": {"Arn": "arn:aws:iam::123:role/test"}}
        mgr.create_iam_role("ext-id")
        doc = json.loads(mgr.iam.create_role.call_args[1]["AssumeRolePolicyDocument"])
        assert doc["Statement"][0]["Principal"]["AWS"] == ["arn:aws:iam::111:role/MyInstaller"]


# ================================================================
# check_ocm_role_linked
# ================================================================

class TestCheckOcmRoleLinked:
    def test_returns_true_when_external_id_present(self):
        mgr = _make_mgr()
        with patch.object(mgr, "_api_request", return_value={"external_id": "ext-123"}):
            assert mgr.check_ocm_role_linked("token", "org-1") is True

    def test_returns_true_when_role_binding_has_ocm(self):
        mgr = _make_mgr()
        resp = {"role_bindings": [{"role": {"id": "OCMRole"}}], "external_id": ""}
        with patch.object(mgr, "_api_request", return_value=resp):
            assert mgr.check_ocm_role_linked("token", "org-1") is True

    def test_returns_false_when_no_linkage(self):
        mgr = _make_mgr()
        with patch.object(mgr, "_api_request", return_value={"role_bindings": [], "external_id": ""}):
            assert mgr.check_ocm_role_linked("token", "org-1") is False

    def test_returns_false_on_api_error(self):
        mgr = _make_mgr()
        with patch.object(mgr, "_api_request", side_effect=Exception("network")):
            assert mgr.check_ocm_role_linked("token", "org-1") is False

    def test_handles_role_bindings_as_dict(self):
        mgr = _make_mgr()
        resp = {"role_bindings": {"items": [{"role": {"id": "OCMRoleBinding"}}]}, "external_id": ""}
        with patch.object(mgr, "_api_request", return_value=resp):
            assert mgr.check_ocm_role_linked("token", "org-1") is True


# ================================================================
# ensure_ocm_role (orchestrator)
# ================================================================

class TestEnsureOcmRole:
    def test_existing_role_linked(self):
        mgr = _make_mgr()
        with patch("agents.domains.rosa_hcp.ocm_role_manager.boto3", _BOTO3_TRUTHY), \
             patch.object(mgr, "check_iam_role_exists", return_value="arn:aws:iam::123:role/OCM-Role-1"), \
             patch.object(mgr, "get_ocm_access_token", return_value="tok"), \
             patch.object(mgr, "get_ocm_organization", return_value={"id": "org-1"}), \
             patch.object(mgr, "check_ocm_role_linked", return_value=True):
            ok, msg = mgr.ensure_ocm_role()
            assert ok is True
            assert "linked to organization org-1" in msg

    def test_existing_role_not_linked(self):
        mgr = _make_mgr()
        with patch("agents.domains.rosa_hcp.ocm_role_manager.boto3", _BOTO3_TRUTHY), \
             patch.object(mgr, "check_iam_role_exists", return_value="arn:aws:iam::123:role/OCM-Role-1"), \
             patch.object(mgr, "get_ocm_access_token", return_value="tok"), \
             patch.object(mgr, "get_ocm_organization", return_value={"id": "org-1"}), \
             patch.object(mgr, "check_ocm_role_linked", return_value=False):
            ok, msg = mgr.ensure_ocm_role()
            assert ok is True
            assert "could not confirm linkage" in msg

    def test_creates_new_role(self):
        mgr = _make_mgr()
        with patch("agents.domains.rosa_hcp.ocm_role_manager.boto3", _BOTO3_TRUTHY), \
             patch.object(mgr, "check_iam_role_exists", return_value=None), \
             patch.object(mgr, "get_ocm_access_token", return_value="tok"), \
             patch.object(mgr, "get_ocm_organization", return_value={"id": "org-1", "external_id": "ext-1"}), \
             patch.object(mgr, "create_iam_role", return_value="arn:aws:iam::123:role/New-OCM-Role"), \
             patch.object(mgr, "check_ocm_role_linked", return_value=True):
            ok, msg = mgr.ensure_ocm_role()
            assert ok is True
            assert "Created and linked" in msg

    def test_dry_run_skips_creation(self):
        mgr = _make_mgr(dry_run=True)
        with patch("agents.domains.rosa_hcp.ocm_role_manager.boto3", _BOTO3_TRUTHY), \
             patch.object(mgr, "check_iam_role_exists", return_value=None):
            ok, msg = mgr.ensure_ocm_role()
            assert ok is True
            assert "DRY RUN" in msg

    def test_returns_false_without_boto3(self):
        mgr = _make_mgr()
        with patch("agents.domains.rosa_hcp.ocm_role_manager.boto3", None):
            ok, msg = mgr.ensure_ocm_role()
            assert ok is False
            assert "boto3" in msg

    def test_handles_creation_failure(self):
        mgr = _make_mgr()
        with patch("agents.domains.rosa_hcp.ocm_role_manager.boto3", _BOTO3_TRUTHY), \
             patch.object(mgr, "check_iam_role_exists", return_value=None), \
             patch.object(mgr, "get_ocm_access_token", return_value="tok"), \
             patch.object(mgr, "get_ocm_organization", return_value={"id": "org-1", "external_id": "ext-1"}), \
             patch.object(mgr, "create_iam_role", side_effect=RuntimeError("IAM failed")):
            ok, msg = mgr.ensure_ocm_role()
            assert ok is False
            assert "IAM failed" in msg


# ================================================================
# ensure_ocm_role_from_env
# ================================================================

class TestEnsureOcmRoleFromEnv:
    def test_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            ok, msg = ensure_ocm_role_from_env()
            assert ok is False
            assert "OCM_CLIENT_ID" in msg

    @patch("agents.domains.rosa_hcp.ocm_role_manager.OcmRoleManager.ensure_ocm_role")
    def test_passes_env_vars(self, mock_ensure):
        mock_ensure.return_value = (True, "ok")
        env = {
            "OCM_CLIENT_ID": "cid",
            "OCM_CLIENT_SECRET": "csecret",
            "OCM_API_URL": "https://api.test",
            "AWS_ACCOUNT_ID": "123",
            "RH_INSTALLER_ROLE_ARN": "arn:aws:iam::999:role/Test",
        }
        with patch.dict(os.environ, env, clear=True):
            ok, msg = ensure_ocm_role_from_env()
            assert ok is True


# ================================================================
# get_ocm_organization
# ================================================================

class TestGetOcmOrganization:
    def test_returns_org(self):
        mgr = _make_mgr()
        with patch.object(mgr, "_api_request", return_value={"organization": {"id": "org-abc"}, "username": "test"}):
            assert mgr.get_ocm_organization("tok")["id"] == "org-abc"

    def test_raises_when_no_org(self):
        mgr = _make_mgr()
        with patch.object(mgr, "_api_request", return_value={"organization": {}, "username": "test"}):
            with pytest.raises(RuntimeError, match="No organization found"):
                mgr.get_ocm_organization("tok")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
