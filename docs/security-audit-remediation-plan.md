# Security Audit Remediation Plan

**Audit Date**: 2026-06-08
**Triage Date**: 2026-06-29
**Repository**: https://github.com/stolostron/rosa-hcp-e2e-test
**Audit Reference**: HCMSEC-3528
**Framework**: OWASP ASVS v5.0; OWASP K8s Top 10 2025; CIS K8s v2.0; SLSA v1.2; OpenSSF Scorecard

---

## Findings Summary

| # | Severity | Audit CVSS | Triage CVSS | Triage Disposition | Status |
|---|----------|------------|-------------|-------------------|--------|
| FIND-002 | **High** | 6.8 | **9.9** | Confirmed — rescored up | Not started |
| FIND-003 | **High** | 5.0 | **8.5** | Confirmed — rescored up (was Medium) | Not started |
| FIND-006 | **High** | 4.4 | **8.4** | Confirmed — rescored up (was Medium) | Not started |
| FIND-001 | **High** | 6.5 | **7.7** | Confirmed — rescored up | Not started |
| FIND-004 | **Medium** | 5.4 | **6.0** | Confirmed — needs manual test | Not started |
| FIND-005 | Medium | 5.0 | — | Triage dropped — intentional behavior | Not started |
| FIND-007 | Low | 3.1 | — | Triage dropped — no source location | **Done** (PR #69, merged 6/30) |
| FIND-008 | Low | 3.0 | — | Triage dropped — not actionable from this repo | Not started |
| FIND-009 | Info | 0.0 | — | Triage dropped — no source location | **Partial** (PR #69, merged 6/30) |
| STS-001 | Medium | — | — | New — proposed mitigation | Not started |

---

## FIND-002 — oc login disables TLS verification and exposes password on CLI

**Severity**: High (triage confirmed, rescored)
**Audit CVSS**: 6.8 — CVSS:3.1/AV:A/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N
**Triage CVSS**: **9.9 — CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H**
**CWE**: CWE-295, CWE-532, CWE-214
**Location**: `tasks/login_ocp.yml:42-47`, `tasks/check_environment_health.yml:22-28`
**Category**: ASVS V9.2 (TLS) / OWASP K8s K09 Broken Authentication / CIS 1.2.x
**Triage Confidence**: 8.3/10
**Triage Votes**: 3 true_positive, 0 false_positive

**Description**: The hub-cluster login task uses `oc --insecure-skip-tls-verify login -u {{ ocp_user }} -p {{ ocp_password }}`. TLS verification is unconditionally disabled, so an on-path attacker can capture cluster-admin credentials. The task lacks `no_log: true`, so at `-vvv` the plaintext password is printed to stdout.

**Triage Rescore Rationale**: Auditor's 6.8 covered only the adjacent-network MITM path. Triage found `OCP_HUB_CLUSTER_PASSWORD` is declared as a plain `string()` Jenkins parameter — not `password()`, not bound via `withCredentials` — so Jenkins applies NO masking. The unmasked console leak is the easier attack path (AV:N, not AV:A). S:C for Jenkins-to-hub-cluster scope change. 12 playbooks include this task; it executes on every scheduled run.

**Reachability**: 12 playbooks include `login_ocp.yml`. Jenkinsfile stage 'Configure CAPI/CAPA Environment' passes `OCP_HUB_CLUSTER_PASSWORD` as `-e` arg at `-vvv`.

**Remediation Steps**:
1. Remove `--insecure-skip-tls-verify` from all `oc login` invocations
2. Ship the hub CA bundle in the Jenkins agent image and pass `--certificate-authority=<path>`
3. Switch to token-based login (`oc login --token`) or use the `kubernetes.core` connection plugin with `validate_certs: true`
4. Add `no_log: true` to all login tasks

---

## FIND-003 — AWS access keys interpolated into shell task without no_log

**Severity**: High (triage rescored from Medium)
**Audit CVSS**: 5.0 — CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N
**Triage CVSS**: **8.5 — CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:L/A:N**
**CWE**: CWE-532, CWE-214
**Location**: `tasks/create_capa_manager_bootstrap_credentials.yml:7-14`, `tasks/configure-capa-environment.yml:10-12`
**Category**: OWASP K8s K03 Secrets Management / ASVS V8.1
**Triage Confidence**: 8/10
**Triage Votes**: 3 true_positive, 0 false_positive

**Description**: The CAPA bootstrap secret task builds an INI block containing `aws_access_key_id` and `aws_secret_access_key` through `base64` in a `shell:` task without `no_log: true`. At `-vvv` Ansible prints the fully-rendered command with cleartext AWS keys to the Jenkins console.

**Triage Rescore Rationale**: Auditor scored AV:L. Triage found the base64-encoded `stdout` is a transformation of the secret that bypasses Jenkins `withCredentials` exact-match masking. Console/artefacts are network-reachable to authenticated Jenkins users (AV:N). The rendered secret YAML is also written to the agent-pod filesystem and every stdout line is fed to the AI agent's `intervention_log.json`, which is archived. S:C for CI-to-AWS-account scope change.

**Reachability**: `roles/configure-capa-environment/tasks/main.yml:~87` includes this task unconditionally. Jenkinsfile stage 'Configure CAPI/CAPA Environment' runs with `-vvv` and `withCredentials CAPI_AWS_SECRET_ACCESS_KEY`.

**Remediation Steps**:
1. Add `no_log: true` to the shell and template tasks
2. Delete commented-out debug blocks that print raw keys
3. Build the secret using `kubernetes.core.k8s` with `b64encode` filter so key material never transits a shell command
4. Consider replacing static IAM keys with STS/IRSA (see STS-001)

---

## FIND-006 — Jenkins pipeline passes all secrets as CLI extra-vars at -vvv

**Severity**: High (triage rescored from Medium)
**Audit CVSS**: 4.4 — CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N
**Triage CVSS**: **8.4 — CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:N**
**CWE**: CWE-214, CWE-532
**Location**: `Jenkinsfile:174-184`, `Jenkinsfile:259-300`
**Category**: OWASP K8s K03 / ASVS V8.1
**Triage Confidence**: 8/10
**Triage Votes**: 3 true_positive, 0 false_positive

**Description**: Each pipeline stage invokes `./run-test-suite.py ... -vvv -e OCP_HUB_CLUSTER_PASSWORD=... -e AWS_SECRET_ACCESS_KEY=... -e OCM_CLIENT_SECRET=...`. Secrets appear in `/proc/<pid>/cmdline` on the shared Jenkins agent pod for the duration of multi-hour runs (timeouts reach 180 min) and in Ansible's verbose output.

**Triage Rescore Rationale**: `OCP_HUB_CLUSTER_PASSWORD` is completely unmasked (plain `string()` param). `/proc/cmdline` readable by co-tenant processes for the full run window. S:C because recovered secrets cross into AWS, OCM, and hub-cluster authorities. Agent pod image pulled from personal mutable `quay.io/vboulos/...` namespace — any process in that image shares the PID namespace. Same pattern repeats in 6+ Jenkins stages.

**Reachability**: Jenkinsfile stage 'Configure CAPI/CAPA Environment' has no `when{}` guard, runs every build. `run-test-suite.py:226-254` builds `cmd=["ansible-playbook", ..., "-vvv", "-e", f"{key}={value}"]` and `subprocess.Popen(cmd)` re-exposes every secret in child argv.

**Remediation Steps**:
1. Export secrets as environment variables inside the `withCredentials` block
2. Have playbooks read them via `lookup('env', ...)` (already partially supported)
3. Alternatively, write secrets to a mode-0600 vars file passed with `--extra-vars @file`
4. Drop `-vvv` for credential-carrying stages, or pair it with blanket `no_log` on secret-handling tasks

---

## FIND-001 — OCM client secret printed to Ansible debug output

**Severity**: High (triage confirmed, rescored)
**Audit CVSS**: 6.5 — CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N
**Triage CVSS**: **7.7 — CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:N/A:N**
**CWE**: CWE-532, CWE-312
**Location**: `tasks/create_rosa_creds_secret.yml:8-27`
**Category**: OWASP K8s K03 Secrets Management / ASVS V8.1
**Triage Confidence**: 8/10
**Triage Votes**: 3 true_positive, 0 false_positive

**Description**: After creating the rosa-creds-secret, the task emits a `debug:` message that interpolates `{{ ocm_client_secret }}` directly into stdout. The preceding `shell:` tasks also embed the secret in the rendered command without `no_log: true`. The `debug` module prints unconditionally at verbosity 0+.

**Triage Rescore Rationale**: Added S:C for OCM stage API as separate security authority. Triage identified additional unmasked sinks: `_generate_junit_xml()` writes full captured output into `<failure>` element text → archived via `archiveArtifacts 'test-results/**/*.xml'`. Archived artefacts bypass `withCredentials` masking entirely. Every stdout line also fed to `monitor_agent.process_line(line)` → `intervention_log.json` (also archived).

**Reachability**: `roles/configure-capa-environment/tasks/main.yml:~88` includes `create_rosa_creds_secret.yml` unconditionally. Jenkinsfile stage 'Configure CAPI/CAPA Environment' runs with `withCredentials CAPI_OCM_CLIENT_SECRET` at `-vvv`.

**Remediation Steps**:
1. Delete the debug task that prints `ocm_client_secret`
2. Add `no_log: true` to both `shell:` tasks that interpolate `ocm_client_secret`
3. Replace `shell: oc create secret --from-literal` with `kubernetes.core.k8s` module and `no_log: true` so the value never appears in a rendered shell command
4. Apply the same `no_log: true` treatment to all tasks that handle OCM, AWS, or OCP credentials

---

## FIND-004 — AWSClusterControllerIdentity allows all namespaces

**Severity**: Medium (triage confirmed, rescored, needs manual test)
**Audit CVSS**: 5.4 — CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:L/I:L/A:N
**Triage CVSS**: **6.0 — CVSS:3.1/AV:N/AC:H/PR:L/UI:N/S:C/C:L/I:L/A:L**
**CWE**: CWE-269, CWE-284
**Location**: `tasks/set_aws_identity.yml:1-13`
**Category**: OWASP K8s K08 Cloud Lateral Movement
**Triage Confidence**: 6.7/10
**Triage Votes**: 3 true_positive, 0 false_positive

**Description**: The `AWSClusterControllerIdentity` named `default` is created with `spec.allowedNamespaces: {}`, which matches every namespace. Any principal able to create CAPI/CAPA CRs in any namespace can reference the controller's AWS credentials. The task is idempotent `oc apply`, so it re-asserts the permissive value on every Jenkins run, defeating any out-of-band tightening.

**Triage Note**: Needs manual test — confirm whether co-tenants on the shared MCE hub hold create verb on `infrastructure.cluster.x-k8s.io` CRs. AC:H reflects this conditionality; S:C for hub-to-AWS-account scope change.

**Remediation Steps**:
1. Restrict `allowedNamespaces` to an explicit list (e.g., `{{ capi_namespace }}`, `multicluster-engine`) or a label selector scoped to QE-owned namespaces
2. Document that this object is cluster-scoped and persists after the test run
3. Add an explicit teardown task that reverts the identity scope after testing

---

## FIND-005 — capa-manager-role gets cluster-wide Secret list/watch

**Severity**: Medium
**Audit CVSS**: 5.0 — CVSS:3.1/AV:N/AC:H/PR:H/UI:N/S:C/C:H/I:N/A:N
**CWE**: CWE-269
**Location**: `tasks/update_capa_clusterrole_network.yml:126-151`
**Category**: OWASP K8s K02 Overly Permissive RBAC / CIS 5.1.3
**Triage Disposition**: Dropped — intentional behavior / misread code

**Description**: The task appends a rule granting `get`, `list`, `watch` on all Secrets cluster-wide to the `capa-manager-role` ClusterRole with no `resourceNames` restriction. The sibling task `update_capa_clusterrole.yml` correctly scopes the same grant with `resourceNames`, indicating this broader grant may be unintended drift.

**Triage Note**: Triage dropped this as intentional behavior required for CAPA network automation. The broad secrets rule in `update_capa_clusterrole_network.yml` is needed because CAPA network controllers must read secrets across namespaces. However, we should still evaluate whether scoping is possible.

**Remediation Steps**:
1. Evaluate whether `resourceNames` scoping is feasible without breaking CAPA network automation
2. If not feasible, document the justification and accept the risk
3. If feasible, scope the appended secrets rule with `resourceNames` or move to a namespaced Role

---

## FIND-007 — GitHub Actions pinned by mutable tag/branch

**Severity**: Low
**Audit CVSS**: 3.1 — CVSS:3.1/AV:N/AC:H/PR:H/UI:N/S:C/C:L/I:L/A:N
**CWE**: CWE-1357, CWE-494
**Location**: `.github/workflows/ci.yml`, `.github/workflows/pr-checks.yml`
**Category**: SLSA v1.2 Pinned-Dependencies / OpenSSF Scorecard
**Triage Disposition**: Dropped — no source location in triage input

**Description**: All third-party actions were referenced by mutable refs (`@v4`, `@master`, `@main`). Neither workflow declared a top-level `permissions:` block.

**Remediation Steps**:
1. Pin every `uses:` to a full 40-char commit SHA with inline version comment
2. Add top-level `permissions: { contents: read }` to both workflows
3. Scope elevated permissions (e.g., `security-events: write`) only to jobs that need them
4. Add `persist-credentials: false` to all checkout steps

**Status**: **DONE** — PR #69 (merged 6/30). All 7 action SHAs verified against upstream tags.

---

## FIND-008 — Jenkins agent pod lacks securityContext and uses mutable image tags

**Severity**: Low
**Audit CVSS**: 3.0 — CVSS:3.1/AV:L/AC:H/PR:H/UI:N/S:C/C:L/I:L/A:N
**CWE**: CWE-250, CWE-1188
**Location**: `picsAgentPod_capa.yaml:1-40`
**Category**: OWASP K8s K01 Insecure Workload Config / CIS 5.7.3
**Triage Disposition**: Dropped — not actionable from this repo (infra-owned)

**Description**: The Jenkins agent Pod spec has no `securityContext` (no `runAsNonRoot`, no `allowPrivilegeEscalation: false`, no `readOnlyRootFilesystem`). Images are referenced by mutable tags including a personal `quay.io/vboulos/...` namespace.

**Triage Note**: Agent pod spec is owned by the infra team, not this repo. Changes require coordination with the Jenkins platform team.

**Remediation Steps**:
1. Add `securityContext` to both containers: `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `capabilities: { drop: [ALL] }`, `seccompProfile: { type: RuntimeDefault }`
2. Set `automountServiceAccountToken: false` on the pod
3. Pin both images by `@sha256:` digest
4. Host images under an org-controlled registry namespace (not personal quay)

---

## FIND-009 — Missing Dependabot, SECURITY.md, and lint enforcement

**Severity**: Informational
**Audit CVSS**: 0.0
**CWE**: CWE-1104
**Location**: `.github/`
**Category**: SLSA v1.2 / OpenSSF Scorecard
**Triage Disposition**: Dropped — no source location in triage input

**Description**: No `.github/dependabot.yml` or Renovate config, no `SECURITY.md` disclosure policy, and CI lint jobs all end with `|| true` so findings never fail the build.

**Remediation Steps**:
1. Add `.github/dependabot.yml` covering `github-actions` and `pip` ecosystems
2. Add `SECURITY.md` pointing to Red Hat PSIRT
3. Remove `|| true` from lint steps so they gate merges
4. Onboard the repo to OpenSSF Scorecard

**Status**: **PARTIAL** — Dependabot config, SECURITY.md, and lint enforcement merged via PR #69 (6/30). OpenSSF Scorecard onboarding is an org-level action.

---

## STS-001 — Replace static AWS IAM keys with short-lived STS credentials

**Severity**: Medium
**CWE**: CWE-798
**Location**: `Jenkinsfile`, `tasks/create_capa_manager_bootstrap_credentials.yml`
**Category**: OWASP K8s K03 / AWS Security Best Practices

**Description**: The framework uses long-lived AWS IAM access keys stored in Jenkins credentials. If leaked via any of the credential exposure findings (FIND-001, FIND-003, FIND-006), they are valid until manually rotated.

**Remediation Steps**:
1. Create an IAM role (e.g., `rosa-hcp-e2e-test-runner`) with the permissions CAPA needs
2. Configure a trust policy allowing the Jenkins IAM user to assume this role
3. Add an `aws sts assume-role` step at the start of each Jenkins stage to generate temporary credentials (1-hour TTL)
4. Update `create_capa_manager_bootstrap_credentials.yml` to include `aws_session_token` in the credentials INI block
5. Temporary credentials expire automatically — even if leaked, exposure window is 1 hour instead of indefinite

---

## Recommended Priority Order

| Priority | Finding | Triage CVSS | Description | Effort |
|----------|---------|-------------|-------------|--------|
| 1 | FIND-002 | 9.9 | Remove TLS skip, switch to token auth, add `no_log` | Small |
| 2 | FIND-003 | 8.5 | Add `no_log` to AWS credential tasks, delete debug prints | Small |
| 3 | FIND-006 | 8.4 | Stop passing secrets as CLI args, drop `-vvv` | Small |
| 4 | FIND-001 | 7.7 | Delete OCM secret debug print, add `no_log` | Small |
| 5 | FIND-004 | 6.0 | Scope AWSIdentity to QE namespaces (needs manual test first) | Small |
| 6 | FIND-005 | 5.0 | Evaluate scoping capa-manager-role secrets rule (triage dropped — verify) | Small |
| 7 | STS-001 | — | Replace static IAM keys with STS AssumeRole | Medium |
| 8 | FIND-008 | 3.0 | Agent pod securityContext + image pinning (infra-team coordination) | Small |
| 9 | FIND-009 | 0.0 | OpenSSF Scorecard onboarding (remaining item) | Small |
| — | FIND-007 | 3.1 | GitHub Actions SHA pinning + workflow permissions | **Done** (PR #69, merged 6/30) |
