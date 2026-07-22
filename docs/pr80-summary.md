# PR #80 — Fix 4 Latent Provisioning Bugs in Default Variable Handling

**Repository:** stolostron/rosa-hcp-e2e-test
**Branch:** `fix/provisioning-defaults` → `main`
**Author:** tinaafitz
**Status:** Open — awaiting reviewer approval
**Files changed:** 2 (~75 lines)
**Commits:** 2

---

## Overview

Fixes 4 latent bugs in the provisioning playbook that are masked by Jenkins always providing variables via `user_vars.yml`, but break when playbooks are invoked with `-e` extra-vars (CLI, other runners, or any non-Jenkins context).

---

## Bugs Fixed

| # | Bug | Root Cause | Impact |
|---|-----|-----------|--------|
| 1 | `automation_path` resolves to `playbooks/` instead of repo root | `default(playbook_dir)` in role, but `playbook_dir` = `playbooks/` | Configure role task includes fail with "file not found" |
| 2 | Provisioning unconditionally re-configures CAPI/CAPA | No guard checking if controllers are already running | Unnecessary reconfiguration; fails if configure role has issues |
| 3 | `channel_group`, `private_network`, `additional_tags` not set when `aws_region` is passed via `-e` | All bundled in same `set_fact` behind `when: aws_region is not defined` | Undefined variable error on `channel_group` |
| 4 | `role_prefix` empty string not treated as undefined | `default()` without `true` flag treats `""` as defined | ROSARoleConfig CRD rejects empty prefix |

---

## Files Changed

| File | Changes |
|------|---------|
| `playbooks/create_rosa_hcp_cluster.yml` | Split bundled defaults into separate tasks; add CAPI/CAPA skip guard; fix `role_prefix` fallback with `default(..., true)`; fix `aws_region` empty-string handling |
| `roles/configure-capa-environment/tasks/main.yml` | Fix `automation_path` to use `playbook_dir + '/..` for correct repo root resolution |

---

## Testing

Full provision + delete cycle on OCP 4.22.2 against live hub cluster using extra-vars only (no `user_vars.yml`):

- [x] Suite 05 (pre-flight) passes with extra-vars
- [x] Suite 20 (provision) completes successfully on 4.22.2
- [x] Suite 30 (delete) initiated and progressing
- [x] YAML validates cleanly
- [x] Pre-commit hooks pass

---

## Blockers

- Needs `/approve` and `/lgtm` from an OWNERS file approver
