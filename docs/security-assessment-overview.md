# Security Assessment Overview

**Repository**: https://github.com/stolostron/rosa-hcp-e2e-test
**Audit Reference**: HCMSEC-3528
**Audit Date**: 2026-06-08
**Triage Date**: 2026-06-29

---

## What Is This?

A security assessment was performed on the rosa-hcp-e2e-test framework — an internal QE automation harness that provisions and tests ROSA HCP clusters. Although it is not shipped to customers, it handles high-value credentials (AWS IAM keys, OCM client secret, OCP cluster-admin password) against real cloud infrastructure and OpenShift hub clusters. The assessment evaluated how those credentials are handled throughout the system.

---

## The Four Documents

### 1. Threat Model (June 9)

**Purpose**: Maps the system's attack surface before anyone looks for specific bugs.

**What's in it**:
- **Assets** — what has value (AWS keys, OCM secret, hub password, cluster state)
- **Entry points** — where an attacker could interact with the system (Ansible tasks, Jenkins pipeline, agent pod, GitHub Actions)
- **Trust boundaries** — where trusted components meet untrusted ones (Jenkins secrets → Ansible stdout, agent pod → corporate network, test harness → shared hub)
- **12 threat scenarios** (T1–T12) — specific ways an attacker could exploit the system

**How to read it**: Start with the assets table to understand what's at risk, then look at the threats table to see what could go wrong and whether any controls exist.

### 2. Security Audit (June 8)

**Purpose**: A scanner examined the actual code and found specific vulnerabilities.

**What's in it**:
- **9 findings** (FIND-001 through FIND-009) rated from High to Informational
- Each finding includes: severity, CVSS score, exact file and line number, code evidence, attack pattern, and remediation steps
- Also includes **negative results** — areas that were checked and found clean (e.g., no shell injection in Python code, no hardcoded credentials committed)

**Available in two formats**:
- **Markdown** — human-readable report for review and discussion
- **JSON** — machine-readable version for tooling, dashboards, and tracking systems (identical data, different format)

**How to read it**: The findings summary table gives the overview. Each finding section shows the exact vulnerable code and explains how an attacker would exploit it.

### 3. Triage Report (June 29)

**Purpose**: A deeper second pass that verifies each finding and re-scores severity based on actual exploitability.

**What's in it**:
- Each finding was independently verified by 3 voters (true positive / false positive / cannot verify)
- CVSS scores were re-derived based on deeper code analysis of reachability chains
- Detailed evidence showing exactly how an attacker reaches each vulnerability through the codebase

**Results**:
- **5 confirmed** as real problems (4 High, 1 Medium)
- **4 dropped** — either not actually exploitable, already fixed, or not actionable from this repo

**Key changes from the original audit**:
- FIND-002 (oc login) rescored from 6.8 → **9.9** — the OCP password is completely unmasked in Jenkins (worse than the audit thought)
- FIND-003 (AWS keys) rescored from 5.0 → **8.5** and promoted Medium → **High** — base64 encoding bypasses Jenkins credential masking
- FIND-006 (Jenkins argv) rescored from 4.4 → **8.4** and promoted Medium → **High** — secrets readable in /proc for multi-hour runs

**How to read it**: The "Act on these" section lists confirmed findings in priority order. The "Dropped" section explains why certain findings were dismissed.

### 4. Remediation Plan

**Purpose**: The actionable output — what we fix, in what order, and how.

**What's in it**:
- All findings (confirmed and dropped) with full descriptions, CVSS scores from both audit and triage, and specific remediation steps
- Priority ordering based on triage CVSS scores
- Current status of each remediation effort

**Location**: `docs/security-audit-remediation-plan.md`

**How to read it**: Start with the findings summary table for the overview, then check the recommended priority order at the bottom for the fix sequence.

---

## How the Documents Connect

```
Threat Model                Security Audit              Triage Report
(what could go wrong)  →    (what IS wrong)        →    (how bad, really?)
12 threat scenarios         9 code-level findings        5 confirmed, 4 dropped
                                  ↓                           ↓
                            JSON version              Remediation Plan
                            (for tooling)             (what we fix & when)
```

Each finding traces through the full chain:

```
FIND-002 (code-level finding)
  ↓ maps to threats
T1 (credential leak) + T2 (TLS disabled)
  ↓ threatens assets
OCP hub cluster-admin password
  ↓ exploitable via entry points
Jenkins console read (easiest) or network MITM (harder)
  ↓ fix with remediation
Remove --insecure-skip-tls-verify, add no_log, switch to token auth
```

---

## Findings Summary

| # | Description | Severity | Audit CVSS | Triage CVSS | Triage Disposition | Status |
|---|-------------|----------|------------|-------------|-------------------|--------|
| FIND-002 | oc login disables TLS verification and exposes password on CLI | **High** | 6.8 | **9.9** | Confirmed — rescored up | Not started |
| FIND-003 | AWS access keys interpolated into shell task without no_log | **High** | 5.0 | **8.5** | Confirmed — rescored up (was Medium) | Not started |
| FIND-006 | Jenkins pipeline passes all secrets as CLI extra-vars at -vvv | **High** | 4.4 | **8.4** | Confirmed — rescored up (was Medium) | Not started |
| FIND-001 | OCM client secret printed to Ansible debug output | **High** | 6.5 | **7.7** | Confirmed — rescored up | Not started |
| FIND-004 | AWSClusterControllerIdentity allows all namespaces | **Medium** | 5.4 | **6.0** | Confirmed — needs manual test | Not started |
| FIND-005 | capa-manager-role gets cluster-wide Secret list/watch | Medium | 5.0 | — | Triage dropped — intentional behavior | Not started |
| FIND-007 | GitHub Actions pinned by mutable tag/branch | Low | 3.1 | — | Triage dropped — no source location | **Done** (PR #69, merged 6/30) |
| FIND-008 | Jenkins agent pod lacks securityContext, uses mutable image tags | Low | 3.0 | — | Triage dropped — not actionable from this repo | Not started |
| FIND-009 | Missing Dependabot, SECURITY.md, and lint enforcement | Info | 0.0 | — | Triage dropped — no source location | **Partial** (PR #69, merged 6/30) |
| STS-001 | Replace static AWS IAM keys with short-lived STS credentials | Medium | — | — | New — proposed mitigation | Not started |

---

## The Common Theme

The dominant risk across all High findings is **credential exposure**. AWS keys, the OCM secret, and the OCP hub password are being printed, logged, or exposed through:

- Ansible `debug:` tasks that print secrets to stdout
- `shell:` tasks that interpolate secrets into commands without `no_log: true`
- Jenkins pipeline passing secrets as command-line arguments visible in `/proc`
- `-vvv` verbosity causing Ansible to echo rendered commands with credentials
- Archived JUnit XML and agent logs that bypass Jenkins credential masking
- `oc login` with TLS verification disabled, exposing the password on the network

The fixes are mostly:
- Adding `no_log: true` to Ansible tasks that handle credentials
- Deleting debug prints that expose secrets
- Changing how Jenkins passes secrets (env vars or files instead of CLI args)
- Enabling TLS verification and switching to token-based authentication

---

## Current Remediation Status

| Finding | Status | Details |
|---------|--------|---------|
| FIND-007 | **Done** | PR #69 (merged 6/30) — all GitHub Actions pinned to verified SHAs, top-level permissions added |
| FIND-009 | **Partial** | PR #69 (merged 6/30) — Dependabot config, SECURITY.md, and lint enforcement merged. OpenSSF Scorecard onboarding is org-level. |
| FIND-001 | Not started | |
| FIND-002 | Not started | |
| FIND-003 | Not started | |
| FIND-004 | Not started | Needs manual test to verify hub co-tenant RBAC |
| FIND-005 | Not started | Triage dropped — evaluate whether scoping is feasible |
| FIND-006 | Not started | |
| FIND-008 | Not started | Requires infra-team coordination |

---

## Frameworks Used

The audit was evaluated against:

- **OWASP ASVS v5.0** — Application Security Verification Standard
- **OWASP K8s Top 10 2025** — Kubernetes-specific security risks
- **CIS K8s v2.0** — Center for Internet Security Kubernetes benchmark
- **DISA STIG V2R6** — Defense Information Systems Agency Security Technical Implementation Guide
- **SLSA v1.2** — Supply-chain Levels for Software Artifacts
- **OpenSSF Scorecard** — Open Source Security Foundation project health metrics
