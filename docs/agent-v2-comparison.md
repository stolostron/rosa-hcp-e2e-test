# Agent Framework Comparison: Local Agents vs PR #39 (agent-v2)

**Date:** April 29, 2026
**PR:** [stolostron/rosa-hcp-e2e-test#39](https://github.com/stolostron/rosa-hcp-e2e-test/pull/39) (closed, not merged)
**PR Description:** "Adding refactoring for the Agent work under Agent-v2 dir"

---

## Overview

This document compares our current agent framework (`agents/`) with the proposed
agent-v2 rewrite from PR #39. Both implement the same four-agent chain
(Monitor -> Diagnose -> Remediate -> Learn) but take fundamentally different
approaches: ours is a domain-specialized, in-process framework tightly integrated
with the test runner; agent-v2 is a generic, deployable platform designed to work
across frameworks and environments.

---

## Architecture at a Glance

| Aspect | Local Agents (`agents/`) | PR #39 (`agent-v2/`) |
|---|---|---|
| Version | 0.2.0 | N/A (new) |
| Files | 8 Python modules | 47 files (Python + K8s manifests + Dockerfile) |
| Entry point | `run-test-suite.py` (in-process) | `cli.py` with subcommands |
| Agent chain | Monitor -> Diagnose -> Remediate -> Learn | Monitor -> Diagnose -> Remediate -> Learn |
| Base class | `BaseAgent` (122 lines) | `BaseAgent` (115 lines) |
| Deployment | Runs inside test runner process | Standalone K8s pod, Docker container, or CLI |
| Test framework | Ansible only | Ansible, pytest, shell, generic |
| Log sources | stdout + sidecar log file | 6 pluggable streams (stdout, file, K8s, pipe, CloudWatch, journald) |
| Diagnostics engine | Rule-based with domain-specific methods | Claude API (primary) + rule-based fallback |
| Knowledge base | JSON (known_issues, fix_strategies, outcomes, pending_learnings) | JSON (known_issues, fix_strategies, outcomes) |
| AWS integration | Dedicated `AWSClient` class (450 lines, boto3) | Relies on Claude API intelligence + boto3 |
| Dependencies | boto3, oc CLI, OCM API (urllib) | anthropic, boto3, kubernetes, ansible-core, pytest |

---

## Component-by-Component Comparison

### 1. Monitoring Agent

**Local (`monitoring_agent.py` - 336 lines)**
- Per-resource state machine (`TrackedIssue`) with states: DETECTED, DIAGNOSING, REMEDIATING, RESOLVED, FAILED
- Sophisticated deduplication: 60s throttle window, 120s resolved re-check cooldown
- Max 3 retry attempts per resource, with one bonus attempt after 2 min cooldown
- Parses `#AGENT_CONTEXT:` structured markers from Ansible playbooks
- Multi-priority resource extraction (structured context > explicit fields > oc commands > output tables > task names)
- Tracks `current_task` and `waiting_for_resource` from Ansible output

**Agent-v2 (`monitoring/monitoring_agent.py` - 253 lines)**
- Pattern-based detection (similar known_issues.json matching)
- No per-resource state machine documented
- Simpler lifecycle management
- Designed to consume from any log stream, not just Ansible output

**Verdict:** Our monitoring agent is significantly more sophisticated for ROSA-specific
use cases. The per-resource state machine and deduplication logic prevent duplicate
interventions and handle multi-resource deletion scenarios that agent-v2 doesn't
address.

---

### 2. Diagnostic Agent

**Local (`diagnostic_agent.py` - 707 lines)**
- Fully rule-based with specialized diagnostic methods per issue type:
  - `_diagnose_stuck_rosanetwork()` - CloudFormation stack status checks, VPC dependency analysis
  - `_diagnose_stuck_rosacontrolplane()` - Low confidence, defers to CAPA controller
  - `_diagnose_cloudformation_failure()` - CF-specific analysis
  - `_diagnose_ocm_auth()` - OCM authentication checks
  - `_diagnose_capi_missing()` - Controller availability verification
  - `_diagnose_rate_limit()`, `_diagnose_timeouts()` - Operational issues
- Learned confidence integration from LearningAgent
- Multi-priority resource extraction with 5 fallback strategies
- Queries K8s resources (`oc get -o json`), AWS (boto3), OCM API (urllib)
- Sophisticated ROSANetwork logic:
  - CF `DELETE_IN_PROGRESS` + VPC blockers -> `retry_cloudformation_delete` (0.95 confidence)
  - CF `DELETE_FAILED` -> retry with cleanup (0.95 confidence)
  - CF `GONE` -> safe to remove finalizers
  - CF `UNKNOWN` -> low confidence (0.4), wait for more info

**Agent-v2 (`diagnostic/diagnostic_agent.py` - 639 lines)**
- **Claude API as primary diagnostic engine** via `claude_client.py` (192 lines)
- Sends issue context + log buffer to Claude for root cause analysis
- Built-in rule-based fallback when API unavailable
- More flexible (Claude can reason about novel issues)
- Less deterministic (API responses vary)

**Verdict:** Different philosophies. Our agent has deep, battle-tested domain logic
that handles ROSA-specific edge cases deterministically. Agent-v2's Claude API
approach is more flexible for unknown issues but less predictable and requires
API access. For ROSA deletion workflows specifically, our approach is superior.
For general-purpose use, agent-v2's AI-driven diagnostics are more adaptable.

---

### 3. Remediation Agent

**Local (`remediation_agent.py` - 442 lines)**
- Data-driven fix dispatch (routes by `diagnosis["recommended_fix"]`)
- Specialized fix methods:
  - `_fix_remove_finalizers()` - K8s finalizer removal via `oc patch`
  - `_fix_retry_cloudformation_delete()` - 7-step VPC cleanup:
    1. Check stack status (skip if GONE)
    2. Delete VPC endpoints (they create elastic-attach ENIs)
    3. Detach and delete remaining ENIs
    4. Delete non-default security groups
    5. Delete subnets
    6. Detach and delete internet gateways
    7. Retry stack deletion via boto3
    8. Verify stack transitions to DELETE_IN_PROGRESS
  - `_fix_cleanup_vpc_dependencies()` - Orphaned ENI/SG cleanup
  - `_fix_refresh_ocm_token()` - Placeholder (manual intervention)
  - `_fix_install_capi()` - CAPI/CAPA verification
  - Advisory fixes: `_fix_backoff_retry()`, `_fix_increase_timeout()`, `_fix_log_and_continue()`
- Success rate tracking per fix type
- Dry-run mode for all operations

**Agent-v2 (`remediation/remediation_agent.py` - 498 lines)**
- Similar data-driven executor dispatch
- Fix strategies loaded from `fix_strategies.json` (8 strategies with shell steps)
- More generic fix execution (shell command-based)
- Larger codebase suggests additional infrastructure

**Verdict:** Our remediation agent has deeply specialized AWS cleanup logic
(the 7-step CF delete is the crown jewel). Agent-v2 uses a more generic
shell-command-based approach from fix_strategies.json, which is more flexible
but less robust for complex multi-step AWS operations.

---

### 4. Learning Agent

**Local (`learning_agent.py` - 327 lines)**
- Records every remediation outcome with full context
- End-of-run analysis: groups outcomes, calculates confidence adjustments
- Confidence adjustment rules:
  - 3+ consecutive successes -> boost by 0.05 (max 1.0)
  - 2+ consecutive failures -> reduce by 0.1 (min 0.3)
  - Mixed results -> no change
- Applies adjustments directly to `known_issues.json` (modifies `learned_confidence` field)
- Pending learnings system: new patterns go to `pending_learnings.json` for human review
- Keeps last 500 outcomes (append-only history)

**Agent-v2 (`learning/learning_agent.py` - 262 lines)**
- Outcome recording (similar structure)
- Shorter implementation suggests less sophisticated adjustment logic
- No documented pending learnings or human review workflow

**Verdict:** Our learning agent is more mature with confidence feedback loops
and a human-in-the-loop review system for new patterns.

---

### 5. Infrastructure & Deployment

**Local Agents**
- Zero deployment overhead: agents run in-process inside `run-test-suite.py`
- Initialized via CLI flags: `--ai-agent`, `--ai-agent-dry-run`
- No container, no K8s manifests, no external services
- Knowledge base lives in `agents/knowledge_base/`

**Agent-v2**
- Full K8s deployment story:
  - `Dockerfile` (Python 3.11-slim + AWS CLI v2 + OpenShift CLI)
  - `Makefile` (build, push, deploy, undeploy targets)
  - `deploy/rbac.yaml` (ServiceAccount, ClusterRole, ClusterRoleBinding)
  - `deploy/configmap.yaml` (5 ConfigMaps, init container merge script)
  - `deploy/deployment.yaml` (init container + main container)
  - `deploy/service.yaml`
  - 6 example deployment manifests (k8s-stream, file-tail, cloudwatch, stdout-job, pipe, journald)
- `pipeline.py` (222 lines) for multi-stream orchestration
- `cli.py` (219 lines) with subcommands: `ansible`, `pytest`, `shell`, `generic`, `pipe`
- Requires `anthropic` API key for full diagnostic capability

---

### 6. Log Stream Architecture

**Local Agents**
- Two sources only:
  1. Ansible playbook stdout (piped through `process_line()`)
  2. Sidecar log file (`/tmp/deletion-agent-{cluster_name}.log`) tailed in background thread

**Agent-v2 (6 pluggable streams)**

| Stream | File | Lines | Description |
|---|---|---|---|
| `stdout_stream.py` | 65 | Process stdout/stderr |
| `file_stream.py` | 91 | Tail log files |
| `k8s_stream.py` | 247 | K8s pod logs (SDK + subprocess dual mode) |
| `pipe_stream.py` | 47 | stdin pipe |
| `cloudwatch_stream.py` | 103 | AWS CloudWatch Logs |
| `journald_stream.py` | 142 | systemd journal |

All streams implement `base_stream.py` (51 lines) interface.

---

## Strengths and Gaps

### What Our Agents Do Better

1. **Domain expertise** - Deep ROSANetwork/CloudFormation/VPC cascade logic handles
   real-world deletion edge cases that a generic agent can't match
2. **Per-resource state tracking** - TrackedIssue state machine prevents duplicate
   interventions and handles multi-resource scenarios correctly
3. **Deterministic behavior** - Rule-based diagnostics produce consistent results;
   no API variability
4. **Confidence learning** - Feedback loop adjusts pattern confidence based on
   actual outcomes over time
5. **Human review gate** - New patterns require human approval before being
   applied (safety for destructive operations)
6. **Zero dependencies on external AI services** - Works in air-gapped or
   restricted environments
7. **Tight test runner integration** - Structured context markers and real-time
   Ansible task tracking

### What Agent-v2 Does Better

1. **Generalized architecture** - Works with any test framework (pytest, shell),
   not just Ansible
2. **Pluggable log sources** - 6 stream types vs our 2; can monitor CloudWatch,
   K8s pods, journald natively
3. **AI-powered diagnostics** - Claude API can reason about novel, unseen issues
   that rule-based systems miss
4. **Standalone deployment** - Runs as K8s sidecar, Docker container, or CLI tool
   independent of the test runner
5. **Multi-stream orchestration** - Pipeline can consume multiple log sources
   simultaneously
6. **Lower barrier for new issue types** - Claude API handles new patterns without
   code changes

### Gaps in Both

| Gap | Local | Agent-v2 |
|---|---|---|
| Metrics/observability | No Prometheus/metrics endpoint | No metrics endpoint |
| Alerting | Log-only | Log-only |
| Web UI/dashboard | `report.py` generates HTML | None |
| Multi-cluster support | Single cluster per run | Possible via K8s deployment but not documented |
| Pattern versioning | No version tracking on KB changes | No version tracking |

---

## Potential Path Forward

The two implementations are complementary rather than competing:

1. **Keep our domain-specific agents** for ROSA HCP deletion workflows where
   deterministic, battle-tested logic is critical

2. **Adopt agent-v2's pluggable architecture** for the platform layer:
   - Log stream abstraction (especially K8s pod logs and CloudWatch)
   - Framework adapters (extend to pytest for unit test monitoring)
   - CLI and deployment infrastructure

3. **Integrate selectively** - Our specialized diagnostic/remediation methods
   could be registered as plugins in agent-v2's generic framework, getting the
   best of both worlds: domain expertise with platform flexibility

4. **Claude API as escalation tier** - Use our rule-based diagnostics as the
   primary engine, falling back to Claude API for unrecognized issues (novel
   error patterns the rules don't cover)

---

## File Inventory

### Local Agents (`agents/`)

| File | Lines | Purpose |
|---|---|---|
| `__init__.py` | 34 | Package exports |
| `base_agent.py` | 122 | Foundation class |
| `monitoring_agent.py` | 336 | Real-time monitoring + state machine |
| `diagnostic_agent.py` | 707 | Rule-based root cause analysis |
| `remediation_agent.py` | 442 | Autonomous fix execution |
| `learning_agent.py` | 327 | Outcome tracking + confidence adjustment |
| `aws_client.py` | 450 | boto3 wrapper |
| `report.py` | 417 | Report generation (HTML/JSON/text) |
| `test_agents.py` | ~500 | 46 unit tests |

### Agent-v2 (PR #39) - 47 files

| Directory | Files | Purpose |
|---|---|---|
| `agent-v2/` | 5 | Package root, CLI, Dockerfile, Makefile, requirements.txt |
| `agent-v2/core/` | 4 | BaseAgent, Event dataclasses, Pipeline orchestrator |
| `agent-v2/log_streams/` | 8 | 6 pluggable log source implementations |
| `agent-v2/frameworks/` | 5 | 4 framework adapters (Ansible, pytest, shell, generic) |
| `agent-v2/monitoring/` | 2 | Monitoring agent |
| `agent-v2/diagnostic/` | 3 | Diagnostic agent + Claude API client |
| `agent-v2/remediation/` | 2 | Remediation agent |
| `agent-v2/learning/` | 2 | Learning agent |
| `agent-v2/knowledge_base/` | 3 | Known issues, fix strategies, outcomes |
| `agent-v2/deploy/` | 4 | K8s manifests (RBAC, ConfigMap, Deployment, Service) |
| `agent-v2/deploy/examples/` | 6 | Example deployment configurations |
