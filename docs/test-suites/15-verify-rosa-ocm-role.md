# Verify ROSAOCMRoleConfig

| Field | Value |
|---|---|
| **Suite ID** | `15-verify-rosa-ocm-role` |
| **Tags** | `rosa`, `ocm-role`, `iam`, `lifecycle` |
| **Playbooks** | 1 |

## Overview

This test suite verifies the ROSAOCMRoleConfig CRD and controller. It validates that the controller reconciles existing account roles, queries OCM organization linkage, marks the CR Ready, populates roleARN and organizationID, and safely removes finalizers on deletion without unlinking the shared account.

## Prerequisites

- OpenShift hub cluster with CAPA controller supporting ROSAOCMRoleConfig
- Valid OpenShift cluster login credentials configured in vars/user_vars.yml or environment
- OCM credentials configured in rosa-creds-secret
