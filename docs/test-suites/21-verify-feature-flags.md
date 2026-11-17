# Verify Feature Flags

| Field | Value |
|---|---|
| **Suite ID** | `21-verify-feature-flags` |
| **Tags** | `rosa`, `hcp`, `features`, `verification` |
| **Playbooks** | 1 |

## Overview

This test suite verifies that features requested during provisioning (via --feature or --feature-group) were correctly applied. It checks CRDs, queries the OCM API, and validates AWS resources. Features not requested are SKIPped, not FAILed.

## Prerequisites

- A provisioned ROSA HCP cluster (suite 20 must have passed)
- CLUSTER_FEATURES or FEATURE_GROUP must be set
- OpenShift cluster login credentials configured
- AWS credentials for AWS CLI checks

## Quick start

```bash
./run-test-suite.py 21-verify-feature-flags --feature domain --feature autoscaler -e cluster_name=jnk-rosa-hcp
```

Verifies that the specified features were applied to the named cluster
