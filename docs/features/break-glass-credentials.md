# 4.22 Feature Testing: External Auth Break-Glass Credentials

| Field | Value |
|-------|-------|
| Feature ID | `break_glass_credentials` |
| CLI Flag | `--feature break-glass` |
| Category | Security & Authentication |
| Phase | Day1 (post-provision) |
| Type | action |
| Mutable | No |
| Requires Input | Yes (`cluster_id` — OCM cluster ID) |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.externalAuthProviders` |
| Min Version | 4.19 |
| Dependency | `external_oidc` (auto-resolved) |
| Ansible Variable | `break_glass_credentials` |
| Feature Flag Variable | `feature_break_glass_credentials_enabled` |

## Description

Validates that OCM break-glass credential list/create operations work on
external-auth ROSA HCP clusters. When a 403 Forbidden is detected, the
diagnostic identifies the root cause from four scenarios:

1. **AMS role denial** — OCM credential lacks `cluster_owner` or
   `cluster_service_developer` role (most common in customer escalations)
2. **Missing provisioner kubeconfig secrets** — deleted during ArgoCD adoption
3. **External auth not enabled** — break-glass requires external auth
4. **Invalid/expired OCM token**

## Usage

Run the playbook directly:

```bash
ansible-playbook playbooks/verify_break_glass_credentials.yml \
  -e cluster_id=<ocm_cluster_id> \
  -e cluster_name=<cluster_name> \
  -e OCP_HUB_API_URL=<hub_api> \
  -e OCP_HUB_CLUSTER_USER=<user> \
  -e OCP_HUB_CLUSTER_PASSWORD=<password>
```

### Diagnostic Flow

```
PHASE 1 — Preflight
  |-- Validate cluster_id is provided
  |-- Get cluster info from OCM API
  |-- Check external auth is enabled
  |-- Check bootstrap-kubeconfig secret exists on provisioner
  |-- Set break_glass_preflight_passed

PHASE 2 — Break-Glass Credential Lifecycle
  |-- List existing break-glass credentials (GET)
  |-- Detect 403 on list → set break_glass_403_detected
  |-- Detect 'Forbidden access' → set break_glass_403_is_ams_denial
  |-- Create new break-glass credential (POST)
  |-- Detect 403 on create → set break_glass_403_detected
  |-- Poll for credential to reach 'issued' status (20x, 30s)
  |-- Retrieve kubeconfig for issued credential (no_log: true)
  |-- Validate kubeconfig content

PHASE 3 — 403 Diagnosis (if detected)
  |-- Check OCM token validity (ocm whoami)
  |-- Check cluster limited support status
  |-- Query OCM role bindings for cluster_owner / cluster_service_developer
  |-- Inventory provisioner secrets in CAPI namespace
  |-- Check CAPA controller logs for break-glass errors
  |-- Determine root cause (priority order):
  |     1. AMS role denial (Forbidden access pattern)
  |     2. Missing kubeconfig secrets
  |     3. External auth not enabled
  |     4. Invalid OCM token
  |     5. Unknown (low confidence)
  |-- Generate remediation steps

FINAL — Summary + fail/pass
```

## Prerequisites

- `ocm` CLI authenticated (`ocm login --token=...`)
- `oc` CLI with access to the provisioner/hub cluster
- Cluster must have `enableExternalAuthProviders: true`
- OCM credential must have `cluster_owner` or `cluster_service_developer` AMS role

### Provisioning a ROSA HCP Cluster with External Auth via CAPA

Break-glass credentials require a cluster provisioned with external authentication
enabled. To provision using this framework:

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature external-oidc \
  -e openshift_version=4.22.3 \
  -e name_prefix=my-cluster
```

This sets `enableExternalAuthProviders: true` on the ROSAControlPlane CR. The
`--feature break-glass` flag auto-resolves `external_oidc` as a dependency, but
the cluster must be provisioned with external auth first — it cannot be enabled
after creation.

The provisioning template (`templates/versions/4.22/features/rosa-combined-automation.yaml.j2`)
renders the following when `external_oidc` is enabled:

```yaml
spec:
  enableExternalAuthProviders: true
```

When `oidc_issuer_url` is also provided, the template additionally renders the
`externalAuthProviders` array with issuer, audiences, and claim mappings:

```yaml
spec:
  enableExternalAuthProviders: true
  externalAuthProviders:
    - name: capa-e2e-oidc
      issuer:
        issuerURL: <oidc_issuer_url>
        audiences:
          - <oidc_client_id>
      claimMappings:
        username:
          claim: email
```

### Connecting to an IDP

When `external_oidc` is enabled without providing an `oidc_issuer_url`, only
`enableExternalAuthProviders: true` is set on the cluster. The
`setup_oidc_provider.yml` task (run during break-glass verification) will
attempt to query or create a ROSA OIDC config via OCM, but this is the STS
OIDC config — not a user-facing IDP.

To connect a custom IDP (e.g., Entra ID, Okta, Keycloak), pass the IDP
configuration at provision time:

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature external-oidc \
  -e openshift_version=4.22.3 \
  -e name_prefix=my-cluster \
  -e oidc_issuer_url=https://login.microsoftonline.com/<tenant>/v2.0 \
  -e oidc_client_id=<app-registration-client-id> \
  -e oidc_username_claim=email \
  -e oidc_groups_claim=groups
```

With external auth enabled, the standard `kubeadmin` login is disabled. Access
is through:
1. **Break-glass credentials** — temporary kubeconfig via OCM API (what this
   playbook tests)
2. **IDP login** — once the external auth provider is configured and users are
   mapped

## Files

| File | Purpose |
|------|---------|
| `playbooks/verify_break_glass_credentials.yml` | Orchestrator — 3-phase playbook |
| `tasks/break_glass_preflight.yml` | Phase 1 — cluster/secret validation |
| `tasks/break_glass_create_credential.yml` | Phase 2 — credential lifecycle: list existing, create new, poll for issuance, retrieve kubeconfig, detect 403 |
| `tasks/break_glass_diagnose_403.yml` | Phase 3 — root cause analysis with AMS role check |
| `templates/schemas/feature-registry.yml` | Feature definition with external_oidc dependency |

## Root Cause Scenarios

### 1. AMS Role Denial (High Confidence)

The OCM credential used by CAPA does not have `cluster_owner` or
`cluster_service_developer` role. AMS `access_review` denies the
`ClusterBreakGlassCredential` resource type. Note that `sre_agent` and
`uhc_support` roles are explicitly excluded from this permission.

**Detection**: 403 response contains `"Forbidden access"` pattern, or OCM role
bindings query shows neither `cluster_owner` nor `cluster_service_developer`.

**Remediation**:
1. Verify the OCM token/credential used by CAPA has `cluster_owner` role
2. Update the CAPA OCM secret on the provisioner
3. Restart CAPA controller
4. Retry break-glass operations

### 2. Missing Provisioner Kubeconfig Secrets (High Confidence)

Customer deleted `<cluster_name>-kubeconfig` and/or
`<cluster_name>-bootstrap-kubeconfig` secrets from the CAPI namespace
(common during ArgoCD adoption).

**Detection**: `oc get secret` returns not-found for one or both secrets.

**Remediation**:
1. Recreate kubeconfig secrets from the Management Cluster
2. Restart CAPA controller
3. Retry break-glass operations

### 3. External Auth Not Enabled (High Confidence)

Break-glass credentials require `enableExternalAuthProviders: true` on
the ROSAControlPlane. If external auth is disabled, the OCM API rejects
break-glass operations.

**Detection**: OCM cluster info shows `external_auth_config.enabled: false`.

### 4. Invalid OCM Token (High Confidence)

The OCM CLI token is expired or invalid.

**Detection**: `ocm whoami` returns non-zero exit code.

## Jenkins Integration

Set `CLUSTER_FEATURES=break-glass` in the Jenkins job parameters. Pass
the OCM cluster ID via `EXTRA_FEATURE_VARS=cluster_id=<ocm_id>`.

## Test Coverage

| Test | File | What it verifies |
|------|------|-----------------|
| `test_break_glass_alias` | `tests/test_feature_manager.py` | `break-glass` resolves to `break_glass_credentials` |
| `test_break_glass_in_cli_features` | `tests/test_feature_manager.py` | Feature is listed in CLI features |
| `test_break_glass_feature_metadata` | `tests/test_feature_manager.py` | Type is `action`, resource is `ROSAControlPlane` |
| `test_break_glass_depends_on_external_oidc` | `tests/test_feature_manager.py` | Auto-resolves `external_oidc` dependency |
| `test_break_glass_valid_on_419` | `tests/test_feature_manager.py` | Valid on 4.19+ |
| `test_break_glass_invalid_on_418` | `tests/test_feature_manager.py` | Rejected on 4.18 |
| `test_break_glass_valid_on_422` | `tests/test_feature_manager.py` | Valid on 4.22 |
| `test_break_glass_var_mapping` | `tests/test_feature_manager.py` | `feature_break_glass_credentials_enabled` set |
| `test_break_glass_alias_resolves_in_extra_vars` | `tests/test_feature_manager.py` | `break-glass` alias resolves correctly in extra vars |
| `test_break_glass_not_in_418_list` | `tests/test_feature_manager.py` | Excluded from 4.18 feature list |
| `test_break_glass_in_419_list` | `tests/test_feature_manager.py` | Included in 4.19 feature list |

## Security Considerations

- `no_log: true` on kubeconfig retrieval prevents CI log exposure
- OCM email and organization ID are masked in diagnostic output
- All templated shell variables are quoted to prevent injection
- Only credential ID is stored (not full API response)
- SRE tokens are explicitly noted as excluded from break-glass permissions

## Live Testing

Verified end-to-end on 2026-07-08 against a real ROSA HCP cluster.

**Environment:**
- Hub cluster: ACM/MCE on VMware (qe6)
- ROSA HCP version: 4.22.3
- Region: us-west-2
- External auth: `enableExternalAuthProviders: true`
- Provisioned via: `./run-test-suite.py 20-rosa-hcp-provision --feature external-oidc -e openshift_version=4.22.3`

**Results (5 runs):**

```
BREAK-GLASS CREDENTIALS VERIFICATION SUMMARY
═══════════════════════════════════════════════════════════════

Cluster: [redacted]
Cluster ID: [redacted]

───────────────────────────────────────────────────────────────
RESULTS:
  ✓ Preflight checks: PASSED
  ✓ Credential creation: SUCCESS
  ✓ 403 Error: NOT DETECTED
═══════════════════════════════════════════════════════════════

PLAY RECAP
localhost: ok=36  changed=2  unreachable=0  failed=0  skipped=38  rescued=0  ignored=0
```

**Credential lifecycle verified:**
1. Listed existing break-glass credentials (GET) — 200 OK
2. Created new break-glass credential (POST) — 201 Created
3. Polled for credential issuance — status reached `issued`
4. Retrieved kubeconfig for issued credential — valid content

**Preflight validation confirmed:**
- Cluster exists in OCM: YES
- External auth enabled: YES
- Kubeconfig secret: MISSING (expected for external-auth clusters)
- Bootstrap kubeconfig secret: EXISTS

**Bugs found and fixed during live testing:** 21 (see commit history on this branch)

## Related

- [External OIDC](external-oidc.md) (auto-resolved dependency)
- [PR #70](https://github.com/stolostron/rosa-hcp-e2e-test/pull/70)
