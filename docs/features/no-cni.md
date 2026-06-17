# 4.22 Feature Testing: No CNI Plugin

| Field | Value |
|-------|-------|
| Feature ID | `no_cni` |
| CLI Flag | `--feature no-cni` |
| Category | Networking |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.network.networkType` |
| Min Version | 4.19 |
| Ansible Variable | `no_cni` |

## Description

Deploys the ROSA HCP cluster without a default CNI plugin (BYO CNI).
When enabled, the ROSAControlPlane sets `network.networkType: Other`, allowing
the customer to install their own CNI (e.g., Cilium, Calico).

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni
```

## Template Rendering

When `no_cni` is `true`, the template renders:

```yaml
spec:
  network:
    machineCIDR: 10.0.0.0/16
    networkType: Other
    podCIDR: 10.128.0.0/14
    serviceCIDR: 172.30.0.0/16
```

Without `--feature no-cni`, the `networkType` line is omitted entirely
(defaults to OpenShift SDN/OVN).

## Verification

Asserts `rcp.spec.network.networkType == 'Other'`.

If the feature was requested but the CRD does not have the `networkType`
field, the check reports WARN (CRD limitation) instead of FAIL.

## Related

- [Automated Feature Verification](automated-feature-verification.md)
