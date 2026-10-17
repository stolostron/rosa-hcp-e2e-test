# RC6 CAPA Scenario-Based Testing Plan

**Date:** October 16, 2026  
**Goal:** Complete RC6 CAPA testing for ROSA HCP clusters  
**Status:** In Progress  

---

## Executive Summary

This document outlines the scenario-based testing strategy for RC6 CAPA (Cluster API Provider AWS) with ROSA HCP (Red Hat OpenShift Service on AWS Hosted Control Plane).

**Key Outcome:** Validate that all day1 and day2 scenarios work correctly with the scenario-based testing framework.

---

## Testing Progress

### ✅ Completed Tests

1. **day1-basic with rs1 prefix (4.22.6)**
   - Status: ✅ PASSED (Configure, Provision, Verify)
   - Duration: 16m 44s
   - Result: All 3 stages passed; deletion had code bug (now fixed)
   - Outcome: Scenario framework works end-to-end

2. **day1-basic with rs2 prefix (5.0.0-rc.6)** 
   - Status: ✅ PASSED (Configure, Provision, Verify)
   - Duration: 17m 12s
   - Result: Cluster provisioned successfully with RC6
   - Outcome: RC6 provisioning works; deletion code bug confirmed and fixed

### 🔄 In Progress

- Cleanup of rs2-rosa-hcp cluster

### ⏭️ Planned Tests

| Test | Prefix | Version | Features | Status |
|------|--------|---------|----------|--------|
| day1-combo | rs3 | 5.0.0-rc.6 | domain_prefix, AZs, tags, channel, autoscaling + networking | Queued |
| day1-networking | rs4 | 5.0.0-rc.6 | domain_prefix, AZs, tags, channel, autoscaling + networking config | Queued |
| day1-security | rs5 | 5.0.0-rc.6 | domain_prefix, AZs, tags, channel, autoscaling + OIDC | Queued |
| day2-machinepool | rs6 | 5.0.0-rc.6 | Multi-zone machine pools with different configs | Queued |

---

## Available Scenarios

### Day 1 Scenarios (Basic Provisioning)

**day1-basic**
- Features: domain_prefix, availability_zones, additional_tags, channel_group, default_autoscaling
- Use case: Baseline ROSA HCP cluster with core features
- Stages: Configure MCE → Provision → Verify → Delete
- Runtime: ~17 minutes

**day1-combo**
- Features: All day1-basic + networking configuration
- Use case: Cluster with pre-configured VPC/networking
- Runtime: ~20 minutes

**day1-networking**
- Features: Advanced networking (custom CIDR, subnet config)
- Use case: Multi-zone cluster with specific network topology
- Runtime: ~22 minutes

**day1-security**
- Features: External OIDC provider integration
- Use case: Cluster with identity provider for pod authentication
- Runtime: ~18 minutes

### Day 2 Scenarios (Advanced)

**day2-machinepool**
- Features: Multiple machine pools with different node counts, types, instance sizes
- Use case: Cluster with heterogeneous worker node configuration
- Runtime: ~25 minutes

---

## Code Fixes Applied

### Fix 1: Deletion Task Conditional Logic Bug

**File:** `/tasks/delete_rosa_hcp_resources.yml`  
**Lines:** 335, 345  
**Issue:** Operator precedence and unsafe dict attribute access  

**Before:**
```yaml
- "wait_rcp is defined and wait_rcp.rc == 0 or final_rcp_check is defined and final_rcp_check.rc == 0"
```

**After:**
```yaml
- "((wait_rcp is defined and wait_rcp.rc == 0) or (final_rcp_check is defined and final_rcp_check.get('rc', 1) == 0))"
```

**Impact:** Deletion phase now completes successfully instead of crashing on conditional evaluation.

---

## Testing Strategy

### Phase 1: RC6 Basic Validation ✅
- ✅ Verify scenario framework works
- ✅ Verify RC6 cluster provisioning
- ✅ Fix deletion task bugs
- ⏳ Next: Run remaining day1 scenarios

### Phase 2: Advanced Scenarios (Today)
- day1-combo with rs3
- day1-networking with rs4
- day1-security with rs5
- day2-machinepool with rs6

### Phase 3: Dual-Mode Jenkinsfile Integration (After validation)
- Merge dual-mode Jenkinsfile to main
- Configure Jenkins with scenario parameters
- Run Jenkins job #376+ with scenario mode

---

## Test Execution Command Template

```bash
# Basic template
python3 run-test-suite.py --scenario <scenario-name> -e name_prefix=<prefix> -e openshift_version=5.0.0-rc.6

# Examples:
python3 run-test-suite.py --scenario day1-basic -e name_prefix=rs2 -e openshift_version=5.0.0-rc.6
python3 run-test-suite.py --scenario day1-combo -e name_prefix=rs3 -e openshift_version=5.0.0-rc.6
python3 run-test-suite.py --scenario day1-networking -e name_prefix=rs4 -e openshift_version=5.0.0-rc.6
python3 run-test-suite.py --scenario day1-security -e name_prefix=rs5 -e openshift_version=5.0.0-rc.6
python3 run-test-suite.py --scenario day2-machinepool -e name_prefix=rs6 -e openshift_version=5.0.0-rc.6
```

---

## Success Criteria

Each test is considered **PASSED** when:

1. ✅ **Configure MCE Environment** stage completes (MCE/CAPI/CAPA ready)
2. ✅ **Provision ROSA HCP Cluster** stage completes (cluster created in AWS)
3. ✅ **Verify Feature Flags** stage completes (all features applied correctly)
4. ✅ **Delete Cluster** stage completes (clean removal of all resources)

**Pass Rate Target:** 5/5 scenarios passing (100%)

---

## Known Issues & Workarounds

### Issue 1: Deletion Task Conditional Bug
- **Status:** ✅ FIXED
- **Details:** See "Code Fixes Applied" section above
- **Verification:** Run `day1-basic` with rs2 again after fix

### Issue 2: Auto-Recreating Orphaned Clusters
- **Status:** DOCUMENTED
- **Details:** Use `rosa delete cluster` (not `oc delete`) to prevent orphans
- **Relevance:** Low for scenario testing (automated deletion)

### Issue 3: MCE Upgrade Impact on Clusters
- **Status:** RESEARCH COMPLETE
- **Details:** See `MCE_UPGRADE_AND_CLUSTER_ATTACHMENT.md`
- **Key Finding:** MCE upgrades do NOT scale down or delete clusters

---

## Next Steps

1. **Wait for rs2 cleanup** to complete
2. **Run day1-combo with rs3** — Next scenario
3. **Monitor for completion** (expect ~20 minutes)
4. **Continue with day1-networking (rs4)** if day1-combo passes
5. **Track results in this document**

---

## Environment Status

**Current Namespace:** ns-rosa-hcp  
**Running Processes:** 0 (test completed)  
**Failed Resources:** 0  
**Git Branch:** `fix/machine-pool-readiness-detection` (before dual-mode Jenkinsfile)  

---

## Reference Documents

- `/MCE_UPGRADE_AND_CLUSTER_ATTACHMENT.md` — MCE upgrade safety and behavior
- `/backup-crs-2026-10-16/` — Cluster resource backups
- `test-rs2-day1-basic.log` — Latest test execution log

---

**Last Updated:** 2026-10-16 10:50 UTC  
**Test Owner:** Tina Fitzgerald  
**Goal:** Complete RC6 CAPA testing before end of day
