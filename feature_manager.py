"""Lightweight feature registry for CLI --feature flag resolution."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional


def _version_tuple(ver: str) -> tuple:
    """Convert '4.21' to (4, 21) for proper numeric comparison."""
    parts = ver.split(".")
    return tuple(int(p) for p in parts[:2])


class FeatureManager:
    """Loads the feature registry and resolves --feature flags to Ansible extra_vars."""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self._registry = self._load_yaml(base_dir / "templates" / "schemas" / "feature-registry.yml")
        self._compat = self._load_yaml(base_dir / "templates" / "schemas" / "version-compatibility.yml")

        self._var_map = self._registry.get("var_map", {})
        self._cli_aliases = self._registry.get("cli_aliases", {})
        self._cli_features = set(self._registry.get("cli_features", []))
        self._dependencies = self._registry.get("dependencies", {})
        self._mutual_exclusions = self._registry.get("mutual_exclusions", [])
        self._feature_availability = self._compat.get("feature_availability", {})

        self._feature_groups = self._registry.get("feature_groups", {})

        self._features: Dict[str, dict] = {}
        for suite in self._registry.get("suites", []):
            for feat in suite.get("features", []):
                feat_copy = dict(feat)
                feat_copy["suite_id"] = suite["id"]
                feat_copy["suite_name"] = suite["name"]
                feat_copy["phase"] = suite.get("phase", "Day1")
                self._features[feat["id"]] = feat_copy

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {path}")
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid YAML in {path}")
        return data

    def resolve_alias(self, name: str) -> str:
        return self._cli_aliases.get(name, name)

    def get_feature(self, feature_id: str) -> Optional[dict]:
        return self._features.get(feature_id)

    def auto_resolve_deps(self, feature_names: List[str]) -> List[str]:
        resolved = list(feature_names)
        added = True
        while added:
            added = False
            for feat in list(resolved):
                for dep in self._dependencies.get(feat, []):
                    if dep not in resolved:
                        resolved.append(dep)
                        added = True
        return resolved

    def validate_features(self, feature_names: List[str], version: str) -> List[str]:
        errors = []
        ocp_ver = _version_tuple(version)

        for name in feature_names:
            if name not in self._features:
                available = ", ".join(sorted(self._cli_features))
                errors.append(f"Unknown feature: '{name}'. Available: {available}")
                continue

            if name not in self._cli_features:
                errors.append(f"Feature '{name}' is not available as a CLI flag")
                continue

            avail = self._feature_availability.get(name)
            if avail:
                min_ver = avail.get("min_version")
                max_ver = avail.get("max_version")
                if min_ver and ocp_ver < _version_tuple(min_ver):
                    errors.append(
                        f"Feature '{name}' requires OpenShift >= {min_ver}, "
                        f"but version is {version}"
                    )
                if max_ver and ocp_ver > _version_tuple(max_ver):
                    errors.append(
                        f"Feature '{name}' is deprecated after OpenShift {max_ver}"
                    )

        for exclusion_group in self._mutual_exclusions:
            present = [f for f in feature_names if f in exclusion_group]
            if len(present) > 1:
                errors.append(
                    f"Features {present} are mutually exclusive"
                )

        return errors

    @staticmethod
    def _serialize_value(value, feat_type: str) -> str:
        if feat_type in ("key_value", "list", "range"):
            import json
            return json.dumps(value)
        return str(value)

    def resolve_to_extra_vars(self, feature_names: List[str]) -> dict:
        extra_vars = {}
        extra_vars["requested_features"] = ",".join(feature_names)

        for name in feature_names:
            var_name = self._var_map.get(name, name)
            feat = self._features.get(name, {})
            feat_type = feat.get("type", "boolean")

            if feat_type == "boolean":
                extra_vars[var_name] = "true"
            else:
                ci_default = feat.get("ci_default")
                default = feat.get("default")
                effective = ci_default if ci_default is not None else default
                if effective is not None and effective != "" and effective != {} and effective != []:
                    extra_vars[var_name] = self._serialize_value(effective, feat_type)
                extra_vars[f"feature_{name}_enabled"] = "true"

        return extra_vars

    def check_required_inputs(self, feature_names: List[str], extra_vars: dict) -> List[str]:
        warnings = []
        for name in feature_names:
            feat = self._features.get(name, {})
            if feat.get("requires_input", False):
                var_name = self._var_map.get(name, name)
                if var_name not in extra_vars:
                    warnings.append(
                        f"Feature '{name}' requires a value via -e {var_name}=<value>. "
                        f"No test default is available."
                    )
        return warnings

    def resolve_group(self, group_name: str) -> Optional[List[str]]:
        group = self._feature_groups.get(group_name)
        if group is None:
            return None
        return list(group.get("features", []))

    def list_groups(self) -> List[dict]:
        results = []
        for name, group in self._feature_groups.items():
            results.append({
                "name": name,
                "description": group.get("description", ""),
                "features": group.get("features", []),
            })
        return results

    def list_features(self, version: Optional[str] = None) -> List[dict]:
        results = []
        ocp_ver = None
        if version:
            ocp_ver = _version_tuple(version)

        reverse_aliases = {}
        for alias, feat_id in self._cli_aliases.items():
            if feat_id not in reverse_aliases:
                reverse_aliases[feat_id] = alias

        for feat_id in sorted(self._cli_features):
            feat = self._features.get(feat_id)
            if not feat:
                continue

            avail = self._feature_availability.get(feat_id, {})
            min_ver = avail.get("min_version") or feat.get("min_version")

            if ocp_ver and min_ver and ocp_ver < _version_tuple(min_ver):
                continue

            max_ver = avail.get("max_version")
            if ocp_ver and max_ver and ocp_ver > _version_tuple(max_ver):
                continue

            results.append({
                "id": feat_id,
                "name": feat["name"],
                "description": feat["description"],
                "type": feat.get("type", "boolean"),
                "default": feat.get("default"),
                "phase": feat.get("phase", "Day1"),
                "suite": feat.get("suite_name", ""),
                "cli_alias": reverse_aliases.get(feat_id, ""),
                "min_version": min_ver,
                "var_name": self._var_map.get(feat_id, feat_id),
            })

        return results
