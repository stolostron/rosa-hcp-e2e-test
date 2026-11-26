#!/usr/bin/env python3
"""Guards that every shipped feature still matches the add-feature-test skill.

`.claude/skills/add-feature-test/` tells an agent which files a feature test has to
touch. scripts/verify_skills_md.py derives what each layer should contain from the
registry and checks the layer contains it; this module runs that over every feature
reachable from ``--feature``, one test per feature, so a failure names the feature
rather than just saying the doc is wrong.

A failure here means one of two things, and both are worth a human look:

* the skill drifted from the code -- someone changed a seam without updating the
  procedure, so the next agent to follow it will write something that does not work;
* that feature is genuinely incomplete -- a layer the procedure requires is missing,
  which usually shows up as a verification WARN or a silent PASS much later.

Resist the urge to add ids to KNOWN_GAPS to turn this green. The point of the gate
is that the list stays short and every entry has a reason someone can act on.
"""

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

# pylint: disable=wrong-import-position
from verify_skills_md import cli_features, verify  # noqa: E402

# Features deliberately not gated, with the reason. Each one is a decision, not a
# convenience: anything added here stops being checked, so say why and when it can go.
KNOWN_GAPS = {}

FEATURES = cli_features()


def test_cli_features_is_not_empty():
    """A registry that parses but yields no features would make every test below vacuous."""
    assert FEATURES, "feature-registry.yml declares no cli_features"


def test_known_gaps_are_real_features():
    """A stale KNOWN_GAPS entry silently excludes nothing and hides that it is stale."""
    unknown = sorted(set(KNOWN_GAPS) - set(FEATURES))
    assert (
        not unknown
    ), f"KNOWN_GAPS names features that are not in cli_features: {unknown}"


@pytest.mark.parametrize("feature_id", FEATURES)
def test_feature_matches_skill(feature_id):
    """Every layer the skill says this feature must touch actually contains it."""
    if feature_id in KNOWN_GAPS:
        pytest.skip(KNOWN_GAPS[feature_id])
    failures, _warnings = verify(feature_id, quiet=True)
    assert not failures, "\n".join(
        [f"'{feature_id}' disagrees with the add-feature-test skill:"]
        + [f"  - {line}" for line in failures]
    )
