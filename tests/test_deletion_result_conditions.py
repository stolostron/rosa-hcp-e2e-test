#!/usr/bin/env python3
"""
Regression tests for the deletion-result conditionals in
``tasks/delete_rosa_hcp_resources.yml``.

The wait/final-check tasks for ROSAControlPlane, ROSANetwork and ROSARoleConfig
are themselves conditional, so their registered results are not guaranteed to
carry an ``rc`` key:

* the task never ran at all -> the variable is undefined;
* the task was skipped      -> the variable is a dict such as
  ``{"changed": false, "skipped": true, "skip_reason": "..."}`` with no ``rc``.

Two defects were possible in the conditionals that consume those results:

1. ``wait_rcp is defined and wait_rcp.rc == 0`` passes the ``is defined`` guard
   for a *skipped* result and then aborts the play with
   ``object of type 'dict' has no attribute 'rc'``.
2. An unquoted ``- (wait_rcp | default({'rc': 1})).rc != 0`` list item is parsed
   by YAML as a **mapping** (because of the ``'rc': 1`` pair), not as a string.
   ansible-core rejects a non-string conditional
   (``Conditional expressions must be strings``).

These tests evaluate the *real* conditions, read straight out of the task file,
through a real ``ansible-playbook`` run, and assert that an absent or skipped
result is never reported as a successful deletion.
"""

import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

BASE_DIR = Path(__file__).parent.parent
TASK_FILE = BASE_DIR / "tasks" / "delete_rosa_hcp_resources.yml"

ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")

requires_ansible = pytest.mark.skipif(
    ANSIBLE_PLAYBOOK is None,
    reason="ansible-playbook is required to evaluate Ansible conditionals",
)

# A registered result for a task that Ansible skipped: defined, but no 'rc'.
SKIPPED_RESULT = {
    "changed": False,
    "skipped": True,
    "skip_reason": "Conditional result was False",
}

# Resource blocks that follow the wait -> final check -> report pattern.
# (label, wait variable, final-check variable, task-name infix)
RESOURCES = [
    ("rcp", "wait_rcp", "final_rcp_check", "ROSAControlPlane"),
    ("rn", "wait_rn", "final_rn_check", "ROSANetwork"),
    ("rrc", "wait_rrc", "final_rrc_check", "ROSARoleConfig"),
]

# Probe role -> task name template. Each of these tasks consumes the wait and/or
# final-check result of its resource.
PROBE_TASKS = {
    "final_check": "Final check - verify {infix} is actually gone",
    "success": "Display {infix} deletion result",
    "warning": "Display {infix} still exists warning",
    "failed_fact": "Warn if {infix} still exists after all retries",
}

PROBE_ORDER = ("final_check", "success", "warning", "failed_fact")

# Scenario -> (wait result, final-check result). ``None`` means "undefined".
SCENARIOS = {
    "both_undefined": (None, None),
    "wait_skipped": (SKIPPED_RESULT, None),
    "wait_rc0": ({"rc": 0}, None),
    "wait_rc1_final_rc0": ({"rc": 1}, {"rc": 0}),
    "wait_rc1_final_rc1": ({"rc": 1}, {"rc": 1}),
    "wait_skipped_final_rc0": (SKIPPED_RESULT, {"rc": 0}),
    "wait_rc1_final_skipped": ({"rc": 1}, SKIPPED_RESULT),
}

# Scenario -> expected outcome of each probe, for every resource block.
# "success" must only be True when some check actually observed rc == 0; the
# run summary must agree with it.
EXPECTED = {
    #                       final_check success warning failed_fact
    "both_undefined": (True, False, True, True),
    "wait_skipped": (True, False, True, True),
    "wait_rc0": (False, True, False, False),
    "wait_rc1_final_rc0": (True, True, False, False),
    "wait_rc1_final_rc1": (True, False, True, True),
    "wait_skipped_final_rc0": (True, True, False, False),
    "wait_rc1_final_skipped": (True, False, True, True),
}

# The pre-fix expression that this change replaces. Kept verbatim so the test
# suite demonstrates the bug it guards against.
PRE_FIX_SUCCESS_CONDITION = (
    "(wait_rcp is defined and wait_rcp.rc == 0) or "
    "(final_rcp_check is defined and final_rcp_check.rc == 0)"
)

# ``.rc`` read by a condition without an immediately following default filter.
UNGUARDED_RC = re.compile(r"\.rc\b(?!\s*\|\s*default\()")


@functools.lru_cache(maxsize=1)
def _load_tasks():
    return yaml.safe_load(TASK_FILE.read_text(encoding="utf-8"))


def _task_by_name(name):
    for task in _load_tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"Task not found in {TASK_FILE.name}: {name}")


def _when_items(task):
    when = task.get("when")
    if when is None:
        return []
    return when if isinstance(when, list) else [when]


def _base_vars():
    """Variables that make every outer guard of the probed tasks true."""
    return {
        "wait_for_deletion": True,
        "delete_network": True,
        "delete_roles": True,
        "cluster_name": "test-cluster",
        "rosa_hcp_namespace": "ns",
        "discovered_rosa_network_name": "test-cluster-network",
        "discovered_rosa_role_config_name": "test-cluster-roles",
        "rcp_exists": {"stdout": "test-cluster"},
        "rmp_exists": {"stdout": "__NOTFOUND__"},
        "resources_to_delete": [],
    }


def _scenario_vars(scenario):
    extra = _base_vars()
    wait_result, final_result = SCENARIOS[scenario]
    for _label, wait_var, final_var, _infix in RESOURCES:
        if wait_result is not None:
            extra[wait_var] = wait_result
        if final_result is not None:
            extra[final_var] = final_result
    return extra


def _build_probe_playbook(results_file):
    """Build a playbook whose tasks reuse the real ``when`` conditions."""
    tasks = []
    probe_names = []
    for label, _wait_var, _final_var, infix in RESOURCES:
        for role in PROBE_ORDER:
            task = _task_by_name(PROBE_TASKS[role].format(infix=infix))
            probe = f"probe_{label}_{role}"
            probe_names.append(probe)
            tasks.append(
                {
                    "name": f"Probe {probe}",
                    "ansible.builtin.set_fact": {probe: True},
                    "when": task["when"],
                }
            )

    # The end-of-run summary must not claim a deletion that was never observed.
    summary_task = _task_by_name("Set deletion summary")
    tasks.append(
        {
            "name": "Evaluate deletion summary",
            "ansible.builtin.set_fact": summary_task["set_fact"],
        }
    )

    results = {name: "{{ %s | default(false) }}" % name for name in probe_names}
    results["deletion_summary"] = "{{ deletion_summary | default('') }}"
    tasks.append(
        {
            "name": "Write probe results",
            "ansible.builtin.copy": {
                "dest": str(results_file),
                "content": "{{ probe_results | to_json }}",
                "mode": "0644",
            },
            "vars": {"probe_results": results},
        }
    )

    return _play("Evaluate deletion result conditions", tasks)


def _play(name, tasks):
    return [
        {
            "name": name,
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "tasks": tasks,
        }
    ]


def _run_playbook(play, extra_vars, tmp_path):
    """Run a playbook with an environment that cannot alter the outcome."""
    playbook = tmp_path / "probe.yml"
    playbook.write_text(
        yaml.safe_dump(play, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ANSIBLE_")
    }
    env["ANSIBLE_LOCALHOST_WARNING"] = "false"
    env["ANSIBLE_CONFIG"] = str(tmp_path / "ansible.cfg")
    return subprocess.run(
        [
            ANSIBLE_PLAYBOOK,
            "-i",
            "localhost,",
            str(playbook),
            "-e",
            json.dumps(extra_vars),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session", name="scenario_results")
def scenario_results_fixture(tmp_path_factory):
    """Evaluate each scenario once; every resource block is probed per run."""
    cache = {}

    def _results(scenario):
        if scenario not in cache:
            tmp_path = tmp_path_factory.mktemp(scenario)
            results_file = tmp_path / "results.json"
            proc = _run_playbook(
                _build_probe_playbook(results_file),
                _scenario_vars(scenario),
                tmp_path,
            )
            assert proc.returncode == 0, (
                f"ansible-playbook failed for scenario {scenario}:\n"
                f"{proc.stdout}\n{proc.stderr}"
            )
            cache[scenario] = json.loads(results_file.read_text(encoding="utf-8"))
        return cache[scenario]

    return _results


# ================================================================
# The conditions must be valid Ansible conditionals
# ================================================================


def test_all_conditions_are_strings():
    """ansible-core rejects a non-string conditional.

    An unquoted ``- (x | default({'rc': 1})).rc != 0`` list item is YAML-parsed
    as a mapping, because of the ``'rc': 1`` pair, and fails at run time with
    "Conditional expressions must be strings".
    """
    offenders = []
    for task in _load_tasks():
        for item in _when_items(task):
            if not isinstance(item, (str, bool)):
                offenders.append((task.get("name"), item))
    assert offenders == [], f"non-string when conditions: {offenders}"


def test_no_unguarded_rc_access_in_conditions():
    """Every ``rc`` read in a condition must tolerate a missing ``rc`` key."""
    offenders = []
    for task in _load_tasks():
        for item in _when_items(task):
            if isinstance(item, str) and UNGUARDED_RC.search(item):
                offenders.append((task.get("name"), item))
    assert offenders == [], f"conditions reading .rc without a default: {offenders}"


# ================================================================
# Behaviour of the real conditions under real Ansible evaluation
# ================================================================


@requires_ansible
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
@pytest.mark.parametrize("resource", [r[0] for r in RESOURCES])
def test_condition_outcomes(scenario, resource, scenario_results):
    results = scenario_results(scenario)
    expected = dict(zip(PROBE_ORDER, EXPECTED[scenario]))
    actual = {role: results[f"probe_{resource}_{role}"] for role in PROBE_ORDER}
    assert actual == expected, f"{resource} / {scenario}: {actual} != {expected}"


@requires_ansible
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
@pytest.mark.parametrize("resource", [r[0] for r in RESOURCES])
def test_summary_agrees_with_reported_outcome(scenario, resource, scenario_results):
    """The run summary must never claim a deletion that was not observed."""
    results = scenario_results(scenario)
    infix = next(r[3] for r in RESOURCES if r[0] == resource)
    summary = results["deletion_summary"]
    if results[f"probe_{resource}_success"]:
        assert f"{infix}: ✅ Deleted" in summary
    else:
        assert f"{infix}: ⏳ Deletion initiated" in summary
        assert f"{infix}: ✅ Deleted" not in summary


@requires_ansible
@pytest.mark.parametrize(
    "scenario",
    ["both_undefined", "wait_skipped", "wait_rc1_final_rc1", "wait_rc1_final_skipped"],
)
def test_absent_or_skipped_result_is_never_reported_as_deleted(
    scenario, scenario_results
):
    results = scenario_results(scenario)
    for label, _wait_var, _final_var, _infix in RESOURCES:
        assert results[f"probe_{label}_success"] is False
        assert results[f"probe_{label}_warning"] is True
        assert results[f"probe_{label}_failed_fact"] is True


# ================================================================
# The pre-fix expression still fails, proving the regression is real
# ================================================================


@requires_ansible
def test_pre_fix_condition_crashes_on_skipped_result(tmp_path):
    """Defect 1: ``is defined`` does not protect a skipped result."""
    play = _play(
        "Pre-fix condition",
        [
            {
                "name": "Pre-fix success report",
                "ansible.builtin.set_fact": {"reported": True},
                "when": [PRE_FIX_SUCCESS_CONDITION],
            }
        ],
    )
    proc = _run_playbook(play, {"wait_rcp": SKIPPED_RESULT}, tmp_path)
    assert proc.returncode != 0
    assert "'rc'" in (proc.stdout + proc.stderr)


@requires_ansible
def test_current_condition_survives_skipped_result(tmp_path):
    """The shipped condition evaluates cleanly for the same input."""
    task = _task_by_name("Display ROSAControlPlane deletion result")
    condition = [
        item
        for item in _when_items(task)
        if isinstance(item, str) and "wait_rcp" in item
    ]
    assert condition, "expected the success report to consume wait_rcp"
    results_file = tmp_path / "reported.json"
    play = _play(
        "Current condition",
        [
            {
                "name": "Current success report",
                "ansible.builtin.set_fact": {"reported": True},
                "when": condition,
            },
            {
                "name": "Write result",
                "ansible.builtin.copy": {
                    "dest": str(results_file),
                    "content": "{{ {'reported': reported | default(false)} | to_json }}",
                    "mode": "0644",
                },
            },
        ],
    )
    proc = _run_playbook(play, {"wait_rcp": SKIPPED_RESULT}, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(results_file.read_text(encoding="utf-8")) == {"reported": False}
