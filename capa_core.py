"""
Shared core logic for CAPA CLI and backend.

This module is the single source of truth for:
- FeatureRegistry: loading and querying the feature registry
- ClusterAutomationSpec: parsing and validating spec YAML
- validate_feature_value: type-checking feature values
- build_json_merge_patch: constructing K8s merge patches
- resolve_spec_to_plan: converting specs into execution plans
"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any


# ============================================================================
# Feature Registry
# ============================================================================
class FeatureRegistry:
    """Loads and queries the feature registry with mtime-based cache."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._registry_path = base_dir / "schemas" / "feature-registry.yml"
        self._data = None
        self._features = {}
        self._mtime = 0
        self._load()

    def _load(self):
        """Load or reload registry if file has changed."""
        try:
            mtime = os.path.getmtime(self._registry_path)
        except OSError:
            mtime = 0
        if self._data is not None and self._mtime == mtime:
            return
        try:
            with open(self._registry_path) as f:
                self._data = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Feature registry not found: {self._registry_path}\n"
                f"Expected at: schemas/feature-registry.yml"
            )
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in feature registry: {e}")
        self._mtime = mtime
        self._features = {}
        for suite in self._data.get("suites", []):
            for feat in suite.get("features", []):
                feat["_suite"] = suite["id"]
                self._features[feat["id"]] = feat

    def refresh(self):
        """Re-check file mtime and reload if changed."""
        self._load()

    @property
    def var_map(self) -> Dict[str, str]:
        self._load()
        return self._data.get("var_map", {})

    @property
    def dependencies(self) -> Dict[str, List[str]]:
        self._load()
        return self._data.get("dependencies", {})

    @property
    def sequences(self) -> Dict[str, Any]:
        self._load()
        return self._data.get("sequences", {})

    @property
    def suites(self) -> List[Dict]:
        self._load()
        return self._data.get("suites", [])

    @property
    def raw_data(self) -> Dict:
        """Return the full registry YAML data (for API responses)."""
        self._load()
        return self._data

    def get_feature(self, feature_id: str) -> Optional[Dict]:
        self._load()
        return self._features.get(feature_id)

    def all_features(self) -> Dict[str, Dict]:
        self._load()
        return self._features

    def get_deps(self, feature_id: str) -> List[str]:
        return self.dependencies.get(feature_id, [])

    def resolve_var(self, feature_id: str) -> str:
        """Map feature ID to playbook extra_var name."""
        return self.var_map.get(feature_id, feature_id)


# ============================================================================
# Cluster Spec
# ============================================================================
class ClusterAutomationSpec:
    """Parses and validates a ClusterAutomationSpec YAML."""

    def __init__(self, data: Dict, overrides: Optional[Dict] = None,
                 base_dir: Optional[Path] = None):
        if data.get("apiVersion") != "capa-automation/v1":
            raise ValueError(f"Unsupported apiVersion: {data.get('apiVersion')}")
        if data.get("kind") != "ClusterAutomationSpec":
            raise ValueError(f"Unsupported kind: {data.get('kind')}")

        self.metadata = data.get("metadata", {})
        self.spec = data.get("spec", {})
        self.name = self.metadata.get("name", "unnamed")

        # Profile inheritance: merge parent profile underneath
        inherits = self.metadata.get("inherits")
        if inherits and base_dir:
            self._apply_inheritance(inherits, base_dir)

        # Apply overrides (from CLI -e flags or API overrides)
        if overrides:
            for k, v in overrides.items():
                if k in ("cluster", "namespace", "version", "region", "channel",
                          "name_prefix", "action"):
                    self.spec[k] = v
                elif k.startswith("feature."):
                    feat_key = k.split(".", 1)[1]
                    self.spec.setdefault("features", {})[feat_key] = v
                else:
                    self.spec.setdefault("features", {})[k] = v

    @property
    def action(self) -> str:
        return self.spec.get("action", "create")

    @property
    def cluster(self) -> str:
        return self.spec.get("cluster", "")

    @property
    def namespace(self) -> str:
        return self.spec.get("namespace", "ns-rosa-hcp")

    @property
    def version(self) -> str:
        return self.spec.get("version", "")

    @property
    def region(self) -> str:
        return self.spec.get("region", "us-west-2")

    @property
    def channel(self) -> str:
        return self.spec.get("channel", "stable")

    @property
    def name_prefix(self) -> str:
        return self.spec.get("name_prefix", "")

    @property
    def features(self) -> Dict[str, Any]:
        return self.spec.get("features", {})

    @property
    def actions(self) -> List[Dict]:
        return self.spec.get("actions", [])

    @property
    def profile(self) -> str:
        return self.metadata.get("profile", "")

    def _apply_inheritance(self, parent_name: str, base_dir: Path,
                           _seen: Optional[set] = None):
        """Merge a parent profile's spec underneath this spec (child wins).

        Supports multi-level inheritance (A inherits B inherits C).
        Circular inheritance is detected and raises ValueError.
        """
        if _seen is None:
            _seen = set()
        if parent_name in _seen:
            raise ValueError(f"Circular inheritance detected: {parent_name}")
        _seen.add(parent_name)

        parent_path = None
        for candidate in (base_dir / "specs").rglob(f"{parent_name}.yml"):
            parent_path = candidate
            break
        if not parent_path or not parent_path.exists():
            raise ValueError(f"Inherited profile not found: {parent_name}")

        with open(parent_path) as f:
            parent_data = yaml.safe_load(f)

        # Recurse: if parent also inherits, resolve that first
        grandparent = parent_data.get("metadata", {}).get("inherits")
        if grandparent:
            # Build a temporary spec to resolve the parent's full inheritance chain
            parent_obj = ClusterAutomationSpec.__new__(ClusterAutomationSpec)
            parent_obj.metadata = parent_data.get("metadata", {})
            parent_obj.spec = parent_data.get("spec", {})
            parent_obj.name = parent_obj.metadata.get("name", "unnamed")
            parent_obj._apply_inheritance(grandparent, base_dir, _seen)
            parent_data["spec"] = parent_obj.spec

        parent_spec = parent_data.get("spec", {})

        # Merge parent features under child features (child wins)
        parent_features = parent_spec.get("features", {})
        child_features = self.spec.get("features", {})
        merged_features = {**parent_features, **child_features}
        if merged_features:
            self.spec["features"] = merged_features

        # Merge parent top-level spec fields (child wins)
        for key in ("version", "region", "channel", "namespace"):
            if key not in self.spec and key in parent_spec:
                self.spec[key] = parent_spec[key]


# ============================================================================
# Validation
# ============================================================================

# Cluster name: lowercase alphanumeric + hyphens, 1-54 chars (ROSA HCP limit)
_CLUSTER_NAME_RE = re.compile(r'^[a-z][a-z0-9-]{0,53}$')


def validate_cluster_name(name: str) -> Optional[str]:
    """Validate cluster name format. Returns error message or None if valid."""
    if not name:
        return "Cluster name is required"
    if len(name) > 54:
        return f"Cluster name must be 54 characters or fewer (got {len(name)})"
    if not _CLUSTER_NAME_RE.match(name):
        return "Cluster name must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens"
    return None


def validate_feature_value(feature: dict, value) -> Optional[str]:
    """Validate target_value matches the feature's declared type. Returns error or None."""
    feat_type = feature.get("type", "string")
    feat_id = feature["id"]

    if feat_type == "boolean":
        if not isinstance(value, bool):
            return f"Feature '{feat_id}' expects boolean, got {type(value).__name__}"
    elif feat_type == "select":
        options = feature.get("options", [])
        if options and str(value) not in [str(o) for o in options]:
            return f"Feature '{feat_id}' expects one of {options}, got: {value}"
    elif feat_type == "number":
        if not isinstance(value, (int, float)):
            return f"Feature '{feat_id}' expects number, got {type(value).__name__}"
    elif feat_type == "string":
        max_len = feature.get("max_length")
        if max_len and len(str(value)) > max_len:
            return f"Feature '{feat_id}' max length is {max_len}, got {len(str(value))} chars"
    elif feat_type == "version":
        if not isinstance(value, str) or not re.match(r'^\d+\.\d+\.\d+$', str(value)):
            return f"Feature '{feat_id}' expects semver (e.g. 4.20.11), got: {value}"
    elif feat_type == "key_value":
        if not isinstance(value, dict):
            return f"Feature '{feat_id}' expects key-value dict, got {type(value).__name__}"
    elif feat_type == "list":
        if not isinstance(value, list):
            return f"Feature '{feat_id}' expects list, got {type(value).__name__}"
    elif feat_type == "range":
        if isinstance(value, dict):
            if "min" not in value or "max" not in value:
                return f"Feature '{feat_id}' range expects {{min, max}}, got: {value}"
            elif value["min"] > value["max"]:
                return f"Feature '{feat_id}' range: min ({value['min']}) > max ({value['max']})"
        else:
            return f"Feature '{feat_id}' expects range {{min, max}}, got {type(value).__name__}"
    return None


# ============================================================================
# JSON Merge Patch
# ============================================================================
def build_json_merge_patch(k8s_field: str, value) -> dict:
    """Build a JSON merge patch object from a k8s_field path (e.g. '.spec.channelGroup')."""
    field_parts = [p for p in k8s_field.split(".") if p]
    patch_obj = {}
    current = patch_obj
    for i, part in enumerate(field_parts):
        if i == len(field_parts) - 1:
            current[part] = value
        else:
            current[part] = {}
            current = current[part]
    return patch_obj


# ============================================================================
# Spec-to-Plan Resolution
# ============================================================================
def resolve_spec_to_plan(registry: FeatureRegistry,
                         spec: ClusterAutomationSpec) -> List[Dict]:
    """Resolve a ClusterAutomationSpec into an ordered execution plan."""
    action = spec.action

    if action == "create":
        return _plan_create(registry, spec)
    elif action == "upgrade":
        return _plan_upgrade(registry, spec)
    elif action == "apply":
        return _plan_apply(registry, spec)
    elif action == "delete":
        return _plan_delete(registry, spec)
    elif action == "test":
        return _plan_test(registry, spec)
    else:
        raise ValueError(f"Unknown action: {action}")


def _plan_create(registry: FeatureRegistry, spec: ClusterAutomationSpec) -> List[Dict]:
    """Plan: resolve features to playbook extra_vars, run provision playbook."""
    extra_vars = {
        "name_prefix": spec.name_prefix,
        "capi_namespace": spec.namespace,
        "aws_region": spec.region,
        "channel_group": spec.channel,
    }
    if spec.version:
        extra_vars["openshift_version"] = spec.version

    for feat_id, value in spec.features.items():
        var_name = registry.resolve_var(feat_id)
        extra_vars[var_name] = value

    provision_seq = registry.sequences.get("provision", {})
    playbook = provision_seq.get("playbook", "playbooks/create_rosa_hcp_cluster.yml")

    return [{
        "step": 1,
        "type": "playbook",
        "name": f"Create cluster {spec.name_prefix or 'new'}-rosa-hcp",
        "playbook": playbook,
        "extra_vars": extra_vars,
        "features_used": list(spec.features.keys()),
    }]


def _plan_upgrade(registry: FeatureRegistry, spec: ClusterAutomationSpec) -> List[Dict]:
    """Plan: upgrade control plane then machine pool (auto-sequenced)."""
    if not spec.cluster:
        raise ValueError("upgrade requires --cluster")
    if not spec.version:
        raise ValueError("upgrade requires --version")

    cp_feature = registry.get_feature("control_plane_upgrade")
    mp_feature = registry.get_feature("machine_pool_upgrade")

    return [
        {
            "step": 1,
            "type": "playbook",
            "name": f"Upgrade control plane to {spec.version}",
            "playbook": cp_feature["playbook"],
            "extra_vars": {
                "cluster_name": spec.cluster,
                "capi_namespace": spec.namespace,
                "requested_version": spec.version,
            },
            "wait": True,
            "wait_resource": cp_feature.get("wait_resource"),
            "wait_field": cp_feature.get("wait_field"),
            "wait_value": cp_feature.get("wait_value"),
            "wait_timeout": cp_feature.get("wait_timeout", 3600),
            "feature": "control_plane_upgrade",
        },
        {
            "step": 2,
            "type": "playbook",
            "name": f"Upgrade machine pool to {spec.version}",
            "playbook": mp_feature["playbook"],
            "extra_vars": {
                "cluster_name": spec.cluster,
                "capi_namespace": spec.namespace,
                "requested_version": spec.version,
            },
            "wait": True,
            "wait_resource": mp_feature.get("wait_resource"),
            "wait_field": mp_feature.get("wait_field"),
            "wait_value": mp_feature.get("wait_value"),
            "wait_timeout": mp_feature.get("wait_timeout", 3600),
            "feature": "machine_pool_upgrade",
            "depends_on": "control_plane_upgrade",
        },
    ]


def _plan_apply(registry: FeatureRegistry, spec: ClusterAutomationSpec) -> List[Dict]:
    """Plan: execute explicit action list with dependency ordering."""
    if not spec.cluster:
        raise ValueError("apply requires --cluster")

    raw_actions = spec.actions
    if not raw_actions:
        raise ValueError("apply requires actions list")

    steps = []
    for i, action in enumerate(raw_actions):
        feat_id = action["feature"]
        value = action.get("value")
        wait = action.get("wait", True)
        feature = registry.get_feature(feat_id)

        if not feature:
            raise ValueError(f"Unknown feature: {feat_id}")

        deps = registry.get_deps(feat_id)
        depends_on = deps[0] if deps else None

        if feature.get("playbook"):
            extra_vars = {
                "cluster_name": spec.cluster,
                "capi_namespace": spec.namespace,
            }
            if value:
                if feat_id in ("control_plane_upgrade", "machine_pool_upgrade"):
                    extra_vars["requested_version"] = str(value)

            steps.append({
                "step": i + 1,
                "type": "playbook",
                "name": f"{feature['name']}",
                "playbook": feature["playbook"],
                "extra_vars": extra_vars,
                "wait": wait,
                "wait_resource": feature.get("wait_resource"),
                "wait_field": feature.get("wait_field"),
                "wait_value": feature.get("wait_value"),
                "wait_timeout": feature.get("wait_timeout", 600),
                "feature": feat_id,
                "depends_on": depends_on,
            })
        else:
            steps.append({
                "step": i + 1,
                "type": "patch",
                "name": f"{feature['name']} = {value}",
                "resource": feature.get("resource", ""),
                "k8s_field": feature.get("k8s_field", ""),
                "value": value,
                "cluster": spec.cluster,
                "namespace": spec.namespace,
                "wait": wait,
                "feature": feat_id,
                "depends_on": depends_on,
            })

    return steps


def _plan_delete(registry: FeatureRegistry, spec: ClusterAutomationSpec) -> List[Dict]:
    """Plan: delete cluster."""
    if not spec.cluster:
        raise ValueError("delete requires --cluster")

    delete_seq = registry.sequences.get("delete", {})
    playbook = delete_seq.get("playbook", "playbooks/delete_rosa_hcp_cluster.yml")

    return [{
        "step": 1,
        "type": "playbook",
        "name": f"Delete cluster {spec.cluster}",
        "playbook": playbook,
        "extra_vars": {
            "cluster_name": spec.cluster,
            "capi_namespace": spec.namespace,
        },
        "wait": True,
        "feature": "cluster_delete",
    }]


def _plan_test(registry: FeatureRegistry, spec: ClusterAutomationSpec) -> List[Dict]:
    """Plan: run test suites against cluster."""
    suites = spec.spec.get("test_suites", [])
    if not suites:
        suites = [s["id"] for s in registry.suites if s["phase"] == "Day2"]

    steps = []
    for i, suite_id in enumerate(suites):
        steps.append({
            "step": i + 1,
            "type": "test_suite",
            "name": f"Test suite: {suite_id}",
            "suite_id": suite_id,
            "cluster": spec.cluster,
            "namespace": spec.namespace,
        })
    return steps
