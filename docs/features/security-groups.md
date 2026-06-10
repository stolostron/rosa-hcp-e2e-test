# 4.22 Feature Testing: Additional Security Groups

| Field | Value |
|-------|-------|
| Feature ID | `security_groups` |
| CLI Flag | `--feature security-groups` |
| Category | Security & Authentication |
| Phase | Day1 |
| Type | list |
| Mutable | Yes (create + apply) |
| Requires Input | Yes (auto-created when using `--feature security-groups`) |
| CRD Resource | `ROSAMachinePool` |
| K8s Field | `.spec.additionalSecurityGroups` |
| Min Version | 4.19 |
| Ansible Variable | `additional_security_groups` |
| Feature Flag Variable | `feature_security_groups_enabled` |

## Description

Attaches extra AWS security groups to all worker nodes in the ROSA HCP cluster.
When used with `--feature security-groups`, the framework automatically creates a
test security group in the cluster VPC (Step 2.5) and injects it into the
`ROSAMachinePool.spec.additionalSecurityGroups` list at template rendering time.

## How It Works

```
./run-test-suite.py 20-rosa-hcp-provision --feature security-groups
```

### Provisioning Flow

```
Step 1/3  ROSARoleConfig       AWS IAM roles + OIDC provider
Step 2/3  ROSANetwork          VPC, subnets, NAT GWs (CloudFormation)
Step 2.5  create_security_group.yml
          |-- Gets VPC ID from ROSANetwork
          |   jsonpath: .status.resources[?(@.logicalId=="VPC")].physicalId
          |-- Creates SG in VPC (or reuses existing by name+VPC)
          |-- Tags for cleanup:
          |     rosa-cluster=<cluster_name>
          |     automation.acm.redhat.com/created-by=ansible-automation
          |     automation.acm.redhat.com/test-case=SC-04
          |-- Sets fact: additional_security_groups=[sg-xxx]
Step 3/3  ROSAControlPlane + ROSAMachinePool from template
          ROSAMachinePool.spec.additionalSecurityGroups: [sg-xxx]
Step 4/4  Wait for cluster ready
```

### Deletion Flow

```
delete_rosa_hcp_resources.yml
  |-- Wait for ROSAControlPlane deletion
  |-- delete_security_group.yml   <-- before VPC deletion
  |   |-- Find SGs by tag: rosa-cluster=<cluster_name>
  |   |-- Delete with ENI detach retry (12x, 10s intervals)
  |   |-- Handles InvalidGroup.NotFound gracefully
  |-- Delete ROSANetwork (tears down VPC via CloudFormation)
  |-- Delete ROSARoleConfig
```

## Files

| File | Purpose |
|------|---------|
| `tasks/create_security_group.yml` | Creates SG in cluster VPC, idempotent |
| `tasks/delete_security_group.yml` | Deletes SG with ENI retry logic |
| `tasks/provision_rosa_hcp_with_automation.yml` | Orchestrator, Step 2.5 trigger |
| `tasks/delete_rosa_hcp_resources.yml` | Orchestrator, SG cleanup before VPC |
| `templates/versions/4.22/features/rosa-controlplane-only.yaml.j2` | Template (SG on ROSAMachinePool) |
| `templates/versions/4.22/features/rosa-combined-automation.yaml.j2` | Template (SG on ROSAMachinePool) |
| `templates/versions/4.21/features/rosa-controlplane-only.yaml.j2` | Template (SG on ROSAMachinePool) |
| `templates/schemas/feature-registry.yml` | Feature definition |
| `feature_manager.py` | Sets `feature_security_groups_enabled` for list-type features |

## Template Rendering

When `additional_security_groups` is defined and non-empty, the Jinja2 templates
render this block on the **ROSAMachinePool** resource only:

```yaml
spec:
  additionalSecurityGroups:
    - sg-0fdad2295cfee7ba3
```

The ROSAControlPlane CRD does **not** support `additionalSecurityGroups`.

## Usage Modes

### Auto-create (recommended for CI)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature security-groups
```

A test SG is created in the cluster VPC automatically and deleted during cleanup.

### Bring Your Own SG

```bash
./run-test-suite.py 20-rosa-hcp-provision \
  -e 'additional_security_groups=["sg-abc123","sg-def456"]'
```

No `--feature` flag needed. Step 2.5 is skipped because `additional_security_groups`
is already defined. The user-provided SGs go directly into the template.

**Cleanup behavior**: User-provided SGs are **not deleted** during cluster teardown.
The delete task only removes SGs tagged with both `rosa-cluster=<cluster_name>` and
`automation.acm.redhat.com/created-by=ansible-automation`. The user is responsible
for managing their own SGs.

## Idempotency

- **Create**: If a SG named `<cluster_name>-test-sg` already exists in the VPC,
  it is reused (looked up by name + VPC ID). Cleanup tags are re-applied.
- **Delete**: If the SG is already gone (`InvalidGroup.NotFound`), deletion
  succeeds silently. ENI detach retries handle cases where the SG is still
  attached to node interfaces.

## Jenkins Integration

Set `CLUSTER_FEATURES=security-groups` in the Jenkins job parameters. AWS
credentials (`CAPI_AWS_ACCESS_KEY_ID`, `CAPI_AWS_SECRET_ACCESS_KEY`) are
required and passed automatically by the Jenkinsfile.

## Test Coverage

| Test | File | What it verifies |
|------|------|-----------------|
| `test_sg_only_on_machine_pool` | `tests/test_feature_manager.py` | SG renders only on ROSAMachinePool (3 templates) |
| `test_no_sg_when_not_defined` | `tests/test_feature_manager.py` | No SG block when feature not used (3 templates) |
| `test_security_groups_resource_is_machine_pool` | `tests/test_feature_manager.py` | Registry says ROSAMachinePool |
| `test_security_groups_var_mapping` | `tests/test_feature_manager.py` | `feature_security_groups_enabled` set correctly |

## Live Test Record

| Field | Value |
|-------|-------|
| Date | 2026-06-10 |
| Hub Cluster | ci-azure-w24 |
| Cluster Name | sg1-rosa-hcp |
| OCM ID | 2qrlaikus4p1au4o7b7o4j74hhdr4mal |
| Version | 4.22.0-rc.5 (candidate) |
| Region | us-west-2 |
| API URL | https://api.sg1.j9y4.s3.devshift.org:443 |
| VPC ID | vpc-0c5abdb3aa4493f66 |
| Security Group | sg-0fdad2295cfee7ba3 (sg1-rosa-hcp-test-sg) |
| ROSAMachinePool SG | `["sg-0fdad2295cfee7ba3"]` |
| ROSAControlPlane Ready | true |
| ROSAMachinePool Ready | true |
| Result | PASS |

## Related PRs

- [PR #67](https://github.com/stolostron/rosa-hcp-e2e-test/pull/67) - feat: auto-create AWS security group for --feature security-groups testing
