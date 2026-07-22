# OCM Role Pre-Flight Check

## Problem

When provisioning ROSA HCP clusters, if the `ManagedOpenShift-OCM-Role` IAM role is missing from the AWS account, provisioning fails silently after **~45 minutes** with a `CLUSTERS-MGMT-403` error. There is no early warning -- the cluster creation simply times out.

This was discovered during CI runs on Jenkins workers that had been reprovisioned without the OCM role pre-configured.

## Solution

A pre-flight check runs **before** any resources are created. It validates the OCM role exists in AWS IAM, and if missing, auto-creates and links it to the OCM organization -- all via boto3 and the OCM REST API (no `rosa` or `aws` CLI required).

### Where it fits in the provisioning flow

```
provision_rosa_hcp_with_automation.yml
│
├── PRE-FLIGHT: OCM role check          <── new
│   └── preflight_check_ocm_role.yml
│       └── OcmRoleManager.ensure_ocm_role()
│
├── STEP 1: Create RosaRoleConfig       (Installer, Support, Worker roles)
├── STEP 2: Create ROSANetwork          (VPC, subnets, NAT gateways)
└── STEP 3: Create RosaControlPlane     (the cluster itself)
```

## How it works

### 1. The playbook triggers the check

The provisioning playbook includes the pre-flight when `create_rosa_roles` is enabled:

```yaml
# provision_rosa_hcp_with_automation.yml (line 153)

- name: Verify OCM role is linked to AWS account
  when: create_rosa_roles | bool
  block:
    - name: Display OCM role pre-flight check message
      debug:
        msg: |
          PRE-FLIGHT: Checking OCM role linkage
          Verifying that an OCM role exists in AWS IAM and is linked
          to the OCM organization. If missing, will auto-create it.

    - name: Run OCM role pre-flight check
      include_tasks: preflight_check_ocm_role.yml
```

### 2. The pre-flight scans IAM for existing roles

```yaml
# preflight_check_ocm_role.yml

- name: Check for OCM role in AWS IAM
  shell: |
    python3 -c "
    import json, sys, boto3
    iam = boto3.client('iam')
    paginator = iam.get_paginator('list_roles')
    for page in paginator.paginate():
        for role in page['Roles']:
            if 'OCM-Role' in role['RoleName']:
                print(json.dumps({
                    'exists': True,
                    'arn': role['Arn'],
                    'name': role['RoleName']
                }))
                sys.exit(0)
    print(json.dumps({'exists': False}))
    "
  register: ocm_role_check_result
```

If found: provisioning continues normally.
If missing: `OcmRoleManager` takes over.

### 3. `OcmRoleManager` creates and links the role

The manager orchestrates four steps -- authenticate with OCM, get the org, create the IAM role, and link it:

```python
# agents/domains/rosa_hcp/ocm_role_manager.py

class OcmRoleManager:
    def ensure_ocm_role(self) -> Tuple[bool, str]:
        # Step 1: Check if role already exists
        existing_arn = self.check_iam_role_exists()
        if existing_arn:
            # Verify linkage, link if needed
            token = self.get_ocm_access_token()
            org = self.get_ocm_organization(token)
            if self.check_ocm_role_linked(token, org["id"]):
                return True, f"{existing_arn} -- linked to org {org['id']}"
            self.link_ocm_role(token, org["id"], existing_arn)
            return True, f"{existing_arn} -- newly linked"

        # Step 2: Create from scratch
        token = self.get_ocm_access_token()
        org = self.get_ocm_organization(token)
        new_arn = self.create_iam_role(org.get("external_id", org["id"]))
        self.link_ocm_role(token, org["id"], new_arn)
        return True, f"Created and linked: {new_arn}"
```

The IAM role is created with a trust policy pointing to Red Hat's managed installer:

```python
# The trust policy allows Red Hat's installer to assume the role
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {
            "AWS": ["arn:aws:iam::644306948063:role/RH-Managed-OpenShift-Installer"]
        },
        "Action": ["sts:AssumeRole"],
        "Condition": {
            "StringEquals": {"sts:ExternalId": external_id}
        },
    }]
}

role_name = f"ManagedOpenShift-OCM-Role-{random_suffix}"
self.iam.create_role(
    RoleName=role_name,
    AssumeRolePolicyDocument=json.dumps(trust_policy),
)
```

## How the agent framework would catch this without the pre-flight

If the pre-flight were not in place, the agent framework's detection pipeline would eventually catch the `403` -- but only after the 45-minute timeout:

```
MonitoringAgent.process_line()
│
│   line: "CLUSTERS-MGMT-403: insufficient permissions"
│   matches pattern: (ocm|openshift cluster manager).*(401|403|unauthorized|forbidden)
│
├── TrackedIssue created
│     state: DETECTED
│     issue_type: "ocm_auth_failure"
│
├── DiagnosticAgent.diagnose("ocm_auth_failure", context)
│   │
│   ├── confidence: 0.7
│   ├── _apply_learned_confidence()
│   │     # Blends historical outcomes (capped at +/- 0.1)
│   │     delta = max(-0.1, min(0.1, learned - original))
│   │     adjusted = round(original + delta, 2)
│   │     evidence: "Confidence adjusted 0.7 -> 0.8
│   │                (learned from 4 consecutive successes)"
│   │
│   └── returns diagnosis:
│         recommended_fix: "refresh_ocm_token"
│         confidence: 0.8
│
└── RemediationAgent.remediate(diagnosis)
      fix: refresh_ocm_token
      result: (False, "Cannot fix missing OCM role -- role does not exist")
```

The pre-flight eliminates this entire failure path by catching it in **seconds** instead of 45 minutes.

## What the learning agent tracks

When remediation succeeds or fails, the learning agent adjusts confidence scores in `known_issues.json`. These adjustments feed back into future diagnoses:

```json
// agents/knowledge_base/known_issues.json

{
  "type": "cloudformation_deletion_failure",
  "severity": "high",
  "auto_fix": true,
  "learned_confidence": 1.0,
  "last_adjusted": "2026-03-31T16:10:22",
  "adjustment_reason": "4 consecutive successes in last 4 runs"
}
```

```python
# agents/learning_agent.py -- how confidence adjusts over time

def _apply_confidence_adjustments(self, adjustments):
    for adj in adjustments:
        for pattern in patterns:
            if pattern["type"] == adj["issue_type"]:
                old = pattern.get("learned_confidence", 0.9)
                new = max(0.3, min(1.0, old + adj["delta"]))
                pattern["learned_confidence"] = round(new, 2)
                pattern["adjustment_reason"] = adj["reason"]
```

Confidence is bounded between `0.3` and `1.0`. The diagnostic agent applies this as a nudge (capped at +/- 0.1) so learned history informs but never overrides the current diagnosis.

## Environment requirements

| Variable | Purpose |
|----------|---------|
| `AWS_ACCESS_KEY_ID` | IAM role creation and lookup |
| `AWS_SECRET_ACCESS_KEY` | IAM role creation and lookup |
| `AWS_ACCOUNT_ID` | Role ARN construction (auto-detected via STS if omitted) |
| `OCM_CLIENT_ID` | OCM OAuth2 authentication |
| `OCM_CLIENT_SECRET` | OCM OAuth2 authentication |
| `OCM_API_URL` | OCM endpoint (defaults to stage) |

## Related files

| File | Purpose |
|------|---------|
| `tasks/preflight_check_ocm_role.yml` | Ansible pre-flight task |
| `agents/domains/rosa_hcp/ocm_role_manager.py` | IAM + OCM API operations |
| `tasks/provision_rosa_hcp_with_automation.yml` | Integration point (line 153) |
| `agents/knowledge_base/known_issues.json` | `ocm_auth_failure` pattern definition |
| `agents/knowledge_base/fix_strategies.json` | `ocm_auth_failure` fix strategy |
