# Enable CAPI/CAPA, Disable Hypershift

| Field | Value |
|---|---|
| **Suite ID** | `40-enable-capi-disable-hypershift` |
| **Tags** | `mce`, `capi`, `hypershift`, `configuration`, `component-management` |
| **Playbooks** | 1 |

## Overview

This test suite switches the MCE configuration from Hypershift mode back to CAPI/CAPA mode. Use this when you need to return to CAPI-based cluster management for ROSA HCP clusters.

## Prerequisites

- MCE/ACM hub cluster deployed
- OpenShift cluster login credentials configured
- Sufficient permissions to modify MCE configuration
- All Hypershift-managed clusters should be deleted before switching modes

## Quick start

```bash
./run-test-suite.py 40-enable-capi-disable-hypershift
```

Enables CAPI/CAPA components and disables Hypershift components in MCE

## Usage examples

### Basic switch

Switch from Hypershift to CAPI with default 30-second pause between steps

```bash
./run-test-suite.py 40-enable-capi-disable-hypershift
```

### Custom pause

Switch with a longer pause (60s) to allow more time for MCE reconciliation

```bash
./run-test-suite.py 40-enable-capi-disable-hypershift -e pause_duration=60
```

## Customization

- **`pause_duration`:** Time in seconds to wait between disabling Hypershift and enabling CAPI (default: 30)

## Operation steps

1. Login to OpenShift cluster
2. Get current MCE configuration
3. Disable Hypershift components (hypershift, hypershift-local-hosting)
4. Pause for MCE reconciliation
5. Enable CAPI components (cluster-api, cluster-api-provider-aws)
6. Verify final configuration

## Expected results

- CAPI/CAPA components enabled in MCE
- Hypershift components disabled in MCE
- MCE reconciliation successful
- CAPI/CAPA controllers deployed and running
- No errors in MCE operator logs

## Monitoring

```bash
oc get mce multiclusterengine -n multicluster-engine -o yaml
oc get deployment -n multicluster-engine | grep -E '(capi|capa)'
oc logs -n multicluster-engine deployment/multicluster-engine-operator
oc get deployment -n multicluster-engine capi-controller-manager
oc get deployment -n multicluster-engine capa-controller-manager
```

## Troubleshooting

### Component not enabled

**Symptom:** CAPI components not showing as enabled

**Check:**

```bash
oc get mce multiclusterengine -n multicluster-engine -o jsonpath='{.spec.overrides.components[?(@.name=="cluster-api")].enabled}'
```

**Solution:** Check MCE operator logs for reconciliation errors. May need to restart MCE operator.

### Component not disabled

**Symptom:** Hypershift components not showing as disabled

**Check:**

```bash
oc get mce multiclusterengine -n multicluster-engine -o jsonpath='{.spec.overrides.components[?(@.name=="hypershift")].enabled}'
```

**Solution:** Verify no Hypershift-managed clusters exist. Delete any remaining Hypershift resources before disabling.

### MCE not reconciling

**Symptom:** MCE configuration changes not applied

**Check:**

```bash
oc get mce multiclusterengine -n multicluster-engine -o jsonpath='{.status.conditions[?(@.type=="Available")]}'
```

**Solution:** Increase pause_duration to allow more time. Check MCE operator status.

### CAPI controllers not deploying

**Symptom:** CAPI/CAPA controller deployments not appearing

**Check:**

```bash
oc get deployment -n multicluster-engine | grep -E '(capi|capa)'
```

**Solution:** Check MCE operator logs. Verify component configuration is correct. May need to run 10-configure-mce-environment test suite.

## Important notes

- ⚠️  Delete all Hypershift-managed clusters BEFORE disabling Hypershift components
- ⚠️  This operation changes the cluster management mode - ensure you understand the implications
- ⚠️  After switching, run the MCE configuration test suite: ./run-test-suite.py 10-configure-mce-environment
- ✓ The operation is reversible - you can switch back to Hypershift if needed
- ✓ MCE will automatically deploy/remove the appropriate controllers based on configuration

## Workflow integration

Complete workflow for switching back to CAPI/CAPA from Hypershift

### Steps

1. Delete Hypershift clusters: (use Hypershift CLI or Console)
2. Switch mode: ./run-test-suite.py 40-enable-capi-disable-hypershift
3. Configure CAPI: ./run-test-suite.py 10-configure-mce-environment
4. Verify: oc get deployment -n multicluster-engine | grep -E '(capi|capa)'
5. Provision cluster: ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test

## Next steps

### After enabling CAPI

1. Configure MCE CAPI environment:

   ```bash
   ./run-test-suite.py 10-configure-mce-environment
   ```

2. Verify CAPI components are running:

   ```bash
   oc get deployment -n multicluster-engine | grep -E '(capi|capa)'
   ```

3. Provision a ROSA HCP cluster:

   ```bash
   ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test
   ```

## Reverse operation

To switch back from CAPI/CAPA to Hypershift

```bash
./run-test-suite.py 41-disable-capi-enable-hypershift
```

**Note:** Use test suite 41-disable-capi-enable-hypershift to return to Hypershift mode
