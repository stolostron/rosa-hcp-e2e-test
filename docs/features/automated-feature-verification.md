# Automated Feature Verification

The verification playbook (`playbooks/verify_feature_flags.yml`) automatically
checks that requested features are correctly rendered on the cluster after
provisioning.

## Usage

```bash
./run-test-suite.py 21-rosa-hcp-verify --feature security-groups --feature fips
```

## How It Works

1. Reads the ROSAControlPlane and ROSAMachinePool specs from the hub cluster
2. Queries OCM API for cluster details (falls back to CRD checks if unavailable)
3. Verifies each requested feature against AWS resources, OCM API, or CRD spec
4. Reports PASS/FAIL/SKIP/WARN per feature with detailed diagnostics

## Verification Methods

| Method | Features |
|--------|----------|
| AWS CLI | private_network, fips, etcd_kms, additional_tags, disk_size, availability_zones, default_autoscaling, cluster_autoscaler_expander, audit_logging |
| OCM API | no_cni, external_oidc, image_registry, domain_prefix, channel_group, parallel_upgrade |
| CRD spec | user_agent, security_groups, proxy_enabled |

## Related

- [Feature Registry](../../templates/schemas/feature-registry.yml)
