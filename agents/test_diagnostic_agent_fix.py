#!/usr/bin/env python3
"""
Test for diagnostic_agent.py resource name extraction fix
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.diagnostic_agent import DiagnosticAgent


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

    print(f"✓ Extracted: {resource_name} in namespace {namespace}")
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    assert namespace == "ns-rosa-hcp", f"Expected 'ns-rosa-hcp', got '{namespace}'"
    print("✓ Test PASSED")


def test_extract_from_kubectl_command():
    """Test extraction from kubectl command"""
    print("\n=== Test 2: Extract from kubectl command ===")

    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    context = {
        "buffer": [
            "kubectl get rosanetwork my-test-cluster -n test-namespace"
        ]
    }

    resource_name, namespace = agent._extract_resource_info(context)

    print(f"✓ Extracted: {resource_name} in namespace {namespace}")
    assert resource_name == "my-test-cluster", f"Expected 'my-test-cluster', got '{resource_name}'"
    assert namespace == "test-namespace", f"Expected 'test-namespace', got '{namespace}'"
    print("✓ Test PASSED")


def test_extract_from_output_table():
    """Test extraction from kubectl/oc output table"""
    print("\n=== Test 3: Extract from output table ===")

    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    context = {
        "buffer": [
            "NAME                   AGE",
            "pop-rosa-hcp-network   76m"
        ]
    }

    resource_name, namespace = agent._extract_resource_info(context)

    print(f"✓ Extracted: {resource_name}")
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    print("✓ Test PASSED (namespace defaults to 'default')")


def test_extract_from_explicit_context():
    """Test extraction from explicit context fields"""
    print("\n=== Test 4: Extract from explicit context ===")

    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    context = {
        "resource_name": "explicit-cluster",
        "namespace": "explicit-namespace"
    }

    resource_name, namespace = agent._extract_resource_info(context)

    print(f"✓ Extracted: {resource_name} in namespace {namespace}")
    assert resource_name == "explicit-cluster", f"Expected 'explicit-cluster', got '{resource_name}'"
    assert namespace == "explicit-namespace", f"Expected 'explicit-namespace', got '{namespace}'"
    print("✓ Test PASSED")


def test_fallback_to_unknown():
    """Test fallback to 'unknown-cluster' when extraction fails"""
    print("\n=== Test 5: Fallback to 'unknown-cluster' ===")

    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    context = {
        "buffer": ["irrelevant output", "nothing useful here"]
    }

    resource_name, namespace = agent._extract_resource_info(context)

    print(f"✓ Extracted: {resource_name} in namespace {namespace}")
    assert resource_name == "unknown-cluster", f"Expected 'unknown-cluster', got '{resource_name}'"
    assert namespace == "default", f"Expected 'default', got '{namespace}'"
    print("✓ Test PASSED (fallback working as expected)")


def test_real_jenkins_output():
    """Test with actual output from the failed Jenkins job"""
    print("\n=== Test 6: Real Jenkins output scenario ===")

    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    # Simulated context from actual Jenkins logs
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

    print(f"✓ Extracted: {resource_name} in namespace {namespace}")
    assert resource_name == "pop-rosa-hcp-network", f"Expected 'pop-rosa-hcp-network', got '{resource_name}'"
    assert namespace == "ns-rosa-hcp", f"Expected 'ns-rosa-hcp', got '{namespace}'"
    print("✓ Test PASSED - Would fix the actual bug!")


def test_backward_compatibility():
    """Test that old _extract_cluster_name still works"""
    print("\n=== Test 7: Backward compatibility ===")

    agent = DiagnosticAgent(Path("."), enabled=True, verbose=True)

    context = {
        "buffer": ["oc get rosanetwork test-cluster -n test-ns"]
    }

    # Old method should still work
    cluster_name = agent._extract_cluster_name(context)

    print(f"✓ Old method returned: {cluster_name}")
    assert cluster_name == "test-cluster", f"Expected 'test-cluster', got '{cluster_name}'"
    print("✓ Test PASSED - Backward compatibility maintained")


def main():
    """Run all tests"""
    print("=" * 70)
    print("Testing diagnostic_agent.py Resource Name Extraction Fix")
    print("=" * 70)

    tests = [
        test_extract_from_oc_command,
        test_extract_from_kubectl_command,
        test_extract_from_output_table,
        test_extract_from_explicit_context,
        test_fallback_to_unknown,
        test_real_jenkins_output,
        test_backward_compatibility,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ Test FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ Test ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed == 0:
        print("\n✓ All tests passed! The fix is working correctly.")
        print("\nExpected behavior:")
        print("  - Resource names extracted from oc/kubectl commands")
        print("  - Namespace correctly identified")
        print("  - No more 'unknown-cluster' errors in normal operation")
        print("  - Remediation agent will target the correct resources")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed. Please review the fix.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
