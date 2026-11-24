#!/usr/bin/env python3
"""Guard the defaults for per-run inputs.

The suite JSON no longer supplies these values. Each default lives in the
layer that owns it: vars/vars.yml, the consuming playbook, or the task.
"""

from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
VARS_FILE = BASE_DIR / "vars" / "vars.yml"
PLAYBOOKS_DIR = BASE_DIR / "playbooks"


def _vars() -> dict:
    return yaml.safe_load(VARS_FILE.read_text())


def _playbook(name: str) -> str:
    return (PLAYBOOKS_DIR / name).read_text()


def test_rosa_hcp_namespace_default_lives_in_vars():
    assert _vars()["rosa_hcp_namespace"] == "ns-rosa-hcp"


def test_capi_namespace_default_is_deployment_mode_aware():
    value = _vars()["capi_namespace"]
    assert "capi-system" in value
    assert "multicluster-engine" in value


def test_create_cluster_region_default():
    text = _playbook("create_rosa_hcp_cluster.yml")
    assert "lookup('env', 'AWS_REGION')" in text
    assert "default('us-west-2')" in text


def test_install_standalone_region_default():
    text = _playbook("install_capi_standalone.yml")
    assert "lookup('env', 'AWS_REGION')" in text
    assert "default('us-east-1'" in text


def test_ocm_role_default_lives_in_verify_playbook():
    text = _playbook("verify_rosa_ocm_role.yml")
    assert 'ocm_role_config_name: "shared-ocm-role"' in text
