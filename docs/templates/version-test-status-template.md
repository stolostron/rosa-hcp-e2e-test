# OpenShift {VERSION} ROSA HCP E2E Test Status

**Date:** {DATE}
**Branch:** {BRANCH}
**Hub:** {HUB_URL}
**Hub OCP:** {HUB_OCP_VERSION} | **ACM:** {ACM_VERSION} | **MCE:** {MCE_VERSION}
**CAPA Image:** `{CAPA_IMAGE}`
**CRD API:** {CRD_API_VERSION}

---

## Cluster Under Test

| Property | Value |
|----------|-------|
| Cluster Name | {CLUSTER_NAME} |
| Namespace | {NAMESPACE} |
| OpenShift Version | {VERSION} |
| Region | {REGION} |
| AZs | {AZS} |
| Domain Prefix | {DOMAIN_PREFIX} |
| Provision Status | {PROVISION_STATUS} |
| Provision Duration | {PROVISION_DURATION} |

---

## Features Tested

| Feature | CLI Flag | Ansible Var | CRD Field | Rendered | CRD Supported | Verified |
|---------|----------|-------------|-----------|----------|---------------|----------|
| | `--feature ` | `=` | `.spec.` | YES/NO | YES/NO | PASS/FAIL/SKIP |

---

## Provisioning Results (Suite 20)

| Step | Resource | Status | Duration |
|------|----------|--------|----------|
| 1/3 | ROSARoleConfig | | |
| 2/3 | ROSANetwork | | |
| 3/3 | ROSAControlPlane + ROSAMachinePool | | |

---

## Verification Results (Suite 21)

| Feature | CRD Field | Expected Value | Actual Value | Result |
|---------|-----------|----------------|--------------|--------|
| | `.spec.` | | | PASS/FAIL/SKIP |

---

## Template Changes

### New fields added

| Field | Template Var | CRD Field | Min ACM Version |
|-------|-------------|-----------|-----------------|
| | `{{ var }}` | `.spec.` | |

### Fields removed/fixed

| Field | Change | Reason |
|-------|--------|--------|
| | | |

---

## CRD Feature Support (from `./scripts/check_crd_feature_support.sh`)

### ROSAControlPlane ({N}/{TOTAL})

| Feature | CRD Field | Supported |
|---------|-----------|-----------|
| | `.spec.` | YES/NO |

### ROSAMachinePool ({N}/{TOTAL})

| Feature | CRD Field | Supported |
|---------|-----------|-----------|
| | `.spec.` | YES/NO |

---

## Environment Comparison

*Link to `docs/crd-feature-support-report.md` for cross-environment comparison*

---

## Future Work

- [ ] 
- [ ] 

---

## How to Reproduce

```bash
./run-test-suite.py 20-rosa-hcp-provision \
  --feature {FEATURE1} --feature {FEATURE2} \
  -e openshift_version={VERSION} \
  -e name_prefix={PREFIX} \
  -e OCP_HUB_API_URL={HUB_URL} \
  ... (credentials)
```
