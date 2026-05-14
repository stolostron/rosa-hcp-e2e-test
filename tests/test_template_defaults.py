#!/usr/bin/env python3
"""
Tests for Jinja2 template defaults and API versions.

Validates templates in templates/versions/4.20/features/ and 4.21/features/:
    - defaultMachinePoolSpec min <= max and both > 0
    - MachinePool replicas > 0
    - Correct API versions (v1beta1 for MachinePool, v1beta2 for
      ROSAMachinePool/ROSAControlPlane/ROSACluster)
    - rosa-capi-roles-cluster.yaml.j2 is excluded from v1beta2 checks
      because it intentionally uses v1beta1 for some infrastructure resources

Templates are Jinja2 and not valid YAML, so we use regex for extraction.
"""

import re
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_BASE = BASE_DIR / "templates" / "versions"

# Versions with feature templates
TEMPLATE_VERSIONS = ["4.20", "4.21"]


def _collect_j2_templates():
    """Collect all .j2 template files across supported versions."""
    templates = []
    for version in TEMPLATE_VERSIONS:
        features_dir = TEMPLATES_BASE / version / "features"
        if features_dir.exists():
            for f in sorted(features_dir.glob("*.j2")):
                templates.append(f)
    return templates


def _template_id(path):
    """Return a short ID like '4.20/rosa-capi-network-cluster.yaml.j2'."""
    parts = path.parts
    # Find the version part
    idx = parts.index("versions")
    return "/".join(parts[idx + 1:])


ALL_J2_TEMPLATES = _collect_j2_templates()

# rosa-capi-roles-cluster.yaml.j2 intentionally uses v1beta1 for some
# infrastructure resources (ROSAControlPlane, ROSAMachinePool) — exclude it
# from v1beta2 enforcement checks
ROLES_TEMPLATE_NAME = "rosa-capi-roles-cluster.yaml.j2"

J2_TEMPLATES_FOR_V1BETA2 = [
    t for t in ALL_J2_TEMPLATES if t.name != ROLES_TEMPLATE_NAME
]


def _extract_default_values(text, key):
    """Extract all default(N) values for a given key from template text.

    Matches patterns like:
        key: {{ expr | default(N) }}
        key: {{ expr | default('N') }}
    """
    # Match lines like "minReplicas: {{ ... | default(2) }}"
    pattern = rf'{key}:\s*\{{\{{[^}}]*\|\s*default\((\d+)\)\s*\}}\}}'
    return [int(m) for m in re.findall(pattern, text)]


def _extract_replicas_defaults(text):
    """Extract replicas default values from template text.

    Matches patterns like:
        replicas: {{ expr | default(2) }}
    """
    pattern = r'replicas:\s*\{\{[^}]*\|\s*default\((\d+)\)\s*\}\}'
    return [int(m) for m in re.findall(pattern, text)]


# ================================================================
# defaultMachinePoolSpec Constraints
# ================================================================

@pytest.mark.parametrize("template", ALL_J2_TEMPLATES, ids=_template_id)
def test_min_replicas_greater_than_zero(template):
    text = template.read_text()
    mins = _extract_default_values(text, "minReplicas")
    for val in mins:
        assert val > 0, \
            f"{template.name}: minReplicas default({val}) must be > 0"


@pytest.mark.parametrize("template", ALL_J2_TEMPLATES, ids=_template_id)
def test_max_replicas_greater_than_zero(template):
    text = template.read_text()
    maxes = _extract_default_values(text, "maxReplicas")
    for val in maxes:
        assert val > 0, \
            f"{template.name}: maxReplicas default({val}) must be > 0"


@pytest.mark.parametrize("template", ALL_J2_TEMPLATES, ids=_template_id)
def test_min_replicas_lte_max_replicas(template):
    text = template.read_text()
    mins = _extract_default_values(text, "minReplicas")
    maxes = _extract_default_values(text, "maxReplicas")
    if mins and maxes:
        # In a given template, min and max appear in pairs (per defaultMachinePoolSpec)
        # Check that every min is <= every max found in the same template
        for min_val in mins:
            for max_val in maxes:
                assert min_val <= max_val, \
                    f"{template.name}: minReplicas default({min_val}) > " \
                    f"maxReplicas default({max_val})"


# ================================================================
# MachinePool Replicas
# ================================================================

@pytest.mark.parametrize("template", ALL_J2_TEMPLATES, ids=_template_id)
def test_machinepool_replicas_greater_than_zero(template):
    text = template.read_text()
    replicas = _extract_replicas_defaults(text)
    for val in replicas:
        assert val > 0, \
            f"{template.name}: replicas default({val}) must be > 0"


# ================================================================
# API Version: MachinePool uses v1beta1
# ================================================================

@pytest.mark.parametrize("template", ALL_J2_TEMPLATES, ids=_template_id)
def test_machinepool_uses_v1beta1(template):
    text = template.read_text()
    # Find MachinePool resource blocks (kind: MachinePool with cluster.x-k8s.io API)
    # These should use v1beta1
    pattern = r'apiVersion:\s*(cluster\.x-k8s\.io/v\w+)\s*\nkind:\s*MachinePool'
    matches = re.findall(pattern, text)
    for api_version in matches:
        assert api_version == "cluster.x-k8s.io/v1beta1", \
            f"{template.name}: MachinePool should use cluster.x-k8s.io/v1beta1, " \
            f"got {api_version}"


# ================================================================
# API Version: ROSAMachinePool uses v1beta2
# (excluding rosa-capi-roles-cluster.yaml.j2)
# ================================================================

@pytest.mark.parametrize("template", J2_TEMPLATES_FOR_V1BETA2, ids=_template_id)
def test_rosamachinepool_uses_v1beta2(template):
    text = template.read_text()
    pattern = r'apiVersion:\s*(infrastructure\.cluster\.x-k8s\.io/v\w+)\s*\nkind:\s*ROSAMachinePool'
    matches = re.findall(pattern, text)
    for api_version in matches:
        assert api_version == "infrastructure.cluster.x-k8s.io/v1beta2", \
            f"{template.name}: ROSAMachinePool should use v1beta2, got {api_version}"


@pytest.mark.parametrize("template", J2_TEMPLATES_FOR_V1BETA2, ids=_template_id)
def test_rosacontrolplane_uses_v1beta2(template):
    text = template.read_text()
    pattern = r'apiVersion:\s*(controlplane\.cluster\.x-k8s\.io/v\w+)\s*\nkind:\s*ROSAControlPlane'
    matches = re.findall(pattern, text)
    for api_version in matches:
        assert api_version == "controlplane.cluster.x-k8s.io/v1beta2", \
            f"{template.name}: ROSAControlPlane should use v1beta2, got {api_version}"


@pytest.mark.parametrize("template", J2_TEMPLATES_FOR_V1BETA2, ids=_template_id)
def test_rosacluster_uses_v1beta2(template):
    text = template.read_text()
    pattern = r'apiVersion:\s*(infrastructure\.cluster\.x-k8s\.io/v\w+)\s*\nkind:\s*ROSACluster\b'
    matches = re.findall(pattern, text)
    for api_version in matches:
        assert api_version == "infrastructure.cluster.x-k8s.io/v1beta2", \
            f"{template.name}: ROSACluster should use v1beta2, got {api_version}"


# ================================================================
# rosa-capi-roles-cluster.yaml.j2 — Allowed v1beta1 Exceptions
# ================================================================

def test_roles_template_uses_v1beta1_for_some_resources():
    """Verify that rosa-capi-roles-cluster.yaml.j2 uses v1beta1 for some resources.

    This template intentionally uses v1beta1 for ROSARoleConfig, ROSAControlPlane,
    and ROSAMachinePool — confirming it needs to be excluded from v1beta2 checks.
    """
    roles_templates = [
        t for t in ALL_J2_TEMPLATES if t.name == ROLES_TEMPLATE_NAME
    ]
    if not roles_templates:
        pytest.skip("rosa-capi-roles-cluster.yaml.j2 not found")

    text = roles_templates[0].read_text()
    assert "infrastructure.cluster.x-k8s.io/v1beta1" in text, \
        "roles template should contain v1beta1 infrastructure references"
