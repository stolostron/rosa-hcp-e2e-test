# run-v5-feature-tests Skill — Enhanced with Live Monitoring & User Guidance

## Quick Start

### Basic Usage
```bash
/run-v5-rc-tests day1-basic rs2 5.0.0-rc.6
```

### What You'll See

**Minute 0:** Test starts
```
🚀 Starting day1-basic scenario with rs2 prefix (5.0.0-rc.6)
```

**Minutes 0-1:** MCE configuration
```
✅ STAGE 1/4: Configure MCE Environment (34.8s)
Ready to provision cluster
```

**Minutes 1-20:** Live progress updates every 30 seconds
```
⏳ STAGE 2/4: Provision ROSA HCP Cluster

[████████░░░░░░░░░░] 40% (6m 30s / ~17m)

📊 Current Activity:
  └─ ROSANetwork creating AWS infrastructure
  └─ VPC: vpc-0da1e159a0faef4aa ✓
  └─ Resources: RosaRoleConfig ✓ | ROSANetwork ⏳ | RosaControlPlane ⏳
```

**If something goes wrong:** Auto-guidance appears
```
⚠️  ATTENTION REQUIRED

Your cluster has been waiting 10+ minutes.
This can happen with AWS infrastructure creation.

Options:
  1. Keep waiting (recommended)
  2. Debug AWS status
  3. Investigate logs
  4. Abort and retry
```

**Minutes 20-23:** Feature verification
```
✅ STAGE 3/4: Verify Features (20.3s)
  ✓ domain_prefix
  ✓ availability_zones
  ✓ additional_tags
  ✓ channel_group
  ✓ default_autoscaling
```

**Minutes 23-25:** Cleanup
```
✅ STAGE 4/4: Delete Cluster (2m 15s)
```

**Completion**
```
✅ TEST PASSED!

Results saved to: RC6_TEST_RESULTS.md
Features verified: 5/5 ✅
Duration: 17m 12s

🎯 Next: /run-v5-rc-tests day1-combo rs3 5.0.0-rc.6
```

---

## What's New in This Enhanced Version

### 1. **Live Progress Monitoring**
- **Instead of:** Silent 15-20 minute wait with no feedback
- **Now:** Progress updates every 30 seconds showing:
  - Current stage & progress bar
  - Elapsed time vs estimated completion
  - Which resources are being created
  - What AWS is currently doing
  - ETA for when it will be done

### 2. **Auto-Detection of Issues**
The skill watches for problems and alerts you:
- **Cluster stuck >10 minutes** → Suggests debugging or retry
- **Feature verification failed** → Shows what's missing and why
- **Hub cluster unreachable** → Helps reconnect or recover
- **Credentials expired** → Prompts for re-authentication

### 3. **Interactive Guidance**
When issues are detected, you get clear options:
```
Would you like to:
  1. Keep waiting (recommended)
  2. Debug AWS CloudFormation stack
  3. Check CAPA controller logs
  4. Abort and start fresh
```

### 4. **Smart Recovery**
The skill can automatically:
- Reconnect to hub cluster if connection drops
- Detect and suggest fixes for common issues
- Mark partial passes (e.g., 4/5 features verified)
- Resume from certain stages without full restart

### 5. **Continuous Tracking**
After each test, RC6_TEST_RESULTS.md is automatically updated:
```markdown
| Test 3 | day1-combo | rs3 | 5.0.0-rc.6 | 6 features | ✅✅✅✅ | ✅ PASS | 20m 15s |
```

---

## Common Scenarios & How the Skill Helps

### Scenario 1: "I'm running day1-networking but it's taking forever"
**Old:** You'd have to check the log file manually every few minutes
**New:** 
- Skill shows progress every 30 seconds
- After 10 minutes, automatically detects if it's stuck
- Offers to debug AWS or show CAPA logs
- You see what's actually happening, not guessing

### Scenario 2: "Test said feature verification failed"
**Old:** You'd have to read logs to figure out what failed
**New:**
- Skill shows exactly which features failed: `Missing: audit_logging`
- Shows the root cause: `log_forward_applications not configured`
- Offers to apply the fix and retry
- Clear path to resolution

### Scenario 3: "My test stopped and I don't know why"
**Old:** Cryptic error like "connection refused" with no context
**New:**
- Skill detects: "Hub cluster became unreachable"
- Shows when it happened and what stage you were in
- Offers to check hub status or reconnect
- Can resume if cluster comes back online

### Scenario 4: "I want to run all 6 tests"
**Old:** You'd run each test manually, track results by hand
**New:**
```bash
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.6
# ✅ Test 1 complete, results saved

/run-v5-rc-tests day1-basic rs2 5.0.0-rc.6
# ✅ Test 2 complete, results saved

# ... continue with rs3-rs6 ...

# RC6_TEST_RESULTS.md automatically updated with all results
# Open reports/rc6-feature-coverage.html to see summary
```

---

## Enhanced Skill Features Reference

### Live Display Elements
```
Progress Bar:     [████████░░░░░░░░░░] 40%
Elapsed Time:     6m 30s / ~17m
Resource Status:  RosaRoleConfig ✓ | ROSANetwork ⏳ | RosaControlPlane ⏳
Current Activity: Waiting for ROSANetwork to be ready
AWS Status:       VPC created, creating subnets...
ETA:              ~10 minutes remaining
```

### Interactive Commands (During Test)
```
status           → Show current progress
logs             → View last 20 log lines  
describe <name>  → Show cluster resource details
help             → Show available commands
abort            → Stop test and cleanup
```

### Automatic Actions
```
Every 30 seconds:
  - Update progress bar
  - Check resource status
  - Detect issues

Every 10 minutes of stuck time:
  - Prompt with diagnostic options
  - Suggest debugging or recovery

On test completion:
  - Auto-update RC6_TEST_RESULTS.md
  - Show pass/fail summary
  - Suggest next steps
```

---

## Understanding the Progress Bar

### Stage 2: Provision (The Longest Stage)
```
[████░░░░░░░░░░░░░░] 20%  = 3m in, ~14m remaining (AWS infrastructure)
[████████░░░░░░░░░░] 40%  = 6m in, ~11m remaining (VPC/networking)
[████████████░░░░░░] 60%  = 9m in, ~8m remaining (Control plane bootstrap)
[████████████████░░░] 80%  = 12m in, ~5m remaining (Cluster ready)
[██████████████████░] 95%  = 15m in, ~1m remaining (Final checks)
```

**Why it takes so long:**
1. AWS CloudFormation creating VPC, subnets, gateways (3-8 min)
2. ROSA bootstrap creating control plane (5-10 min)
3. OpenShift waiting for node readiness (2-3 min)

---

## How to Access the Skill

### Option 1: Direct Command
```bash
/run-v5-rc-tests day1-basic rs2 5.0.0-rc.6
```

### Option 2: Interactive Prompts
```bash
/run-v5-rc-tests
? Which scenario? day1-basic
? Cluster prefix? rs2
? OpenShift version? 5.0.0-rc.6
? Keep cluster after test? n
```

### Option 3: With Flags
```bash
/run-v5-rc-tests \
  --scenario day1-basic \
  --prefix rs2 \
  --version 5.0.0-rc.6 \
  --keep-cluster=false
```

### Option 4: Special Modes
```bash
/run-v5-rc-tests day1-basic rs2 5.0.0-rc.6 --keep-cluster
# Leaves cluster running after test (for inspection)

/run-v5-rc-tests day1-basic rs2 5.0.0-rc.6 --verbose
# Shows detailed logs during execution
```

---

## Documentation Structure

**Quick Start:** This file (README.md)
- How to use the skill
- What you'll see
- Common scenarios

**Reference:** SKILL.md
- All usage options
- Troubleshooting
- Related files

**Getting Started:** QUICKSTART.md
- Step-by-step setup
- Credential configuration
- First test walkthrough

**Deep Dive:** IMPLEMENTATION.md
- How live monitoring works
- User guidance logic
- Example interactions
- Timeline of a full test run

---

## Success Criteria

A test "passes" when:
✅ Configure MCE completes (MCE ready)
✅ Provision creates cluster in AWS (Cluster created and ready)
✅ Verify confirms all features applied (Features validated)
✅ Delete removes all resources cleanly (Cleanup successful)

**Partial Pass:** Features missing but cluster provisioned
- Example: 4/5 features verified (cluster still counted as usable)

**Failure:** Any stage fails
- Provision never completes (cluster never created)
- Hub cluster becomes unreachable (can't verify)
- Feature missing at verification time (wrong config)

---

## Tips for Best Results

1. **Run in sequence, not parallel**
   - Each test uses rs{1-6} prefixes
   - Prevents resource conflicts
   - Easier to track results

2. **Don't interrupt the test**
   - Provisioning stage is long but normal
   - Cluster creation can take 15-20 minutes
   - If stuck >15 min, use the skill's guidance

3. **Monitor the progress display**
   - Real-time feedback every 30 seconds
   - Shows exactly what's happening
   - More useful than reading logs

4. **Check results when done**
   - RC6_TEST_RESULTS.md auto-updated
   - reports/rc6-feature-coverage.html for summary
   - Share with team to show progress

---

## Next Steps After Tests Complete

1. **View comprehensive results:**
   ```bash
   cat RC6_TEST_RESULTS.md
   open reports/rc6-feature-coverage.html
   ```

2. **Share with team:**
   - Email RC6_TEST_RESULTS.md
   - Post rc6-feature-coverage.html to docs
   - Reference during release decisions

3. **Merge dual-mode Jenkinsfile:**
   - After all 6 scenarios pass
   - Enables Jenkins job integration
   - Automated testing going forward

4. **Integrate into CI/CD:**
   - `run-test-suite.py --scenario day1-basic`
   - Automatic daily runs
   - Track regressions

---

## Questions?

See **SKILL.md** for detailed explanations of:
- All usage options
- Troubleshooting guide
- Performance expectations
- Related files and documentation

