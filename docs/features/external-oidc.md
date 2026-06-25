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

Uses OCM API to verify external OIDC configuration:

GET /api/clusters_mgmt/v1/clusters/{id}

Asserts:
- `.external_auth_config.enabled` is true
- External authentication providers are properly configured
- Falls back to ROSAControlPlane K8s spec if OCM is unavailable

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Break-Glass Credentials (depends on this feature, not yet automated)
- Feature Group: `day1-networking`
