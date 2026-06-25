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

### Default network CIDRs

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni
```

### Custom network CIDRs

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature no-cni \
  -e '{"cluster_network": {"machine_cidr": "10.1.0.0/16", "pod_cidr": "10.200.0.0/14", "service_cidr": "172.31.0.0/16"}}'
```

## Template Rendering

When `no_cni` is `true`, the template renders:

```yaml
spec:
  network:
    machineCIDR: {{ cluster_network.machine_cidr | default('10.0.0.0/16') }}
    networkType: Other
    podCIDR: {{ cluster_network.pod_cidr | default('10.128.0.0/14') }}
    serviceCIDR: {{ cluster_network.service_cidr | default('172.30.0.0/16') }}
```

The network CIDRs are configurable via `cluster_network.*` variables.
Without `--feature no-cni`, the `networkType` line is omitted entirely
(defaults to OpenShift SDN/OVN).

## Verification

Uses OCM API to verify no-cni configuration:

GET /api/clusters_mgmt/v1/clusters/{id}

Asserts:
- `.network.type == 'Other'`
- Falls back to ROSAControlPlane K8s spec if OCM is unavailable

## Related

- [Automated Feature Verification](automated-feature-verification.md)
