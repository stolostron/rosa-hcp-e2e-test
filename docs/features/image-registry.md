# 4.22 Feature Testing: Image Registry Config

| Field | Value |
|-------|-------|
| Feature ID | `image_registry` |
| CLI Flag | `--feature image-registry` |
| Category | Storage |
| Phase | Day1 |
| Type | boolean |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.clusterRegistryConfig` |
| Min Version | 4.19 |
| Ansible Variable | `image_registry_config` |

## Description

Configures the cluster internal image registry with allowed registries
for import and registry sources. Default registry domain: `quay.io`.

## Usage

### Default registry (quay.io)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature image-registry
```

### Custom registry domain

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature image-registry \
  -e registry_domain=registry.example.com \
  -e allowed_registry=registry.example.com
```

## Template Rendering

When `image_registry_config` is `true`:

```yaml
spec:
  clusterRegistryConfig:
    allowedRegistriesForImport:
      - domainName: "quay.io"
        insecure: false
    registrySources:
      allowedRegistries:
        - "quay.io"
```

## Verification

Asserts:
- `clusterRegistryConfig` structure present
- `allowedRegistriesForImport` has at least one entry
- `registrySources.allowedRegistries` is defined
- Registry domain matches expected value (default: `quay.io`)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-combo`
