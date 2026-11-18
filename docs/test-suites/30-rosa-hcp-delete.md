# CAPA Cluster Deletion

| Field | Value |
|---|---|
| **Suite ID** | `30-rosa-hcp-delete` |
| **Tags** | `rosa`, `hcp`, `deletion`, `cleanup`, `lifecycle`, `smoke`, `full` |
| **Playbooks** | 1 |

## Overview

This test suite deletes ROSA HCP clusters and their automation resources. It pairs with the 20-rosa-hcp-provision test suite for complete cluster lifecycle management.

## Prerequisites

- MCE/ACM hub cluster with CAPI/CAPA configured
- OpenShift cluster login credentials configured
- Existing ROSA HCP cluster created via 20-rosa-hcp-provision test suite

## Quick start

```bash
./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=qe6
```

Using name_prefix automatically derives cluster_name as '{prefix}-rosa-hcp' and deletes all related resources (network, roles) created during provisioning

## Usage examples

### Delete by name prefix

Delete cluster and all automation resources created with name_prefix=qe6

```bash
./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=qe6
```

### Delete by cluster name

Delete cluster by explicit name

```bash
./run-test-suite.py 30-rosa-hcp-delete -e cluster_name=my-test-cluster
```

### Delete without network

Delete cluster but keep ROSANetwork resources (VPC, subnets)

```bash
./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=qe6 -e delete_network=false
```

### Delete without roles

Delete cluster but keep ROSARoleConfig resources (IAM roles)

```bash
./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=qe6 -e delete_roles=false
```

### Delete without waiting

Initiate deletion without waiting for completion

```bash
./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=qe6 -e wait_for_deletion=false
```

## Customization

- **`name_prefix`:** Simple prefix to identify cluster (e.g., 'qe6'). Automatically derives cluster_name as '{prefix}-rosa-hcp'. RECOMMENDED for matching provisioning workflow.
- **`cluster_name`:** Name of the cluster to delete (auto-derived from name_prefix if provided, or specify explicitly)
- **`rosa_hcp_namespace`:** Namespace where cluster resources exist (default: ns-rosa-hcp)
- **`delete_network`:** Delete ROSANetwork resources (VPC, subnets) - true or false (default: true)
- **`delete_roles`:** Delete ROSARoleConfig resources (IAM roles, OIDC) - true or false (default: true)
- **`wait_for_deletion`:** Wait for resources to be fully deleted - true or false (default: true)
- **`deletion_timeout`:** Timeout in seconds for waiting (default: 3600 = 60 minutes)

## Deletion order

1. ROSAMachinePool - Delete worker node pools first
2. ROSAControlPlane - Delete control plane (triggers AWS cluster deletion)
3. ROSANetwork - Delete VPC and networking resources (if delete_network=true)
4. ROSARoleConfig - Delete IAM roles and OIDC provider (if delete_roles=true)
5. Core Cluster object - Delete orphaned CAPI cluster object (if exists)

## Expected results

- ROSAControlPlane deleted successfully
- ROSAMachinePool deleted (if it existed)
- ROSANetwork deleted (if enabled and existed)
- ROSARoleConfig deleted (if enabled and existed)
- All Kubernetes resources removed from namespace
- AWS resources cleaned up (cluster, VPC, IAM roles)

## Monitoring

```bash
oc get rosacontrolplane,rosamachinepool,rosanetwork,rosaroleconfig -n ns-rosa-hcp
oc describe rosacontrolplane <cluster-name> -n ns-rosa-hcp
oc get rosacontrolplane --all-namespaces -o wide
```

## Troubleshooting

### Stuck deletion

**Symptom:** Resources stuck in 'Deleting' state

**Check:**

```bash
oc get rosacontrolplane <name> -n ns-rosa-hcp -o yaml | grep finalizers
```

**Solution:** Check AWS Console for stuck CloudFormation stacks or IAM role deletion issues

### Orphaned resources

**Symptom:** Core Cluster object remains after ROSAControlPlane deletion

**Check:**

```bash
oc get cluster.cluster.x-k8s.io -n ns-rosa-hcp
```

**Solution:** The playbook automatically cleans up orphaned core Cluster objects

### Network deletion timeout

**Symptom:** ROSANetwork deletion takes longer than timeout

**Check:** AWS Console &gt; CloudFormation - check stack deletion progress

**Solution:** Increase deletion_timeout or set wait_for_deletion=false

### Role deletion timeout

**Symptom:** ROSARoleConfig deletion takes longer than timeout

**Check:** AWS Console &gt; IAM - check if roles are being used elsewhere

**Solution:** Ensure no other resources are using the IAM roles

## Lifecycle workflow

Complete ROSA HCP cluster lifecycle using test suites

### Steps

1. Configure: ./run-test-suite.py 10-configure-mce-environment
2. Provision: ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=qe6
3. Test: Run your cluster tests...
4. Delete: ./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=qe6

## Notes

- Always use the same name_prefix or cluster_name used during provisioning
- ROSANetwork deletion may take 5-10 minutes due to CloudFormation stack deletion
- ROSARoleConfig deletion may take 2-5 minutes for IAM role cleanup
- If delete_network=false, VPC and subnets remain and can be reused
- If delete_roles=false, IAM roles remain and can be reused
- The playbook safely handles cases where resources don't exist (idempotent)
