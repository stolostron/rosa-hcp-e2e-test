# FeatureGuard

Automated system that keeps per-feature manifest pages accurate by detecting changes from three sources, recording audit trails, and optionally triggering test re-runs.

## Quick Start

```bash
# One command does everything
python3 scripts/feature_guard.py run

# Or enable auto-testing
python3 scripts/feature_guard.py run --auto-test
```

## Architecture

```
agents/
  feature_guard.py       Stateful orchestrator (tracker, docs, logging)
  feature_guard_constants.py   Constants, redaction patterns, keyword maps
  feature_guard_config.py      Config dataclass + YAML loader
  upstream_poller.py          GitHub API calls for upstream change detection
  advisory_manager.py         CVE scanning (Red Hat + GitHub), keyword matching
  test_runner.py              Test command building + subprocess execution

scripts/
  feature_guard.py     CLI with subcommands

agents/knowledge_base/
  feature_guard_settings.yml   Configuration (auto_record, auto_test, etc.)
  doc_tracker.json           Persistent state (SHAs, scan dates, history)
  advisories.json            CVE/advisory storage

docs/features/
  *.md                       Per-feature manifest pages
  _template.md               Template for generating new feature manifests
```

## Three Change Detection Sources

### 1. Local Code Changes

Detects when implementation files change (tasks, templates, playbooks, feature_manager.py). Ignores test code, docs, scripts, and agents.

Maps files to features by:
- Checking `FEATURE_FILE_PATTERNS` for feature-specific files (e.g., `tasks/create_security_group.yml` -> `security_groups`)
- Scanning Jinja2 templates for Ansible variable references
- Including shared files that affect all features (`feature_manager.py`, `feature-registry.yml`)

```bash
python3 scripts/feature_guard.py stale --since HEAD~5
```

### 2. Upstream CAPA Repo Changes

Polls `stolostron/cluster-api-provider-aws` for new commits. Maps upstream file paths to local features using `UPSTREAM_FILE_MAP`:

- `rosacontrolplane_types.go` -> all ROSAControlPlane features
- `rosamachinepool_types.go` -> security_groups, parallel_upgrade, disk_size
- `Dockerfile*` -> fips only
- `pkg/cloud/services/kms/*` -> etcd_kms only

Stores last-seen SHA in `doc_tracker.json` so subsequent runs are incremental.

```bash
# Auto-check (remembers last SHA)
python3 scripts/feature_guard.py watch

# Check a specific PR
python3 scripts/feature_guard.py upstream https://github.com/stolostron/cluster-api-provider-aws/pull/102
```

### 3. Security Advisories (CVEs)

Scans two feeds:
- **Red Hat Security Data API** - filters by OpenShift/ROSA products
- **GitHub Security Advisories** - checks upstream CAPA repo dependencies

Each CVE's title + description is keyword-matched to features using `ADVISORY_KEYWORD_MAP`. Only CVEs matching at least one feature are stored.

```bash
# Scan for new CVEs
python3 scripts/feature_guard.py advisory-scan

# Dry run
python3 scripts/feature_guard.py advisory-scan --dry-run

# Manually add an advisory
python3 scripts/feature_guard.py advisory-add CVE-2026-12345 "FIPS bypass" --severity critical

# Mark resolved after patching/testing
python3 scripts/feature_guard.py advisory-resolve CVE-2026-12345

# List active advisories
python3 scripts/feature_guard.py advisory-list
```

## Unified Check

Combines all three sources into one report:

```bash
python3 scripts/feature_guard.py check
```

Output:
```
Feature                   Local    Upstream   Advisory   Action
------------------------------------------------------------------------------------------
  fips                    OK       STALE      ALERT      Advisory (critical)
  security_groups         STALE    OK         OK         Review local
  etcd_kms                OK       STALE      OK         Test upstream
```

### Recording Changes

By default, `check` is read-only. Add `--record` to write detected changes into each feature manifest's Change History section:

```bash
python3 scripts/feature_guard.py check --record
```

### Auto-Testing

```bash
# Show what would run
python3 scripts/feature_guard.py check --auto-test-dry-run

# Actually run tests for affected features
python3 scripts/feature_guard.py check --auto-test

# Override 5-feature safety limit
python3 scripts/feature_guard.py check --auto-test --auto-test-max 10
```

## Full Lifecycle Run

The `run` command does everything in sequence:

```bash
python3 scripts/feature_guard.py run
```

1. Scans for new CVEs (if `advisory.enabled` in settings)
2. Checks all 3 change sources
3. Records changes in feature manifests (if `auto_record` in settings)
4. Runs tests for affected features (if `auto_test.enabled` in settings)

### Overrides

```bash
# Enable auto-test for this run only
python3 scripts/feature_guard.py run --auto-test

# Skip advisory scanning
python3 scripts/feature_guard.py run --no-advisory-scan

# JSON output for CI
python3 scripts/feature_guard.py run --json
```

## Configuration

Settings file: `agents/knowledge_base/feature_guard_settings.yml`

```yaml
auto_record: true
verbose: false

detection:
  local_since: "HEAD~1"

upstream:
  repo: "stolostron/cluster-api-provider-aws"
  branch: "backplane-2.11"

advisory:
  enabled: true
  sources:
    - redhat
    - github

auto_test:
  enabled: false
  max_features: 5
  suite_id: "20-rosa-hcp-provision"
```

Set `auto_test.enabled: true` to have the `run` command automatically execute tests when changes are detected.

## Feature Manifest Structure

Each feature manifest (`docs/features/<feature>.md`) contains:

| Section | Purpose |
|---------|---------|
| Metadata table | Feature ID, CLI flag, CRD resource, K8s field |
| Audit Status | Last verified, confidence score (HIGH/MEDIUM/LOW), open advisories |
| Description | What the feature does |
| Usage | How to run it |
| Template Rendering | What YAML it produces |
| Verification | How to verify it worked |
| Change History | Append-only log of all events (max 50 entries) |
| Test Run History | Last 10 test runs with results, duration, trigger |

### Audit Status Confidence Levels

| Level | Criteria |
|-------|----------|
| HIGH | Tested within 7 days, PASS, no advisories, not stale |
| MEDIUM | Tested within 30 days, no advisories |
| LOW | Last test FAIL, or >30 days old, or has open advisories |
| UNKNOWN | Never tested |

## Redaction

All sensitive data is automatically scrubbed before writing to docs:

| Pattern | Replacement |
|---------|-------------|
| `arn:aws:kms:us-west-2:123456789012:key/abc` | `arn:aws:***:***:***:***` |
| `sg-0123456789abcdef0` | `sg-<id>` |
| `vpc-abc12345` | `vpc-<id>` |
| `subnet-*`, `eni-*`, `igw-*`, `nat-*` | `<type>-<id>` |
| `AKIAIOSFODNN7EXAMPLE` | `<access-key-id>` |
| OpenShift API URLs | `https://api.<cluster>.<domain>:443` |
| UUIDs | `<uuid>` |
| 12-digit account IDs | `<account-id>` |

## Retention Limits

| Data | Limit | Location |
|------|-------|----------|
| Test runs in docs | 10 | `## Test Run History` |
| Change history in docs | 50 | `## Change History` |
| Tracker history lists | 200 | `doc_tracker.json` |

## CI/Jenkins Integration

```groovy
stage('Feature Health Check') {
    steps {
        sh 'python3 scripts/feature_guard.py run --json'
    }
}
```

Or as a cron job:
```
0 8 * * * cd /path/to/repo && python3 scripts/feature_guard.py run
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `run` | Full lifecycle: scan, check, record, test |
| `check` | Unified check for all 3 change sources |
| `status` | Show doc status for all features |
| `gaps` | Coverage gap analysis with suggestions |
| `stale` | Detect stale docs from local git changes |
| `watch` | Auto-check upstream repo for new changes |
| `upstream <pr_url>` | Check a specific upstream PR's impact |
| `generate <feature_id>` | Generate doc page from template |
| `update <feature_id>` | Update live test record |
| `advisory-scan` | Scan Red Hat + GitHub for new CVEs |
| `advisory-add` | Manually add an advisory |
| `advisory-list` | List active advisories |
| `advisory-resolve` | Mark advisory as resolved |

## Test Coverage

510 tests covering:
- Redaction (10 tests)
- Feature manifest agent core (14 tests)
- Doc gap analysis (6 tests)
- Upstream impact detection (16 tests)
- Upstream polling with SHA tracking (6 tests)
- Unified check_all (8 tests)
- Advisory management (15 tests)
- Advisory scanning with mocked APIs (19 tests)
- Auto-test execution (12 tests)
- Audit trail system (17 tests)
- Configuration system (9 tests)

```bash
python3 -m pytest tests/test_feature_guard.py tests/test_feature_guard_config.py -v
```
