# Status Update — Week Ending 6/9/2026

## Cluster Service Migrations
**Completed:**
- migration of cs-rosa-hcp-backup-cp-upgrade-integration-main [OCM-23830]
- migration of cs-rosa-hcp-autonode-integration-main [OCM-23829]
- migration of cs-osd-gcp-wif-sv-staging-main [OCM-23818]
- migration of cs-rosa-hcp-upgrade-staging-main [OCM-23812]

## Future Sustainability [OCM-22529]
**Completed:**
- Built and shipped the automated feature testing framework for CAPI/CAPA 4.22. This allows the team to provision ROSA HCP clusters with any combination of Day 1 features using simple CLI flags (e.g., `--feature etcd-kms --feature fips`) instead of manually editing templates. The framework automatically resolves dependencies between features, validates compatibility with the target OpenShift version, and verifies after provisioning that each requested feature was correctly applied to the live cluster. This significantly reduces the manual effort required for feature regression testing and enables CI to catch template rendering issues before they reach customers. 13 of the targeted features are now fully automated with end-to-end coverage from provisioning through verification. (PRs #60-66)

**In Progress:**
- Security group automation for `--feature security-groups` testing
- Break-glass credential 403 diagnostic for external-auth clusters
