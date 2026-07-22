# Status Update — Week Ending 6/16/2026

## Future Sustainability [OCM-22529]
**Completed:**
- Added automated security group provisioning and cleanup. When a tester runs `--feature security-groups`, the framework now creates a test security group in the cluster VPC, injects it into the ROSAMachinePool template, and automatically cleans it up during cluster deletion with ENI detach retry logic. This eliminates the need to manually create and manage AWS security groups for Day 1 feature testing. (PR #67)
- Built a diagnostic test for break-glass credential 403 errors on external-auth clusters. The diagnostic checks OCM role bindings, provisioner secret state, external auth configuration, and token validity, then provides specific remediation steps for each root cause. (PR #70)

**In Review:**
- Individual documentation for each of the 15 automated feature tests, covering usage examples, expected template output, and verification assertions. (PR #71)

**In Progress:**
- Hardening CI workflows by pinning all GitHub Actions to immutable SHA hashes and restricting token permissions to least privilege, reducing supply chain and credential exfiltration risk. (PR #69)
