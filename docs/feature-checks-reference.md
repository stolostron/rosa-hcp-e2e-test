# Feature Checks Reference

All checks run against live K8s resources via `oc get -o json`. The playbook fetches three resources once, then asserts fields from the parsed JSON.

## Data Sources

| Variable | Command |
|----------|---------|
| `rcp` | `oc get rosacontrolplane <cluster> -n <ns> -o json` |
| `rmp` | `oc get rosamachinepool <cluster> -n <ns> -o json` |
| `rnet` | `oc get rosanetwork <cluster>-network -n <ns> -o json` |

## Feature Checks

| # | Feature ID | Resource | Assertion | Expected Value |
|---|-----------|----------|-----------|----------------|
| 1 | `no_cni` | ROSAControlPlane | `rcp.spec.network.networkType == 'Other'` | `Other` |
| 2 | `private_network` | ROSAControlPlane | `rcp.spec.endpointAccess == 'Private'` | `Private` |
| 3 | `external_oidc` | ROSAControlPlane | `rcp.spec.enableExternalAuthProviders \| bool` | `true` |
| 4 | `fips` | ROSAControlPlane | `rcp.spec.fips == 'Enabled'` | `Enabled` |
| 5 | `etcd_kms` | ROSAControlPlane | `rcp.spec.etcdEncryptionKMSARN \| length > 0` | any ARN string |
| 6 | `user_agent` | ROSAControlPlane | `rcp.spec.userAgent \| length > 0` | any non-empty string |
| 7 | `cluster_autoscaler_expander` | ROSAControlPlane | `rcp.spec.autoscaler.expanders \| length > 0` | non-empty list |
| 8 | `image_registry` | ROSAControlPlane | `rcp.spec.clusterRegistryConfig is defined` | field exists |
| 9 | `additional_tags` | ROSAControlPlane | `rcp.spec.additionalTags.keys() \| length > 5` | more than 5 tags |
| 10 | `channel_group` | ROSAControlPlane | `rcp.spec.channelGroup \| length > 0` | any non-empty string |
| 11 | `long_cluster_name` | ROSAControlPlane | `rcp.spec.rosaClusterName \| length > 20` | name > 20 chars |
| 12 | `disk_size` | ROSAMachinePool | `rmp.spec.volumeSize \| int != 300` | not default (300) |
| 13 | `parallel_upgrade` | ROSAMachinePool | `rmp.spec.updateConfig.rollingUpdate is defined` | field exists |
| 14 | `security_groups` | ROSAMachinePool | `rmp.spec.additionalSecurityGroups \| length > 0` | non-empty list |
| 15 | `availability_zones` | ROSANetwork | `rnet.spec.availabilityZones \| length >= 2` | 2+ AZs |
| 16 | `audit_logging` | ROSAControlPlane | `rcp.spec.cloudWatchlogForwarder is defined` | field exists |
| 17 | `proxy_enabled` | ROSAControlPlane | `rcp.spec.proxy is defined` | field exists |

## Informational Check (no pass/fail)

| Feature | Resource | Output |
|---------|----------|--------|
| `domain_prefix` | ROSAControlPlane | Prints `rcp.spec.domainPrefix` value |

## Result Categories

| Result | Meaning | Fails Build? |
|--------|---------|-------------|
| **PASS** | Assertion succeeded | No |
| **SKIP** | Feature not in `--feature` flags | No |
| **WARN** | Feature requested but CRD schema lacks the field | No |
| **FAIL** | Feature requested, CRD supports it, value missing from spec | Yes |

## Adding a New Feature Check

Add a `block/rescue` entry to `playbooks/verify_feature_flags.yml` and a CRD mapping to `crd_field_map`:

```yaml
# In vars section, add to crd_field_map:
my_feature: {crd: "rosacontrolplanes.controlplane.cluster.x-k8s.io", field: "myField"}

# In tasks section, add the check:
- name: "CHECK: My Feature"
  block:
    - name: Assert myField is set
      assert:
        that:
          - rcp.spec.myField is defined
        fail_msg: "FAIL: myField not set"
        success_msg: "PASS: myField configured"
    - set_fact:
        features_passed: "{{ features_passed | int + 1 }}"
  rescue:
    - include_tasks: "{{ playbook_dir }}/../tasks/verify_feature_rescue.yml"
      vars:
        feature_id: my_feature
        fail_detail: "myField is not set"
```

## Source

`playbooks/verify_feature_flags.yml`
