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
`enableExternalAuthProviders: true` on the ROSAControlPlane. When
`oidc_issuer_url` is also provided, configures the `externalAuthProviders`
array with issuer URL, audiences, and claim mappings. Without an issuer URL,
only the boolean flag is set.

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

When `oidc_issuer_url` was provided at provision time, also asserts:
- OIDC issuer URL returns HTTP 200 with valid discovery document
- Audiences array is non-empty
- Claim mappings (username claim) are configured

## Live Testing

Verified on 2026-07-08 by provisioning a ROSA HCP 4.22.3 cluster with
`--feature external-oidc` via CAPA.

**Environment:**
- Hub cluster: ACM/MCE on VMware (qe6)
- ROSA HCP version: 4.22.3
- Region: us-west-2
- Provisioned via: `./run-test-suite.py 20-rosa-hcp-provision --feature external-oidc -e openshift_version=4.22.3 -e name_prefix=bg70`

**Results:**
- `enableExternalAuthProviders: true` confirmed in ROSAControlPlane spec
- Cluster reached `ready` state in 15 minutes
- Standard kubeconfig secret absent (expected — no `kubeadmin` on external-auth clusters)
- Bootstrap kubeconfig secret present
- Break-glass credential creation succeeded against the provisioned cluster
  (see [break-glass live testing](break-glass-credentials.md#live-testing))

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- [Break-Glass Credentials](break-glass-credentials.md) (depends on this feature)
- Feature Group: `day1-security`
