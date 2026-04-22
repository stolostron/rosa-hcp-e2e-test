#!/usr/bin/env python3
"""
Tests for vars/vars.yml default configuration.

Validates without a live cluster:
    - Required keys exist
    - supported_versions contains openshift_version
    - Feature flags are structured correctly (acm21174_config, acm21162)
    - Timeouts are positive integers
    - Role naming suffixes follow conventions
"""

from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
VARS_FILE = BASE_DIR / "vars" / "vars.yml"


def _load_vars():
    """Load and parse vars/vars.yml."""
    return yaml.safe_load(VARS_FILE.read_text())


# ================================================================
# File Existence and Parsing
# ================================================================

def test_vars_file_exists():
    assert VARS_FILE.exists(), "vars/vars.yml must exist"


def test_vars_is_valid_yaml():
    data = _load_vars()
    assert isinstance(data, dict), "vars.yml should parse as a dict"


# ================================================================
# Required Keys
# ================================================================

def test_required_common_keys():
    data = _load_vars()
    required = [
        "output_dir",
        "openshift_version",
        "supported_versions",
        "capi_namespace",
        "rosa_creds_secret",
    ]
    for key in required:
        assert key in data, f"vars.yml missing required key: {key}"


def test_required_mce_keys():
    data = _load_vars()
    mce_keys = ["mce_sub_name", "mce_namespace", "mce_name"]
    for key in mce_keys:
        assert key in data, f"vars.yml missing MCE key: {key}"


def test_required_cloud_provider_keys():
    data = _load_vars()
    assert "cloud_provider" in data, "vars.yml missing cloud_provider"
    assert "supported_providers" in data, "vars.yml missing supported_providers"


# ================================================================
# Version Management
# ================================================================

def test_supported_versions_contains_openshift_version():
    data = _load_vars()
    openshift_version = data["openshift_version"]
    supported = data["supported_versions"]
    assert openshift_version in supported, \
        f"openshift_version '{openshift_version}' not in supported_versions {supported}"


def test_supported_versions_is_list():
    data = _load_vars()
    assert isinstance(data["supported_versions"], list), \
        "supported_versions must be a list"
    assert len(data["supported_versions"]) > 0, \
        "supported_versions must not be empty"


def test_template_version_path_references_openshift_version():
    data = _load_vars()
    tvp = data.get("template_version_path", "")
    assert "openshift_version" in tvp, \
        "template_version_path should reference openshift_version variable"


# ================================================================
# Feature Flags: acm21174_config
# ================================================================

def test_acm21174_config_exists():
    data = _load_vars()
    assert "acm21174_config" in data, "vars.yml missing acm21174_config"


def test_acm21174_has_feature_name():
    data = _load_vars()
    config = data["acm21174_config"]
    assert "feature_name" in config, "acm21174_config missing feature_name"
    assert isinstance(config["feature_name"], str)


def test_acm21174_has_feature_flags():
    data = _load_vars()
    config = data["acm21174_config"]
    assert "feature_flags" in config, "acm21174_config missing feature_flags"
    flags = config["feature_flags"]
    assert isinstance(flags, dict), "feature_flags must be a dict"


def test_acm21174_has_test_config():
    data = _load_vars()
    config = data["acm21174_config"]
    assert "test_config" in config, "acm21174_config missing test_config"
    assert "timeout" in config["test_config"], "test_config missing timeout"


def test_acm21174_has_default_network_config():
    data = _load_vars()
    config = data["acm21174_config"]
    assert "default_network_config" in config, \
        "acm21174_config missing default_network_config"
    net = config["default_network_config"]
    assert "cidr_block" in net, "default_network_config missing cidr_block"


# ================================================================
# Feature Flags: acm21162
# ================================================================

def test_acm21162_config_exists():
    data = _load_vars()
    assert "acm21162" in data, "vars.yml missing acm21162"


def test_acm21162_has_enabled_flag():
    data = _load_vars()
    config = data["acm21162"]
    assert "enabled" in config, "acm21162 missing 'enabled' flag"
    assert isinstance(config["enabled"], bool), "acm21162.enabled must be a bool"


def test_acm21162_has_rosa_role_config():
    data = _load_vars()
    config = data["acm21162"]
    assert "rosa_role_config" in config, "acm21162 missing rosa_role_config"


def test_acm21162_has_testing_section():
    data = _load_vars()
    config = data["acm21162"]
    assert "testing" in config, "acm21162 missing testing section"


# ================================================================
# Timeouts > 0
# ================================================================

def test_acm21174_timeout_positive():
    data = _load_vars()
    timeout = data["acm21174_config"]["test_config"]["timeout"]
    assert isinstance(timeout, int) and timeout > 0, \
        f"acm21174 test_config.timeout must be > 0, got {timeout}"


def test_acm21162_creation_timeout_positive():
    data = _load_vars()
    timeout = data["acm21162"]["rosa_role_config"]["creation_timeout"]
    assert isinstance(timeout, int) and timeout > 0, \
        f"acm21162 creation_timeout must be > 0, got {timeout}"


def test_acm21162_validation_timeout_positive():
    data = _load_vars()
    timeout = data["acm21162"]["rosa_role_config"]["validation_timeout"]
    assert isinstance(timeout, int) and timeout > 0, \
        f"acm21162 validation_timeout must be > 0, got {timeout}"


def test_acm21162_cleanup_timeout_positive():
    data = _load_vars()
    timeout = data["acm21162"]["rosa_role_config"]["cleanup_timeout"]
    assert isinstance(timeout, int) and timeout > 0, \
        f"acm21162 cleanup_timeout must be > 0, got {timeout}"


def test_acm21162_poll_interval_positive():
    data = _load_vars()
    interval = data["acm21162"]["rosa_role_config"]["poll_interval"]
    assert isinstance(interval, int) and interval > 0, \
        f"acm21162 poll_interval must be > 0, got {interval}"


# ================================================================
# Role Naming Suffixes
# ================================================================

def test_role_naming_installer_suffix():
    data = _load_vars()
    suffix = data["acm21162"]["role_naming"]["installer_suffix"]
    assert suffix.endswith("-role"), \
        f"installer_suffix should end with '-role', got '{suffix}'"
    assert "installer" in suffix, \
        f"installer_suffix should contain 'installer', got '{suffix}'"


def test_role_naming_support_suffix():
    data = _load_vars()
    suffix = data["acm21162"]["role_naming"]["support_suffix"]
    assert suffix.endswith("-role"), \
        f"support_suffix should end with '-role', got '{suffix}'"
    assert "support" in suffix, \
        f"support_suffix should contain 'support', got '{suffix}'"


def test_role_naming_worker_suffix():
    data = _load_vars()
    suffix = data["acm21162"]["role_naming"]["worker_suffix"]
    assert suffix.endswith("-role"), \
        f"worker_suffix should end with '-role', got '{suffix}'"
    assert "worker" in suffix, \
        f"worker_suffix should contain 'worker', got '{suffix}'"
