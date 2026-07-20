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

- **OpenShift Hub Cluster** with MCE 2.x or ACM 2.x installed
- **AWS Account** with appropriate permissions for ROSA
- **OCM (OpenShift Cluster Manager)** credentials
- **Python** 3.8+ with `boto3` and `PyYAML`
- **Ansible** 2.19+
- **oc CLI** installed and authenticated

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
AWS_ACCESS_KEY_ID: "your-aws-key"
AWS_SECRET_ACCESS_KEY: "your-aws-secret"
OCM_CLIENT_ID: "your-ocm-client-id"
OCM_CLIENT_SECRET: "your-ocm-client-secret"
MCE_NAMESPACE: "multicluster-engine"
```

3. Authenticate to your OpenShift cluster:
```bash
oc login <your-api-url> -u <your-user> -p <your-password>
```
The playbooks load credentials from `vars/user_vars.yml` automatically via `vars_files`.

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

Feature Flags:
  --feature NAME              Enable a cluster feature (repeatable)
  --feature-group NAME        Enable a preset group of features
  --list-features             List all available features
  --list-groups               List all available feature groups
  --ocp-version VER           Filter features by OpenShift version
  --validate-only             Validate feature flags only (no execution)

Execution:
  -e KEY=VALUE                Extra Ansible variables (repeatable)
  --dry-run                   Ansible check mode (no changes)
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
| `05-verify-mce-environment` | Validate MCE/CAPI/CAPA environment configuration before provisioning |
| `10-configure-mce-environment` | Set up MCE environment for CAPI/CAPA cluster provisioning |
| `20-rosa-hcp-provision` | Provision a ROSA HCP cluster with automated network and role configuration (supports `--feature` flags) |
| `21-verify-feature-flags` | Verify provisioned cluster feature flags match requested configuration |
| `25-rosa-hcp-upgrade-control-plane` | Upgrade ROSA HCP control plane to next available OpenShift version |
| `26-rosa-hcp-upgrade-machine-pool` | Upgrade ROSA HCP machine pool to next available OpenShift version |
| `27-rosa-hcp-add-machinepool` | Add a new MachinePool + ROSAMachinePool pair to an existing cluster |
| `28-rosa-hcp-delete-machinepool` | Delete a MachinePool + ROSAMachinePool pair from an existing cluster |
| `30-rosa-hcp-delete` | Delete ROSA HCP cluster and CAPA automation resources (ROSANetwork, ROSARoleConfig) |
| `40-enable-capi-disable-hypershift` | Switch MCE from HyperShift to CAPI/CAPA |
| `41-disable-capi-enable-hypershift` | Switch MCE from CAPI/CAPA to HyperShift |

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
| `--feature user-agent` | Custom ROSA API user agent | ROSAControlPlane |

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

# Dry-run mode (validates but doesn't execute)
./run-test-suite.py 20-rosa-hcp-provision --dry-run

# Validate feature flags only (no cluster connection needed)
./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature no-cni

# Check Ansible playbook syntax
ansible-playbook playbooks/create_rosa_hcp_cluster.yml --syntax-check
```

### Test Results

```
test-results/
├── test-run-<timestamp>.log
├── junit-<test-suite>.xml
└── results-<timestamp>.json
```

## Contributing

1. Fork the repository
2. Create a feature branch from `main`
3. Add tests for new functionality
4. Ensure all existing tests pass: `python3 -m pytest tests/ -v`
5. Lint playbooks: `ansible-lint playbooks/`
6. Submit a pull request to `stolostron/rosa-hcp-e2e-test`

### Adding a New Feature

1. Add the feature definition to `templates/schemas/feature-registry.yml`
2. Add a CLI alias under `cli_aliases`
3. Add the feature ID to `cli_features` if it's a Day 1 creation feature
4. Add version-specific template conditionals under `templates/versions/`
5. Add a feature doc to `docs/features/`
6. Add the feature to a feature group if applicable
7. Run `./run-test-suite.py --list-features` to verify

## Support

- **Issues**: https://github.com/stolostron/rosa-hcp-e2e-test/issues
- **Pull Requests**: https://github.com/stolostron/rosa-hcp-e2e-test/pulls

## Open Pull Requests

| PR | Title | Status |
|----|-------|--------|
| [#80](https://github.com/stolostron/rosa-hcp-e2e-test/pull/80) | fix: 4 latent provisioning bugs in default variable handling | In Review |
| [#79](https://github.com/stolostron/rosa-hcp-e2e-test/pull/79) | fix: harden credential handling across pipeline and Ansible tasks | In Review |
| [#74](https://github.com/stolostron/rosa-hcp-e2e-test/pull/74) | feat: rewrite feature verification with AWS CLI and OCM API | In Progress |
| [#72](https://github.com/stolostron/rosa-hcp-e2e-test/pull/72) | feat: add private subnet and BYON support for `--feature private` and `--feature byon-vpc` | In Progress |
| [#70](https://github.com/stolostron/rosa-hcp-e2e-test/pull/70) | feat: add break-glass credential 403 diagnostic test for external-auth clusters | In Progress |

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## References

- [ROSA Documentation](https://docs.openshift.com/rosa/welcome/index.html)
- [Cluster API Documentation](https://cluster-api.sigs.k8s.io/)
- [CAPA Provider Documentation](https://cluster-api-aws.sigs.k8s.io/)
- [MCE Documentation](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/)
