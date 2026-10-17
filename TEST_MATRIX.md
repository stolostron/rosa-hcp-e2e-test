# CAPA 5.0 Integration Test Matrix

## Overview
Comprehensive test coverage for ROSA HCP (Hosted Control Plane) with CAPA (Cluster API Provider AWS) on OpenShift 5.0.

---

## Test Configuration Options

| Configuration | Category | Test Method | Phase | Priority | Status |
|---------------|----------|-------------|-------|----------|--------|
| **ROSA HCP** | ROSA HCP | ROSA(HCP) | Day1 | P1 | ✅ |
| **Private** | Network | Manually | Day1 | P1 | ⏳ |
| **BYON** | Network | Manually | Day1 | P1 | ⏳ |
| **Proxy enabled** | Network | Manual | Day1 | N/A | ⏳ |
| **STS** | Security | Automatically | Day1 | P1 | ✅ |
| **Default Machinepool Auto Scaling** | Compute | Automatically | Day1 | P1 | ✅ |
| **Machine Pool Auto Scaling Enabled** | Compute | Automatically | Day1 | P1 | ✅ |
| **Audit log forwarding** | Logging | Automatically | Day1 | P1 | ✅ |
| **Long cluster Name** | Naming | Automatically | Day1 | P1 | ⏳ |
| **No CNI Plugin** | Network | Manually | Day1 | P1 | ⏳ |
| **Additional Tags** | Tagging | Automatically | Day1 | P1 | ✅ |
| **ETCD KMS key** | Security | Automatically | Day1 | P1 | ✅ |
| **Additional Security Group** | Security | Manually | Day1 | P1 | ⏳ |
| **Availability Zones** | Networking | Automatically | Day1 | P1 | ✅ |
| **Identify Provider** | Identity | Manually | Day1 | P1 | ⏳ |
| **External OIDC** | Identity | Manually | Day1 | P1 | ✅ |
| **DomainPrefix** | Networking | Automatically | Day1 | P1 | ✅ |
| **Parallel node upgrade** | Upgrade | Automatically | Day1 | P1 | ✅ |
| **Enable cluster autoscaler expanders** | Compute | Automatically | Day1 | P1 | ⚠️ |
| **User agent for ROSA CAPA** | Observability | Manually | Day1 | P1 | ⏳ |
| **Image registry config** | Registry | Automatically | Day1 | P1 | ✅ |
| **Set machinepool disk volume size** | Storage | Automatically | Day1 | P1 | ✅ |
| **Day2 Scenarios** | Operations | Mixed | Day2 | P1 | ⏳ |

---

## Test Scenarios

### Day1 Scenarios
These scenarios test cluster provisioning with various feature combinations.

#### day1-basic
- **Features**: Core cluster provisioning
- **Test Method**: Automatic
- **Priority**: P1
- **Status**: ✅ Passing

#### day1-combo
- **Features**: cluster_autoscaler_expander, image_registry, parallel_upgrade, disk_size
- **Test Method**: Automatic
- **Priority**: P1
- **Status**: ⚠️ cluster_autoscaler_expander warned (CRD field not available on platform)

#### day1-networking
- **Features**: private_network, byon, availability_zones
- **Test Method**: Manual
- **Priority**: P1
- **Status**: ⏳ In Progress

#### day1-security
- **Features**: external_oidc, fips, etcd_kms, security_groups
- **Test Method**: Manual
- **Priority**: P1
- **Status**: ⏳ In Progress

### Day2 Scenarios
These scenarios test cluster operations after provisioning.

#### day2-machinepool
- **Features**: Machine pool scaling, autoscaling configuration
- **Test Method**: Automatic
- **Priority**: P1
- **Status**: ✅ Passing

---

## Feature Coverage Status

### ✅ Verified (Passing)
- ROSA HCP baseline
- Default Machinepool Auto Scaling
- Machine Pool Auto Scaling
- Audit log forwarding
- Additional Tags
- ETCD KMS encryption
- Availability Zones
- External OIDC
- DomainPrefix
- Parallel node upgrade
- Image registry config
- Set machinepool disk volume size

### ⚠️ Verified with Warnings
- Enable cluster autoscaler expanders — CRD field not available on platform (platform limitation, not a bug)

### ⏳ In Progress
- Private Network
- BYON (Bring Your Own Network)
- Proxy enabled
- Long cluster Name
- No CNI Plugin
- Additional Security Group
- Identify Provider
- User agent for ROSA CAPA
- Day2 operations

---

## Test Execution Tracking

| Test Run | Cluster | Version | Scenario | Features Tested | Passed | Failed | Warned | Duration |
|----------|---------|---------|----------|-----------------|--------|--------|--------|----------|
| 2026-10-17 | rsa | 5.0.0-rc.6 | day1-combo | 4 | 3 | 0 | 1 | 14m 26s |
| 2026-10-16 | rs6 | 5.0.0-rc.6 | day2-machinepool | 5 | 5 | 0 | 0 | ~75m |

---

## Priority Levels

- **P1** — Critical path features, must pass before release
- **N/A** — Out of scope for this release cycle
- **Manual** — Requires manual test execution (not automated)
- **Automatically** — Runs as part of automated test suite

---

## Next Steps

1. **Automated Testing**: Complete day1-networking scenario
2. **Security Testing**: Complete day1-security scenario with manual steps
3. **Day2 Operations**: Expand machine pool and upgrade scenarios
4. **Documentation**: Update per-feature test results in feature matrix
