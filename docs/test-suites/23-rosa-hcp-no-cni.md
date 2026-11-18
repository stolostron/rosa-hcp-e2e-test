# CAPA No-CNI (BYO-CNI) Cluster Provisioning - OpenShift 5.0 RC

| Field | Value |
|---|---|
| **Suite ID** | `23-rosa-hcp-no-cni` |
| **Tags** | `rosa`, `hcp`, `provisioning`, `network-automation`, `role-automation`, `no-cni`, `byo-cni`, `5.0`, `features` |
| **Playbooks** | 1 |

## Overview

This test suite provisions a ROSA HCP No-CNI (BYO-CNI) cluster on the OpenShift 5.0 release candidate (5.0.0-ec.6, candidate channel) against the MCE 5.0 RC hub. It uses the 5.0 feature template rosa-no-cni-cluster, which derives from the 4.20 combined-automation template (full ROSANetwork + ROSARoleConfig automation, no hard-coded ARNs) and sets network.networkType: Other on the ROSAControlPlane.

## Prerequisites

- MCE 5.0 RC hub cluster with CAPI/CAPA configured
- AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) in vars/user_vars.yml
- OpenShift cluster login credentials configured
- rosa-creds-secret created in multicluster-engine namespace

## Quick start

```bash
./run-test-suite.py 23-rosa-hcp-no-cni -e name_prefix=qe6
```

Using name_prefix automatically sets cluster_name and domain_prefix consistently

## Customization

- **`openshift_version`:** OpenShift version to deploy (default: 5.0.0-ec.6, candidate channel)
- **`channel_group`:** Update channel: stable, fast, or candidate (this suite uses candidate for the 5.0 RC)
- **`network_type`:** ROSAControlPlane network.networkType enum (OVNKubernetes|Other); this suite uses Other for BYO-CNI
- **`aws_region`:** AWS region for deployment (default: us-west-2)

## Expected results

- ROSANetwork resource created with CloudFormation stack
- ROSARoleConfig resource created with IAM roles and OIDC
- ROSAControlPlane applied with network.networkType: Other (BYO-CNI)
- Cluster provisioned without the default OVNKubernetes CNI
- User can install and manage their own CNI plugin on the cluster
