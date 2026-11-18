# Upgrade ROSA HCP Control Plane

| Field | Value |
|---|---|
| **Suite ID** | `25-rosa-hcp-upgrade-control-plane` |
| **Tags** | `rosa`, `hcp`, `upgrade`, `control-plane`, `full` |
| **Playbooks** | 1 |

## Overview

This test suite upgrades a ROSA HCP cluster's control plane version. It auto-detects the next available upgrade version, patches the ROSAControlPlane resource, and waits for the upgrade to complete.

## Prerequisites

- An existing ROSA HCP cluster in ready state
- MCE/ACM hub cluster with CAPI/CAPA configured
- OpenShift cluster login credentials configured
- Available upgrade versions (check .status.availableUpgrades)

## Quick start

```bash
./run-test-suite.py 25-rosa-hcp-upgrade-control-plane -e cluster_name=my-cluster
```

Upgrades the control plane to the first available version automatically

## Customization

- **`cluster_name`:** Name of the cluster to upgrade (required)
- **`requested_version`:** Specific version to upgrade to (optional, defaults to first available)
- **`rosa_hcp_namespace`:** Namespace containing the ROSAControlPlane resource (default: ns-rosa-hcp)

## Expected results

- ROSAControlPlane spec.version patched to requested version
- Cluster begins upgrade process
- Playbook waits for ROSAControlPlane status.ready to become true
- Cluster fully upgraded and ready (max wait: 60 minutes)

## Monitoring

```bash
oc get rosacontrolplane <cluster-name> -n ns-rosa-hcp -w
oc describe rosacontrolplane <cluster-name> -n ns-rosa-hcp
oc get rosacontrolplane <cluster-name> -n ns-rosa-hcp -o jsonpath='{.status.availableUpgrades}'
```
