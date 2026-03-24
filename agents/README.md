# AI Agent Framework for ROSA HCP Test Automation

## Overview

The AI Agent Framework provides **autonomous issue detection and remediation** for ROSA HCP (Red Hat OpenShift Service on AWS - Hosted Control Plane) test automation. It monitors test execution output in real-time, diagnoses issues as they occur, and automatically applies fixes to keep tests running.

This framework is designed as a **reference pattern** for adding self-healing capabilities to any Ansible-based test pipeline.

## Key Features

- **Real-Time Monitoring**: Line-by-line analysis of test output as it streams
- **Per-Resource State Machine**: `DETECTED -> DIAGNOSING -> REMEDIATING -> RESOLVED / FAILED` lifecycle prevents duplicate interventions
- **Single Source of Truth**: All detection patterns defined in `known_issues.json` -- no hardcoded keyword matching
- **Structured Context Markers**: `#AGENT_CONTEXT:` protocol for deterministic resource extraction from playbook output
- **Non-Blocking Remediation**: Advisory backoff instead of `time.sleep()` that would freeze CI pipelines
- **Confidence Scoring**: Only intervenes when diagnosis confidence >= 70%
- **Dry-Run Mode**: Test agent behavior without applying fixes

## Architecture

```
+-------------------------------------------------------------+
|                     Test Suite Runner                        |
|                   (run-test-suite.py)                        |
+--------------------------+----------------------------------+
                           | Line-by-line streaming
                           v
+-------------------------------------------------------------+
|                  Monitoring Agent                            |
|  * Processes output in real-time                            |
|  * Detects issues via JSON pattern matching                 |
|  * Per-resource state machine (TrackedIssue)                |
|  * Parses #AGENT_CONTEXT markers                            |
|  * Clears context on TASK boundaries                        |
+--------------------------+----------------------------------+
                           | Issue detected + resource_key
                           v
+-------------------------------------------------------------+
|                 Diagnostic Agent                             |
|  * Determines root cause                                    |
|  * Queries Kubernetes resources (oc/kubectl)                |
|  * Provides confidence score                                |
|  * Supports multiple resource types via resource_type param |
+--------------------------+----------------------------------+
                           | Diagnosis + recommended fix
                           v
+-------------------------------------------------------------+
|                Remediation Agent                             |
|  * Executes autonomous fixes                                |
|  * Tracks success rates                                     |
|  * Feeds result back to monitor state machine               |
+-------------------------------------------------------------+
```

### State Machine

Each detected issue is tracked per-resource through a lifecycle:

```
DETECTED --> DIAGNOSING --> REMEDIATING --> RESOLVED
                                       \-> FAILED (can retry up to max_attempts)
```

This prevents the same issue from triggering multiple interventions while allowing retries after failure. The `resource_key` (e.g., `ns-rosa-hcp/my-cluster`) is captured at detection time and passed through the callback so the correct tracked issue is resolved.

### Structured Context Markers

Ansible playbooks can emit structured context for deterministic resource extraction:

```yaml
- name: Emit agent context
  debug:
    msg: "#AGENT_CONTEXT: resource_name={{ resource_name }} namespace={{ namespace }} resource_type=rosanetwork"
```

The monitoring agent parses these markers and clears them on each new `TASK [...]` boundary to prevent stale context from leaking between tasks.

## Quick Start

### Enable AI Agents

```bash
# Enable AI agents with live remediation
./run-test-suite.py 20-rosa-hcp-provision --ai-agent

# Enable AI agents in dry-run mode (detect and diagnose only)
./run-test-suite.py 20-rosa-hcp-provision --ai-agent --ai-agent-dry-run

# Combine with verbose mode for detailed agent logging
./run-test-suite.py 20-rosa-hcp-provision --ai-agent -vv
```

### Running Tests

```bash
# Run the agent framework tests
python3 agents/test_agents.py
```

### Example Output

```
Initializing AI Agent Framework...
AI Agent Framework initialized (LIVE MODE)
  - Monitoring Agent: Real-time issue detection
  - Diagnostic Agent: Root cause analysis
  - Remediation Agent: Autonomous fixes

================================================================================
CAPA Test Suite Runner
================================================================================

[Test execution begins...]

AI Agent detected issue: rosanetwork_stuck_deletion
   Root cause: ROSANetwork has finalizers preventing deletion
   Confidence: 95%
   Recommended fix: remove_finalizers
   Fix applied: Successfully removed finalizers from rosanetwork/test-cluster

[Test execution continues...]

================================================================================
FINAL RESULTS SUMMARY:
   Total Tests: 3
   Passed: 3
   Failed: 0
   Total Duration: 15m 42s

AI AGENT STATISTICS:
   Issues Detected: 2
   Interventions: 2

   Fix Success Rates:
      remove_finalizers: 100.0% (1/1)
      backoff_and_retry: 100.0% (1/1)
================================================================================
```

## Detected Issue Patterns

All patterns are defined in `knowledge_base/known_issues.json` (single source of truth).

| Issue Type | Auto-Fix | Severity | Description |
|---|---|---|---|
| `rosanetwork_stuck_deletion` | Yes | high | ROSANetwork stuck with finalizers preventing deletion |
| `vpc_deletion_failure` | Yes | high | VPC deletion blocked by orphaned ENIs/security groups |
| `api_rate_limit` | Yes | low | API rate limiting (429, throttle errors) |
| `cloudformation_deletion_failure` | No | high | CloudFormation stack deletion failure |
| `ocm_auth_failure` | Partial | medium | OCM authentication failure (expired token) |
| `capi_not_installed` | No | high | CAPI/CAPA controllers not installed or running |
| `repeated_timeouts` | No | medium | Operations timing out repeatedly |
| `resource_quota_exceeded` | No | medium | AWS resource quota exceeded |
| `networking_configuration_error` | No | high | Subnet/VPC configuration errors |
| `iam_permission_error` | No | high | IAM permission or access denied errors |

## Knowledge Base

### `knowledge_base/known_issues.json`

The single source of truth for issue detection. Each pattern defines:
- `type`: Issue identifier (must match diagnostic agent method names)
- `pattern`: Regex for detection (with negative lookahead to avoid self-triggering)
- `severity`: high / medium / low
- `auto_fix`: Whether the framework can remediate automatically
- `description`, `symptoms`, `common_causes`: Documentation

### `knowledge_base/fix_strategies.json`

Operator runbook documentation for each issue type. Contains step-by-step procedures, required commands, prerequisites, success criteria, and rollback procedures. Referenced by operators when manual intervention is needed.

## Agent Components

### Base Agent (`base_agent.py`)

Foundation class providing:
- Color-coded logging (debug, info, warning, error, success)
- Regex pattern matching against knowledge base
- Intervention recording (in-memory)
- Lazy-loaded knowledge base via `@property`
- Execution context management

### Monitoring Agent (`monitoring_agent.py`)

Real-time output monitoring with per-resource state machine:
- Line-by-line processing with 50-line context buffer
- `TrackedIssue` class with `IssueState` enum for lifecycle management
- `#AGENT_CONTEXT:` marker parsing with context isolation per TASK
- All detection via JSON patterns only (no hardcoded keywords)

**Callback signature:**
```python
def issue_callback(issue_type: str, context: Dict, issue: Dict) -> None:
    # context includes "resource_key" for feeding back to state machine
    resource_key = context["resource_key"]
    # ... diagnose and remediate ...
    monitor.mark_issue_resolved(issue_type, resource_key)
```

### Diagnostic Agent (`diagnostic_agent.py`)

Root cause analysis with resource extraction priority:
1. Structured context fields (from `#AGENT_CONTEXT` markers) -- most reliable
2. Buffer parsing for `oc`/`kubectl` commands
3. Buffer parsing for output tables (`NAME  AGE` format)
4. Task name parsing with skip-word filtering -- least reliable

Supports multiple resource types via `resource_type` parameter (default: `rosanetwork`).

### Remediation Agent (`remediation_agent.py`)

Autonomous fix execution:
- Fix routing via method dispatch dictionary
- Success rate tracking per fix type
- Non-blocking backoff (advisory, not `time.sleep()`)
- Dry-run mode support
- All fix results fed back to monitor state machine

## Configuration

### Confidence Threshold

Automatic remediation requires diagnosis confidence >= 70%:
```python
if diagnosis.get('confidence', 0) >= 0.7:
    success, message = self.remediation_agent.remediate(diagnosis)
```

### Verbosity Levels

- **Default**: Shows only issue detection and fix results
- **-v**: Adds agent debug logging
- **-vv+**: Detailed agent operation logs

## Safety Features

- **Disabled by default** -- must explicitly enable with `--ai-agent`
- **Fail-safe error handling** -- agent errors never break test execution
- **Per-resource state machine** -- prevents duplicate interventions
- **Max attempts** -- stops retrying after 3 failed attempts per issue
- **Confidence threshold** -- only acts on high-confidence diagnoses
- **Audit trail** -- all interventions recorded with timestamps and parameters

## Extending the Framework

### Adding a New Issue Pattern

1. Add pattern to `knowledge_base/known_issues.json`:
```json
{
  "type": "new_issue_type",
  "pattern": "your-regex-here",
  "severity": "high",
  "auto_fix": true,
  "description": "Description of the issue"
}
```

2. Add diagnostic method to `diagnostic_agent.py`:
```python
def _diagnose_new_issue(self, context: Dict) -> Dict:
    return {
        "issue_type": "new_issue_type",
        "root_cause": "Root cause description",
        "severity": "high",
        "confidence": 0.9,
        "evidence": [],
        "recommended_fix": "new_fix_strategy",
        "fix_parameters": {}
    }
```

3. Register it in the `diagnosis_methods` dict in `diagnose()`.

4. Add remediation method to `remediation_agent.py` and register it in `fix_methods`.

5. Add operator runbook to `knowledge_base/fix_strategies.json`.

6. Add tests to `test_agents.py`.

## Using as a Reference Pattern

To adapt this framework for other test automation:

1. **Replace patterns**: Update `known_issues.json` with your domain-specific error patterns
2. **Add diagnostics**: Write `_diagnose_*` methods that inspect your infrastructure
3. **Add remediations**: Write `_fix_*` methods for your automated fixes
4. **Hook into your runner**: Call `monitor.process_line(line)` on each output line
5. **Wire the callback**: Connect monitor -> diagnostic -> remediation chain
6. **Feed back results**: Pass `resource_key` to `mark_issue_resolved`/`mark_issue_failed`

The framework handles the rest: state machine, duplicate prevention, retry logic, context isolation, and audit trail.

---

**Version**: 0.1.0
**Author**: Tina Fitzgerald
**Created**: March 3, 2026
