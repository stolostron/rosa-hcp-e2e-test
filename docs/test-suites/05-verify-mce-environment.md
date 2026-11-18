# Verify MCE Environment

| Field | Value |
|---|---|
| **Suite ID** | `05-verify-mce-environment` |
| **Tags** | `mce`, `capi`, `capa`, `validation`, `verification` |
| **Playbooks** | 1 |

## Overview

This test suite validates the MCE environment before attempting cluster provisioning. It checks OCP login, CAPI/CAPA controller deployments, and optionally reports on existing resources. Use this to verify your environment is ready for ROSA HCP cluster management.

## Prerequisites

- OpenShift cluster login credentials configured in vars/user_vars.yml
- MCE hub cluster deployed
- Network access to OpenShift API

## Quick start

```bash
./run-test-suite.py 05-verify-mce-environment
```

Validates MCE environment is ready for cluster provisioning

## Usage examples

### Pre configuration check

Run before 10-configure-mce-environment to see what needs to be configured

**Use case:** First-time setup or troubleshooting

```bash
./run-test-suite.py 05-verify-mce-environment
```

### Post configuration validation

Configure MCE then verify the configuration succeeded

**Use case:** Ensure configuration changes were applied correctly

```bash
./run-test-suite.py 10-configure-mce-environment && ./run-test-suite.py 05-verify-mce-environment
```

### Pre provisioning check

Verify environment before provisioning a cluster

**Use case:** Proactive validation to catch issues early

```bash
./run-test-suite.py 05-verify-mce-environment && ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test
```

## Validation steps

1. Verify OCP login successful
2. Check CAPI controller (capi-controller-manager) deployed
3. Check CAPA controller (capa-controller-manager) deployed
4. Report ClusterManager registration configuration (informational)
5. Report ClusterRoleBinding status (informational)
6. Report AWS credentials secret status (informational)
7. Report ROSA credentials secret status (informational)
8. Report AWSClusterControllerIdentity status (informational)
9. List existing ROSA namespaces (informational)
10. List existing ROSACluster resources (informational)
11. List existing RosaControlPlane resources (informational)
12. List existing RosaNetwork resources (informational)
13. List existing Cluster resources (informational)

## What gets validated

### Critical checks

These MUST pass for the test to succeed

- OCP login context is valid
- CAPI controller manager is deployed in multicluster-engine namespace
- CAPA controller manager is deployed in multicluster-engine namespace

### Informational checks

These are reported but don't cause failure

- ClusterManager registration configuration
- ClusterRoleBinding for CAPI registration
- AWS and ROSA credential secrets
- AWSClusterControllerIdentity
- Existing clusters and resources

## Expected results

### Fully configured

- ✅ OCP login successful
- ✅ CAPI controller deployed and running
- ✅ CAPA controller deployed and running
- ✓ All configuration resources present
- Message: ENVIRONMENT CONFIGURED AND READY TO GO!

### Needs configuration

- ✅ OCP login successful
- ❌ CAPI controller not found - needs configuration
- Error: Click 'Configure' button to set up CAPI/CAPA

### Login needed

- ❌ OpenShift login needed
- Error: Click 'Credentials' button to update cluster connection

## Workflow integration

How this fits into the complete ROSA HCP workflow

### Recommended workflow

1. Verify environment: ./run-test-suite.py 05-verify-mce-environment
2. If validation fails, configure: ./run-test-suite.py 10-configure-mce-environment
3. Verify configuration worked: ./run-test-suite.py 05-verify-mce-environment
4. Provision cluster: ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test
5. Delete cluster: ./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=test

### Troubleshooting workflow

1. Cluster provisioning failed?
2. Run: ./run-test-suite.py 05-verify-mce-environment
3. Check which critical checks failed
4. Re-configure: ./run-test-suite.py 10-configure-mce-environment
5. Verify again: ./run-test-suite.py 05-verify-mce-environment
6. Retry provisioning

## Troubleshooting

### OCP login failed

**Symptom:** 🔑 OpenShift login needed

**Check:**

```bash
oc whoami --show-context
```

**Solution:** Update OCP_HUB_CLUSTER_USER, OCP_HUB_CLUSTER_PASSWORD, and OCP_HUB_API_URL in vars/user_vars.yml

### CAPI controller not found

**Symptom:** ⚙️ Configuration needed - CAPI controller not found

**Check:**

```bash
oc get deployment -n multicluster-engine | grep capi
```

**Solution:** Run: ./run-test-suite.py 10-configure-mce-environment

### CAPA controller not found

**Symptom:** ⚙️ AWS provider needed - CAPA controller not found

**Check:**

```bash
oc get deployment -n multicluster-engine | grep capa
```

**Solution:** Run: ./run-test-suite.py 10-configure-mce-environment

### Controllers not ready

**Symptom:** Controllers deployed but pods not ready

**Check:**

```bash
oc get pods -n multicluster-engine | grep -E '(capi|capa)'
```

**Solution:** Check pod logs: oc logs -n multicluster-engine deployment/capi-controller-manager

## Monitoring

Use these commands to monitor environment status after validation

```bash
oc get deployment -n multicluster-engine | grep -E '(capi|capa)'
oc get pods -n multicluster-engine | grep -E '(capi|capa)'
oc get mce multiclusterengine -n multicluster-engine -o yaml
oc get rosacontrolplane,rosamachinepool,rosanetwork --all-namespaces
```

## Important notes

- ✓ This test suite is non-destructive - it only reads and reports status
- ✓ Informational checks don't cause failure - they show what exists
- ✓ Critical checks must pass: OCP login, CAPI controller, CAPA controller
- ✓ Run this before provisioning to catch configuration issues early
- ✓ Run this after configuration to verify changes were applied
- ⚠️ If validation fails, run 10-configure-mce-environment to fix issues

## Next steps

### If validation passes

Environment is ready for cluster provisioning!

1. Provision a ROSA HCP cluster:

   ```bash
   ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test
   ```

2. Or use the E2E workflow:

   ```bash
   ./run-e2e-workflow.sh test skip-config
   ```

### If validation fails

Environment needs configuration.

1. Configure MCE environment:

   ```bash
   ./run-test-suite.py 10-configure-mce-environment
   ```

2. Verify configuration succeeded:

   ```bash
   ./run-test-suite.py 05-verify-mce-environment
   ```

3. Then provision clusters:

   ```bash
   ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test
   ```

## Comparison

### Verify vs configure

#### 05 verify MCE environment

Read-only validation - checks current state

#### 10 configure MCE environment

Write operation - applies configuration changes

### When to use each

#### Use verify when

1. Before provisioning clusters
2. After configuration to confirm it worked
3. Troubleshooting provisioning issues
4. Checking environment status

#### Use configure when

1. First-time MCE setup
2. CAPI/CAPA controllers not deployed
3. Configuration resources missing
4. After MCE upgrade or changes
