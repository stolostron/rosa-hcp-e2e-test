#!/usr/bin/env python3
"""
Tests for standalone mode conditionals.

Validates that ManagedCluster resources and OCM-specific tasks are properly
guarded with deployment_mode conditionals so they are skipped in standalone mode.
"""

import re
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent

MANAGED_CLUSTER_TEMPLATES = [
    "templates/versions/4.20/features/rosa-controlplane-only.yaml.j2",
    "templates/versions/4.20/features/rosa-combined-automation.yaml.j2",
    "templates/versions/4.20/features/rosa-capi-network-cluster.yaml.j2",
    "templates/versions/4.20/features/rosa-log-forwarding.yaml.j2",
    "templates/versions/4.21/features/rosa-controlplane-only.yaml.j2",
    "templates/versions/4.21/features/rosa-combined-automation.yaml.j2",
    "templates/versions/4.21/features/rosa-capi-network-cluster.yaml.j2",
    "templates/versions/4.22/features/rosa-controlplane-only.yaml.j2",
    "templates/versions/4.22/features/rosa-combined-automation.yaml.j2",
]


# ================================================================
# ManagedCluster Conditionals in Templates
# ================================================================

@pytest.mark.parametrize("template_path", MANAGED_CLUSTER_TEMPLATES)
def test_managed_cluster_wrapped_in_conditional(template_path):
    """ManagedCluster resource must be inside a deployment_mode conditional."""
    text = (BASE_DIR / template_path).read_text()
    assert "kind: ManagedCluster" in text, \
        f"{template_path}: expected ManagedCluster resource"
    mc_pos = text.index("kind: ManagedCluster")
    before_mc = text[:mc_pos]
    assert "{% if deployment_mode != 'standalone' %}" in before_mc, \
        f"{template_path}: ManagedCluster not wrapped in deployment_mode conditional"


@pytest.mark.parametrize("template_path", MANAGED_CLUSTER_TEMPLATES)
def test_cluster_resource_outside_conditional(template_path):
    """The Cluster resource (kind: Cluster) must NOT be inside the
    ManagedCluster conditional block."""
    text = (BASE_DIR / template_path).read_text()
    endif_match = re.search(r'\{%\s*endif\s*%\}', text)
    assert endif_match, f"{template_path}: missing endif"
    after_endif = text[endif_match.end():]
    assert "kind: Cluster" in after_endif, \
        f"{template_path}: Cluster resource should be after the endif block"


@pytest.mark.parametrize("template_path", MANAGED_CLUSTER_TEMPLATES)
def test_yaml_separator_inside_conditional(template_path):
    """The --- separator between ManagedCluster and Cluster should be
    inside the conditional block (before endif)."""
    text = (BASE_DIR / template_path).read_text()
    endif_match = re.search(r'\{%\s*endif\s*%\}', text)
    assert endif_match, f"{template_path}: missing endif"
    conditional_start = text.index("{% if deployment_mode != 'standalone' %}")
    block = text[conditional_start:endif_match.end()]
    assert "\n---\n" in block, \
        f"{template_path}: --- separator should be inside the conditional block"


# ================================================================
# OCM Task Guards in configure-capa-environment Role
# ================================================================

CONFIGURE_ROLE_MAIN = "roles/configure-capa-environment/tasks/main.yml"

OCM_GUARDED_TASKS = [
    "enable_capi_capa.yml",
    "set_registration_configuration.yml",
    "set_cluster_role_binding.yml",
]


@pytest.mark.parametrize("task_file", OCM_GUARDED_TASKS)
def test_ocm_task_guarded_in_configure_role(task_file):
    """OCM-specific include_tasks must have deployment_mode guard."""
    text = (BASE_DIR / CONFIGURE_ROLE_MAIN).read_text()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if task_file in line:
            context = "\n".join(lines[max(0, i-3):i+3])
            assert "deployment_mode != 'standalone'" in context, (
                f"{CONFIGURE_ROLE_MAIN}: include of {task_file} (line {i+1}) "
                f"missing deployment_mode guard"
            )
            return
    pytest.fail(f"{CONFIGURE_ROLE_MAIN}: {task_file} not found")


# ================================================================
# ManagedCluster Deletion Guard
# ================================================================

def test_managed_cluster_deletion_guarded():
    """The ManagedCluster deletion task must be guarded by deployment_mode."""
    path = BASE_DIR / "tasks" / "delete_rosa_hcp_resources.yml"
    text = path.read_text()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "managedcluster" in line.lower() and "delete" in line.lower():
            context = "\n".join(lines[max(0, i-5):i+10])
            assert "deployment_mode != 'standalone'" in context, (
                f"delete_rosa_hcp_resources.yml: ManagedCluster deletion "
                f"(line {i+1}) missing deployment_mode guard"
            )
            return
    pytest.fail("delete_rosa_hcp_resources.yml: ManagedCluster deletion task not found")
