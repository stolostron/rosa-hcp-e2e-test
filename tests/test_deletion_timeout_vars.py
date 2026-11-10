#!/usr/bin/env python3
"""
Tests for deletion and machine pool timeout variables.

Validates that playbooks define required timeout variables with sensible defaults.
"""

from pathlib import Path
import yaml

BASE_DIR = Path(__file__).parent.parent


def _load_playbook(filename):
    """Load and parse a playbook YAML file."""
    path = BASE_DIR / "playbooks" / filename
    with open(path) as f:
        data = yaml.safe_load(f)
    return data[0] if isinstance(data, list) else data


# ================================================================
# Delete ROSA HCP Cluster Playbook Timeouts
# ================================================================

def test_delete_rosa_hcp_cluster_has_vars_section():
    """Verify delete_rosa_hcp_cluster.yml has a vars section."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    assert "vars" in pb, "delete_rosa_hcp_cluster.yml missing vars section"


def test_delete_playbook_has_deletion_timeout():
    """Verify deletion_timeout variable exists and is positive."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    timeout = pb["vars"].get("deletion_timeout")
    assert timeout is not None, "deletion_timeout not defined"
    assert isinstance(timeout, int), f"deletion_timeout must be int, got {type(timeout)}"
    assert timeout > 0, f"deletion_timeout must be > 0, got {timeout}"


def test_delete_playbook_has_rosacontrolplane_timeout():
    """Verify rosacontrolplane_timeout variable exists and is positive."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    timeout = pb["vars"].get("rosacontrolplane_timeout")
    assert timeout is not None, "rosacontrolplane_timeout not defined"
    assert isinstance(timeout, int), f"rosacontrolplane_timeout must be int, got {type(timeout)}"
    assert timeout > 0, f"rosacontrolplane_timeout must be > 0, got {timeout}"


def test_delete_playbook_has_rosacontrolplane_final_check_retries():
    """Verify rosacontrolplane_final_check_retries variable exists and is positive."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    retries = pb["vars"].get("rosacontrolplane_final_check_retries")
    assert retries is not None, "rosacontrolplane_final_check_retries not defined"
    assert isinstance(retries, int), f"rosacontrolplane_final_check_retries must be int, got {type(retries)}"
    assert retries > 0, f"rosacontrolplane_final_check_retries must be > 0, got {retries}"


def test_delete_playbook_has_rosanetwork_timeout():
    """Verify rosanetwork_timeout variable exists and is positive."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    timeout = pb["vars"].get("rosanetwork_timeout")
    assert timeout is not None, "rosanetwork_timeout not defined"
    assert isinstance(timeout, int), f"rosanetwork_timeout must be int, got {type(timeout)}"
    assert timeout > 0, f"rosanetwork_timeout must be > 0, got {timeout}"


def test_delete_playbook_has_rosaroleconfig_timeout():
    """Verify rosaroleconfig_timeout variable exists and is positive."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    timeout = pb["vars"].get("rosaroleconfig_timeout")
    assert timeout is not None, "rosaroleconfig_timeout not defined"
    assert isinstance(timeout, int), f"rosaroleconfig_timeout must be int, got {type(timeout)}"
    assert timeout > 0, f"rosaroleconfig_timeout must be > 0, got {timeout}"


def test_delete_playbook_timeout_hierarchy():
    """Verify per-resource timeouts are reasonable vs global timeout."""
    pb = _load_playbook("delete_rosa_hcp_cluster.yml")
    global_timeout = pb["vars"].get("deletion_timeout")
    rcp_timeout = pb["vars"].get("rosacontrolplane_timeout")
    rn_timeout = pb["vars"].get("rosanetwork_timeout")
    rrc_timeout = pb["vars"].get("rosaroleconfig_timeout")

    # Per-resource timeouts should be less than global timeout (they're per-resource)
    assert rcp_timeout <= global_timeout, \
        f"rosacontrolplane_timeout ({rcp_timeout}s) should be <= global ({global_timeout}s)"
    assert rn_timeout <= global_timeout, \
        f"rosanetwork_timeout ({rn_timeout}s) should be <= global ({global_timeout}s)"
    assert rrc_timeout <= global_timeout, \
        f"rosaroleconfig_timeout ({rrc_timeout}s) should be <= global ({global_timeout}s)"

    # Network should be fastest (typical 2-5 min)
    assert rn_timeout < rcp_timeout, \
        f"rosanetwork_timeout ({rn_timeout}s) should be < rcp ({rcp_timeout}s)"


# ================================================================
# Add ROSA Machine Pool Playbook Timeouts
# ================================================================

def test_add_rosa_machine_pool_has_vars_section():
    """Verify add_rosa_machine_pool.yml has a vars section."""
    pb = _load_playbook("add_rosa_machine_pool.yml")
    assert "vars" in pb, "add_rosa_machine_pool.yml missing vars section"


def test_add_machine_pool_has_readiness_timeout_minutes():
    """Verify machine_pool_readiness_timeout_minutes variable exists and is positive."""
    pb = _load_playbook("add_rosa_machine_pool.yml")
    timeout = pb["vars"].get("machine_pool_readiness_timeout_minutes")
    assert timeout is not None, "machine_pool_readiness_timeout_minutes not defined"
    assert isinstance(timeout, int), f"machine_pool_readiness_timeout_minutes must be int, got {type(timeout)}"
    assert timeout > 0, f"machine_pool_readiness_timeout_minutes must be > 0, got {timeout}"


def test_add_machine_pool_has_readiness_poll_interval():
    """Verify machine_pool_readiness_poll_interval variable exists and is positive."""
    pb = _load_playbook("add_rosa_machine_pool.yml")
    interval = pb["vars"].get("machine_pool_readiness_poll_interval")
    assert interval is not None, "machine_pool_readiness_poll_interval not defined"
    assert isinstance(interval, int), f"machine_pool_readiness_poll_interval must be int, got {type(interval)}"
    assert interval > 0, f"machine_pool_readiness_poll_interval must be > 0, got {interval}"


def test_add_machine_pool_poll_interval_less_than_timeout():
    """Verify poll_interval is less than total timeout."""
    pb = _load_playbook("add_rosa_machine_pool.yml")
    timeout_min = pb["vars"].get("machine_pool_readiness_timeout_minutes")
    timeout_sec = timeout_min * 60
    interval = pb["vars"].get("machine_pool_readiness_poll_interval")

    assert interval < timeout_sec, \
        f"poll_interval ({interval}s) should be < total timeout ({timeout_sec}s)"


# ================================================================
# Documentation
# ================================================================

def test_deletion_timeout_vars_have_comments():
    """Verify timeout variables have documentation comments in YAML source."""
    path = BASE_DIR / "playbooks" / "delete_rosa_hcp_cluster.yml"
    content = path.read_text()

    # Should mention timeouts are configurable in comments
    assert "configurable" in content.lower(), \
        "Timeout variables should have 'configurable' in documentation"
    assert "-e" in content, \
        "Documentation should show how to override with -e flag"
