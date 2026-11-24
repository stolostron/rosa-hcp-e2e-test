#!/usr/bin/env python3
"""
Tests for the ROSAMachinePool readiness timeout wiring.

WHY THIS EXISTS
---------------
The readiness wait used to hardcode `retries: 60` / `delay: 30`, so the only
way to wait longer than 30 minutes was to edit the playbook. It now derives
both from machine_pool_readiness_timeout_minutes and
machine_pool_readiness_poll_interval, overridable with -e.

The risk in a derived retries/delay pair is that it silently stops matching the
stated budget — the same failure mode the deletion wait loops hit, where a
retry count derived as timeout/10 stopped tracking wall-clock once the sleep
interval changed. Here the sleep is constant (`delay`), so a count is safe, but
only if it is actually computed from the two variables rather than drifting
back to a literal.

These tests pin: the variables exist, the wait derives from them, the default
budget is unchanged, and the failure message tells the operator how to extend
it.
"""

import re
from pathlib import Path

import pytest
import yaml

BASE_DIR = Path(__file__).parent.parent
PLAYBOOK = BASE_DIR / "playbooks" / "add_rosa_machine_pool.yml"

TIMEOUT_VAR = "machine_pool_readiness_timeout_minutes"
INTERVAL_VAR = "machine_pool_readiness_poll_interval"


def _play():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert plays, "add_rosa_machine_pool.yml did not parse"
    return plays[0]


def _vars():
    return _play().get("vars", {}) or {}


def _readiness_task():
    """The task that waits for the pool to report ready."""
    for task in _play().get("tasks", []) or []:
        if isinstance(task, dict) and "until" in task:
            return task
    raise AssertionError("no task with an `until:` wait was found")


@pytest.mark.parametrize("name", [TIMEOUT_VAR, INTERVAL_VAR])
def test_readiness_vars_are_defined(name):
    assert name in _vars(), f"{name} is not defined in the playbook vars"


@pytest.mark.parametrize("name", [TIMEOUT_VAR, INTERVAL_VAR])
def test_readiness_vars_are_positive_ints(name):
    value = _vars().get(name)
    assert isinstance(value, int), f"{name} should be an int, got {value!r}"
    assert value > 0, f"{name} must be positive, got {value}"


def test_poll_interval_is_shorter_than_the_total_budget():
    """A poll interval >= the whole budget would yield fewer than one retry."""
    variables = _vars()
    total_seconds = variables[TIMEOUT_VAR] * 60
    assert variables[INTERVAL_VAR] < total_seconds, (
        f"{INTERVAL_VAR}={variables[INTERVAL_VAR]}s is not shorter than the "
        f"{total_seconds}s budget from {TIMEOUT_VAR}"
    )


def test_wait_derives_retries_and_delay_from_the_vars():
    """Both must be templated, or changing the variables has no effect."""
    task = _readiness_task()
    retries, delay = str(task.get("retries", "")), str(task.get("delay", ""))

    assert TIMEOUT_VAR in retries and INTERVAL_VAR in retries, (
        f"`retries` does not derive from {TIMEOUT_VAR}/{INTERVAL_VAR}: {retries!r}"
    )
    assert INTERVAL_VAR in delay, (
        f"`delay` does not derive from {INTERVAL_VAR}: {delay!r}"
    )
    for field, value in (("retries", retries), ("delay", delay)):
        assert not re.fullmatch(r"\s*\d+\s*", value), (
            f"`{field}` is a hardcoded literal ({value!r}); it should be derived"
        )


def test_default_budget_is_unchanged_at_thirty_minutes():
    """
    The derivation must reproduce the previous hardcoded 60 retries x 30s, so
    introducing the variables did not quietly change behaviour for anyone who
    does not override them.
    """
    variables = _vars()
    expected_retries = (variables[TIMEOUT_VAR] * 60) // variables[INTERVAL_VAR]
    assert expected_retries == 60, (
        f"default works out to {expected_retries} retries, expected 60 "
        "(30 minutes at a 30s poll interval)"
    )
    assert variables[INTERVAL_VAR] == 30


def test_failure_message_reports_the_configured_budget_and_the_override():
    """
    The old message said "within 30 minutes" as a literal, which would lie once
    the value became configurable.
    """
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert "did not become ready within" in text, "readiness failure message is missing"
    assert re.search(r"did not become ready within\s*\n?\s*\{\{\s*" + TIMEOUT_VAR, text), (
        "failure message does not interpolate the configured timeout — it will "
        "report a stale literal if the value is overridden"
    )
    assert f"-e {TIMEOUT_VAR}=" in text, (
        "failure message should name the override flag so the operator knows "
        "how to extend the wait"
    )
