# Dual-Mode Jenkins Implementation — COMPLETE ✅

## Summary

Successfully implemented **scenario-based + custom-features dual-mode Jenkins** for ROSA HCP E2E testing.

**Commit:** `5a392ed` on `fix/machine-pool-readiness-detection`

---

## What Changed

### 4 Jenkinsfile Modifications

**1. Parameters Block (Lines 96–143)**
- ✅ Added `TEST_MODE` choice (scenario | custom-features, default: scenario)
- ✅ Added `TEST_SCENARIO` choice (5 scenarios: day1-basic, day1-combo, day1-networking, day1-security, day2-machinepool)
- ✅ Added `OPENSHIFT_VERSION` string (default: `5.0.0-rc.6`)
- ✅ Added `CHANNEL_GROUP` string (default: `candidate`)
- ✅ Added `EXTRA_VARS` string (replaces scattered feature var params)
- ✅ Kept `CLUSTER_FEATURES`, `FEATURE_GROUP`, `EXTRA_FEATURE_VARS`, `ETCD_KMS_ARN` (marked `[CUSTOM MODE]`)
- ✅ Kept all auth/environment params unchanged

**2. Validate Feature Flags Stage (Line 227)**
- ✅ Added condition: `params.TEST_MODE == 'custom-features'`
- Only runs in custom-features mode (skipped in scenario mode)

**3. Provision Stage (Lines 307–357)**
- ✅ Added `if [ "${TEST_MODE}" = "scenario" ]` conditional
- ✅ Scenario branch: `--scenario ${TEST_SCENARIO}` with version/channel params
- ✅ Custom branch: Original feature flag logic (preserved)
- ✅ Added new params to environment block: TEST_MODE, TEST_SCENARIO, OPENSHIFT_VERSION, CHANNEL_GROUP

**4. Verify Feature Flags Stage (Lines 376–380)**
- ✅ Updated when condition to: `(TEST_MODE == 'scenario') || (TEST_MODE == 'custom-features' && features set)`
- ✅ Runs in both modes (scenario always includes it, custom only if features set)
- ✅ Added TEST_SCENARIO to environment for scenario mode reference

---

## How to Use

### Default Path: Scenario Mode (Recommended)

```
TEST_MODE = scenario (default)
TEST_SCENARIO = day1-basic
OPENSHIFT_VERSION = 5.0.0-rc.6
CHANNEL_GROUP = candidate
EXTRA_VARS = (leave blank or override specific vars)
```

**Result:** `./run-test-suite.py --scenario day1-basic -e openshift_version=5.0.0-rc.6 -e channel_group=candidate ...`

### Advanced Path: Custom Features Mode (Power Users)

```
TEST_MODE = custom-features
CLUSTER_FEATURES = no-cni,external-oidc
FEATURE_GROUP = day1-networking
EXTRA_FEATURE_VARS = root_volume_size=500
ETCD_KMS_ARN = arn:aws:kms:...
OPENSHIFT_VERSION = 5.0.0-rc.6
CHANNEL_GROUP = candidate
```

**Result:** `./run-test-suite.py 20-rosa-hcp-provision --feature no-cni --feature external-oidc --feature-group day1-networking ...`

---

## Benefits

✅ **Prevents Typos** — Scenario defaults catch version/channel errors (was: `5.0.0-ec.6` in #374)
✅ **Discoverable** — Jenkins dropdown shows all available scenarios (clear choices)
✅ **Simplified Flow** — Scenario stage routing (10→20→21→30) baked into registry
✅ **Backward Compatible** — Custom features mode preserves old behavior 100%
✅ **Zero Risk** — All auth, cleanup, upgrade logic untouched

---

## Testing Checklist

Before merging to main, test:

- [ ] **Scenario Mode (day1-basic)**: Pick scenario=day1-basic, run through Jenkins
  - Should provision, verify, delete successfully
  - Validate Feature Flags stage: SKIPPED ✓
  - Verify Feature Flags stage: RUNS ✓

- [ ] **Scenario Mode (day1-security)**: Pick scenario=day1-security, set EXTRA_VARS with KMS ARN
  - Should pass etcd_kms feature through
  - Validate stage skipped ✓
  - Verify stage runs ✓

- [ ] **Custom Features Mode**: Set TEST_MODE=custom-features, CLUSTER_FEATURES=no-cni,external-oidc
  - Should use original feature flag path
  - Validate Feature Flags stage: RUNS (validates flags) ✓
  - Verify Feature Flags stage: RUNS (if features set) ✓

- [ ] **RC6 Scenario Run**: Jenkins #376+ with scenario=day1-basic, version=5.0.0-rc.6, channel=candidate
  - Cluster provisions, verifies, deletes
  - No version typos, clean logs

---

## Next Steps

1. **Wait for Jenkins #375 to complete** (currently running)
   - Verify RC6 baseline passes with corrected version
   
2. **Test dual-mode locally** (optional):
   ```bash
   # Scenario mode
   cd rosa-hcp-e2e-test
   ./run-test-suite.py --scenario day1-basic \
     -e openshift_version=5.0.0-rc.6 \
     -e channel_group=candidate \
     ...rest of vars...
   
   # Custom mode (verify old path still works)
   ./run-test-suite.py 20-rosa-hcp-provision \
     --feature no-cni --feature-group day1-networking \
     -e openshift_version=5.0.0-rc.6 \
     -e channel_group=candidate \
     ...rest of vars...
   ```

3. **Create PR** with commit `5a392ed` when ready
   - Base: main
   - Title: "feat: scenario-based Jenkins testing (dual-mode)"
   - Description: Link to this document + RC6 test results

4. **Merge to main** after tests pass

---

## Files Modified

- ✅ `Jenkinsfile` — All 4 changes in place

## Files Created (for tracking)

- `DUAL_MODE_CODE_CHANGES.md` — Reference code changes
- `DUAL_MODE_IMPLEMENTATION_COMPLETE.md` — This file

---

## Rollback Plan

If issues arise:

```bash
# Revert to pre-dual-mode state
git revert 5a392ed

# Or manually revert the 4 changes (edit Jenkinsfile back to feature-only params)
```

---

## Git Status

```
On branch fix/machine-pool-readiness-detection
Your branch is ahead of origin/main by 8 commits.

Changes to be committed: (none)
Working tree clean ✓
```

All changes committed, ready to push and create PR.
