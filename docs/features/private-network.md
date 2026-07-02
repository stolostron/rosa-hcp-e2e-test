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
| K8s Field | `.spec.endpointAccess`, `.spec.subnets` |
| Min Version | 4.19 |
| Ansible Variable | `private` |

## Description

Enables private cluster networking with no public API endpoint.
Sets `endpointAccess: Private` on the ROSAControlPlane and configures
the cluster to use only private subnets from the VPC.

When used with automated provisioning, the framework automatically
extracts private subnet IDs from the ROSANetwork status. Users can
also provide their own private subnet IDs directly. Full private subnet
support is implemented in PR #72 (`feat/private-cluster-subnets`).

## Usage

### Auto-create with private subnets (recommended for CI)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature private
```

The framework automatically:
1. Creates ROSANetwork (VPC with public + private subnets per AZ)
2. Extracts only the private subnet IDs from ROSANetwork status
3. Passes them to `ROSAControlPlane.spec.subnets`
4. Sets `endpointAccess: Private`

### Bring your own subnets

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature private \
  -e '{"private_subnet_ids": ["subnet-abc123", "subnet-def456"]}'
```

When `private_subnet_ids` is provided, the framework uses the
user-provided IDs directly instead of extracting from ROSANetwork.

## Template Rendering

When `private` is `true` and private subnets are available:

```yaml
spec:
  endpointAccess: Private
  subnets:
    - subnet-abc123
    - subnet-def456
  availabilityZones:
    - us-west-2a
    - us-west-2b
```

The template renders `endpointAccess: Private`. The `subnets` and
`availabilityZones` fields are populated by the ROSANetwork controller
or passed directly when using BYON (bring your own network).

Without `--feature private`, `endpointAccess` defaults to `Public`.

## Verification

Uses AWS CLI to verify the cluster VPC has no internet-facing load balancers:

```bash
aws ec2 describe-subnets \
  --filters "Name=tag:aws:cloudformation:stack-name,Values=<cluster>-rosa-network-stack" \
  --region <region> \
  --query 'Subnets[0].VpcId'

aws ec2 describe-internet-gateways \
  --filters "Name=attachment.vpc-id,Values=<vpc_id>" \
  --region <region> \
  --query 'InternetGateways[].InternetGatewayId'

aws elbv2 describe-load-balancers \
  --region <region> \
  --query "LoadBalancers[?VpcId=='<vpc_id>'].{Name:LoadBalancerName,Scheme:Scheme}"
```

Asserts:
- All load balancers in the cluster VPC have `Scheme: internal` (none are `internet-facing`)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
