# run-v5-rc-tests

Test OCM 5.0 Release Candidate Testing — Run ROSA HCP scenario-based tests with live monitoring, user guidance, and auto-tracking

## What this skill does

Executes end-to-end scenario-based CAPA testing for ROSA HCP clusters:
- Configures MCE environment
- Provisions ROSA HCP cluster with specified features
- Verifies all features applied correctly
- Cleans up and deletes cluster
- Automatically tracks results to RC6_TEST_RESULTS.md

**NEW: Live Monitoring & User Guidance**
- Shows real-time progress every 30 seconds (no silent waits)
- Auto-detects issues (cluster stuck >10min, feature failed, hub unreachable)
- Provides interactive troubleshooting guidance
- Suggests next steps and helps with recovery

## Usage

### Simple: scenario, prefix, version
```bash
/run-scenario day1-basic rs3 5.0.0-rc.6
```

### Interactive: prompt-driven
```bash
/run-scenario
# Prompts: Which scenario? What prefix? What version?
```

### Command-line style: flags
```bash
/run-scenario --scenario day1-basic --prefix rs3 --version 5.0.0-rc.6
```

### Keep cluster for inspection
```bash
/run-scenario day1-basic rs3 5.0.0-rc.6 --keep-cluster
# Skips delete stage, leaves cluster running
```

## Available Scenarios

| Scenario | Features | Est. Time |
|----------|----------|-----------|
| `day1-basic` | domain_prefix, AZs, tags, channel, autoscaling | ~17 min |
| `day1-combo` | day1-basic + networking | ~20 min |
| `day1-networking` | Advanced networking config | ~22 min |
| `day1-security` | External OIDC provider | ~18 min |
| `day2-machinepool` | Multi-zone machine pools | ~25 min |

## Examples

### Run day1-basic with RC6
```bash
/run-scenario day1-basic rs2 5.0.0-rc.6
```

Output:
```
🚀 Starting day1-basic scenario with rs2 prefix (5.0.0-rc.6)

📋 Test Plan:
  ├─ Configure MCE Environment
  ├─ Provision ROSA HCP cluster
  ├─ Verify feature flags
  └─ Delete cluster & cleanup

⏳ Running... [████████░░░░░░░░░░] 50%

✅ STAGE 1/4: Configure MCE Environment (34.8s)
✅ STAGE 2/4: Provision Cluster (15m 41s)
  └─ Cluster: rs2-rosa-hcp
  └─ Version: 5.0.0-rc.6
  └─ Status: Ready in AWS

✅ STAGE 3/4: Verify Features (20.3s)
  ✓ domain_prefix
  ✓ availability_zones
  ✓ additional_tags
  ✓ channel_group
  ✓ default_autoscaling

⏳ STAGE 4/4: Delete Cluster...

✅ Test Complete! Results added to RC6_TEST_RESULTS.md

📊 Summary:
   Scenario: day1-basic
   Prefix: rs2
   Version: 5.0.0-rc.6
   Features: 5/5 passed ✅
   Total Duration: 17m 12s
   Status: PASSED ✅
```

### Interactive mode
```bash
/run-scenario

? Which scenario? (day1-basic, day1-combo, day1-networking, day1-security, day2-machinepool)
> day1-combo

? Cluster prefix? (e.g., rs1, rs2, rs3)
> rs3

? OpenShift version? (e.g., 5.0.0-rc.6, 4.22.6)
> 5.0.0-rc.6

? Keep cluster running after test? (y/n)
> n

[Running test...]
```

### Keep cluster for debugging
```bash
/run-scenario day1-basic rs4 5.0.0-rc.6 --keep-cluster

# Test runs through verify, but skips delete
# Cluster stays running: oc get rosacontrolplane rs4-rosa-hcp -n ns-rosa-hcp
```

## Output

### Live progress (during test)
- Stage completion status
- Cluster creation confirmation
- Feature verification results (as they complete)
- Duration tracking

### Final summary
Shows:
- Scenario name
- Cluster prefix & version
- All features (✓ pass or ✗ fail)
- Total duration
- Exit status (PASSED/FAILED)

### Automatic tracking
Results automatically appended to:  
`/rosa-hcp-e2e/RC6_TEST_RESULTS.md`

Format:
```markdown
| Test N | scenario | prefix | version | features | stages... | result | duration |
|--------|----------|--------|---------|----------|-----------|--------|----------|
| 3 | day1-combo | rs3 | 5.0.0-rc.6 | 6 features | ✅✅✅✅ | ✅ PASS | 20m 15s |
```

## What the skill does behind the scenes

1. **Validates inputs** — Check scenario exists, prefix format, version format
2. **Sets environment** — Set AWS credentials, OCM endpoints from user_vars.yml
3. **Runs test suite** — Execute `run-test-suite.py --scenario <name> -e name_prefix=<prefix> -e openshift_version=<version>`
4. **Monitors progress** — Stream output, extract stage completions
5. **Parses results** — Extract feature verification results, cluster status
6. **Updates tracking** — Append row to RC6_TEST_RESULTS.md
7. **Cleanup** — Delete cluster (unless --keep-cluster)
8. **Reports summary** — Show final results table

## Success criteria

Test passes when:
- ✅ Configure MCE completes
- ✅ Provision creates cluster in AWS
- ✅ Verify confirms all features applied
- ✅ Delete removes all resources cleanly

If any stage fails, test is marked FAILED and cluster is NOT deleted (for investigation).

## Live Monitoring & Auto-Guidance

When you run a test, the skill monitors progress automatically:

### Real-Time Progress Display
```
⏳ STAGE 2/4: Provision ROSA HCP Cluster

[████████░░░░░░░░░░] 40% (6m 30s / ~17m elapsed)

📊 Current Activity:
  └─ Waiting for ROSANetwork to be ready
  └─ Resources: RosaRoleConfig ✓ | ROSANetwork ⏳ | RosaControlPlane ⏳
  └─ AWS VPC created: vpc-0da1e159a0faef4aa

💡 What's Happening:
AWS is creating cluster infrastructure (can take 15-20 minutes)
```

Updates every 30 seconds — no more silent waits!

### Auto-Detection & Guidance

If something goes wrong, the skill detects it and helps:

**Issue: Cluster stuck >10 minutes**
```
⚠️  ATTENTION REQUIRED

Your cluster has been waiting 10+ minutes.
Let me check what's happening...

CloudFormation status: CREATE_IN_PROGRESS (normal)
CAPA controller logs: No errors detected

Options:
  1. Keep waiting (AWS sometimes takes 20-30 min)
  2. Debug: Show AWS CloudFormation details
  3. Investigate: Show CAPA controller logs
  4. Abort: Delete resources and retry
```

**Issue: Feature verification failed**
```
❌ FEATURE VERIFICATION FAILED

Expected: 4 features
Got: 3 features (missing: audit_logging)

🔍 Root cause: log_forward_applications not configured
💡 Suggestion: Apply fix and retry

Options:
  1. View the fix
  2. Apply fix & restart test
  3. Continue anyway (partial pass)
```

**Issue: Hub cluster unreachable**
```
❌ HUB CLUSTER UNREACHABLE

Lost connection during test: "connection timed out"

Options:
  1. Check hub cluster status
  2. Reconnect to hub (logout & login)
  3. Check network connectivity
  4. Save progress & retry when hub recovers
```

### During Test Execution
Quick commands you can use anytime:
```bash
status          # Show current progress
logs            # View last 20 log lines
describe rs4    # Show cluster resource details
help            # Show available commands
abort           # Stop test and cleanup
```

---

## Troubleshooting

### "Cluster creation stuck (10+ minutes)"
The skill will **automatically detect** this and offer options:
- Keep waiting (recommended for AWS infrastructure creation)
- Debug AWS CloudFormation stack status
- Investigate CAPA controller logs
- Abort and retry

Or manually inspect:
```bash
oc describe rosacontrolplane <prefix>-rosa-hcp -n ns-rosa-hcp
oc logs -n multicluster-engine deployment/capa-controller-manager --tail=100
```

### "Feature verification failed"
Run with verbose output:
```bash
/run-scenario day1-basic rs5 5.0.0-rc.6 -v

# Shows detailed OCM API calls and CRD checks
```

### "Delete stage failed but cluster provisioned"
This is expected (code bug). To clean up:
```bash
oc patch rosanetwork <prefix>-rosa-hcp-network -n ns-rosa-hcp -p '{"metadata":{"finalizers":[]}}' --type=merge
oc patch rosaroleconfig <prefix>-rosa-hcp-roles -n ns-rosa-hcp -p '{"metadata":{"finalizers":[]}}' --type=merge
oc delete rosacontrolplane <prefix>-rosa-hcp -n ns-rosa-hcp --grace-period=0 --force
```

Or just use `rosa delete cluster` from CLI.

## Results tracking

All test results automatically appended to:  
📄 `/rosa-hcp-e2e/RC6_TEST_RESULTS.md`

View progress:
```bash
cat RC6_TEST_RESULTS.md
# Shows all tests run, pass/fail status, features, durations
```

Share with team:
```bash
# Copy RC6_TEST_RESULTS.md to team repo or Slack
# Contains full testing history + findings
```

## Performance expectations

| Scenario | Avg Duration | Bottleneck |
|----------|--------------|-----------|
| day1-basic | 17m | AWS cluster provisioning (10-15m) |
| day1-combo | 20m | VPC + networking setup |
| day1-networking | 22m | Multi-zone subnets |
| day1-security | 18m | OIDC provider setup |
| day2-machinepool | 25m | Multiple machine pools |

Most of the time is AWS provisioning. Ansible automation takes ~1-2 minutes total.

## Related files & Documentation

### Test Execution & Results
- **Tracking:** `/rosa-hcp-e2e/RC6_TEST_RESULTS.md` — Test results history
- **Plan:** `/rosa-hcp-e2e/RC6_SCENARIO_TESTING_PLAN.md` — Testing strategy
- **Runner:** `/rosa-hcp-e2e/run-test-suite.py` — Core test execution
- **MCE Guide:** `/rosa-hcp-e2e/MCE_UPGRADE_AND_CLUSTER_ATTACHMENT.md` — Architecture reference

### Skill Implementation
- **IMPLEMENTATION.md** — Detailed guide to monitoring, user guidance, and troubleshooting features
- **SKILL.md** (this file) — Quick reference and usage guide

### Reports
- **rc6-feature-coverage.html** — HTML report of all RC6 tests and feature coverage
- **rc5-feature-coverage.html** — Previous RC5 test results (for comparison)

## Team context

This skill automates the RC6 CAPA testing campaign:
- 6 scenarios to validate (4/6 complete as of Oct 16)
- Results tracked for team visibility
- Automatic cleanup prevents resource sprawl
- Ready for Jenkins integration (dual-mode Jenkinsfile pending)
