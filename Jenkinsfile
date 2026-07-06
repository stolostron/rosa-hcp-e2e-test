
@Library('ci-shared-lib') _

// ============================================================================
// CAPI/CAPA Test Pipeline - E2E ROSA HCP Testing
// ============================================================================
// Pipeline Flow:
//   1. Configure MCE Environment (suite 10) - Disable HyperShift, enable CAPI/CAPA
//   2. Validate Feature Flags (dry-run) - Only runs if CLUSTER_FEATURES is set, fails fast on bad input
//   3. Provision ROSA HCP Cluster (suite 20) - Only runs if configuration passes
//   4. Verify Feature Flags (suite 21) - Only runs if provisioning passes AND CLUSTER_FEATURES is set
//   5. Add ROSA MachinePool (suite 27) - Only runs if provisioning passes
//   6. Delete ROSA MachinePool (suite 28) - Only runs if add ROSA machinepool passes
//   7. Upgrade ROSA Control Plane (suite 25) - Only runs if provisioning passes (optional)
//   8. Upgrade ROSA Machine Pool (suite 26) - Only runs if CP upgrade passes (optional)
//   9. Delete ROSA HCP Cluster (suite 30) - Only runs if provisioning passes (optional)
//  10. Restore HyperShift (suite 41) - Runs if RESTORE_HYPERSHIFT=true (default), re-enables HyperShift
//
// HyperShift State Management:
//   Suite 10 automatically disables HyperShift and enables CAPI/CAPA.
//   By default, suite 41 restores HyperShift after testing. Set
//   RESTORE_HYPERSHIFT=false to leave CAPI/CAPA enabled for further testing.
//
// Test Suites:
//   10-configure-mce-environment             - Disable HyperShift, enable CAPI/CAPA (RHACM4K-61722)
//   20-rosa-hcp-provision                    - Provision ROSA HCP cluster (runs if 10 passes)
//   21-verify-feature-flags                  - Verify features applied to cluster (runs if 20 passes + features set)
//   27-rosa-hcp-add-machinepool              - Add a ROSA MachinePool (runs if 20 passes)
//   28-rosa-hcp-delete-machinepool           - Delete the ROSA MachinePool (runs if 27 passes)
//   25-rosa-hcp-upgrade-control-plane        - Upgrade control plane (runs if 20 passes, optional)
//   26-rosa-hcp-upgrade-machine-pool         - Upgrade machine pool (runs if 25 passes, optional)
//   30-rosa-hcp-delete                       - Delete ROSA HCP cluster (runs if 20 passes, optional)
//   41-disable-capi-enable-hypershift        - Restore HyperShift (runs if RESTORE_HYPERSHIFT=true)
//   05-verify-mce-environment                - Verify MCE environment (manual/separate)
//
// Credentials Required:
//   Parameters (passed when running job):
//   - OCP_HUB_API_URL           : OpenShift cluster API URL
//   - OCP_HUB_CLUSTER_USER      : OpenShift username (default: kubeadmin)
//   - OCP_HUB_CLUSTER_PASSWORD  : OpenShift password
//   - OCM_CLIENT_ID             : OCM client ID (optional, uses vault if not provided)
//   - OCM_CLIENT_SECRET         : OCM client secret (optional, uses vault if not provided)
//   - MCE_NAMESPACE             : MCE namespace (default: multicluster-engine)
//   - TEST_GIT_BRANCH           : Git branch to test (default: main)
//
//   Jenkins Credentials (configured in Jenkins):
//   - CAPI_AWS_ACCESS_KEY_ID    : AWS access key
//   - CAPI_AWS_SECRET_ACCESS_KEY: AWS secret key
//   - CAPI_AWS_ACCOUNT_ID       : AWS account ID
//   - CAPI_OCM_CLIENT_ID        : OCM client ID for ROSA provisioning
//   - CAPI_OCM_CLIENT_SECRET    : OCM client secret for ROSA provisioning
//
// Pipeline Behavior:
//   - Stage 1 (Configure): If fails → skips to Restore HyperShift stage
//   - Stage 2 (Validate Features): Only runs if CLUSTER_FEATURES is set; validates input only (no cluster connection)
//   - Stage 3 (Provision): Only runs if Stage 1 succeeds (and Stage 2 if features set)
//   - Stage 4 (Verify Features): Only runs if Stage 3 succeeds AND CLUSTER_FEATURES is set
//   - Stage 5 (Add ROSA MachinePool): Only runs if Stage 3 succeeds
//   - Stage 6 (Delete ROSA MachinePool): Only runs if Stage 5 succeeds
//   - Stage 7 (Upgrade ROSA CP): Only runs if Stage 3 succeeds AND RUN_UPGRADE_TESTS=true
//   - Stage 8 (Upgrade ROSA MP): Only runs if Stage 7 succeeds AND RUN_UPGRADE_TESTS=true
//   - Stage 9 (Delete): Only runs if provisioning succeeded AND CLEANUP_AFTER_TEST=true (runs even if upgrades fail)
//   - Stage 10 (Restore HyperShift): Runs if RESTORE_HYPERSHIFT=true (default) — disables CAPI/CAPA, re-enables HyperShift
//   - Stage 11 (Archive): Archives all test results as JUnit XML for Jenkins reporting
//
// Test Results:
//   - JUnit XML: test-results/**/*.xml (only format generated)
// ============================================================================

pipeline {
    options {
        // This rotates the logs every month
        buildDiscarder(logRotator(daysToKeepStr: '30'))
        // This stops the automatic, failing checkout
        skipDefaultCheckout()
    }
    agent {
        kubernetes {
            defaultContainer 'capa-container'
            yamlFile 'picsAgentPod_capa.yaml'
            // ITUP Prod
            cloud 'remote-ocp-cluster-itup-prod'
            // ITUP PreProd
            // cloud 'remote-ocp-cluster-itup-pre-prod'
        }
    }

    environment {
        CI = 'true'
        // CAPI_AWS_ROLE_ARN = "arn:aws:iam::xxxxxxxx:role/capi-role"
        CAPI_AWS_ACCESS_KEY_ID = credentials('CAPI_AWS_ACCESS_KEY_ID')
        CAPI_AWS_SECRET_ACCESS_KEY = credentials('CAPI_AWS_SECRET_ACCESS_KEY')
    }
    parameters {
        string(name:'OCP_HUB_API_URL', defaultValue: '', description: 'Hub OCP API url')
        string(name:'OCP_HUB_CLUSTER_USER', defaultValue: 'kubeadmin', description: 'Hub OCP username')
        password(name:'OCP_HUB_CLUSTER_PASSWORD', defaultValue: '', description: 'Hub cluster password')
        string(name:'MCE_NAMESPACE', defaultValue: 'multicluster-engine', description: 'The Namespace where MCE is installed')
        string(name:'OCM_CLIENT_ID', defaultValue: '', description: 'OCM client ID for ROSA provisioning')
        password(name:'OCM_CLIENT_SECRET', defaultValue: '', description: 'OCM client secret for ROSA provisioning')
        string(name:'TEST_GIT_BRANCH', defaultValue: 'main', description: 'Git branch to test (for reference/documentation)')
        string(name:'NAME_PREFIX', defaultValue: 'jnk', description: 'Cluster name prefix (creates {prefix}-rosa-hcp)')
        string(name:'CLUSTER_FEATURES', defaultValue: '', description: 'Comma-separated cluster features (e.g., no-cni,external-oidc,autoscaler). Run --list-features to see options.')
        string(name:'EXTRA_FEATURE_VARS', defaultValue: '', description: 'Additional feature vars as key=value pairs separated by spaces (e.g., root_volume_size=500 user_agent=my-agent)')
        string(name:'ETCD_KMS_ARN', defaultValue: '', description: 'AWS KMS ARN for etcd encryption (required when CLUSTER_FEATURES includes etcd-kms)')
        booleanParam(name:'RUN_UPGRADE_TESTS', defaultValue: false, description: 'Run control plane and machine pool upgrade tests after provisioning')
        booleanParam(name:'CLEANUP_AFTER_TEST', defaultValue: true, description: 'Delete cluster after successful provisioning (E2E test)')
        booleanParam(name:'RESTORE_HYPERSHIFT', defaultValue: true, description: 'Restore HyperShift and disable CAPI/CAPA after test (uncheck to leave CAPI enabled)')
    }
    stages {
        stage('Clone the ROSA HCP E2E Test Repository') {
            steps {
                retry(count: 3) {
                    script{
                        def repo = "stolostron/rosa-hcp-e2e-test.git"
                        def git_branch = params.TEST_GIT_BRANCH
                        withCredentials([string(credentialsId: 'vincent-github-token', variable: 'GITHUB_TOKEN')]) {
                            sh '''
                                rm -rf rosa-hcp-e2e-test

                                # Configure Git to use the token for this command only via a secure header.
                                git -c http.https://github.com/.extraheader="AUTHORIZATION: basic $(echo -n x-oauth-basic:${GITHUB_TOKEN} | base64)" \
                                    -c http.sslVerify=false \
                                    clone \
                                    -b "''' + git_branch + '''" \
                                    "https://github.com/''' + repo + '''" \
                                    rosa-hcp-e2e-test/
                            '''
                        }
                    }
                }
            }
        }
        stage('Install Python Dependencies') {
            steps {
                sh '''
                    # Install boto3 for AI agent AWS remediation (CloudFormation cleanup)
                    pip3 install --user boto3 2>/dev/null || pip install --user boto3 2>/dev/null || echo "WARNING: Could not install boto3 — agent AWS remediation will be limited"
                '''
            }
        }
        stage ('Verify OCP Credentials') {
            when {
                expression {
                    return (params.OCP_HUB_API_URL == '' || params.OCP_HUB_CLUSTER_PASSWORD == '')
                }
            }
            steps {
                error ('OCP_HUB_API_URL, OCP_HUB_CLUSTER_PASSWORD must be set to run the pipeline!')
            }
        }
        stage('Configure CAPI/CAPA Environment') {
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
            }
            steps {
                script {
                    try {
                        withCredentials([
                            string(credentialsId: 'CAPI_AWS_ACCESS_KEY_ID', variable: 'AWS_ACCESS_KEY_ID'),
                            string(credentialsId: 'CAPI_AWS_SECRET_ACCESS_KEY', variable: 'AWS_SECRET_ACCESS_KEY'),
                            string(credentialsId: 'CAPI_AWS_ACCOUNT_ID', variable: 'AWS_ACCOUNT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_ID', variable: 'OCM_CLIENT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_SECRET', variable: 'OCM_CLIENT_SECRET')
                        ]) {
                            sh '''
                                cd rosa-hcp-e2e-test
                                # Execute the CAPI/CAPA configuration test suite (RHACM4K-61722) with maximum verbosity
                                # Pass all credentials and cluster info as Ansible extra vars (UPPERCASE names match playbook expectations)
                                # AI agents enabled for autonomous issue detection and remediation
                                ./run-test-suite.py 10-configure-mce-environment --format junit -v --ai-agent \
                                  -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                                  -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                                  -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                                  -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}"
                            '''
                        }
                        // Archive results from both old and new test systems, including AI agent logs
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/results/**/*.xml, rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'CAPI Configuration Tests failed ... Marking build as FAILURE'
                        currentBuild.result = 'FAILURE'
                    }
                }
            }
        }
        stage('Validate Feature Flags') {
            when {
                allOf {
                    expression { currentBuild.result != 'FAILURE' }
                    expression { params.CLUSTER_FEATURES != '' }
                }
            }
            environment {
                CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
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
                            for feature in $(echo "${CLUSTER_FEATURES}" | tr ',' ' '); do
                                FEATURE_FLAGS="${FEATURE_FLAGS} --feature ${feature}"
                            done
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
                            # Validate feature names, version compatibility, dependencies, and
                            # required inputs — no cluster connection needed, exits before ansible
                            ./run-test-suite.py 20-rosa-hcp-provision --validate-only ${FEATURE_FLAGS} \
                              ${EXTRA_VARS}
                        '''
                        echo "Feature validation passed for: ${CLUSTER_FEATURES}"
                    }
                    catch (ex) {
                        echo "Feature validation FAILED for: ${CLUSTER_FEATURES}"
                        echo 'Check feature names with: ./run-test-suite.py --list-features'
                        currentBuild.result = 'FAILURE'
                    }
                }
            }
        }
        stage('Provision a ROSA HCP Cluster') {
            when {
                expression { currentBuild.result != 'FAILURE' }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
                CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
                EXTRA_FEATURE_VARS = "${params.EXTRA_FEATURE_VARS}"
                ETCD_KMS_ARN = "${params.ETCD_KMS_ARN}"
            }
            steps {
                script {
                    try {
                        withCredentials([
                            string(credentialsId: 'CAPI_AWS_ACCESS_KEY_ID', variable: 'AWS_ACCESS_KEY_ID'),
                            string(credentialsId: 'CAPI_AWS_SECRET_ACCESS_KEY', variable: 'AWS_SECRET_ACCESS_KEY'),
                            string(credentialsId: 'CAPI_AWS_ACCOUNT_ID', variable: 'AWS_ACCOUNT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_ID', variable: 'OCM_CLIENT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_SECRET', variable: 'OCM_CLIENT_SECRET')
                        ]) {
                            sh '''
                                cd rosa-hcp-e2e-test
                                # Build feature flags from CLUSTER_FEATURES parameter
                                FEATURE_FLAGS=""
                                if [ -n "${CLUSTER_FEATURES}" ]; then
                                    for feature in $(echo "${CLUSTER_FEATURES}" | tr ',' ' '); do
                                        FEATURE_FLAGS="${FEATURE_FLAGS} --feature ${feature}"
                                    done
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
                                # Pass Jenkins parameters and credentials as Ansible extra vars
                                # AI agents enabled for autonomous issue detection and remediation
                                ./run-test-suite.py 20-rosa-hcp-provision --format junit -v --ai-agent ${FEATURE_FLAGS} \
                                  -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                                  -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                                  -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                                  -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
                                  -e AWS_REGION="us-west-2" \
                                  -e name_prefix="${NAME_PREFIX}" \
                                  ${EXTRA_VARS}
                            '''
                        }
                        // Archive provisioning test results, including AI agent logs
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
        stage('Verify Feature Flags') {
            when {
                allOf {
                    expression { currentBuild.result != 'FAILURE' }
                    expression { params.CLUSTER_FEATURES != '' }
                }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
                CLUSTER_FEATURES = "${params.CLUSTER_FEATURES}"
            }
            steps {
                script {
                    try {
                        sh '''
                            cd rosa-hcp-e2e-test
                            # Build feature flags so requested_features flows to the verify playbook
                            # (CLUSTER_FEATURES guaranteed non-empty by stage when guard)
                            FEATURE_FLAGS=""
                            for feature in $(echo "${CLUSTER_FEATURES}" | tr ',' ' '); do
                                FEATURE_FLAGS="${FEATURE_FLAGS} --feature ${feature}"
                            done
                            ./run-test-suite.py 21-verify-feature-flags --format junit -v --ai-agent ${FEATURE_FLAGS} \
                              -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                              -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                              -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                              -e cluster_name="${NAME_PREFIX}-rosa-hcp"
                        '''
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'Feature flag verification failed — features may not have been applied correctly'
                        currentBuild.result = 'UNSTABLE'
                    }
                }
            }
        }
        stage('Add a ROSA MachinePool') {
            when {
                expression { currentBuild.result != 'FAILURE' }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
            }
            steps {
                script {
                    try {
                        sh '''
                            cd rosa-hcp-e2e-test
                            ./run-test-suite.py 27-rosa-hcp-add-machinepool --format junit -v --ai-agent \
                              -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                              -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                              -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                              -e cluster_name="${NAME_PREFIX}-rosa-hcp" \
                              -e pool_name="${NAME_PREFIX}-mp"
                        '''
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'Add ROSA MachinePool failed'
                        currentBuild.result = 'FAILURE'
                    }
                }
            }
        }
        stage('Delete the ROSA MachinePool') {
            when {
                expression { currentBuild.result != 'FAILURE' }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
            }
            steps {
                script {
                    try {
                        sh '''
                            cd rosa-hcp-e2e-test
                            ./run-test-suite.py 28-rosa-hcp-delete-machinepool --format junit -v --ai-agent \
                              -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                              -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                              -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                              -e cluster_name="${NAME_PREFIX}-rosa-hcp" \
                              -e pool_name="${NAME_PREFIX}-mp"
                        '''
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'Delete ROSA MachinePool failed'
                        currentBuild.result = 'UNSTABLE'
                    }
                }
            }
        }
        stage('Upgrade ROSA Control Plane') {
            when {
                allOf {
                    expression { currentBuild.result != 'FAILURE' }
                    expression { params.RUN_UPGRADE_TESTS == true }
                }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
                UPGRADE_CLUSTER_NAME = "${params.NAME_PREFIX}-rosa-hcp"
            }
            steps {
                script {
                    try {
                        withCredentials([
                            string(credentialsId: 'CAPI_AWS_ACCESS_KEY_ID', variable: 'AWS_ACCESS_KEY_ID'),
                            string(credentialsId: 'CAPI_AWS_SECRET_ACCESS_KEY', variable: 'AWS_SECRET_ACCESS_KEY'),
                            string(credentialsId: 'CAPI_AWS_ACCOUNT_ID', variable: 'AWS_ACCOUNT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_ID', variable: 'OCM_CLIENT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_SECRET', variable: 'OCM_CLIENT_SECRET')
                        ]) {
                            timeout(time: 90, unit: 'MINUTES') {
                                sh '''
                                    cd rosa-hcp-e2e-test
                                    ./run-test-suite.py 25-rosa-hcp-upgrade-control-plane --format junit -v --ai-agent \
                                      -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                                      -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                                      -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                                      -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
                                      -e AWS_REGION="us-west-2" \
                                      -e cluster_name="${UPGRADE_CLUSTER_NAME}"
                                '''
                            }
                        }
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'ROSA Control Plane Upgrade failed'
                        currentBuild.result = 'FAILURE'
                    }
                }
            }
        }
        stage('Upgrade ROSA Machine Pool') {
            when {
                allOf {
                    expression { currentBuild.result != 'FAILURE' }
                    expression { params.RUN_UPGRADE_TESTS == true }
                }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
                UPGRADE_CLUSTER_NAME = "${params.NAME_PREFIX}-rosa-hcp"
            }
            steps {
                script {
                    try {
                        withCredentials([
                            string(credentialsId: 'CAPI_AWS_ACCESS_KEY_ID', variable: 'AWS_ACCESS_KEY_ID'),
                            string(credentialsId: 'CAPI_AWS_SECRET_ACCESS_KEY', variable: 'AWS_SECRET_ACCESS_KEY'),
                            string(credentialsId: 'CAPI_AWS_ACCOUNT_ID', variable: 'AWS_ACCOUNT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_ID', variable: 'OCM_CLIENT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_SECRET', variable: 'OCM_CLIENT_SECRET')
                        ]) {
                            timeout(time: 180, unit: 'MINUTES') {
                                sh '''
                                    cd rosa-hcp-e2e-test
                                    ./run-test-suite.py 26-rosa-hcp-upgrade-machine-pool --format junit -v --ai-agent \
                                      -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                                      -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                                      -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                                      -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
                                      -e AWS_REGION="us-west-2" \
                                      -e cluster_name="${UPGRADE_CLUSTER_NAME}"
                                '''
                            }
                        }
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'ROSA Machine Pool Upgrade failed'
                        currentBuild.result = 'FAILURE'
                    }
                }
            }
        }
        stage('Delete the ROSA HCP Cluster') {
            when {
                allOf {
                    expression { env.PROVISION_PASSED == 'true' }
                    expression { params.CLEANUP_AFTER_TEST == true }
                }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
            }
            steps {
                script {
                    try {
                        withCredentials([
                            string(credentialsId: 'CAPI_AWS_ACCESS_KEY_ID', variable: 'AWS_ACCESS_KEY_ID'),
                            string(credentialsId: 'CAPI_AWS_SECRET_ACCESS_KEY', variable: 'AWS_SECRET_ACCESS_KEY'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_ID', variable: 'OCM_CLIENT_ID'),
                            string(credentialsId: 'CAPI_OCM_CLIENT_SECRET', variable: 'OCM_CLIENT_SECRET')
                        ]) {
                            // Add timeout for deletion (can take 30-50 minutes)
                            timeout(time: 60, unit: 'MINUTES') {
                                sh '''
                                    cd rosa-hcp-e2e-test
                                    # Execute the ROSA HCP deletion test suite
                                    # Pass all required credentials and parameters (same as provisioning)
                                    # AI agents enabled for autonomous issue detection and remediation
                                    ./run-test-suite.py 30-rosa-hcp-delete --format junit -v --ai-agent \
                                      -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                                      -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                                      -e MCE_NAMESPACE="${MCE_NAMESPACE}" \
                                      -e AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID}" \
                                      -e AWS_REGION="us-west-2" \
                                      -e name_prefix="${NAME_PREFIX}"
                                '''
                            }
                        }
                        // Archive deletion test results, including AI agent logs
                        archiveArtifacts artifacts: 'rosa-hcp-e2e-test/test-results/**/*, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false, fingerprint: true
                    }
                    catch (ex) {
                        echo 'ROSA HCP Deletion Tests failed or timed out'
                        echo 'WARNING: Cluster may still exist and require manual cleanup'
                        currentBuild.result = 'UNSTABLE'
                    }
                }
            }
        }
        stage('Restore HyperShift') {
            when {
                expression { params.RESTORE_HYPERSHIFT == true }
            }
            environment {
                OCP_HUB_API_URL = "${params.OCP_HUB_API_URL}"
                OCP_HUB_CLUSTER_USER = "${params.OCP_HUB_CLUSTER_USER}"
                OCP_HUB_CLUSTER_PASSWORD = "${params.OCP_HUB_CLUSTER_PASSWORD}"
                MCE_NAMESPACE = "${params.MCE_NAMESPACE}"
            }
            steps {
                script {
                    try {
                        echo 'Restoring HyperShift: disabling CAPI/CAPA and re-enabling HyperShift components'
                        sh '''
                            cd rosa-hcp-e2e-test
                            ./run-test-suite.py 41-disable-capi-enable-hypershift --format junit -v --ai-agent \
                              -e OCP_HUB_API_URL="${OCP_HUB_API_URL}" \
                              -e OCP_HUB_CLUSTER_USER="${OCP_HUB_CLUSTER_USER}" \
                              -e MCE_NAMESPACE="${MCE_NAMESPACE}"
                        '''
                    }
                    catch (ex) {
                        echo "WARNING: Failed to restore HyperShift — cluster may need manual intervention"
                        echo "Run manually: ./run-test-suite.py 41-disable-capi-enable-hypershift"
                    }
                }
            }
        }
        stage('Archive the CAPI/CAPA Artifacts') {
            steps {
                script {
                   // Archive artifacts from both old (results/) and new (test-results/) systems, including AI agent logs
                   archiveArtifacts artifacts: 'rosa-hcp-e2e-test/results/**/*.xml, rosa-hcp-e2e-test/test-results/**/*.xml, rosa-hcp-e2e-test/agents/knowledge_base/intervention_log.json', allowEmptyArchive: true, followSymlinks: false

                   // Publish JUnit test results from both systems
                   junit allowEmptyResults: true, testResults: 'rosa-hcp-e2e-test/results/**/*.xml, rosa-hcp-e2e-test/test-results/**/*.xml'
                }
            }
        }
    }
}
