# 4.22 Feature Testing: Private Network

| Field | Value |
|-------|-------|
| Feature ID | `private_network` |
| CLI Flag | `--feature private` |
| Category | Infrastructure |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.endpointAccess` |
| Min Version | 4.19 |
| Ansible Variable | `private` |

## Description

Enables private cluster networking with no public API endpoint.
Sets `endpointAccess: Private` on the ROSAControlPlane, restricting cluster
access to the VPC and connected networks only.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature private
```

## Template Rendering

When `private` is `true`, the template renders:

```yaml
spec:
  endpointAccess: Private
```

Without `--feature private`, `endpointAccess` defaults to `Public` (in the
combined template) or is omitted (in the controlplane-only template).

## Verification

Asserts `rcp.spec.endpointAccess == 'Private'`.

## Related

- [Automated Feature Verification](automated-feature-verification.md)
