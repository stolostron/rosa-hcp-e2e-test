# CAPA Private (PrivateLink) Cluster Provisioning - OpenShift 5.0 RC

| Field | Value |
|---|---|
| **Suite ID** | `22-rosa-hcp-private` |
| **Tags** | `rosa`, `hcp`, `provisioning`, `network-automation`, `role-automation`, `private`, `privatelink`, `5.0`, `features` |
| **Playbooks** | 1 |

## Overview

This test suite provisions a ROSA HCP PrivateLink cluster on the OpenShift 5.0 release candidate (5.0.0-ec.6, candidate channel) against the MCE 5.0 RC hub. It uses the versioned 5.0 feature template rosa-controlplane-only with private: true, which sets endpointAccess: Private on the ROSAControlPlane and extracts only private subnets from the automated ROSANetwork.

## Prerequisites

- MCE 5.0 RC hub cluster with CAPI/CAPA configured
- AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) in vars/user_vars.yml
- OpenShift cluster login credentials configured
- rosa-creds-secret created in multicluster-engine namespace

## Quick start

```bash
./run-test-suite.py 22-rosa-hcp-private -e name_prefix=qe6
```

Using name_prefix automatically sets cluster_name and domain_prefix consistently

## Customization

- **`openshift_version`:** OpenShift version to deploy (default: 5.0.0-ec.6, candidate channel)
- **`channel_group`:** Update channel: stable, fast, or candidate (this suite uses candidate for the 5.0 RC)
- **`private`:** Set by the suite to provision PrivateLink (`endpointAccess: Private`); the template defaults to Public
- **`aws_region`:** AWS region for deployment (default: us-west-2)

## Expected results

- ROSANetwork resource created with CloudFormation stack
- ROSARoleConfig resource created with IAM roles and OIDC
- ROSAControlPlane applied with endpointAccess: Private (PrivateLink)
- Cluster provisioned with no public API server or public ingress
- Cluster reachable only over AWS PrivateLink
