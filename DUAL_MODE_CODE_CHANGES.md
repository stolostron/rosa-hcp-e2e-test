# Dual-Mode Jenkinsfile Code Changes

## Change 1: Parameters Block (Lines 96–113)

### BEFORE
```groovy
parameters {
    string(name:'OCP_HUB_API_URL', defaultValue: '', description: 'Hub OCP API url')
    string(name:'OCP_HUB_CLUSTER_USER', defaultValue: 'kubeadmin', description: 'Hub OCP username')
    password(name:'OCP_HUB_CLUSTER_PASSWORD', defaultValue: '', description: 'Hub cluster password')
    string(name:'MCE_NAMESPACE', defaultValue: 'multicluster-engine', description: 'The Namespace where MCE is installed')
    string(name:'OCM_API_URL', defaultValue: 'https://api.stage.openshift.com', description: 'OCM API URL (e.g. https://api.openshift.com or https://api.stage.openshift.com)')
    string(name:'OCM_CLIENT_ID', defaultValue: '', description: 'OCM client ID for ROSA provisioning')
    password(name:'OCM_CLIENT_SECRET', defaultValue: '', description: 'OCM client secret for ROSA provisioning')
    string(name:'TEST_GIT_BRANCH', defaultValue: 'main', description: 'Git branch to test (for reference/documentation)')
    string(name:'NAME_PREFIX', defaultValue: 'jnk', description: 'Cluster name prefix (creates {prefix}-rosa-hcp)')
    string(name:'CLUSTER_FEATURES', defaultValue: '', description: 'Comma-separated cluster features (e.g., no-cni,external-oidc,autoscaler). Run --list-features to see options.')
    string(name:'FEATURE_GROUP', defaultValue: '', description: 'Feature group preset (e.g., day1-basic, day1-combo, day1-security, day1-networking). Run --list-groups to see options. Can be combined with CLUSTER_FEATURES.')
    string(name:'EXTRA_FEATURE_VARS', defaultValue: '', description: 'Additional feature vars as key=value pairs separated by spaces (e.g., root_volume_size=500)')
    string(name:'ETCD_KMS_ARN', defaultValue: '', description: 'AWS KMS ARN for etcd encryption (required when CLUSTER_FEATURES includes etcd-kms)')
    booleanParam(name:'RUN_UPGRADE_TESTS', defaultValue: false, description: 'Run control plane and machine pool upgrade tests after provisioning')
    booleanParam(name:'CLEANUP_AFTER_TEST', defaultValue: true, description: 'Delete cluster after successful provisioning (E2E test)')
    booleanParam(name:'RESTORE_HYPERSHIFT', defaultValue: true, description: 'Restore HyperShift and disable CAPI/CAPA after test (uncheck to leave CAPI enabled)')
}
```

### AFTER
```groovy
parameters {
    // ========== Environment & Auth ==========
    string(name:'OCP_HUB_API_URL', defaultValue: '', description: 'Hub OCP API url')
    string(name:'OCP_HUB_CLUSTER_USER', defaultValue: 'kubeadmin', description: 'Hub OCP username')
    password(name:'OCP_HUB_CLUSTER_PASSWORD', defaultValue: '', description: 'Hub cluster password')
    string(name:'MCE_NAMESPACE', defaultValue: 'multicluster-engine', description: 'The Namespace where MCE is installed')
    string(name:'OCM_API_URL', defaultValue: 'https://api.stage.openshift.com', description: 'OCM API URL (e.g. https://api.openshift.com or https://api.stage.openshift.com)')
    string(name:'OCM_CLIENT_ID', defaultValue: '', description: 'OCM client ID for ROSA provisioning')
    password(name:'OCM_CLIENT_SECRET', defaultValue: '', description: 'OCM client secret for ROSA provisioning')
    string(name:'TEST_GIT_BRANCH', defaultValue: 'main', description: 'Git branch to test (for reference/documentation)')
    string(name:'NAME_PREFIX', defaultValue: 'jnk', description: 'Cluster name prefix (creates {prefix}-rosa-hcp)')

    // ========== Test Mode Selection ==========
    choice(name: 'TEST_MODE', choices: ['scenario', 'custom-features'], defaultValue: 'scenario',
           description: 'Scenario presets (recommended) or custom feature combinations (advanced users)')

    // ========== Scenario Mode ==========
    choice(name: 'TEST_SCENARIO', choices: [
        'day1-basic',
        'day1-combo',
        'day1-networking',
        'day1-security',
        'day2-machinepool'
    ], description: 'Test scenario preset (active only if TEST_MODE=scenario)')

    // ========== Common Vars (both modes) ==========
    string(name: 'OPENSHIFT_VERSION', defaultValue: '5.0.0-rc.6',
           description: 'OpenShift version (e.g., 5.0.0-rc.6, 4.22.0)')

    string(name: 'CHANNEL_GROUP', defaultValue: 'candidate',
           description: 'Channel group (stable, fast, candidate)')

    string(name: 'EXTRA_VARS', defaultValue: '',
           description: 'Additional Ansible vars as key=value pairs (e.g., root_volume_size=500 etcd_encryption_kms_arn=arn:aws:...)')

    // ========== Custom Features Mode (backward compatible) ==========
    string(name:'CLUSTER_FEATURES', defaultValue: '', description: '[CUSTOM MODE] Comma-separated cluster features (e.g., no-cni,external-oidc,autoscaler). Run --list-features to see options.')
    string(name:'FEATURE_GROUP', defaultValue: '', description: '[CUSTOM MODE] Feature group preset (e.g., day1-basic, day1-combo, day1-security, day1-networking). Run --list-groups to see options. Can be combined with CLUSTER_FEATURES.')
    string(name:'EXTRA_FEATURE_VARS', defaultValue: '', description: '[CUSTOM MODE] Additional feature vars as key=value pairs separated by spaces (e.g., root_volume_size=500)')
    string(name:'ETCD_KMS_ARN', defaultValue: '', description: '[CUSTOM MODE] AWS KMS ARN for etcd encryption (required when CLUSTER_FEATURES includes etcd-kms)')

    // ========== Test Control Flow ==========
    booleanParam(name:'RUN_UPGRADE_TESTS', defaultValue: false, description: 'Run control plane and machine pool upgrade tests after provisioning')
    booleanParam(name:'CLEANUP_AFTER_TEST', defaultValue: true, description: 'Delete cluster after successful provisioning (E2E test)')
    booleanParam(name:'RESTORE_HYPERSHIFT', defaultValue: true, description: 'Restore HyperShift and disable CAPI/CAPA after test (uncheck to leave CAPI enabled)')
}
```

---

## Change 2: Validate Feature Flags Stage (Lines 196–250)

### BEFORE
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
            // ... validation logic ...
        }
    }
}
```

### AFTER
```groovy
stage ('Validate Feature Flags') {
    when {
        allOf {
            expression { currentBuild.result != 'FAILURE' }
            expression { params.TEST_MODE == 'custom-features' }
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
            // ... validation logic ... (unchanged)
        }
    }
}
```

**Key change:** Add `expression { params.TEST_MODE == 'custom-features' }` to the `when` condition.

---

## Change 3: Provision Stage (Lines 251–322)

### BEFORE
```groovy
stage('Provision a ROSA HCP Cluster') {
    when {
        expression { currentBuild.result != 'FAILURE' }
    }
    environment {
        OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
        OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
        MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
        CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
        FEATURE_GROUP = "${params.FEATURE_GROUP}"
        EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
        ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
    }
    steps {
        script {
            try {
                withCredentials([...]) {
                    sh '''
                        cd rosa-hcp-e2e-test
                        # Build feature flags from CLUSTER_FEATURES parameter
                        FEATURE_FLAGS=""
                        if [ -n "${CLUSTER_FEATURES}" ]; then
                            for feature in $(echo "${CLUSTER_FEATURES}" | tr ',' ' '); do
                                FEATURE_FLAGS="${FEATURE_FLAGS} --feature ${feature}"
                            done
                        fi
                        # Build feature group flag from FEATURE_GROUP parameter
                        GROUP_FLAG=""
                        if [ -n "${FEATURE_GROUP}" ]; then
                            GROUP_FLAG="--feature-group ${FEATURE_GROUP}"
                        fi
                        # Build extra vars from EXTRA_FEATURE_VARS and ETCD_KMS_ARN
                        EXTRA_VARS=""
                        if [ -n "${ETCD_KMS_ARN}" ]; then
                            EXTRA_VARS="${EXTRA_VARS} -e etcd_encryption_kms_arn=${ETCD_KMS_ARN}"
                        fi
                        if [ -n "${EXTRA_FEATURE_VARS}" ]; then
                            for var in ${EXTRA_FEATURE_VARS}; do
                                EXTRA_VARS="${EXTRA_VARS} -e \"${var}\""
                            done
                        fi
                        # Execute the ROSA HCP provisioning test suite with maximum verbosity
                        ./run-test-suite.py 20-rosa-hcp-provision --format junit -v --ai-agent ${FEATURE_FLAGS} ${GROUP_FLAG} \
                          -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                          -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                          -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                          -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
                          -e AWS_REGION="us-west-2" \
                          -e name_prefix="${NAME_PREFIX}" \
                          -e OCM_API_URL="${OCM_API_URL}" \
                          ${EXTRA_VARS}
                    '''
                }
                // Archive provisioning test results
                archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/test-results/**/*.html, rosa-hcp-e2e-test/test-results/**/*.json, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                env.PROVISION_PASSED = 'true'
            }
            catch (ex) {
                echo 'ROSA HCP Provisioning Tests failed'
                currentBuild.result = 'FAILURE'
            }
        }
    }
}
```

### AFTER
```groovy
stage('Provision a ROSA HCP Cluster') {
    when {
        expression { currentBuild.result != 'FAILURE' }
    }
    environment {
        OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
        OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
        MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
        TEST_MODE = "${params.TEST_MODE}"
        TEST_SCENARIO = "${params.TEST_SCENARIO}"
        OPENSHIFT_VERSION = "${params.OPENSHIFT_VERSION}"
        CHANNEL_GROUP = "${params.CHANNEL_GROUP}"
        CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
        FEATURE_GROUP = "${params.FEATURE_GROUP}"
        EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
        ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
    }
    steps {
        script {
            try {
                withCredentials([...]) {
                    sh '''
                        cd rosa-hcp-e2e-test
                        
                        # Dual-mode: route based on TEST_MODE
                        if [ "${TEST_MODE}" = "scenario" ]; then
                            # ========== SCENARIO MODE ==========
                            ./run-test-suite.py --scenario "${TEST_SCENARIO}" --format junit -v --ai-agent \
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
                        else
                            # ========== CUSTOM FEATURES MODE ==========
                            # Build feature flags from CLUSTER_FEATURES parameter
                            FEATURE_FLAGS=""
                            if [ -n "${CLUSTER_FEATURES}" ]; then
                                for feature in $(echo "${CLUSTER_FEATURES}" | tr ',' ' '); do
                                    FEATURE_FLAGS="${FEATURE_FLAGS} --feature ${feature}"
                                done
                            fi
                            # Build feature group flag from FEATURE_GROUP parameter
                            GROUP_FLAG=""
                            if [ -n "${FEATURE_GROUP}" ]; then
                                GROUP_FLAG="--feature-group ${FEATURE_GROUP}"
                            fi
                            # Build extra vars from EXTRA_FEATURE_VARS and ETCD_KMS_ARN
                            EXTRA_VARS_CUSTOM=""
                            if [ -n "${ETCD_KMS_ARN}" ]; then
                                EXTRA_VARS_CUSTOM="${EXTRA_VARS_CUSTOM} -e etcd_encryption_kms_arn=${ETCD_KMS_ARN}"
                            fi
                            if [ -n "${EXTRA_FEATURE_VARS}" ]; then
                                for var in ${EXTRA_FEATURE_VARS}; do
                                    EXTRA_VARS_CUSTOM="${EXTRA_VARS_CUSTOM} -e \"${var}\""
                                done
                            fi
                            
                            ./run-test-suite.py 20-rosa-hcp-provision --format junit -v --ai-agent ${FEATURE_FLAGS} ${GROUP_FLAG} \
                              -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                              -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                              -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                              -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
                              -e AWS_REGION="us-west-2" \
                              -e name_prefix="${NAME_PREFIX}" \
                              -e OCM_API_URL="${OCM_API_URL}" \
                              -e openshift_version="${OPENSHIFT_VERSION}" \
                              -e channel_group="${CHANNEL_GROUP}" \
                              ${EXTRA_VARS_CUSTOM}
                        fi
                    '''
                }
                // Archive provisioning test results
                archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/test-results/**/*.html, rosa-hcp-e2e-test/test-results/**/*.json, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                env.PROVISION_PASSED = 'true'
            }
            catch (ex) {
                echo 'ROSA HCP Provisioning Tests failed'
                currentBuild.result = 'FAILURE'
            }
        }
    }
}
```

**Key changes:**
- Add `if [ "${TEST_MODE}" = "scenario" ]` conditional
- Scenario branch: use `--scenario` with version/channel params
- Custom features branch: keep original feature flag logic
- Add new vars to environment block (TEST_MODE, TEST_SCENARIO, OPENSHIFT_VERSION, CHANNEL_GROUP)

---

## Change 4: Verify Feature Flags Stage (Lines 324–406)

### BEFORE
```groovy
stage('Verify Feature Flags') {
    when {
        allOf {
            expression { currentBuild.result != 'FAILURE' }
            expression { params.CLUSTER_FEATURES?.trim() || params.FEATURE_GROUP?.trim() }
        }
    }
    environment {
        OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
        OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
        MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
        CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
        FEATURE_GROUP = "${params.FEATURE_GROUP}"
        EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
        ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
    }
    steps {
        // ... verification logic ...
    }
}
```

### AFTER
```groovy
stage('Verify Feature Flags') {
    when {
        allOf {
            expression { currentBuild.result != 'FAILURE' }
            expression { 
                (params.TEST_MODE == 'scenario') || 
                (params.TEST_MODE == 'custom-features' && (params.CLUSTER_FEATURES?.trim() || params.FEATURE_GROUP?.trim()))
            }
        }
    }
    environment {
        OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
        OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
        MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
        TEST_MODE = "${params.TEST_MODE}"
        TEST_SCENARIO = "${params.TEST_SCENARIO}"
        CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
        FEATURE_GROUP = "${params.FEATURE_GROUP}"
        EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
        ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
    }
    steps {
        // ... verification logic ... (unchanged)
    }
}
```

**Key change:** Update `when` condition to run in both modes:
- Scenario mode: always runs (scenario includes it)
- Custom features mode: runs only if features are set (old behavior)

---

## Summary of Changes

| File | Lines | Change | Impact |
|------|-------|--------|--------|
| Jenkinsfile | 96–125 | Add TEST_MODE choice, TEST_SCENARIO choice, OPENSHIFT_VERSION, CHANNEL_GROUP, EXTRA_VARS params | User UI now shows both paths |
| Jenkinsfile | 196–250 | Add `TEST_MODE == 'custom-features'` to when condition | Validation only runs in custom mode |
| Jenkinsfile | 251–322 | Add if/else for scenario vs custom-features provisioning | Route to correct provisioning path |
| Jenkinsfile | 324–406 | Update when condition to include scenario mode | Verify always runs in scenario mode |

**Files NOT modified:**
- Add/Delete MachinePool stages (no changes needed, don't use features)
- Upgrade stages (no changes needed)
- Delete cluster stage (no changes needed)
- Cleanup stages (no changes needed)

---

## Usage Examples

### Scenario Mode (recommended, default)
```
TEST_MODE = scenario
TEST_SCENARIO = day1-security
OPENSHIFT_VERSION = 5.0.0-rc.6
CHANNEL_GROUP = candidate
EXTRA_VARS = etcd_encryption_kms_arn=arn:aws:kms:...
```
→ Uses `--scenario day1-security` with version/channel overrides

### Custom Features Mode (power users, backward compatible)
```
TEST_MODE = custom-features
CLUSTER_FEATURES = no-cni,external-oidc
FEATURE_GROUP = day1-networking
EXTRA_FEATURE_VARS = root_volume_size=500
ETCD_KMS_ARN = arn:aws:kms:...
OPENSHIFT_VERSION = 5.0.0-rc.6
CHANNEL_GROUP = candidate
```
→ Uses `--feature no-cni --feature external-oidc --feature-group day1-networking` (old path)
