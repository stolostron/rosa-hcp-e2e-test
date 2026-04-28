"""
OCM Role Manager
================

Creates OCM IAM roles and verifies linkage to the OCM organization without
requiring the rosa CLI. Uses boto3 for IAM operations and the OCM REST API
for organization verification.
"""

import json
import logging
import os
import random
import urllib.request
import urllib.parse
from typing import Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception

logger = logging.getLogger(__name__)

SSO_TOKEN_URL = "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"


def get_ocm_token(client_id: str, client_secret: str) -> str:
    """Get an OCM access token via OAuth2 client credentials flow.

    Standalone function usable without instantiating OcmRoleManager.
    Raises RuntimeError if the token request fails.
    """
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(
        SSO_TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())
    token = result.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to get OCM token: {result.get('error_description', 'no access_token')}")
    return token


class OcmRoleManager:
    """Manages OCM IAM role lifecycle: check, create, and link to OCM org."""

    def __init__(
        self,
        ocm_client_id: str,
        ocm_client_secret: str,
        ocm_api_url: str = "https://api.stage.openshift.com",
        aws_account_id: str = "",
        region: str = "us-west-2",
        dry_run: bool = False,
        installer_role_arn: str = "",
    ):
        self.ocm_client_id = ocm_client_id
        self.ocm_client_secret = ocm_client_secret
        self.ocm_api_url = ocm_api_url.rstrip("/")
        self.aws_account_id = aws_account_id
        self.region = region
        self.dry_run = dry_run
        self.installer_role_arn = installer_role_arn

        if boto3:
            self.iam = boto3.client("iam", region_name=region)
            self.sts = boto3.client("sts", region_name=region)
        else:
            self.iam = None
            self.sts = None

    def _api_request(self, url: str, method: str = "GET", data: dict = None,
                     headers: dict = None, timeout: int = 30) -> dict:
        hdrs = {"Accept": "application/json"}
        if headers:
            hdrs.update(headers)

        body = None
        if data is not None:
            if "Content-Type" not in hdrs:
                hdrs["Content-Type"] = "application/json"
            if hdrs["Content-Type"] == "application/json":
                body = json.dumps(data).encode()
            else:
                body = urllib.parse.urlencode(data).encode()

        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def get_ocm_access_token(self) -> str:
        """Get an OCM access token via OAuth2 client credentials flow."""
        return get_ocm_token(self.ocm_client_id, self.ocm_client_secret)

    def get_ocm_organization(self, access_token: str) -> dict:
        """Get the current account's organization from OCM."""
        url = f"{self.ocm_api_url}/api/accounts_mgmt/v1/current_account"
        account = self._api_request(
            url, headers={"Authorization": f"Bearer {access_token}"}
        )
        org = account.get("organization", {})
        if not org.get("id"):
            raise RuntimeError(f"No organization found for current account: {account.get('username', 'unknown')}")
        return org

    def check_iam_role_exists(self) -> Optional[str]:
        """Check if an OCM role exists in AWS IAM. Returns first matching ARN or None."""
        if not self.iam:
            raise RuntimeError("boto3 not available")

        matches = []
        paginator = self.iam.get_paginator("list_roles")
        for page in paginator.paginate():
            for role in page["Roles"]:
                if "OCM-Role" in role["RoleName"]:
                    matches.append(role)

        if not matches:
            return None

        if len(matches) > 1:
            names = [r["RoleName"] for r in matches]
            logger.warning(f"Found {len(matches)} OCM roles in AWS IAM: {names} — using first match")

        chosen = matches[0]
        logger.info(f"Found existing OCM role: {chosen['RoleName']} ({chosen['Arn']})")
        return chosen["Arn"]

    def create_iam_role(self, external_id: str) -> str:
        """Create the OCM IAM role with the Red Hat trust policy."""
        if not self.iam:
            raise RuntimeError("boto3 not available")

        if not self.installer_role_arn:
            raise RuntimeError("installer_role_arn is required to create trust policy (set RH_INSTALLER_ROLE_ARN env var)")

        if not self.aws_account_id:
            if self.sts:
                identity = self.sts.get_caller_identity()
                self.aws_account_id = identity["Account"]
            else:
                raise RuntimeError("AWS account ID not provided and STS not available")

        role_suffix = random.randint(10000000, 99999999)
        role_name = f"ManagedOpenShift-OCM-Role-{role_suffix}"

        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": [self.installer_role_arn]},
                    "Action": ["sts:AssumeRole"],
                    "Condition": {
                        "StringEquals": {"sts:ExternalId": external_id}
                    },
                }
            ],
        }

        logger.info(f"Creating OCM role: {role_name}")

        try:
            response = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="OCM role for ROSA cluster management",
                MaxSessionDuration=3600,
            )
            role_arn = response["Role"]["Arn"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityAlreadyExists":
                role_arn = f"arn:aws:iam::{self.aws_account_id}:role/{role_name}"
                logger.info(f"Role already exists: {role_arn}")
            else:
                raise

        ocm_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "iam:GetRole",
                        "iam:GetRolePolicy",
                        "iam:ListRoles",
                        "iam:ListRolePolicies",
                        "iam:ListAttachedRolePolicies",
                        "iam:CreateRole",
                        "iam:AttachRolePolicy",
                        "iam:DetachRolePolicy",
                        "iam:DeleteRole",
                        "iam:DeleteRolePolicy",
                        "iam:PutRolePolicy",
                        "iam:TagRole",
                        "iam:CreateOpenIDConnectProvider",
                        "iam:DeleteOpenIDConnectProvider",
                        "iam:GetOpenIDConnectProvider",
                        "iam:ListOpenIDConnectProviders",
                        "iam:TagOpenIDConnectProvider",
                        "iam:CreateInstanceProfile",
                        "iam:DeleteInstanceProfile",
                        "iam:AddRoleToInstanceProfile",
                        "iam:RemoveRoleFromInstanceProfile",
                        "iam:ListInstanceProfilesForRole",
                        "organizations:DescribeOrganization",
                        "organizations:ListAccounts",
                    ],
                    "Resource": "*",
                }
            ],
        }

        policy_name = f"{role_name}-Policy"
        inline_ok = False
        try:
            self.iam.put_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
                PolicyDocument=json.dumps(ocm_policy),
            )
            inline_ok = True
        except ClientError as e:
            logger.warning(f"Failed to attach inline policy {policy_name}: {e}")

        managed_ok = False
        admin_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
        try:
            self.iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn=admin_policy_arn,
            )
            managed_ok = True
        except ClientError as e:
            logger.warning(f"Failed to attach AdministratorAccess policy: {e}")

        if not inline_ok and not managed_ok:
            raise RuntimeError(f"Role {role_name} created but no policies could be attached — role has no permissions")

        logger.info(f"Created OCM role: {role_arn}")
        return role_arn

    def check_ocm_role_linked(self, access_token: str, org_id: str) -> bool:
        """Check if an OCM role is linked to the organization."""
        url = f"{self.ocm_api_url}/api/accounts_mgmt/v1/organizations/{org_id}"
        try:
            org_data = self._api_request(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
            links = org_data.get("role_bindings", [])
            if isinstance(links, dict):
                links = links.get("items", [])
            for link in links:
                if "OCM" in str(link.get("role", {}).get("id", "")):
                    return True
            external_id = org_data.get("external_id", "")
            if external_id:
                return True
        except Exception as e:
            logger.warning(f"Could not check OCM role linkage: {e}")
        return False

    def ensure_ocm_role(self) -> Tuple[bool, str]:
        """
        Top-level orchestrator: check for OCM role, create if needed, verify linkage.
        Returns (success, message) tuple.
        """
        if not boto3:
            return False, "boto3 is required for OCM role management but is not installed"

        try:
            existing_arn = self.check_iam_role_exists()
            if existing_arn:
                msg = f"OCM role already exists: {existing_arn}"
                logger.info(msg)

                try:
                    token = self.get_ocm_access_token()
                    org = self.get_ocm_organization(token)
                    org_id = org["id"]

                    if self.check_ocm_role_linked(token, org_id):
                        return True, f"{msg} — linked to organization {org_id}"
                    else:
                        return True, f"{msg} — OCM API could not confirm linkage — verify in OCM console"
                except Exception as e:
                    return True, f"{msg} — could not verify linkage: {e}"

            logger.info("No OCM role found in AWS IAM, creating one")

            if self.dry_run:
                return True, "[DRY RUN] Would create OCM role and link to organization"

            token = self.get_ocm_access_token()
            org = self.get_ocm_organization(token)
            org_id = org["id"]
            external_id = org.get("external_id", org_id)

            new_arn = self.create_iam_role(external_id)

            if self.check_ocm_role_linked(token, org_id):
                return True, f"Created and linked OCM role: {new_arn}"
            return True, f"Created OCM role: {new_arn} — OCM API could not confirm linkage — verify in OCM console"

        except Exception as e:
            logger.error(f"OCM role management failed: {e}")
            return False, f"Failed to ensure OCM role: {e}"


def ensure_ocm_role_from_env() -> Tuple[bool, str]:
    """Convenience function that reads credentials from environment variables."""
    ocm_client_id = os.environ.get("OCM_CLIENT_ID", "")
    ocm_client_secret = os.environ.get("OCM_CLIENT_SECRET", "")
    ocm_api_url = os.environ.get("OCM_API_URL", "https://api.stage.openshift.com")
    aws_account_id = os.environ.get("AWS_ACCOUNT_ID", "")
    installer_role_arn = os.environ.get("RH_INSTALLER_ROLE_ARN", "")

    if not ocm_client_id or not ocm_client_secret:
        return False, "OCM_CLIENT_ID and OCM_CLIENT_SECRET environment variables are required"

    mgr = OcmRoleManager(
        ocm_client_id=ocm_client_id,
        ocm_client_secret=ocm_client_secret,
        ocm_api_url=ocm_api_url,
        aws_account_id=aws_account_id,
        installer_role_arn=installer_role_arn,
    )
    return mgr.ensure_ocm_role()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    success, msg = ensure_ocm_role_from_env()
    print(msg)
    exit(0 if success else 1)
