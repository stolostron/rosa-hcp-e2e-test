# ROSA HCP Provisioning Feature Coverage

## OCM-22529: CAPI/CAPA Testing with OCP 4.22

### Currently Automated (always-on in provisioning workflow)

| Feature | How It's Configured | Default |
|---------|-------------------|---------|
| ROSANetwork (VPC/subnets) | `create_rosa_network=true` | Auto-creates VPC via CloudFormation |
| ROSARoleConfig (IAM roles) | `create_rosa_role_config=true` | Auto-creates installer, support, worker, operator roles |
| STS | Implicit (roles are STS-based) | Always on |
| Availability Zones | `availability_zone_count` | 2 |
| Additional Tags | Hardcoded in template | env, purpose, automated, network-automation, role-automation |
| DomainPrefix | Derived from `name_prefix` | `{prefix}` (max 15 chars) |
| Default MachinePool Autoscaling | `machine_pool.min_replicas` / `max_replicas` | 2 / 2 |
| Channel Group | `channel_group` | stable |

### Conditionally Supported (via `-e` extra vars)

| Feature | Variable | Notes |
|---------|----------|-------|
| Log Forwarding (CloudWatch) | `log_forward_enabled=true` + `log_forward_cloudwatch_role_arn` + `log_forward_cloudwatch_log_group` | In 4.20+ templates |
| Log Forwarding (S3) | `log_forward_enabled=true` + `log_forward_s3_bucket` + `log_forward_s3_prefix` | In 4.20+ templates |
| FIPS | `--feature fips` | 4.21+ templates |
| Channel Override | `--feature channel -e channel_group=fast` | 4.21+ templates |

### Now Automated via `--feature` Flag (OCM-22529)

| Feature | CLI Flag | Status |
|---------|----------|--------|
| No CNI Plugin | `--feature no-cni` | `networkType: Other` in rosa-controlplane-only templates |
| External OIDC | `--feature external-oidc` | `enableExternalAuthProviders: true` |
| ETCD KMS Key | `--feature etcd-kms -e etcd_encryption_kms_arn=arn:...` | `etcdEncryptionKMSARN` |
| Proxy Enabled | `--feature proxy -e http_proxy_url=...` | `proxy` block |
| FIPS | `--feature fips` (4.21+, requires etcd-kms) | `fips: "Enabled"` |
| Additional Tags | `--feature tags -e additional_tags='{key: val}'` | `additionalTags` |
| Additional Security Groups | `--feature security-groups -e additional_security_groups='[sg-xxx]'` | `additionalSecurityGroups` |
| Cluster Autoscaler Expanders | `--feature autoscaler` | `autoscaler.expanders` |
| Image Registry Config | `--feature image-registry` | `clusterRegistryConfig` |
| Machine Pool Disk Volume Size | `--feature disk-size` (default 300 GiB) | `rootVolume.size` |
| Parallel Node Upgrade | `--feature parallel-upgrade` | `updateConfig.rollingUpdate` |
| User Agent for ROSA CAPA | `--feature user-agent -e user_agent=my-agent` | `userAgent` |
| Domain Prefix / Long Name | `--feature domain -e domain_prefix=my-long-prefix` | `domainPrefix` |
| Audit Log Forwarding | `--feature log-forwarding -e log_forward_cloudwatch_role_arn=...` | `cloudWatchlogForwarder` |
| Availability Zones | `--feature azs -e availability_zone_count=3` | AZ list built in provisioning task |

### NOT Yet Automated (Remaining Gaps)

| Feature | Priority | Notes |
|---------|----------|-------|
| Private Cluster | P1 | Requires private-only subnets in ROSANetwork (not yet implemented) |
| BYON (Bring Your Own Network) | P1 | Requires template changes to skip ROSANetwork and accept manual subnets |
| Identity Provider | P1 | No template conditional exists |
| Default MachinePool Auto Scaling | P1 | Template uses `machine_pool.min/max_replicas`, not settable via flat extra var |
| Machine Pool Auto Scaling Enabled | P1 | Same — uses nested `machine_pool.*` vars |
| STS | P1 | Always on (implicit via ROSARoleConfig) |

### Existing 4.19 Feature Fixtures (static YAML, not wired into provisioning)

These exist under `templates/versions/4.19/features/` but are standalone test manifests with hardcoded `REPLACE_ME` values. They are NOT used by the automated provisioning flow:

- `rcp-private.yaml` — Private cluster with `endpointAccess: Private`
- `rcp-no-cni.yaml` — No CNI with `networkType: Other`
- `rcp-external-oidc.yaml` — External OIDC (also includes image registry config)
- `rcp-image-registry-config.yaml` — Image registry `clusterRegistryConfig`
- `rcp-machine-pool-disk-size.yaml` — Custom disk volume size
- `rcp-parallel-node-upgrade.yaml` — Rolling update with `maxSurge`/`maxUnavailable`
- `rcp-enable-cluster-autoscaler-expander.yaml` — Autoscaler with expander
- `rcp-enable-cluster-autoscaler-without-expander.yaml` — Autoscaler without expander
- `rcp-external-auth.yaml` — External auth providers
- `rcp-multi-test.yaml` — Multi-configuration test

### Template Versions Available

| Version | Cluster Config | Combined Automation | Network Config | Role Config |
|---------|---------------|-------------------|---------------|-------------|
| 4.18 | Yes | No | No | No |
| 4.19 | Yes | No | Yes | Yes |
| 4.20 | Yes | Yes | Yes | Yes |
| 4.21 | No | Yes | No | No |
| 4.22 | **Needed** | **Needed** | **Needed** | **Needed** |

### Plan to Close Gaps

Add `--feature` CLI flag to `run-test-suite.py` backed by a declarative feature registry (`templates/schemas/feature-registry.yml`). Each feature maps to conditional Jinja2 blocks in `rosa-controlplane-only.yaml.j2` templates (4.20, 4.21, 4.22).

Usage:
```bash
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni --feature external-oidc --feature autoscaler
./run-test-suite.py --list-features
./run-test-suite.py --list-features --ocp-version 4.22
```

Jenkins:
```
CLUSTER_FEATURES=private,no-cni,external-oidc
```
