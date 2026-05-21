"""Tests for the FeatureManager class."""

import pytest
from pathlib import Path
from feature_manager import FeatureManager


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

    def test_long_name_alias(self, fm):
        assert fm.resolve_alias("long-name") == "domain_prefix"


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


class TestDependencyResolution:
    def test_byon_adds_private(self, fm):
        # byon is not a CLI feature but dependency resolution still works
        resolved = fm.auto_resolve_deps(["byon"])
        assert "private_network" in resolved
        assert "byon" in resolved

    def test_no_deps_unchanged(self, fm):
        resolved = fm.auto_resolve_deps(["private_network"])
        assert resolved == ["private_network"]

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

    def test_ci_default_user_agent(self, fm):
        result = fm.resolve_to_extra_vars(["user_agent"])
        assert result["user_agent"] == "capa-e2e-test"

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
        assert features == []

    def test_resolve_combo_group(self, fm):
        features = fm.resolve_group("day1-combo")
        assert len(features) > 0
        assert "no_cni" in features
        assert "disk_size" in features

    def test_resolve_unknown_group(self, fm):
        result = fm.resolve_group("nonexistent")
        assert result is None

    def test_combo_group_plus_extra_feature(self, fm):
        group_features = fm.resolve_group("day1-combo")
        combined = group_features + ["etcd_kms"]
        resolved = fm.auto_resolve_deps(combined)
        assert "no_cni" in resolved
        assert "etcd_kms" in resolved
        assert len(resolved) == len(set(resolved))

    def test_group_and_individual_feature_dedup(self, fm):
        """Simulate --feature-group day1-combo --feature no-cni (no_cni in both)."""
        group_features = fm.resolve_group("day1-combo")
        individual = ["no_cni"]
        merged = individual + group_features
        deduped = list(dict.fromkeys(merged))
        assert deduped.count("no_cni") == 1
        assert len(deduped) == len(group_features)

    def test_group_features_are_valid_cli_features(self, fm):
        for group in fm.list_groups():
            for feat in group["features"]:
                assert feat in fm._cli_features, \
                    f"Group '{group['name']}' contains '{feat}' which is not in cli_features"


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
