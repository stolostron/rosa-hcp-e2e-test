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

The AZ list is derived from the AWS region and the requested count.
For example, `us-west-2` with count 2 produces `[us-west-2a, us-west-2b]`.
With count 3: `[us-west-2a, us-west-2b, us-west-2c]`.

## Usage

### Default (2 AZs)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature azs
```

Uses the default of 2 availability zones in the target region.

### 3 AZs for full HA

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature azs \
  -e availability_zone_count=3
```

### Single AZ (dev/test)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature azs \
  -e availability_zone_count=1
```

## Template Rendering

Rendered on the **ROSANetwork** resource (not ROSAControlPlane). The
ROSANetwork creates a CloudFormation stack that provisions the VPC,
subnets, and NAT gateways across the specified AZs.

### 2 AZs (default)

```yaml
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: ROSANetwork
metadata:
  name: my-cluster-network
  namespace: ns-rosa-hcp
spec:
  identityRef:
    kind: AWSClusterControllerIdentity
    name: default
  region: us-west-2
  stackName: my-cluster-rosa-network-stack
  availabilityZones:
    - us-west-2a
    - us-west-2b
  cidrBlock: 10.0.0.0/16
```

### 3 AZs

```yaml
spec:
  availabilityZones:
    - us-west-2a
    - us-west-2b
    - us-west-2c
```

### What the CloudFormation stack creates per AZ

Each AZ gets:
- 1 public subnet
- 1 private subnet
- 1 NAT gateway (in the public subnet)
- Route table associations

## Verification

Uses `aws ec2 describe-subnets` to verify subnets created by the
CloudFormation stack span the expected availability zones:

```bash
aws ec2 describe-subnets \
  --filters "Name=tag:aws:cloudformation:stack-name,Values=<cluster>-rosa-network-stack" \
  --region <region> \
  --query 'Subnets[].AvailabilityZone'
```

Asserts:
- Subnet AZ count matches the requested `availability_zone_count` (default: 2)
- All AZs belong to the expected AWS region

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
