# 4.22 Feature Testing: Cluster Autoscaler with Expander

| Field | Value |
|-------|-------|
| Feature ID | `cluster_autoscaler_expander` |
| CLI Flag | `--feature autoscaler` |
| Category | Scaling |
| Phase | Day1 |
| Type | boolean |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.autoscaler.expanders` |
| Min Version | 4.19 |
| Ansible Variable | `cluster_autoscaler_expander` |

## Description

Enables the cluster autoscaler with the `LeastWaste` expander strategy.
The autoscaler scales node groups based on which group would have the
least idle resources after scale-up.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature autoscaler
```

## Template Rendering

When `cluster_autoscaler_expander` is `true`:

```yaml
spec:
  autoscaler:
    expanders:
      - LeastWaste
```

## Verification

Uses `aws autoscaling describe-auto-scaling-groups` to verify autoscaling
is active on cluster node groups:

```bash
aws autoscaling describe-auto-scaling-groups \
  --filters "Name=tag:kubernetes.io/cluster/<cluster>,Values=owned" \
  --region <region> \
  --query 'AutoScalingGroups[].{Name:AutoScalingGroupName,Min:MinSize,Max:MaxSize}'
```

Asserts:
- At least one ASG exists for the cluster
- ASG MaxSize > MinSize (scaling is allowed)
- Expander strategy (`LeastWaste`) verified via ROSAControlPlane K8s spec
  (not exposed in AWS ASG config)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-combo`
