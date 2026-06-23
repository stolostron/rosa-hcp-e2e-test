# 4.22 Feature Testing: Domain Prefix

| Field | Value |
|-------|-------|
| Feature ID | `domain_prefix` |
| CLI Flag | `--feature domain` |
| Category | Configuration |
| Phase | Day1 |
| Type | string |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.domainPrefix` |
| Min Version | 4.18 |
| Ansible Variable | `domain_prefix` |

## Description

Sets a custom domain prefix for the cluster API URL. Maximum 15
characters. Defaults to the role prefix or cluster name.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature domain
```

The prefix is derived automatically from the role prefix or cluster name.
To override:

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature domain \
  -e domain_prefix=myprefix
```

## Template Rendering

The domain prefix falls back through: `domain_prefix` → `rosa_role_prefix` → `cluster_name`.

```yaml
spec:
  domainPrefix: {{ domain_prefix | default(rosa_role_prefix) | default(cluster_name) }}
```

The resulting cluster API URL becomes `https://api.<prefix>.<base_domain>:443`.

## Verification

Uses OCM API to verify domain prefix configuration:

GET /api/clusters_mgmt/v1/clusters/{id}

Asserts:
- `.domain_prefix` is defined and non-empty
- Length is <= 15 characters
- Value matches expected prefix
- Falls back to ROSAControlPlane K8s spec if OCM is unavailable

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
