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

Rendered on **ROSAMachinePool** (not ROSAControlPlane) only when
`root_volume_size` is defined:

```yaml
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: ROSAMachinePool
spec:
  # Only rendered if root_volume_size is defined
  volumeSize: 500
```

Without `--feature disk-size`, `volumeSize` is omitted entirely and
ROSA uses its default of 300 GiB.

## Verification

Uses `aws ec2 describe-instances` and `aws ec2 describe-volumes` to verify
the actual EBS root volume size on worker nodes:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:kubernetes.io/cluster/<cluster>,Values=owned" \
  "Name=instance-state-name,Values=running" \
  --region <region> \
  --query 'Reservations[0].Instances[0].{Root:RootDeviceName,BDM:BlockDeviceMappings}'

aws ec2 describe-volumes --volume-ids <root_volume_id> \
  --region <region> \
  --query 'Volumes[0].Size'
```

The root volume is identified by matching `RootDeviceName` against
`BlockDeviceMappings[].DeviceName` (index 0 is not guaranteed to be
the root device on multi-volume instances).

Asserts:
- Root EBS volume size matches expected value (CI default: 500 GiB)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-combo`
