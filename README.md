# ROSA HCP Feature Test Automation

Feature testing framework for **ROSA HCP** (Red Hat OpenShift Service on AWS - Hosted Control Plane) clusters using **Cluster API Provider AWS (CAPA)**.

## Overview

This repository provides comprehensive automated testing for ROSA HCP cluster lifecycle management through CAPI/CAPA, including:

- MCE (Multicluster Engine) environment configuration and verification
- ROSA HCP cluster provisioning with automated network and IAM role setup
- Composable feature flag system for targeted Day 1 feature testing
- Post-provision feature verification with CRD-aware checks
- Cluster lifecycle operations (create, upgrade, scale, delete)
- MachinePool management (add, scale, delete)
- Control plane and machine pool upgrade testing
- AI agent framework for autonomous issue detection and remediation
- JSON-based test suite framework with Jenkins integration

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   MCE Hub Cluster                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Multicluster Engine (MCE)                           │   │
│  │  ├── CAPI Controller (cluster-api)                   │   │
│  │  └── CAPA Controller (cluster-api-provider-aws)      │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           │ Manages                         │
│                           ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ROSA HCP Cluster (AWS)                              │   │
│  │  ├── ROSAControlPlane (control plane in AWS)         │   │
│  │  ├── ROSANetwork (VPC, subnets via CloudFormation)   │   │
│  │  ├── ROSARoleConfig (IAM roles, OIDC provider)       │   │
│  │  └── ROSAMachinePool (worker nodes)                  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- **OpenShift Hub Cluster** with MCE 2.x or ACM 2.x installed, **or** CRC for standalone mode
- **AWS Account** with appropriate permissions for ROSA
- **OCM (OpenShift Cluster Manager)** credentials
- **Python** 3.8+ with `boto3` and `PyYAML`
- **Ansible** 2.19+
- **oc CLI** installed and authenticated
- **Helm** 3.x (standalone mode only)

### Environment Setup

1. Clone the repository:
```bash
git clone https://github.com/stolostron/rosa-hcp-e2e-test.git
cd rosa-hcp-e2e-test
```

2. Configure credentials (copy the example and fill in your values):
```bash
cp vars/user_vars.yml.example vars/user_vars.yml
```

```yaml
# vars/user_vars.yml (gitignored)
OCP_HUB_API_URL: "https://api.your-cluster.com:6443"
OCP_HUB_CLUSTER_USER: "kubeadmin"
OCP_HUB_CLUSTER_PASSWORD: "your-password"
AWS_REGION: "us-west-2"
AWS_ACCOUNT_ID: "your-aws-account-id"
AWS_ACCESS_KEY_ID: "your-aws-key"
AWS_SECRET_ACCESS_KEY: "your-aws-secret"
OCM_API_URL: "https://api.openshift.com"       # or https://api.stage.openshift.com for staging
OCM_CLIENT_ID: "your-ocm-client-id"
OCM_CLIENT_SECRET: "your-ocm-client-secret"
# openshift_version: "4.22"                    # optional, default: 4.22
# channel_group: "stable"                      # stable (prod) or nightly (staging)
```

3. Authenticate to your OpenShift cluster:
```bash
oc login <your-api-url> -u <your-user> -p <your-password>
```
The playbooks load credentials from `vars/user_vars.yml` automatically via `vars_files`.

### Local Standalone Testing with CRC

You can run the full smoke test suite locally using [CRC (CodeReady Containers)](https://crc.dev/) without an MCE hub cluster. This deploys CAPI/CAPA controllers directly via Helm charts from the [cluster-api-installer](https://github.com/stolostron/cluster-api-installer) repo.

**Requirements:**
- [CRC](https://crc.dev/) installed and configured
- A [Red Hat pull secret](https://console.redhat.com/openshift/create/local) saved to a file
- `oc`, `helm` CLI tools
- `vars/user_vars.yml` configured with AWS and OCM credentials

**Run the standalone smoke tests (provision + delete):**
```bash
make crc-smoke PULL_SECRET_FILE=~/quay-pull-secret.json
```

**Run the full lifecycle tests (provision → upgrade CP → upgrade MP → add pool → delete pool → delete cluster):**
```bash
make crc-full PULL_SECRET_FILE=~/quay-pull-secret.json
```

Both will:
1. Start CRC (if not already running)
2. Login as `kubeadmin`
3. Run the tagged suites with a random cluster prefix

**Stop CRC:**
```bash
make crc-stop
```

**What standalone mode does differently:**
- Deploys CAPI/CAPA controllers via Helm instead of relying on MCE
- Removes the MCE webhook (`mce-capi-webhook-config`) which is not needed without MCE
- Removes the `--watch-filter=multicluster-engine` flag so the CAPI controller watches all resources
- Skips MCE-specific configuration (OCP login, MCE namespace setup)

### Running a Scenario (recommended)

A **scenario** is a named, self-contained feature test. It carries its own
features, their required inputs, the suites to run, and any per-version quirks,
so running one takes a name and a version and nothing else:

```bash
# See what's available and which versions each supports
./run-test-suite.py --list-scenarios

# Run one end to end (configure hub → provision → verify → delete → restore)
./run-test-suite.py --scenario day1-basic -e openshift_version=5.0 -e name_prefix=qe6

# Check everything resolves before spending an hour on AWS
./run-test-suite.py --scenario day1-security -e openshift_version=5.0 --validate-only

# Hub already has CAPI/CAPA enabled? Run just the cluster stages
./run-test-suite.py --scenario day1-combo -e openshift_version=4.22 --stages 20,21,30
```

Scenarios are defined under `scenarios:` in
`templates/schemas/feature-registry.yml`. The versions a scenario supports are
**computed** from its features' `min_version`/`max_version` in
`templates/schemas/version-compatibility.yml` — adding a version to
`supported_versions` makes every compatible scenario runnable on it with no
further edits.

Account-specific inputs stay out of git. Scenarios reference them as `${ENV_VAR}`
and fail fast, naming exactly what's missing, if they aren't set:

```bash
export ETCD_KMS_ARN="arn:aws:kms:us-west-2:123456789012:key/..."
export CAPI_TEST_SECURITY_GROUP_IDS='["sg-0abc1234"]'   # JSON array
export CAPI_TEST_LOG_S3_BUCKET="my-audit-bucket"
```

`extra_vars` precedence, lowest to highest:
feature defaults → scenario `extra_vars` → `version_overrides` → CLI `-e`.

Stages marked `always: true` (delete, restore HyperShift) still run after an
earlier stage fails, so a failed provision doesn't leak an AWS cluster or leave
the hub with HyperShift disabled.

### Running Tests

```bash
# Run a specific test suite
./run-test-suite.py 20-rosa-hcp-provision

# Run with feature flags
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni --feature etcd-kms \
  -e etcd_encryption_kms_arn="arn:aws:kms:..."

# Run a feature group (preset combination)
./run-test-suite.py 20-rosa-hcp-provision --feature-group day1-security \
  -e etcd_encryption_kms_arn="arn:aws:kms:..."

# Validate features without running (CI-safe dry run)
./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature no-cni

# Run with AI agent for autonomous issue detection
./run-test-suite.py 30-rosa-hcp-delete --ai-agent

# Run with verbose output
./run-test-suite.py 20-rosa-hcp-provision -vvv

# List all available test suites
./run-test-suite.py --list

# List available features and feature groups
./run-test-suite.py --list-features
./run-test-suite.py --list-groups
```

## CLI Reference

```
./run-test-suite.py [suite_id] [options]

Positional:
  suite_id                    Test suite ID (e.g., 20-rosa-hcp-provision)

Test Selection:
  --all                       Run all test suites
  --tag TAG                   Filter test suites by tag
  --list                      List all available test suites

Scenarios:
  --scenario NAME             Run a named scenario end to end
  --stages A,B,C              Run only these stages of the scenario
  --list-scenarios            List scenarios and the versions each supports

Feature Flags:
  --feature NAME              Enable a cluster feature (repeatable)
  --feature-group NAME        Enable a preset group of features
  --list-features             List all available features
  --list-groups               List all available feature groups
  --ocp-version VER           Filter features by OpenShift version
  --validate-only             Validate feature flags only (no execution)

Execution:
  -e KEY=VALUE                Extra Ansible variables (repeatable)
  -v / -vv / -vvv / -vvvv    Increase verbosity

AI Agent:
  --ai-agent                  Enable autonomous issue detection/remediation
  --ai-agent-dry-run          Detect and diagnose only (no fixes applied)

Output:
  --format {json,html,junit,all}  Output format (default: all)
  --no-save                   Don't save results to file
```

## Available Test Suites

| Test Suite | Description |
|------------|-------------|
| [`05-verify-mce-environment`](docs/test-suites/05-verify-mce-environment.md) | Validate MCE/CAPI/CAPA environment configuration before provisioning |
| [`10-configure-mce-environment`](docs/test-suites/10-configure-mce-environment.md) | Set up MCE environment for CAPI/CAPA cluster provisioning |
| [`11-install-capi-standalone`](docs/test-suites/11-install-capi-standalone.md) | Install CAPI/CAPA controllers via Helm charts for standalone mode |
| [`15-verify-rosa-ocm-role`](docs/test-suites/15-verify-rosa-ocm-role.md) | Verify ROSAOCMRoleConfig creation, reconciliation, status, and Retain deletion |
| [`20-rosa-hcp-provision`](docs/test-suites/20-rosa-hcp-provision.md) | Provision a ROSA HCP cluster with automated network and role configuration (supports `--feature` flags) |
| [`21-verify-feature-flags`](docs/test-suites/21-verify-feature-flags.md) | Verify provisioned cluster feature flags match requested configuration |
| [`22-rosa-hcp-private`](docs/test-suites/22-rosa-hcp-private.md) | Provision a PrivateLink ROSA HCP cluster (OpenShift 5.0 RC) |
| [`23-rosa-hcp-no-cni`](docs/test-suites/23-rosa-hcp-no-cni.md) | Provision a no-CNI (BYO-CNI) ROSA HCP cluster (OpenShift 5.0 RC) |
| [`25-rosa-hcp-upgrade-control-plane`](docs/test-suites/25-rosa-hcp-upgrade-control-plane.md) | Upgrade ROSA HCP control plane to next available OpenShift version |
| [`26-rosa-hcp-upgrade-machine-pool`](docs/test-suites/26-rosa-hcp-upgrade-machine-pool.md) | Upgrade ROSA HCP machine pool to next available OpenShift version |
| [`27-rosa-hcp-add-machinepool`](docs/test-suites/27-rosa-hcp-add-machinepool.md) | Add a new MachinePool + ROSAMachinePool pair to an existing cluster |
| [`28-rosa-hcp-delete-machinepool`](docs/test-suites/28-rosa-hcp-delete-machinepool.md) | Delete a MachinePool + ROSAMachinePool pair from an existing cluster |
| [`30-rosa-hcp-delete`](docs/test-suites/30-rosa-hcp-delete.md) | Delete ROSA HCP cluster and CAPA automation resources (ROSANetwork, ROSARoleConfig) |
| [`40-enable-capi-disable-hypershift`](docs/test-suites/40-enable-capi-disable-hypershift.md) | Switch MCE from HyperShift to CAPI/CAPA |
| [`41-disable-capi-enable-hypershift`](docs/test-suites/41-disable-capi-enable-hypershift.md) | Switch MCE from CAPI/CAPA to HyperShift |

### Per-run inputs

Region, namespace, and the OCM role name are not hardcoded in the suite
definitions. Override them with `-e`:

```bash
./run-test-suite.py 20-rosa-hcp-provision \
  -e aws_region=us-east-1 \
  -e rosa_hcp_namespace=my-ns

./run-test-suite.py 15-verify-rosa-ocm-role \
  -e ocm_role_config_name=my-role
```

Defaults:

- `aws_region`: from `-e`, otherwise the `AWS_REGION` environment variable or
  `vars/user_vars.yml`, otherwise the playbook default (usually `us-west-2`;
  the standalone install playbook defaults to `us-east-1` when `AWS_REGION` is
  unset)
- `rosa_hcp_namespace`: `ns-rosa-hcp` from `vars/vars.yml`
- `ocm_role_config_name`: `shared-ocm-role` from the verify playbook

The Jenkins pipeline exposes `AWS_REGION` and `ROSA_HCP_NAMESPACE` as
parameters and passes them to the ROSA HCP suites.

### Suite dependencies

A suite can declare the suites it needs in `depends_on`:

```json
"depends_on": ["20-rosa-hcp-provision"]
```

On `--all` and `--tag` runs, declared dependencies that are part of the same
selection run first, and a suite is skipped when a dependency selected with it
failed. A dependency the selection does not include is ignored — `--tag full`
still provisions without adding `10-configure-mce-environment`, which it did
not select. Single-suite runs are not affected.

Cleanup and restore suites are marked `always` and still run when their
dependency failed, so partially created resources are deleted and hub settings
restored:

```json
"depends_on": ["20-rosa-hcp-provision"],
"always": true
```

## Feature Flag System

The framework supports composable Day 1 feature testing via `--feature` CLI flags. Features are defined in `templates/schemas/feature-registry.yml` and resolved by `feature_manager.py`.

### Available Features

| CLI Flag | Feature | Resource |
|----------|---------|----------|
| `--feature private` | Private cluster networking | ROSAControlPlane |
| `--feature no-cni` | Deploy without default CNI | ROSAControlPlane |
| `--feature external-oidc` | External OIDC authentication | ROSAControlPlane |
| `--feature break-glass` | Break-glass credential verification | ROSAControlPlane |
| `--feature etcd-kms` | etcd encryption with AWS KMS | ROSAControlPlane |
| `--feature fips` | FIPS 140-2 compliance mode | ROSAControlPlane |
| `--feature security-groups` | Additional AWS security groups | ROSAMachinePool |
| `--feature tags` | Custom AWS resource tags | ROSAControlPlane |
| `--feature domain` | Custom domain prefix | ROSAControlPlane |
| `--feature channel-group` | Version channel (stable/fast/candidate) | ROSAControlPlane |
| `--feature disk-size` | Worker node root volume size | ROSAMachinePool |
| `--feature azs` | Availability zone count | ROSANetwork |
| `--feature image-registry` | Internal image registry config | ROSAControlPlane |
| `--feature parallel-upgrade` | Parallel node upgrade strategy | ROSAMachinePool |
| `--feature autoscaling` | Default MachinePool autoscaling | ROSAControlPlane |
| `--feature autoscaler` | Cluster autoscaler with expander | ROSAControlPlane |
| `--feature log-forwarding` | Audit log forwarding to CloudWatch | ROSAControlPlane |
| `--feature byon-vpc` | Pre-existing VPC and subnets instead of ROSANetwork | ROSAControlPlane |
| `--feature spot` | Run the machine pool on AWS Spot instances | ROSAMachinePool |

### Feature Groups

Preset combinations for common test scenarios:

| Group | Features |
|-------|----------|
| `day1-basic` | domain, azs, tags, channel-group, autoscaling |
| `day1-combo` | autoscaler, image-registry, parallel-upgrade, disk-size |
| `day1-security` | etcd-kms, fips, security-groups |
| `day1-networking` | external-oidc, log-forwarding |

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature-group day1-combo
```

### Feature Dependencies

Some features have dependencies that are automatically validated:

- `break-glass` requires `external-oidc`
- `fips` requires `etcd-kms`
- `byon-vpc` requires `private`

### Version Compatibility

Features are validated against the target OpenShift version. For example, `fips` requires 4.21+, `break-glass` requires 4.19+.

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature fips --ocp-version 4.22
```

## Feature Documentation

Each feature has detailed documentation in [`docs/features/`](docs/features/):

| Feature | Documentation |
|---------|--------------|
| Additional Tags | [additional-tags.md](docs/features/additional-tags.md) |
| Audit Log Forwarding | [audit-logging.md](docs/features/audit-logging.md) |
| Automated Verification | [automated-feature-verification.md](docs/features/automated-feature-verification.md) |
| Availability Zones | [availability-zones.md](docs/features/availability-zones.md) |
| Break-Glass Credentials | [break-glass-credentials.md](docs/features/break-glass-credentials.md) |
| Bring Your Own Network | [byon.md](docs/features/byon.md) |
| Channel Group | [channel-group.md](docs/features/channel-group.md) |
| Cluster Autoscaler Expander | [cluster-autoscaler-expander.md](docs/features/cluster-autoscaler-expander.md) |
| Default Autoscaling | [default-autoscaling.md](docs/features/default-autoscaling.md) |
| Disk Size | [disk-size.md](docs/features/disk-size.md) |
| Domain Prefix | [domain-prefix.md](docs/features/domain-prefix.md) |
| etcd KMS Encryption | [etcd-kms.md](docs/features/etcd-kms.md) |
| External OIDC | [external-oidc.md](docs/features/external-oidc.md) |
| FIPS Mode | [fips.md](docs/features/fips.md) |
| Image Registry | [image-registry.md](docs/features/image-registry.md) |
| No CNI | [no-cni.md](docs/features/no-cni.md) |
| Parallel Upgrade | [parallel-upgrade.md](docs/features/parallel-upgrade.md) |
| Private Network | [private-network.md](docs/features/private-network.md) |
| Security Groups | [security-groups.md](docs/features/security-groups.md) |
| Spot Market Options | [spot-market-options.md](docs/features/spot-market-options.md) |

## Version-Specific Templates

The framework supports version-specific cluster templates under `templates/versions/`:

```
templates/
├── versions/
│   ├── 4.18/features/
│   ├── 4.19/features/
│   ├── 4.20/features/
│   ├── 4.21/features/
│   │   ├── rosa-capi-network-cluster.yaml.j2
│   │   ├── rosa-combined-automation.yaml.j2
│   │   ├── rosa-controlplane-only.yaml.j2
│   │   ├── rosa-network-config.yaml.j2
│   │   └── rosa-role-config.yaml.j2
│   └── 4.22/features/
│       ├── rosa-combined-automation.yaml.j2
│       ├── rosa-controlplane-only.yaml.j2
│       ├── rosa-network-config.yaml.j2
│       └── rosa-role-config.yaml.j2
├── schemas/
│   ├── feature-registry.yml
│   └── version-compatibility.yml
└── capa-manager-bootstrap-credentials.yaml.j2
```

Supported versions: **4.18, 4.19, 4.20, 4.21, 4.22**

## AI Agent Framework

The framework includes an optional AI agent system for autonomous issue detection and remediation during test execution.

| Agent | Role |
|-------|------|
| Monitoring Agent | Real-time log analysis and issue detection |
| Diagnostic Agent | Root cause analysis with confidence scoring |
| Remediation Agent | Autonomous fix application (e.g., CloudFormation cleanup) |
| Learning Agent | Outcome tracking and confidence adjustment |

```bash
# Full autonomous mode
./run-test-suite.py 30-rosa-hcp-delete --ai-agent

# Observe-only mode (no fixes applied)
./run-test-suite.py 30-rosa-hcp-delete --ai-agent-dry-run
```

See [AI_AGENT_FRAMEWORK.md](AI_AGENT_FRAMEWORK.md) for details.

## Repository Structure

```
rosa-hcp-e2e-test/
├── playbooks/                  # Ansible playbook entry points
│   ├── configure_mce_environment.yml
│   ├── create_rosa_hcp_cluster.yml
│   ├── create_rosa_hcp_automated.yaml
│   ├── delete_rosa_hcp_cluster.yml
│   ├── add_rosa_machine_pool.yml
│   ├── delete_rosa_machine_pool.yml
│   ├── upgrade_rosa_control_plane.yml
│   ├── upgrade_rosa_machine_pool.yml
│   ├── verify_feature_flags.yml
│   ├── verify_break_glass_credentials.yml
│   ├── verify_capi_environment.yaml
│   ├── install_capi_standalone.yml
│   ├── enable_capi_disable_hypershift.yml
│   └── disable_capi_enable_hypershift.yml
├── tasks/                      # Reusable Ansible task files (60+)
├── templates/                  # Jinja2 templates and schemas
│   ├── versions/{4.18-4.22}/   # Version-specific feature templates
│   └── schemas/                # Feature registry and compatibility
├── roles/                      # Ansible roles
│   └── configure-capa-environment/
├── agents/                     # AI agent framework
│   ├── base_agent.py
│   ├── monitoring_agent.py
│   ├── diagnostic_agent.py
│   ├── remediation_agent.py
│   ├── learning_agent.py
│   ├── aws_client.py
│   ├── domains/rosa_hcp/
│   ├── knowledge_base/
│   ├── test_agents.py
│   └── test_aws_client.py
├── tests/                      # Unit and integration tests
│   ├── test_feature_manager.py
│   ├── test_run_test_suite.py
│   ├── test_playbook_structure.py
│   ├── test_machinepool_playbooks.py
│   ├── test_suite_json_schema.py
│   ├── test_template_defaults.py
│   └── test_vars_defaults.py
├── scripts/                    # Utility scripts
│   ├── check_cfn_stack_status.py
│   ├── test_check_cfn_stack_status.py
│   ├── check_crd_feature_support.sh
│   └── cleanup_orphaned_iam_roles.sh
├── test-suites/                # JSON test suite definitions
├── docs/                       # Feature documentation
│   └── features/               # Per-feature documentation (18 features)
├── vars/                       # Variable files
│   ├── vars.yml                # Default variables
│   ├── user_vars.yml.example   # Credential template
│   └── user_vars.yml           # User credentials (gitignored)
├── feature_manager.py          # Feature flag resolution engine
├── run-test-suite.py           # CLI test runner
├── ansible.cfg                 # Ansible configuration
├── Jenkinsfile                 # Jenkins pipeline (14 stages)
├── Dockerfile.prow             # Prow CI container
├── AI_AGENT_FRAMEWORK.md       # AI agent documentation
└── picsAgentPod_capa.yaml      # Jenkins agent pod spec
```

## Jenkins Integration

The `Jenkinsfile` defines a 14-stage pipeline:

| Stage | Suite | Condition |
|-------|-------|-----------|
| Clone Repository | — | Always |
| Install Python Dependencies | — | Always |
| Verify OCP Credentials | — | Always (fails if missing) |
| Configure CAPI/CAPA | `10` | Always |
| Validate Feature Flags | — | `CLUSTER_FEATURES` is set |
| Provision ROSA HCP | `20` | Configure passes |
| Verify Feature Flags | `21` | Provision passes + features set |
| Add MachinePool | `27` | Provision passes |
| Delete MachinePool | `28` | Add MachinePool passes |
| Upgrade Control Plane | `25` | Provision passes + `RUN_UPGRADE_TESTS=true` |
| Upgrade Machine Pool | `26` | CP upgrade passes + `RUN_UPGRADE_TESTS=true` |
| Delete ROSA HCP | `30` | Provision passes + `CLEANUP_AFTER_TEST=true` |
| Restore HyperShift | `41` | `RESTORE_HYPERSHIFT=true` (default) |
| Archive Results | — | Always |

### Jenkins Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `OCP_HUB_API_URL` | — | OpenShift cluster API URL |
| `OCP_HUB_CLUSTER_USER` | `kubeadmin` | OpenShift username |
| `OCP_HUB_CLUSTER_PASSWORD` | — | OpenShift password |
| `MCE_NAMESPACE` | `multicluster-engine` | MCE namespace |
| `OCM_CLIENT_ID` | — | OCM client ID |
| `OCM_CLIENT_SECRET` | — | OCM client secret |
| `TEST_GIT_BRANCH` | `main` | Git branch to test |
| `NAME_PREFIX` | `jnk` | Cluster name prefix |
| `CLUSTER_FEATURES` | — | Comma-separated features (e.g., `no-cni,etcd-kms`) |
| `EXTRA_FEATURE_VARS` | — | Additional key=value pairs |
| `ETCD_KMS_ARN` | — | AWS KMS ARN for etcd encryption |
| `RUN_UPGRADE_TESTS` | `false` | Run upgrade tests |
| `CLEANUP_AFTER_TEST` | `true` | Delete cluster after test |
| `RESTORE_HYPERSHIFT` | `true` | Restore HyperShift after test |

### Required Jenkins Credentials

- `CAPI_AWS_ACCESS_KEY_ID` — AWS access key
- `CAPI_AWS_SECRET_ACCESS_KEY` — AWS secret key
- `CAPI_AWS_ACCOUNT_ID` — AWS account ID
- `CAPI_OCM_CLIENT_ID` — OCM client ID
- `CAPI_OCM_CLIENT_SECRET` — OCM client secret

## Running Tests (pytest)

```bash
python3 -m pytest tests/ -v
```

## Troubleshooting

### Debug Mode

```bash
# Maximum verbosity
./run-test-suite.py 20-rosa-hcp-provision -vvv

# Validate feature flags only (no cluster connection needed)
./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature no-cni

# Check Ansible playbook syntax
ansible-playbook playbooks/create_rosa_hcp_cluster.yml --syntax-check
```

### Test Results

`<label>` is the suite ID without its ordering prefix
(`20-rosa-hcp-provision` → `rosa-hcp-provision`), so it is unique per suite.

```
test-results/
├── feature-verification.json               # latest per-feature results (suite 21)
├── latest-<label>.json                    # latest JSON report
├── latest-<label>.html                    # latest HTML report
└── <date>/
    ├── test-run-<label>-<timestamp>.xml   # one JUnit report per run
    ├── test-run-<label>-<timestamp>.json
    ├── test-run-<label>-<timestamp>.html
    └── feature-verification-<label>-<timestamp>.json
```

Only the dated `test-run-*.xml` is written: Jenkins consumes
`test-results/**/*.xml`, so a `latest-*.xml` copy would make every testcase be
counted twice.

### Per-Feature Verification Results

Suite 21 writes `test-results/feature-verification.json` **while the cluster is
still alive** — after the delete stage its observed values cannot be recovered.
The file records, for every requested feature, whether it passed, failed, or
warned, plus the resource specs the checks read.

Two things consume it:

**1. JUnit expands to one testcase per feature.** Without the artifact the whole
suite reports as a single test; with it, CI names the feature that broke and can
trend one feature across builds:

```xml
<testcase classname="FeatureVerification" name="channel_group"/>
<testcase classname="FeatureVerification" name="fips">
  <skipped message="CRD has no field 'fips' — platform limitation"/>
</testcase>
```

A **warned** feature (the installed CRD has no field for it) maps to `skipped`,
not `failure` — a platform limitation is not an automation defect, and keeping
the build green while still surfacing the gap is the distinction you need when
validating a new OpenShift release. If the playbook dies before writing the
artifact (login failure, timeout), the runner falls back to the single
playbook-level testcase carrying the raw error.

## Contributing

1. Fork the repository
2. Create a feature branch from `main`
3. Add tests for new functionality
4. Ensure all existing tests pass: `python3 -m pytest tests/ -v`
5. Lint playbooks: `ansible-lint playbooks/`
6. Submit a pull request to `stolostron/rosa-hcp-e2e-test`

### Adding a New Feature Test

A feature flows through four layers — the **registry**, the **templates**, the
**provisioning playbook** and the **suite-21 verification wiring** — and all four
have to agree. Miss one and the usual result is not a red test: it is a test that
passes against a cluster where the feature was never applied.

The full procedure lives in [`SKILLS.md`](SKILLS.md), which is also packaged as a
Claude Code skill so an agent can execute it end to end.

#### With Claude Code (recommended)

The skill is tracked in this repo, so cloning it is the whole setup — no install
step. Start a session in the repo root and describe the task; nothing is loaded
until you do:

```bash
claude
```

```
> add a feature test for the disableWorkloadMonitoring field on ROSAControlPlane
```

Or invoke it by name, `/add-feature-test`.

Either way the agent **reads before it asks**. It pulls the field shape from
whatever source you named — an upstream PR, the live CRD on your hub, the webhook,
the OCM model — drafts an intake form with a `[source]` tag on every derived line,
and then shows you that form with the two or three decisions it genuinely cannot
derive (CI-safe default value, which feature group, Day-2 scope). Confirming the
draft is your only required input.

The more specific your opening line, the fewer questions you get:

```
> add a feature test for kubernetes-sigs/cluster-api-provider-aws/pull/5432
> add a feature test for disableWorkloadMonitoring on ROSAControlPlane
> add a feature test for "some randome related text with details"
```

##### The shortest useful invocation

Three facts cannot be derived from anything, so supply those and let the agent work
out the rest:

```
> Add new feature test
> feature_id: disable_workload_monitoring
> CRD resource: ROSAControlPlane
> CRD field path: disableWorkloadMonitoring
```

The form's labels are not required — *"add a feature test for
disableWorkloadMonitoring on ROSAControlPlane, id disable_workload_monitoring"*
does the same thing.

This is **preferable to filling the intake form in yourself and pasting it**. Those
three lines are the only facts the agent cannot establish on its own; everything
else it derives and verifies rather than taking on trust, reading the live CRD on
your hub for the type, default, validation pattern, description and the CEL
immutability rules. Give it a complete form and it only spot-checks what you wrote;
give it the three keys and it reads the API properly. A guessed field path is
exactly what produces a test that silently asserts nothing.

You will still be asked two to four questions, each with a recommendation attached,
because they are judgments about this repo's test matrix rather than facts about
the API:

| It will ask | Because no source can answer it |
|---|---|
| CI-safe default value | Which value is safe in automation is operational judgment; a plausible-looking one can make clusters fail to provision for reasons unrelated to the test |
| Feature group | Trades coverage against blast radius, and can raise a whole group's version floor |
| `min_version` | The CRD says when the field entered CAPA, not which MCE/OCP build ships it |
| Day-2 scope | Upstream may document mutations this repo has no suite for |

Two caveats:

1. The live-CRD lookup needs `oc` pointed at a hub that actually has the CRD.
   Without one it falls back to fetching the schema from upstream by branch or tag —
   still fine, just say which provider version you care about.
2. If the field comes from an **unmerged** upstream PR, pass the PR link as well.
   The CRD cannot tell you about cross-field webhook conflicts ("rejects
   `fooOptions` when `barID` is set") — those are Go code only, and they are where
   `mutual_exclusions` entries come from.

##### Filling the intake form yourself

If you would rather supply everything up front, the form is Part 2 of
[`references/intake.md`](.claude/skills/add-feature-test/references/intake.md):

```bash
sed -n '229,289p' .claude/skills/add-feature-test/references/intake.md > /tmp/intake.md
# fill it in, then:
claude
> add a feature test — I filled the intake form myself, it is at /tmp/intake.md
```

The agent then skips the source-reading step, spot-checks your CRD resource and
field path against the live CRD, flags any disagreement rather than silently
following either version, and asks only about the lines you left blank. Note the
block in that file is a worked example filled in with `audit_logging` values, so
you are overwriting values rather than filling blanks.

#### By hand

Read [`.claude/skills/add-feature-test/SKILL.md`](.claude/skills/add-feature-test/SKILL.md)
and work through its ten steps; the references beside it hold copy-paste skeletons,
the validation commands, and the gotchas that produce silently-passing tests. In
outline:

| Layer | Files |
|---|---|
| Registry | `templates/schemas/feature-registry.yml` (`var_map`, `cli_aliases`, `cli_features`, the feature entry) and `templates/schemas/version-compatibility.yml` |
| Templates | `rosa-controlplane-only.yaml.j2` **and** `rosa-combined-automation.yaml.j2` under `templates/versions/4.22/features/`, then copied byte-for-byte to `5.0/` |
| Verification | `crd_field_map` + a `CHECK:` block in `playbooks/verify_feature_flags.yml`, and `tasks/features/verify_<id>.yml` |
| Docs and tests | `docs/features/<feature>.md`, both README tables above, and a `TestMyFeature` class in `tests/test_feature_manager.py` |

#### Checking your work

```bash
./run-test-suite.py --list-features                          # registry parses, metadata is right
./run-test-suite.py 20-rosa-hcp-provision \
  --feature my-feature --validate-only                       # resolution, deps, version gate
make verify-skills FEATURE=my_feature                        # every layer above agrees
python3 -m pytest tests agents scripts -q                    # same paths CI runs
```

`make verify-skills` walks your feature through each layer the procedure requires
and exits non-zero on the first disagreement. `tests/test_skills_md.py` runs the
same checks for every feature in CI, so a half-wired feature fails a build rather
than surfacing as a confusing WARN forty minutes into a provision.

## Support

- **Issues**: https://github.com/stolostron/rosa-hcp-e2e-test/issues
- **Pull Requests**: https://github.com/stolostron/rosa-hcp-e2e-test/pulls

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## References

- [ROSA Documentation](https://docs.openshift.com/rosa/welcome/index.html)
- [Cluster API Documentation](https://cluster-api.sigs.k8s.io/)
- [CAPA Provider Documentation](https://cluster-api-aws.sigs.k8s.io/)
- [MCE Documentation](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/)
