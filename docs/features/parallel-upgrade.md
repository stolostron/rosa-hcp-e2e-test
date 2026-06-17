# 4.22 Feature Testing: Parallel Node Upgrade

| Field | Value |
|-------|-------|
| Feature ID | `parallel_upgrade` |
| CLI Flag | `--feature parallel-upgrade` |
| Category | Scaling |
| Phase | Day1 |
| Type | number |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAMachinePool` |
| K8s Field | `.spec.updateConfig.rollingUpdate` |
| Min Version | 4.19 |
| Ansible Variable | `parallel_node_upgrade` |

## Description

Configures rolling update strategy for node upgrades. Controls how many
nodes can be upgraded simultaneously. CI default: maxSurge=1,
maxUnavailable=0.

## Usage

### CI defaults

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature parallel-upgrade
```

### Custom values

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature parallel-upgrade \
  -e max_surge=2 \
  -e max_unavailable=1
```

## Template Rendering

When `parallel_node_upgrade` is defined (rendered on **ROSAMachinePool**):

```yaml
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: ROSAMachinePool
spec:
  updateConfig:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

## Verification

Asserts:
- `updateConfig.rollingUpdate` is defined
- `maxSurge` matches expected (default: 1)
- `maxUnavailable` matches expected (default: 0)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-combo`
