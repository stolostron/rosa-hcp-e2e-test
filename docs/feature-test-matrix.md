# ROSA HCP Feature Test Matrix

## Automated Features (via `--feature` flag)

These features are fully wired: CLI flag, template conditional, and post-provision verification.

### ROSAControlPlane Features

| Feature | CLI Flag | Ansible Var | Extra Vars | Verify Check |
|---------|----------|-------------|------------|--------------|
| No CNI Plugin | `--feature no-cni` | `no_cni=true` | None | `networkType == 'Other'` |
| External OIDC | `--feature external-oidc` | `external_oidc=true` | None | `enableExternalAuthProviders == true` |
| ETCD KMS Encryption | `--feature etcd-kms` | `etcd_encryption_kms_arn` | `-e etcd_encryption_kms_arn=arn:aws:kms:...` | `etcdEncryptionKMSARN \| length > 0` |
| FIPS Mode | `--feature fips` | `fips=true` | None (auto-adds `etcd-kms` dep) | `fips == 'Enabled'` |
| Image Registry Config | `--feature image-registry` | `image_registry_config=true` | None | `clusterRegistryConfig is defined` |
| Cluster Autoscaler | `--feature autoscaler` | `cluster_autoscaler_expander=true` | None | `autoscaler.expanders \| length > 0` |
| User Agent | `--feature user-agent` | `user_agent` | None (ci_default: `capa-e2e-test`) | `userAgent \| length > 0` |
| Additional Tags | `--feature tags` | `additional_tags` | None (ci_default: `{Team: PICS}`) | `additionalTags.keys() \| length > 5` |
| Audit Log Forwarding | `--feature audit-logging` | `log_forward_enabled=true` | `-e log_forward_cloudwatch_role_arn=arn:...` | `cloudWatchlogForwarder is defined` |
| Channel Group | `--feature channel` | `channel_group` | None (default: `stable`) | `channelGroup \| length > 0` |
| Domain Prefix | `--feature domain` | `domain_prefix` | None (derived from `name_prefix`) | INFO only |

### ROSAMachinePool Features

| Feature | CLI Flag | Ansible Var | Extra Vars | Verify Check |
|---------|----------|-------------|------------|--------------|
| Disk Volume Size | `--feature disk-size` | `root_volume_size` | `-e root_volume_size=500` | `volumeSize \| int != 300` |
| Parallel Node Upgrade | `--feature parallel-upgrade` | `parallel_node_upgrade` | `-e parallel_node_upgrade=2` | `updateConfig.rollingUpdate is defined` |
| Additional Security Groups | `--feature security-groups` | `additional_security_groups` | `-e additional_security_groups='["sg-xxx"]'` | `additionalSecurityGroups \| length > 0` |

### ROSANetwork Features

| Feature | CLI Flag | Ansible Var | Extra Vars | Verify Check |
|---------|----------|-------------|------------|--------------|
| Availability Zones | `--feature azs` | `availability_zone_count` | None (default: `2`) | `availabilityZones \| length >= 2` |

---

## Automatic Features (always tested, no flag needed)

These are verified on every provision run without any `--feature` flag.

| Feature | How It's Set | Verify Check |
|---------|-------------|--------------|
| STS Mode | Always on (CAPA default) | None (implicit) |
| Default MP Auto Scaling | `machine_pool.min_replicas` / `max_replicas` in template | None |
| Long Cluster Name | `-e name_prefix=<long-name>` | `rosaClusterName \| length > 20` |

---

## Not Yet Automated

### Ready to Enable (template + verify exist, just needs `cli_features` unblock)

| Feature | Blocked By | Ansible Var | Extra Vars | Verify Check |
|---------|-----------|-------------|------------|--------------|
| **Private** | Not in `cli_features` list | `private=true` | None | `endpointAccess == 'Private'` |

### Needs Implementation

| Feature | What's Missing | Extra Vars Would Need |
|---------|---------------|----------------------|
| BYON (Bring Your Own Network) | Template: skip ROSANetwork, accept manual subnets | `-e vpc_id=... -e subnet_ids='[...]'` |
| Machine Pool Auto Scaling | Template: expose MP autoscaling as flat vars | `-e mp_min_replicas=1 -e mp_max_replicas=3` |
| Identity Provider | Template + verify: IDP configuration | `-e idp_type=htpasswd` (TBD) |

### Out of Scope

| Feature | Reason |
|---------|--------|
| Proxy | N/A per test matrix |

---

## Feature Groups (presets for `--feature-group`)

| Group | Features Included |
|-------|------------------|
| `day1-basic` | Default provisioning (STS, Tags, AZs, DomainPrefix, Autoscaling, Long Name) |
| `day1-combo` | `no-cni`, `autoscaler`, `image-registry`, `parallel-upgrade`, `disk-size`, `user-agent` |
| `day1-security` | `etcd-kms`, `fips` |
| `day1-networking` | `external-oidc`, `audit-logging` |

---

## Quick Reference

```bash
# List all available features
./run-test-suite.py --list-features

# Validate feature flags without running
./run-test-suite.py 20-rosa-hcp-provision --validate-only --feature no-cni --feature disk-size

# Provision with features
./run-test-suite.py 20-rosa-hcp-provision --feature autoscaler --feature image-registry \
  -e root_volume_size=500

# Verify features after provisioning
./run-test-suite.py 21-verify-feature-flags --feature autoscaler --feature image-registry \
  -e cluster_name=my-cluster

# Use a preset group
./run-test-suite.py 20-rosa-hcp-provision --feature-group day1-combo

# Check CRD support on live cluster
./scripts/check_crd_feature_support.sh
```
