#!/usr/bin/env python3
"""
Tests that deletion timeout variables are wired up in both directions.

WHY THIS EXISTS
---------------
tasks/delete_rosa_hcp_resources.yml computed its retry counts from
per-resource timeouts:

    RETRIES: "{{ (rosanetwork_timeout | default(deletion_timeout) | int / 10) | int }}"

...but nothing in the repo ever *set* rosanetwork_timeout, so the
`| default(deletion_timeout)` fallback always won and every resource waited the
full 60-minute global timeout — including ROSANetwork, which normally finishes
in 2-5 minutes. The feature was present as plumbing with no values in it, and
nothing failed, so it went unnoticed.

These tests enforce symmetry in both directions:

  read  -> set    every timeout a task reads must be defined (no inert plumbing)
  set   -> read   every timeout the playbook defines must be read (no dead vars)

The second direction matters too: `rosacontrolplane_final_check_retries` was
proposed alongside these values, but nothing consumes it (the final-check task
hardcodes `seq 1 18`), so defining it would have created dead state.
"""

import re
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
DELETION_TASKS = BASE_DIR / "tasks" / "delete_rosa_hcp_resources.yml"
DELETION_PLAYBOOK = BASE_DIR / "playbooks" / "delete_rosa_hcp_cluster.yml"

GLOBAL_FALLBACK = "deletion_timeout"


def _playbook_vars():
    with open(DELETION_PLAYBOOK, encoding="utf-8") as handle:
        plays = yaml.safe_load(handle)
    assert plays, "deletion playbook did not parse"
    return plays[0].get("vars", {}) or {}


def _timeouts_read_by_tasks():
    """Timeout variable names referenced in the deletion tasks file."""
    text = DELETION_TASKS.read_text(encoding="utf-8")
    return set(re.findall(r"\b([a-z][a-z0-9_]*_timeout)\b", text))


def _timeouts_defined_in_playbook():
    return {k for k in _playbook_vars() if k.endswith("_timeout")}


def test_every_timeout_read_by_tasks_is_defined():
    """No inert plumbing: a timeout the tasks read must have a value."""
    read = _timeouts_read_by_tasks()
    defined = _timeouts_defined_in_playbook()
    missing = sorted(read - defined)
    assert not missing, (
        "these timeouts are read by tasks/delete_rosa_hcp_resources.yml but never "
        f"defined, so they silently fall back to {GLOBAL_FALLBACK}: {missing}"
    )


def test_every_timeout_defined_is_actually_read():
    """No dead vars: a timeout defined in the playbook must be consumed."""
    read = _timeouts_read_by_tasks()
    defined = _timeouts_defined_in_playbook()
    unused = sorted(defined - read)
    assert not unused, (
        "these timeouts are defined in the playbook but never read by "
        f"tasks/delete_rosa_hcp_resources.yml — dead state: {unused}"
    )


def test_per_resource_timeouts_are_positive_ints():
    for name, value in _playbook_vars().items():
        if name.endswith("_timeout"):
            assert isinstance(value, int), f"{name} should be an int, got {value!r}"
            assert value > 0, f"{name} must be positive, got {value}"


def test_per_resource_timeouts_do_not_exceed_the_global_timeout():
    """
    A per-resource timeout longer than the global one is almost certainly a
    mistake: the point of these values is to fail faster than the 60-minute
    fallback, not slower.
    """
    variables = _playbook_vars()
    global_timeout = variables.get(GLOBAL_FALLBACK)
    assert global_timeout, f"{GLOBAL_FALLBACK} is not defined in the playbook"

    for name, value in variables.items():
        if name.endswith("_timeout") and name != GLOBAL_FALLBACK:
            assert value <= global_timeout, (
                f"{name}={value} exceeds {GLOBAL_FALLBACK}={global_timeout}, so it "
                "can never take effect"
            )


def test_retries_are_derived_from_the_timeouts():
    """
    Each wait loop should compute RETRIES from its own timeout rather than
    hardcoding a count, otherwise changing the timeout has no effect.
    """
    text = DELETION_TASKS.read_text(encoding="utf-8")
    for resource in ("rosacontrolplane", "rosanetwork", "rosaroleconfig"):
        pattern = rf"RETRIES:.*{resource}_timeout"
        assert re.search(pattern, text), (
            f"no RETRIES expression derives from {resource}_timeout — the wait "
            "loop is probably using a hardcoded retry count"
        )
