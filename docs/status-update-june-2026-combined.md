# Combined Status Report — June 2026

**Period**: June 9 – June 30, 2026
**Author**: Tina Fitzgerald

---

## Summary

Over June, the primary focus was building and maturing the ROSA HCP CAPI/CAPA automated feature testing framework. The month started with shipping the core feature flag system covering 13 features, and progressed through adding individual feature support (security groups, private clusters, BYON), improving verification to use direct AWS/OCM API checks, documenting all 15 features, and hardening CI security. By month end, 15 features are fully automated with end-to-end coverage, multiple PRs are in review, and a security audit remediation effort is underway.

---

## Week Ending 6/9/2026

### Cluster Service Migrations
**Completed:**
- migration of cs-rosa-hcp-backup-cp-upgrade-integration-main [OCM-23830]
- migration of cs-rosa-hcp-autonode-integration-main [OCM-23829]
- migration of cs-osd-gcp-wif-sv-staging-main [OCM-23818]
- migration of cs-rosa-hcp-upgrade-staging-main [OCM-23812]

### Future Sustainability [OCM-22529]
**Completed:**
- Built and shipped the automated feature testing framework for CAPI/CAPA 4.22. This allows the team to provision ROSA HCP clusters with any combination of Day 1 features using simple CLI flags (e.g., `--feature etcd-kms --feature fips`) instead of manually editing templates. The framework automatically resolves dependencies between features, validates compatibility with the target OpenShift version, and verifies after provisioning that each requested feature was correctly applied to the live cluster. 13 of the targeted features are now fully automated with end-to-end coverage. (PRs #60-66)

**In Progress:**
- Security group automation for `--feature security-groups` testing
- Break-glass credential 403 diagnostic for external-auth clusters

---

## Week Ending 6/16/2026

### Future Sustainability [OCM-22529]
**Completed:**
- Added automated security group provisioning and cleanup. When a tester runs `--feature security-groups`, the framework now creates a test security group in the cluster VPC, injects it into the ROSAMachinePool template, and automatically cleans it up during cluster deletion with ENI detach retry logic. This eliminates the need to manually create and manage AWS security groups for Day 1 feature testing. (PR #67)
- Built a diagnostic test for break-glass credential 403 errors on external-auth clusters. The diagnostic checks OCM role bindings, provisioner secret state, external auth configuration, and token validity, then provides specific remediation steps for each root cause. (PR #70)

**In Review:**
- Individual documentation for each of the 15 automated feature tests, covering usage examples, expected template output, and verification assertions. (PR #71)

**In Progress:**
- Hardening CI workflows by pinning all GitHub Actions to immutable SHA hashes and restricting token permissions to least privilege, reducing supply chain and credential exfiltration risk. (PR #69)

---

## Week Ending 6/23/2026

### Future Sustainability [OCM-22529]
**Completed:**
- PR #67 — Automated security group creation and cleanup for cluster testing. Addressed reviewer feedback and merged. (6/22)

**In Review:**
- PR #70 — Automated diagnostic tool that identifies why break-glass credential requests fail on external-auth clusters. Reworked based on review feedback.
- PR #72 — Added support for provisioning private clusters with private subnets. Validated on a live cluster and addressed review feedback.
- PR #74 — Improved how the framework verifies that cluster features were applied correctly, replacing indirect checks with direct AWS and OCM API validation.
- PR #71 — Added documentation for all 15 supported cluster features, covering usage, expected behavior, and how each is verified.

**In Progress:**
- PR #69 — Improving CI pipeline security by restricting permissions and pinning dependencies.

---

## Week Ending 6/30/2026

### Future Sustainability [ROSAENG-8331]
**Completed:**
- [ROSAENG-59883] PR #69 — CI security hardening merged. All GitHub Actions SHA-pinned, workflow permissions restricted, Dependabot added, lint enforcement enabled. (6/30)
- [ROSAENG-60063] PR #70 — Reworked break-glass credential diagnostic tool. Refactored for YAML compliance and maintainability, addressed review findings. (6/25)
- [ROSAENG-60060] PR #72 — Addressed review findings on private cluster subnet support. (6/25)
- [ROSAENG-60065] PR #74 — Addressed review findings on AWS/OCM feature verification rewrite. Added OIDC issuer URL validation. (6/25)

**In Review:**
- [ROSAENG-60063] PR #70 — Break-glass credential diagnostic tool for external-auth clusters. Awaiting reviewer approval.
- [ROSAENG-60065] PRs #71, #74 — Feature documentation and AWS/OCM API verification for all 15 cluster features. Awaiting reviewer approval.
- [ROSAENG-60060] PR #72 — Private cluster subnet support. Awaiting reviewer approval.

**In Progress:**
- [ROSAENG-60058] PR #77 — Added Bring Your Own Network (BYON) support, allowing testers to provision clusters into existing VPCs instead of creating new ones.

---

## Month-End PR Status

| PR | Title | Jira | Status |
|---|---|---|---|
| #60-66 | Feature flag framework (13 features) | OCM-22529 | Merged |
| #67 | Security group automation | ROSAENG-59871 | Merged (6/22) |
| #69 | CI security hardening | ROSAENG-59883 | Merged (6/30) |
| #70 | Break-glass credential diagnostic | ROSAENG-60063 | Open — awaiting approval |
| #71 | Feature documentation (15 features) | ROSAENG-60065 | Open — awaiting approval |
| #72 | Private cluster subnet support | ROSAENG-60060 | Open — awaiting approval |
| #74 | AWS/OCM API feature verification | ROSAENG-60065 | Open — awaiting approval |
| #77 | Bring Your Own Network (BYON) | ROSAENG-60058 | Open |

---

## Key Accomplishments — June 2026

1. **Feature testing framework shipped** — 15 ROSA HCP Day 1 features can now be provisioned and verified with simple CLI flags, replacing manual template editing
2. **All cluster service migrations completed** — 4 remaining migrations finished across staging and integration environments
3. **Security group automation** — fully automated creation, injection, and cleanup for security group feature testing
4. **Private cluster support** — framework can provision private clusters with auto-extracted or user-provided subnets
5. **AWS/OCM API verification** — replaced indirect CRD-only checks with direct AWS CLI and OCM API validation for 15 features
6. **CI security hardening** — GitHub Actions SHA-pinned, workflow permissions restricted, Dependabot added, lint enforcement enabled
7. **Break-glass diagnostic** — automated root cause analysis for credential 403 errors on external-auth clusters
8. **Feature documentation** — all 15 features documented with metadata, usage examples, and verification approach
