# Default Provisioning Configuration

When you run provisioning without any `--feature` flags, these are the defaults applied by the `20-rosa-hcp-provision` test suite.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=xyz
```

## Default Configuration

| Setting | Default Value | Source |
|---------|--------------|--------|
| OpenShift Version | 4.20.10 | Test suite JSON |
| AWS Region | us-west-2 | Test suite JSON |
| Channel Group | stable | Test suite JSON |
| Namespace | ns-rosa-hcp | Test suite JSON |
| VPC CIDR | 10.0.0.0/16 | Test suite JSON |
| Availability Zones | 2 | Test suite JSON |
| Endpoint Access | Public | Template default |
| Instance Type | m5.xlarge | Template default |
| Autoscaling | min 2 / max 2 | Template default |
| Cluster Name | `{name_prefix}-rosa-hcp` | Derived from `-e name_prefix=` |
| Domain Prefix | `{name_prefix}` | Derived from name_prefix |

## Automation Resources (always created)

| Resource | What It Does |
|----------|-------------|
| ROSARoleConfig | Creates AWS IAM roles (installer, support, worker, operator) via `create_rosa_role_config: true` |
| ROSANetwork | Creates VPC, public/private subnets, internet gateway, NAT gateways, route tables via CloudFormation (`create_rosa_network: true`) |
| STS | Always on (implicit via ROSARoleConfig) |

## Template Used

`templates/versions/4.20/features/rosa-controlplane-only.yaml.j2`

Produces 6 Kubernetes resources:
1. ManagedCluster (ACM integration)
2. Cluster (CAPI)
3. ROSACluster (infrastructure)
4. ROSAControlPlane (control plane spec with `rosaNetworkRef` and `rosaRoleConfigRef`)
5. MachinePool (CAPI worker pool)
6. ROSAMachinePool (ROSA worker nodes)

ROSANetwork and ROSARoleConfig are created separately in earlier provisioning steps, not in this template.

## What's NOT Configured by Default

These require `--feature` flags or `-e` overrides:

| Feature | How to Enable |
|---------|--------------|
| No CNI | `--feature no-cni` |
| External OIDC | `--feature external-oidc` |
| FIPS (4.21+) | `--feature fips` (auto-requires etcd-kms) |
| ETCD KMS Encryption | `--feature etcd-kms -e etcd_encryption_kms_arn=arn:...` |
| Proxy | `--feature proxy -e http_proxy_url=...` |
| Additional Tags | `--feature tags -e additional_tags='{key: val}'` |
| Additional Security Groups | `--feature security-groups -e additional_security_groups='[sg-xxx]'` |
| Cluster Autoscaler | `--feature autoscaler` |
| Image Registry Config | `--feature image-registry` |
| Disk Volume Size | `--feature disk-size -e root_volume_size=500` |
| Parallel Node Upgrade | `--feature parallel-upgrade` |
| User Agent | `--feature user-agent -e user_agent=my-agent` |
| Log Forwarding | `--feature log-forwarding -e log_forward_cloudwatch_role_arn=...` |
| Custom Channel | `--feature channel -e channel_group=fast` |
| Custom Domain | `--feature domain -e domain_prefix=my-prefix` |
| Custom AZ Count | `--feature azs -e availability_zone_count=3` |

## Overriding Defaults

Any default can be overridden with `-e`:

```bash
# Use a different version and region
./run-test-suite.py 20-rosa-hcp-provision \
  -e name_prefix=xyz \
  -e openshift_version=4.21.5 \
  -e aws_region=us-east-1

# Use 3 availability zones with a larger CIDR
./run-test-suite.py 20-rosa-hcp-provision \
  -e name_prefix=xyz \
  -e availability_zone_count=3 \
  -e vpc_cidr_block=172.16.0.0/16
```

See `docs/feature-flags.md` for the full `--feature` flag reference.
