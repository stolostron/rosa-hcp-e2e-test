# 4.22 Feature Testing: Default MachinePool Autoscaling

| Field | Value |
|-------|-------|
| Feature ID | `default_autoscaling` |
| CLI Flag | `--feature autoscaling` |
| Category | Scaling |
| Phase | Day1 |
| Type | boolean |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.defaultMachinePoolSpec.autoscaling` |
| Min Version | 4.19 |
| Ansible Variable | `default_autoscaling` |

## Description

Enables autoscaling on the default machine pool. When enabled, the
default replicas range is min=2, max=4. Without autoscaling, replicas
are fixed at min=2, max=2.

## Usage

### Default range (2-4)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature autoscaling
```

### Custom range

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature autoscaling \
  -e mp_min_replicas=3 \
  -e mp_max_replicas=6
```

## Template Rendering

When `default_autoscaling` is `true`:

```yaml
spec:
  defaultMachinePoolSpec:
    instanceType: m5.xlarge
    autoscaling:
      minReplicas: 2
      maxReplicas: 4
```

Without autoscaling (default):

```yaml
spec:
  defaultMachinePoolSpec:
    instanceType: m5.xlarge
    autoscaling:
      minReplicas: 2
      maxReplicas: 2
```

## Verification

Asserts:
- `defaultMachinePoolSpec.autoscaling` is defined
- `minReplicas` and `maxReplicas` match expected values
- `maxReplicas >= minReplicas`

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
