#!/usr/bin/env python3
"""Regression tests for the pre-cleanup CAPA failure snapshot.

These pin the ordering and the non-fatal behavior that keep the failure-time
snapshot available: capture (inside the provision path) -> fail -> cleanup
stage. Only repository content is read; no cluster, AWS or network access.
"""

from pathlib import Path

import yaml
from feature_manager import FeatureManager

BASE_DIR = Path(__file__).parent.parent
TASK_FILE = BASE_DIR / "tasks" / "wait_for_rosa_control_plane_ready.yml"
PROVISION_TASK_FILE = BASE_DIR / "tasks" / "provision_rosa_hcp_with_automation.yml"
SNAPSHOT_SCRIPT = BASE_DIR / "scripts" / "capture_capa_failure_snapshot.py"

SCRIPT_NAME = "capture_capa_failure_snapshot.py"
PROVISION_SUITE = "20-rosa-hcp-provision"
CLEANUP_SUITE = "30-rosa-hcp-delete"


def _tasks():
    return yaml.safe_load(TASK_FILE.read_text())


def _index_of(tasks, predicate, label):
    for index, task in enumerate(tasks):
        if predicate(task):
            return index
    raise AssertionError(f"no {label} task found in {TASK_FILE.name}")


def _capture_index(tasks):
    return _index_of(
        tasks, lambda t: SCRIPT_NAME in str(t.get("command", "")), "capture"
    )


def _fail_index(tasks):
    return _index_of(tasks, lambda t: "fail" in t, "fail")


def test_capture_runs_before_the_fail_task():
    """The fail hands control back to the runner, which then runs cleanup."""
    tasks = _tasks()
    assert _capture_index(tasks) < _fail_index(tasks)


def test_no_task_between_capture_and_fail_can_delete_resources():
    tasks = _tasks()
    between = tasks[_capture_index(tasks) : _fail_index(tasks)]
    for task in between:
        body = str(task)
        assert "oc delete" not in body
        assert "state: absent" not in body


def test_every_scenario_runs_cleanup_after_provisioning():
    """Chains the ordering: capture is inside the provision suite, and every
    scenario orders its always-cleanup stage after that suite."""
    manager = FeatureManager(BASE_DIR)
    checked = 0
    for scenario in manager.list_scenarios():
        stages = manager.scenario_stages(scenario["name"])
        suites = [stage["suite"] for stage in stages]
        if PROVISION_SUITE not in suites or CLEANUP_SUITE not in suites:
            continue
        checked += 1
        assert suites.index(PROVISION_SUITE) < suites.index(CLEANUP_SUITE)
        cleanup = stages[suites.index(CLEANUP_SUITE)]
        assert cleanup["always"] is True
    assert checked > 0, "no scenario provisions and then cleans up"


def test_provision_path_includes_the_readiness_wait():
    body = PROVISION_TASK_FILE.read_text()
    assert "wait_for_rosa_control_plane_ready.yml" in body


def test_capture_is_never_fatal():
    task = _tasks()[_capture_index(_tasks())]
    assert task.get("failed_when") is False
    assert task.get("changed_when") is False


def test_original_failure_remains_the_primary_signal():
    tasks = _tasks()
    fail_task = tasks[_fail_index(tasks)]
    message = fail_task["fail"]["msg"]
    assert "did not become ready within the timeout period" in message
    assert "{{ rcp_full_status.stdout" in message
    assert "{{ rcp_events.stdout" in message


def test_capture_only_runs_when_the_control_plane_is_not_ready():
    """Normal-success runs must not pay for, or trip over, the capture."""
    tasks = _tasks()
    capture = tasks[_capture_index(tasks)]
    fail_task = tasks[_fail_index(tasks)]
    assert capture["when"] == fail_task["when"]
    assert "not (rcp_status.stdout | bool)" in str(capture["when"])


def test_readiness_wait_timeouts_are_unchanged():
    wait_task = _tasks()[0]
    assert "75 if retry_count is undefined" in str(wait_task["retries"])
    assert "30 if delay is undefined" in str(wait_task["delay"])


def test_capture_invokes_the_snapshot_script_read_only():
    command = str(_tasks()[_capture_index(_tasks())]["command"])
    assert SCRIPT_NAME in command
    assert "--cluster-name" in command
    assert "--namespace" in command
    assert "rosa_hcp_namespace" in command
    assert "--fallback-dir" in command
    for mutating in ("oc delete", "oc patch", "oc apply", "oc create", "aws "):
        assert mutating not in command


def test_snapshot_script_exists_and_is_standalone():
    source = SNAPSHOT_SCRIPT.read_text()
    assert source.startswith("#!/usr/bin/env python3")
    for third_party in ("import boto3", "import yaml", "import requests", "kubernetes"):
        assert third_party not in source
