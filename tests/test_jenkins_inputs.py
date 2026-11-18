#!/usr/bin/env python3
"""Tests for Jenkins per-run input parameterization."""

from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
JENKINSFILE = BASE_DIR / "Jenkinsfile"


def _jenkinsfile() -> str:
    return JENKINSFILE.read_text()


def test_jenkins_exposes_region_and_namespace_parameters():
    text = _jenkinsfile()
    assert (
        "string(name:'AWS_REGION', defaultValue: 'us-west-2'" in text
    ), "Jenkins must expose an AWS_REGION parameter"
    assert (
        "string(name:'ROSA_HCP_NAMESPACE', defaultValue: 'ns-rosa-hcp'" in text
    ), "Jenkins must expose a ROSA_HCP_NAMESPACE parameter"


def test_jenkins_does_not_hardcode_the_region():
    text = _jenkinsfile()
    assert '-e AWS_REGION="us-west-2"' not in text, (
        "AWS_REGION must come from the Jenkins parameter, not a literal"
    )
    assert text.count('-e AWS_REGION="${AWS_REGION}"') >= 5, (
        "The stages that previously hardcoded the region must use the parameter"
    )


def test_jenkins_passes_the_namespace_parameter():
    text = _jenkinsfile()
    assert '-e rosa_hcp_namespace="${ROSA_HCP_NAMESPACE}"' in text, (
        "Suites that operate on ROSA HCP resources must receive rosa_hcp_namespace"
    )
