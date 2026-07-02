# 4.22 Feature Testing: Audit Log Forwarding

| Field | Value |
|-------|-------|
| Feature ID | `audit_logging` |
| CLI Flag | `--feature log-forwarding` |
| Category | Operations |
| Phase | Day1 + Day2 (mutable) |
| Type | boolean |
| Mutable | Yes |
| Requires Input | Yes |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.cloudWatchlogForwarder`, `.spec.s3LogForwarder` |
| Min Version | 4.20 |
| Ansible Variable | `log_forward_enabled` |

## Description

Forwards cluster audit logs to CloudWatch and/or S3. At least one
destination must be configured via extra vars. CloudWatch and S3 can
be used independently or simultaneously.

Required extra vars (at least one set):
- **CloudWatch**: `log_forward_cloudwatch_role_arn` and/or `log_forward_cloudwatch_log_group`
- **S3**: `log_forward_s3_bucket` and/or `log_forward_s3_prefix`
- **Applications filter** (optional): `log_forward_applications` (valid: `application`, `infrastructure`, `audit-webhook`)

## Usage

### CloudWatch only

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature log-forwarding \
  -e log_forward_cloudwatch_role_arn=arn:aws:iam::123456789012:role/example \
  -e log_forward_cloudwatch_log_group=/rosa/audit-logs
```

### S3 only

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature log-forwarding \
  -e log_forward_s3_bucket=my-audit-bucket \
  -e log_forward_s3_prefix=rosa/logs
```

### Both CloudWatch and S3

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature log-forwarding \
  -e log_forward_cloudwatch_role_arn=arn:aws:iam::123456789012:role/example \
  -e log_forward_cloudwatch_log_group=/rosa/audit-logs \
  -e log_forward_s3_bucket=my-audit-bucket \
  -e log_forward_s3_prefix=rosa/logs
```

### With application filter

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature log-forwarding \
  -e log_forward_cloudwatch_role_arn=arn:aws:iam::123456789012:role/example \
  -e '{"log_forward_applications": ["application", "infrastructure", "audit-webhook"]}'
```

## Template Rendering

### CloudWatch configuration

When `log_forward_cloudwatch_role_arn` and/or `log_forward_cloudwatch_log_group`
are provided:

```yaml
spec:
  cloudWatchlogForwarder:
    applications:
      - application
      - infrastructure
      - audit-webhook
    cloudWatchLogRoleArn: arn:aws:iam::123456789012:role/example
    cloudWatchLogGroupName: /rosa/audit-logs
```

### S3 configuration

When `log_forward_s3_bucket` and/or `log_forward_s3_prefix` are provided:

```yaml
spec:
  s3LogForwarder:
    applications:
      - application
      - infrastructure
      - audit-webhook
    s3ConfigBucketName: my-audit-bucket
    s3ConfigBucketPrefix: rosa/logs
```

Both blocks are rendered independently — they can coexist in the same
ROSAControlPlane spec. The `applications` list is optional and only
rendered if `log_forward_applications` is defined.

Without any log forwarding vars, no `cloudWatchlogForwarder` or
`s3LogForwarder` blocks are rendered.

## Verification

Uses AWS CLI to verify log forwarding destinations exist:

**CloudWatch**:
```bash
aws iam get-role --role-name <role_name>
aws logs describe-log-groups --log-group-name-prefix <log_group> --region <region>
```

**S3**:
```bash
aws s3api head-bucket --bucket <bucket_name>
```

Asserts:
- CloudWatch IAM role exists and ARN matches the requested value
- CloudWatch log group exists in the target region
- S3 bucket exists (if `log_forward_s3_bucket` was provided)

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Feature Group: `day1-networking`
