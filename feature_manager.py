"""Lightweight feature registry for CLI --feature flag resolution."""

import json
import os
import re

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ScenarioError(Exception):
    """Raised when a scenario cannot be resolved into a runnable configuration."""


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
        self._scenarios = self._registry.get("scenarios", {})
        self._scenario_defaults = self._registry.get("scenario_defaults", {})
        self._supported_versions = self._compat.get("supported_versions", [])

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
        seen = set(resolved)
        queue = list(feature_names)
        while queue:
            feat = queue.pop(0)
            for dep in self._dependencies.get(feat, []):
                if dep not in seen:
                    seen.add(dep)
                    resolved.append(dep)
                    queue.append(dep)
        return resolved

    def validate_features(self, feature_names: List[str], version: str) -> List[str]:
        errors = []
        ocp_ver = _version_tuple(version)

        for name in feature_names:
            name = self.resolve_alias(name)
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
            return json.dumps(value)
        return str(value)

    def resolve_to_extra_vars(self, feature_names: List[str]) -> dict:
        extra_vars = {}
        resolved_names = [self.resolve_alias(n) for n in feature_names]
        extra_vars["requested_features"] = ",".join(resolved_names)

        for name in resolved_names:
            var_name = self._var_map.get(name, name)
            feat = self._features.get(name, {})
            feat_type = feat.get("type", "boolean")

            if feat_type == "boolean":
                extra_vars[var_name] = "true"
            else:
                ci_default = feat.get("ci_default")
                default = feat.get("default")
                effective = ci_default if ci_default is not None else default
                if effective is not None and effective not in ("", {}, []):
                    extra_vars[var_name] = self._serialize_value(effective, feat_type)
                extra_vars[f"feature_{name}_enabled"] = "true"

        return extra_vars

    def check_required_inputs(self, feature_names: List[str], extra_vars: dict) -> List[str]:
        """Report features whose user-supplied inputs are missing from extra_vars.

        A feature declares what it needs in one of three ways, most specific first:
          required_vars_any_of: list of groups; at least one group must be fully set
          required_vars:        every listed var must be set
          (neither)            falls back to the feature's var_map entry
        """
        warnings = []
        for name in feature_names:
            feat = self._features.get(name, {})
            if not feat.get("requires_input", False):
                continue

            any_of = feat.get("required_vars_any_of")
            if any_of:
                if not any(all(v in extra_vars for v in group) for group in any_of):
                    options = " OR ".join(
                        " and ".join(f"-e {v}=<value>" for v in group) for group in any_of
                    )
                    warnings.append(
                        f"Feature '{name}' requires {options}. "
                        f"No test default is available."
                    )
                continue

            required = feat.get("required_vars") or [self._var_map.get(name, name)]
            missing = [v for v in required if v not in extra_vars]
            if missing:
                warnings.append(
                    f"Feature '{name}' requires a value via "
                    f"{' and '.join(f'-e {v}=<value>' for v in missing)}. "
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

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------

    def _scenario_setting(self, name: str, key: str, default=None):
        """Read a scenario key, falling back to scenario_defaults."""
        scenario = self._scenarios.get(name, {})
        if key in scenario:
            return scenario[key]
        return self._scenario_defaults.get(key, default)

    def scenario_features(self, name: str) -> List[str]:
        """Resolve a scenario's feature list: extends + feature_group + features."""
        return self._scenario_features(name, set())

    def _scenario_features(self, name: str, seen: set) -> List[str]:
        if name in seen:
            raise ScenarioError(f"Circular 'extends' chain involving scenario '{name}'")
        seen.add(name)

        scenario = self._scenarios.get(name)
        if scenario is None:
            raise ScenarioError(
                f"Unknown scenario: '{name}'. Available: {', '.join(sorted(self._scenarios))}"
            )

        features: List[str] = []
        parent = scenario.get("extends")
        if parent:
            features.extend(self._scenario_features(parent, seen))

        group_name = scenario.get("feature_group")
        if group_name:
            group = self.resolve_group(group_name)
            if group is None:
                raise ScenarioError(
                    f"Scenario '{name}' references unknown feature group '{group_name}'"
                )
            features.extend(group)

        features.extend(scenario.get("features", []))
        return list(dict.fromkeys(features))

    def scenario_versions(self, name: str) -> List[str]:
        """Supported versions this scenario can run on, computed from its features.

        A scenario is valid on a version when every one of its features is
        available there. Nothing is hand-maintained: adding a version to
        supported_versions makes every compatible scenario runnable on it.
        """
        features = self.scenario_features(name)
        valid = []
        for version in self._supported_versions:
            if not self._features_available_at(features, version):
                continue
            valid.append(version)
        return valid

    def _features_available_at(self, features: List[str], version: str) -> bool:
        ocp_ver = _version_tuple(version)
        for feat_id in features:
            avail = self._feature_availability.get(feat_id, {})
            min_ver = avail.get("min_version") or self._features.get(feat_id, {}).get("min_version")
            max_ver = avail.get("max_version")
            if min_ver and ocp_ver < _version_tuple(min_ver):
                return False
            if max_ver and ocp_ver > _version_tuple(max_ver):
                return False
        return True

    @staticmethod
    def _expand_env(value) -> Tuple[object, List[str]]:
        """Substitute ${ENV_VAR} references. Returns (value, missing_env_names)."""
        if not isinstance(value, str):
            return value, []
        missing = []

        def _sub(match):
            env_name = match.group(1)
            env_value = os.environ.get(env_name)
            if env_value is None or env_value == "":
                missing.append(env_name)
                return match.group(0)
            return env_value

        expanded = _ENV_REF.sub(_sub, value)
        return expanded, missing

    def resolve_scenario(self, name: str, version: Optional[str] = None) -> dict:
        """Resolve a scenario into everything needed to run it.

        Returns a dict with: name, description, features, extra_vars, stages,
        version, estimated_minutes.

        extra_vars precedence (lowest to highest):
            feature defaults -> scenario extra_vars -> version_overrides
        The caller layers CLI -e on top, which always wins.
        """
        if name not in self._scenarios:
            raise ScenarioError(
                f"Unknown scenario: '{name}'. Available: {', '.join(sorted(self._scenarios))}"
            )

        features = self.scenario_features(name)

        if version:
            applicable = self.scenario_versions(name)
            if version not in applicable:
                blockers = [
                    f"{f} (needs >= {self._feature_availability.get(f, {}).get('min_version')})"
                    for f in features
                    if not self._features_available_at([f], version)
                ]
                raise ScenarioError(
                    f"Scenario '{name}' is not available on OpenShift {version}: "
                    f"{'; '.join(blockers)}. "
                    f"Runnable on: {', '.join(applicable) or '(no supported version)'}"
                )

        extra_vars: Dict[str, object] = {}
        missing_env: Dict[str, List[str]] = {}

        for var_name, raw in (self._scenario_setting(name, "extra_vars", {}) or {}).items():
            expanded, missing = self._expand_env(raw)
            if missing:
                missing_env[var_name] = missing
            else:
                extra_vars[var_name] = expanded

        if missing_env:
            lines = [
                f"  {var} needs ${{{'}, ${'.join(envs)}}}"
                for var, envs in sorted(missing_env.items())
            ]
            raise ScenarioError(
                f"Scenario '{name}' needs environment values that are not set:\n"
                + "\n".join(lines)
                + "\nExport them (or configure them as Jenkins credentials) and re-run."
            )

        if version:
            overrides = self._scenario_setting(name, "version_overrides", {}) or {}
            extra_vars.update(overrides.get(version, {}))

        return {
            "name": name,
            "description": self._scenarios[name].get("description", ""),
            "features": features,
            "extra_vars": extra_vars,
            "stages": self.scenario_stages(name),
            "version": version,
            "estimated_minutes": self._scenarios[name].get("estimated_minutes"),
        }

    def scenario_stages(self, name: str) -> List[dict]:
        """Normalize a scenario's stage list to [{suite, always}, ...]."""
        stages = []
        for entry in self._scenario_setting(name, "stages", []) or []:
            if isinstance(entry, str):
                stages.append({"suite": entry, "always": False})
            else:
                stages.append({
                    "suite": entry["suite"],
                    "always": bool(entry.get("always", False)),
                })
        return stages

    def list_scenarios(self) -> List[dict]:
        results = []
        for name in sorted(self._scenarios):
            results.append({
                "name": name,
                "description": self._scenarios[name].get("description", ""),
                "features": self.scenario_features(name),
                "versions": self.scenario_versions(name),
                "stages": [s["suite"] for s in self.scenario_stages(name)],
                "estimated_minutes": self._scenarios[name].get("estimated_minutes"),
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
