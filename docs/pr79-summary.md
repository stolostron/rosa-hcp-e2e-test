# PR #79 — Harden Credential Handling Across Pipeline and Ansible Tasks

**Repository:** stolostron/rosa-hcp-e2e-test
**Branch:** `cleanup` → `main`
**Author:** tinaafitz
**Status:** Open — awaiting reviewer approval
**Files changed:** 5 (~299 lines)
**Commits:** 4

---

## Overview

Hardens credential handling across the Jenkins pipeline and Ansible task files to prevent secrets from leaking into logs, console output, or rendered files on disk.

---

## Files Changed

| File | Purpose |
|------|---------|
| `Jenkinsfile` | Remove secrets from `-e` CLI args; reduce verbosity `-vvv` → `-v`; bind `AWS_ACCOUNT_ID` in delete stage |
| `tasks/check_environment_health.yml` | Conditional TLS certificate-authority login handling |
| `tasks/create_capa_manager_bootstrap_credentials.yml` | `no_log`, file permissions `0600`, block/always cleanup |
| `tasks/create_rosa_creds_secret.yml` | `no_log` on credential tasks; safe confirmation message |
| `tasks/login_ocp.yml` | `no_log` on login command; conditional CA bundle |

---

## Changes

### Jenkinsfile
- Removed secret values (`PASSWORD`, `SECRET_ACCESS_KEY`, `OCM_CLIENT_SECRET`) from `-e` extra vars in 9 test stages — playbooks already read these via `lookup('env', ...)`
- Changed verbosity from `-vvv` to `-v` on all pipeline stages to reduce credential echo
- Added `CAPI_AWS_ACCOUNT_ID` binding to the delete stage `withCredentials` block

### Ansible Tasks — Credential Suppression
- Added `no_log: true` to all tasks that handle OCM, AWS, and OCP credentials
- Replaced debug task that printed `ocm_client_secret` to stdout with a safe confirmation message
- Removed commented-out debug blocks that printed raw AWS keys

### Ansible Tasks — TLS Handling
- Replaced hardcoded `--insecure-skip-tls-verify` with conditional `--certificate-authority={{ ocp_ca_bundle }}` when CA bundle is provided, falling back to TLS skip otherwise

### Ansible Tasks — File Security
- Set mode `0600` on rendered CAPA bootstrap credentials file
- Wrapped `oc apply` + file removal in `block/always` so credential file is cleaned up even if apply fails

### Bug Fixes
- Fixed credential gate param name mismatch (`OCP_HUB_CLUSTER_API_URL` → `OCP_HUB_API_URL`)
- Removed cluster name from login task name to avoid leaking it in logs

---

## Test Plan

- [ ] Run pipeline end-to-end and verify no secrets appear in Jenkins console output
- [ ] Run with `ocp_ca_bundle` defined to verify certificate-authority login path
- [ ] Run without `ocp_ca_bundle` to verify insecure-skip-tls fallback
- [ ] Verify CAPA credentials file is removed after `oc apply` (including on failure)
- [ ] Verify delete stage receives `AWS_ACCOUNT_ID` correctly

---

## Blockers

- Needs `/approve` and `/lgtm` from an OWNERS file approver
