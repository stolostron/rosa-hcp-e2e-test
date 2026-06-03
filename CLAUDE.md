# CLAUDE.md

## Project Overview
ROSA HCP E2E test automation — Ansible playbooks + Python test runner + AI agent framework for end-to-end ROSA HCP (Hosted Control Plane) cluster lifecycle testing via CAPI/CAPA on OpenShift MCE.

## Project Structure
- `playbooks/` — Ansible playbooks (create, delete, upgrade, configure clusters)
- `roles/` — Ansible roles (`configure-capa-environment`)
- `tasks/` — Ansible task files (granular operations: login, network, roles, wait loops)
- `test-suites/` — JSON test suite definitions (numbered, sequential pipeline stages)
- `tests/` — Python pytest unit tests
- `agents/` — AI agent framework (monitoring, diagnostic, remediation, learning agents)
- `scripts/` — Utility scripts (CRD checks, CloudFormation status, IAM cleanup)
- `templates/` — Jinja2 templates for Kubernetes resource generation
- `vars/` — Ansible variable files (`vars.yml`, `user_vars.yml`)
- `run-test-suite.py` — Main CLI test runner (executes Ansible test suites)
- `Jenkinsfile` — CI/CD pipeline definition
- `picsAgentPod_capa.yaml` — Jenkins agent pod spec (Kubernetes)

## Commands
- **Run a test suite**: `./run-test-suite.py <suite-id>` (e.g., `./run-test-suite.py 20-rosa-hcp-provision`)
- **List test suites**: `./run-test-suite.py --list`
- **Dry run**: `./run-test-suite.py <suite-id> --dry-run`
- **With extra vars**: `./run-test-suite.py <suite-id> -e key=value`
- **Verbose**: `./run-test-suite.py <suite-id> -vvv`
- **With AI agents**: `./run-test-suite.py <suite-id> --ai-agent`
- **JUnit output**: `./run-test-suite.py <suite-id> --format junit`
- **Python tests**: `python3 -m pytest tests/`
- **Python lint**: `python3 -m pylint run-test-suite.py agents/`

## Tech Stack
- Python 3, Ansible
- pytest for unit tests
- boto3 for AWS operations (AI agent remediation)
- OpenShift CLI (`oc`) for cluster interactions
- Jenkins CI/CD with Kubernetes agent pods

## Environment Setup
- Copy `vars/user_vars.yml.example` to `vars/user_vars.yml` and fill in credentials
- Required credentials: OCP hub URL/user/password, AWS keys, OCM client ID/secret
- Ansible config: `ansible.cfg` (roles path: `./roles`)
- Never commit `vars/user_vars.yml` to git

## Rules
- Always check for security issues (secrets, keys, credentials) before committing
- Never push directly to main — always create a PR
- Make a plan first and show me the outline
- Branch naming: `feat/`, `fix/`, `docs/`, `ci/`, `chore/` + kebab-case

## Conventions
- Test suite JSON files are numbered for pipeline ordering (05, 10, 20, 25, 27, 28, 30, 40, 41)
- Playbook extra vars use UPPERCASE for credentials, lowercase for config
- Test results output to `test-results/` as JUnit XML, JSON, and HTML
- Jinja2 templates in `templates/` use `.yaml.j2` extension
- Test files follow `test_*.py` naming in `tests/`

## Test Suite Reference

| ID | Name | Description |
|----|------|-------------|
| 05 | Verify MCE Environment | Check MCE/CAPI/CAPA status (standalone) |
| 10 | Configure MCE Environment | Disable HyperShift, enable CAPI/CAPA |
| 20 | ROSA HCP Provision | Provision a ROSA HCP cluster via CAPA |
| 25 | Upgrade Control Plane | Upgrade ROSA control plane version |
| 26 | Upgrade Machine Pool | Upgrade ROSA machine pool version |
| 27 | Add MachinePool | Add a ROSA MachinePool to existing cluster |
| 28 | Delete MachinePool | Delete a ROSA MachinePool |
| 30 | Delete ROSA HCP | Delete ROSA HCP cluster and cleanup |
| 40 | Enable CAPI / Disable HyperShift | Toggle to CAPI mode |
| 41 | Disable CAPI / Enable HyperShift | Restore HyperShift mode |

## Pipeline Stage Dependencies
- Suite 10 (Configure) must pass before 20 (Provision)
- Suite 20 must pass before 27 (Add MP), 25 (Upgrade CP), 30 (Delete)
- Suite 27 must pass before 28 (Delete MP)
- Suite 25 (Upgrade CP) must pass before 26 (Upgrade MP)
- Suite 30 (Delete) runs only if `CLEANUP_AFTER_TEST=true` and provisioning passed
- Suite 41 (Restore HyperShift) runs independently if `RESTORE_HYPERSHIFT=true` (default)

## Feature Flags
Features are passed to `run-test-suite.py` via `--feature <name>` (used in Jenkinsfile via `CLUSTER_FEATURES` param). Available features:

| CLI Flag | Ansible Var | CRD Field |
|----------|-------------|-----------|
| `autoscaler` | `cluster_autoscaler_expander=true` | ROSAControlPlane `.spec.autoscaler.expanders` |
| `image-registry` | `image_registry_config=true` | ROSAControlPlane `.spec.clusterRegistryConfig` |
| `disk-size` | `root_volume_size=500` | ROSAMachinePool `.spec.rootVolume.size` |
| `user-agent` | `user_agent=capa-e2e-test` | ROSAControlPlane `.spec.userAgent` |
| `parallel-upgrade` | `parallel_node_upgrade=2` | ROSAMachinePool `.spec.updateConfig.rollingUpdate` |
| `no-cni` | `no_cni=true` | ROSAControlPlane `.spec.network.networkType` |
| `external-oidc` | `external_oidc=true` | ROSAControlPlane `.spec.enableExternalAuthProviders` |
| `etcd-kms` | `etcd_encryption_kms_arn=<ARN>` | ROSAControlPlane `.spec.etcdEncryptionKMSARN` |
| `fips` | `fips=true` | ROSAControlPlane `.spec.fips` |
| `private` | `private=true` | ROSAControlPlane `.spec.endpointAccess` |
| `autoscaling` | `default_autoscaling=true` | ROSAControlPlane `.spec.defaultMachinePoolSpec.autoscaling` |
| `channel-group` | `channel_group=stable` | ROSAControlPlane `.spec.channelGroup` |
| `tags` | `additional_tags={Team: PICS}` | ROSAControlPlane `.spec.additionalTags` |
| `azs` | `availability_zone_count=2` | ROSANetwork `.spec.availabilityZones` |
| `domain` | `domain_prefix=<prefix>` | ROSAControlPlane `.spec.domainPrefix` |
| `security-groups` | `additional_security_groups=["sg-xxx"]` | ROSAMachinePool `.spec.additionalSecurityGroups` |
| `log-forwarding` | `log_forward_enabled=true` | ROSAControlPlane `.spec.cloudWatchlogForwarder` |

Use `--validate-only` to check feature names and dependencies without connecting to a cluster.
Check CRD support on a live cluster: `./scripts/check_crd_feature_support.sh`

## AI Agent Modes
- `--ai-agent` — **Live mode**: monitors Ansible output in real-time, detects issues, diagnoses root cause, and applies remediation fixes autonomously (e.g., CloudFormation stack cleanup)
- `--ai-agent-dry-run` — **Dry-run mode**: detects and diagnoses issues but does NOT apply any fixes; logs what it would have done
- Agents: MonitoringAgent (pattern detection) → DiagnosticAgent (root cause) → RemediationAgent (apply fix) → LearningAgent (track outcomes, adjust confidence)
- Remediation only triggers when diagnostic confidence >= 0.7
- Agent logs saved to `agents/knowledge_base/intervention_log.json`

## Key Defaults (vars/vars.yml)
- `openshift_version`: `4.21`
- `supported_versions`: `4.18`, `4.19`, `4.20`, `4.21`
- `cloud_provider`: `aws`
- `capi_namespace`: `ns-rosa-hcp`
- `capa_system_namespace`: `multicluster-engine`
- `mce_namespace`: `multicluster-engine`
- `capi_installation_method`: `clusterctl`
- `rosa_creds_secret`: `rosa-creds-secret`
- `acm21174_config.default_network_config.cidr_block`: `10.0.0.0/16`
- `acm21174_config.default_network_config.availability_zones`: `us-west-2a`, `us-west-2b`

## Common Debugging Commands
```bash
oc get rosacontrolplanes -A
oc get rosamachinepools -A
oc get rosanetwork -A
oc get rosaroleconfig -A
oc logs -n multicluster-engine deployment/capa-controller-manager --tail=100
oc logs -n multicluster-engine deployment/capi-controller-manager --tail=100
oc get deploy -n multicluster-engine | grep -E 'capi|capa'
oc get multiclusterengine -o yaml
oc get crd | grep -E 'rosa|capa|capi'
./scripts/check_crd_feature_support.sh
./scripts/check_crd_feature_support.sh --json
```

## .gitignore Expectations
The following must never be committed:
- `vars/user_vars.yml` — contains credentials
- `test-results/` — generated test output
- `results/` — legacy test output
- `__pycache__/`, `*.pyc` — Python bytecode
- `*.pem`, `*.key`, `*.crt`, `kubeconfig` — secrets and certificates
- `*.log` — log files
- `.ansible/`, `*.retry` — Ansible runtime files

## CI/CD
- Jenkins pipeline: Clone → Install deps → Verify creds → Configure CAPI/CAPA → Validate features → Provision → Verify features → Add MachinePool → Delete MachinePool → Upgrade CP → Upgrade MP → Delete → Restore HyperShift → Archive
- JUnit XML results from `test-results/**/*.xml`
- AI agents enabled in CI via `--ai-agent` flag
- Pipeline runs on Kubernetes pod (`picsAgentPod_capa.yaml`)

## Jenkins Gotchas
- **Never use "Rebuild"** — it replays the old Jenkinsfile from the original build's commit, ignoring any changes merged to main since then. Always use **"Build with Parameters"** to pick up the latest Jenkinsfile from HEAD.
- **Lightweight checkout caching**: Jenkins may cache the Jenkinsfile SCM checkout. If a fresh "Build with Parameters" still uses a stale Jenkinsfile, disable "Lightweight checkout" in the job config (Pipeline → uncheck "Lightweight checkout") to force a full `git clone` every build.
- **Split-brain architecture**: The Jenkinsfile (pipeline definition, stages, parameters) comes from `origin/main`, but the code under test (`run-test-suite.py`, feature_manager, playbooks) comes from `TEST_GIT_BRANCH`. Both must have matching feature support — the Jenkinsfile must pass `--feature` flags AND `run-test-suite.py` on the target branch must accept them.
- **Ghost parameters**: Jenkins persists parameter fields from previous builds. If a parameter (e.g., `CLUSTER_FEATURES`) appears on the build form but the Jenkinsfile doesn't reference it, the value is silently ignored.
