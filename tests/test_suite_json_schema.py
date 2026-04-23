#!/usr/bin/env python3
"""
Tests for test suite JSON schema validation.

Validates all test suite JSON files without a live cluster:
    - Required fields (name, description, playbooks)
    - Playbook file paths exist on disk
    - extra_vars are dicts when present
    - tags are lists
    - documentation sections (when present)
"""

import json
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
TEST_SUITES_DIR = BASE_DIR / "test-suites"

SUITE_FILES = [
    "05-verify-mce-environment.json",
    "10-configure-mce-environment.json",
    "20-rosa-hcp-provision.json",
    "27-rosa-hcp-add-machinepool.json",
    "28-rosa-hcp-delete-machinepool.json",
    "30-rosa-hcp-delete.json",
    "40-enable-capi-disable-hypershift.json",
    "41-disable-capi-enable-hypershift.json",
]

# 10-configure-mce-environment.json does not have a documentation section
SUITES_WITH_DOCUMENTATION = [
    "05-verify-mce-environment.json",
    "20-rosa-hcp-provision.json",
    "27-rosa-hcp-add-machinepool.json",
    "28-rosa-hcp-delete-machinepool.json",
    "30-rosa-hcp-delete.json",
    "40-enable-capi-disable-hypershift.json",
    "41-disable-capi-enable-hypershift.json",
]


def _load_suite(filename):
    """Load and parse a test suite JSON file."""
    return json.loads((TEST_SUITES_DIR / filename).read_text())


# ================================================================
# Suite File Existence
# ================================================================

@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_file_exists(suite_file):
    path = TEST_SUITES_DIR / suite_file
    assert path.exists(), f"Test suite file missing: {suite_file}"


@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_is_valid_json(suite_file):
    text = (TEST_SUITES_DIR / suite_file).read_text()
    data = json.loads(text)
    assert isinstance(data, dict), f"{suite_file} should parse to a dict"


# ================================================================
# Required Fields
# ================================================================

@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_has_required_fields(suite_file):
    suite = _load_suite(suite_file)
    for field in ("name", "description", "playbooks"):
        assert field in suite, f"{suite_file} missing required field '{field}'"


@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_name_is_nonempty_string(suite_file):
    suite = _load_suite(suite_file)
    assert isinstance(suite["name"], str) and len(suite["name"]) > 0, \
        f"{suite_file}: 'name' must be a non-empty string"


@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_description_is_nonempty_string(suite_file):
    suite = _load_suite(suite_file)
    assert isinstance(suite["description"], str) and len(suite["description"]) > 0, \
        f"{suite_file}: 'description' must be a non-empty string"


@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_playbooks_is_nonempty_list(suite_file):
    suite = _load_suite(suite_file)
    assert isinstance(suite["playbooks"], list) and len(suite["playbooks"]) > 0, \
        f"{suite_file}: 'playbooks' must be a non-empty list"


# ================================================================
# Tags Validation
# ================================================================

@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_tags_is_list(suite_file):
    suite = _load_suite(suite_file)
    assert "tags" in suite, f"{suite_file} missing 'tags' field"
    assert isinstance(suite["tags"], list), \
        f"{suite_file}: 'tags' must be a list, got {type(suite['tags']).__name__}"


@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_suite_tags_are_strings(suite_file):
    suite = _load_suite(suite_file)
    for tag in suite.get("tags", []):
        assert isinstance(tag, str), \
            f"{suite_file}: each tag must be a string, got {type(tag).__name__}: {tag}"


# ================================================================
# Playbook File Paths
# ================================================================

@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_playbook_file_paths_exist(suite_file):
    suite = _load_suite(suite_file)
    for pb in suite["playbooks"]:
        pb_file = pb.get("file", pb.get("name"))
        assert pb_file is not None, \
            f"{suite_file}: playbook entry missing both 'file' and 'name'"
        full_path = BASE_DIR / pb_file
        assert full_path.exists(), \
            f"{suite_file}: playbook path does not exist: {pb_file}"


@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_playbook_entries_have_name(suite_file):
    suite = _load_suite(suite_file)
    for idx, pb in enumerate(suite["playbooks"]):
        assert "name" in pb, \
            f"{suite_file}: playbook[{idx}] missing 'name' field"


# ================================================================
# Extra Vars Validation
# ================================================================

@pytest.mark.parametrize("suite_file", SUITE_FILES)
def test_extra_vars_are_dicts_when_present(suite_file):
    suite = _load_suite(suite_file)
    for pb in suite["playbooks"]:
        if "extra_vars" in pb:
            assert isinstance(pb["extra_vars"], dict), \
                f"{suite_file}: playbook '{pb.get('name')}' extra_vars must be a dict, " \
                f"got {type(pb['extra_vars']).__name__}"


# ================================================================
# Documentation Sections
# ================================================================

@pytest.mark.parametrize("suite_file", SUITES_WITH_DOCUMENTATION)
def test_suite_has_documentation_section(suite_file):
    suite = _load_suite(suite_file)
    assert "documentation" in suite, \
        f"{suite_file} expected to have 'documentation' section"


@pytest.mark.parametrize("suite_file", SUITES_WITH_DOCUMENTATION)
def test_documentation_has_prerequisites(suite_file):
    suite = _load_suite(suite_file)
    doc = suite.get("documentation", {})
    assert "prerequisites" in doc, \
        f"{suite_file}: documentation missing 'prerequisites'"
    assert isinstance(doc["prerequisites"], list), \
        f"{suite_file}: documentation.prerequisites must be a list"


def test_configure_mce_has_no_documentation():
    """10-configure-mce-environment.json does not have a documentation section."""
    suite = _load_suite("10-configure-mce-environment.json")
    # This is expected - verify we handle it gracefully
    assert "documentation" not in suite, \
        "10-configure-mce-environment.json is not expected to have documentation"
