# 4.22 Feature Testing: Additional Tags

| Field | Value |
|-------|-------|
| Feature ID | `additional_tags` |
| CLI Flag | `--feature tags` |
| Category | Infrastructure |
| Phase | Day1 |
| Type | key_value |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.additionalTags` |
| Min Version | 4.18 |
| Ansible Variable | `additional_tags` |

## Description

Applies custom AWS tags to all cluster resources. Default tags (env,
purpose, automated) are always applied. CI defaults add `Team: PICS`
and `Jira: RHACM4K-61815`.

## Usage

### CI defaults (recommended)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature tags
```

Uses the CI default tags: `Team: PICS`, `Jira: RHACM4K-61815`.

### Custom tags

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature tags \
  -e '{"additional_tags": {"CostCenter": "12345", "Owner": "team-platform"}}'
```

### Default tags (always applied)

These tags are rendered by the template regardless of `--feature tags`:

```yaml
additionalTags:
  env: test
  purpose: rosa-hcp-automation-testing
  automated: "true"
  network-automation: "true"
  role-automation: "true"
```

When `--feature tags` is used, the CI defaults are merged on top:

```yaml
additionalTags:
  env: test
  purpose: rosa-hcp-automation-testing
  automated: "true"
  network-automation: "true"
  role-automation: "true"
  Team: PICS
  Jira: RHACM4K-61815
```

## Verification

Asserts default tags (env, purpose, automated) present; custom tags
match if provided via `-e additional_tags={}`

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
