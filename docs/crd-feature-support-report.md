# ROSA HCP CRD Feature Support Report

**Purpose:** Compare actual CRD field support across hub environments to identify which features templates can safely use.
**Script:** `./scripts/check_crd_feature_support.sh`

---

## Environment Comparison

### Hub Environments Tested

| Property | Env 1 (qe6) | Env 2 (qe1) |
|----------|-------------|-------------|
| **Hub URL** | api.qe6-vmware-ibm.install.dev09.red-chesterfield.com:6443 | api.qe1-vmware-ibm.dev09.red-chesterfield.com:6443 |
| **OCP Version** | 4.21.16 | 4.21.15 |
| **Kubernetes** | v1.34.7 | v1.34.6 |
| **Platform** | VSphere | VSphere |
| **ACM Version** | 2.17.0 | 2.16.2 |
| **MCE Version** | 2.17.0 | 2.11.2 |
| **CAPA Image** | `...@sha256:ab869a49...` | `...@sha256:a2814869...` |
| **CRD API Version** | v1beta2 | v1beta2 |
| **Date Checked** | 2026-05-28 | 2026-05-28 |

---

## ROSAControlPlane Feature Fields

| Feature | CRD Field | Template Field | Env 1 (qe6) | Env 2 (qe1) | Delta |
|---------|-----------|----------------|-------------|-------------|-------|
| image_registry | `.spec.clusterRegistryConfig` | `.spec.clusterRegistryConfig` | YES | YES | |
| no_cni | `.spec.network.networkType` | `.spec.network.networkType` | YES | YES | |
| external_oidc | `.spec.enableExternalAuthProviders` | `.spec.enableExternalAuthProviders` | YES | YES | |
| etcd_kms | `.spec.etcdEncryptionKMSARN` | `.spec.etcdEncryptionKMSARN` | YES | YES | |
| fips | `.spec.fips` | `.spec.fips` | YES | **NO** | **NEW in ACM 2.17** |
| audit_logging | `.spec.auditLogRoleARN` | `.spec.auditLogRoleARN` | YES | YES | |
| audit_logging (cloudwatch) | `.spec.cloudWatchlogForwarder` | `.spec.cloudWatchlogForwarder` | YES | YES | |
| additionalTags | `.spec.additionalTags` | `.spec.additionalTags` | YES | YES | |
| domainPrefix | `.spec.domainPrefix` | `.spec.domainPrefix` | YES | YES | |
| channelGroup | `.spec.channelGroup` | `.spec.channelGroup` | YES | YES | |
| private_network | `.spec.endpointAccess` | `.spec.endpointAccess` | YES | YES | |
| **autoscaler (expanders)** | — | `.spec.autoscaler.expanders` | **NO** | **NO** | Not in any CRD |
| **user_agent** | — | `.spec.userAgent` | **NO** | **NO** | Not in any CRD |
| **security_groups (on RCP)** | — | `.spec.additionalSecurityGroups` | **NO** | **NO** | Not in any CRD |
| **http_proxy** | — | `.spec.proxy` | **NO** | **NO** | Not in any CRD |

**Score:** Env 1: 11/15 | Env 2: 10/15

## ROSAMachinePool Feature Fields

| Feature | CRD Field | Template Field | Env 1 (qe6) | Env 2 (qe1) | Delta |
|---------|-----------|----------------|-------------|-------------|-------|
| disk_size | **`.spec.volumeSize`** | ~~`.spec.rootVolume.size`~~ | YES (wrong path) | YES (wrong path) | |
| parallel_upgrade | `.spec.updateConfig.rollingUpdate` | `.spec.updateConfig.rollingUpdate` | YES | YES | |
| security_groups | `.spec.additionalSecurityGroups` | `.spec.additionalSecurityGroups` | YES | YES | |
| availabilityZone | `.spec.availabilityZone` | `.spec.availabilityZone` | YES | YES | |
| instanceType | `.spec.instanceType` | `.spec.instanceType` | YES | YES | |
| nodePoolName | `.spec.nodePoolName` | `.spec.nodePoolName` | YES | YES | |

**Score:** Env 1: 7/9 | Env 2: 7/9

---

## Key Findings

### Fields that differ between environments

| Feature | ACM 2.16.2 / MCE 2.11.2 (qe1) | ACM 2.17.0 / MCE 2.17.0 (qe6) |
|---------|-------------------------------|-------------------------------|
| **fips** | NO | YES |
| **channel** | NO (missing from qe1 field list) | YES |

### Fields not yet in CRD (kept in templates for future CAPA releases)

| # | Field | Template Path | Status |
|---|-------|---------------|--------|
| 1 | `autoscaler.expanders` | `.spec.autoscaler.expanders` | Not in CRD — expected in future CAPA release |
| 2 | `userAgent` | `.spec.userAgent` | Not in CRD — expected in future CAPA release |
| 3 | `proxy` | `.spec.proxy` | Not in CRD — expected in future CAPA release |
| 4 | `additionalSecurityGroups` (on RCP) | `.spec.additionalSecurityGroups` | Only on ROSAMachinePool currently |

### Fixes applied

| # | Fix | Template | Detail |
|---|-----|----------|--------|
| 1 | `disk_size` field path corrected | 4.22 `rosa-controlplane-only.yaml.j2` | Changed `.spec.rootVolume.size` to `.spec.volumeSize` |
| 2 | New CRD fields added | 4.22 `rosa-controlplane-only.yaml.j2` | Added `billingAccount`, `versionGate`, `autoNode`, `channel` |

### Fixes still needed

| # | Fix | Template |
|---|-----|----------|
| 1 | `disk_size` field path still wrong | 4.21 `rosa-controlplane-only.yaml.j2` (uses `.spec.rootVolume.size`) |
| 2 | New CRD fields not yet added | 4.21 `rosa-controlplane-only.yaml.j2` (missing `billingAccount`, `versionGate`, `autoNode`, `channel`) |

---

## Full CRD Spec Fields (for reference)

### ROSAControlPlane `.spec` fields

**Env 1 (qe6 — ACM 2.17.0):**
```
additionalTags, auditLogRoleARN, autoNode, availabilityZones, billingAccount,
channel, channelGroup, cloudWatchlogForwarder, clusterRegistryConfig,
controlPlaneEndpoint, credentialsSecretRef, defaultMachinePoolSpec, domainPrefix,
enableExternalAuthProviders, endpointAccess, etcdEncryptionKMSARN,
externalAuthProviders, fips, identityRef, installerRoleARN, network, oidcID,
provisionShardID, region, rolesRef, rosaClusterName, rosaNetworkRef,
rosaRoleConfigRef, s3LogForwarder, subnets, supportRoleARN, version,
versionGate, workerRoleARN
```

**Env 2 (qe1 — ACM 2.16.2):**
```
additionalTags, auditLogRoleARN, autoNode, availabilityZones, billingAccount,
channelGroup, cloudWatchlogForwarder, clusterRegistryConfig,
controlPlaneEndpoint, credentialsSecretRef, defaultMachinePoolSpec, domainPrefix,
enableExternalAuthProviders, endpointAccess, etcdEncryptionKMSARN,
externalAuthProviders, identityRef, installerRoleARN, network, oidcID,
provisionShardID, region, rolesRef, rosaClusterName, rosaNetworkRef,
rosaRoleConfigRef, s3LogForwarder, subnets, supportRoleARN, version,
versionGate, workerRoleARN
```

### ROSAMachinePool `.spec` fields (same on both)
```
additionalSecurityGroups, additionalTags, autoRepair, autoscaling,
availabilityZone, capacityReservationID, imageType, instanceType, labels,
nodeDrainGracePeriod, nodePoolName, providerIDList, subnet, taints,
tuningConfigs, updateConfig, version, volumeSize
```

---

## How to Add Another Environment

1. Log in: `oc login <hub-url> -u kubeadmin -p <password>`
2. Run: `./scripts/check_crd_feature_support.sh`
3. Add a new column to the tables above with the results
4. For JSON: `./scripts/check_crd_feature_support.sh --json --label "env-name"`
