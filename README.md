# ROSA HCP Feature Test Automation

Feature testing framework for **ROSA HCP** (Red Hat OpenShift Service on AWS - Hosted Control Plane) clusters using **Cluster API Provider AWS (CAPA)**.

## Overview

This repository provides comprehensive automated testing for ROSA HCP cluster lifecycle management through CAPI/CAPA, including:

- ✅ MCE (Multicluster Engine) environment configuration and verification
- 🚀 ROSA HCP cluster provisioning with automated network and IAM role setup
- 🔄 Cluster lifecycle operations (create, update, delete)
- 🗑️ Resource cleanup with finalizer handling for stuck deletions
- 🧪 Full end-to-end test automation
- 📊 JSON-based test suite framework with Jenkins integration

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   MCE Hub Cluster                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Multicluster Engine (MCE)                           │   │
│  │  ├── CAPI Controller (cluster-api)                   │   │
│  │  └── CAPA Controller (cluster-api-provider-aws)      │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           │ Manages                          │
│                           ▼                                  │
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
- **Python** 3.8+ installed
- **oc CLI** installed and authenticated
- **kubectl** CLI installed

### Environment Setup

1. Clone the repository:
```bash
git clone https://github.com/stolostron/rosa-hcp-e2e-test.git
cd rosa-hcp-e2e-test
```

2. Configure environment variables:
```bash
export OCP_HUB_API_URL="https://api.your-cluster.com:6443"
export OCP_HUB_CLUSTER_USER="kubeadmin"
export OCP_HUB_CLUSTER_PASSWORD="your-password"
export MCE_NAMESPACE="multicluster-engine"
export OCM_CLIENT_ID="your-ocm-client-id"
export OCM_CLIENT_SECRET="your-ocm-client-secret"
export AWS_ACCESS_KEY_ID="your-aws-key"
export AWS_SECRET_ACCESS_KEY="your-aws-secret"
export AWS_ACCOUNT_ID="your-aws-account-id"
```

3. Authenticate to your OpenShift cluster:
```bash
oc login ${OCP_HUB_API_URL} -u ${OCP_HUB_CLUSTER_USER} -p ${OCP_HUB_CLUSTER_PASSWORD}
```

### Running Tests

The test suite uses a Python test runner that executes predefined test scenarios:

```bash
# Run a specific test suite
./run-test-suite.py 10-configure-mce-environment

# Run with verbose output
./run-test-suite.py 20-rosa-hcp-provision -vvv

# Run with JUnit XML output for CI/CD
./run-test-suite.py 20-rosa-hcp-provision --format junit

# Pass environment variables inline
./run-test-suite.py 20-rosa-hcp-provision \
  -e name_prefix="test" \
  -e AWS_REGION="us-west-2"
```

### Available Test Suites

| Test Suite | Description |
|------------|-------------|
| `05-verify-mce-environment` | Verify MCE environment health and readiness |
| `10-configure-mce-environment` | Configure and verify MCE environment with CAPI/CAPA |
| `20-rosa-hcp-provision` | Provision a new ROSA HCP cluster |
| `30-rosa-hcp-delete` | Delete ROSA HCP cluster and cleanup resources |
| `40-enable-capi-disable-hypershift` | Switch from HyperShift to CAPI/CAPA |
| `41-disable-capi-enable-hypershift` | Switch from CAPI/CAPA to HyperShift |

## Test Suite Structure

Test suites are defined in JSON format under `test-suites/`:

```json
{
  "name": "20-rosa-hcp-provision",
  "description": "Provision ROSA HCP cluster via CAPI/CAPA",
  "environment_variables": {
    "required": ["OCP_HUB_API_URL", "AWS_ACCESS_KEY_ID", "OCM_CLIENT_ID"],
    "optional": ["name_prefix", "AWS_REGION"]
  },
  "tasks": [
    {
      "name": "Create ROSANetwork",
      "playbook": "playbooks/create_rosa_hcp_cluster.yml",
      "extra_vars": {
        "cluster_name": "{{ name_prefix }}-rosa-test",
        "aws_region": "{{ AWS_REGION | default('us-east-1') }}"
      }
    }
  ]
}
```

## Repository Structure

```
rosa-hcp-e2e-test/
├── playbooks/              # Main Ansible playbook entry points
│   ├── configure_mce_environment.yml
│   ├── create_rosa_hcp_cluster.yml
│   ├── delete_rosa_hcp_cluster.yml
│   ├── enable_capi_disable_hypershift.yml
│   └── disable_capi_enable_hypershift.yml
├── tasks/                  # Reusable Ansible task files
│   ├── create_rosa_network.yml
│   ├── create_rosa_role_config.yml
│   ├── create_rosa_control_plane.yml
│   ├── delete_rosa_hcp_resources.yml
│   └── wait_for_rosa_control_plane_ready.yml
├── templates/              # Jinja2 templates for Kubernetes resources
│   ├── rosa-network.yaml.j2
│   ├── rosa-control-plane.yaml.j2
│   └── rosa-machine-pool.yaml.j2
├── roles/                  # Ansible roles for specific features
├── test-suites/            # JSON test suite definitions
│   ├── 05-verify-mce-environment.json
│   ├── 10-configure-mce-environment.json
│   ├── 20-rosa-hcp-provision.json
│   └── 30-rosa-hcp-delete.json
├── vars/                   # Variable files
│   ├── vars.yml           # Default variables
│   └── user_vars.yml      # User-specific variables (gitignored)
├── run-test-suite.py       # Python test runner
├── Jenkinsfile            # Jenkins pipeline definition
└── README.md              # This file
```

## Key Features

- Extendable framework for ROSA-HCP features test-case eg; Adding machinePool with fips enable
- Using AI agent to monitor the test logs and provide solution and fixes

### Automated Network Setup
- Creates VPC, subnets, and security groups via CloudFormation
- Configures private hosted zones for cluster DNS
- Handles multi-AZ subnet distribution

### IAM Role Automation
- Automatically creates ROSA-required IAM roles
- Configures OIDC provider for pod identity
- Sets up installer and control plane roles

### CI/CD Integration
- Jenkins pipeline support via `Jenkinsfile`
- JUnit XML output for test reporting
- Environment variable injection
- Parallel test execution support

## Jenkins Integration

This repository includes a `Jenkinsfile` for automated testing in Jenkins:

```groovy
pipeline {
  agent any

  stages {
    stage('Configure MCE') {
      steps {
        sh './run-test-suite.py 10-configure-mce-environment --format junit'
      }
    }

    stage('Provision ROSA HCP') {
      steps {
        sh './run-test-suite.py 20-rosa-hcp-provision --format junit -e name_prefix="${JOB_NAME}"'
      }
    }

    stage('Delete ROSA HCP') {
      steps {
        sh './run-test-suite.py 30-rosa-hcp-delete --format junit -e name_prefix="${JOB_NAME}"'
      }
    }
  }

  post {
    always {
      junit 'test-results/*.xml'
    }
  }
}
```

### Required Jenkins Credentials

Configure the following credentials in Jenkins:

- `MCE_HUB_CREDENTIALS` - OpenShift hub cluster credentials (username/password)
- `OCM_CREDENTIALS` - OCM client ID and secret (username/password)
- `AWS_CREDENTIALS` - AWS access key ID and secret access key (username/password)

## Troubleshooting

### Debug Mode

Run tests with verbose output for debugging:

```bash
# Maximum verbosity (-vvv shows all Ansible task output)
./run-test-suite.py 20-rosa-hcp-provision -vvv

# Dry-run mode (validates but doesn't execute)
./run-test-suite.py 20-rosa-hcp-provision --dry-run

# Check Ansible playbook syntax
ansible-playbook playbooks/create_rosa_hcp_cluster.yml --syntax-check
```

### Viewing Logs and Results

Test execution logs and results are stored in:

```
test-results/
├── test-run-<timestamp>.log        # Full test execution log
├── junit-<test-suite>.xml          # JUnit XML test results
└── ansible-<playbook>-<timestamp>/ # Ansible playbook artifacts
```

## Advanced Configuration

### Custom Test Variables

Create a local variables file:

```yaml
# vars/user_vars.yml (gitignored)
cluster_name_prefix: "mytest"
aws_region: "us-west-2"
rosa_version: "4.21"
machine_pool_replicas: 3
instance_type: "m5.xlarge"
enable_fips: true
deletion_timeout: 3600  # 60 minutes for slower deletions
```

Use with test runner:
```bash
./run-test-suite.py 20-rosa-hcp-provision --extra-vars @vars/user_vars.yml
```

### Version-Specific Features

The framework supports version-specific configurations through the `templates/versions/` directory:

```
templates/versions/
├── 4.18/
│   └── control-plane.yaml.j2
├── 4.19/
│   └── control-plane.yaml.j2
└── 4.21/
    └── control-plane-fips.yaml.j2  # FIPS support for 4.21+
```

### Parallel Test Execution

Run multiple test instances in parallel with different cluster names:

```bash
# Terminal 1
./run-test-suite.py 20-rosa-hcp-provision -e name_prefix="test1"

# Terminal 2
./run-test-suite.py 20-rosa-hcp-provision -e name_prefix="test2"

# Terminal 3
./run-test-suite.py 20-rosa-hcp-provision -e name_prefix="test3"
```

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch from `main`
3. Add tests for new functionality
4. Ensure all existing tests pass
5. Update documentation as needed
6. Submit a pull request to `stolostron/rosa-hcp-e2e-test`

### Adding New Test Suites

1. Create a JSON file in `test-suites/`:

```json
{
  "name": "60-my-new-test",
  "description": "Description of the new test",
  "environment_variables": {
    "required": ["OCP_HUB_API_URL"],
    "optional": ["CUSTOM_VAR"]
  },
  "tasks": [
    {
      "name": "My test task",
      "playbook": "playbooks/my_new_playbook.yml",
      "extra_vars": {}
    }
  ]
}
```

2. Create corresponding Ansible playbook in `playbooks/`
3. Add reusable tasks to `tasks/` directory
4. Update this README with the new test suite
5. Add to `Jenkinsfile` if needed for CI/CD

### Code Quality

- Use `ansible-lint` for playbook linting
- Follow Ansible best practices
- Add comments for complex logic
- Use meaningful variable names
- Keep tasks idempotent

## Support

For issues, questions, and contributions:

- **Issues**: https://github.com/stolostron/rosa-hcp-e2e-test/issues
- **Pull Requests**: https://github.com/stolostron/rosa-hcp-e2e-test/pulls
- **Slack**: Contact the MCE team

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## References

- [ROSA Documentation](https://docs.openshift.com/rosa/welcome/index.html)
- [ROSA HCP Architecture](https://docs.openshift.com/rosa/rosa_architecture/rosa-understanding.html)
- [Cluster API Documentation](https://cluster-api.sigs.k8s.io/)
- [CAPA Provider Documentation](https://cluster-api-aws.sigs.k8s.io/)
- [MCE Documentation](https://access.redhat.com/documentation/en-us/red_hat_advanced_cluster_management_for_kubernetes/2.11/html/multicluster_engine/index)
- [OpenShift 4.21 Release Notes](https://docs.openshift.com/container-platform/4.21/release_notes/ocp-4-21-release-notes.html)
