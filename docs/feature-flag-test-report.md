# Feature Flag E2E Test Report

**Date:** 2026-05-27
**Branch:** tf_test (merged feat/feature-registry-cli)
**Cluster:** feat-rosa-hcp
**Hub:** api.qe6-vmware-ibm.install.dev09.red-chesterfield.com:6443

## Test Summary

| Suite | Description | 4.20 Result | 4.21 Result |
|-------|-------------|-------------|-------------|
| 10 | Configure CAPI/CAPA Environment | PASS (42s) | PASS (reused) |
| 20 | Provision ROSA HCP with 5 features | PASS | Pending |
| 21 | Verify Feature Flags | FAIL (4/5) | Pending |
| 30 | Delete ROSA HCP Cluster | PASS | Pending |

## Features Tested

### Requested Features (via --feature flags)

| # | CLI Flag | Ansible Var | Template Conditional | K8s Resource | K8s Field | 4.20 Result | 4.21 Expected |
|---|----------|-------------|---------------------|--------------|-----------|-------------|---------------|
| 1 | `--feature autoscaler` | `cluster_autoscaler_expander=true` | `{% if cluster_autoscaler_expander %}` | ROSAControlPlane | `.spec.autoscaler.expanders` | FAIL | PASS |
| 2 | `--feature image-registry` | `image_registry_config=true` | `{% if image_registry_config %}` | ROSAControlPlane | `.spec.clusterRegistryConfig` | FAIL | PASS |
| 3 | `--feature disk-size` | `root_volume_size=500` | `{% if root_volume_size %}` | ROSAMachinePool | `.spec.rootVolume.size` | FAIL | PASS |
| 4 | `--feature user-agent` | `user_agent=capa-e2e-test` | `{% if user_agent %}` | ROSAControlPlane | `.spec.userAgent` | FAIL | PASS |
| 5 | `--feature parallel-upgrade` | `parallel_node_upgrade=2` | `{% if parallel_node_upgrade %}` | ROSAMachinePool | `.spec.updateConfig.rollingUpdate` | PASS | PASS |

### Default Features (always present in template)

| # | Feature | K8s Field | Verify Check | 4.20 Result |
|---|---------|-----------|--------------|-------------|
| 6 | additionalTags | `.spec.additionalTags` | keys() > 5 | SKIP (only 5 default tags) |
| 7 | domainPrefix | `.spec.domainPrefix` | Informational | PASS (feat) |
| 8 | channelGroup | `.spec.channelGroup` | Defined, non-empty | PASS (stable) |
| 9 | availabilityZones | ROSANetwork `.spec.availabilityZones` | >= 2 AZs | PASS (us-west-2a, us-west-2b) |
| 10 | long cluster name | `.spec.rosaClusterName` | Length > 20 | SKIP (13 chars) |

## Bug Found: 4.20 Template Missing Feature Conditionals

**Root Cause:** The provisioning template `templates/versions/4.20/features/rosa-controlplane-only.yaml.j2` is missing all feature flag Jinja2 conditionals. Only the 4.21 template has them.

**Impact:** When provisioning with OpenShift 4.20.x, feature flags passed via `--feature` are ignored because the template doesn't contain the `{% if %}` blocks to render them into the cluster YAML.

**Why parallel-upgrade worked on 4.20:** The `updateConfig.rollingUpdate` block happens to exist in the 4.20 ROSAMachinePool section of the template.

### Template Comparison

| Feature Conditional | 4.20 Template | 4.21 Template |
|---------------------|---------------|---------------|
| `{% if cluster_autoscaler_expander %}` (autoscaler) | Missing | Line 150 |
| `{% if image_registry_config %}` (image registry) | Missing | Line 140 |
| `{% if root_volume_size %}` (disk size) | Missing | Line 241 |
| `{% if user_agent %}` (user agent) | Missing | Line 122 |
| `{% if parallel_node_upgrade %}` (parallel upgrade) | Missing | Line 245 |
| `{% if no_cni %}` (no CNI) | Missing | Line 108 |
| `{% if external_oidc %}` (external OIDC) | Missing | Line 114 |
| `{% if etcd_encryption_kms_arn %}` (etcd KMS) | Missing | Line 118 |
| `{% if fips %}` (FIPS mode) | Missing | Line 76 |

### Fix Required

Backport all feature flag conditionals from the 4.21 template to the 4.20 template:
- `templates/versions/4.20/features/rosa-controlplane-only.yaml.j2`

## Feature Pipeline Flow

```
CLI: --feature autoscaler --feature disk-size ...
  |
  v
FeatureManager.resolve_alias()     # autoscaler -> cluster_autoscaler_expander
  |
  v
FeatureManager.auto_resolve_deps() # Add dependencies (e.g., fips -> etcd_kms)
  |
  v
FeatureManager.validate_features() # Check version compatibility
  |
  v
FeatureManager.resolve_to_extra_vars()  # Produce Ansible vars
  |                                      # cluster_autoscaler_expander=true
  v                                      # root_volume_size=500
run_playbook() -> ansible-playbook -e key=value
  |
  v
Playbook selects template based on openshift_version
  |
  v
Template renders YAML with {% if feature_var %} conditionals
  |
  v
oc apply -f rendered.yaml -> K8s cluster created
  |
  v
Suite 21 verifies: oc get rosacontrolplane -o json -> check spec fields
```

## Unit Test Results

```
358 tests (pre-merge) -> 366 tests (post-merge)
All 366 PASSED on tf_test branch
```

## CLI Validation Tests

```bash
# Valid feature
$ ./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature autoscaler
Feature validation PASSED

# Invalid feature
$ ./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature bogus
Feature error: Unknown feature: 'bogus-feature'

# Feature group
$ ./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature-group day1-combo
Feature group 'day1-combo': no_cni, cluster_autoscaler_expander, ...
Feature validation PASSED
```
