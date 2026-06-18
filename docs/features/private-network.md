# 4.22 Feature Testing: Private Network

| Field | Value |
|-------|-------|
| Feature ID | `private_network` |
| CLI Flag | `--feature private` |
| Category | Infrastructure |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | No (auto-extracts private subnets from ROSANetwork) |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.endpointAccess`, `.spec.subnets` |
| Min Version | 4.19 |
| Ansible Variable | `private` |

## Description

Enables private cluster networking with no public API endpoint. Sets
`endpointAccess: Private` and configures the cluster to use only private
subnets from the VPC.

When used with automated provisioning (`create_rosa_network=true`), the
framework automatically extracts private subnet IDs from the ROSANetwork
status after VPC creation (Step 2.5). Users can also provide their own
private subnet IDs directly.

## Usage

### Auto-create with private subnets (recommended for CI)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature private
```

The framework:
1. Creates ROSANetwork (VPC with public + private subnets per AZ)
2. Extracts only the private subnet IDs from `ROSANetwork.status.subnets`
3. Passes them to `ROSAControlPlane.spec.subnets`
4. Sets `endpointAccess: Private`

### Bring your own subnets

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature private \
  -e '{"private_subnet_ids": ["subnet-abc123", "subnet-def456"]}'
```

When `private_subnet_ids` is provided, the framework skips ROSANetwork
subnet extraction and uses the user-provided IDs directly. The subnets
must already exist in a VPC with proper routing and NAT gateway
configuration.

## Provisioning Flow

```
Step 1  ROSARoleConfig       AWS IAM roles + OIDC provider
Step 2  ROSANetwork          VPC, subnets, NAT GWs (CloudFormation)
Step 2.5  extract_private_subnets.yml
          |-- Source: user-provided private_subnet_ids OR ROSANetwork status
          |-- Extracts privateSubnet from each AZ (skips publicSubnet)
          |-- Validates subnet ID format (subnet-<hex>)
          |-- Sets fact: cluster_private_subnets=[subnet-xxx, subnet-yyy]
Step 3  ROSAControlPlane from template
          endpointAccess: Private
          subnets: [subnet-xxx, subnet-yyy]
          availabilityZones: [us-west-2a, us-west-2b]
          rosaNetworkRef: EXCLUDED (mutually exclusive with subnets)
Step 4  Wait for cluster ready
```

## Template Rendering

When `private` is `true` and `cluster_private_subnets` is populated:

```yaml
apiVersion: controlplane.cluster.x-k8s.io/v1beta2
kind: ROSAControlPlane
spec:
  endpointAccess: Private
  subnets:
    - subnet-abc123
    - subnet-def456
  availabilityZones:
    - us-west-2a
    - us-west-2b
```

**Important CRD constraints**:
- `subnets` and `rosaNetworkRef` are **mutually exclusive** — the template
  automatically excludes `rosaNetworkRef` when private subnets are configured
- `availabilityZones` is **required** when `rosaNetworkRef` is omitted — the
  template extracts AZ names from `rosa_network_subnets` automatically

Without `--feature private`, `endpointAccess` defaults to `Public`,
`rosaNetworkRef` is rendered, and no `subnets` or `availabilityZones`
fields appear (ROSANetwork handles everything automatically).

## Verification

Uses AWS CLI to verify the cluster VPC has no internet-facing load balancers:

```bash
aws ec2 describe-subnets \
  --filters "Name=tag:aws:cloudformation:stack-name,Values=<cluster>-rosa-network-stack" \
  --query 'Subnets[0].VpcId'

aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?VpcId=='<vpc_id>'].{Name:LoadBalancerName,Scheme:Scheme}"
```

Asserts:
- All load balancers in the cluster VPC have `Scheme: internal` (none are `internet-facing`)

## Files

| File | Purpose |
|------|---------|
| `tasks/extract_private_subnets.yml` | Extracts private subnets from ROSANetwork or user input |
| `tasks/provision_rosa_hcp_with_automation.yml` | Orchestrator, Step 2.5 trigger |
| `templates/versions/4.22/features/rosa-controlplane-only.yaml.j2` | Template (subnets on ROSAControlPlane) |
| `templates/versions/4.22/features/rosa-combined-automation.yaml.j2` | Template (subnets on ROSAControlPlane) |
| `templates/versions/4.21/features/rosa-controlplane-only.yaml.j2` | Template (subnets on ROSAControlPlane) |

## Test Coverage

| Test | File | What it verifies |
|------|------|-----------------|
| `test_private_subnets_rendered_on_controlplane` | `tests/test_feature_manager.py` | Subnets render on ROSAControlPlane with Private endpoint (3 templates) |
| `test_no_subnets_when_not_private` | `tests/test_feature_manager.py` | No subnets field when not private (3 templates) |
| `test_private_without_subnets_renders_no_subnets_field` | `tests/test_feature_manager.py` | Private without subnet list renders no subnets field (3 templates) |
| `test_private_network_feature_metadata` | `tests/test_feature_manager.py` | Registry says ROSAControlPlane |
| `test_private_network_var_mapping` | `tests/test_feature_manager.py` | `private` set to `true` in extra vars |

## Related

- Feature Group: none (standalone)
