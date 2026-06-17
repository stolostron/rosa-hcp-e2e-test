# 4.22 Feature Testing: User Agent

| Field | Value |
|-------|-------|
| Feature ID | `user_agent` |
| CLI Flag | `--feature user-agent` |
| Category | Configuration |
| Phase | Day1 |
| Type | string |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.userAgent` |
| Min Version | 4.19 |
| Ansible Variable | `user_agent` |

## Description

Sets a custom user agent string sent with ROSA API requests.
CI default: `capa-e2e-test`.

## Usage

### CI default

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature user-agent
```

Uses CI default value `capa-e2e-test`.

### Custom value

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature user-agent \
  -e user_agent=my-custom-agent
```

## Template Rendering

When `user_agent` is defined:

```yaml
spec:
  userAgent: capa-e2e-test
```

## Verification

Asserts `rcp.spec.userAgent` is defined and non-empty.

## Related

- [Automated Feature Verification](automated-feature-verification.md)
