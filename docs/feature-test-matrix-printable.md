# ROSA HCP CAPA Feature Test Matrix

| # | Feature | Test Method | Status | CLI Flag | Ansible Var | Extra Vars | Verify Check |
|:--|:--------|:------------|:-------|:---------|:------------|:-----------|:-------------|
| 1 | Private | Manually | Done | `private` | `private=true` | — | `endpointAccess == 'Private'` |
| 2 | BYON | Manually | Needs template | not yet | `byon_vpc=true` | `vpc_id`, `subnet_ids` | — |
| 3 | Proxy | N/A | N/A | — | — | — | — |
| 4 | STS Mode | Automatically | Done | — | — | — (always on) | — |
| 5 | Default MP Autoscaling | Automatically | Done | `autoscaling` | `default_autoscaling=true` | `-e mp_min_replicas=N -e mp_max_replicas=N` | `minReplicas/maxReplicas` match |
| 6 | MP Autoscaling | Automatically | Needs template | not yet | — | `mp_min_replicas`, `mp_max_replicas` | — |
| 7 | Audit Log Forwarding | Manually | Done | `audit-logging` | `log_forward_enabled=true` | `log_forward_cloudwatch_role_arn=arn:...` | `cloudWatchlogForwarder` defined |
| 8 | Long Cluster Name | Automatically | Done | — | — | `name_prefix=<21+ chars>` | `rosaClusterName > 20 chars` |
| 9 | No CNI Plugin | Manually | Done | `no-cni` | `no_cni=true` | — | `networkType == 'Other'` |
| 10 | Additional Tags | Automatically | Done | `tags` | `additional_tags` | — (default: Team=PICS) | 5 defaults + Team=PICS, Jira=RHACM4K-61815 |
| 11 | ETCD KMS key | Manually | Done | `etcd-kms` | `etcd_encryption_kms_arn` | `etcd_encryption_kms_arn=arn:aws:kms:...` | `etcdEncryptionKMSARN` set |
| 12 | Security Groups | Manually | Done | `security-groups` | `additional_security_groups` | `additional_security_groups='["sg-xxx"]'` | `additionalSecurityGroups` set |
| 13 | Availability Zones | Automatically | Done | `azs` | `availability_zone_count` | — (default: 2) | count >= 2 + AZ names match region |
| 14 | Identity Provider | Manually | Needs everything | not yet | — | `idp_type` (TBD) | — |
| 15 | External OIDC | Manually | Done | `external-oidc` | `external_oidc=true` | — | `enableExternalAuthProviders == true` |
| 16 | Domain Prefix | Automatically | Done | `domain` | `domain_prefix` | — (from name_prefix) | value matches expected prefix |
| 17 | Parallel Upgrade | Manually | Done | `parallel-upgrade` | `parallel_node_upgrade` | `parallel_node_upgrade=2` | `updateConfig.rollingUpdate` defined |
| 18 | Autoscaler Expanders | Manually | Done | `autoscaler` | `cluster_autoscaler_expander=true` | — | `autoscaler.expanders` set |
| 19 | User Agent | Manually | Done | `user-agent` | `user_agent` | — (default: capa-e2e-test) | `userAgent` set |
| 20 | Image Registry | Manually | Done | `image-registry` | `image_registry_config=true` | — | `clusterRegistryConfig` defined |
| 21 | Disk Volume Size | Manually | Done | `disk-size` | `root_volume_size` | `root_volume_size=500` | `volumeSize != 300` |
| 22 | FIPS Mode | Manually | Done | `fips` | `fips=true` | — (auto-adds etcd-kms) | `fips == 'Enabled'` |
| 23 | Channel Group | Manually | Done | `channel-group` | `channel_group` | — (default: stable) | `channelGroup` set |

## Feature Groups

| Group | CLI | Features |
|:------|:----|:---------|
| `day1-basic` | `--feature-group day1-basic` | `domain_prefix`, `availability_zones`, `additional_tags`, `channel_group`, `default_autoscaling` |
| `day1-combo` | `--feature-group day1-combo` | `cluster_autoscaler_expander`, `image_registry`, `parallel_upgrade`, `disk_size` |
| `day1-security` | `--feature-group day1-security` | `etcd_kms`, `fips` |
| `day1-networking` | `--feature-group day1-networking` | `external_oidc`, `audit_logging` |
