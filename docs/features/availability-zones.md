# 4.22 Feature Testing: Availability Zones

| Field | Value |
|-------|-------|
| Feature ID | `availability_zones` |
| CLI Flag | `--feature azs` |
| Category | Infrastructure |
| Phase | Day1 |
| Type | select |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSANetwork` |
| K8s Field | `.spec.availabilityZones` |
| Min Version | 4.18 |
| Ansible Variable | `availability_zone_count` |

## Description

Sets the number of availability zones for high availability (1-3).
The ROSANetwork distributes subnets across the specified number of AZs
in the target AWS region. Default: 2 AZs.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature azs
```

To specify a different AZ count:

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature azs \
  -e availability_zone_count=3
```

## Template Rendering

Rendered on the **ROSANetwork** resource (not ROSAControlPlane):

```yaml
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: ROSANetwork
spec:
  availabilityZones:
    - us-west-2a
    - us-west-2b
```

## Verification

Asserts:
- At least 2 availability zones configured
- All AZs are in the expected AWS region

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
