"""
ROSA HCP Domain Plugin Tests
=============================

Smoke tests verifying that the ROSA HCP domain subclasses
instantiate correctly and delegate to the right methods.
"""

import sys
import os
from pathlib import Path

# Ensure the project root is on sys.path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.domains.rosa_hcp import RosaHcpMonitoringAgent, RosaHcpDiagnosticAgent, RosaHcpRemediationAgent
from agents import LearningAgent


def test_domain_agents_instantiate():
    """Domain subclasses can be created and their kb_dir points to the domain KB."""
    base_dir = project_root

    monitor = RosaHcpMonitoringAgent(base_dir, enabled=True, verbose=False)
    diag = RosaHcpDiagnosticAgent(base_dir, enabled=True, verbose=False)
    remed = RosaHcpRemediationAgent(base_dir, enabled=True, verbose=False, dry_run=True)

    expected_kb = Path(__file__).parent.parent / "knowledge_base"
    assert monitor.kb_dir == expected_kb, f"MonitoringAgent kb_dir: {monitor.kb_dir} != {expected_kb}"
    assert diag.kb_dir == expected_kb, f"DiagnosticAgent kb_dir: {diag.kb_dir} != {expected_kb}"
    assert remed.kb_dir == expected_kb, f"RemediationAgent kb_dir: {remed.kb_dir} != {expected_kb}"
    print("PASSED: Domain agents instantiate with correct kb_dir")


def test_learning_agent_shares_kb_dir():
    """LearningAgent can share the domain's kb_dir when explicitly passed."""
    base_dir = project_root
    domain_kb = Path(__file__).parent.parent / "knowledge_base"

    learning = LearningAgent(base_dir, enabled=True, verbose=False, kb_dir=domain_kb)

    assert learning.kb_dir == domain_kb, f"LearningAgent kb_dir: {learning.kb_dir} != {domain_kb}"
    assert learning.outcomes_file == domain_kb / "remediation_outcomes.json"
    assert learning.pending_file == domain_kb / "pending_learnings.json"
    print("PASSED: LearningAgent shares domain kb_dir")


def test_monitoring_hooks():
    """ROSA monitoring hooks detect ROSA resource types."""
    base_dir = project_root
    monitor = RosaHcpMonitoringAgent(base_dir, enabled=True, verbose=False)

    assert monitor._extract_waiting_for_resource("Waiting for ROSANetwork deletion") == "ROSANetwork"
    assert monitor._extract_waiting_for_resource("Waiting for ROSAControlPlane") == "ROSAControlPlane"
    assert monitor._extract_waiting_for_resource("Waiting for ROSARoleConfig") == "ROSARoleConfig"
    assert monitor._extract_waiting_for_resource("Waiting for something else") is None
    print("PASSED: Monitoring hooks detect ROSA resource types")


def test_diagnostic_dispatch():
    """ROSA diagnostic agent dispatches to ROSA-specific methods."""
    base_dir = project_root
    diag = RosaHcpDiagnosticAgent(base_dir, enabled=True, verbose=False)

    # _diagnose_issue should return a dict for known ROSA issue types
    context = {"line": "test", "buffer": [], "current_task": "test"}
    result = diag._diagnose_issue("api_rate_limit", context)
    assert result is not None, "Expected diagnosis for api_rate_limit"
    assert result["issue_type"] == "api_rate_limit"
    assert result["recommended_fix"] == "backoff_and_retry"

    # Unknown issue types should return None (fall through to generic)
    result = diag._diagnose_issue("unknown_issue_xyz", context)
    assert result is None, "Expected None for unknown issue type"
    print("PASSED: Diagnostic dispatch works for ROSA issue types")


def test_remediation_dispatch():
    """ROSA remediation agent has all expected fix methods."""
    base_dir = project_root
    remed = RosaHcpRemediationAgent(base_dir, enabled=True, verbose=False, dry_run=True)

    expected_fixes = [
        "remove_finalizers", "refresh_ocm_token", "backoff_and_retry",
        "cleanup_vpc_dependencies", "manual_cloudformation_cleanup",
        "retry_cloudformation_delete", "install_capi_capa",
        "increase_timeout_and_monitor", "log_and_continue",
    ]
    for fix_name in expected_fixes:
        method = remed._get_fix_method(fix_name)
        assert method is not None, f"Missing fix method: {fix_name}"

    assert remed._get_fix_method("nonexistent_fix") is None
    print("PASSED: Remediation dispatch has all ROSA fix methods")


def test_dry_run_through_domain_agent():
    """End-to-end dry run through domain remediation agent."""
    base_dir = project_root
    remed = RosaHcpRemediationAgent(base_dir, enabled=True, verbose=False, dry_run=True)

    diagnosis = {
        "issue_type": "rosanetwork_stuck_deletion",
        "recommended_fix": "retry_cloudformation_delete",
        "fix_parameters": {"stack_name": "test-stack", "region": "us-west-2"},
        "confidence": 0.95,
    }
    success, message = remed.remediate(diagnosis)
    assert success, f"Dry run should succeed: {message}"
    assert "DRY RUN" in message
    print("PASSED: Dry run through domain remediation agent")


if __name__ == "__main__":
    tests = [
        test_domain_agents_instantiate,
        test_learning_agent_shares_kb_dir,
        test_monitoring_hooks,
        test_diagnostic_dispatch,
        test_remediation_dispatch,
        test_dry_run_through_domain_agent,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAILED: {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"ROSA HCP Domain Tests: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'=' * 60}")
    sys.exit(1 if failed > 0 else 0)
