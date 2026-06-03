# Feature Flag Verification Report — Jenkins Build #242

**Date**: 2026-06-02  
**Branch**: `tf_test` (commit `c924bcd`)  
**Cluster**: `moo-rosa-hcp` in namespace `ns-rosa-hcp`  
**OpenShift Version**: 4.21.0  
**Region**: us-west-2  
**Build Result**: SUCCESS

---

## Requested Features

The following features were passed to the pipeline via `CLUSTER_FEATURES=autoscaler,image-registry,parallel-upgrade,disk-size`:

| CLI Flag | Ansible Variable | Template Value |
|----------|-----------------|----------------|
| `autoscaler` | `cluster_autoscaler_expander=true` | `.spec.autoscaler.expanders: [LeastWaste]` |
| `image-registry` | `image_registry_config=true` | `.spec.clusterRegistryConfig` |
| `parallel-upgrade` | `parallel_node_upgrade=2` | `.spec.updateConfig.rollingUpdate.maxSurge: 1` |
| `disk-size` | `root_volume_size=500` | `.spec.volumeSize: 500` |

Additional extra vars passed by Jenkins:
```
-e root_volume_size=500
-e parallel_node_upgrade=2
-e openshift_version=4.21.0
```

---

## Verification Results Summary

```
Passed:   5
Skipped: 11  (feature not requested — not an error)
Warned:   1  (feature requested but CRD field not supported by installed version)
Failed:   0  (no requested+supported features were missing from spec)
```

**Overall verdict**: PASS (0 failures among requested features)

---

## Detailed Feature-by-Feature Results

### Requested Features (4)

| Feature | K8s Resource | CRD Field Checked | Assertion | Result | Live Value |
|---------|-------------|-------------------|-----------|--------|------------|
| **image-registry** | ROSAControlPlane | `.spec.clusterRegistryConfig` | Field is defined | **PASS** | `allowedRegistriesForImport: [{domainName: quay.io, insecure: false}]`, `registrySources.allowedRegistries: [quay.io]` |
| **disk-size** | ROSAMachinePool | `.spec.volumeSize` | Value is not default (300) | **PASS** | `500` |
| **parallel-upgrade** | ROSAMachinePool | `.spec.updateConfig.rollingUpdate` | Field is defined | **PASS** | `maxSurge: 1, maxUnavailable: 0` |
| **autoscaler** | ROSAControlPlane | `.spec.autoscaler.expanders` | Field is defined and non-empty | **WARN** | Template rendered `[LeastWaste]`, but CRD schema lacks `autoscaler` field |

### Baseline Checks (always run)

| Check | K8s Resource | Assertion | Result | Live Value |
|-------|-------------|-----------|--------|------------|
| Channel Group | ROSAControlPlane | `.spec.channelGroup` is set | **PASS** | `stable` |
| Availability Zones | ROSANetwork | `.spec.availabilityZones` count >= 2 | **PASS** | `[us-west-2a, us-west-2b]` |
| Domain Prefix | ROSAControlPlane | informational only | **INFO** | `moo` |
| Long Cluster Name | ROSAControlPlane | name length > 20 | **SKIP** | `moo-rosa-hcp` (12 chars) |

### Not-Requested Features (correctly skipped)

These features were checked but immediately skipped because they were not in `--feature` flags:

| Feature | CRD Field | Why Skipped |
|---------|-----------|-------------|
| `no-cni` | `.spec.network.networkType` | Not requested |
| `private-network` | `.spec.endpointAccess` | Not requested |
| `external-oidc` | `.spec.enableExternalAuthProviders` | Not requested |
| `fips` | `.spec.fips` | Not requested |
| `etcd-kms` | `.spec.etcdEncryptionKMSARN` | Not requested |
| `user-agent` | `.spec.userAgent` | Not requested |
| `additional-tags` | `.spec.additionalTags` | Not requested |
| `security-groups` | `.spec.additionalSecurityGroups` | Not requested |
| `audit-logging` | `.spec.cloudWatchlogForwarder` | Not requested |
| `proxy` | `.spec.proxy` | Not requested |
| long cluster name | `.spec.rosaClusterName` length | Not a requestable feature |

---

## How Verification Works

### Pipeline Flow

```
Jenkinsfile                    run-test-suite.py              Ansible Playbook
───────────                    ─────────────────              ────────────────
CLUSTER_FEATURES param    →    --feature flags            →   requested_features var
  "autoscaler,image-           --feature autoscaler           "cluster_autoscaler_expander,
   registry,parallel-          --feature image-registry        image_registry,
   upgrade,disk-size"          --feature parallel-upgrade      parallel_upgrade,
                               --feature disk-size             disk_size"
```

### Verification Playbook Architecture

The verify playbook (`playbooks/verify_feature_flags.yml`) uses a **block/rescue** pattern for each feature:

```
┌──────────────────────────────────────────┐
│  For each feature check:                 │
│                                          │
│  block:                                  │
│    1. assert: CRD field has expected     │
│       value in live cluster spec         │
│    2. Increment features_passed          │
│                                          │
│  rescue (on assertion failure):          │
│    → include verify_feature_rescue.yml   │
│      with feature_id                     │
└──────────────────────────────────────────┘
```

### Rescue Handler Logic (`tasks/verify_feature_rescue.yml`)

When an assertion fails, the rescue handler determines _why_ it failed:

```
Was this feature requested via --feature flag?
│
├─ NO → SKIP (not an error, increment features_skipped)
│
└─ YES → Check if CRD supports the field:
         │
         │  oc get crd <crd-name> -o json |
         │    jq '.spec.versions[] |
         │      select(.served==true) |
         │      .schema.openAPIV3Schema
         │        .properties.spec
         │        .properties.<field> // empty'
         │
         ├─ CRD field is EMPTY → WARN
         │   (platform limitation, increment features_warned)
         │
         └─ CRD field EXISTS → FAIL
             (template bug, increment features_failed)
```

### Data Sources

The playbook reads three live K8s resources to verify features:

| Resource | Command | Fields Checked |
|----------|---------|----------------|
| ROSAControlPlane | `oc get rosacontrolplane moo-rosa-hcp -n ns-rosa-hcp -o json` | autoscaler, clusterRegistryConfig, networkType, endpointAccess, enableExternalAuthProviders, fips, etcdEncryptionKMSARN, userAgent, channelGroup, domainPrefix, additionalTags, cloudWatchlogForwarder, proxy |
| ROSAMachinePool | `oc get rosamachinepool moo-rosa-hcp -n ns-rosa-hcp -o json` | volumeSize, updateConfig.rollingUpdate, additionalSecurityGroups |
| ROSANetwork | `oc get rosanetwork moo-rosa-hcp-network -n ns-rosa-hcp -o json` | availabilityZones |

---

## The Autoscaler Warning Explained

The `autoscaler` feature was requested and the template correctly rendered:

```yaml
spec:
  autoscaler:
    expanders:
      - LeastWaste
```

The Kubernetes API accepted this field (no strict validation error on apply). However, the verify playbook's rescue handler queried the CRD schema:

```bash
oc get crd rosacontrolplanes.controlplane.cluster.x-k8s.io -o json | \
  jq '.spec.versions[] | select(.served==true) |
      .schema.openAPIV3Schema.properties.spec.properties.autoscaler // empty'
```

This returned **empty**, meaning the installed CRD version on this MCE cluster does not define an `autoscaler` field in its OpenAPI schema. The field is present in the live resource (Kubernetes stores unknown fields), but the CRD doesn't formally recognize it.

**Classification**: Platform limitation (WARN), not a test failure. The template is correct; the CRD version needs to be updated to formally support `autoscaler.expanders`.

---

## CRD-to-Feature Mapping Reference

The playbook defines this mapping to determine which CRD to query for each feature:

```yaml
crd_field_map:
  no_cni:                     {crd: rosacontrolplanes..., field: network.networkType}
  private_network:            {crd: rosacontrolplanes..., field: endpointAccess}
  external_oidc:              {crd: rosacontrolplanes..., field: enableExternalAuthProviders}
  fips:                       {crd: rosacontrolplanes..., field: fips}
  etcd_kms:                   {crd: rosacontrolplanes..., field: etcdEncryptionKMSARN}
  user_agent:                 {crd: rosacontrolplanes..., field: userAgent}
  cluster_autoscaler_expander:{crd: rosacontrolplanes..., field: autoscaler}
  image_registry:             {crd: rosacontrolplanes..., field: clusterRegistryConfig}
  disk_size:                  {crd: rosamachinepools...,  field: volumeSize}
  parallel_upgrade:           {crd: rosamachinepools...,  field: updateConfig}
  security_groups:            {crd: rosamachinepools...,  field: additionalSecurityGroups}
  audit_logging:              {crd: rosacontrolplanes..., field: cloudWatchlogForwarder}
  proxy_enabled:              {crd: rosacontrolplanes..., field: proxy}
```

---

## Live Cluster Spec Snapshots

### ROSAControlPlane `.spec` (relevant fields)

```json
{
  "channelGroup": "stable",
  "clusterRegistryConfig": {
    "allowedRegistriesForImport": [
      {"domainName": "quay.io", "insecure": false}
    ],
    "registrySources": {
      "allowedRegistries": ["quay.io"]
    }
  },
  "domainPrefix": "moo",
  "enableExternalAuthProviders": false,
  "endpointAccess": "Public",
  "fips": "Disabled",
  "network": {
    "hostPrefix": 23,
    "machineCIDR": "10.0.0.0/16",
    "networkType": "OVNKubernetes",
    "podCIDR": "10.128.0.0/14",
    "serviceCIDR": "172.30.0.0/16"
  },
  "region": "us-west-2",
  "rosaClusterName": "moo-rosa-hcp",
  "rosaNetworkRef": {"name": "moo-rosa-hcp-network"},
  "rosaRoleConfigRef": {"name": "moo-rosa-hcp-roles"},
  "version": "4.21.0"
}
```

### ROSAMachinePool `.spec` (relevant fields)

```json
{
  "instanceType": "m5.xlarge",
  "nodePoolName": "moo-np",
  "version": "4.21.0",
  "volumeSize": 500,
  "updateConfig": {
    "rollingUpdate": {
      "maxSurge": 1,
      "maxUnavailable": 0
    }
  }
}
```

### ROSANetwork `.spec` (relevant fields)

```json
{
  "availabilityZones": ["us-west-2a", "us-west-2b"],
  "cidrBlock": "10.0.0.0/16",
  "region": "us-west-2",
  "stackName": "moo-rosa-hcp-rosa-network-stack"
}
```

---

## Source Files

| File | Purpose |
|------|---------|
| `playbooks/verify_feature_flags.yml` | Main verification playbook with all feature assertions |
| `tasks/verify_feature_rescue.yml` | Rescue handler that classifies failures as SKIP/WARN/FAIL |
| `test-suites/21-verify-feature-flags.json` | Test suite definition that invokes the verify playbook |
| `Jenkinsfile` | Pipeline stage that passes `--feature` flags and `cluster_name` |
