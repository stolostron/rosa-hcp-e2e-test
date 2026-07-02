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
default replicas range is min=2, max=4. Without the autoscaling
feature flag, the range is derived from the AZ count
(min=`len(AZs)`, max=`len(AZs)*2`).

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

Without autoscaling (derived from AZ count):

```yaml
spec:
  defaultMachinePoolSpec:
    instanceType: m5.xlarge
    autoscaling:
      minReplicas: 1   # len(availability_zones_list), default 1
      maxReplicas: 2   # len(availability_zones_list) * 2
```

## Verification

Uses `aws autoscaling describe-auto-scaling-groups` to verify the default
machine pool ASG has the expected min/max sizes:

```bash
aws autoscaling describe-auto-scaling-groups \
  --filters "Name=tag:kubernetes.io/cluster/<cluster>,Values=owned" \
  --region <region> \
  --query 'AutoScalingGroups[].{Name:AutoScalingGroupName,Min:MinSize,Max:MaxSize,Desired:DesiredCapacity}'
```

Asserts:
- At least one ASG exists for the cluster
- ASG `MinSize` matches expected `minReplicas` (default: 2)
- ASG `MaxSize` matches expected `maxReplicas` (default: 4 when autoscaling enabled)
- `MaxSize >= MinSize`

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
