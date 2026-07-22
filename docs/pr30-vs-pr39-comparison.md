# PR #30 vs PR #39: Agent Framework Refactor Comparison

**Date:** April 29, 2026
**PRs Compared:**
- [PR #30](https://github.com/stolostron/rosa-hcp-e2e-test/pull/30) — "refactor: generic agent framework with domain plugin architecture" (tinaafitz, closed 2026-04-19)
- [PR #39](https://github.com/stolostron/rosa-hcp-e2e-test/pull/39) — "Add Agent v2" (closed)

Both PRs attempt to make the agent framework reusable beyond ROSA HCP. Neither was merged. This document compares their approaches side by side.

---

## Executive Summary

| | PR #30 (Domain Plugin Refactor) | PR #39 (Agent-v2) |
|---|---|---|
| **Approach** | Refactor existing agents into base + domain plugin | Ground-up rewrite in separate `agent-v2/` directory |
| **Scope** | 18 files changed, surgical extraction | 47 new files, zero changes to existing code |
| **Risk** | Low — preserves existing code, all 52 tests pass | High — parallel codebase, no migration path |
| **Domain logic preserved** | Yes — moved to `agents/domains/rosa_hcp/` | No — replaced with Claude API + generic strategies |
| **New capabilities** | Domain plugin system, isolated KBs | Pluggable log streams, K8s deployment, Claude API diagnostics |
| **Diagnostics** | Rule-based (deterministic) | Claude API primary, rule-based fallback |
| **Test framework support** | Ansible (extensible via plugins) | Ansible, pytest, shell, generic |
| **Deployment** | In-process (same as today) | Standalone K8s pod, Docker, CLI |
| **Dependencies added** | None | anthropic, kubernetes |
| **Backward compatible** | Yes — existing tests pass unchanged | No — separate directory, separate entry point |

---

## Architecture Comparison

### PR #30: Domain Plugin Refactor

Keeps the existing agent chain intact and extracts domain-specific code into
a plugin structure:

```
agents/
  base_agent.py          (122 -> 128 lines, added kb_dir parameter)
  monitoring_agent.py    (336 -> 337 lines, extracted 2 overridable hooks)
  diagnostic_agent.py    (673 -> 119 lines, gutted to generic base)
  remediation_agent.py   (610 -> 139 lines, gutted to generic base)
  learning_agent.py      (327 -> 329 lines, added kb_dir pass-through)
  domains/
    rosa_hcp/
      __init__.py         (exports RosaHcp*Agent classes)
      diagnostic.py       (480 lines — all ROSA diagnosis methods)
      remediation.py      (448 lines — all ROSA fix methods)
      monitoring.py       (41 lines — resource type detection + stale filtering)
      knowledge_base/
        known_issues.json
        fix_strategies.json
        remediation_outcomes.json
      tests/
        test_rosa_hcp.py  (138 lines — 6 domain smoke tests)
```

**Key design decisions:**
- Base classes expose overridable hooks: `_diagnose_issue()`, `_get_fix_method()`,
  `_should_skip_stale_issue()`, `_extract_waiting_for_resource()`
- Each domain plugin gets its own `kb_dir` for knowledge base isolation
- `LearningAgent` used as-is (domain-agnostic) — just point it at the right KB
- `run-test-suite.py` changes are minimal (swap imports, pass `kb_dir`)

**How a new team adopts it:**
1. Create `agents/domains/my_team/knowledge_base/known_issues.json`
2. Subclass `DiagnosticAgent` — override `_diagnose_issue()`
3. Subclass `RemediationAgent` — override `_get_fix_method()`
4. Optionally subclass `MonitoringAgent` for domain hooks
5. Use `LearningAgent` as-is with `kb_dir=` pointing to your KB

### PR #39: Agent-v2 (Ground-Up Rewrite)

Creates an entirely new package alongside the existing agents:

```
agent-v2/
  cli.py                 (219 lines — ansible/pytest/shell/generic/pipe subcommands)
  Dockerfile             (43 lines — Python 3.11-slim + AWS CLI + oc)
  Makefile               (52 lines — build/push/deploy/undeploy)
  requirements.txt       (anthropic, boto3, kubernetes, ansible-core, pytest)
  core/
    base_agent.py        (115 lines)
    event.py             (72 lines — LogLine/Issue/Diagnosis dataclasses)
    pipeline.py          (222 lines — multi-stream orchestrator)
  log_streams/
    base_stream.py       (51 lines — stream interface)
    stdout_stream.py     (65 lines)
    file_stream.py       (91 lines)
    k8s_stream.py        (247 lines — SDK + subprocess dual mode)
    pipe_stream.py       (47 lines)
    cloudwatch_stream.py (103 lines)
    journald_stream.py   (142 lines)
  frameworks/
    base_framework.py    (63 lines)
    ansible_framework.py (90 lines)
    pytest_framework.py  (76 lines)
    shell_framework.py   (65 lines)
    generic_framework.py (97 lines)
  monitoring/
    monitoring_agent.py  (253 lines)
  diagnostic/
    diagnostic_agent.py  (639 lines)
    claude_client.py     (192 lines — Anthropic API integration)
  remediation/
    remediation_agent.py (498 lines)
  learning/
    learning_agent.py    (262 lines)
  knowledge_base/        (known_issues.json, fix_strategies.json, outcomes.json)
  deploy/                (K8s manifests: RBAC, ConfigMap, Deployment, Service)
  deploy/examples/       (6 example deployments)
```

---

## Component-by-Component Comparison

### 1. Monitoring Agent

| | PR #30 | PR #39 |
|---|---|---|
| **Base** | Same `MonitoringAgent` with 2 new hooks | New `monitoring_agent.py` (253 lines) |
| **State machine** | `TrackedIssue` with DETECTED/DIAGNOSING/REMEDIATING/RESOLVED/FAILED | No per-resource state machine |
| **Deduplication** | 60s throttle, 120s resolved re-check, max 3 retries + bonus | Basic or none |
| **Structured context** | `#AGENT_CONTEXT:` markers from playbooks | Framework adapter parses output |
| **Domain hooks** | `_should_skip_stale_issue()`, `_extract_waiting_for_resource()` | N/A (monolithic) |
| **Log sources** | stdout + sidecar file (unchanged) | 6 pluggable streams |

PR #30 preserves all the battle-tested state machine logic. PR #39 gains
multi-source log ingestion but loses per-resource tracking sophistication.

### 2. Diagnostic Agent

| | PR #30 | PR #39 |
|---|---|---|
| **Base class** | 119 lines, `_diagnose_issue()` returns `None` | 639 lines, Claude API primary |
| **ROSA logic** | `RosaHcpDiagnosticAgent` (480 lines) in domain plugin | Not present (Claude API handles it) |
| **CF/VPC cascade** | Full logic preserved in domain plugin | Not present |
| **Resource extraction** | 5-priority fallback chain preserved | Simpler extraction |
| **Learned confidence** | Preserved, reads from domain KB | Not documented |
| **External AI** | None (deterministic) | Claude API required for full capability |
| **Novel issues** | Returns generic low-confidence diagnosis | Claude can reason about unknown patterns |

PR #30 keeps every ROSA-specific diagnostic method intact — just moves them.
PR #39 replaces domain expertise with AI inference.

### 3. Remediation Agent

| | PR #30 | PR #39 |
|---|---|---|
| **Base class** | 139 lines, `_get_fix_method()` returns basic fixes only | 498 lines, data-driven dispatch |
| **ROSA fixes** | `RosaHcpRemediationAgent` (448 lines) in domain plugin | Shell-command strategies from fix_strategies.json |
| **CF retry (7-step)** | Preserved in domain plugin | Generic shell commands |
| **VPC cleanup** | Preserved (ENI, SG, subnet, IGW) | Not present as specialized logic |
| **Dry-run** | Preserved | Documented |
| **Success tracking** | Preserved | Present |

The 7-step CloudFormation retry with VPC dependency cleanup is the most
complex piece of remediation logic. PR #30 preserves it entirely. PR #39
replaces it with generic shell command strategies.

### 4. Learning Agent

| | PR #30 | PR #39 |
|---|---|---|
| **Changes** | 2 lines changed (added `kb_dir` parameter) | New implementation (262 lines) |
| **Confidence adjustment** | Preserved (3+ successes -> +0.05, 2+ failures -> -0.1) | Shorter, less documented |
| **Pending learnings** | Preserved (human review gate) | Not documented |
| **KB isolation** | `kb_dir` parameter enables per-domain KBs | Single KB |

PR #30 makes the learning agent domain-agnostic by parameterizing `kb_dir`.
The actual adjustment logic is unchanged.

### 5. Infrastructure & Deployment

| | PR #30 | PR #39 |
|---|---|---|
| **Deployment** | In-process (unchanged) | K8s pod, Docker, standalone CLI |
| **Dockerfile** | None needed | Python 3.11-slim + AWS CLI v2 + oc CLI |
| **K8s manifests** | None | RBAC, ConfigMaps, Deployment, Service, 6 examples |
| **CLI** | `--ai-agent` flag on `run-test-suite.py` | `cli.py` with 5 subcommands |
| **Framework support** | Ansible (others via domain plugins) | Ansible, pytest, shell, generic built-in |

### 6. Log Streams

| | PR #30 | PR #39 |
|---|---|---|
| **Sources** | stdout + sidecar file (unchanged) | 6 pluggable: stdout, file, K8s, pipe, CloudWatch, journald |
| **Architecture** | Inline in TestSuiteRunner | `base_stream.py` interface + implementations |
| **Multi-stream** | Background thread for sidecar | `pipeline.py` orchestrator |

This is agent-v2's strongest differentiator. PR #30 doesn't address log
source extensibility at all.

---

## What PR #30 Does Better Than PR #39

1. **Preserves domain expertise** — All ROSA-specific diagnostic and remediation
   logic (707 + 442 lines) is preserved intact, just reorganized. PR #39 drops it.

2. **Backward compatible** — All 46 original tests pass plus 6 new ones.
   `run-test-suite.py` changes are minimal. PR #39 is a parallel codebase.

3. **Lower risk** — Surgical refactor vs ground-up rewrite. No new external
   dependencies. No API keys required.

4. **Clear adoption path** — 6-step guide for new teams to create domain plugins.
   PR #39 requires understanding a new framework from scratch.

5. **Learning loop preserved** — Confidence adjustments, pending learnings, and
   human review gates are untouched. PR #39's learning agent is less mature.

6. **Per-resource state machine** — The TrackedIssue state machine with
   deduplication, throttling, and retry logic is preserved. PR #39 has no equivalent.

7. **No external AI dependency** — Works in air-gapped/restricted environments.
   PR #39 requires an Anthropic API key for full diagnostic capability.

---

## What PR #39 Does Better Than PR #30

1. **Pluggable log streams** — 6 log sources vs 2. CloudWatch, K8s pod logs,
   and journald support enable monitoring beyond stdout/files.

2. **Standalone deployment** — Can run as a K8s sidecar pod independent of the
   test runner. Useful for long-running cluster monitoring.

3. **AI-powered diagnostics** — Claude API can reason about novel, unseen issues.
   Rule-based systems need new patterns added manually.

4. **Built-in multi-framework support** — pytest, shell, generic adapters are
   ready to use. PR #30 would need new domain plugins for each.

5. **Pipeline orchestrator** — Dedicated multi-stream coordinator. PR #30 relies
   on the test runner's callback pattern.

6. **Complete containerization** — Dockerfile, Makefile, K8s manifests. Ready to
   deploy as a service.

---

## Gaps in Both

| Gap | PR #30 | PR #39 |
|---|---|---|
| Metrics/observability | No metrics endpoint | No metrics endpoint |
| Alerting | Log-only | Log-only |
| Web UI/dashboard | `report.py` (existing, not in PR) | None |
| Multi-cluster | Single cluster per run | Possible via K8s but not documented |
| Pattern versioning | No version tracking | No version tracking |
| Log stream extensibility | Not addressed | Fully addressed |
| Claude API integration | Not addressed | Core feature |

---

## Migration & Coexistence

**PR #30** is additive to the existing codebase. If merged:
- Existing behavior is unchanged
- New teams can create domain plugins immediately
- ROSA HCP logic continues working as before
- No parallel codebase to maintain

**PR #39** creates a parallel codebase. If merged:
- Two agent frameworks exist side by side (`agents/` and `agent-v2/`)
- No migration path from one to the other
- Double maintenance burden until one is deprecated
- Existing `run-test-suite.py` integration is not addressed

---

## Recommendation

The ideal solution combines both approaches:

1. **Start with PR #30's plugin architecture** — it's low-risk, backward
   compatible, and preserves all domain expertise

2. **Selectively adopt PR #39's infrastructure** on top:
   - Log stream abstraction (the `base_stream.py` interface + implementations)
   - Pipeline orchestrator for multi-stream ingestion
   - K8s deployment manifests (optional, for sidecar monitoring)

3. **Add Claude API as an escalation tier** — rule-based diagnostics as primary
   engine, Claude API fallback for unrecognized patterns (combines determinism
   with flexibility)

4. **Framework adapters as domain plugins** — pytest/shell support implemented
   as new domain plugins under `agents/domains/` rather than a separate framework
   layer

This gives us: domain expertise + pluggable log sources + AI escalation +
K8s deployment, without the risk of a ground-up rewrite or maintaining two
parallel codebases.

---

## File Inventories

### PR #30 — 18 Files Changed

**Modified (8 files):**

| File | Before | After | Change |
|---|---|---|---|
| `agents/base_agent.py` | 122 lines | 128 lines | Added `kb_dir` parameter |
| `agents/diagnostic_agent.py` | 673 lines | 119 lines | ROSA methods extracted |
| `agents/remediation_agent.py` | 610 lines | 139 lines | ROSA methods extracted |
| `agents/monitoring_agent.py` | 336 lines | 337 lines | 2 hooks extracted |
| `agents/learning_agent.py` | 327 lines | 329 lines | `kb_dir` pass-through |
| `agents/knowledge_base/known_issues.json` | 220 lines | 2 lines | Patterns moved to domain |
| `agents/test_agents.py` | ~500 lines | ~500 lines | Updated to domain classes |
| `run-test-suite.py` | ~1113 lines | ~1115 lines | Domain imports + `kb_dir` |

**New (10 files):**

| File | Lines | Purpose |
|---|---|---|
| `agents/domains/__init__.py` | 3 | Package init |
| `agents/domains/rosa_hcp/__init__.py` | 13 | Exports domain agent classes |
| `agents/domains/rosa_hcp/diagnostic.py` | 480 | All ROSA diagnosis methods |
| `agents/domains/rosa_hcp/remediation.py` | 448 | All ROSA fix methods |
| `agents/domains/rosa_hcp/monitoring.py` | 41 | Resource type detection, stale filtering |
| `agents/domains/rosa_hcp/knowledge_base/known_issues.json` | 223 | Error patterns |
| `agents/domains/rosa_hcp/knowledge_base/fix_strategies.json` | 200 | Fix strategy definitions |
| `agents/domains/rosa_hcp/knowledge_base/remediation_outcomes.json` | 62 | Historical outcomes |
| `agents/domains/rosa_hcp/tests/__init__.py` | 0 | Package init |
| `agents/domains/rosa_hcp/tests/test_rosa_hcp.py` | 138 | 6 domain smoke tests |

### PR #39 — 47 New Files

| Directory | Files | Purpose |
|---|---|---|
| `agent-v2/` | 5 | Package root, CLI, Dockerfile, Makefile, requirements.txt |
| `agent-v2/core/` | 4 | BaseAgent, Event dataclasses, Pipeline orchestrator |
| `agent-v2/log_streams/` | 8 | 6 pluggable log source implementations |
| `agent-v2/frameworks/` | 5 | 4 framework adapters |
| `agent-v2/monitoring/` | 2 | Monitoring agent |
| `agent-v2/diagnostic/` | 3 | Diagnostic agent + Claude API client |
| `agent-v2/remediation/` | 2 | Remediation agent |
| `agent-v2/learning/` | 2 | Learning agent |
| `agent-v2/knowledge_base/` | 3 | Known issues, fix strategies, outcomes |
| `agent-v2/deploy/` | 4 | K8s manifests |
| `agent-v2/deploy/examples/` | 6 | Example deployment configurations |
| `agent-v2/README.md` | 1 | Documentation (780 lines) |
