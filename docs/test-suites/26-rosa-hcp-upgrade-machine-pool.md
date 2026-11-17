# Upgrade ROSA HCP Machine Pool

| Field | Value |
|---|---|
| **Suite ID** | `26-rosa-hcp-upgrade-machine-pool` |
| **Tags** | `rosa`, `hcp`, `upgrade`, `machine-pool`, `full` |
| **Playbooks** | 1 |

## Overview

This test suite upgrades a ROSA HCP cluster's machine pool version. It auto-detects the pool name and next available upgrade version, patches the ROSAMachinePool resource, and waits for the upgrade to complete. The control plane must be upgraded first.

## Prerequisites

- An existing ROSA HCP cluster with machine pool in ready state
- Control plane already upgraded to the target version or higher
- MCE/ACM hub cluster with CAPI/CAPA configured
- OpenShift cluster login credentials configured
- Available upgrade versions (check .status.availableUpgrades)

## Quick start

```bash
./run-test-suite.py 26-rosa-hcp-upgrade-machine-pool -e cluster_name=my-cluster
```

Auto-discovers the machine pool and upgrades to the first available version

## Customization

- **`cluster_name`:** Name of the cluster (required)
- **`pool_name`:** Name of the ROSAMachinePool resource (optional, auto-discovered if omitted)
- **`requested_version`:** Specific version to upgrade to (optional, defaults to first available)
- **`rosa_hcp_namespace`:** Namespace containing the ROSAMachinePool resource (default: ns-rosa-hcp)

## Expected results

- ROSAMachinePool spec.version patched to requested version
- Worker nodes begin rolling upgrade
- Playbook waits for ROSAMachinePool status.ready to become true
- All replicas upgraded and ready (max wait: 60 minutes)

## Monitoring

```bash
oc get rosamachinepool <pool-name> -n ns-rosa-hcp -w
oc describe rosamachinepool <pool-name> -n ns-rosa-hcp
oc get rosamachinepool <pool-name> -n ns-rosa-hcp -o jsonpath='{.status.availableUpgrades}'
```
