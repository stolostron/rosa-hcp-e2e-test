# Add ROSAMachinePool

| Field | Value |
|---|---|
| **Suite ID** | `27-rosa-hcp-add-machinepool` |
| **Tags** | `rosa`, `hcp`, `machinepool`, `add`, `full` |
| **Playbooks** | 1 |

## Overview

This test suite adds a new machine pool to an existing ROSA HCP cluster. It creates both the CAPI MachinePool and the ROSAMachinePool infrastructure resource, then waits for the pool to become ready.

## Prerequisites

- An existing ROSA HCP cluster in ready state
- MCE/ACM hub cluster with CAPI/CAPA configured
- OpenShift cluster login credentials configured

## Quick start

```bash
./run-test-suite.py 27-rosa-hcp-add-machinepool -e cluster_name=my-cluster -e pool_name=my-pool
```

Adds a machine pool with default settings (m5.xlarge, 1 replica)

## Customization

- **`cluster_name`:** Name of the cluster to add the pool to (required)
- **`pool_name`:** Name for the new machine pool, max 15 chars (required)
- **`instance_type`:** AWS instance type (default: m5.xlarge)
- **`replicas`:** Number of worker replicas (default: 1)
- **`availability_zone`:** AWS availability zone (optional, auto-assigned if omitted)

## Expected results

- MachinePool resource created in the cluster namespace
- ROSAMachinePool resource created with matching infrastructure reference
- ROSA provisions new worker nodes in AWS
- Pool becomes ready with requested number of replicas (max wait: 30 minutes)

## Monitoring

```bash
oc get rosamachinepool <pool-name> -n ns-rosa-hcp
oc get machinepool <pool-name> -n ns-rosa-hcp
oc describe rosamachinepool <pool-name> -n ns-rosa-hcp
```
