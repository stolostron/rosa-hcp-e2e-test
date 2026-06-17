# 4.22 Feature Testing: Audit Log Forwarding

| Field | Value |
|-------|-------|
| Feature ID | `audit_logging` |
| CLI Flag | `--feature log-forwarding` |
| Category | Operations |
| Phase | Day1 |
| Type | boolean |
| Mutable | Yes |
| Requires Input | Yes |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.cloudWatchlogForwarder` |
| Min Version | 4.20 |
| Ansible Variable | `log_forward_enabled` |

## Description

Forwards cluster audit logs to CloudWatch or S3. Requires additional
vars for the destination configuration.

## Usage

### CloudWatch

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature log-forwarding \
  -e log_forward_cloudwatch_role_arn=arn:aws:iam::123456789012:role/example \
  -e log_forward_cloudwatch_log_group=/rosa/audit-logs
```

### S3

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature log-forwarding \
  -e log_forward_s3_bucket=my-audit-bucket \
  -e log_forward_s3_prefix=rosa/logs
```

## Template Rendering

### CloudWatch configuration

```yaml
spec:
  cloudWatchlogForwarder:
    cloudWatchLogRoleArn: arn:aws:iam::123456789012:role/example
    cloudWatchLogGroupName: /rosa/audit-logs
```

### S3 configuration

```yaml
spec:
  s3LogForwarder:
    s3ConfigBucketName: my-audit-bucket
    s3ConfigBucketPrefix: rosa/logs
```

Both can be configured simultaneously.

## Verification

Asserts:
- `cloudWatchlogForwarder` is defined
- CloudWatch role ARN and/or log group match requested values if provided

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-networking`
