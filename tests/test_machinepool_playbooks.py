#!/usr/bin/env python3
"""
Tests for machinepool playbook structure and test suite configuration.

Validates without a live cluster:
    - YAML structure and syntax
    - Required variables and defaults
    - Resource API versions
    - Test suite JSON configuration
    - Jenkinsfile stage wiring
"""

import json
import re
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
PLAYBOOKS_DIR = BASE_DIR / "playbooks"
TEST_SUITES_DIR = BASE_DIR / "test-suites"
JENKINSFILE = BASE_DIR / "Jenkinsfile"


# ================================================================
# YAML Structure Tests
# ================================================================

def test_add_playbook_is_valid_yaml():
    playbook = yaml.safe_load(PLAYBOOKS_DIR.joinpath("add_rosa_machine_pool.yml").read_text())
    assert isinstance(playbook, list), "Playbook should be a list of plays"
    assert len(playbook) == 1, "Expected exactly one play"
    play = playbook[0]
    assert play["hosts"] == "localhost"
    assert play["connection"] == "local"
    assert play["any_errors_fatal"] is True


def test_delete_playbook_is_valid_yaml():
    playbook = yaml.safe_load(PLAYBOOKS_DIR.joinpath("delete_rosa_machine_pool.yml").read_text())
    assert isinstance(playbook, list), "Playbook should be a list of plays"
    assert len(playbook) == 1, "Expected exactly one play"
    play = playbook[0]
    assert play["hosts"] == "localhost"
    assert play["connection"] == "local"
    assert play["any_errors_fatal"] is True


# ================================================================
# Required Variables and Defaults
# ================================================================

def _get_task_names(playbook_path):
    playbook = yaml.safe_load(playbook_path.read_text())
    return [t.get("name", "") for t in playbook[0]["tasks"]]


def _get_playbook_text(playbook_path):
    return playbook_path.read_text()


def test_add_playbook_validates_cluster_name():
    task_names = _get_task_names(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "Validate required parameters" in task_names


def test_add_playbook_validates_pool_name_length():
    task_names = _get_task_names(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "Validate pool_name length" in task_names


def test_add_playbook_checks_existing_pool():
    task_names = _get_task_names(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "Check if ROSAMachinePool already exists" in task_names


def test_add_playbook_default_replicas_is_1():
    text = _get_playbook_text(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "default(1)" in text or "default('1')" in text, \
        "Default replicas should be 1 for smaller cluster size"


def test_add_playbook_default_instance_type():
    text = _get_playbook_text(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "m5.xlarge" in text


def test_add_playbook_default_namespace():
    text = _get_playbook_text(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "ns-rosa-hcp" in text


def test_delete_playbook_validates_required_params():
    task_names = _get_task_names(PLAYBOOKS_DIR / "delete_rosa_machine_pool.yml")
    assert "Validate required parameters" in task_names


def test_delete_playbook_checks_pool_exists():
    task_names = _get_task_names(PLAYBOOKS_DIR / "delete_rosa_machine_pool.yml")
    assert "Check if ROSAMachinePool exists" in task_names


def test_delete_playbook_handles_missing_pool_gracefully():
    task_names = _get_task_names(PLAYBOOKS_DIR / "delete_rosa_machine_pool.yml")
    assert "Skip if pool does not exist" in task_names
    assert "End if pool does not exist" in task_names


# ================================================================
# Resource API Versions
# ================================================================

def test_add_playbook_uses_correct_machinepool_api():
    text = _get_playbook_text(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "cluster.x-k8s.io/v1beta1" in text, "MachinePool should use v1beta1"
    assert "infrastructure.cluster.x-k8s.io/v1beta2" in text, "ROSAMachinePool should use v1beta2"


def test_add_playbook_creates_both_resources():
    task_names = _get_task_names(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "Create MachinePool resource" in task_names
    assert "Create ROSAMachinePool resource" in task_names


def test_delete_playbook_deletes_both_resources():
    task_names = _get_task_names(PLAYBOOKS_DIR / "delete_rosa_machine_pool.yml")
    assert "Delete MachinePool resource" in task_names
    assert "Delete ROSAMachinePool resource" in task_names


# ================================================================
# Wait / Readiness Logic
# ================================================================

def test_add_playbook_waits_for_ready():
    task_names = _get_task_names(PLAYBOOKS_DIR / "add_rosa_machine_pool.yml")
    assert "Wait for ROSAMachinePool to become ready" in task_names
    assert "Verify pool is ready" in task_names


def test_delete_playbook_waits_for_removal():
    task_names = _get_task_names(PLAYBOOKS_DIR / "delete_rosa_machine_pool.yml")
    assert "Wait for ROSAMachinePool to be fully removed" in task_names
    assert "Verify deletion completed" in task_names


# ================================================================
# Test Suite JSON Configuration
# ================================================================

def test_add_machinepool_suite_json():
    suite = json.loads(TEST_SUITES_DIR.joinpath("27-rosa-hcp-add-machinepool.json").read_text())
    assert suite["name"] == "Add ROSAMachinePool"
    assert "machinepool" in suite["tags"]
    assert "add" in suite["tags"]
    playbook = suite["playbooks"][0]
    assert playbook["file"] == "playbooks/add_rosa_machine_pool.yml"
    assert playbook["extra_vars"]["instance_type"] == "m5.xlarge"
    assert playbook["extra_vars"]["replicas"] == 1


def test_delete_machinepool_suite_json():
    suite = json.loads(TEST_SUITES_DIR.joinpath("28-rosa-hcp-delete-machinepool.json").read_text())
    assert suite["name"] == "Delete ROSAMachinePool"
    assert "machinepool" in suite["tags"]
    assert "delete" in suite["tags"]
    playbook = suite["playbooks"][0]
    assert playbook["file"] == "playbooks/delete_rosa_machine_pool.yml"


def test_add_suite_requires_cluster_name():
    suite = json.loads(TEST_SUITES_DIR.joinpath("27-rosa-hcp-add-machinepool.json").read_text())
    extra_vars = suite["playbooks"][0]["extra_vars"]
    assert "cluster_name" in extra_vars


def test_add_suite_has_documentation():
    suite = json.loads(TEST_SUITES_DIR.joinpath("27-rosa-hcp-add-machinepool.json").read_text())
    assert "documentation" in suite
    assert "prerequisites" in suite["documentation"]
    assert "quick_start" in suite["documentation"]
    assert "expected_results" in suite["documentation"]


def test_delete_suite_has_documentation():
    suite = json.loads(TEST_SUITES_DIR.joinpath("28-rosa-hcp-delete-machinepool.json").read_text())
    assert "documentation" in suite
    assert "prerequisites" in suite["documentation"]
    assert "expected_results" in suite["documentation"]


# ================================================================
# Jenkinsfile Integration
# ================================================================

def test_jenkinsfile_has_machinepool_stages():
    text = JENKINSFILE.read_text()
    assert "stage('Add a ROSA MachinePool')" in text
    assert "stage('Delete the ROSA MachinePool')" in text


def test_jenkinsfile_machinepool_stages_before_upgrade():
    text = JENKINSFILE.read_text()
    add_pos = text.index("stage('Add a ROSA MachinePool')")
    delete_pos = text.index("stage('Delete the ROSA MachinePool')")
    upgrade_pos = text.index("stage('Upgrade ROSA Control Plane')")
    assert add_pos < delete_pos < upgrade_pos, \
        "Machinepool stages should come before upgrade stages"


def test_jenkinsfile_machinepool_stages_after_provision():
    text = JENKINSFILE.read_text()
    provision_pos = text.index("stage('Provision a ROSA HCP Cluster')")
    add_pos = text.index("stage('Add a ROSA MachinePool')")
    assert provision_pos < add_pos, \
        "Machinepool add should come after provision"


def test_jenkinsfile_machinepool_uses_name_prefix():
    text = JENKINSFILE.read_text()
    add_section_start = text.index("stage('Add a ROSA MachinePool')")
    add_section_end = text.index("stage('Delete the ROSA MachinePool')")
    add_section = text[add_section_start:add_section_end]
    assert "${NAME_PREFIX}-rosa-hcp" in add_section, \
        "Add stage should derive cluster_name from NAME_PREFIX"
    assert "${NAME_PREFIX}-mp" in add_section, \
        "Add stage should derive pool_name from NAME_PREFIX"


def test_jenkinsfile_runs_correct_suites():
    text = JENKINSFILE.read_text()
    assert "27-rosa-hcp-add-machinepool" in text
    assert "28-rosa-hcp-delete-machinepool" in text


# ================================================================
# Cross-file Consistency
# ================================================================

def test_add_playbook_name_matches_suite():
    suite = json.loads(TEST_SUITES_DIR.joinpath("27-rosa-hcp-add-machinepool.json").read_text())
    playbook_path = suite["playbooks"][0]["file"]
    assert (BASE_DIR / playbook_path).exists(), \
        f"Playbook referenced in suite JSON does not exist: {playbook_path}"


def test_delete_playbook_name_matches_suite():
    suite = json.loads(TEST_SUITES_DIR.joinpath("28-rosa-hcp-delete-machinepool.json").read_text())
    playbook_path = suite["playbooks"][0]["file"]
    assert (BASE_DIR / playbook_path).exists(), \
        f"Playbook referenced in suite JSON does not exist: {playbook_path}"


def test_vars_files_exist():
    for playbook_name in ["add_rosa_machine_pool.yml", "delete_rosa_machine_pool.yml"]:
        playbook = yaml.safe_load((PLAYBOOKS_DIR / playbook_name).read_text())
        vars_files = playbook[0].get("vars_files", [])
        for vf in vars_files:
            resolved = (PLAYBOOKS_DIR / vf).resolve()
            assert resolved.exists(), f"vars_file {vf} referenced in {playbook_name} does not exist"
