# Disable CAPI/CAPA, Enable Hypershift

| Field | Value |
|---|---|
| **Suite ID** | `41-disable-capi-enable-hypershift` |
| **Tags** | `mce`, `hypershift`, `capi`, `configuration`, `component-management` |
| **Playbooks** | 1 |

## Overview

This test suite switches the MCE configuration from CAPI/CAPA mode to Hypershift mode. It's useful when you need to use Hypershift for hosted control planes instead of CAPI for ROSA HCP cluster management.

## Prerequisites

- MCE/ACM hub cluster deployed
- OpenShift cluster login credentials configured
- Sufficient permissions to modify MCE configuration
- All CAPI-managed clusters should be deleted before switching modes

## Quick start

```bash
./run-test-suite.py 41-disable-capi-enable-hypershift
```

Disables CAPI/CAPA components and enables Hypershift components in MCE

## Usage examples

### Basic switch

Switch from CAPI to Hypershift with default 30-second pause between steps

```bash
./run-test-suite.py 41-disable-capi-enable-hypershift
```

### Custom pause

Switch with a longer pause (60s) to allow more time for MCE reconciliation

```bash
./run-test-suite.py 41-disable-capi-enable-hypershift -e pause_duration=60
```

## Customization

- **`pause_duration`:** Time in seconds to wait between enabling Hypershift and disabling CAPI (default: 30)

## Operation steps

1. Login to OpenShift cluster
2. Get current MCE configuration
3. Enable Hypershift components (hypershift, hypershift-local-hosting)
4. Pause for MCE reconciliation
5. Disable CAPI components (cluster-api, cluster-api-provider-aws)
6. Verify final configuration

## Expected results

- Hypershift components enabled in MCE
- CAPI/CAPA components disabled in MCE
- MCE reconciliation successful
- No errors in MCE operator logs

## Monitoring

```bash
oc get mce multiclusterengine -n multicluster-engine -o yaml
oc get deployment -n multicluster-engine | grep -E '(hypershift|cluster-api)'
oc logs -n multicluster-engine deployment/multicluster-engine-operator
```

## Troubleshooting

### Component not enabled

**Symptom:** Hypershift components not showing as enabled

**Check:**

```bash
oc get mce multiclusterengine -n multicluster-engine -o jsonpath='{.spec.overrides.components[?(@.name=="hypershift")].enabled}'
```

**Solution:** Check MCE operator logs for reconciliation errors. May need to restart MCE operator.

### Component not disabled

**Symptom:** CAPI components not showing as disabled

**Check:**

```bash
oc get mce multiclusterengine -n multicluster-engine -o jsonpath='{.spec.overrides.components[?(@.name=="cluster-api")].enabled}'
```

**Solution:** Verify no CAPI-managed clusters exist. Delete any remaining CAPI resources before disabling.

### MCE not reconciling

**Symptom:** MCE configuration changes not applied

**Check:**

```bash
oc get mce multiclusterengine -n multicluster-engine -o jsonpath='{.status.conditions[?(@.type=="Available")]}'
```

**Solution:** Increase pause_duration to allow more time. Check MCE operator status.

## Important notes

- ⚠️  Delete all CAPI-managed clusters BEFORE disabling CAPI components
- ⚠️  This operation changes the cluster management mode - ensure you understand the implications
- ⚠️  Hypershift and CAPI use different cluster lifecycle models
- ✓ The operation is reversible - you can switch back to CAPI if needed
- ✓ MCE will automatically deploy/remove the appropriate controllers based on configuration

## Workflow integration

Complete workflow for switching between CAPI and Hypershift modes

### Switch to hypershift

1. List clusters: oc get cluster.cluster.x-k8s.io -A
2. Delete clusters: ./run-test-suite.py 30-rosa-hcp-delete -e name_prefix=&lt;prefix&gt;
3. Switch mode: ./run-test-suite.py 41-disable-capi-enable-hypershift
4. Verify: oc get deployment -n multicluster-engine | grep hypershift

### Switch to CAPI

1. Delete Hypershift clusters (if any)
2. Switch mode: ./run-test-suite.py 40-enable-capi-disable-hypershift
3. Configure: ./run-test-suite.py 10-configure-mce-environment
4. Provision: ./run-test-suite.py 20-rosa-hcp-provision -e name_prefix=test

## Reverse operation

To switch back from Hypershift to CAPI/CAPA

**Note:** The reverse suite is `40-enable-capi-disable-hypershift`.

### Manual steps

1. Disable Hypershift: oc patch mce multiclusterengine --type=merge -p '{"spec":{"overrides":{"components":[{"name":"hypershift","enabled":false},{"name":"hypershift-local-hosting","enabled":false}]}}}'
2. Enable CAPI: oc patch mce multiclusterengine --type=merge -p '{"spec":{"overrides":{"components":[{"name":"cluster-api","enabled":true},{"name":"cluster-api-provider-aws","enabled":true}]}}}'
3. Run: ./run-test-suite.py 10-configure-mce-environment
