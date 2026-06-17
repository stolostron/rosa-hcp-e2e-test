# 4.22 Feature Testing: Automated Feature Verification

## Overview

The feature verification playbook (`playbooks/verify_feature_flags.yml`) runs
post-provision to confirm that requested ROSA HCP features were correctly applied
to the cluster. It reads the live K8s resources (ROSAControlPlane, ROSAMachinePool,
ROSANetwork) and asserts that each requested feature's field is present with the
expected value.

## How It Works

```bash
./run-test-suite.py 21-verify-feature-flags --feature <feature1> --feature <feature2> \
  -e cluster_name=<name> \
  -e OCP_HUB_API_URL=<hub_api> \
  -e OCP_HUB_CLUSTER_USER=<user> \
  -e OCP_HUB_CLUSTER_PASSWORD=<password>
```

The playbook:
1. Logs into the hub cluster
2. Fetches ROSAControlPlane, ROSAMachinePool, and ROSANetwork JSON specs
3. Runs each feature check against the live spec
4. Classifies results as PASS, FAIL, WARN (CRD limitation), or SKIP (not requested)
5. Fails the playbook if any requested, CRD-supported feature is missing

## Verification Results

Each feature check produces one of four outcomes:

| Result | Meaning |
|--------|---------|
| **PASS** | Feature field is present with expected value |
| **FAIL** | Feature was requested, CRD supports the field, but value is missing or wrong |
| **WARN** | Feature was requested, but the installed CRD version does not have the field |
| **SKIP** | Feature was not requested (not an error) |

The CRD field check (`tasks/verify_feature_rescue.yml`) queries the live CRD
schema via `oc get crd` to distinguish between a missing field (platform
limitation) and an incorrectly applied feature (test failure).

## Verified Features

### ROSAControlPlane Features

| Feature | CLI Flag | K8s Field | What is Verified |
|---------|----------|-----------|-----------------|
| `no_cni` | `--feature no-cni` | `.spec.network.networkType` | Value is `Other` |
| `private_network` | `--feature private` | `.spec.endpointAccess` | Value is `Private` |
| `external_oidc` | `--feature external-oidc` | `.spec.enableExternalAuthProviders` | `true`, plus `externalAuthProviders` array with issuerURL, audiences, claimMappings |
| `fips` | `--feature fips` | `.spec.fips` | Value is `Enabled` |
| `etcd_kms` | `--feature etcd-kms` | `.spec.etcdEncryptionKMSARN` | Non-empty, starts with `arn:aws:kms:`, matches requested ARN if provided |
| `user_agent` | `--feature user-agent` | `.spec.userAgent` | Non-empty string present |
| `cluster_autoscaler_expander` | `--feature autoscaler` | `.spec.autoscaler.expanders` | Contains `LeastWaste`, all values in valid set (LeastWaste, Priority, Random) |
| `image_registry` | `--feature image-registry` | `.spec.clusterRegistryConfig` | Structure present with `allowedRegistriesForImport`, `registrySources`, domain matches expected (default: `quay.io`) |
| `additional_tags` | `--feature tags` | `.spec.additionalTags` | Default tags (env, purpose, automated) present; custom tags match if provided via `-e additional_tags={}` |
| `domain_prefix` | `--feature domain` | `.spec.domainPrefix` | Non-empty, <= 15 chars, matches expected prefix |
| `channel_group` | `--feature channel-group` | `.spec.channelGroup` | Valid value (stable, fast, candidate), matches requested |
| `default_autoscaling` | `--feature autoscaling` | `.spec.defaultMachinePoolSpec.autoscaling` | `minReplicas`/`maxReplicas` match expected (default: 2/4 when enabled, 2/2 otherwise) |
| `audit_logging` | `--feature log-forwarding` | `.spec.cloudWatchlogForwarder` | Structure present, CloudWatch role ARN and/or log group match if provided |
| `proxy_enabled` | `-e http_proxy=true` | `.spec.proxy` | Proxy configuration block present |

### ROSAMachinePool Features

| Feature | CLI Flag | K8s Field | What is Verified |
|---------|----------|-----------|-----------------|
| `disk_size` | `--feature disk-size` | `.spec.volumeSize` | Matches requested value (CI default: 500, default: 300) |
| `parallel_upgrade` | `--feature parallel-upgrade` | `.spec.updateConfig.rollingUpdate` | `maxSurge` and `maxUnavailable` match expected (default: 1/0) |
| `security_groups` | `--feature security-groups` | `.spec.additionalSecurityGroups` | Non-empty array, matches requested SG IDs if provided |

### Action Features (Non-Field Checks)

| Feature | CLI Flag | Type | What it Does |
|---------|----------|------|-------------|
| `break_glass_credentials` | `--feature break-glass` | action | Runs dedicated playbook to list/create break-glass credentials via OCM API, diagnoses 403 errors with AMS role check |

See [Break-Glass Credentials](break-glass-credentials.md) for full details.

### ROSANetwork Features

| Feature | CLI Flag | K8s Field | What is Verified |
|---------|----------|-----------|-----------------|
| `availability_zones` | `--feature azs` | `.spec.availabilityZones` | >= 2 AZs, all in expected AWS region |

## Feature Groups

Pre-configured feature groups for common test scenarios:

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature-group day1-basic
```

| Group | Features | Description |
|-------|----------|-------------|
| `day1-basic` | domain_prefix, availability_zones, additional_tags, channel_group, default_autoscaling | Default provisioning features |
| `day1-combo` | cluster_autoscaler_expander, image_registry, parallel_upgrade, disk_size | Non-default Day1 features |
| `day1-security` | etcd_kms, fips, security_groups | Security features (requires AWS KMS key) |
| `day1-networking` | external_oidc, audit_logging | Network/auth features (requires OIDC provider) |

## Dependencies

Features with automatic dependency resolution:

| Feature | Dependency | Effect |
|---------|-----------|--------|
| `break_glass_credentials` | `external_oidc` | Using `--feature break-glass` auto-adds `external_oidc` |
| `fips` | `etcd_kms` | Using `--feature fips` auto-adds `etcd_kms` |
| `byon` | `private_network` | Using BYON auto-adds `private_network` |

## Version Compatibility

Features are gated by OpenShift version. The framework rejects features
that require a newer version than the target cluster:

| Min Version | Features |
|-------------|----------|
| 4.18 | additional_tags, availability_zones, channel_group, domain_prefix |
| 4.19 | private_network, no_cni, external_oidc, etcd_kms, security_groups, disk_size, parallel_upgrade, cluster_autoscaler_expander, image_registry, user_agent, proxy_enabled, break_glass_credentials |
| 4.20 | audit_logging |
| 4.21 | fips |

## Jenkins Integration

Set `CLUSTER_FEATURES` in the Jenkins job parameters. The pipeline:

1. **Validate** (Stage 2) — dry-run validation of feature names, versions, dependencies
2. **Provision** (Stage 3) — provision with `--feature` flags
3. **Verify** (Stage 4) — run `21-verify-feature-flags` to confirm features applied

```
CLUSTER_FEATURES=no-cni,etcd-kms,domain
```

Multiple features are comma-separated. Extra vars for features requiring
input (e.g., KMS ARN) are passed via `EXTRA_FEATURE_VARS` or `ETCD_KMS_ARN`.

## Files

| File | Purpose |
|------|---------|
| `playbooks/verify_feature_flags.yml` | Main verification playbook (field-based feature checks) |
| `tasks/verify_feature_rescue.yml` | CRD field check + PASS/FAIL/WARN/SKIP classification |
| `templates/schemas/feature-registry.yml` | Feature definitions, var mappings, groups, dependencies |
| `templates/schemas/version-compatibility.yml` | Version gating rules |
| `feature_manager.py` | CLI `--feature` flag resolution to Ansible extra vars |
| `run-test-suite.py` | CLI entry point with `--feature`, `--feature-group`, `--validate-only` |
| `tests/test_feature_manager.py` | Unit tests for FeatureManager (aliases, deps, validation, groups) |

## Example Output

```
═══════════════════════════════════════════════════════════════
FEATURE FLAG VERIFICATION SUMMARY
═══════════════════════════════════════════════════════════════

Cluster: my-rosa-hcp
Namespace: ns-rosa-hcp
Cluster Version: 4.22.0
Requested: no_cni, domain_prefix, additional_tags

───────────────────────────────────────────────────────────────
PASSED (3):
  ✓ no_cni
  ✓ domain_prefix
  ✓ additional_tags

SKIPPED: 15 (feature not requested — not an error)
═══════════════════════════════════════════════════════════════
```

## Related PRs

- [PR #65](https://github.com/stolostron/rosa-hcp-e2e-test/pull/65) - feat: feature flag framework
- [PR #67](https://github.com/stolostron/rosa-hcp-e2e-test/pull/67) - feat: security group automation
- [PR #70](https://github.com/stolostron/rosa-hcp-e2e-test/pull/70) - feat: break-glass credential diagnostic
