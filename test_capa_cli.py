#!/usr/bin/env python3
"""Tests for the CAPA CLI tool."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path so we can import from the capa script
PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(PROJECT_ROOT))

# Import from the capa module (it's a script without .py extension)
# We create a symlink with .py extension for importlib to work
import importlib.util
import shutil

_capa_py = PROJECT_ROOT / "capa.py"
_needs_cleanup = False
if not _capa_py.exists():
    os.symlink(PROJECT_ROOT / "capa", _capa_py)
    _needs_cleanup = True

_spec = importlib.util.spec_from_file_location("capa_cli", _capa_py)
capa_cli = importlib.util.module_from_spec(_spec)
capa_cli.__name__ = "capa_cli"  # Prevent main() from running
_spec.loader.exec_module(capa_cli)
sys.modules["capa_cli"] = capa_cli  # Register so @patch("capa_cli.xxx") works

if _needs_cleanup:
    os.unlink(_capa_py)

FeatureRegistry = capa_cli.FeatureRegistry
ClusterAutomationSpec = capa_cli.ClusterAutomationSpec
ExecutionEngine = capa_cli.ExecutionEngine
C = capa_cli.C
load_spec = capa_cli.load_spec
_validate_feature_value = capa_cli._validate_feature_value_exit
_validate_feature_value_check = capa_cli._validate_feature_value_check
_evaluate_condition = capa_cli._evaluate_condition

# Also import the shared core validation for direct testing
from capa_core import (
    validate_feature_value,
    validate_cluster_name,
    resolve_spec_to_plan,
    FeatureRegistry as CoreFeatureRegistry,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def registry():
    """Load the real feature registry."""
    return FeatureRegistry(PROJECT_ROOT)


@pytest.fixture
def minimal_registry(tmp_path):
    """Create a minimal feature registry for isolated tests."""
    registry_data = {
        "version": "1.0",
        "var_map": {
            "private_network": "private",
            "channel_group": "channel_group",
        },
        "dependencies": {
            "machine_pool_upgrade": ["control_plane_upgrade"],
        },
        "sequences": {
            "upgrade": {
                "description": "Full cluster upgrade",
                "steps": [
                    {"feature": "control_plane_upgrade", "wait": True},
                    {"feature": "machine_pool_upgrade", "wait": True},
                ],
            },
        },
        "suites": [
            {
                "id": "test-suite",
                "name": "Test Suite",
                "description": "Test features",
                "category": "Testing",
                "phase": "Day2",
                "icon": "test",
                "features": [
                    {
                        "id": "channel_group",
                        "name": "Channel Group",
                        "description": "Update channel",
                        "type": "select",
                        "options": ["stable", "fast", "candidate"],
                        "mutable": True,
                        "applies_to": ["create", "apply", "upgrade"],
                        "default": "stable",
                        "k8s_field": ".spec.channelGroup",
                        "resource": "ROSAControlPlane",
                    },
                    {
                        "id": "control_plane_upgrade",
                        "name": "Control Plane Upgrade",
                        "description": "Upgrade CP",
                        "type": "version",
                        "mutable": True,
                        "applies_to": ["apply", "upgrade"],
                        "default": "",
                        "k8s_field": ".spec.version",
                        "resource": "ROSAControlPlane",
                        "playbook": "playbooks/upgrade_rosa_control_plane.yml",
                        "wait_timeout": 3600,
                    },
                    {
                        "id": "machine_pool_upgrade",
                        "name": "Machine Pool Upgrade",
                        "description": "Upgrade MP",
                        "type": "version",
                        "mutable": True,
                        "applies_to": ["apply", "upgrade"],
                        "default": "",
                        "k8s_field": ".spec.version",
                        "resource": "ROSAMachinePool",
                        "playbook": "playbooks/upgrade_rosa_machine_pool.yml",
                        "wait_timeout": 3600,
                        "depends_on": "control_plane_upgrade",
                    },
                    {
                        "id": "immutable_feat",
                        "name": "Immutable Feature",
                        "description": "Cannot change",
                        "type": "boolean",
                        "mutable": False,
                        "applies_to": ["create"],
                        "default": False,
                        "k8s_field": ".spec.immutable",
                        "resource": "ROSAControlPlane",
                    },
                ],
            },
        ],
    }
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    with open(schemas_dir / "feature-registry.yml", "w") as f:
        yaml.dump(registry_data, f)
    return FeatureRegistry(tmp_path)


def make_spec(action="apply", cluster="test-cluster", **kwargs):
    """Helper to build a ClusterAutomationSpec dict."""
    data = {
        "apiVersion": "capa-automation/v1",
        "kind": "ClusterAutomationSpec",
        "metadata": {"name": "test-spec"},
        "spec": {"action": action, "cluster": cluster, **kwargs},
    }
    return data


# ============================================================================
# FeatureRegistry Tests
# ============================================================================

class TestFeatureRegistry:
    def test_loads_all_suites(self, registry):
        assert len(registry.suites) == 9

    def test_loads_all_features(self, registry):
        assert len(registry.all_features()) == 26

    def test_get_feature_exists(self, registry):
        feat = registry.get_feature("channel_group")
        assert feat is not None
        assert feat["name"] == "Channel Group"
        assert feat["type"] == "select"

    def test_get_feature_not_found(self, registry):
        assert registry.get_feature("nonexistent") is None

    def test_var_map(self, registry):
        vm = registry.var_map
        assert vm["private_network"] == "private"
        assert vm["byon"] == "byon_vpc"
        assert vm["disk_size"] == "root_volume_size"

    def test_resolve_var_mapped(self, registry):
        assert registry.resolve_var("private_network") == "private"

    def test_resolve_var_unmapped(self, registry):
        # Features without a var_map entry return their ID
        assert registry.resolve_var("node_labels") == "node_labels"

    def test_dependencies(self, registry):
        deps = registry.dependencies
        assert "machine_pool_upgrade" in deps
        assert "control_plane_upgrade" in deps["machine_pool_upgrade"]

    def test_get_deps(self, registry):
        assert registry.get_deps("machine_pool_upgrade") == ["control_plane_upgrade"]
        assert registry.get_deps("channel_group") == []

    def test_sequences(self, registry):
        seqs = registry.sequences
        assert "upgrade" in seqs
        assert "provision" in seqs
        assert "delete" in seqs

    def test_suite_metadata(self, registry):
        for suite in registry.suites:
            assert "id" in suite
            assert "name" in suite
            assert "phase" in suite
            assert "features" in suite

    def test_feature_has_applies_to(self, registry):
        for feat_id, feat in registry.all_features().items():
            assert "applies_to" in feat, f"Feature {feat_id} missing applies_to"

    def test_no_duplicate_feature_ids(self, registry):
        ids = []
        for suite in registry.suites:
            for feat in suite["features"]:
                ids.append(feat["id"])
        assert len(ids) == len(set(ids)), f"Duplicate feature IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_disk_volume_size_removed(self, registry):
        """disk_volume_size was a duplicate of disk_size and should be removed."""
        assert registry.get_feature("disk_volume_size") is None
        assert registry.get_feature("disk_size") is not None

    def test_minimal_registry(self, minimal_registry):
        assert len(minimal_registry.all_features()) == 4
        assert minimal_registry.get_feature("channel_group") is not None
        assert minimal_registry.resolve_var("private_network") == "private"


# ============================================================================
# ClusterAutomationSpec Tests
# ============================================================================

class TestClusterAutomationSpec:
    def test_basic_creation(self):
        data = make_spec(action="create", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        assert spec.action == "create"
        assert spec.cluster == "my-cluster"
        assert spec.name == "test-spec"

    def test_invalid_api_version(self):
        data = make_spec()
        data["apiVersion"] = "wrong/v1"
        with pytest.raises(ValueError, match="Unsupported apiVersion"):
            ClusterAutomationSpec(data)

    def test_invalid_kind(self):
        data = make_spec()
        data["kind"] = "WrongKind"
        with pytest.raises(ValueError, match="Unsupported kind"):
            ClusterAutomationSpec(data)

    def test_defaults(self):
        data = make_spec()
        spec = ClusterAutomationSpec(data)
        assert spec.namespace == "ns-rosa-hcp"
        assert spec.region == "us-west-2"
        assert spec.channel == "stable"
        assert spec.version == ""
        assert spec.name_prefix == ""
        assert spec.features == {}
        assert spec.actions == []

    def test_overrides_cluster(self):
        data = make_spec(cluster="original")
        spec = ClusterAutomationSpec(data, overrides={"cluster": "override"})
        assert spec.cluster == "override"

    def test_overrides_version(self):
        data = make_spec()
        spec = ClusterAutomationSpec(data, overrides={"version": "4.20.12"})
        assert spec.version == "4.20.12"

    def test_overrides_namespace(self):
        data = make_spec()
        spec = ClusterAutomationSpec(data, overrides={"namespace": "custom-ns"})
        assert spec.namespace == "custom-ns"

    def test_overrides_feature_prefix(self):
        data = make_spec()
        spec = ClusterAutomationSpec(data, overrides={"feature.channel_group": "fast"})
        assert spec.features["channel_group"] == "fast"

    def test_overrides_generic_key_goes_to_features(self):
        data = make_spec()
        spec = ClusterAutomationSpec(data, overrides={"channel_group": "fast"})
        assert spec.features["channel_group"] == "fast"

    def test_actions_list(self):
        data = make_spec(actions=[
            {"feature": "channel_group", "value": "fast"},
            {"feature": "control_plane_upgrade", "value": "4.20.12"},
        ])
        spec = ClusterAutomationSpec(data)
        assert len(spec.actions) == 2
        assert spec.actions[0]["feature"] == "channel_group"

    def test_profile_from_metadata(self):
        data = make_spec()
        data["metadata"]["profile"] = "ha-production"
        spec = ClusterAutomationSpec(data)
        assert spec.profile == "ha-production"

    def test_features_dict(self):
        data = make_spec(features={"private_network": True, "channel_group": "fast"})
        spec = ClusterAutomationSpec(data)
        assert spec.features["private_network"] is True
        assert spec.features["channel_group"] == "fast"


# ============================================================================
# ExecutionEngine Plan Tests
# ============================================================================

class TestExecutionEnginePlan:
    def test_plan_create(self, minimal_registry, tmp_path):
        data = make_spec(action="create", cluster="", name_prefix="test1",
                         features={"channel_group": "fast"})
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) == 1
        assert plan[0]["type"] == "playbook"
        assert plan[0]["playbook"] == "playbooks/create_rosa_hcp_cluster.yml"
        assert plan[0]["extra_vars"]["name_prefix"] == "test1"
        assert plan[0]["extra_vars"]["channel_group"] == "fast"

    def test_plan_create_uses_var_map(self, minimal_registry, tmp_path):
        data = make_spec(action="create", cluster="", name_prefix="test1",
                         features={"private_network": True})
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        # private_network should be mapped to "private" via var_map
        assert plan[0]["extra_vars"]["private"] is True
        assert "private_network" not in plan[0]["extra_vars"]

    def test_plan_upgrade(self, minimal_registry, tmp_path):
        data = make_spec(action="upgrade", cluster="my-cluster", version="4.20.12")
        data["spec"]["version"] = "4.20.12"
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) == 2
        assert plan[0]["name"] == "Upgrade control plane to 4.20.12"
        assert plan[0]["feature"] == "control_plane_upgrade"
        assert plan[1]["name"] == "Upgrade machine pool to 4.20.12"
        assert plan[1]["feature"] == "machine_pool_upgrade"
        assert plan[1]["depends_on"] == "control_plane_upgrade"

    def test_plan_upgrade_requires_cluster(self, minimal_registry, tmp_path):
        data = make_spec(action="upgrade", cluster="")
        data["spec"]["version"] = "4.20.12"
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="upgrade requires --cluster"):
            engine.plan(spec)

    def test_plan_upgrade_requires_version(self, minimal_registry, tmp_path):
        data = make_spec(action="upgrade", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="upgrade requires --version"):
            engine.plan(spec)

    def test_plan_apply_with_patch(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster",
                         actions=[{"feature": "channel_group", "value": "fast"}])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) == 1
        assert plan[0]["type"] == "patch"
        assert plan[0]["resource"] == "ROSAControlPlane"
        assert plan[0]["k8s_field"] == ".spec.channelGroup"
        assert plan[0]["value"] == "fast"

    def test_plan_apply_with_playbook(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster",
                         actions=[{"feature": "control_plane_upgrade", "value": "4.20.12"}])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) == 1
        assert plan[0]["type"] == "playbook"
        assert "upgrade_rosa_control_plane" in plan[0]["playbook"]

    def test_plan_apply_requires_cluster(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="",
                         actions=[{"feature": "channel_group", "value": "fast"}])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="apply requires --cluster"):
            engine.plan(spec)

    def test_plan_apply_requires_actions(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="apply requires actions"):
            engine.plan(spec)

    def test_plan_apply_unknown_feature(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster",
                         actions=[{"feature": "nonexistent", "value": "x"}])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="Unknown feature"):
            engine.plan(spec)

    def test_plan_delete(self, minimal_registry, tmp_path):
        data = make_spec(action="delete", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) == 1
        assert plan[0]["type"] == "playbook"
        assert "delete_rosa_hcp_cluster" in plan[0]["playbook"]
        assert plan[0]["extra_vars"]["cluster_name"] == "my-cluster"

    def test_plan_delete_requires_cluster(self, minimal_registry, tmp_path):
        data = make_spec(action="delete", cluster="")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="delete requires --cluster"):
            engine.plan(spec)

    def test_plan_unknown_action(self, minimal_registry, tmp_path):
        data = make_spec(action="bogus", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        with pytest.raises(ValueError, match="Unknown action"):
            engine.plan(spec)

    def test_plan_multi_step_apply(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster", actions=[
            {"feature": "channel_group", "value": "fast"},
            {"feature": "control_plane_upgrade", "value": "4.20.12"},
        ])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) == 2
        assert plan[0]["step"] == 1
        assert plan[1]["step"] == 2


# ============================================================================
# ExecutionEngine Execute Tests
# ============================================================================

class TestExecutionEngineExecute:
    def test_dry_run_returns_dry_run_status(self, minimal_registry, tmp_path):
        data = make_spec(action="delete", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)
        results = engine.execute(plan)

        assert len(results) == 1
        assert results[0]["status"] == "dry_run"

    def test_execute_playbook_not_found(self, minimal_registry, tmp_path):
        data = make_spec(action="delete", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=False)
        plan = engine.plan(spec)
        results = engine.execute(plan)

        assert results[0]["status"] == "failed"
        assert "not found" in results[0]["error"]

    def test_execute_patch_step(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster",
                         actions=[{"feature": "channel_group", "value": "fast"}])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=False)
        plan = engine.plan(spec)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="patched")
            results = engine.execute(plan)

        assert results[0]["status"] == "completed"
        call_args = mock_run.call_args[0][0]
        assert "oc" in call_args
        assert "patch" in call_args

    def test_execute_patch_failure(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster",
                         actions=[{"feature": "channel_group", "value": "fast"}])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=False)
        plan = engine.plan(spec)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="not found")
            results = engine.execute(plan)

        assert results[0]["status"] == "failed"

    def test_execute_stops_on_failure(self, minimal_registry, tmp_path):
        data = make_spec(action="apply", cluster="my-cluster", actions=[
            {"feature": "channel_group", "value": "fast"},
            {"feature": "channel_group", "value": "stable"},
        ])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=False)
        plan = engine.plan(spec)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            results = engine.execute(plan)

        assert results[0]["status"] == "failed"
        assert results[1]["status"] == "skipped"

    def test_execute_playbook_success(self, minimal_registry, tmp_path):
        # Create a fake playbook file so the file-exists check passes
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "delete_rosa_hcp_cluster.yml").write_text("---\n- hosts: localhost\n")

        data = make_spec(action="delete", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=False)
        plan = engine.plan(spec)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="ok")
            results = engine.execute(plan)

        assert results[0]["status"] == "completed"

    def test_execute_playbook_timeout(self, minimal_registry, tmp_path):
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "delete_rosa_hcp_cluster.yml").write_text("---\n- hosts: localhost\n")

        data = make_spec(action="delete", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=False)
        plan = engine.plan(spec)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="ansible", timeout=30)
            results = engine.execute(plan)

        assert results[0]["status"] == "failed"
        assert "Timeout" in results[0]["error"]


# ============================================================================
# Validation Tests
# ============================================================================

class TestValidation:
    def test_validate_boolean_valid(self):
        feat = {"id": "test", "type": "boolean"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, True, errors, warnings)
        assert len(errors) == 0

    def test_validate_boolean_invalid(self):
        feat = {"id": "test", "type": "boolean"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "yes", errors, warnings)
        assert len(errors) == 1
        assert "boolean" in errors[0]

    def test_validate_select_valid(self):
        feat = {"id": "test", "type": "select", "options": ["a", "b", "c"]}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "b", errors, warnings)
        assert len(errors) == 0

    def test_validate_select_invalid(self):
        feat = {"id": "test", "type": "select", "options": ["a", "b", "c"]}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "d", errors, warnings)
        assert len(errors) == 1
        assert "one of" in errors[0]

    def test_validate_number_valid(self):
        feat = {"id": "test", "type": "number"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, 42, errors, warnings)
        assert len(errors) == 0

    def test_validate_number_invalid(self):
        feat = {"id": "test", "type": "number"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "not_a_number", errors, warnings)
        assert len(errors) == 1
        assert "number" in errors[0]

    def test_validate_string_max_length_ok(self):
        feat = {"id": "test", "type": "string", "max_length": 15}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "short", errors, warnings)
        assert len(errors) == 0

    def test_validate_string_max_length_exceeded(self):
        feat = {"id": "test", "type": "string", "max_length": 5}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "too_long_string", errors, warnings)
        assert len(errors) == 1
        assert "max length" in errors[0]

    def test_validate_key_value_valid(self):
        feat = {"id": "test", "type": "key_value"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, {"key": "val"}, errors, warnings)
        assert len(errors) == 0

    def test_validate_key_value_invalid(self):
        feat = {"id": "test", "type": "key_value"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "not_a_dict", errors, warnings)
        assert len(errors) == 1
        assert "key-value" in errors[0]

    def test_validate_list_valid(self):
        feat = {"id": "test", "type": "list"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, ["a", "b"], errors, warnings)
        assert len(errors) == 0

    def test_validate_list_invalid(self):
        feat = {"id": "test", "type": "list"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, "not_a_list", errors, warnings)
        assert len(errors) == 1
        assert "list" in errors[0]

    def test_validate_range_valid(self):
        feat = {"id": "test", "type": "range"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, {"min": 1, "max": 5}, errors, warnings)
        assert len(errors) == 0

    def test_validate_range_min_greater_than_max(self):
        feat = {"id": "test", "type": "range"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, {"min": 10, "max": 2}, errors, warnings)
        assert len(errors) == 1
        assert "min" in errors[0] and "max" in errors[0]

    def test_validate_range_invalid_type(self):
        feat = {"id": "test", "type": "range"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, 42, errors, warnings)
        assert len(errors) == 1
        assert "range" in errors[0]

    def test_validate_range_missing_keys(self):
        feat = {"id": "test", "type": "range"}
        errors, warnings = [], []
        _validate_feature_value_check(feat, {"min": 1}, errors, warnings)
        assert len(errors) == 1


# ============================================================================
# cmd_set Validation Tests (via _validate_feature_value)
# ============================================================================

class TestCmdSetValidation:
    def test_set_immutable_feature_passes_type_check(self):
        """_validate_feature_value only checks type, not mutability.
        Mutability is checked in cmd_set before calling this function."""
        feat = {"id": "private_network", "type": "boolean", "mutable": False,
                "applies_to": ["create"]}
        # Should not raise — type check passes (True is a valid boolean)
        _validate_feature_value(feat, True)

    def test_set_select_invalid_exits(self):
        feat = {"id": "channel_group", "type": "select",
                "options": ["stable", "fast", "candidate"],
                "mutable": True, "applies_to": ["apply"]}
        with pytest.raises(SystemExit):
            _validate_feature_value(feat, "invalid")

    def test_set_select_valid_passes(self):
        feat = {"id": "channel_group", "type": "select",
                "options": ["stable", "fast", "candidate"],
                "mutable": True, "applies_to": ["apply"]}
        # Should not raise
        _validate_feature_value(feat, "fast")

    def test_set_boolean_invalid_exits(self):
        feat = {"id": "proxy", "type": "boolean", "mutable": True,
                "applies_to": ["apply"]}
        with pytest.raises(SystemExit):
            _validate_feature_value(feat, "yes")

    def test_set_number_invalid_exits(self):
        feat = {"id": "parallel", "type": "number", "mutable": True,
                "applies_to": ["apply"]}
        with pytest.raises(SystemExit):
            _validate_feature_value(feat, "abc")

    def test_set_string_max_length_exits(self):
        feat = {"id": "domain", "type": "string", "mutable": True,
                "applies_to": ["apply"], "max_length": 5}
        with pytest.raises(SystemExit):
            _validate_feature_value(feat, "too_long_string")


# ============================================================================
# load_spec Tests
# ============================================================================

class TestLoadSpec:
    def test_load_from_file(self, tmp_path):
        spec_data = make_spec(action="apply", cluster="test-cluster",
                              actions=[{"feature": "channel_group", "value": "fast"}])
        spec_file = tmp_path / "test.yml"
        with open(spec_file, "w") as f:
            yaml.dump(spec_data, f)

        args = MagicMock()
        args.file = str(spec_file)
        args.profile = None
        args.extra_vars = None
        args.cluster = None
        args.version = None
        args.namespace = None
        args.name_prefix = None

        spec = load_spec(args, tmp_path)
        assert spec.action == "apply"
        assert spec.cluster == "test-cluster"

    def test_load_from_file_with_overrides(self, tmp_path):
        spec_data = make_spec(action="apply", cluster="original")
        spec_file = tmp_path / "test.yml"
        with open(spec_file, "w") as f:
            yaml.dump(spec_data, f)

        args = MagicMock()
        args.file = str(spec_file)
        args.profile = None
        args.extra_vars = ["channel_group=fast"]
        args.cluster = "override-cluster"
        args.version = "4.20.12"
        args.namespace = None
        args.name_prefix = None

        spec = load_spec(args, tmp_path)
        assert spec.cluster == "override-cluster"
        assert spec.version == "4.20.12"
        assert spec.features["channel_group"] == "fast"

    def test_load_from_profile(self, tmp_path):
        spec_data = make_spec(action="create",
                              features={"private_network": True})
        specs_dir = tmp_path / "specs" / "profiles"
        specs_dir.mkdir(parents=True)
        with open(specs_dir / "test-profile.yml", "w") as f:
            yaml.dump(spec_data, f)

        args = MagicMock()
        args.file = None
        args.profile = "test-profile"
        args.extra_vars = None
        args.cluster = None
        args.version = None
        args.namespace = None
        args.name_prefix = None

        spec = load_spec(args, tmp_path)
        assert spec.features["private_network"] is True

    def test_load_inline_spec(self):
        args = MagicMock()
        args.file = None
        args.profile = None
        args.extra_vars = None
        args.cluster = "my-cluster"
        args.version = None
        args.namespace = None
        args.name_prefix = None
        args.command = "delete"

        spec = load_spec(args, PROJECT_ROOT)
        assert spec.action == "delete"
        assert spec.cluster == "my-cluster"

    def test_extra_vars_boolean_parsing(self, tmp_path):
        spec_data = make_spec(action="create")
        spec_file = tmp_path / "test.yml"
        with open(spec_file, "w") as f:
            yaml.dump(spec_data, f)

        args = MagicMock()
        args.file = str(spec_file)
        args.profile = None
        args.extra_vars = ["private_network=true", "byon=false"]
        args.cluster = None
        args.version = None
        args.namespace = None
        args.name_prefix = None

        spec = load_spec(args, tmp_path)
        assert spec.features["private_network"] is True
        assert spec.features["byon"] is False

    def test_extra_vars_number_parsing(self, tmp_path):
        spec_data = make_spec(action="create")
        spec_file = tmp_path / "test.yml"
        with open(spec_file, "w") as f:
            yaml.dump(spec_data, f)

        args = MagicMock()
        args.file = str(spec_file)
        args.profile = None
        args.extra_vars = ["parallel_upgrade=3"]
        args.cluster = None
        args.version = None
        args.namespace = None
        args.name_prefix = None

        spec = load_spec(args, tmp_path)
        assert spec.features["parallel_upgrade"] == 3


# ============================================================================
# CLI Integration Tests (subprocess)
# ============================================================================

class TestCLIIntegration:
    def test_help(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "--help"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "CAPA CLI" in result.stdout

    def test_features_command(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "features"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "Feature Registry" in result.stdout
        assert "channel_group" in result.stdout

    def test_specs_command(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "specs"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "Available Specs" in result.stdout

    def test_set_dry_run(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "set",
             "channel_group", "fast", "-c", "test-cluster", "--dry-run"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout

    def test_set_unknown_feature(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "set",
             "bogus_feature", "val", "-c", "test-cluster", "--dry-run"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0
        assert "Unknown feature" in result.stderr or "Unknown feature" in result.stdout

    def test_set_immutable_feature(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "set",
             "private_network", "true", "-c", "test-cluster", "--dry-run"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0
        assert "immutable" in (result.stderr + result.stdout).lower()

    def test_set_invalid_select_value(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "set",
             "channel_group", "invalid", "-c", "test-cluster", "--dry-run"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0

    def test_validate_valid_spec(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "validate",
             str(PROJECT_ROOT / "specs" / "features" / "channel-group.yml")],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "Valid spec" in result.stdout

    def test_validate_profile(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "validate",
             str(PROJECT_ROOT / "specs" / "profiles" / "default.yml")],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0

    def test_validate_nonexistent_file(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "validate",
             "/nonexistent/file.yml"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0

    def test_plan_with_spec_file(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "plan",
             "-f", str(PROJECT_ROOT / "specs" / "features" / "channel-group.yml"),
             "--cluster", "test-cluster"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout

    def test_plan_with_profile(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa"), "plan",
             "--profile", "default", "-e", "name_prefix=test1"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout

    def test_generate_specs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy registry to temp dir
            tmp_schemas = Path(tmpdir) / "schemas"
            tmp_schemas.mkdir()
            tmp_specs = Path(tmpdir) / "specs" / "features"
            tmp_specs.mkdir(parents=True)

            import shutil
            shutil.copy(PROJECT_ROOT / "schemas" / "feature-registry.yml",
                        tmp_schemas / "feature-registry.yml")
            # Copy the capa script and its dependencies
            shutil.copy(PROJECT_ROOT / "capa", Path(tmpdir) / "capa")
            shutil.copy(PROJECT_ROOT / "capa_core.py", Path(tmpdir) / "capa_core.py")

            result = subprocess.run(
                [sys.executable, str(Path(tmpdir) / "capa"), "generate-specs"],
                capture_output=True, text=True, timeout=10
            )
            assert result.returncode == 0
            assert "Generated" in result.stdout

            # Check files were created
            generated = list(tmp_specs.glob("*.yml"))
            assert len(generated) > 0

    def test_no_command_shows_help(self):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "capa")],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0


# ============================================================================
# Real Spec File Validation Tests
# ============================================================================

class TestProfileInheritance:
    """Tests for profile inheritance (metadata.inherits)."""

    def test_inheritance_merges_parent_features(self, registry):
        """Child inherits parent features, child features win on conflict."""
        data = {
            "apiVersion": "capa-automation/v1",
            "kind": "ClusterAutomationSpec",
            "metadata": {"name": "child", "inherits": "default"},
            "spec": {
                "action": "create",
                "features": {
                    "instance_type": "m5.4xlarge",  # override parent's m5.xlarge
                },
            },
        }
        spec = capa_cli.ClusterAutomationSpec(data, base_dir=PROJECT_ROOT)
        # Child override wins
        assert spec.features["instance_type"] == "m5.4xlarge"
        # Parent features inherited
        assert spec.features["availability_zones"] == "1"
        assert "automated" in spec.features["additional_tags"]

    def test_inheritance_child_features_win(self, registry):
        """When both parent and child define the same feature, child wins."""
        data = {
            "apiVersion": "capa-automation/v1",
            "kind": "ClusterAutomationSpec",
            "metadata": {"name": "override-test", "inherits": "default"},
            "spec": {
                "action": "create",
                "features": {
                    "additional_tags": {"custom": "value"},
                },
            },
        }
        spec = capa_cli.ClusterAutomationSpec(data, base_dir=PROJECT_ROOT)
        # Child's tags replace parent's tags entirely (dict override)
        assert spec.features["additional_tags"] == {"custom": "value"}

    def test_inheritance_inherits_top_level_fields(self, registry):
        """Child inherits parent's version, region, channel if not set."""
        data = {
            "apiVersion": "capa-automation/v1",
            "kind": "ClusterAutomationSpec",
            "metadata": {"name": "minimal", "inherits": "default"},
            "spec": {
                "action": "create",
                "features": {},
            },
        }
        spec = capa_cli.ClusterAutomationSpec(data, base_dir=PROJECT_ROOT)
        assert spec.version == "4.20.11"  # from default profile
        assert spec.region == "us-west-2"
        assert spec.channel == "stable"

    def test_inheritance_child_overrides_top_level(self, registry):
        """Child's explicit top-level fields override parent."""
        data = {
            "apiVersion": "capa-automation/v1",
            "kind": "ClusterAutomationSpec",
            "metadata": {"name": "override-region", "inherits": "default"},
            "spec": {
                "action": "create",
                "region": "eu-west-1",
                "features": {},
            },
        }
        spec = capa_cli.ClusterAutomationSpec(data, base_dir=PROJECT_ROOT)
        assert spec.region == "eu-west-1"

    def test_inheritance_missing_parent_raises(self):
        """Inheriting from nonexistent profile raises ValueError."""
        data = {
            "apiVersion": "capa-automation/v1",
            "kind": "ClusterAutomationSpec",
            "metadata": {"name": "bad-inherit", "inherits": "nonexistent-profile"},
            "spec": {"action": "create"},
        }
        with pytest.raises(ValueError, match="not found"):
            capa_cli.ClusterAutomationSpec(data, base_dir=PROJECT_ROOT)

    def test_inheritance_no_base_dir_skips(self):
        """Without base_dir, inheritance is silently skipped."""
        data = {
            "apiVersion": "capa-automation/v1",
            "kind": "ClusterAutomationSpec",
            "metadata": {"name": "no-basedir", "inherits": "default"},
            "spec": {"action": "create", "features": {}},
        }
        # Should not raise — inheritance is skipped when base_dir is None
        spec = capa_cli.ClusterAutomationSpec(data)
        assert spec.features == {}

    def test_real_inherited_profile(self, registry):
        """Test the real private-encrypted-custom profile that inherits from private-encrypted."""
        profile_path = PROJECT_ROOT / "specs" / "profiles" / "private-encrypted-custom.yml"
        if not profile_path.exists():
            pytest.skip("private-encrypted-custom.yml not found")
        with open(profile_path) as f:
            data = yaml.safe_load(f)
        spec = capa_cli.ClusterAutomationSpec(data, base_dir=PROJECT_ROOT)
        # From child
        assert spec.features["instance_type"] == "m5.4xlarge"
        assert spec.features["disk_size"] == 500
        # From parent (private-encrypted)
        assert spec.features["private_network"] is True
        assert spec.features["availability_zones"] == "3"

    def test_version_type_validation(self, registry):
        """Test that version type validates semver format."""
        feat = {"id": "test_version", "type": "version"}
        errors = []
        warnings = []
        capa_cli._validate_feature_value_check(feat, "4.20.11", errors, warnings)
        assert errors == []

        errors = []
        capa_cli._validate_feature_value_check(feat, "not-a-version", errors, warnings)
        assert len(errors) == 1
        assert "semver" in errors[0]

        errors = []
        capa_cli._validate_feature_value_check(feat, "4.20", errors, warnings)
        assert len(errors) == 1  # Missing patch version

    def test_multi_level_inheritance(self):
        """Multi-level: grandchild inherits parent inherits grandparent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            specs_dir = Path(tmpdir) / "specs" / "profiles"
            specs_dir.mkdir(parents=True)

            # Grandparent: base features
            grandparent = {
                "apiVersion": "capa-automation/v1",
                "kind": "ClusterAutomationSpec",
                "metadata": {"name": "grandparent"},
                "spec": {
                    "action": "create",
                    "region": "us-east-1",
                    "features": {"private_network": True, "sts": True},
                },
            }
            with open(specs_dir / "grandparent.yml", "w") as f:
                yaml.dump(grandparent, f)

            # Parent: inherits grandparent, adds/overrides
            parent = {
                "apiVersion": "capa-automation/v1",
                "kind": "ClusterAutomationSpec",
                "metadata": {"name": "parent", "inherits": "grandparent"},
                "spec": {
                    "action": "create",
                    "features": {"availability_zones": "3"},
                },
            }
            with open(specs_dir / "parent.yml", "w") as f:
                yaml.dump(parent, f)

            # Child: inherits parent
            child_data = {
                "apiVersion": "capa-automation/v1",
                "kind": "ClusterAutomationSpec",
                "metadata": {"name": "child", "inherits": "parent"},
                "spec": {
                    "action": "create",
                    "features": {"instance_type": "m5.4xlarge"},
                },
            }
            spec = ClusterAutomationSpec(child_data, base_dir=Path(tmpdir))

            # From grandparent
            assert spec.features["private_network"] is True
            assert spec.features["sts"] is True
            assert spec.region == "us-east-1"
            # From parent
            assert spec.features["availability_zones"] == "3"
            # From child
            assert spec.features["instance_type"] == "m5.4xlarge"

    def test_circular_inheritance_raises(self):
        """Circular inheritance (A -> B -> A) raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            specs_dir = Path(tmpdir) / "specs" / "profiles"
            specs_dir.mkdir(parents=True)

            a_data = {
                "apiVersion": "capa-automation/v1",
                "kind": "ClusterAutomationSpec",
                "metadata": {"name": "a", "inherits": "b"},
                "spec": {"action": "create", "features": {}},
            }
            b_data = {
                "apiVersion": "capa-automation/v1",
                "kind": "ClusterAutomationSpec",
                "metadata": {"name": "b", "inherits": "a"},
                "spec": {"action": "create", "features": {}},
            }
            with open(specs_dir / "a.yml", "w") as f:
                yaml.dump(a_data, f)
            with open(specs_dir / "b.yml", "w") as f:
                yaml.dump(b_data, f)

            with pytest.raises(ValueError, match="Circular inheritance"):
                ClusterAutomationSpec(a_data, base_dir=Path(tmpdir))


class TestRealSpecFiles:
    """Validate all spec files in the repo against the registry."""

    def test_all_feature_specs_valid(self, registry):
        specs_dir = PROJECT_ROOT / "specs" / "features"
        if not specs_dir.exists():
            pytest.skip("No feature specs directory")
        for spec_file in specs_dir.glob("*.yml"):
            with open(spec_file) as f:
                data = yaml.safe_load(f)
            assert data["apiVersion"] == "capa-automation/v1", f"{spec_file.name}: bad apiVersion"
            assert data["kind"] == "ClusterAutomationSpec", f"{spec_file.name}: bad kind"
            for act in data.get("spec", {}).get("actions", []):
                feat_id = act["feature"]
                assert registry.get_feature(feat_id) is not None, \
                    f"{spec_file.name}: unknown feature '{feat_id}'"

    def test_all_profile_specs_valid(self, registry):
        specs_dir = PROJECT_ROOT / "specs" / "profiles"
        if not specs_dir.exists():
            pytest.skip("No profiles directory")
        for spec_file in specs_dir.glob("*.yml"):
            with open(spec_file) as f:
                data = yaml.safe_load(f)
            assert data["apiVersion"] == "capa-automation/v1", f"{spec_file.name}: bad apiVersion"
            assert data["kind"] == "ClusterAutomationSpec", f"{spec_file.name}: bad kind"
            for feat_id in data.get("spec", {}).get("features", {}):
                assert registry.get_feature(feat_id) is not None, \
                    f"{spec_file.name}: unknown feature '{feat_id}'"

    def test_all_workflow_specs_valid(self, registry):
        specs_dir = PROJECT_ROOT / "specs" / "workflows"
        if not specs_dir.exists():
            pytest.skip("No workflows directory")
        for spec_file in specs_dir.glob("*.yml"):
            with open(spec_file) as f:
                data = yaml.safe_load(f)
            assert data["apiVersion"] == "capa-automation/v1", f"{spec_file.name}: bad apiVersion"
            assert data["kind"] in ("ClusterAutomationSpec", "Workflow"), f"{spec_file.name}: bad kind"


class TestCmdTest:
    """Tests for the 'capa test' command (passthrough to run-test-suite.py)."""

    def _make_args(self, **kwargs):
        """Build a namespace with defaults for cmd_test args."""
        defaults = {
            "suite_id": None,
            "all": False,
            "list": False,
            "tag": None,
            "format": None,
            "no_save": False,
            "extra_vars": None,
            "ai_agent": False,
            "ai_agent_dry_run": False,
            "test_verbosity": 0,
            "dry_run": False,
            "verbose": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("subprocess.run")
    def test_basic_suite_run(self, mock_run, tmp_path):
        """Test running a single suite by ID."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="20-rosa-hcp-provision")
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "run-test-suite.py" in cmd[1]
        assert "20-rosa-hcp-provision" in cmd

    @patch("subprocess.run")
    def test_list_flag(self, mock_run, tmp_path):
        """Test --list flag passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(list=True)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--list" in cmd

    @patch("subprocess.run")
    def test_all_flag(self, mock_run, tmp_path):
        """Test --all flag passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(all=True)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--all" in cmd

    @patch("subprocess.run")
    def test_ai_agent_flags(self, mock_run, tmp_path):
        """Test --ai-agent and --ai-agent-dry-run passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="30-delete", ai_agent=True, ai_agent_dry_run=True)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--ai-agent" in cmd
        assert "--ai-agent-dry-run" in cmd

    @patch("subprocess.run")
    def test_extra_vars_passthrough(self, mock_run, tmp_path):
        """Test -e extra vars are forwarded."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(
            suite_id="20-provision",
            extra_vars=["OCP_HUB_API_URL=https://api.hub:6443", "AWS_ACCESS_KEY_ID=AKIA123"]
        )
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "-e" in cmd
        assert "OCP_HUB_API_URL=https://api.hub:6443" in cmd
        assert "AWS_ACCESS_KEY_ID=AKIA123" in cmd

    @patch("subprocess.run")
    def test_verbosity_passthrough(self, mock_run, tmp_path):
        """Test -V/-VV/-VVV verbosity mapping."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="20-provision", test_verbosity=3)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "-vvv" in cmd

    @patch("subprocess.run")
    def test_format_passthrough(self, mock_run, tmp_path):
        """Test --format flag passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="20-provision", format="junit")
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--format" in cmd
        assert "junit" in cmd

    @patch("subprocess.run")
    def test_tag_passthrough(self, mock_run, tmp_path):
        """Test --tag flag passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(all=True, tag="rosa-hcp")
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--tag" in cmd
        assert "rosa-hcp" in cmd

    @patch("subprocess.run")
    def test_dry_run_passthrough(self, mock_run, tmp_path):
        """Test --dry-run flag passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="20-provision", dry_run=True)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--dry-run" in cmd

    @patch("subprocess.run")
    def test_no_save_passthrough(self, mock_run, tmp_path):
        """Test --no-save flag passthrough."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="20-provision", no_save=True)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--no-save" in cmd

    def test_missing_runner_exits(self, tmp_path):
        """Test error when run-test-suite.py doesn't exist."""
        args = self._make_args(suite_id="20-provision")
        with pytest.raises(SystemExit):
            capa_cli.cmd_test(args, tmp_path, None)

    @patch("subprocess.run")
    def test_full_jenkins_style_invocation(self, mock_run, tmp_path):
        """Test a full Jenkins-style invocation with all flags."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(
            suite_id="20-rosa-hcp-provision",
            format="junit",
            test_verbosity=3,
            ai_agent=True,
            extra_vars=[
                "OCP_HUB_API_URL=https://api.hub:6443",
                "OCP_HUB_ADMIN_USER=kubeadmin",
                "OCP_HUB_ADMIN_PASS=secret",
                "AWS_ACCESS_KEY_ID=AKIA123",
                "AWS_SECRET_ACCESS_KEY=secret456",
            ]
        )
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "20-rosa-hcp-provision" in cmd
        assert "--format" in cmd
        assert "junit" in cmd
        assert "-vvv" in cmd
        assert "--ai-agent" in cmd
        e_indices = [i for i, x in enumerate(cmd) if x == "-e"]
        assert len(e_indices) == 5

    @patch("subprocess.run")
    def test_exit_code_passthrough(self, mock_run, tmp_path):
        """Test that non-zero exit code from runner is propagated."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=1)

        args = self._make_args(suite_id="20-provision")
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 1

    @patch("subprocess.run")
    def test_verbosity_capped_at_4(self, mock_run, tmp_path):
        """Test that verbosity is capped at -vvvv even if -VVVVV given."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = self._make_args(suite_id="20-provision", test_verbosity=6)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "-vvvv" in cmd
        assert "-vvvvvv" not in cmd


class TestCmdVersion:
    """Tests for the 'capa version' command."""

    def test_version_output(self, registry, capsys):
        """Test version prints CLI info."""
        args = argparse.Namespace(verbose=False)
        capa_cli.cmd_version(args, PROJECT_ROOT, registry)
        output = capsys.readouterr().out
        assert "CAPA CLI" in output
        assert "CLI version:" in output
        assert "Features:" in output
        assert "Python:" in output

    def test_version_shows_agent_version(self, registry, capsys):
        """Test version shows agent framework version."""
        args = argparse.Namespace(verbose=False)
        capa_cli.cmd_version(args, PROJECT_ROOT, registry)
        output = capsys.readouterr().out
        assert "Agent framework:" in output


class TestCmdHistory:
    """Tests for the 'capa history' command."""

    def test_history_no_file(self, tmp_path, capsys):
        """Test history when no history file exists."""
        args = argparse.Namespace(cluster=None, limit=20)
        capa_cli.cmd_history(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "No history file" in output

    def test_history_with_entries(self, tmp_path, capsys):
        """Test history shows entries from file."""
        (tmp_path / "vars").mkdir()
        history = [
            {"cluster_name": "test-cluster", "feature_id": "channel_group",
             "status": "completed", "target_value": "fast",
             "timestamp": "2026-04-14T10:00:00"},
            {"cluster_name": "test-cluster", "feature_id": "control_plane_upgrade",
             "status": "running", "target_value": "4.20.12",
             "timestamp": "2026-04-14T10:01:00"},
        ]
        with open(tmp_path / "vars" / "cluster_action_history.json", "w") as f:
            json.dump(history, f)

        args = argparse.Namespace(cluster=None, limit=20)
        capa_cli.cmd_history(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "channel_group" in output
        assert "control_plane_upgrade" in output
        assert "completed" in output

    def test_history_filter_by_cluster(self, tmp_path, capsys):
        """Test history filters by cluster name."""
        (tmp_path / "vars").mkdir()
        history = [
            {"cluster_name": "cluster-a", "feature_id": "feat-a",
             "status": "completed", "target_value": "x",
             "timestamp": "2026-04-14T10:00:00"},
            {"cluster_name": "cluster-b", "feature_id": "feat-b",
             "status": "running", "target_value": "y",
             "timestamp": "2026-04-14T10:01:00"},
        ]
        with open(tmp_path / "vars" / "cluster_action_history.json", "w") as f:
            json.dump(history, f)

        args = argparse.Namespace(cluster="cluster-a", limit=20)
        capa_cli.cmd_history(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "feat-a" in output
        assert "feat-b" not in output

    def test_history_no_entries_for_cluster(self, tmp_path, capsys):
        """Test history when cluster has no entries."""
        (tmp_path / "vars").mkdir()
        with open(tmp_path / "vars" / "cluster_action_history.json", "w") as f:
            json.dump([], f)

        args = argparse.Namespace(cluster="nonexistent", limit=20)
        capa_cli.cmd_history(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "No history for cluster" in output

    def test_history_limit(self, tmp_path, capsys):
        """Test history respects --limit."""
        (tmp_path / "vars").mkdir()
        history = [
            {"cluster_name": "c", "feature_id": f"feat-{i}",
             "status": "completed", "target_value": str(i),
             "timestamp": f"2026-04-14T10:{i:02d}:00"}
            for i in range(10)
        ]
        with open(tmp_path / "vars" / "cluster_action_history.json", "w") as f:
            json.dump(history, f)

        args = argparse.Namespace(cluster=None, limit=3)
        capa_cli.cmd_history(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "Showing 3 of 10" in output


class TestCmdLogs:
    """Tests for the 'capa logs' command."""

    def test_logs_no_logs_found(self, tmp_path, capsys):
        """Test logs when no log files exist."""
        args = argparse.Namespace(cluster="nonexistent", lines=50, follow=False)
        capa_cli.cmd_logs(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "No logs found" in output

    def test_logs_from_history(self, tmp_path, capsys):
        """Test logs falls back to history file."""
        (tmp_path / "vars").mkdir()
        history = [
            {"cluster_name": "my-cluster", "feature_id": "channel_group",
             "status": "completed", "message": "Done",
             "timestamp": "2026-04-14T10:00:00"},
        ]
        with open(tmp_path / "vars" / "cluster_action_history.json", "w") as f:
            json.dump(history, f)

        args = argparse.Namespace(cluster="my-cluster", lines=50, follow=False)
        capa_cli.cmd_logs(args, tmp_path, None)
        output = capsys.readouterr().out
        assert "Recent operations" in output
        assert "channel_group" in output


class TestCmdListClusters:
    """Tests for the 'capa list-clusters' command."""

    @patch("subprocess.run")
    def test_list_clusters_no_crd(self, mock_run, capsys):
        """Test list-clusters when CRD not installed."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="the server doesn't have a resource type \"rosacontrolplane\""
        )
        args = argparse.Namespace(namespace=None)
        with pytest.raises(SystemExit):
            capa_cli.cmd_list_clusters(args, Path("."), None)
        output = capsys.readouterr().out
        assert "CAPA may not be installed" in output

    @patch("subprocess.run")
    def test_list_clusters_empty(self, mock_run, capsys):
        """Test list-clusters when no clusters exist."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        args = argparse.Namespace(namespace=None)
        capa_cli.cmd_list_clusters(args, Path("."), None)
        output = capsys.readouterr().out
        assert "No clusters found" in output

    @patch("subprocess.run")
    def test_list_clusters_with_results(self, mock_run, capsys):
        """Test list-clusters displays cluster table."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="moo-rosa-hcp|ns-rosa-hcp|4.20.11|true|4.20.11\n"
        )
        args = argparse.Namespace(namespace=None)
        capa_cli.cmd_list_clusters(args, Path("."), None)
        output = capsys.readouterr().out
        assert "moo-rosa-hcp" in output
        assert "4.20.11" in output
        assert "CLUSTER" in output

    @patch("subprocess.run")
    def test_list_clusters_upgrading(self, mock_run, capsys):
        """Test list-clusters shows upgrade status."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="moo-rosa-hcp|ns-rosa-hcp|4.20.10|false|4.20.11\n"
        )
        args = argparse.Namespace(namespace=None)
        capa_cli.cmd_list_clusters(args, Path("."), None)
        output = capsys.readouterr().out
        assert "4.20.10" in output
        assert "4.20.11" in output


class TestCmdWatch:
    """Tests for the 'capa watch' command."""

    @patch("subprocess.run")
    def test_watch_cluster_ready_immediately(self, mock_run, capsys):
        """Test watch exits when cluster is already ready."""
        # First call: control plane check
        # Second call: machine pool check
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="4.20.11|true|4.20.11"),
            MagicMock(returncode=0, stdout="true"),
        ]
        args = argparse.Namespace(cluster="moo", namespace="ns-rosa-hcp",
                                  interval=1, timeout=10)
        capa_cli.cmd_watch(args, Path("."), None)
        output = capsys.readouterr().out
        assert "is ready!" in output

    @patch("subprocess.run")
    def test_watch_timeout(self, mock_run, capsys):
        """Test watch exits on timeout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="4.20.10|false|4.20.11")
        args = argparse.Namespace(cluster="moo", namespace="ns-rosa-hcp",
                                  interval=1, timeout=1)
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_watch(args, Path("."), None)
        assert exc_info.value.code == 1
        output = capsys.readouterr().out
        assert "Timeout" in output


class TestCmdCompletion:
    """Tests for the 'capa completion' command."""

    def test_bash_completion(self, registry, capsys):
        """Test bash completion script generation."""
        args = argparse.Namespace(shell="bash")
        capa_cli.cmd_completion(args, PROJECT_ROOT, registry)
        output = capsys.readouterr().out
        assert "_capa_complete" in output
        assert "compgen" in output
        assert "channel_group" in output

    def test_zsh_completion(self, registry, capsys):
        """Test zsh completion script generation."""
        args = argparse.Namespace(shell="zsh")
        capa_cli.cmd_completion(args, PROJECT_ROOT, registry)
        output = capsys.readouterr().out
        assert "#compdef capa" in output
        assert "_capa" in output

    def test_unknown_shell(self, registry):
        """Test unknown shell type exits."""
        args = argparse.Namespace(shell="fish")
        with pytest.raises(SystemExit):
            capa_cli.cmd_completion(args, PROJECT_ROOT, registry)


class TestCmdTestDryRun:
    """Test --dry-run works in both positions for capa test."""

    @patch("subprocess.run")
    def test_dry_run_via_test_subparser(self, mock_run, tmp_path):
        """Test --dry-run on test subparser (test_dry_run dest)."""
        (tmp_path / "run-test-suite.py").write_text("# fake")
        mock_run.return_value = MagicMock(returncode=0)

        args = argparse.Namespace(
            suite_id="20-provision", all=False, list=False, tag=None,
            format=None, no_save=False, extra_vars=None, ai_agent=False,
            ai_agent_dry_run=False, test_verbosity=0, dry_run=False,
            test_dry_run=True, verbose=False
        )
        with pytest.raises(SystemExit) as exc_info:
            capa_cli.cmd_test(args, tmp_path, None)
        assert exc_info.value.code == 0

        cmd = mock_run.call_args[0][0]
        assert "--dry-run" in cmd


class TestCmdSetDryRun:
    """Test --dry-run works in both positions for capa set."""

    @patch.object(ExecutionEngine, "execute")
    @patch.object(ExecutionEngine, "plan")
    def test_dry_run_via_parent_parser(self, mock_plan, mock_execute, minimal_registry):
        """./capa --dry-run set channel_group fast -c moo — parent dry_run propagates."""
        mock_plan.return_value = [{"step": 1, "name": "test", "status": "dry_run"}]
        mock_execute.return_value = [{"step": 1, "name": "test", "status": "dry_run"}]

        args = argparse.Namespace(
            feature="channel_group", value="fast", cluster="moo-rosa-hcp",
            namespace="ns-rosa-hcp", dry_run=True, set_dry_run=False, verbose=False
        )
        capa_cli.cmd_set(args, minimal_registry._registry_path.parent.parent, minimal_registry)

        # ExecutionEngine should have been constructed with dry_run=True
        mock_execute.assert_called_once()

    @patch.object(ExecutionEngine, "execute")
    @patch.object(ExecutionEngine, "plan")
    def test_dry_run_via_set_subparser(self, mock_plan, mock_execute, minimal_registry):
        """./capa set --dry-run channel_group fast -c moo — subparser dry_run works."""
        mock_plan.return_value = [{"step": 1, "name": "test", "status": "dry_run"}]
        mock_execute.return_value = [{"step": 1, "name": "test", "status": "dry_run"}]

        args = argparse.Namespace(
            feature="channel_group", value="fast", cluster="moo-rosa-hcp",
            namespace="ns-rosa-hcp", dry_run=False, set_dry_run=True, verbose=False
        )
        capa_cli.cmd_set(args, minimal_registry._registry_path.parent.parent, minimal_registry)

        mock_execute.assert_called_once()


class TestCmdWorkflow:
    """Tests for the 'capa workflow' command."""

    @pytest.fixture
    def workflow_env(self, minimal_registry):
        """Set up a temp dir with saved workflows and YAML workflows."""
        base_dir = minimal_registry._registry_path.parent.parent

        # Create vars/saved_workflows.json
        vars_dir = base_dir / "vars"
        vars_dir.mkdir(exist_ok=True)
        saved = [
            {
                "id": "wf-test123",
                "name": "test_workflow",
                "description": "A test workflow",
                "stop_on_failure": True,
                "vars": {"MCE_NAMESPACE": "multicluster-engine"},
                "steps": [
                    {"name": "Step One", "playbook": "playbooks/validate.yml", "on_failure": "stop", "timeout": 120, "vars": {}},
                    {"name": "Step Two", "playbook": "playbooks/configure.yml", "on_failure": "skip", "timeout": 600, "vars": {"key": "val"}},
                ],
                "savedAt": "2026-04-13T10:00:00",
            }
        ]
        with open(vars_dir / "saved_workflows.json", "w") as f:
            json.dump(saved, f)

        # Create YAML workflow
        wf_dir = base_dir / "specs" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        yaml_wf = {
            "apiVersion": "capa-automation/v1",
            "kind": "Workflow",
            "metadata": {"name": "yaml-test", "description": "A YAML workflow"},
            "spec": {
                "vars": {},
                "steps": [
                    {"name": "YAML Step 1", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60},
                ],
            },
        }
        with open(wf_dir / "yaml-test.yml", "w") as f:
            yaml.dump(yaml_wf, f)

        return base_dir

    def test_list_shows_saved_and_yaml(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(workflow_action="list", dry_run=False, verbose=False)
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "test_workflow" in out
        assert "yaml-test" in out
        assert "Step One" in out
        assert "YAML Step 1" in out

    def test_show_saved_workflow(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(workflow_action="show", name="test_workflow", dry_run=False, verbose=False)
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "test_workflow" in out
        assert "wf-test123" in out
        assert "Step One" in out
        assert "playbooks/validate.yml" in out

    def test_show_yaml_workflow(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(workflow_action="show", name="yaml-test", dry_run=False, verbose=False)
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "yaml-test" in out
        assert "YAML Step 1" in out

    def test_show_not_found(self, workflow_env, minimal_registry):
        args = argparse.Namespace(workflow_action="show", name="nonexistent", dry_run=False, verbose=False)
        with pytest.raises(SystemExit):
            capa_cli.cmd_workflow(args, workflow_env, minimal_registry)

    def test_run_dry_run(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(
            workflow_action="run", name="test_workflow",
            dry_run=True, verbose=False, extra_vars=None,
        )
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "test_workflow" in out
        assert "2 steps" in out
        assert "DRY RUN" in out

    def test_run_yaml_dry_run(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(
            workflow_action="run", name="yaml-test",
            dry_run=True, verbose=False, extra_vars=None,
        )
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "yaml-test" in out
        assert "DRY RUN" in out

    def test_run_with_extra_vars(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(
            workflow_action="run", name="test_workflow",
            dry_run=True, verbose=False, extra_vars=["key=override"],
        )
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "DRY RUN" in out

    def test_export_saved_to_yaml(self, workflow_env, minimal_registry, capsys, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        args = argparse.Namespace(
            workflow_action="export", name="test_workflow",
            dry_run=False, verbose=False, output=None,
        )
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "kind: Workflow" in out
        assert "playbooks/validate.yml" in out

    def test_evaluate_condition_none(self):
        assert _evaluate_condition(None, []) is True
        assert _evaluate_condition("", []) is True

    def test_evaluate_condition_always(self):
        assert _evaluate_condition("always", []) is True
        assert _evaluate_condition("always", [{"status": "failed"}]) is True

    def test_evaluate_condition_failure(self):
        assert _evaluate_condition("failure", []) is False
        assert _evaluate_condition("failure", [{"status": "completed"}]) is False
        assert _evaluate_condition("failure", [{"status": "failed"}]) is True
        assert _evaluate_condition("failure", [{"status": "completed"}, {"status": "failed"}]) is True

    def test_evaluate_condition_success(self):
        assert _evaluate_condition("success", []) is True  # vacuously true
        assert _evaluate_condition("success", [{"status": "completed"}]) is True
        assert _evaluate_condition("success", [{"status": "completed"}, {"status": "completed"}]) is True
        assert _evaluate_condition("success", [{"status": "completed"}, {"status": "failed"}]) is False

    def test_evaluate_condition_step_reference(self):
        results = [
            {"step": 0, "status": "completed"},
            {"step": 1, "status": "failed"},
        ]
        assert _evaluate_condition("steps.0.status == 'completed'", results) is True
        assert _evaluate_condition("steps.0.status == 'failed'", results) is False
        assert _evaluate_condition("steps.1.status == 'failed'", results) is True
        assert _evaluate_condition("steps.1.status != 'completed'", results) is True
        assert _evaluate_condition("steps.1.status != 'failed'", results) is False
        # Reference to step that hasn't run
        assert _evaluate_condition("steps.5.status == 'completed'", results) is False

    def test_evaluate_condition_unknown(self, capsys):
        assert _evaluate_condition("some_unknown_condition", []) is False
        out = capsys.readouterr().out
        assert "Unknown condition" in out

    def test_run_dry_run_shows_conditions(self, workflow_env, minimal_registry, capsys):
        """Dry-run output should show if: conditions on steps."""
        # Add a YAML workflow with conditions
        wf_dir = workflow_env / "specs" / "workflows"
        yaml_wf = {
            "apiVersion": "capa-automation/v1",
            "kind": "Workflow",
            "metadata": {"name": "cond-test", "description": "Conditional test"},
            "spec": {
                "vars": {},
                "steps": [
                    {"name": "Step A", "playbook": "playbooks/test.yml", "on_failure": "skip", "timeout": 60},
                    {"name": "Step B", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60, "if": "steps.0.status == 'completed'"},
                    {"name": "Cleanup", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60, "if": "failure"},
                    {"name": "Report", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60, "if": "always"},
                ],
            },
        }
        with open(wf_dir / "cond-test.yml", "w") as f:
            yaml.dump(yaml_wf, f)

        args = argparse.Namespace(
            workflow_action="run", name="cond-test",
            dry_run=True, verbose=False, extra_vars=None,
        )
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "if: steps.0.status == 'completed'" in out
        assert "if: failure" in out
        assert "if: always" in out

    def test_show_yaml_displays_conditions(self, workflow_env, minimal_registry, capsys):
        """Show command should display if: conditions."""
        wf_dir = workflow_env / "specs" / "workflows"
        yaml_wf = {
            "apiVersion": "capa-automation/v1",
            "kind": "Workflow",
            "metadata": {"name": "cond-show", "description": "Conditional show test"},
            "spec": {
                "vars": {},
                "steps": [
                    {"name": "Step A", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60},
                    {"name": "Cleanup", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60, "if": "always"},
                ],
            },
        }
        with open(wf_dir / "cond-show.yml", "w") as f:
            yaml.dump(yaml_wf, f)

        args = argparse.Namespace(workflow_action="show", name="cond-show", dry_run=False, verbose=False)
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "if: always" in out

    def test_export_yaml_already(self, workflow_env, minimal_registry, capsys):
        args = argparse.Namespace(
            workflow_action="export", name="yaml-test",
            dry_run=False, verbose=False, output=None,
        )
        capa_cli.cmd_workflow(args, workflow_env, minimal_registry)
        out = capsys.readouterr().out
        assert "Already a YAML workflow" in out


class TestCmdTrigger:
    """Tests for the 'capa trigger' command."""

    @pytest.fixture
    def trigger_env(self, minimal_registry):
        """Set up a temp dir with a workflow for trigger tests."""
        base_dir = minimal_registry._registry_path.parent.parent

        # Create a YAML workflow
        wf_dir = base_dir / "specs" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        yaml_wf = {
            "apiVersion": "capa-automation/v1",
            "kind": "Workflow",
            "metadata": {"name": "test-wf", "description": "Test workflow"},
            "spec": {
                "triggers": [
                    {"type": "schedule", "name": "nightly", "cron": "0 2 * * *"},
                    {"type": "webhook", "name": "ci-hook"},
                ],
                "vars": {},
                "steps": [
                    {"name": "Step 1", "playbook": "playbooks/test.yml", "on_failure": "stop", "timeout": 60},
                ],
            },
        }
        with open(wf_dir / "test-wf.yml", "w") as f:
            yaml.dump(yaml_wf, f)

        # Ensure vars dir exists
        (base_dir / "vars").mkdir(exist_ok=True)

        return base_dir

    def test_list_empty(self, trigger_env, minimal_registry, capsys):
        args = argparse.Namespace(trigger_action="list", dry_run=False, verbose=False)
        capa_cli.cmd_trigger(args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        # Should show declared YAML triggers
        assert "test-wf" in out
        assert "nightly" in out or "schedule" in out

    def test_create_schedule(self, trigger_env, minimal_registry, capsys):
        args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 3 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        assert "Created schedule trigger" in out
        assert "test-wf" in out
        assert "Daily at 3:00" in out

        # Verify state persisted
        state = capa_cli._load_trigger_state(trigger_env)
        assert len(state["triggers"]) == 1
        assert state["triggers"][0]["type"] == "schedule"
        assert state["triggers"][0]["cron"] == "0 3 * * *"
        assert state["triggers"][0]["enabled"] is True

    def test_create_webhook(self, trigger_env, minimal_registry, capsys):
        args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="webhook", cron=None, timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        assert "Created webhook trigger" in out
        assert "/api/webhooks/trigger/" in out

    def test_create_missing_workflow(self, trigger_env, minimal_registry):
        args = argparse.Namespace(
            trigger_action="create", target="nonexistent",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        with pytest.raises(SystemExit):
            capa_cli.cmd_trigger(args, trigger_env, minimal_registry)

    def test_create_schedule_missing_cron(self, trigger_env, minimal_registry):
        args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron=None, timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        with pytest.raises(SystemExit):
            capa_cli.cmd_trigger(args, trigger_env, minimal_registry)

    def test_list_shows_created_triggers(self, trigger_env, minimal_registry, capsys):
        # Create a trigger first
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="30 4 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()  # clear

        # List
        list_args = argparse.Namespace(trigger_action="list", dry_run=False, verbose=False)
        capa_cli.cmd_trigger(list_args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        assert "Active Triggers" in out
        assert "test-wf" in out
        assert "trg-" in out

    def test_show_trigger(self, trigger_env, minimal_registry, capsys):
        # Create
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()

        state = capa_cli._load_trigger_state(trigger_env)
        trigger_id = state["triggers"][0]["trigger_id"]

        # Show
        show_args = argparse.Namespace(
            trigger_action="show", target=trigger_id,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(show_args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        assert trigger_id in out
        assert "test-wf" in out
        assert "schedule" in out

    def test_enable_disable(self, trigger_env, minimal_registry, capsys):
        # Create
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()

        state = capa_cli._load_trigger_state(trigger_env)
        trigger_id = state["triggers"][0]["trigger_id"]

        # Disable
        disable_args = argparse.Namespace(
            trigger_action="disable", target=trigger_id,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(disable_args, trigger_env, minimal_registry)
        state = capa_cli._load_trigger_state(trigger_env)
        assert state["triggers"][0]["enabled"] is False

        # Enable
        enable_args = argparse.Namespace(
            trigger_action="enable", target=trigger_id,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(enable_args, trigger_env, minimal_registry)
        state = capa_cli._load_trigger_state(trigger_env)
        assert state["triggers"][0]["enabled"] is True

    def test_delete_trigger(self, trigger_env, minimal_registry, capsys):
        # Create
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()

        state = capa_cli._load_trigger_state(trigger_env)
        trigger_id = state["triggers"][0]["trigger_id"]

        # Delete
        delete_args = argparse.Namespace(
            trigger_action="delete", target=trigger_id,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(delete_args, trigger_env, minimal_registry)
        state = capa_cli._load_trigger_state(trigger_env)
        assert len(state["triggers"]) == 0

    def test_history_empty(self, trigger_env, minimal_registry, capsys):
        args = argparse.Namespace(
            trigger_action="history", target=None,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        assert "No trigger run history" in out

    def test_cron_to_human(self):
        assert capa_cli._cron_to_human("0 2 * * *") == "Daily at 2:00"
        assert capa_cli._cron_to_human("30 14 * * *") == "Daily at 14:30"
        assert capa_cli._cron_to_human("0 9 * * 1") == "Every Mon at 9:00"
        assert capa_cli._cron_to_human("15 * * * *") == "Every hour at :15"

    def test_show_not_found(self, trigger_env, minimal_registry):
        args = argparse.Namespace(
            trigger_action="show", target="trg-nonexistent",
            dry_run=False, verbose=False, limit=20,
        )
        with pytest.raises(SystemExit):
            capa_cli.cmd_trigger(args, trigger_env, minimal_registry)

    def test_list_declared_yaml_triggers(self, trigger_env, minimal_registry, capsys):
        """YAML workflows with spec.triggers should show as declared triggers."""
        args = argparse.Namespace(trigger_action="list", dry_run=False, verbose=False)
        capa_cli.cmd_trigger(args, trigger_env, minimal_registry)
        out = capsys.readouterr().out
        assert "Declared Triggers" in out
        assert "schedule" in out
        assert "webhook" in out

    def test_fire_missing_target(self, trigger_env, minimal_registry):
        """Fire without target should exit with error."""
        args = argparse.Namespace(
            trigger_action="fire", target=None,
            dry_run=False, verbose=False, force=False, limit=20,
        )
        with pytest.raises(SystemExit):
            capa_cli.cmd_trigger(args, trigger_env, minimal_registry)

    def test_fire_nonexistent_trigger(self, trigger_env, minimal_registry):
        """Fire with unknown trigger_id should exit with error."""
        args = argparse.Namespace(
            trigger_action="fire", target="trg-nonexistent",
            dry_run=False, verbose=False, force=False, limit=20,
        )
        with pytest.raises(SystemExit):
            capa_cli.cmd_trigger(args, trigger_env, minimal_registry)

    def test_fire_disabled_trigger_without_force(self, trigger_env, minimal_registry, capsys):
        """Fire on a disabled trigger should exit unless --force."""
        # Create a trigger
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()

        state = capa_cli._load_trigger_state(trigger_env)
        trigger_id = state["triggers"][0]["trigger_id"]

        # Disable it
        disable_args = argparse.Namespace(
            trigger_action="disable", target=trigger_id,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(disable_args, trigger_env, minimal_registry)
        capsys.readouterr()

        # Try to fire without --force
        fire_args = argparse.Namespace(
            trigger_action="fire", target=trigger_id,
            dry_run=False, verbose=False, force=False, limit=20,
        )
        with pytest.raises(SystemExit):
            capa_cli.cmd_trigger(fire_args, trigger_env, minimal_registry)

    def test_fire_success(self, trigger_env, minimal_registry, capsys):
        """Fire should execute workflow and record run history."""
        # Create a trigger
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()

        state = capa_cli._load_trigger_state(trigger_env)
        trigger_id = state["triggers"][0]["trigger_id"]

        # Mock _run_workflow_by_name to avoid actual playbook execution
        mock_results = [{"step": 1, "name": "Step 1", "status": "completed"}]
        with patch.object(capa_cli, "_run_workflow_by_name", return_value=(True, mock_results, 5.0)):
            fire_args = argparse.Namespace(
                trigger_action="fire", target=trigger_id,
                dry_run=False, verbose=False, force=False, limit=20,
            )
            capa_cli.cmd_trigger(fire_args, trigger_env, minimal_registry)

        out = capsys.readouterr().out
        assert "Firing trigger" in out

        # Check state was updated
        state = capa_cli._load_trigger_state(trigger_env)
        t = state["triggers"][0]
        assert t["run_count"] == 1
        assert t["last_run_status"] == "completed"
        assert t["consecutive_failures"] == 0
        assert len(state["run_history"]) == 1
        assert state["run_history"][0]["status"] == "completed"

    def test_fire_failure_increments_consecutive(self, trigger_env, minimal_registry, capsys):
        """Failed fire should increment consecutive_failures."""
        create_args = argparse.Namespace(
            trigger_action="create", target="test-wf",
            type="schedule", cron="0 2 * * *", timezone="UTC",
            secret_env=None, trigger_name=None, force=False,
            dry_run=False, verbose=False, limit=20,
        )
        capa_cli.cmd_trigger(create_args, trigger_env, minimal_registry)
        capsys.readouterr()

        state = capa_cli._load_trigger_state(trigger_env)
        trigger_id = state["triggers"][0]["trigger_id"]

        mock_results = [{"step": 1, "name": "Step 1", "status": "failed"}]
        with patch.object(capa_cli, "_run_workflow_by_name", return_value=(False, mock_results, 3.0)):
            fire_args = argparse.Namespace(
                trigger_action="fire", target=trigger_id,
                dry_run=False, verbose=False, force=False, limit=20,
            )
            capa_cli.cmd_trigger(fire_args, trigger_env, minimal_registry)

        state = capa_cli._load_trigger_state(trigger_env)
        t = state["triggers"][0]
        assert t["consecutive_failures"] == 1
        assert t["last_run_status"] == "failed"


# ============================================================================
# capa_core coverage: FeatureRegistry error paths and edge cases
# ============================================================================

class TestFeatureRegistryErrors:
    """Tests for FeatureRegistry error paths in capa_core."""

    def _write_registry(self, tmp_path, content):
        """Write content to the expected registry path under tmp_path."""
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir(exist_ok=True)
        reg_file = schema_dir / "feature-registry.yml"
        reg_file.write_text(content)
        return reg_file

    def test_registry_file_not_found(self, tmp_path):
        """FileNotFoundError when registry YAML doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Feature registry not found"):
            CoreFeatureRegistry(tmp_path)

    def test_registry_invalid_yaml(self, tmp_path):
        """ValueError when registry YAML is malformed."""
        self._write_registry(tmp_path, "{{invalid: yaml: [")
        with pytest.raises(ValueError, match="Invalid YAML"):
            CoreFeatureRegistry(tmp_path)

    def test_registry_getmtime_oserror(self, tmp_path):
        """OSError on getmtime should set mtime to 0 and still load."""
        self._write_registry(tmp_path, yaml.dump({"version": "1.0", "suites": []}))
        with patch("capa_core.os.path.getmtime", side_effect=OSError("permission denied")):
            reg = CoreFeatureRegistry(tmp_path)
        assert reg.suites == []

    def test_refresh_reloads(self, tmp_path):
        """refresh() should re-check the file."""
        reg_file = self._write_registry(tmp_path, yaml.dump({"version": "1.0", "suites": []}))
        reg = CoreFeatureRegistry(tmp_path)
        assert reg.suites == []
        # Update file with a suite — change mtime by writing new content
        import time
        time.sleep(0.05)  # ensure mtime changes
        reg_file.write_text(yaml.dump({
            "version": "1.0",
            "suites": [{"id": "new-suite", "name": "New", "phase": "Day2", "features": []}],
        }))
        reg.refresh()
        assert len(reg.suites) == 1
        assert reg.suites[0]["id"] == "new-suite"

    def test_raw_data_property(self, tmp_path):
        """raw_data should return the full parsed YAML dict."""
        self._write_registry(tmp_path, yaml.dump({"version": "1.0", "suites": []}))
        reg = CoreFeatureRegistry(tmp_path)
        raw = reg.raw_data
        assert raw["version"] == "1.0"
        assert raw["suites"] == []


# ============================================================================
# capa_core coverage: validate_cluster_name
# ============================================================================

class TestValidateClusterName:
    """Tests for validate_cluster_name in capa_core."""

    def test_empty_name(self):
        assert validate_cluster_name("") == "Cluster name is required"

    def test_too_long(self):
        result = validate_cluster_name("a" * 55)
        assert "54 characters or fewer" in result
        assert "got 55" in result

    def test_starts_with_number(self):
        result = validate_cluster_name("1bad")
        assert "start with a lowercase letter" in result

    def test_starts_with_uppercase(self):
        result = validate_cluster_name("Bad")
        assert "start with a lowercase letter" in result

    def test_has_underscores(self):
        result = validate_cluster_name("bad_name")
        assert result is not None

    def test_valid_name(self):
        assert validate_cluster_name("my-cluster-01") is None

    def test_valid_single_char(self):
        assert validate_cluster_name("a") is None

    def test_valid_max_length(self):
        assert validate_cluster_name("a" * 54) is None


# ============================================================================
# capa_core coverage: _plan_test via resolve_spec_to_plan
# ============================================================================

class TestPlanTest:
    """Tests for the test action plan resolution in capa_core."""

    def test_plan_test_with_explicit_suites(self, minimal_registry, tmp_path):
        """test action with explicit test_suites in spec."""
        data = make_spec(action="test", cluster="my-cluster",
                         test_suites=["test-suite"])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert len(plan) >= 1
        assert plan[0]["type"] == "test_suite"
        assert plan[0]["suite_id"] == "test-suite"
        assert plan[0]["cluster"] == "my-cluster"

    def test_plan_test_defaults_to_day2_suites(self, minimal_registry, tmp_path):
        """test action without test_suites should default to Day2 suites."""
        data = make_spec(action="test", cluster="my-cluster")
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        # minimal_registry has one suite with phase="Day2"
        assert len(plan) >= 1
        assert all(s["type"] == "test_suite" for s in plan)

    def test_plan_test_step_numbering(self, minimal_registry, tmp_path):
        """Steps should be numbered sequentially."""
        data = make_spec(action="test", cluster="my-cluster",
                         test_suites=["test-suite"])
        spec = ClusterAutomationSpec(data)
        engine = ExecutionEngine(minimal_registry, tmp_path, dry_run=True)
        plan = engine.plan(spec)

        assert plan[0]["step"] == 1
        assert plan[0]["name"] == "Test suite: test-suite"


# ============================================================================
