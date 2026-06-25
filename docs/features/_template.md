# {version} Feature Testing: {feature_name}

| Field | Value |
|-------|-------|
| Feature ID | `{feature_id}` |
| CLI Flag | `--feature {cli_alias}` |
| Category | {category} |
| Phase | {phase} |
| Type | {feature_type} |
| Mutable | {mutable} |
| Requires Input | {requires_input} |
| CRD Resource | `{resource}` |
| K8s Field | `{k8s_field}` |
| Min Version | {min_version} |
| Ansible Variable | `{ansible_var}` |

## Audit Status

| Metric | Value |
|--------|-------|
| Last Verified | {audit_last_verified} |
| Last Result | {audit_last_result} |
| Days Since Last Test | {audit_days_since_test} |
| Open Advisories | {audit_open_advisories} |
| Local Code Stale | {audit_local_stale} |
| Upstream Stale | {audit_upstream_stale} |
| Test Confidence | {audit_confidence} |

## Description

{description}

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature {cli_alias}
```

## Template Rendering

When `{ansible_var}` is set:

```yaml
spec:
  {k8s_field_short}: {rendered_value}
```

## Verification

{verification_notes}

## Files

| File | Purpose |
|------|---------|
{file_table_rows}

## Test Coverage

| Test | File | What it verifies |
|------|------|-----------------|
{test_table_rows}

## Change History

| Date | Source | Event | Details |
|------|--------|-------|---------|
{change_history_rows}

## Test Run History

### {test_run_date}
| Field | Value |
|-------|-------|
| Version | `{test_run_version}` |
| Region | `{test_run_region}` |
| Provision Result | {test_run_result} |
| Provision Duration | `{test_run_duration}` |
| Trigger | {test_run_trigger} |

## Suggested Related Tests

{suggested_tests}

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `{feature_group}`
