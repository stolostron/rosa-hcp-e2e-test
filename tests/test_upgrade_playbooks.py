#!/usr/bin/env python3
"""Tests for upgrade playbook behaviour when OCM has no upgrade path.

A cluster that is already on the newest version in its channel, or a channel
where the next z-stream has not been published yet, has an empty
status.availableUpgrades. The upgrade suites must end cleanly in that case
instead of failing the periodic job.
"""

from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
PLAYBOOKS_DIR = BASE_DIR / "playbooks"

UPGRADE_PLAYBOOKS = [
    "upgrade_rosa_control_plane.yml",
    "upgrade_rosa_machine_pool.yml",
]

NO_UPGRADE_PATH = "available_upgrades | length == 0"


def _tasks(filename):
    """Return the flat task list of a single-play playbook."""
    playbook = yaml.safe_load((PLAYBOOKS_DIR / filename).read_text())
    return [task for play in playbook for task in play.get("tasks", [])]


def test_no_upgrade_path_does_not_fail_the_playbook():
    for filename in UPGRADE_PLAYBOOKS:
        for task in _tasks(filename):
            if "fail" in task and NO_UPGRADE_PATH in str(task.get("when", "")):
                raise AssertionError(
                    f"{filename}: task {task.get('name')!r} fails the playbook "
                    "when no upgrade path exists; it must end the play instead"
                )


def test_no_upgrade_path_is_reported():
    for filename in UPGRADE_PLAYBOOKS:
        reported = [
            task
            for task in _tasks(filename)
            if task.get("debug") and NO_UPGRADE_PATH in str(task.get("when", ""))
        ]
        assert reported, (
            f"{filename} must report why the upgrade was skipped"
        )


def test_no_upgrade_path_ends_the_play():
    for filename in UPGRADE_PLAYBOOKS:
        end_tasks = [
            task
            for task in _tasks(filename)
            if task.get("meta") == "end_play"
            and NO_UPGRADE_PATH in str(task.get("when", ""))
        ]
        assert end_tasks, (
            f"{filename} must end the play when available_upgrades is empty"
        )
