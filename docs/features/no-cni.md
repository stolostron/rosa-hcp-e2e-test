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
| Feature Group | `day1-networking` |
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

Uses OCM API with CRD fallback, plus direct cluster pod inspection:

```text
GET /api/clusters_mgmt/v1/clusters/{id}
```

Asserts:
- OCM: `.network.type == 'Other'`
- CRD fallback: `.spec.network.networkType == 'Other'`
- No OVN-Kubernetes pods running on the provisioned cluster (`openshift-ovn-kubernetes` namespace is empty)
- If `cni_provider` is set (e.g., `cilium`), verifies custom CNI pods are running in that namespace

## Post-Provision CNI Installation (Experimental)

After provisioning with `--feature no-cni`, the cluster has no networking.
An experimental Cilium install task is available at `tasks/install_cni_cilium.yml`.
Include it in your playbook:

```yaml
- name: Install Cilium CNI
  include_tasks: tasks/install_cni_cilium.yml
  when: cni_provider is defined and cni_provider == 'cilium'
```

Run with:

```bash
ansible-playbook your-playbook.yml \
  -e cluster_name=<name> -e cni_provider=cilium -e cilium_version=1.16.5
```

This installs Cilium via Helm with OpenShift-compatible settings using
`helm upgrade --install --atomic`. **Status: experimental** — not validated
against live ROSA HCP clusters. Cilium compatibility may vary by version.

Required variables:
- `cni_provider`: Must be `cilium`
- `cilium_version`: Helm chart version (required, no default)

Optional variables:
- `cilium_namespace`: Install namespace (default: `cilium`)

## Test Coverage

| Test | File | Description |
|------|------|-------------|
| `test_no_cni_renders_network_type_other` | `tests/test_feature_manager.py` | `networkType: Other` rendered when `no_cni: true` (3 templates) |
| `test_no_cni_false_omits_network_type` | `tests/test_feature_manager.py` | `networkType` absent when `no_cni: false` (3 templates) |
| `test_default_omits_network_type` | `tests/test_feature_manager.py` | `networkType` absent when `no_cni` not set (3 templates) |
| `test_no_cni_feature_metadata` | `tests/test_feature_manager.py` | Registry entry: resource, k8s_field, min_version |
| `test_no_cni_var_mapping` | `tests/test_feature_manager.py` | `no_cni` in resolved extra vars |
| `test_no_cni_alias` | `tests/test_feature_manager.py` | CLI alias `no-cni` resolves to `no_cni` |
| `test_no_cni_rejected_on_418` | `tests/test_feature_manager.py` | Version gate rejects 4.18 |
| `test_no_cni_valid_on_419` | `tests/test_feature_manager.py` | Version gate accepts 4.19+ |

## Related

- [Automated Feature Verification](automated-feature-verification.md)
