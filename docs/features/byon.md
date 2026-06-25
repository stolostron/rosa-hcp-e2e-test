# 4.22 Feature Testing: Bring Your Own Network (BYON)

| Field | Value |
|-------|-------|
| Feature ID | `byon` |
| CLI Flag | `--feature byon-vpc` |
| Category | Infrastructure |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | Yes (`byon_subnet_ids`, `byon_availability_zones`) |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.subnets` |
| Min Version | 4.19 |
| Dependency | `private_network` (auto-resolved) |
| Ansible Variable | `byon_vpc` |

## Description

Provisions a ROSA HCP cluster using pre-existing VPC and subnets instead
of auto-creating a ROSANetwork resource. When enabled, ROSANetwork creation
is skipped entirely and user-provided subnet IDs are passed directly to the
ROSAControlPlane spec.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature byon-vpc \
  -e 'byon_subnet_ids=["subnet-abc123","subnet-def456"]' \
  -e 'byon_availability_zones=["us-west-2a","us-west-2b"]'
```

The `private_network` dependency is auto-resolved, setting `endpointAccess: Private`.

## Template Rendering

When `byon_subnet_ids` is provided:

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

The `rosaNetworkRef` field is omitted when subnets are provided directly.
Without `--feature byon-vpc`, `rosaNetworkRef` points to the auto-created
ROSANetwork resource.

## Provisioning Flow

```
Step 1  ROSARoleConfig       AWS IAM roles + OIDC provider
Step 2  SKIPPED              ROSANetwork not created (BYON)
Step 3  ROSAControlPlane     Uses user-provided subnets directly
Step 4  Wait for cluster ready
```

## Verification

Asserts:
- `subnets` array is present on ROSAControlPlane spec
- `rosaNetworkRef` is not present (no auto-created network)
- Subnet IDs match the user-provided values
- `endpointAccess` is `Private` (from auto-resolved dependency)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- [Private Network](private-network.md) (auto-resolved dependency)
- Feature Group: none (standalone)
