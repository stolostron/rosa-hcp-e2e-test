#!/usr/bin/env python3
"""
Tests for the AI agent framework.

Covers:
    - Diagnostic agent resource name extraction
    - Monitoring agent per-resource state machine
    - Structured context parsing
    - Pattern detection (single source of truth in JSON)
"""

import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.diagnostic_agent import DiagnosticAgent
from agents.monitoring_agent import MonitoringAgent, IssueState


def test_extract_from_oc_command():
    """Test extraction from oc get command"""
    print("\n=== Test 1: Extract from oc command ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {
        "buffer": [
            "TASK [Wait for ROSANetwork deletion to complete]",
            "oc get rosanetwork pop-rosa-hcp-network -n ns-rosa-hcp 2>/dev/null",
            "NAME                   AGE",
            "pop-rosa-hcp-network   76m"
        ]
    }
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    assert namespace == "ns-rosa-hcp", f"Expected 'ns-rosa-hcp', got '{namespace}'"
    print("PASSED")


def test_extract_from_kubectl_command():
    """Test extraction from kubectl command"""
    print("\n=== Test 2: Extract from kubectl command ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {"buffer": ["kubectl get rosanetwork my-test-cluster -n test-namespace"]}
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "my-test-cluster", f"Expected 'my-test-cluster', got '{resource_name}'"
    assert namespace == "test-namespace", f"Expected 'test-namespace', got '{namespace}'"
    print("PASSED")


def test_extract_from_output_table():
    """Test extraction from kubectl/oc output table"""
    print("\n=== Test 3: Extract from output table ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {"buffer": ["NAME                   AGE", "pop-rosa-hcp-network   76m"]}
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    print("PASSED")


def test_extract_from_structured_context():
    """Test extraction from structured context fields (from #AGENT_CONTEXT markers)"""
    print("\n=== Test 4: Extract from structured context ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {"resource_name": "explicit-cluster", "namespace": "explicit-namespace"}
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "explicit-cluster", f"Expected 'explicit-cluster', got '{resource_name}'"
    assert namespace == "explicit-namespace", f"Expected 'explicit-namespace', got '{namespace}'"
    print("PASSED")


def test_fallback_to_unknown():
    """Test fallback to 'unknown-cluster' when extraction fails"""
    print("\n=== Test 5: Fallback to 'unknown-cluster' ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {"buffer": ["irrelevant output", "nothing useful here"]}
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "unknown-cluster", f"Expected 'unknown-cluster', got '{resource_name}'"
    assert namespace == "default", f"Expected 'default', got '{namespace}'"
    print("PASSED")


def test_real_jenkins_output():
    """Test with actual output from the failed Jenkins job"""
    print("\n=== Test 6: Real Jenkins output scenario ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {
        "line": "oc get rosanetwork pop-rosa-hcp-network -n ns-rosa-hcp 2>/dev/null\n",
        "buffer": [
            "TASK [Wait for ROSANetwork deletion to complete] ******",
            "changed: [localhost]",
            "oc get rosanetwork pop-rosa-hcp-network -n ns-rosa-hcp 2>/dev/null",
            "",
            "NAME                   AGE",
            "pop-rosa-hcp-network   76m",
            "",
            "FAILED - RETRYING: [localhost]: Wait for ROSANetwork deletion to complete (35 retries left)"
        ],
        "current_task": "Wait for ROSANetwork deletion to complete",
        "waiting_for": "ROSANetwork"
    }
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    assert namespace == "ns-rosa-hcp", f"Expected 'ns-rosa-hcp', got '{namespace}'"
    print("PASSED")


def test_task_name_skip_words():
    """Test that generic words in task names are not extracted as resource names"""
    print("\n=== Test 7: Task name skip words ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {
        "buffer": [],
        "current_task": "Wait for ROSANetwork deletion to complete"
    }
    resource_name, namespace = agent._extract_resource_info(context)
    # "deletion" should be skipped, fallback to unknown
    assert resource_name == "unknown-cluster", f"Expected 'unknown-cluster', got '{resource_name}'"
    print("PASSED")


def test_state_machine_prevents_duplicate_intervention():
    """Test that the per-resource state machine prevents re-triggering"""
    print("\n=== Test 8: State machine prevents duplicate intervention ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    callback_count = 0
    def mock_callback(issue_type, context, issue):
        nonlocal callback_count
        callback_count += 1

    monitor.set_issue_callback(mock_callback)

    # Simulate the same RETRYING line hitting multiple times
    retrying_line = "FAILED - RETRYING: ROSANetwork pop-rosa-hcp-network still exists waiting for deletion (35 retries left)"
    for i in range(10):
        monitor.process_line(retrying_line)

    # Should only fire callback ONCE (state machine blocks after first)
    assert callback_count == 1, f"Expected 1 callback, got {callback_count}"

    # Mark it failed — should allow one more retry
    monitor.mark_issue_failed("rosanetwork_stuck_deletion")
    monitor.process_line(retrying_line)
    assert callback_count == 2, f"Expected 2 callbacks after failure, got {callback_count}"

    # Mark resolved — no more callbacks
    monitor.mark_issue_resolved("rosanetwork_stuck_deletion")
    monitor.process_line(retrying_line)
    assert callback_count == 2, f"Expected 2 callbacks after resolve, got {callback_count}"
    print("PASSED")


def test_state_machine_max_attempts():
    """Test that state machine stops after max_attempts"""
    print("\n=== Test 9: State machine max attempts ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    callback_count = 0
    def mock_callback(issue_type, context, issue):
        nonlocal callback_count
        callback_count += 1

    monitor.set_issue_callback(mock_callback)

    retrying_line = "FAILED - RETRYING: ROSANetwork test-cluster still exists waiting for deletion (30 retries left)"

    # First attempt
    monitor.process_line(retrying_line)
    assert callback_count == 1

    # Fail and retry up to max_attempts (3)
    for i in range(4):
        monitor.mark_issue_failed("rosanetwork_stuck_deletion")
        monitor.process_line(retrying_line)

    # Should have capped at 3 attempts
    assert callback_count == 3, f"Expected 3 callbacks (max), got {callback_count}"
    print("PASSED")


def test_structured_context_marker():
    """Test parsing #AGENT_CONTEXT markers from playbook output"""
    print("\n=== Test 10: Structured context marker ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    # Simulate structured context marker (bare format)
    monitor.process_line("#AGENT_CONTEXT: resource_name=my-rosa-network namespace=ns-rosa-hcp resource_type=rosanetwork")

    assert monitor._structured_context.get("resource_name") == "my-rosa-network"
    assert monitor._structured_context.get("namespace") == "ns-rosa-hcp"
    assert monitor._structured_context.get("resource_type") == "rosanetwork"

    # Also test Ansible debug output format (wrapped in JSON)
    monitor._structured_context.clear()
    monitor.process_line('    "msg": "#AGENT_CONTEXT: resource_name=bar-rosa-hcp-network namespace=ns-rosa-hcp resource_type=rosanetwork"')

    assert monitor._structured_context.get("resource_name") == "bar-rosa-hcp-network", \
        f"Expected 'bar-rosa-hcp-network', got '{monitor._structured_context.get('resource_name')}'"
    assert monitor._structured_context.get("namespace") == "ns-rosa-hcp"
    print("PASSED")


def test_no_hardcoded_patterns():
    """Verify monitoring agent uses only JSON patterns, no hardcoded detection"""
    print("\n=== Test 11: No hardcoded pattern detection ===")
    import inspect
    source = inspect.getsource(MonitoringAgent._detect_issue)
    # Should not contain hardcoded keyword checks
    assert "line.lower()" not in source, "_detect_issue still contains hardcoded keyword detection"
    assert source.count("return") <= 2, "_detect_issue has too many return paths (likely hardcoded patterns)"
    print("PASSED")


def test_structured_context_cleared_on_new_task():
    """Test that structured context is preserved for one TASK then cleared"""
    print("\n=== Test 12: Structured context cleared on new TASK ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    # Task A emits structured context
    monitor.process_line("#AGENT_CONTEXT: resource_name=cluster-a namespace=ns-a")
    assert monitor._structured_context.get("resource_name") == "cluster-a"

    # First new task — context should be PRESERVED (meant for the next task)
    monitor.process_line("TASK [Wait for cluster-a deletion] ******")
    assert monitor._structured_context.get("resource_name") == "cluster-a", \
        f"Context should survive one TASK transition: {monitor._structured_context}"

    # Second new task — NOW context should be cleared
    monitor.process_line("TASK [Deploy cluster B] ******")
    assert monitor._structured_context.get("resource_name") is None, \
        f"Structured context leaked past second TASK: {monitor._structured_context}"
    print("PASSED")


def test_extract_resource_type_parameter():
    """Test that _extract_resource_info works with different resource types"""
    print("\n=== Test 13: Resource type parameter ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    context = {"buffer": ["oc get rosacontrolplane my-cp -n cp-namespace"]}
    name, ns = agent._extract_resource_info(context, resource_type="rosacontrolplane")
    assert name == "my-cp", f"Expected 'my-cp', got '{name}'"
    assert ns == "cp-namespace", f"Expected 'cp-namespace', got '{ns}'"

    # Default resource_type=rosanetwork should NOT match rosacontrolplane
    name2, _ = agent._extract_resource_info(context, resource_type="rosanetwork")
    assert name2 == "unknown-cluster", f"Expected 'unknown-cluster' for wrong type, got '{name2}'"
    print("PASSED")


def test_remediation_no_crash_on_success():
    """Test that remediation doesn't crash (learn_from_success was removed)"""
    print("\n=== Test 14: Remediation dry run doesn't crash ===")
    from agents.remediation_agent import RemediationAgent
    agent = RemediationAgent(Path("."), enabled=True, verbose=True, dry_run=True)
    diagnosis = {
        "issue_type": "rosanetwork_stuck_deletion",
        "recommended_fix": "remove_finalizers",
        "fix_parameters": {
            "resource_type": "rosanetwork",
            "resource_name": "test-cluster",
            "namespace": "test-ns",
        }
    }
    success, message = agent.remediate(diagnosis)
    assert success, f"Dry run should succeed, got: {message}"
    print("PASSED")


def test_callback_receives_resource_key():
    """Test that the issue callback receives resource_key for state machine feedback"""
    print("\n=== Test 15: Callback receives resource_key ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    captured_context = {}
    def mock_callback(issue_type, context, issue):
        captured_context.update(context)

    monitor.set_issue_callback(mock_callback)

    # Feed structured context then a matching line
    monitor.process_line("#AGENT_CONTEXT: resource_name=my-cluster namespace=my-ns resource_type=rosanetwork")
    monitor.process_line("FAILED - RETRYING: ROSANetwork my-cluster still exists waiting for deletion (30 retries left)")

    assert "resource_key" in captured_context, "Callback context missing resource_key"
    assert captured_context["resource_key"] == "my-ns/my-cluster", \
        f"Expected 'my-ns/my-cluster', got '{captured_context['resource_key']}'"

    # Verify mark_issue_resolved works with the captured key
    monitor.mark_issue_resolved("rosanetwork_stuck_deletion", captured_context["resource_key"])
    tracking_key = f"rosanetwork_stuck_deletion:{captured_context['resource_key']}"
    tracked = monitor._tracked_issues.get(tracking_key)
    assert tracked is not None, f"Tracked issue not found for key {tracking_key}"
    assert tracked.state.value == "resolved", f"Expected 'resolved', got '{tracked.state.value}'"
    print("PASSED")


def test_rosanetwork_pattern_no_false_positive_during_creation():
    """Test that rosanetwork_stuck_deletion does NOT match during creation/provisioning"""
    print("\n=== Test 16: No false positive during ROSANetwork creation ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    callback_count = 0
    def mock_callback(issue_type, context, issue):
        nonlocal callback_count
        callback_count += 1

    monitor.set_issue_callback(mock_callback)

    # Simulate the creation scenario that caused the false positive
    creation_lines = [
        "TASK [Wait for ROSANetwork to be fully ready] ******",
        "FAILED - RETRYING: [localhost]: Wait for ROSANetwork to be fully ready (40 retries left).Result was: {",
        "FAILED - RETRYING: [localhost]: Wait for ROSANetwork to be fully ready (39 retries left).Result was: {",
        "FAILED - RETRYING: [localhost]: Wait for ROSANetwork to be fully ready (38 retries left).Result was: {",
    ]
    for line in creation_lines:
        monitor.process_line(line)

    assert callback_count == 0, f"Expected 0 callbacks during creation, got {callback_count} (false positive!)"
    print("PASSED")


def test_rosanetwork_pattern_matches_deletion():
    """Test that rosanetwork_stuck_deletion DOES match during actual deletion"""
    print("\n=== Test 17: Pattern matches during ROSANetwork deletion ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    callback_count = 0
    detected_types = []
    def mock_callback(issue_type, context, issue):
        nonlocal callback_count
        callback_count += 1
        detected_types.append(issue_type)

    monitor.set_issue_callback(mock_callback)

    # Actual deletion lines that SHOULD match
    monitor.process_line("FAILED - RETRYING: ROSANetwork pop-rosa-hcp-network still exists waiting for deletion (35 retries left)")

    assert callback_count == 1, f"Expected 1 callback during deletion, got {callback_count}"
    assert "rosanetwork_stuck_deletion" in detected_types, f"Expected rosanetwork_stuck_deletion, got {detected_types}"
    print("PASSED")


def test_rosanetwork_deletion_task_retrying_matches():
    """Test that RETRYING lines for deletion tasks match the pattern"""
    print("\n=== Test 18: Deletion task RETRYING lines match ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    callback_count = 0
    def mock_callback(issue_type, context, issue):
        nonlocal callback_count
        callback_count += 1

    monitor.set_issue_callback(mock_callback)

    monitor.process_line("TASK [Wait for ROSANetwork deletion to complete] ******")
    monitor.process_line("FAILED - RETRYING: [localhost]: Wait for ROSANetwork deletion to complete (35 retries left)")

    assert callback_count == 1, f"Expected 1 callback for deletion RETRYING, got {callback_count}"
    print("PASSED")


def test_extract_resource_from_retrying_line():
    """Test resource name extraction from RETRYING lines with explicit resource names"""
    print("\n=== Test 19: Extract resource from RETRYING line ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {
        "buffer": [
            "FAILED - RETRYING: ROSANetwork pop-rosa-hcp-network still exists waiting for deletion (35 retries left)"
        ]
    }
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    print("PASSED")


def test_no_false_positive_on_display_banner():
    """Test that the deletion display banner does NOT trigger detection"""
    print("\n=== Test 20: No false positive on display banner ===")
    monitor = MonitoringAgent(Path("."), enabled=True, verbose=True)

    callback_count = 0
    def mock_callback(issue_type, context, issue):
        nonlocal callback_count
        callback_count += 1

    monitor.set_issue_callback(mock_callback)

    # This is the banner message that caused the original false positive
    banner = (
        "Deletion Configuration:\n"
        "- Cluster Name: pop-rosa-hcp\n"
        "- Namespace: ns-rosa-hcp\n"
        "Resources to Delete:\n"
        "- ROSAControlPlane: Yes\n"
        "- ROSANetwork: Yes\n"
        "- ROSARoleConfig: Yes\n"
    )
    for line in banner.split("\n"):
        monitor.process_line(line)

    assert callback_count == 0, f"Expected 0 callbacks on display banner, got {callback_count} (false positive!)"
    print("PASSED")


def test_extract_resource_from_ansible_json_cmd():
    """Test resource extraction from Ansible JSON cmd output in buffer"""
    print("\n=== Test 21: Extract resource from Ansible JSON cmd ===")
    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)
    context = {
        "buffer": [
            '    "cmd": "oc get rosanetwork pop-rosa-hcp-network -n ns-rosa-hcp 2>/dev/null\\n",',
            '    "_raw_params": "oc get rosanetwork pop-rosa-hcp-network -n ns-rosa-hcp 2>/dev/null\\n",',
        ]
    }
    resource_name, namespace = agent._extract_resource_info(context)
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    assert namespace == "ns-rosa-hcp", f"Expected 'ns-rosa-hcp', got '{namespace}'"
    print("PASSED")


def main():
    """Run all tests"""
    print("=" * 70)
    print("AI Agent Framework Tests")
    print("=" * 70)

    tests = [
        test_extract_from_oc_command,
        test_extract_from_kubectl_command,
        test_extract_from_output_table,
        test_extract_from_structured_context,
        test_fallback_to_unknown,
        test_real_jenkins_output,
        test_task_name_skip_words,
        test_state_machine_prevents_duplicate_intervention,
        test_state_machine_max_attempts,
        test_structured_context_marker,
        test_no_hardcoded_patterns,
        test_structured_context_cleared_on_new_task,
        test_extract_resource_type_parameter,
        test_remediation_no_crash_on_success,
        test_callback_receives_resource_key,
        test_rosanetwork_pattern_no_false_positive_during_creation,
        test_rosanetwork_pattern_matches_deletion,
        test_rosanetwork_deletion_task_retrying_matches,
        test_extract_resource_from_retrying_line,
        test_no_false_positive_on_display_banner,
        test_extract_resource_from_ansible_json_cmd,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
