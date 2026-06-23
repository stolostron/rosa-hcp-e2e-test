# 4.22 Feature Testing: FIPS Mode

| Field | Value |
|-------|-------|
| Feature ID | `fips` |
| CLI Flag | `--feature fips` |
| Category | Security & Authentication |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.fips` |
| Min Version | 4.21 |
| Ansible Variable | `fips` |

## Description

Enables FIPS 140-2 compliance mode on the cluster. Automatically resolves
`etcd_kms` as a dependency (FIPS requires etcd encryption).

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature fips \
  -e etcd_encryption_kms_arn=arn:aws:kms:us-west-2:123456789012:key/example
```

The `etcd_kms` dependency is auto-resolved, but you must still provide the
KMS ARN via `-e` since it requires input.

## Template Rendering

When `fips` is `true`:

```yaml
spec:
  fips: "Enabled"
  etcdEncryptionKMSARN: arn:aws:kms:us-west-2:123456789012:key/example
```

## Verification

Uses `aws ec2 describe-instances` and `aws ec2 describe-images` to verify
worker nodes are running a FIPS-enabled AMI:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:kubernetes.io/cluster/<cluster>,Values=owned" \
  --query 'Reservations[0].Instances[0].ImageId'

aws ec2 describe-images --image-ids <ami_id> \
  --query 'Images[0].{Name:Name,Description:Description}'
```

Asserts:
- Worker AMI name or description contains `fips`

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- [ETCD KMS Encryption](etcd-kms.md) (auto-resolved dependency)
- Feature Group: `day1-security`
