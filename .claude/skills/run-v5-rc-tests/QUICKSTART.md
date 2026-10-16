# Quick Start: run-v5-rc-tests

**Run a complete RC6 test in one command.**

---

## 30-Second Test

```bash
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.6
```

That's it! The skill handles everything:
- ✅ Configures MCE environment
- ✅ Provisions ROSA HCP cluster in AWS
- ✅ Verifies all features applied correctly
- ✅ Cleans up and deletes cluster
- 📊 Auto-updates RC6_TEST_RESULTS.md

**Runtime:** ~17 minutes (mostly AWS provisioning)

---

## Before You Start: Set Hub Credentials

The skill needs your hub cluster credentials. Choose one method:

### Option 1: Environment Variables (Simplest)
```bash
export OCP_HUB_API_URL="https://api.ci-yupgrade-sp11.gcp.dev09.red-chesterfield.com:6443"
export OCP_HUB_CLUSTER_USER="kubeadmin"
export OCP_HUB_CLUSTER_PASSWORD="your-password-here"

# Now run tests
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.6
```

### Option 2: vars/user_vars.yml (Persistent)
Create `vars/user_vars.yml` in the rosa-hcp-e2e repo:
```yaml
OCP_HUB_API_URL: "https://api.ci-yupgrade-sp11.gcp.dev09.red-chesterfield.com:6443"
OCP_HUB_CLUSTER_USER: "kubeadmin"
OCP_HUB_CLUSTER_PASSWORD: "your-password-here"
AWS_REGION: "us-west-2"
AWS_ACCOUNT_ID: "471112697682"
AWS_ACCESS_KEY_ID: "your-key-here"
AWS_SECRET_ACCESS_KEY: "your-secret-here"
OCM_API_URL: "https://api.stage.openshift.com"
OCM_CLIENT_ID: "your-client-id"
OCM_CLIENT_SECRET: "your-client-secret"
MCE_NAMESPACE: "multicluster-engine"
```

### Option 3: Jenkins Credentials (For CI/CD)
Jenkins manages credentials via secrets — no file needed.

---

## Available Scenarios & Versions

Pick any scenario, prefix, and OpenShift version:

### By Scenario
```bash
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.6      # Core features (17 min)
/run-v5-rc-tests day1-combo rs2 5.0.0-rc.6      # + Networking (20 min)
/run-v5-rc-tests day1-networking rs3 5.0.0-rc.6 # Advanced networking (22 min)
/run-v5-rc-tests day1-security rs4 5.0.0-rc.6   # + OIDC (18 min)
/run-v5-rc-tests day2-machinepool rs5 5.0.0-rc.6 # Multi-pool (25 min)
```

### By OpenShift Version
```bash
# RC6 (latest)
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.6

# RC5
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.5

# Release versions
/run-v5-rc-tests day1-basic rs1 5.0.0
/run-v5-rc-tests day1-basic rs1 4.22.6
/run-v5-rc-tests day1-basic rs1 4.22.0
```

---

## Interactive Mode

Don't remember the syntax? Let the skill prompt you:

```bash
/run-v5-rc-tests

? Which scenario? (day1-basic, day1-combo, day1-networking, day1-security, day2-machinepool)
> day1-basic

? Cluster prefix? (e.g., rs1, rs2, rs3)
> rs2

? OpenShift version? (e.g., 5.0.0-rc.6, 4.22.6)
> 5.0.0-rc.6

? Keep cluster running after test? (y/n)
> n

[Running test...]
```

---

## Keep Cluster for Debugging

Skip deletion and leave cluster running for inspection:

```bash
/run-v5-rc-tests day1-basic rs3 5.0.0-rc.6 --keep-cluster

# Cluster stays running: rs3-rosa-hcp
# Inspect with: oc get rosacontrolplane rs3-rosa-hcp -n ns-rosa-hcp
```

---

## What You'll See

### Real-Time Progress (every 30 seconds)
```
⏳ STAGE 2/4: Provision ROSA HCP Cluster

[████████░░░░░░░░░░] 40% (6m 30s / ~17m elapsed)

📊 Current Activity:
  └─ Waiting for ROSANetwork to be ready
  └─ Resources: RosaRoleConfig ✓ | ROSANetwork ⏳ | RosaControlPlane ⏳
  └─ AWS VPC created: vpc-0da1e159a0faef4aa
```

### Final Results
```
✅ TEST PASSED!

📊 Summary:
  Scenario: day1-basic
  Prefix: rs1
  Version: 5.0.0-rc.6
  Features: 5/5 passed ✅
  Duration: 17m 12s
  
Results saved to: RC6_TEST_RESULTS.md
```

---

## Auto-Troubleshooting

If something goes wrong, the skill detects it and helps:

**Cluster stuck >10 minutes?**
```
⚠️  ATTENTION REQUIRED

Your cluster has been waiting 10+ minutes.
Would you like to:
  1. Keep waiting (AWS sometimes takes 20-30 min)
  2. Debug: Show AWS CloudFormation details
  3. Investigate: Show CAPA controller logs
  4. Abort: Delete resources and retry
```

**Feature verification failed?**
```
❌ FEATURE VERIFICATION FAILED

Missing: audit_logging
Root cause: log_forward_applications not configured

Would you like to:
  1. View the fix
  2. Apply fix & restart test
  3. Continue anyway (partial pass)
```

---

## Results Auto-Tracking

After each test completes, the skill **automatically updates** your test results document.

### What Gets Recorded
📄 `RC6_TEST_RESULTS.md` — Master test results file

Each test adds a row like:
```
| Test 5 | day1-combo | rs5 | 5.0.0-rc.6 | 6 features | ✅✅✅✅ | ✅ PASS | 20m 15s |
```

Tracking includes:
- ✅ Scenario name
- ✅ Cluster prefix & version
- ✅ Features tested
- ✅ Stage results (Configure, Provision, Verify, Delete)
- ✅ Pass/Fail status
- ✅ Duration

### View Results
```bash
# View all tests
cat RC6_TEST_RESULTS.md

# View latest test only
tail -5 RC6_TEST_RESULTS.md

# View HTML report (if available)
open reports/rc6-feature-coverage.html
```

### Share with Team
```bash
# Email or post to Slack
cat RC6_TEST_RESULTS.md
```

**No manual documentation needed** — the skill keeps everything up-to-date!

---

## Credential Verification

Check your credentials are set correctly:

```bash
echo "Hub API: $OCP_HUB_API_URL"
echo "Hub User: $OCP_HUB_CLUSTER_USER"
echo "Hub Pass: ${OCP_HUB_CLUSTER_PASSWORD:0:5}..." # Shows first 5 chars
```

Or check the vars file:
```bash
grep OCP_HUB vars/user_vars.yml
```

---

## Common Issues

**"CAPI_TEST_LOG_S3_BUCKET not set"**
→ Use a simpler scenario (day1-basic, day1-combo) that don't need S3

**"Hub cluster unreachable"**
→ Reconnect: `oc login <hub-api-url>`

**"Cluster creation stuck"**
→ Let the skill's auto-guidance help, or manually check:
```bash
oc describe rosacontrolplane <prefix>-rosa-hcp -n ns-rosa-hcp
oc logs -n multicluster-engine deployment/capa-controller-manager
```

**"Credentials not found"**
→ Set them before running:
```bash
export OCP_HUB_API_URL="https://..."
export OCP_HUB_CLUSTER_USER="kubeadmin"
export OCP_HUB_CLUSTER_PASSWORD="..."
```
Or create `vars/user_vars.yml` (see "Before You Start" section above)

**"Connection refused / 401 Unauthorized"**
→ Check credentials are correct:
```bash
oc login $OCP_HUB_API_URL -u $OCP_HUB_CLUSTER_USER -p $OCP_HUB_CLUSTER_PASSWORD
```
If login fails, credentials need to be updated.

---

## Need More Details?

See **SKILL.md** for full reference and **README.md** for intermediate guide.

---

**Ready? Go!**
```bash
/run-v5-rc-tests day1-basic rs1 5.0.0-rc.6
```
