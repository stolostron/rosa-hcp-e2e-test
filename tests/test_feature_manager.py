"""Tests for the FeatureManager class."""

import json
import re
import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, Undefined
from pathlib import Path
from feature_manager import FeatureManager, ScenarioError


@pytest.fixture
def fm():
    base_dir = Path(__file__).parent.parent
    return FeatureManager(base_dir)


class TestAliasResolution:
    def test_known_alias(self, fm):
        assert fm.resolve_alias("private") == "private_network"

    def test_no_cni_alias(self, fm):
        assert fm.resolve_alias("no-cni") == "no_cni"

    def test_external_oidc_alias(self, fm):
        assert fm.resolve_alias("external-oidc") == "external_oidc"

    def test_unknown_passes_through(self, fm):
        assert fm.resolve_alias("private_network") == "private_network"

    def test_disk_size_alias(self, fm):
        assert fm.resolve_alias("disk-size") == "disk_size"

    def test_domain_alias(self, fm):
        assert fm.resolve_alias("domain") == "domain_prefix"


class TestValidation:
    def test_valid_feature(self, fm):
        errors = fm.validate_features(["no_cni"], "4.22")
        assert errors == []

    def test_multiple_valid_features(self, fm):
        errors = fm.validate_features(["no_cni", "external_oidc", "cluster_autoscaler_expander"], "4.22")
        assert errors == []

    def test_unknown_feature(self, fm):
        errors = fm.validate_features(["nonexistent"], "4.22")
        assert len(errors) == 1
        assert "Unknown feature" in errors[0]

    def test_version_too_old(self, fm):
        errors = fm.validate_features(["fips"], "4.20")
        assert len(errors) == 1
        assert "requires OpenShift >= 4.21" in errors[0]

    def test_fips_valid_on_421(self, fm):
        errors = fm.validate_features(["fips"], "4.21")
        assert errors == []

    def test_external_oidc_invalid_on_418(self, fm):
        errors = fm.validate_features(["external_oidc"], "4.18")
        assert len(errors) == 1
        assert "requires OpenShift >= 4.19" in errors[0]

    def test_non_cli_feature_rejected(self, fm):
        errors = fm.validate_features(["sts"], "4.22")
        assert len(errors) == 1
        assert "not available as a CLI flag" in errors[0]

    def test_validate_with_aliases(self, fm):
        errors = fm.validate_features(["no-cni", "disk-size"], "4.22")
        assert errors == []

    def test_validate_mixed_aliases_and_ids(self, fm):
        errors = fm.validate_features(["no-cni", "external_oidc"], "4.22")
        assert errors == []


class TestDependencyResolution:
    def test_byon_adds_private(self, fm):
        # byon is not a CLI feature but dependency resolution still works
        resolved = fm.auto_resolve_deps(["byon"])
        assert "private_network" in resolved
        assert "byon" in resolved

    def test_no_deps_unchanged(self, fm):
        resolved = fm.auto_resolve_deps(["private_network"])
        assert resolved == ["private_network"]

    def test_empty_list(self, fm):
        resolved = fm.auto_resolve_deps([])
        assert resolved == []

    def test_dep_not_duplicated(self, fm):
        resolved = fm.auto_resolve_deps(["byon", "private_network"])
        assert resolved.count("private_network") == 1

    def test_fips_adds_etcd_kms(self, fm):
        resolved = fm.auto_resolve_deps(["fips"])
        assert "etcd_kms" in resolved
        assert "fips" in resolved


class TestExtraVarResolution:
    def test_boolean_feature(self, fm):
        result = fm.resolve_to_extra_vars(["no_cni"])
        assert result["no_cni"] == "true"
        assert "requested_features" in result

    def test_multiple_features(self, fm):
        result = fm.resolve_to_extra_vars(["no_cni", "external_oidc"])
        assert result["no_cni"] == "true"
        assert result["external_oidc"] == "true"

    def test_requested_features_string(self, fm):
        result = fm.resolve_to_extra_vars(["no_cni", "external_oidc"])
        assert "no_cni" in result["requested_features"]
        assert "external_oidc" in result["requested_features"]

    def test_typed_feature_sets_enabled_flag(self, fm):
        result = fm.resolve_to_extra_vars(["etcd_kms"])
        assert "feature_etcd_kms_enabled" in result

    def test_ci_default_overrides_empty_default(self, fm):
        result = fm.resolve_to_extra_vars(["disk_size"])
        assert result["root_volume_size"] == "500"
        assert result["feature_disk_size_enabled"] == "true"

    def test_ci_default_tags(self, fm):
        import json
        result = fm.resolve_to_extra_vars(["additional_tags"])
        assert "additional_tags" in result
        tags = json.loads(result["additional_tags"])
        assert tags["Team"] == "PICS"
        assert tags["Jira"] == "RHACM4K-61815"

    def test_ci_default_parallel_upgrade(self, fm):
        result = fm.resolve_to_extra_vars(["parallel_upgrade"])
        assert result["parallel_node_upgrade"] == "2"

    def test_requires_input_skips_var(self, fm):
        result = fm.resolve_to_extra_vars(["etcd_kms"])
        assert "etcd_encryption_kms_arn" not in result

    def test_empty_list_default_not_set(self, fm):
        result = fm.resolve_to_extra_vars(["security_groups"])
        assert "additional_security_groups" not in result
        assert "feature_security_groups_enabled" in result

    def test_empty_feature_list(self, fm):
        result = fm.resolve_to_extra_vars([])
        assert result["requested_features"] == ""


class TestRequiredInputs:
    def test_etcd_kms_requires_input(self, fm):
        warnings = fm.check_required_inputs(["etcd_kms"], {})
        assert len(warnings) == 1
        assert "requires a value" in warnings[0]

    def test_etcd_kms_satisfied(self, fm):
        warnings = fm.check_required_inputs(
            ["etcd_kms"],
            {"etcd_encryption_kms_arn": "arn:aws:kms:us-west-2:123:key/abc"}
        )
        assert warnings == []

    def test_security_groups_requires_input(self, fm):
        warnings = fm.check_required_inputs(["security_groups"], {})
        assert len(warnings) == 1

    def test_boolean_feature_no_warning(self, fm):
        warnings = fm.check_required_inputs(["no_cni"], {})
        assert warnings == []

    def test_ci_default_feature_no_warning(self, fm):
        warnings = fm.check_required_inputs(["disk_size"], {})
        assert warnings == []

    def test_byon_names_real_inputs_not_enable_flag(self, fm):
        """byon maps to byon_vpc, but the inputs users must supply are the subnets/AZs."""
        warnings = fm.check_required_inputs(["byon"], {})
        assert len(warnings) == 1
        assert "byon_subnet_ids" in warnings[0]
        assert "byon_availability_zones" in warnings[0]
        assert "byon_vpc" not in warnings[0]

    def test_byon_partially_satisfied_still_warns(self, fm):
        warnings = fm.check_required_inputs(
            ["byon"], {"byon_subnet_ids": '["subnet-0abc1234"]'}
        )
        assert len(warnings) == 1
        assert "byon_availability_zones" in warnings[0]
        assert "byon_subnet_ids" not in warnings[0]

    def test_byon_satisfied(self, fm):
        warnings = fm.check_required_inputs(
            ["byon"],
            {
                "byon_subnet_ids": '["subnet-0abc1234"]',
                "byon_availability_zones": '["us-west-2a"]',
            },
        )
        assert warnings == []

    def test_audit_logging_requires_a_destination(self, fm):
        warnings = fm.check_required_inputs(["audit_logging"], {})
        assert len(warnings) == 1
        assert "log_forward_cloudwatch_role_arn" in warnings[0]
        assert "log_forward_s3_bucket" in warnings[0]

    def test_audit_logging_satisfied_by_s3(self, fm):
        warnings = fm.check_required_inputs(
            ["audit_logging"], {"log_forward_s3_bucket": "my-audit-bucket"}
        )
        assert warnings == []

    def test_audit_logging_satisfied_by_full_cloudwatch_pair(self, fm):
        warnings = fm.check_required_inputs(
            ["audit_logging"],
            {
                "log_forward_cloudwatch_role_arn": "arn:aws:iam::123:role/logs",
                "log_forward_cloudwatch_log_group": "/rosa/audit",
            },
        )
        assert warnings == []

    def test_audit_logging_partial_cloudwatch_pair_warns(self, fm):
        """Role ARN without a log group renders no forwarder block — must not pass."""
        warnings = fm.check_required_inputs(
            ["audit_logging"],
            {"log_forward_cloudwatch_role_arn": "arn:aws:iam::123:role/logs"},
        )
        assert len(warnings) == 1

    def test_day1_networking_group_flags_missing_log_destination(self, fm):
        """The whole point: day1-networking must fail fast, not 40 minutes in."""
        features = fm.resolve_group("day1-networking")
        warnings = fm.check_required_inputs(features, {})
        assert any("audit_logging" in w for w in warnings)


class TestListFeatures:
    def test_lists_all(self, fm):
        features = fm.list_features()
        assert len(features) > 0
        ids = [f["id"] for f in features]
        assert "no_cni" in ids
        assert "external_oidc" in ids

    def test_filter_by_version_excludes_new(self, fm):
        features = fm.list_features(version="4.18")
        ids = [f["id"] for f in features]
        assert "fips" not in ids
        assert "external_oidc" not in ids

    def test_filter_by_version_includes_available(self, fm):
        features = fm.list_features(version="4.22")
        ids = [f["id"] for f in features]
        assert "fips" in ids
        assert "no_cni" in ids

    def test_feature_has_required_fields(self, fm):
        features = fm.list_features()
        for f in features:
            assert "id" in f
            assert "name" in f
            assert "description" in f
            assert "type" in f
            assert "var_name" in f


class TestVersionComparison:
    def test_patch_version_handled(self, fm):
        errors = fm.validate_features(["fips"], "4.21.5")
        assert errors == []

    def test_minor_version_only(self, fm):
        errors = fm.validate_features(["fips"], "4.21")
        assert errors == []

    def test_future_version_works(self, fm):
        errors = fm.validate_features(["no_cni"], "4.99")
        assert errors == []

    def test_numeric_comparison_not_lexicographic(self, fm):
        # 4.9 < 4.19 numerically, so features with min_version 4.19
        # should NOT appear at 4.9 but SHOULD appear at 4.19
        features_at_49 = fm.list_features(version="4.9")
        features_at_419 = fm.list_features(version="4.19")
        ids_49 = {f["id"] for f in features_at_49}
        ids_419 = {f["id"] for f in features_at_419}
        assert "no_cni" not in ids_49
        assert "no_cni" in ids_419


class TestGetFeature:
    def test_known_feature(self, fm):
        feat = fm.get_feature("no_cni")
        assert feat is not None
        assert feat["name"] == "No CNI Plugin"

    def test_unknown_feature(self, fm):
        feat = fm.get_feature("nonexistent")
        assert feat is None


class TestFeatureGroups:
    def test_list_groups(self, fm):
        groups = fm.list_groups()
        assert len(groups) >= 4
        names = [g["name"] for g in groups]
        assert "day1-basic" in names
        assert "day1-combo" in names

    def test_resolve_basic_group(self, fm):
        features = fm.resolve_group("day1-basic")
        assert len(features) == 5
        assert "domain_prefix" in features
        assert "availability_zones" in features
        assert "additional_tags" in features
        assert "channel_group" in features
        assert "default_autoscaling" in features

    def test_resolve_combo_group(self, fm):
        features = fm.resolve_group("day1-combo")
        assert len(features) == 4
        assert "cluster_autoscaler_expander" in features
        assert "image_registry" in features
        assert "parallel_upgrade" in features
        assert "disk_size" in features

    def test_resolve_networking_group(self, fm):
        features = fm.resolve_group("day1-networking")
        assert len(features) == 4
        assert "no_cni" in features
        assert "private_network" in features
        assert "external_oidc" in features
        assert "audit_logging" in features

    def test_resolve_unknown_group(self, fm):
        result = fm.resolve_group("nonexistent")
        assert result is None

    def test_combo_group_plus_extra_feature(self, fm):
        group_features = fm.resolve_group("day1-combo")
        combined = group_features + ["etcd_kms"]
        resolved = fm.auto_resolve_deps(combined)
        assert "disk_size" in resolved
        assert "etcd_kms" in resolved
        assert len(resolved) == len(set(resolved))

    def test_group_and_individual_feature_dedup(self, fm):
        """Simulate --feature-group day1-combo --feature disk-size (disk_size in both)."""
        group_features = fm.resolve_group("day1-combo")
        individual = ["disk_size"]
        merged = individual + group_features
        deduped = list(dict.fromkeys(merged))
        assert deduped.count("disk_size") == 1
        assert len(deduped) == len(group_features)

    def test_group_features_are_valid_cli_features(self, fm):
        for group in fm.list_groups():
            for feat in group["features"]:
                assert feat in fm._cli_features, \
                    f"Group '{group['name']}' contains '{feat}' which is not in cli_features"


class TestScenarios:
    def test_list_scenarios(self, fm):
        names = [s["name"] for s in fm.list_scenarios()]
        assert "day1-basic" in names
        assert "day1-security" in names

    def test_scenario_features_come_from_group(self, fm):
        assert fm.scenario_features("day1-security") == fm.resolve_group("day1-security")

    def test_unknown_scenario_raises(self, fm):
        with pytest.raises(ScenarioError, match="Unknown scenario"):
            fm.resolve_scenario("nonexistent")

    def test_stages_normalized_to_dicts(self, fm):
        stages = fm.scenario_stages("day1-basic")
        assert all(set(s) == {"suite", "always"} for s in stages)
        assert stages[0]["suite"] == "10-configure-mce-environment"
        assert stages[0]["always"] is False

    def test_cleanup_stages_marked_always(self, fm):
        """Delete and restore must run even after an earlier stage fails."""
        stages = {s["suite"]: s["always"] for s in fm.scenario_stages("day1-basic")}
        assert stages["30-rosa-hcp-delete"] is True
        assert stages["41-disable-capi-enable-hypershift"] is True
        assert stages["20-rosa-hcp-provision"] is False


class TestScenarioVersions:
    def test_basic_runs_on_every_supported_version(self, fm):
        assert fm.scenario_versions("day1-basic") == fm._supported_versions

    def test_security_gated_by_fips_min_version(self, fm):
        assert fm.scenario_versions("day1-security") == ["4.21", "4.22", "5.0"]

    def test_networking_gated_by_audit_logging(self, fm):
        assert fm.scenario_versions("day1-networking") == ["4.20", "4.21", "4.22", "5.0"]

    def test_combo_gated_at_419(self, fm):
        assert fm.scenario_versions("day1-combo") == ["4.19", "4.20", "4.21", "4.22", "5.0"]

    def test_resolve_rejects_unavailable_version(self, fm):
        with pytest.raises(ScenarioError, match="not available on OpenShift 4.20"):
            fm.resolve_scenario("day1-security", "4.20")

    def test_rejection_names_the_blocking_feature(self, fm):
        with pytest.raises(ScenarioError, match="fips"):
            fm.resolve_scenario("day1-security", "4.20")

    def test_all_scenarios_runnable_on_50(self, fm):
        """5.0 is the version this work was motivated by — every scenario must reach it."""
        for s in fm.list_scenarios():
            assert "5.0" in s["versions"], f"{s['name']} cannot run on 5.0"


class TestScenarioVersionOverrides:
    def test_50_forces_candidate_channel(self, fm):
        resolved = fm.resolve_scenario("day1-basic", "5.0")
        assert resolved["extra_vars"]["channel_group"] == "candidate"

    def test_no_channel_override_on_422(self, fm):
        resolved = fm.resolve_scenario("day1-basic", "4.22")
        assert "channel_group" not in resolved["extra_vars"]


class TestScenarioEnvInterpolation:
    def test_missing_env_raises_naming_the_vars(self, fm, monkeypatch):
        monkeypatch.delenv("ETCD_KMS_ARN", raising=False)
        monkeypatch.delenv("CAPI_TEST_SECURITY_GROUP_IDS", raising=False)
        with pytest.raises(ScenarioError) as exc:
            fm.resolve_scenario("day1-security", "4.22")
        assert "ETCD_KMS_ARN" in str(exc.value)
        assert "CAPI_TEST_SECURITY_GROUP_IDS" in str(exc.value)

    def test_env_values_substituted(self, fm, monkeypatch):
        monkeypatch.setenv("ETCD_KMS_ARN", "arn:aws:kms:us-west-2:1:key/k")
        monkeypatch.setenv("CAPI_TEST_SECURITY_GROUP_IDS", '["sg-0abc1234"]')
        resolved = fm.resolve_scenario("day1-security", "4.22")
        assert resolved["extra_vars"]["etcd_encryption_kms_arn"] == "arn:aws:kms:us-west-2:1:key/k"
        assert resolved["extra_vars"]["additional_security_groups"] == '["sg-0abc1234"]'

    def test_empty_env_treated_as_missing(self, fm, monkeypatch):
        monkeypatch.setenv("CAPI_TEST_LOG_S3_BUCKET", "")
        with pytest.raises(ScenarioError, match="CAPI_TEST_LOG_S3_BUCKET"):
            fm.resolve_scenario("day1-networking", "4.22")

    def test_scenario_inputs_satisfy_required_input_check(self, fm, monkeypatch):
        """day1-security's env-supplied vars must count as provided."""
        monkeypatch.setenv("ETCD_KMS_ARN", "arn:aws:kms:us-west-2:1:key/k")
        monkeypatch.setenv("CAPI_TEST_SECURITY_GROUP_IDS", '["sg-0abc1234"]')
        resolved = fm.resolve_scenario("day1-security", "4.22")
        warnings = fm.check_required_inputs(resolved["features"], resolved["extra_vars"])
        assert warnings == []


class TestScenarioExtends:
    def test_extends_prepends_parent_features(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)
        registry = {
            "version": "1.0",
            "var_map": {"feat_a": "a", "feat_b": "b"},
            "cli_aliases": {},
            "cli_features": ["feat_a", "feat_b"],
            "dependencies": {},
            "mutual_exclusions": [],
            "feature_groups": {
                "grp_a": {"features": ["feat_a"]},
                "grp_b": {"features": ["feat_b"]},
            },
            "scenario_defaults": {"stages": ["20-provision"]},
            "scenarios": {
                "base": {"feature_group": "grp_a"},
                "child": {"extends": "base", "feature_group": "grp_b"},
            },
            "suites": [{
                "id": "test", "name": "Test", "phase": "Day1",
                "features": [
                    {"id": "feat_a", "name": "A", "description": "A", "type": "boolean", "default": False},
                    {"id": "feat_b", "name": "B", "description": "B", "type": "boolean", "default": False},
                ],
            }],
        }
        compat = {"supported_versions": ["4.22"], "feature_availability": {}}
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        assert fm.scenario_features("child") == ["feat_a", "feat_b"]

    def test_circular_extends_raises(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)
        registry = {
            "version": "1.0",
            "var_map": {}, "cli_aliases": {}, "cli_features": [],
            "dependencies": {}, "mutual_exclusions": [],
            "scenarios": {
                "a": {"extends": "b"},
                "b": {"extends": "a"},
            },
            "suites": [],
        }
        compat = {"supported_versions": ["4.22"], "feature_availability": {}}
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        with pytest.raises(ScenarioError, match="Circular"):
            fm.scenario_features("a")


class TestScenarioRegistryIntegrity:
    def test_every_scenario_references_a_real_group(self, fm):
        for name in fm._scenarios:
            fm.scenario_features(name)  # raises on unknown group

    def test_every_scenario_stage_has_a_suite_file(self, fm):
        suites_dir = Path(__file__).parent.parent / "test-suites"
        for s in fm.list_scenarios():
            for suite_id in s["stages"]:
                assert (suites_dir / f"{suite_id}.json").exists(), \
                    f"Scenario '{s['name']}' references missing suite {suite_id}.json"

    def test_every_scenario_has_at_least_one_version(self, fm):
        for s in fm.list_scenarios():
            assert s["versions"], f"Scenario '{s['name']}' cannot run on any supported version"


class TestLoadErrors:
    def test_missing_schema_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Schema file not found"):
            FeatureManager(tmp_path)

    def test_invalid_yaml_content(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)
        (schemas_dir / "feature-registry.yml").write_text("- just a list")
        (schemas_dir / "version-compatibility.yml").write_text("key: val")
        with pytest.raises(ValueError, match="Invalid YAML"):
            FeatureManager(tmp_path)


class TestMutualExclusions:
    def test_mutual_exclusion_detected(self, tmp_path):
        """Test with a custom registry that has actual mutual exclusions."""
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)

        registry = {
            "version": "1.0",
            "var_map": {"feat_a": "a", "feat_b": "b"},
            "cli_aliases": {},
            "cli_features": ["feat_a", "feat_b"],
            "dependencies": {},
            "mutual_exclusions": [["feat_a", "feat_b"]],
            "suites": [{
                "id": "test",
                "name": "Test",
                "phase": "Day1",
                "features": [
                    {"id": "feat_a", "name": "A", "description": "A", "type": "boolean", "default": False},
                    {"id": "feat_b", "name": "B", "description": "B", "type": "boolean", "default": False},
                ]
            }]
        }
        compat = {
            "supported_versions": ["4.22"],
            "feature_availability": {}
        }

        import yaml
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        errors = fm.validate_features(["feat_a", "feat_b"], "4.22")
        assert len(errors) == 1
        assert "mutually exclusive" in errors[0]

    def test_no_exclusion_when_only_one_present(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)

        registry = {
            "version": "1.0",
            "var_map": {"feat_a": "a", "feat_b": "b"},
            "cli_aliases": {},
            "cli_features": ["feat_a", "feat_b"],
            "dependencies": {},
            "mutual_exclusions": [["feat_a", "feat_b"]],
            "suites": [{
                "id": "test",
                "name": "Test",
                "phase": "Day1",
                "features": [
                    {"id": "feat_a", "name": "A", "description": "A", "type": "boolean", "default": False},
                    {"id": "feat_b", "name": "B", "description": "B", "type": "boolean", "default": False},
                ]
            }]
        }
        compat = {
            "supported_versions": ["4.22"],
            "feature_availability": {}
        }

        import yaml
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        errors = fm.validate_features(["feat_a"], "4.22")
        assert errors == []


class TestCircularDependencyGuard:
    def test_circular_deps_do_not_loop(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)

        registry = {
            "version": "1.0",
            "var_map": {"feat_a": "a", "feat_b": "b"},
            "cli_aliases": {},
            "cli_features": ["feat_a", "feat_b"],
            "dependencies": {"feat_a": ["feat_b"], "feat_b": ["feat_a"]},
            "mutual_exclusions": [],
            "suites": [{
                "id": "test",
                "name": "Test",
                "phase": "Day1",
                "features": [
                    {"id": "feat_a", "name": "A", "description": "A", "type": "boolean", "default": False},
                    {"id": "feat_b", "name": "B", "description": "B", "type": "boolean", "default": False},
                ]
            }]
        }
        compat = {
            "supported_versions": ["4.22"],
            "feature_availability": {}
        }

        import yaml
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        resolved = fm.auto_resolve_deps(["feat_a"])
        assert "feat_a" in resolved
        assert "feat_b" in resolved
        assert len(resolved) == 2


class TestFalsyDefaults:
    def test_zero_default_preserved(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)

        registry = {
            "version": "1.0",
            "var_map": {"feat_z": "z_var"},
            "cli_aliases": {},
            "cli_features": ["feat_z"],
            "dependencies": {},
            "mutual_exclusions": [],
            "suites": [{
                "id": "test",
                "name": "Test",
                "phase": "Day1",
                "features": [
                    {"id": "feat_z", "name": "Z", "description": "Zero default", "type": "number", "default": 0},
                ]
            }]
        }
        compat = {
            "supported_versions": ["4.22"],
            "feature_availability": {}
        }

        import yaml
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        result = fm.resolve_to_extra_vars(["feat_z"])
        assert "z_var" in result
        assert result["z_var"] == "0"


class TestDeprecatedFeatureFiltering:
    def test_deprecated_feature_excluded_from_list(self, tmp_path):
        """Test that features past their max_version are excluded from list."""
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)

        registry = {
            "version": "1.0",
            "var_map": {"old_feat": "old"},
            "cli_aliases": {},
            "cli_features": ["old_feat"],
            "dependencies": {},
            "mutual_exclusions": [],
            "suites": [{
                "id": "test",
                "name": "Test",
                "phase": "Day1",
                "features": [
                    {"id": "old_feat", "name": "Old", "description": "Deprecated", "type": "boolean", "default": False},
                ]
            }]
        }
        compat = {
            "supported_versions": ["4.18", "4.19", "4.20"],
            "feature_availability": {
                "old_feat": {"min_version": "4.18", "max_version": "4.19"}
            }
        }

        import yaml
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)

        features_419 = fm.list_features(version="4.19")
        assert any(f["id"] == "old_feat" for f in features_419)

        features_420 = fm.list_features(version="4.20")
        assert not any(f["id"] == "old_feat" for f in features_420)

    def test_deprecated_feature_rejected_in_validation(self, tmp_path):
        schemas_dir = tmp_path / "templates" / "schemas"
        schemas_dir.mkdir(parents=True)

        registry = {
            "version": "1.0",
            "var_map": {"old_feat": "old"},
            "cli_aliases": {},
            "cli_features": ["old_feat"],
            "dependencies": {},
            "mutual_exclusions": [],
            "suites": [{
                "id": "test",
                "name": "Test",
                "phase": "Day1",
                "features": [
                    {"id": "old_feat", "name": "Old", "description": "Deprecated", "type": "boolean", "default": False},
                ]
            }]
        }
        compat = {
            "supported_versions": ["4.18", "4.19", "4.20"],
            "feature_availability": {
                "old_feat": {"min_version": "4.18", "max_version": "4.19"}
            }
        }

        import yaml
        (schemas_dir / "feature-registry.yml").write_text(yaml.dump(registry))
        (schemas_dir / "version-compatibility.yml").write_text(yaml.dump(compat))

        fm = FeatureManager(tmp_path)
        errors = fm.validate_features(["old_feat"], "4.20")
        assert len(errors) == 1
        assert "deprecated" in errors[0]


def _render_template(template_name, version, extra_vars=None):
    base = Path(__file__).parent.parent / "templates" / "versions" / version / "features"
    env = Environment(loader=FileSystemLoader(str(base)), undefined=Undefined)
    env.filters["regex_replace"] = lambda v, p, r="": re.sub(p, r, str(v))
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "on", "1")
    template = env.get_template(template_name)
    vars = {
        "cluster_name": "test-cluster",
        "rosa_hcp_namespace": "test-ns",
        "aws_region": "us-west-2",
        "rcp_version": f"{version}.0",
        "openshift_version": f"{version}.0",
        "rosa_role_prefix": "test",
        "domain_prefix": "test",
        "machine_pool": {"instance_type": "m5.xlarge", "min_replicas": 2, "max_replicas": 2, "replicas": 2},
        "cluster_network": {"machine_cidr": "10.0.0.0/16", "pod_cidr": "10.128.0.0/14", "service_cidr": "172.30.0.0/16"},
        "rosa_network_config": {"identity_name": "default", "cidr_block": "10.0.0.0/16", "availability_zones": ["us-west-2a", "us-west-2b"]},
        "rosa_role_config": {"identity_name": "default", "prefix": "test", "version": f"{version}.0", "enabled": True},
    }
    if extra_vars:
        vars.update(extra_vars)
    rendered = template.render(**vars)
    return [d for d in yaml.safe_load_all(rendered) if d]


class TestTemplateSecurityGroupPlacement:
    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_sg_only_on_machine_pool(self, version, template_name):
        docs = _render_template(template_name, version, {"additional_security_groups": ["sg-test123"]})
        assert docs, f"{template_name}: rendered no YAML documents"
        assert any(d.get("kind") == "ROSAMachinePool" for d in docs), f"{template_name}: no ROSAMachinePool document"
        for doc in docs:
            kind = doc.get("kind")
            has_sg = "additionalSecurityGroups" in doc.get("spec", {})
            if kind == "ROSAMachinePool":
                assert has_sg, f"{template_name}: ROSAMachinePool missing additionalSecurityGroups"
                assert doc["spec"]["additionalSecurityGroups"] == ["sg-test123"]
            else:
                assert not has_sg, f"{template_name}: {kind} should NOT have additionalSecurityGroups"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_no_sg_when_not_defined(self, version, template_name):
        docs = _render_template(template_name, version)
        assert docs, f"{template_name}: rendered no YAML documents"
        for doc in docs:
            assert "additionalSecurityGroups" not in doc.get("spec", {}), \
                f"{template_name}: {doc.get('kind')} has additionalSecurityGroups when none defined"


class TestFeatureRegistrySecurityGroups:
    def test_security_groups_resource_is_machine_pool(self, fm):
        feat = fm.get_feature("security_groups")
        assert feat is not None
        assert feat["resource"] == "ROSAMachinePool"

    def test_security_groups_var_mapping(self, fm):
        result = fm.resolve_to_extra_vars(["security_groups"])
        assert "feature_security_groups_enabled" in result


class TestNoCNI:
    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_no_cni_renders_network_type_other(self, version, template_name):
        docs = _render_template(template_name, version, {"no_cni": True})
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None, f"{template_name}: no ROSAControlPlane document"
        assert rcp["spec"]["network"]["networkType"] == "Other"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_no_cni_false_omits_network_type(self, version, template_name):
        docs = _render_template(template_name, version, {"no_cni": False})
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "networkType" not in rcp["spec"].get("network", {}), \
            f"{template_name}: networkType should not be rendered when no_cni is false"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_default_omits_network_type(self, version, template_name):
        docs = _render_template(template_name, version)
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "networkType" not in rcp["spec"].get("network", {}), \
            f"{template_name}: networkType should not be rendered by default"

    def test_no_cni_feature_metadata(self, fm):
        feat = fm.get_feature("no_cni")
        assert feat is not None
        assert feat["resource"] == "ROSAControlPlane"
        assert feat["k8s_field"] == ".spec.network.networkType"
        assert feat.get("min_version") == "4.19"

    def test_no_cni_var_mapping(self, fm):
        result = fm.resolve_to_extra_vars(["no_cni"])
        assert "no_cni" in result

    def test_no_cni_alias(self, fm):
        assert fm.resolve_alias("no-cni") == "no_cni"

    def test_no_cni_rejected_on_418(self, fm):
        errors = fm.validate_features(["no_cni"], "4.18")
        assert len(errors) > 0

    def test_no_cni_valid_on_419(self, fm):
        errors = fm.validate_features(["no_cni"], "4.19")
        assert errors == []


class TestExternalOIDC:
    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_renders_enabled(self, version, template_name):
        docs = _render_template(template_name, version, {"external_oidc": True})
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None, f"{template_name}: no ROSAControlPlane document"
        assert rcp["spec"]["enableExternalAuthProviders"] is True

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_with_issuer_renders_providers(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_client_id": "test-client",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["enableExternalAuthProviders"] is True
        providers = rcp["spec"].get("externalAuthProviders", [])
        assert len(providers) > 0, f"{template_name}: externalAuthProviders not rendered"
        assert providers[0]["issuer"]["issuerURL"] == "https://login.example.com"
        assert "test-client" in providers[0]["issuer"]["audiences"]

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_false_omits_providers(self, version, template_name):
        docs = _render_template(template_name, version, {"external_oidc": False})
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "enableExternalAuthProviders" not in rcp.get("spec", {}), \
            f"{template_name}: enableExternalAuthProviders should not be rendered when false"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_default_omits_external_oidc(self, version, template_name):
        docs = _render_template(template_name, version)
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "enableExternalAuthProviders" not in rcp.get("spec", {}), \
            f"{template_name}: enableExternalAuthProviders should not be rendered by default"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_claim_mappings(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_username_claim": "preferred_username",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        providers = rcp["spec"].get("externalAuthProviders", [])
        assert len(providers) > 0
        claim_mappings = providers[0].get("claimMappings", {})
        assert claim_mappings["username"]["claim"] == "preferred_username"

    def test_external_oidc_feature_metadata(self, fm):
        feat = fm.get_feature("external_oidc")
        assert feat is not None
        assert feat["resource"] == "ROSAControlPlane"
        assert feat["k8s_field"] == ".spec.enableExternalAuthProviders"
        assert feat.get("min_version") == "4.19"

    def test_external_oidc_var_mapping(self, fm):
        result = fm.resolve_to_extra_vars(["external_oidc"])
        assert "external_oidc" in result

    def test_external_oidc_alias(self, fm):
        assert fm.resolve_alias("external-oidc") == "external_oidc"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_flag_only_no_providers(self, version, template_name):
        docs = _render_template(template_name, version, {"external_oidc": True})
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["enableExternalAuthProviders"] is True
        assert "externalAuthProviders" not in rcp.get("spec", {}), \
            f"{template_name}: externalAuthProviders should not render without oidc_issuer_url"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_oidc_clients_block(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_client_id": "my-client-id",
            "oidc_client_secret_name": "my-client-secret",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        providers = rcp["spec"]["externalAuthProviders"]
        assert len(providers) > 0
        oidc_clients = providers[0].get("oidcClients", [])
        assert len(oidc_clients) > 0, f"{template_name}: oidcClients not rendered"
        assert oidc_clients[0]["componentName"] == "console"
        assert oidc_clients[0]["componentNamespace"] == "openshift-console"
        assert oidc_clients[0]["clientID"] == "my-client-id"
        assert oidc_clients[0]["clientSecret"]["name"] == "my-client-secret"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_oidc_clients_without_secret(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_client_id": "my-client-id",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        providers = rcp["spec"]["externalAuthProviders"]
        oidc_clients = providers[0].get("oidcClients", [])
        assert len(oidc_clients) > 0
        assert oidc_clients[0]["clientID"] == "my-client-id"
        assert "clientSecret" not in oidc_clients[0], \
            f"{template_name}: clientSecret should not render without oidc_client_secret_name"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_groups_claim(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_groups_claim": "groups",
            "oidc_groups_prefix": "oidc-prefix",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        providers = rcp["spec"]["externalAuthProviders"]
        groups = providers[0]["claimMappings"].get("groups", {})
        assert groups["claim"] == "groups"
        assert groups["prefix"] == "oidc-prefix"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_groups_claim_without_prefix(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_groups_claim": "groups",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        providers = rcp["spec"]["externalAuthProviders"]
        groups = providers[0]["claimMappings"].get("groups", {})
        assert groups["claim"] == "groups"
        assert "prefix" not in groups

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_no_groups_by_default(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        providers = rcp["spec"]["externalAuthProviders"]
        assert "groups" not in providers[0]["claimMappings"], \
            f"{template_name}: groups should not render by default"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_custom_audiences(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_audiences": ["aud-1", "aud-2", "aud-3"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        audiences = rcp["spec"]["externalAuthProviders"][0]["issuer"]["audiences"]
        assert audiences == ["aud-1", "aud-2", "aud-3"]

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_custom_provider_name(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_provider_name": "my-custom-provider",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["externalAuthProviders"][0]["name"] == "my-custom-provider"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_external_oidc_custom_prefix_policy(self, version, template_name):
        docs = _render_template(template_name, version, {
            "external_oidc": True,
            "oidc_issuer_url": "https://login.example.com",
            "oidc_username_prefix_policy": "Prefix",
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        prefix_policy = rcp["spec"]["externalAuthProviders"][0]["claimMappings"]["username"]["prefixPolicy"]
        assert prefix_policy == "Prefix"

    def test_external_oidc_rejected_on_418(self, fm):
        errors = fm.validate_features(["external_oidc"], "4.18")
        assert len(errors) > 0

    def test_external_oidc_valid_on_419(self, fm):
        errors = fm.validate_features(["external_oidc"], "4.19")
        assert errors == []


class TestPrivateClusterSubnets:
    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_private_subnets_rendered_on_controlplane(self, version, template_name):
        docs = _render_template(template_name, version, {
            "private": True,
            "cluster_private_subnets": ["subnet-0abc1234", "subnet-0def5678"],
        })
        assert docs, f"{template_name}: rendered no YAML documents"
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None, f"{template_name}: no ROSAControlPlane document"
        assert rcp["spec"]["endpointAccess"] == "Private"
        assert rcp["spec"]["subnets"] == ["subnet-0abc1234", "subnet-0def5678"]

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_no_subnets_when_not_private(self, version, template_name):
        docs = _render_template(template_name, version)
        assert docs, f"{template_name}: rendered no YAML documents"
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "subnets" not in rcp.get("spec", {}), \
            f"{template_name}: subnets should not be rendered when not private"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_private_without_subnets_renders_no_subnets_field(self, version, template_name):
        docs = _render_template(template_name, version, {"private": True})
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"].get("endpointAccess") == "Private"
        assert "subnets" not in rcp.get("spec", {}), \
            f"{template_name}: subnets should not be rendered when cluster_private_subnets not provided"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_rosanetworkref_excluded_when_subnets_set(self, version, template_name):
        docs = _render_template(template_name, version, {
            "private": True,
            "cluster_private_subnets": ["subnet-0abc1234", "subnet-0def5678"],
            "rosa_network_subnets": [
                {"availabilityZone": "us-west-2a", "privateSubnet": "subnet-0abc1234", "publicSubnet": "subnet-0aaa1111"},
                {"availabilityZone": "us-west-2b", "privateSubnet": "subnet-0def5678", "publicSubnet": "subnet-0bbb2222"},
            ],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "rosaNetworkRef" not in rcp.get("spec", {}), \
            f"{template_name}: rosaNetworkRef should be excluded when subnets are set"
        assert rcp["spec"]["subnets"] == ["subnet-0abc1234", "subnet-0def5678"]
        assert rcp["spec"]["availabilityZones"] == ["us-west-2a", "us-west-2b"]

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_rosanetworkref_present_when_no_subnets(self, version, template_name):
        docs = _render_template(template_name, version)
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "rosaNetworkRef" in rcp.get("spec", {}), \
            f"{template_name}: rosaNetworkRef should be present when no subnets"

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_subnets_not_rendered_when_public_even_if_var_present(self, version, template_name):
        docs = _render_template(template_name, version, {
            "private": False,
            "cluster_private_subnets": ["subnet-0abc1234"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["endpointAccess"] == "Public"
        assert "subnets" not in rcp.get("spec", {}), \
            f"{template_name}: subnets should not render when private=false"

    def test_private_network_feature_metadata(self, fm):
        feat = fm.get_feature("private_network")
        assert feat is not None
        assert feat["resource"] == "ROSAControlPlane"
        assert feat["k8s_field"] == ".spec.endpointAccess"

    def test_private_network_var_mapping(self, fm):
        result = fm.resolve_to_extra_vars(["private_network"])
        assert result["private"] == "true"


class TestBYON:
    def test_byon_alias(self, fm):
        assert fm.resolve_alias("byon-vpc") == "byon"

    def test_byon_in_cli_features(self, fm):
        features = fm.list_features()
        ids = [f["id"] for f in features]
        assert "byon" in ids

    def test_byon_depends_on_private_network(self, fm):
        resolved = fm.auto_resolve_deps(["byon"])
        assert "private_network" in resolved
        assert "byon" in resolved

    def test_byon_feature_metadata(self, fm):
        feat = fm.get_feature("byon")
        assert feat is not None
        assert feat["resource"] == "ROSAControlPlane"
        assert feat["k8s_field"] == ".spec.subnets"
        assert feat.get("requires_input") is True

    def test_byon_var_mapping(self, fm):
        result = fm.resolve_to_extra_vars(["byon"])
        assert "byon_vpc" in result

    def test_byon_valid_on_422(self, fm):
        errors = fm.validate_features(["byon"], "4.22")
        assert errors == []

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_private_availability_zones_fallback(self, version, template_name):
        docs = _render_template(template_name, version, {
            "private": True,
            "cluster_private_subnets": ["subnet-0abc1234", "subnet-0def5678"],
            "private_availability_zones": ["us-west-2a", "us-west-2c"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["subnets"] == ["subnet-0abc1234", "subnet-0def5678"]
        assert rcp["spec"]["availabilityZones"] == ["us-west-2a", "us-west-2c"]

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_byon_subnets_rendered(self, version, template_name):
        docs = _render_template(template_name, version, {
            "byon_subnet_ids": ["subnet-0abc1234", "subnet-0def5678"],
            "byon_availability_zones": ["us-west-2a", "us-west-2b"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["subnets"] == ["subnet-0abc1234", "subnet-0def5678"]
        assert rcp["spec"]["availabilityZones"] == ["us-west-2a", "us-west-2b"]
        assert "rosaNetworkRef" not in rcp.get("spec", {})

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
    ])
    def test_rosa_network_subnets_take_priority_over_fallback(self, version, template_name):
        docs = _render_template(template_name, version, {
            "private": True,
            "cluster_private_subnets": ["subnet-0abc1234"],
            "rosa_network_subnets": [
                {"availabilityZone": "us-west-2a", "privateSubnet": "subnet-0abc1234", "publicSubnet": "subnet-0aaa1111"},
            ],
            "private_availability_zones": ["us-west-2b"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["availabilityZones"] == ["us-west-2a"]

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_no_byon_keeps_network_ref(self, version, template_name):
        docs = _render_template(template_name, version)
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert "rosaNetworkRef" in rcp.get("spec", {})
        assert "subnets" not in rcp.get("spec", {})

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_byon_with_private(self, version, template_name):
        docs = _render_template(template_name, version, {
            "private": True,
            "byon_subnet_ids": ["subnet-0aaa1111", "subnet-0bbb2222"],
            "byon_availability_zones": ["us-west-2a", "us-west-2b"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["endpointAccess"] == "Private"
        assert rcp["spec"]["subnets"] == ["subnet-0aaa1111", "subnet-0bbb2222"]
        assert "rosaNetworkRef" not in rcp.get("spec", {})

    @pytest.mark.parametrize("version,template_name", [
        ("4.22", "rosa-controlplane-only.yaml.j2"),
        ("4.22", "rosa-combined-automation.yaml.j2"),
        ("4.21", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-controlplane-only.yaml.j2"),
        ("4.20", "rosa-combined-automation.yaml.j2"),
    ])
    def test_byon_without_azs_renders_subnets_only(self, version, template_name):
        docs = _render_template(template_name, version, {
            "byon_subnet_ids": ["subnet-0abc1234", "subnet-0def5678"],
        })
        rcp = next((d for d in docs if d.get("kind") == "ROSAControlPlane"), None)
        assert rcp is not None
        assert rcp["spec"]["subnets"] == ["subnet-0abc1234", "subnet-0def5678"]
        assert "availabilityZones" not in rcp.get("spec", {})
        assert "rosaNetworkRef" not in rcp.get("spec", {})


class TestBreakGlassCredentials:
    def test_break_glass_alias(self, fm):
        assert fm.resolve_alias("break-glass") == "break_glass_credentials"

    def test_break_glass_in_cli_features(self, fm):
        features = fm.list_features()
        ids = [f["id"] for f in features]
        assert "break_glass_credentials" in ids

    def test_break_glass_feature_metadata(self, fm):
        feat = fm.get_feature("break_glass_credentials")
        assert feat is not None
        assert feat["name"] == "Break Glass Credentials"
        assert feat["type"] == "action"
        assert feat["resource"] == "ROSAControlPlane"

    def test_break_glass_depends_on_external_oidc(self, fm):
        resolved = fm.auto_resolve_deps(["break_glass_credentials"])
        assert "external_oidc" in resolved
        assert "break_glass_credentials" in resolved

    def test_break_glass_valid_on_419(self, fm):
        errors = fm.validate_features(["break_glass_credentials"], "4.19")
        assert errors == []

    def test_break_glass_invalid_on_418(self, fm):
        errors = fm.validate_features(["break_glass_credentials"], "4.18")
        assert len(errors) == 1
        assert "requires OpenShift >= 4.19" in errors[0]

    def test_break_glass_valid_on_422(self, fm):
        errors = fm.validate_features(["break_glass_credentials"], "4.22")
        assert errors == []

    def test_break_glass_var_mapping(self, fm):
        result = fm.resolve_to_extra_vars(["break_glass_credentials"])
        assert "feature_break_glass_credentials_enabled" in result

    def test_break_glass_alias_resolves_in_extra_vars(self, fm):
        result = fm.resolve_to_extra_vars(["break-glass"])
        assert "break_glass_credentials" in result["requested_features"]
        assert result["feature_break_glass_credentials_enabled"] == "true"

    def test_break_glass_not_in_418_list(self, fm):
        features = fm.list_features(version="4.18")
        ids = [f["id"] for f in features]
        assert "break_glass_credentials" not in ids

    def test_break_glass_in_419_list(self, fm):
        features = fm.list_features(version="4.19")
        ids = [f["id"] for f in features]
        assert "break_glass_credentials" in ids


def _coerce_like_runner(extra_vars):
    """Mimic run_playbook(): JSON-decode values that look like dicts/lists.

    The runner passes those as a JSON blob so Ansible receives real types,
    while everything else goes through as a string. Tests must do the same or
    they are not exercising what actually reaches the templates.
    """
    out = {}
    for key, value in extra_vars.items():
        text = str(value)
        if text[:1] in "{[":
            try:
                out[key] = json.loads(text)
                continue
            except json.JSONDecodeError:
                pass
        out[key] = value
    return out


def _render_scenario(fm, scenario_name, version, template_name):
    """Resolve a scenario and render it through a real template."""
    scenario = fm.resolve_scenario(scenario_name, version)
    extra_vars = _coerce_like_runner({
        **fm.resolve_to_extra_vars(scenario["features"]),
        **scenario["extra_vars"],
    })
    docs = _render_template(template_name, version, extra_vars)
    return {d["kind"]: d.get("spec", {}) for d in docs if "kind" in d}


# Each scenario feature -> (resource kind, top-level spec key it must produce).
# Written out explicitly rather than derived from the registry's `k8s_field`:
# that field is documentation only (nothing reads it), and for audit_logging it
# names just one of two possible forwarder shapes. Same for the playbook's
# `crd_field_map`, which is defined at verify_feature_flags.yml:20 and never
# referenced. An explicit table is the only trustworthy expectation here.
SCENARIO_RENDER_EXPECTATIONS = {
    "day1-basic": [
        ("domain_prefix", "ROSAControlPlane", "domainPrefix"),
        ("additional_tags", "ROSAControlPlane", "additionalTags"),
        ("channel_group", "ROSAControlPlane", "channelGroup"),
        ("default_autoscaling", "ROSAControlPlane", "defaultMachinePoolSpec"),
    ],
    "day1-combo": [
        ("cluster_autoscaler_expander", "ROSAControlPlane", "autoscaler"),
        ("image_registry", "ROSAControlPlane", "clusterRegistryConfig"),
        ("parallel_upgrade", "ROSAMachinePool", "updateConfig"),
        ("disk_size", "ROSAMachinePool", "volumeSize"),
    ],
    "day1-networking": [
        ("no_cni", "ROSAControlPlane", "network"),
        ("private_network", "ROSAControlPlane", "endpointAccess"),
        ("external_oidc", "ROSAControlPlane", "enableExternalAuthProviders"),
        ("audit_logging", "ROSAControlPlane", "s3LogForwarder"),
    ],
    "day1-security": [
        ("etcd_kms", "ROSAControlPlane", "etcdEncryptionKMSARN"),
        ("fips", "ROSAControlPlane", "fips"),
        ("security_groups", "ROSAMachinePool", "additionalSecurityGroups"),
    ],
}


@pytest.fixture
def scenario_env(monkeypatch):
    """The environment inputs the scenarios declare via ${ENV_VAR}."""
    monkeypatch.setenv("ETCD_KMS_ARN", "arn:aws:kms:us-west-2:111122223333:key/test")
    monkeypatch.setenv("CAPI_TEST_SECURITY_GROUP_IDS", '["sg-0abc1234"]')
    monkeypatch.setenv("CAPI_TEST_LOG_S3_BUCKET", "test-audit-bucket")


class TestScenarioRendersThroughTemplates:
    """Close the registry -> template seam.

    Other tests check that the registry emits the right dict, or that a
    template renders given hand-written vars. Nothing checked that the var
    names the registry emits are the var names the templates consume — which
    is exactly where the byon (byon_vpc vs byon_subnet_ids) and audit_logging
    input bugs lived. Scenarios make this seam load-bearing, because nobody
    types these vars by hand any more.
    """

    @pytest.mark.parametrize("scenario_name", sorted(SCENARIO_RENDER_EXPECTATIONS))
    @pytest.mark.parametrize("version", ["4.22", "5.0"])
    def test_every_feature_reaches_the_manifest(self, fm, scenario_env, scenario_name, version):
        applicable = fm.scenario_versions(scenario_name)
        if version not in applicable:
            pytest.skip(f"{scenario_name} not available on {version}")

        specs = _render_scenario(fm, scenario_name, version, "rosa-controlplane-only.yaml.j2")

        for feature, kind, field in SCENARIO_RENDER_EXPECTATIONS[scenario_name]:
            assert kind in specs, f"{scenario_name}@{version}: no {kind} document rendered"
            assert field in specs[kind], (
                f"{scenario_name}@{version}: feature '{feature}' did not reach "
                f"{kind}.spec.{field} — registry var name and template likely disagree"
            )

    @pytest.mark.parametrize("scenario_name", sorted(SCENARIO_RENDER_EXPECTATIONS))
    def test_renders_valid_yaml_in_combined_template(self, fm, scenario_env, scenario_name):
        specs = _render_scenario(fm, scenario_name, "5.0", "rosa-combined-automation.yaml.j2")
        assert "ROSAControlPlane" in specs

    def test_security_values_are_carried_through_not_just_present(self, fm, scenario_env):
        specs = _render_scenario(fm, "day1-security", "5.0", "rosa-controlplane-only.yaml.j2")
        assert specs["ROSAControlPlane"]["etcdEncryptionKMSARN"] == \
            "arn:aws:kms:us-west-2:111122223333:key/test"
        assert specs["ROSAMachinePool"]["additionalSecurityGroups"] == ["sg-0abc1234"]

    def test_50_version_override_reaches_the_manifest(self, fm, scenario_env):
        """channel_group=candidate is what makes 5.0 resolvable via OCM."""
        specs = _render_scenario(fm, "day1-basic", "5.0", "rosa-controlplane-only.yaml.j2")
        assert specs["ROSAControlPlane"]["channelGroup"] == "candidate"

    def test_422_keeps_stable_channel(self, fm, scenario_env):
        specs = _render_scenario(fm, "day1-basic", "4.22", "rosa-controlplane-only.yaml.j2")
        assert specs["ROSAControlPlane"]["channelGroup"] == "stable"


class TestVersionTemplateParity:
    def test_50_templates_match_422(self):
        """5.0 is currently a verbatim copy of 4.22. If that stops being true,
        this test should be updated deliberately rather than drifting silently."""
        import filecmp
        base = Path(__file__).parent.parent / "templates" / "versions"
        a, b = base / "4.22" / "features", base / "5.0" / "features"
        names = sorted(p.name for p in a.iterdir())
        assert names == sorted(p.name for p in b.iterdir())
        match, mismatch, errors = filecmp.cmpfiles(a, b, names, shallow=False)
        assert not mismatch and not errors, f"5.0 diverged from 4.22: {mismatch + errors}"
