# 4.22 Feature Testing: Root Disk Size

| Field | Value |
|-------|-------|
| Feature ID | `disk_size` |
| CLI Flag | `--feature disk-size` |
| Category | Node Configuration |
| Phase | Day1 |
| Type | number |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAMachinePool` |
| K8s Field | `.spec.volumeSize` |
| Min Version | 4.19 |
| Ansible Variable | `root_volume_size` |

## Description

Sets the root volume size (in GiB) for worker nodes. Default: 300 GiB.
CI default: 500 GiB.

## Usage

### CI default (500 GiB)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature disk-size
```

### Custom size

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature disk-size \
  -e root_volume_size=1000
```

## Template Rendering

When `root_volume_size` is defined (rendered on **ROSAMachinePool**, not
ROSAControlPlane):

```yaml
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: ROSAMachinePool
spec:
  volumeSize: 500
```

Without `--feature disk-size`, `volumeSize` is omitted (uses ROSA default of 300).

## Verification

Asserts `rmp.spec.volumeSize` matches expected value (CI default: 500).

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-combo`
