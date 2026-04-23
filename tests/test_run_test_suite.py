#!/usr/bin/env python3
"""
Tests for TestSuiteRunner from run-test-suite.py.

Validates runner functionality without executing playbooks:
    - Suite loading from JSON files
    - Listing available suites
    - Extra vars merging
    - Suite label extraction
    - Tag filtering
"""

import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# Import run-test-suite.py via importlib (filename contains a hyphen)
_spec = importlib.util.spec_from_file_location(
    "run_test_suite", BASE_DIR / "run-test-suite.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
TestSuiteRunner = _module.TestSuiteRunner


def _make_runner(**kwargs):
    """Create a TestSuiteRunner with AI agents disabled and BASE_DIR set."""
    defaults = {"base_dir": BASE_DIR, "ai_agent_enabled": False}
    defaults.update(kwargs)
    return TestSuiteRunner(**defaults)


# ================================================================
# Suite Loading
# ================================================================

def test_load_valid_suite():
    runner = _make_runner()
    suite = runner.load_test_suite("20-rosa-hcp-provision")
    assert suite is not None, "Should load a valid suite"
    assert "name" in suite
    assert "playbooks" in suite


def test_load_nonexistent_suite():
    runner = _make_runner()
    suite = runner.load_test_suite("99-does-not-exist")
    assert suite is None, "Loading a nonexistent suite should return None"


def test_load_all_suite_files():
    runner = _make_runner()
    suite_ids = [
        "05-verify-mce-environment",
        "10-configure-mce-environment",
        "20-rosa-hcp-provision",
        "27-rosa-hcp-add-machinepool",
        "28-rosa-hcp-delete-machinepool",
        "30-rosa-hcp-delete",
        "40-enable-capi-disable-hypershift",
        "41-disable-capi-enable-hypershift",
    ]
    for suite_id in suite_ids:
        suite = runner.load_test_suite(suite_id)
        assert suite is not None, f"Failed to load suite: {suite_id}"


# ================================================================
# Listing Suites
# ================================================================

def test_list_test_suites_returns_all():
    runner = _make_runner()
    suites = runner.list_test_suites()
    assert len(suites) >= 8, \
        f"Expected at least 8 suites, got {len(suites)}"


def test_list_test_suites_fields():
    runner = _make_runner()
    suites = runner.list_test_suites()
    for suite in suites:
        assert "id" in suite, "Listed suite missing 'id'"
        assert "name" in suite, "Listed suite missing 'name'"
        assert "tags" in suite, "Listed suite missing 'tags'"
        assert "playbook_count" in suite, "Listed suite missing 'playbook_count'"


def test_list_suites_sorted():
    runner = _make_runner()
    suites = runner.list_test_suites()
    ids = [s["id"] for s in suites]
    assert ids == sorted(ids), "Suites should be listed in sorted order"


# ================================================================
# Extra Vars
# ================================================================

def test_extra_vars_default_automation_path():
    runner = _make_runner()
    assert "AUTOMATION_PATH" in runner.extra_vars, \
        "Runner should set AUTOMATION_PATH by default"
    assert runner.extra_vars["AUTOMATION_PATH"] == str(BASE_DIR.absolute())


def test_extra_vars_override():
    runner = _make_runner(extra_vars={"cluster_name": "test-cluster", "replicas": "2"})
    assert runner.extra_vars["cluster_name"] == "test-cluster"
    assert runner.extra_vars["replicas"] == "2"
    # AUTOMATION_PATH should still be present
    assert "AUTOMATION_PATH" in runner.extra_vars


def test_extra_vars_override_automation_path():
    custom_path = "/custom/path"
    runner = _make_runner(extra_vars={"AUTOMATION_PATH": custom_path})
    assert runner.extra_vars["AUTOMATION_PATH"] == custom_path, \
        "Extra vars should be able to override AUTOMATION_PATH"


# ================================================================
# Suite Label Extraction
# ================================================================

def test_extract_suite_label_configure():
    runner = _make_runner()
    assert runner._extract_suite_label("10-configure-mce-environment") == "configure"


def test_extract_suite_label_provision():
    runner = _make_runner()
    assert runner._extract_suite_label("20-rosa-hcp-provision") == "provision"


def test_extract_suite_label_delete():
    runner = _make_runner()
    assert runner._extract_suite_label("30-rosa-hcp-delete") == "delete"


def test_extract_suite_label_verify():
    runner = _make_runner()
    assert runner._extract_suite_label("05-verify-mce-environment") == "verify"


def test_extract_suite_label_toggle():
    runner = _make_runner()
    label = runner._extract_suite_label("40-enable-capi-disable-hypershift")
    assert label == "toggle", f"Expected 'toggle', got '{label}'"


def test_extract_suite_label_lifecycle():
    runner = _make_runner()
    assert runner._extract_suite_label("23-rosa-hcp-full-lifecycle") == "lifecycle"


def test_extract_suite_label_fallback():
    runner = _make_runner()
    label = runner._extract_suite_label("99-something-unknown")
    assert isinstance(label, str) and len(label) > 0, \
        "Fallback label should be a non-empty string"


# ================================================================
# Tag Filtering
# ================================================================

def test_tag_filter_rosa():
    runner = _make_runner()
    suites = runner.list_test_suites()
    rosa_suites = [s for s in suites if "rosa" in s.get("tags", [])]
    assert len(rosa_suites) >= 1, "Should find at least one suite tagged 'rosa'"


def test_tag_filter_machinepool():
    runner = _make_runner()
    suites = runner.list_test_suites()
    mp_suites = [s for s in suites if "machinepool" in s.get("tags", [])]
    assert len(mp_suites) == 2, \
        f"Expected 2 machinepool-tagged suites, got {len(mp_suites)}"


def test_tag_filter_no_match():
    runner = _make_runner()
    suites = runner.list_test_suites()
    none_suites = [s for s in suites if "nonexistent-tag-xyz" in s.get("tags", [])]
    assert len(none_suites) == 0, "Nonexistent tag should match no suites"


# ================================================================
# Runner Initialization
# ================================================================

def test_runner_dry_run_flag():
    runner = _make_runner(dry_run=True)
    assert runner.dry_run is True


def test_runner_ai_agent_disabled():
    runner = _make_runner(ai_agent_enabled=False)
    assert runner.ai_agent_enabled is False
    assert runner.monitor_agent is None


def test_runner_results_initialized():
    runner = _make_runner()
    assert runner.results["total_tests"] == 0
    assert runner.results["passed"] == 0
    assert runner.results["failed"] == 0
