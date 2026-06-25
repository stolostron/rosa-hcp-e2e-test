"""Tests for FeatureGuardConfig."""

import pytest
import yaml
from pathlib import Path

from agents.feature_guard_config import (
    FeatureGuardConfig,
    DetectionConfig,
    UpstreamConfig,
    AdvisoryConfig,
    AutoTestConfig,
)

BASE_DIR = Path(__file__).parent.parent


class TestFeatureGuardConfig:
    def test_default_values(self):
        config = FeatureGuardConfig.default()
        assert config.auto_record is True
        assert config.verbose is False
        assert config.detection.local_since == "HEAD~1"
        assert config.upstream.repo == "stolostron/cluster-api-provider-aws"
        assert config.upstream.branch == "backplane-2.11"
        assert config.advisory.enabled is True
        assert config.advisory.sources == ["redhat", "github"]
        assert config.auto_test.enabled is False
        assert config.auto_test.max_features == 5
        assert config.auto_test.suite_id == "20-rosa-hcp-provision"

    def test_default_with_base_dir(self):
        config = FeatureGuardConfig.default(Path("/tmp/test"))
        assert config.base_dir == Path("/tmp/test")

    def test_from_file(self, tmp_path):
        settings = {
            "auto_record": False,
            "verbose": True,
            "detection": {"local_since": "HEAD~5"},
            "upstream": {"branch": "main"},
            "advisory": {"enabled": False},
            "auto_test": {"enabled": True, "max_features": 10},
        }
        path = tmp_path / "settings.yml"
        path.write_text(yaml.dump(settings))

        config = FeatureGuardConfig.from_file(path, tmp_path)
        assert config.auto_record is False
        assert config.verbose is True
        assert config.detection.local_since == "HEAD~5"
        assert config.upstream.branch == "main"
        assert config.upstream.repo == "stolostron/cluster-api-provider-aws"
        assert config.advisory.enabled is False
        assert config.auto_test.enabled is True
        assert config.auto_test.max_features == 10

    def test_from_file_partial(self, tmp_path):
        settings = {"auto_test": {"enabled": True}}
        path = tmp_path / "settings.yml"
        path.write_text(yaml.dump(settings))

        config = FeatureGuardConfig.from_file(path, tmp_path)
        assert config.auto_test.enabled is True
        assert config.detection.local_since == "HEAD~1"
        assert config.advisory.enabled is True

    def test_from_file_empty(self, tmp_path):
        path = tmp_path / "settings.yml"
        path.write_text("")

        config = FeatureGuardConfig.from_file(path, tmp_path)
        assert config.auto_record is True
        assert config.auto_test.enabled is False

    def test_load_with_settings_file(self):
        config = FeatureGuardConfig.load(BASE_DIR)
        assert config.base_dir == BASE_DIR
        assert config.auto_record is True

    def test_load_without_settings_file(self, tmp_path):
        config = FeatureGuardConfig.load(tmp_path)
        assert config.base_dir == tmp_path
        assert config.auto_record is True

    def test_settings_path(self):
        path = FeatureGuardConfig.settings_path(BASE_DIR)
        assert path == BASE_DIR / "agents" / "knowledge_base" / "feature_guard_settings.yml"

    def test_real_settings_file_loads(self):
        path = FeatureGuardConfig.settings_path(BASE_DIR)
        assert path.exists()
        config = FeatureGuardConfig.from_file(path, BASE_DIR)
        assert config.upstream.repo == "stolostron/cluster-api-provider-aws"
