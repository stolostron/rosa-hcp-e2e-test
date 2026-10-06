#!/usr/bin/env python3
"""The default_autoscaling feature must be observable in the rendered template.

Regression guard. The disabled branch previously derived maxReplicas from the AZ
count (length * 2), which at the default 2 AZs produced exactly the same 2/4 as
the enabled branch — so enabling the feature changed nothing, verification
asserted values that occur either way, and the test could not fail. It also
disagreed with verify_feature_flags.yml, which expects max == 2 when disabled.
"""

import re
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

BASE_DIR = Path(__file__).parent.parent

# 4.20 is deliberately out of scope. All four of its templates still render a
# fixed 2/2 and ignore default_autoscaling, so verification — which expects
# max == 4 when the feature is on — fails on that version. That is a known,
# accepted gap, not an oversight; the exclusion is explicit here so the next
# reader does not "fix" the list and get a red suite.
UNCOVERED_VERSIONS = {"4.18", "4.19", "4.20"}

COVERED_VERSIONS = sorted(
    v for v in (
        yaml.safe_load(
            (BASE_DIR / "templates" / "schemas" / "version-compatibility.yml").read_text()
        )["supported_versions"]
    )
    if v not in UNCOVERED_VERSIONS
)

TEMPLATES = [
    p for v in COVERED_VERSIONS
    for p in (BASE_DIR / "templates" / "versions" / v / "features").glob("rosa-*.yaml.j2")
    if "defaultMachinePoolSpec" in p.read_text()
]


def _render(path, enabled, azs=2):
    block = re.search(r"^  defaultMachinePoolSpec:.*?^\{% endif %\}",
                      path.read_text(), re.S | re.M)
    assert block, f"{path}: defaultMachinePoolSpec block not found"
    env = Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "1", "yes")
    out = env.from_string(block.group(0)).render(
        machine_pool={},
        availability_zones_list=[f"us-west-2{c}" for c in "abcdef"[:azs]],
        default_autoscaling=enabled,
    )
    v = dict(re.findall(r"(minReplicas|maxReplicas): (\d+)", out))
    return int(v["minReplicas"]), int(v["maxReplicas"])


def test_the_glob_covers_every_in_scope_version():
    """A truthiness check would still pass if a whole version went missing."""
    found = {p.parent.parent.name for p in TEMPLATES}
    assert found == set(COVERED_VERSIONS), (
        f"expected templates for {COVERED_VERSIONS}, found {sorted(found)}"
    )
    assert len(TEMPLATES) >= len(COVERED_VERSIONS)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_enabled_and_disabled_differ(path):
    """The whole point: the two branches must be distinguishable."""
    assert _render(path, True) != _render(path, False), (
        f"{path}: enabling default_autoscaling changes nothing, so the feature "
        f"cannot be verified"
    )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_enabled_autoscales(path):
    mn, mx = _render(path, True)
    assert mx > mn, f"{path}: enabled branch must have headroom, got {mn}/{mx}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_disabled_is_fixed_size(path):
    """No replicas field exists, so 'not autoscaling' means min == max."""
    mn, mx = _render(path, False)
    assert mn == mx, f"{path}: disabled branch must be fixed size, got {mn}/{mx}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_matches_what_verification_expects(path):
    """verify_feature_flags.yml: expected_min=2, expected_max = 4 if on else 2."""
    assert _render(path, True) == (2, 4)
    assert _render(path, False) == (2, 2)
