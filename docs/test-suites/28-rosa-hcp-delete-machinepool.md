# Delete ROSAMachinePool

| Field | Value |
|---|---|
| **Suite ID** | `28-rosa-hcp-delete-machinepool` |
| **Tags** | `rosa`, `hcp`, `machinepool`, `delete`, `full` |
| **Playbooks** | 1 |

## Overview

This test suite deletes a machine pool from an existing ROSA HCP cluster. It removes both the CAPI MachinePool and the ROSAMachinePool infrastructure resource, then waits for the resources to be fully cleaned up.

## Prerequisites

- An existing ROSA HCP cluster with the target machine pool
- MCE/ACM hub cluster with CAPI/CAPA configured
- OpenShift cluster login credentials configured

## Quick start

```bash
./run-test-suite.py 28-rosa-hcp-delete-machinepool -e cluster_name=my-cluster -e pool_name=my-pool
```

Deletes the specified machine pool and waits for cleanup

## Customization

- **`cluster_name`:** Name of the cluster (required)
- **`pool_name`:** Name of the machine pool to delete (required)

## Expected results

- MachinePool resource deleted
- ROSAMachinePool resource deleted
- ROSA decommissions worker nodes in AWS
- Resources fully removed from the namespace (max wait: 15 minutes)

## Monitoring

```bash
oc get rosamachinepool -n ns-rosa-hcp
oc get machinepool -n ns-rosa-hcp
oc describe rosamachinepool <pool-name> -n ns-rosa-hcp
```
