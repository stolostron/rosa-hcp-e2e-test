# Status Update — Week Ending 6/2/2026

## Cluster Service Migrations
**Completed:**
- migration of cs-rosa-hcp-autonode-staging-main [OCM-23828]
- migration of cs-rosa-hcp-amd64-staging-main [OCM-23817]
- migration of cs-rosa-hcp-arm-staging-main [OCM-23816]
- migration of cs-rosa-hcp-amd64-upgrade-staging-main [OCM-23813]
- migration of cs-rosa-sts-upgrade-staging-main [OCM-23811]

**In Progress:**
- migration of cs-rosa-hcp-backup-cp-upgrade-integration-main [OCM-23830]
- migration of cs-rosa-hcp-autonode-integration-main [OCM-23829]
- migration of cs-osd-gcp-wif-sv-staging-main [OCM-23818]
- migration of cs-rosa-hcp-upgrade-staging-main [OCM-23812]

## Future Sustainability
**Completed:**
- Modified Jenkinsfile to reorder archive and restore HyperShift steps for CAPA e2e tests
- Completed Sprint 4 regression testing on 2 environments
- Verify playbook distinguishes CRD limitations from template failures (PR #59)
- Synced Jenkinsfile from tf_test for feature flag testing (PR #52)

**In Progress:**
- Major focus on automating CAPI/CAPA 4.22 feature testing. 6 features marked as automated, working on 7 more [OCM-22529]
