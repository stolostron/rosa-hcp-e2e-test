# Cluster Feature Flags

The `--feature` flag on `run-test-suite.py` enables composable ROSA HCP Day 1 configuration options during cluster provisioning.

## Quick Start

```bash
# List all available features
./run-test-suite.py --list-features

# Filter by OpenShift version
./run-test-suite.py --list-features --ocp-version 4.22

# Provision with features
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni --feature external-oidc -e name_prefix=test

# Dry run to see what vars are set
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni --dry-run -e name_prefix=test
```

## How It Works

Each `--feature` flag resolves through:

1. **Alias resolution** — `--feature no-cni` resolves to feature ID `no_cni`
2. **Dependency resolution** — `--feature fips` auto-adds `etcd_kms`
3. **Version validation** — checks feature is available for the target OpenShift version
4. **Var mapping** — converts feature ID to Ansible extra var (e.g., `no_cni` -> `no_cni=true`)
5. **Template selection** — when features are active, uses the `rosa-controlplane-only.yaml.j2` template with conditional blocks for each feature

User-provided `-e key=value` overrides always take precedence over feature defaults.

## Boolean Features

These features are fully activated by `--feature` alone:

| Flag | Feature | What It Does |
|------|---------|-------------|
| `--feature no-cni` | No CNI plugin | Sets `networkType: Other` |
| `--feature external-oidc` | External OIDC | Sets `enableExternalAuthProviders: true` |
| `--feature proxy` | Proxy enabled | Enables proxy config block (needs `-e` for URLs) |
| `--feature fips` | FIPS mode (4.21+) | Sets `fips: "Enabled"` (auto-requires etcd-kms) |
| `--feature autoscaler` | Cluster autoscaler | Enables autoscaler with `LeastWaste` expander |
| `--feature image-registry` | Image registry config | Enables `clusterRegistryConfig` block |
| `--feature parallel-upgrade` | Parallel node upgrade | Enables `updateConfig.rollingUpdate` |
| `--feature log-forwarding` | Audit log forwarding | Enables log forwarding (needs `-e` for config) |

## Typed Features (require `-e` for values)

These features need companion `-e` variables to be useful:

| Flag | Required `-e` Variables | Example |
|------|------------------------|---------|
| `--feature etcd-kms` | `etcd_encryption_kms_arn` | `--feature etcd-kms -e etcd_encryption_kms_arn=arn:aws:kms:us-west-2:123:key/abc` |
| `--feature proxy` | `http_proxy_url`, `https_proxy_url`, `no_proxy` | `--feature proxy -e http_proxy_url=http://proxy:3128 -e https_proxy_url=http://proxy:3128` |
| `--feature tags` | `additional_tags` | `--feature tags -e "additional_tags={team: platform, cost-center: eng}"` |
| `--feature security-groups` | `additional_security_groups` | `--feature security-groups -e "additional_security_groups=[sg-abc123]"` |
| `--feature user-agent` | `user_agent` | `--feature user-agent -e user_agent=my-test-agent` |
| `--feature domain` | `domain_prefix` | `--feature domain -e domain_prefix=my-long-prefix` |
| `--feature channel` | `channel_group` | `--feature channel -e channel_group=fast` |
| `--feature disk-size` | `root_volume_size` (default: 300) | `--feature disk-size -e root_volume_size=500` |
| `--feature azs` | `availability_zone_count` | `--feature azs -e availability_zone_count=3` |
| `--feature log-forwarding` | `log_forward_cloudwatch_role_arn`, `log_forward_cloudwatch_log_group` (or S3 equivalents) | `--feature log-forwarding -e log_forward_cloudwatch_role_arn=arn:... -e log_forward_cloudwatch_log_group=my-group` |

## Composing Multiple Features

Features can be freely combined:

```bash
# No CNI with external OIDC and custom disk size
./run-test-suite.py 20-rosa-hcp-provision \
  --feature no-cni \
  --feature external-oidc \
  --feature disk-size \
  -e root_volume_size=500 \
  -e name_prefix=test
```

## Version Constraints

Some features are only available on certain OpenShift versions:

| Feature | Minimum Version |
|---------|----------------|
| `fips` | 4.21 |
| `log-forwarding` | 4.20 |
| All others | 4.19 |

The CLI validates version constraints and exits with an error if a feature isn't available:

```
Feature error: Feature 'fips' requires OpenShift >= 4.21, but version is 4.20
```

## Jenkins Usage

The `CLUSTER_FEATURES` Jenkins parameter accepts a comma-separated list:

```
CLUSTER_FEATURES=no-cni,external-oidc
```

This expands to `--feature no-cni --feature external-oidc` in the provision stage.

## Feature Groups

Feature groups are named presets that bundle common feature combinations:

```bash
# List available groups
./run-test-suite.py --list-groups

# Run with a group
./run-test-suite.py 20-rosa-hcp-provision --feature-group day1-combo -e name_prefix=test

# Combine a group with individual features
./run-test-suite.py 20-rosa-hcp-provision --feature-group day1-combo --feature etcd-kms \
  -e etcd_encryption_kms_arn=arn:... -e name_prefix=test
```

| Group | Features | Coverage |
|-------|----------|----------|
| `day1-basic` | *(none — uses default provisioning)* | STS, Tags, AZs, DomainPrefix, Autoscaling, Long Name |
| `day1-combo` | no-cni, autoscaler, image-registry, parallel-upgrade, disk-size, user-agent | day1-basic + 6 features = 13/21 |
| `day1-security` | etcd-kms, fips | Requires AWS KMS key |
| `day1-networking` | external-oidc, log-forwarding | Requires OIDC provider + CloudWatch |

## Feature Registry

Features are defined declaratively in `templates/schemas/feature-registry.yml`. Adding a new feature requires:

1. Add the feature definition to a suite in `feature-registry.yml` (id, name, description, type, default)
2. Add a `var_map` entry mapping the feature ID to an Ansible variable name
3. Add a `cli_aliases` entry for the user-friendly flag name
4. Add the feature ID to `cli_features`
5. Add a conditional block in the `rosa-controlplane-only.yaml.j2` templates (4.20, 4.21, 4.22)
6. Add a `feature_availability` entry in `version-compatibility.yml` if version-restricted

No Python code changes required.

## Features Not Yet Available via `--feature`

These require additional template or architecture work:

| Feature | Reason |
|---------|--------|
| Private Cluster | Requires private-only subnets in ROSANetwork (not yet implemented) |
| BYON (Bring Your Own Network) | Requires skipping ROSANetwork creation and accepting manual subnet IDs |
| Identity Provider | No template conditional exists |
| Default MachinePool Auto Scaling | Template uses nested `machine_pool.*` vars, not settable via flat extra var |
| Instance Type | Same — uses `machine_pool.instance_type` |

These can still be configured via `-e` variables directly.
