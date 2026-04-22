#!/usr/bin/env python3
"""
Tests for Ansible playbook structural validation.

Validates all 9 playbooks without a live cluster:
    - Valid YAML syntax
    - hosts=localhost
    - connection=local (for the 7 playbooks that set it)
    - vars_files references exist on disk
    - Playbook has tasks or roles
    - any_errors_fatal is set
"""

from pathlib import Path

import pytest
import yaml

BASE_DIR = Path(__file__).parent.parent
PLAYBOOKS_DIR = BASE_DIR / "playbooks"

ALL_PLAYBOOKS = [
    "create_rosa_hcp_cluster.yml",
    "delete_rosa_hcp_cluster.yml",
    "create_rosa_hcp_automated.yaml",
    "configure_mce_environment.yml",
    "verify_capi_environment.yaml",
    "enable_capi_disable_hypershift.yml",
    "disable_capi_enable_hypershift.yml",
    "add_rosa_machine_pool.yml",
    "delete_rosa_machine_pool.yml",
]

# These two playbooks do NOT set connection: local
PLAYBOOKS_WITHOUT_CONNECTION_LOCAL = {
    "configure_mce_environment.yml",
    "verify_capi_environment.yaml",
}

PLAYBOOKS_WITH_CONNECTION_LOCAL = [
    p for p in ALL_PLAYBOOKS if p not in PLAYBOOKS_WITHOUT_CONNECTION_LOCAL
]


def _load_playbook(filename):
    """Load and parse a playbook YAML file, returning the parsed list."""
    return yaml.safe_load((PLAYBOOKS_DIR / filename).read_text())


# ================================================================
# Valid YAML
# ================================================================

@pytest.mark.parametrize("playbook_file", ALL_PLAYBOOKS)
def test_playbook_is_valid_yaml(playbook_file):
    path = PLAYBOOKS_DIR / playbook_file
    assert path.exists(), f"Playbook not found: {playbook_file}"
    data = _load_playbook(playbook_file)
    assert isinstance(data, list), \
        f"{playbook_file}: playbook should parse as a list of plays"
    assert len(data) >= 1, \
        f"{playbook_file}: playbook must contain at least one play"


# ================================================================
# hosts=localhost
# ================================================================

@pytest.mark.parametrize("playbook_file", ALL_PLAYBOOKS)
def test_playbook_targets_localhost(playbook_file):
    plays = _load_playbook(playbook_file)
    play = plays[0]
    assert play.get("hosts") == "localhost", \
        f"{playbook_file}: first play should target 'localhost', got '{play.get('hosts')}'"


# ================================================================
# connection=local (only for playbooks that set it)
# ================================================================

@pytest.mark.parametrize("playbook_file", PLAYBOOKS_WITH_CONNECTION_LOCAL)
def test_playbook_uses_local_connection(playbook_file):
    plays = _load_playbook(playbook_file)
    play = plays[0]
    assert play.get("connection") == "local", \
        f"{playbook_file}: expected connection=local, got '{play.get('connection')}'"


@pytest.mark.parametrize("playbook_file", list(PLAYBOOKS_WITHOUT_CONNECTION_LOCAL))
def test_playbook_without_connection_local(playbook_file):
    """Verify that configure_mce and verify_capi do NOT set connection: local."""
    plays = _load_playbook(playbook_file)
    play = plays[0]
    assert "connection" not in play, \
        f"{playbook_file}: not expected to set 'connection', but found '{play.get('connection')}'"


# ================================================================
# vars_files Exist
# ================================================================

@pytest.mark.parametrize("playbook_file", ALL_PLAYBOOKS)
def test_vars_files_exist(playbook_file):
    plays = _load_playbook(playbook_file)
    play = plays[0]
    vars_files = play.get("vars_files", [])
    for vf in vars_files:
        resolved = (PLAYBOOKS_DIR / vf).resolve()
        assert resolved.exists(), \
            f"{playbook_file}: vars_file does not exist: {vf} (resolved to {resolved})"


# ================================================================
# Has Tasks or Roles
# ================================================================

@pytest.mark.parametrize("playbook_file", ALL_PLAYBOOKS)
def test_playbook_has_tasks_or_roles(playbook_file):
    plays = _load_playbook(playbook_file)
    play = plays[0]
    has_tasks = "tasks" in play and len(play["tasks"]) > 0
    has_roles = "roles" in play and len(play["roles"]) > 0
    assert has_tasks or has_roles, \
        f"{playbook_file}: play must have non-empty 'tasks' or 'roles'"


# ================================================================
# any_errors_fatal
# ================================================================

@pytest.mark.parametrize("playbook_file", ALL_PLAYBOOKS)
def test_playbook_any_errors_fatal(playbook_file):
    plays = _load_playbook(playbook_file)
    play = plays[0]
    assert play.get("any_errors_fatal") is True, \
        f"{playbook_file}: any_errors_fatal should be true"
