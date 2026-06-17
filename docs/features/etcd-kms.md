# 4.22 Feature Testing: ETCD KMS Encryption

| Field | Value |
|-------|-------|
| Feature ID | `etcd_kms` |
| CLI Flag | `--feature etcd-kms` |
| Category | Security & Authentication |
| Phase | Day1 |
| Type | string |
| Mutable | No |
| Requires Input | Yes |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.etcdEncryptionKMSARN` |
| Min Version | 4.19 |
| Ansible Variable | `etcd_encryption_kms_arn` |

## Description

Encrypts etcd data at rest using an AWS KMS key. The KMS ARN must be
provided via `-e etcd_encryption_kms_arn=arn:aws:kms:...`. The feature
flag enables the check but does not supply a default value.

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature etcd-kms \
  -e etcd_encryption_kms_arn=arn:aws:kms:us-west-2:123456789012:key/example
```

In Jenkins, pass the ARN via the `ETCD_KMS_ARN` parameter.

## Template Rendering

When `etcd_encryption_kms_arn` is provided:

```yaml
spec:
  etcdEncryptionKMSARN: arn:aws:kms:us-west-2:123456789012:key/example
```

Without the ARN, the field is omitted entirely.

## Verification

Asserts:
- `etcdEncryptionKMSARN` is defined and non-empty
- Value starts with `arn:aws:kms:`
- If a specific ARN was requested, the value matches exactly

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- [FIPS Mode](fips.md) (requires this as a dependency)
- Feature Group: `day1-security`
