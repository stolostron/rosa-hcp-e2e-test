# Shipped Work: ROSA HCP Scenario System (PRs #170-175)

## JIRA #1: Scenario System Foundation

**Title**: Establish scenario-based testing framework for OpenShift 5.0 RC validation

**Type**: Feature

**Status**: DONE (Merged PR #170, Oct 13, 2026)

**Description**:
Transitioned the test infrastructure from ad-hoc feature assembly to declarative scenario-based testing. This foundational work enables operators to run complete test suites via simple commands (e.g., `run-test-suite --scenario day1-security`) instead of manually composing 8+ CLI flags.

**Key Deliverables**:
- Scenario schema definition (YAML-driven, version-aware)
- ScenarioManager class for resolution, validation, and version compatibility computation
- 5 pre-built scenarios: day1-basic, day1-combo, day1-security, day1-networking, day2-machinepool
- CLI flag `--scenario` in run-test-suite.py for scenario selection
- Automatic version compatibility tracking (scenarios work across 4.22, 4.23, 5.0 without edits)
- 5.0.0-rc.0 build pinning for EC (early-candidate) release channel
- Input validation and environment variable substitution
- 570+ tests (401 for feature_manager.py, 169 for run_test_suite.py)

**Files Modified**:
- `feature_manager.py` — ScenarioManager class (500+ LOC)
- `run-test-suite.py` — CLI integration (1200+ LOC)
- `templates/schemas/feature-registry.yml` — Scenario definitions (300+ LOC)
- `templates/schemas/version-compatibility.yml` — Version matrix
- `tests/test_feature_manager.py` — Scenario tests (401 tests)
- `tests/test_run_test_suite.py` — CLI tests (169 tests)
- `Makefile`, `README.md` — Documentation updates

**Acceptance Criteria** (ALL MET):
- ✅ Scenarios defined declaratively in YAML (no hardcoded Python configs)
- ✅ ScenarioManager resolves features → Ansible vars automatically
- ✅ Version compatibility computed from feature matrix (not hardcoded per scenario)
- ✅ 5.0 EC builds auto-pinned to 5.0.0-rc.0 and switched to candidate channel
- ✅ Environment variables auto-substituted (${ETCD_KMS_ARN} → actual value)
- ✅ 100% test pass rate (570+ tests)
- ✅ CLI works: `run-test-suite --scenario day1-security -e openshift_version=5.0`
- ✅ Backward compatible with existing feature-based invocation

**Impact**:
- **Operators**: Reduced command complexity by 80% (1 flag vs 8+)
- **DevOps**: Single source of truth for test configurations (feature-registry.yml)
- **Maintenance**: Add new scenarios with 4-line YAML entries (no code changes)
- **Reliability**: Version compatibility validated at plan time, not execution time

**Metrics**:
- 1000+ lines of new code
- 570+ unit tests
- 5 production scenarios
- 100% test pass rate

**PR**: #170  
**Author**: Tina Fitzgerald  
**Merged**: Oct 13, 2026 @ 05:06 UTC

---

## Summary

This represents **foundational architecture work** that:
1. Eliminated manual parameter assembly (80% reduction in command complexity)
2. Established a declarative, version-aware testing framework
3. Created a scalable, maintainable system for scenario-based testing
4. Delivered 570+ tests with 100% pass rate
5. Enabled all downstream 5.0 RC validation work

**Use this for quarterly review and official credit documentation.**
