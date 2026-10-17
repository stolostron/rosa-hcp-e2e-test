# Scenario-Based Jenkins Parameters — Complete Audit

## Current Parameters (12 total)

| Param | Type | Default | Purpose | Stage(s) Used |
|-------|------|---------|---------|----------------|
| `OCP_HUB_API_URL` | string | '' | Hub cluster API endpoint | 10, 20, 21, 27, 28, 25, 26, 30, 41 |
| `OCP_HUB_CLUSTER_USER` | string | 'kubeadmin' | Hub cluster username | 10, 20, 21, 27, 28, 25, 26, 30, 41 |
| `OCP_HUB_CLUSTER_PASSWORD` | password | '' | Hub cluster password | Required, checked in "Verify OCP Credentials" |
| `MCE_NAMESPACE` | string | 'multicluster-engine' | MCE namespace | 10, 20, 21, 27, 28, 25, 26, 30, 41 |
| `OCM_API_URL` | string | 'https://api.stage.openshift.com' | OCM API endpoint | 20 provisioning |
| `OCM_CLIENT_ID` | string | '' | OCM OAuth client ID | 20 provisioning (via Jenkins credential) |
| `OCM_CLIENT_SECRET` | password | '' | OCM OAuth secret | 20 provisioning (via Jenkins credential) |
| `TEST_GIT_BRANCH` | string | 'main' | Repo branch to test | 5 (clone stage, documentation only) |
| `NAME_PREFIX` | string | 'jnk' | Cluster name prefix | 20, 21, 27, 28, 25, 26, 30 |
| `CLUSTER_FEATURES` | string | '' | **[TO REMOVE]** Granular features | 20, 21 (feature-based path) |
| `FEATURE_GROUP` | string | '' | **[TO REMOVE]** Feature preset | 20, 21 (feature-based path) |
| `EXTRA_FEATURE_VARS` | string | '' | **[TO REMOVE]** Feature var overrides | 20, 21 (feature-based path) |
| `ETCD_KMS_ARN` | password | '' | **[TO REMOVE]** Special-case KMS ARN | 20 (feature-based path only) |
| `RUN_UPGRADE_TESTS` | boolean | false | Enable upgrade stages 25–26 | 25, 26 |
| `CLEANUP_AFTER_TEST` | boolean | true | Enable cleanup stage 30 | 30, "Best-effort Cleanup" |
| `RESTORE_HYPERSHIFT` | boolean | true | Enable HyperShift restore stage 41 | 41 |

---

## Proposed Scenario Parameters (Keep + Add)

### Keep (Environment/Auth)
- ✅ `OCP_HUB_API_URL` — hub cluster endpoint (required)
- ✅ `OCP_HUB_CLUSTER_USER` — hub cluster user (required)
- ✅ `OCP_HUB_CLUSTER_PASSWORD` — hub cluster password (required)
- ✅ `MCE_NAMESPACE` — MCE namespace (required)
- ✅ `OCM_API_URL` — OCM API endpoint (required)
- ✅ `OCM_CLIENT_ID` — OCM OAuth client ID (required, via Jenkins credential)
- ✅ `OCM_CLIENT_SECRET` — OCM OAuth secret (required, via Jenkins credential)
- ✅ `TEST_GIT_BRANCH` — repo branch (documentation, default 'main')
- ✅ `NAME_PREFIX` — cluster name prefix (required, default 'jnk')

### Remove (Feature-based)
- ❌ `CLUSTER_FEATURES` — scenarios handle this
- ❌ `FEATURE_GROUP` — scenarios handle this
- ❌ `EXTRA_FEATURE_VARS` → merge into `EXTRA_VARS`
- ❌ `ETCD_KMS_ARN` → pass via `EXTRA_VARS`

### Add (Scenario-based)
- ✅ `TEST_SCENARIO` (choice) — {day1-basic, day1-combo, day1-networking, day1-security, day2-machinepool}
- ✅ `OPENSHIFT_VERSION` (string) — default '5.0.0-rc.6'
- ✅ `CHANNEL_GROUP` (string) — default 'candidate' (for RC testing)
- ✅ `EXTRA_VARS` (string) — free-form key=value overrides (replaces `EXTRA_FEATURE_VARS`)

### Keep (Test Control Flow)
- ✅ `RUN_UPGRADE_TESTS` (boolean) — enable stages 25–26
- ✅ `CLEANUP_AFTER_TEST` (boolean) — enable stage 30
- ✅ `RESTORE_HYPERSHIFT` (boolean) — enable stage 41

---

## Final Parameter List (11 total, cleaner)

```groovy
parameters {
    // Environment & Auth (9 required)
    string(name:'OCP_HUB_API_URL', defaultValue: '', description: 'Hub OCP API url (required)')
    string(name:'OCP_HUB_CLUSTER_USER', defaultValue: 'kubeadmin', description: 'Hub OCP username')
    password(name:'OCP_HUB_CLUSTER_PASSWORD', defaultValue: '', description: 'Hub cluster password (required)')
    string(name:'MCE_NAMESPACE', defaultValue: 'multicluster-engine', description: 'MCE namespace')
    string(name:'OCM_API_URL', defaultValue: 'https://api.stage.openshift.com', description: 'OCM API URL')
    string(name:'TEST_GIT_BRANCH', defaultValue: 'main', description: 'Git branch to test')
    string(name:'NAME_PREFIX', defaultValue: 'jnk', description: 'Cluster name prefix')
    
    // Scenario Selection (3 required for scenario mode)
    choice(name: 'TEST_SCENARIO', choices: [
        'day1-basic',
        'day1-combo',
        'day1-networking',
        'day1-security',
        'day2-machinepool'
    ], description: 'Test scenario preset')
    string(name:'OPENSHIFT_VERSION', defaultValue: '5.0.0-rc.6', description: 'OpenShift version (e.g., 5.0.0-rc.6, 4.22.0)')
    string(name:'CHANNEL_GROUP', defaultValue: 'candidate', description: 'Channel group (stable, fast, candidate)')
    
    // Scenario Overrides (optional)
    string(name:'EXTRA_VARS', defaultValue: '', description: 'Additional Ansible vars (e.g., root_volume_size=500 etcd_encryption_kms_arn=arn:aws:...)')
    
    // Test Control Flow (optional)
    booleanParam(name:'RUN_UPGRADE_TESTS', defaultValue: false, description: 'Run control plane and machine pool upgrade tests')
    booleanParam(name:'CLEANUP_AFTER_TEST', defaultValue: true, description: 'Delete cluster after test')
    booleanParam(name:'RESTORE_HYPERSHIFT', defaultValue: true, description: 'Restore HyperShift after test')
}
```

---

## Validation Checklist

### Stage 10 (Configure CAPI/CAPA)
- Needs: `OCP_HUB_API_URL`, `OCP_HUB_CLUSTER_USER`, `MCE_NAMESPACE`, `AWS_ACCOUNT_ID` ✅
- Stage input: Unchanged, no feature logic

### Stage 20 (Provision)
- Needs: `OCP_HUB_API_URL`, `OCP_HUB_CLUSTER_USER`, `MCE_NAMESPACE`, `AWS_ACCOUNT_ID`, `AWS_REGION`, `name_prefix`, `OCM_API_URL`
- **Old**: `CLUSTER_FEATURES`, `FEATURE_GROUP`, `EXTRA_FEATURE_VARS`, `ETCD_KMS_ARN`
- **New**: `TEST_SCENARIO`, `OPENSHIFT_VERSION`, `CHANNEL_GROUP`, `EXTRA_VARS` ✅
- Command: `./run-test-suite.py --scenario ${TEST_SCENARIO} -e openshift_version="${OPENSHIFT_VERSION}" -e channel_group="${CHANNEL_GROUP}" ... ${EXTRA_VARS}`

### Stage 21 (Verify Feature Flags)
- **Handled by scenario's stage list** — no longer manually triggered
- Remove: Feature-based conditional logic ✅

### Stages 27, 28 (Add/Delete MachinePool)
- Needs: `OCP_HUB_API_URL`, `OCP_HUB_CLUSTER_USER`, `MCE_NAMESPACE`, `cluster_name`, `pool_name`
- Unchanged ✅

### Stages 25, 26 (Upgrade CP/MP)
- Controlled by `RUN_UPGRADE_TESTS` ✅
- Unchanged ✅

### Stage 30 (Delete)
- Controlled by `CLEANUP_AFTER_TEST` ✅
- Unchanged ✅

### Stage 41 (Restore HyperShift)
- Controlled by `RESTORE_HYPERSHIFT` ✅
- Unchanged ✅

---

## Summary

✅ **All scenario requirements covered:**
- Test selection: `TEST_SCENARIO`, `OPENSHIFT_VERSION`, `CHANNEL_GROUP`
- Overrides: `EXTRA_VARS` (supports arbitrary inputs like KMS ARNs)
- Control flow: `RUN_UPGRADE_TESTS`, `CLEANUP_AFTER_TEST`, `RESTORE_HYPERSHIFT`
- Environment: All existing auth/endpoint params

✅ **Removed complexity:**
- No `CLUSTER_FEATURES`, `FEATURE_GROUP`, `EXTRA_FEATURE_VARS`, `ETCD_KMS_ARN` clutter
- Feature validation stage simplified (dry-run only, not in provisioning path)
- Scenario stages embedded in registry, not Jenkinsfile

✅ **Backward compatibility:**
- All environment auth params unchanged
- Test flow control params unchanged
- Jenkins job can migrate cleanly without breaking existing infrastructure
