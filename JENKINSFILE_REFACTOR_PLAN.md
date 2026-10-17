# Jenkinsfile Refactor Plan: Scenario-Based Testing

## Overview

Add scenario-based parameters (`TEST_SCENARIO`, `OPENSHIFT_VERSION`, `CHANNEL_GROUP`) while keeping feature-based parameters as a fallback for advanced/custom testing.

**Dual-Mode Approach:**
- **Scenario Mode (default, recommended):** Pick `TEST_SCENARIO` from dropdown → simple, safe, no typos
- **Custom Features Mode (optional, for power users):** Set `TEST_MODE=custom-features` → granular `--feature` flags with full flexibility

**Impact:** Simplifies most Jenkins jobs (scenarios), preserves flexibility for advanced users (custom features), prevents typos through defaults.

**Effort:** ~90 minutes total (slightly more complex than removal-only)

---

## Phase 1: Parameter Definition (10 min)

### Location
Lines 96–113 in Jenkinsfile (the `parameters` block)

### Current State
```groovy
parameters {
    string(name:'OCP_HUB_API_URL', defaultValue: '', description: 'Hub OCP API url')
    string(name:'OCP_HUB_CLUSTER_USER', defaultValue: 'kubeadmin', description: 'Hub OCP username')
    password(name:'OCP_HUB_CLUSTER_PASSWORD', defaultValue: '', description: 'Hub cluster password')
    string(name:'MCE_NAMESPACE', defaultValue: 'multicluster-engine', description: 'The Namespace where MCE is installed')
    string(name:'OCM_API_URL', defaultValue: 'https://api.stage.openshift.com', description: 'OCM API URL')
    string(name:'OCM_CLIENT_ID', defaultValue: '', description: 'OCM client ID for ROSA provisioning')
    password(name:'OCM_CLIENT_SECRET', defaultValue: '', description: 'OCM client secret for ROSA provisioning')
    string(name:'TEST_GIT_BRANCH', defaultValue: 'main', description: 'Git branch to test (for reference/documentation)')
    string(name:'NAME_PREFIX', defaultValue: 'jnk', description: 'Cluster name prefix (creates {prefix}-rosa-hcp)')
    
    // TO REMOVE:
    string(name:'CLUSTER_FEATURES', defaultValue: '', description: '...')
    string(name:'FEATURE_GROUP', defaultValue: '', description: '...')
    string(name:'EXTRA_FEATURE_VARS', defaultValue: '', description: '...')
    string(name:'ETCD_KMS_ARN', defaultValue: '', description: '...')
    
    booleanParam(name:'RUN_UPGRADE_TESTS', defaultValue: false, description: '...')
    booleanParam(name:'CLEANUP_AFTER_TEST', defaultValue: true, description: '...')
    booleanParam(name:'RESTORE_HYPERSHIFT', defaultValue: true, description: '...')
}
```

### New State
```groovy
parameters {
    // ========== Environment & Auth (Keep) ==========
    string(name:'OCP_HUB_API_URL', defaultValue: '', description: 'Hub OCP API url (required)')
    string(name:'OCP_HUB_CLUSTER_USER', defaultValue: 'kubeadmin', description: 'Hub OCP username')
    password(name:'OCP_HUB_CLUSTER_PASSWORD', defaultValue: '', description: 'Hub cluster password (required)')
    string(name:'MCE_NAMESPACE', defaultValue: 'multicluster-engine', description: 'MCE namespace')
    string(name:'OCM_API_URL', defaultValue: 'https://api.stage.openshift.com', description: 'OCM API URL (e.g. https://api.openshift.com or https://api.stage.openshift.com)')
    string(name:'TEST_GIT_BRANCH', defaultValue: 'main', description: 'Git branch to test (for reference/documentation)')
    string(name:'NAME_PREFIX', defaultValue: 'jnk', description: 'Cluster name prefix (creates {prefix}-rosa-hcp)')
    
    // ========== Scenario Selection (New) ==========
    choice(name: 'TEST_SCENARIO', choices: [
        'day1-basic',
        'day1-combo',
        'day1-networking',
        'day1-security',
        'day2-machinepool'
    ], description: 'Test scenario preset (e.g., day1-basic, day1-security)')
    
    string(name: 'OPENSHIFT_VERSION', defaultValue: '5.0.0-rc.6', 
           description: 'OpenShift version (e.g., 5.0.0-rc.6, 4.22.0)')
    
    string(name: 'CHANNEL_GROUP', defaultValue: 'candidate', 
           description: 'Channel group (stable, fast, candidate)')
    
    string(name: 'EXTRA_VARS', defaultValue: '', 
           description: 'Additional Ansible vars as key=value pairs (e.g., root_volume_size=500 etcd_encryption_kms_arn=arn:aws:...)')
    
    // ========== Test Control Flow (Keep) ==========
    booleanParam(name:'RUN_UPGRADE_TESTS', defaultValue: false, description: 'Run control plane and machine pool upgrade tests after provisioning')
    booleanParam(name:'CLEANUP_AFTER_TEST', defaultValue: true, description: 'Delete cluster after successful provisioning (E2E test)')
    booleanParam(name:'RESTORE_HYPERSHIFT', defaultValue: true, description: 'Restore HyperShift and disable CAPI/CAPA after test (uncheck to leave CAPI enabled)')
}
```

### Changes
- ✅ Keep: all auth params (OCP_HUB_*, MCE_NAMESPACE, OCM_API_URL, TEST_GIT_BRANCH, NAME_PREFIX)
- ✅ Keep: test flow control (RUN_UPGRADE_TESTS, CLEANUP_AFTER_TEST, RESTORE_HYPERSHIFT)
- ❌ Remove: CLUSTER_FEATURES, FEATURE_GROUP, EXTRA_FEATURE_VARS, ETCD_KMS_ARN
- ✅ Add: TEST_SCENARIO (choice), OPENSHIFT_VERSION, CHANNEL_GROUP, EXTRA_VARS

---

## Phase 2: Remove Feature Validation Stage (10 min)

### Location
Lines 196–250 (entire "Validate Feature Flags" stage)

### Current State
```groovy
stage ('Validate Feature Flags') {
    when {
        allOf {
            expression { currentBuild.result != 'FAILURE' }
            expression { params.CLUSTER_FEATURES?.trim() || params.FEATURE_GROUP?.trim() }
        }
    }
    environment {
        CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
        FEATURE_GROUP = "${params.FEATURE_GROUP}"
        EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
        ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
    }
    steps {
        script {
            try {
                sh '''
                    cd rosa-hcp-e2e-test
                    # Build feature flags from CLUSTER_FEATURES parameter
                    FEATURE_FLAGS=""
                    if [ -n "${CLUSTER_FEATURES}" ]; then
                        for feature in $(echo "${CLUSTER_FEATURES}" | tr ',' ' '); do
                            FEATURE_FLAGS="${FEATURE_FLAGS} --feature ${feature}"
                        done
                    fi
                    # ... rest of validation logic ...
                '''
            }
            catch (ex) {
                echo "Feature validation FAILED"
                currentBuild.result = 'FAILURE'
            }
        }
    }
}
```

### Action
**Delete entire stage** (lines 196–250).

**Why?** Scenario validation happens automatically in `feature_manager.py` when `--scenario` is resolved. No separate dry-run needed.

---

## Phase 3: Update Provisioning Stage (20 min)

### Location
Lines 251–322 ("Provision a ROSA HCP Cluster" stage)

### Current Command
```groovy
./run-test-suite.py 20-rosa-hcp-provision --format junit -v --ai-agent ${FEATURE_FLAGS} ${GROUP_FLAG} \
  -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
  -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
  -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
  -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
  -e AWS_REGION="us-west-2" \
  -e name_prefix="${NAME_PREFIX}" \
  -e OCM_API_URL="${OCM_API_URL}" \
  ${EXTRA_VARS}
```

### New Command
```groovy
./run-test-suite.py --scenario ${TEST_SCENARIO} --format junit -v --ai-agent \
  -e openshift_version="${OPENSHIFT_VERSION}" \
  -e channel_group="${CHANNEL_GROUP}" \
  -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
  -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
  -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
  -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
  -e AWS_REGION="us-west-2" \
  -e name_prefix="${NAME_PREFIX}" \
  -e OCM_API_URL="${OCM_API_URL}" \
  ${EXTRA_VARS}
```

### Changes
- Remove feature flag building logic (lines 277–298)
- Replace with `--scenario ${TEST_SCENARIO}`
- Add `-e openshift_version="${OPENSHIFT_VERSION}"` and `-e channel_group="${CHANNEL_GROUP}"`
- Keep all other `-e` parameters unchanged
- Keep `${EXTRA_VARS}` pass-through at end

### Steps
1. Remove lines 276–298 (feature flag building)
2. Rewrite sh block to use `--scenario` syntax
3. Add version and channel_group vars
4. Test locally with one scenario first

---

## Phase 4: Clean Up Environment Blocks (15 min)

### Affected Stages
- Lines 196–250: (deleted in Phase 2)
- Lines 251–322: Provisioning (updated in Phase 3)
- Lines 324–406: Verify Feature Flags
- Lines 407–435: Add ROSA MachinePool
- Lines 437–465: Delete ROSA MachinePool

### Action
Remove these environment variables from all stage `environment` blocks:
```groovy
CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
FEATURE_GROUP = "${params.FEATURE_GROUP}"
EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
```

### Keep
All other environment vars (OCP_HUB_API_URL, MCE_NAMESPACE, etc.) stay in place.

**Affected Lines:**
- Line 204–207: Remove from "Validate Feature Flags" env (stage deleted, so N/A)
- Line 259–262: Remove from "Provision" env
- Line 331–338: Remove from "Verify Feature Flags" env

---

## Phase 5: Verify Feature Flags Stage (10 min)

### Location
Lines 324–406

### Current Behavior
Only runs if `CLUSTER_FEATURES` or `FEATURE_GROUP` is set. Uses those to build `--feature` flags for verification.

### New Behavior
Scenario includes its own stage list. If scenario includes stage 21 (verify-feature-flags), it runs automatically.

### Action
**Keep the stage as-is**, but update condition to always run (scenarios always include it):
```groovy
stage('Verify Feature Flags') {
    when {
        expression { currentBuild.result != 'FAILURE' }
    }
    // ... rest unchanged ...
}
```

**Why?** The scenario's stage list (from registry) now controls which stages run. Provisioning stage uses `--scenario`, which includes/excludes verification automatically.

---

## Phase 6: Update Add/Delete MachinePool Stages (10 min)

### Location
Lines 407–435 (Add), 437–465 (Delete)

### Current State
These stages take environment from provisioning (cluster_name, pool_name).

### Action
**No changes needed.** These stages don't use feature params. Just remove feature env vars from their environment blocks (Phase 4).

### Keep
- OCP_HUB_API_URL, OCP_HUB_CLUSTER_USER, MCE_NAMESPACE still needed
- cluster_name and pool_name derived from NAME_PREFIX (already in place)

---

## Phase 7: Local Smoke Test (30 min)

### Before Committing

**Test 1: day1-basic scenario**
```bash
cd rosa-hcp-e2e-test
./run-test-suite.py --scenario day1-basic \
  -e openshift_version=5.0.0-rc.6 \
  -e channel_group=candidate \
  -e OCP_HUB_API_URL=... \
  -e OCP_HUB_CLUSTER_USER=kubeadmin \
  -e MCE_NAMESPACE=multicluster-engine \
  -e AWS_ACCOUNT_ID=... \
  -e AWS_REGION=us-west-2 \
  -e name_prefix=test
```

**Expected:**
- Feature manager resolves day1-basic features
- Provisioning stage runs (20)
- Verification stage runs (21)
- Deletion stage runs (30)
- All pass ✅

**Test 2: day1-security scenario with EXTRA_VARS**
```bash
./run-test-suite.py --scenario day1-security \
  -e openshift_version=5.0.0-rc.6 \
  -e channel_group=candidate \
  -e etcd_encryption_kms_arn=arn:aws:kms:... \
  # ... other vars ...
```

**Expected:**
- Scenario includes etcd_kms feature
- EXTRA_VARS passes through KMS ARN correctly
- Provisioning succeeds ✅

---

## Phase 8: Update Jenkins Job (5 min)

### Steps
1. Commit Jenkinsfile changes to branch
2. Open Jenkins job configuration UI
3. Verify new parameters appear:
   - TEST_SCENARIO (choice dropdown with 5 options)
   - OPENSHIFT_VERSION (string, default 5.0.0-rc.6)
   - CHANNEL_GROUP (string, default candidate)
   - EXTRA_VARS (string, blank)
4. Verify removed parameters are gone:
   - CLUSTER_FEATURES ❌
   - FEATURE_GROUP ❌
   - EXTRA_FEATURE_VARS ❌
   - ETCD_KMS_ARN ❌
5. Test one scenario run through UI

---

## Rollback Plan

If anything breaks:

1. **Revert commit:** `git revert HEAD`
2. **Identify blocker:**
   - Scenario resolution failed? Check feature_manager.py
   - Stage didn't run? Check scenario stage list in feature-registry.yml
   - Version mismatch? Check default in OPENSHIFT_VERSION param
3. **Fix in new commit** (don't amend, as per CLAUDE.md)
4. **Re-test** before merging to main

---

## Success Criteria

✅ All phases complete
✅ Smoke tests pass (local day1-basic + day1-security)
✅ Jenkins UI shows new params, hides old ones
✅ One full RC6 scenario run succeeds via Jenkins
✅ Feature validation no longer appears as separate stage
✅ Provisioning call uses `--scenario` syntax
✅ Zero changes to deletion, upgrade, or cleanup logic

---

## Timeline Estimate

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Parameter definition | 10 min |
| 2 | Remove validation stage | 10 min |
| 3 | Update provisioning command | 20 min |
| 4 | Clean environment blocks | 15 min |
| 5 | Update verify stage condition | 10 min |
| 6 | Add/Delete machinepool (no-op) | 5 min |
| 7 | Local smoke test | 30 min |
| 8 | Jenkins job update | 5 min |
| **Total** | | **~105 min** |

**Realistic:** 80-90 min if no blockers

---

## Files Modified

- `Jenkinsfile` (main changes, ~200 lines affected)

## Files NOT Modified

- Test suites, playbooks, feature registry, run-test-suite.py (all unchanged)

---

## Why This Works

1. **Scenario is the source of truth** — feature list, stage sequence, defaults all live in `feature-registry.yml`
2. **Jenkins is the UI** — users pick scenario from dropdown, no manual variable typing
3. **CLI flexibility preserved** — advanced users still run `--feature` locally if needed
4. **Zero breaking changes** — auth/cred params unchanged, test flow control unchanged
5. **Cleaner audit trail** — Jenkins history shows "scenario=day1-basic" instead of cryptic feature strings

