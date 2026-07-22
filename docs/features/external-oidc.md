# 4.22 Feature Testing: External OIDC

| Field | Value |
|-------|-------|
| Feature ID | `external_oidc` |
| CLI Flag | `--feature external-oidc` |
| Category | Security & Authentication |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.enableExternalAuthProviders` |
| Min Version | 4.19 |
| Ansible Variable | `external_oidc` |

## Description

Enables external OIDC authentication on the cluster. Sets
`enableExternalAuthProviders: true` and configures the `externalAuthProviders`
array with issuer URL, audiences, and claim mappings.

Required for break-glass credential operations.

## Usage

### Basic (flag only)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature external-oidc
```

### With OIDC provider details

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature external-oidc \
  -e oidc_issuer_url=https://login.microsoftonline.com/<tenant>/v2.0 \
  -e oidc_client_id=<client_id>
```

## Template Rendering

When `external_oidc` is `true` with OIDC details provided:

```yaml
spec:
  enableExternalAuthProviders: true
  externalAuthProviders:
    - name: capa-e2e-oidc
      issuer:
        issuerURL: https://login.microsoftonline.com/<tenant>/v2.0
        audiences:
          - <client_id>
      claimMappings:
        username:
          claim: email
          prefixPolicy: ""
      oidcClients:
        - componentName: console
          componentNamespace: openshift-console
          clientID: <client_id>
```

Without OIDC details, only `enableExternalAuthProviders: true` is rendered.

## Verification

### External auth enabled (OCM API + CRD fallback)

Uses OCM API to verify external OIDC is enabled on the cluster:

```text
GET /api/clusters_mgmt/v1/clusters/{id}
```

Falls back to ROSAControlPlane CRD if OCM is unavailable.

### OIDC issuer validation

Validates the OIDC issuer URL is reachable and returns a valid OpenID
Connect discovery document:

```bash
curl -s https://<issuer_url>/.well-known/openid-configuration
```

Asserts:
- `.external_auth_config.enabled` is true (via OCM)
- OIDC issuer URL returns HTTP 200 with valid discovery document
- Audiences array is non-empty
- Claim mappings (username claim) are configured

## Test Coverage

| Test | File | Description |
|------|------|-------------|
| `test_external_oidc_renders_enabled` | `tests/test_feature_manager.py` | `enableExternalAuthProviders: true` rendered (3 templates) |
| `test_external_oidc_with_issuer_renders_providers` | `tests/test_feature_manager.py` | Full `externalAuthProviders` block with issuerURL + audiences (3 templates) |
| `test_external_oidc_false_omits_providers` | `tests/test_feature_manager.py` | Absent when `external_oidc: false` (3 templates) |
| `test_default_omits_external_oidc` | `tests/test_feature_manager.py` | Absent by default (3 templates) |
| `test_external_oidc_claim_mappings` | `tests/test_feature_manager.py` | Custom `username.claim` renders correctly (3 templates) |
| `test_external_oidc_flag_only_no_providers` | `tests/test_feature_manager.py` | Flag without issuer URL renders only `enableExternalAuthProviders` (3 templates) |
| `test_external_oidc_oidc_clients_block` | `tests/test_feature_manager.py` | `oidcClients` with clientID + clientSecret (3 templates) |
| `test_external_oidc_oidc_clients_without_secret` | `tests/test_feature_manager.py` | `oidcClients` without `clientSecret` (3 templates) |
| `test_external_oidc_groups_claim` | `tests/test_feature_manager.py` | Groups claim + prefix rendering (3 templates) |
| `test_external_oidc_groups_claim_without_prefix` | `tests/test_feature_manager.py` | Groups claim without prefix (3 templates) |
| `test_external_oidc_no_groups_by_default` | `tests/test_feature_manager.py` | No groups block by default (3 templates) |
| `test_external_oidc_custom_audiences` | `tests/test_feature_manager.py` | Custom audiences list (3 templates) |
| `test_external_oidc_custom_provider_name` | `tests/test_feature_manager.py` | Custom provider name (3 templates) |
| `test_external_oidc_custom_prefix_policy` | `tests/test_feature_manager.py` | Custom `prefixPolicy` value (3 templates) |
| `test_external_oidc_feature_metadata` | `tests/test_feature_manager.py` | Registry: resource, k8s_field, min_version |
| `test_external_oidc_var_mapping` | `tests/test_feature_manager.py` | `external_oidc` in resolved extra vars |
| `test_external_oidc_alias` | `tests/test_feature_manager.py` | CLI alias `external-oidc` resolves to `external_oidc` |
| `test_external_oidc_rejected_on_418` | `tests/test_feature_manager.py` | Version gate rejects 4.18 |
| `test_external_oidc_valid_on_419` | `tests/test_feature_manager.py` | Version gate accepts 4.19+ |

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Break-Glass Credentials (depends on this feature — see PR #70)
- Feature Group: `day1-networking`
