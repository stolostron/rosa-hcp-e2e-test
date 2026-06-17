# 4.22 Feature Testing: Channel Group

| Field | Value |
|-------|-------|
| Feature ID | `channel_group` |
| CLI Flag | `--feature channel-group` |
| Category | Operations |
| Phase | Day1 |
| Type | select |
| Mutable | Yes |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.channelGroup` |
| Min Version | 4.18 |
| Ansible Variable | `channel_group` |

## Description

Sets the update channel group for version availability. Controls which
OpenShift versions are available for the cluster.

Valid values: `stable`, `fast`, `candidate`.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature channel-group
```

Default: `stable`. To use a different channel:

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature channel-group \
  -e channel_group=candidate
```

## Template Rendering

When `channel_group` is defined:

```yaml
spec:
  channelGroup: candidate
```

## Verification

Asserts:
- `channelGroup` is defined
- Value is in valid set: `stable`, `fast`, `candidate`
- Matches the requested channel group

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-basic`
