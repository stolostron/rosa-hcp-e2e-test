#!/usr/bin/env python3
"""Validate test-suites/*.json against a closed schema.

The schema lives at templates/schemas/test-suite-schema.json and lists only
the fields run-test-suite.py actually reads. Anything else is configuration
drift and fails here.

These tests run without a live cluster.
"""

import json
import re
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
SUITE_DIR = BASE_DIR / "test-suites"
SCHEMA_PATH = BASE_DIR / "templates" / "schemas" / "test-suite-schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

SUITE_FILES = sorted(SUITE_DIR.glob("*.json"))

_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
}


def _load_suite(path: Path) -> dict:
    return json.loads(path.read_text())


def _validate(value, schema: dict, path: str) -> list[str]:
    """Validate the small JSON Schema subset used by the suite schema."""
    errors = []
    expected_type = schema.get("type")
    if expected_type and not _TYPE_CHECKS[expected_type](value):
        return [f"{path}: expected {expected_type}, got {type(value).__name__}"]

    if expected_type == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: must be at least {schema['minLength']} characters")
    elif expected_type == "integer":
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
    elif expected_type == "object":
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key '{key}'")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in sorted(set(value) - set(properties)):
                errors.append(
                    f"{path}: unknown key '{key}' (not read by run-test-suite.py)"
                )
        for key, sub_schema in properties.items():
            if key in value:
                errors += _validate(value[key], sub_schema, f"{path}.{key}")
    elif expected_type == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: must contain at least {schema['minItems']} item(s)")
        items = schema.get("items")
        if items:
            for index, item in enumerate(value):
                errors += _validate(item, items, f"{path}[{index}]")

    return errors


@pytest.mark.parametrize("suite_file", SUITE_FILES, ids=lambda path: path.stem)
def test_suite_matches_schema(suite_file):
    errors = _validate(_load_suite(suite_file), SCHEMA, suite_file.stem)
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("suite_file", SUITE_FILES, ids=lambda path: path.stem)
def test_playbook_file_paths_exist(suite_file):
    suite = _load_suite(suite_file)
    for playbook in suite["playbooks"]:
        playbook_file = playbook.get("file", playbook.get("name"))
        assert playbook_file, f"{suite_file.name}: playbook missing both 'file' and 'name'"
        assert (BASE_DIR / playbook_file).exists(), (
            f"{suite_file.name}: playbook path does not exist: {playbook_file}"
        )


def test_suite_numbering_is_unique():
    prefixes = {}
    for suite_file in SUITE_FILES:
        match = re.match(r"^(\d+)-", suite_file.stem)
        assert match, f"{suite_file.name}: suite id must start with a number"
        prefixes.setdefault(match.group(1), []).append(suite_file.stem)

    duplicates = {prefix: names for prefix, names in prefixes.items() if len(names) > 1}
    assert not duplicates, f"duplicate suite numbers: {duplicates}"


def test_schema_lists_only_runner_read_fields():
    """Guard against metadata creeping back into the suite definition."""
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["properties"]) == {
        "name",
        "description",
        "tags",
        "stopOnFailure",
        "depends_on",
        "always",
        "playbooks",
    }

    playbook_schema = SCHEMA["properties"]["playbooks"]["items"]
    assert playbook_schema["additionalProperties"] is False
    assert set(playbook_schema["properties"]) == {
        "name",
        "file",
        "description",
        "extra_vars",
        "required",
        "timeout",
        "test_case_id",
    }


def test_suites_do_not_hardcode_per_run_inputs():
    """Region, namespace and OCM role name come from -e/Jenkins, not the suite."""
    forbidden = {
        "aws_region",
        "rosa_hcp_namespace",
        "capi_namespace",
        "ocm_role_config_name",
    }
    offenders = []
    for suite_file in SUITE_FILES:
        suite = _load_suite(suite_file)
        for playbook in suite.get("playbooks", []):
            hardcoded = set(playbook.get("extra_vars", {})) & forbidden
            if hardcoded:
                offenders.append(f"{suite_file.name}: {sorted(hardcoded)}")

    assert not offenders, (
        "Per-run inputs must come from -e/Jenkins, not suite JSON:\n"
        + "\n".join(offenders)
    )


def test_depends_on_targets_exist():
    suite_ids = {suite_file.stem for suite_file in SUITE_FILES}
    unknown = [
        f"{suite_file.stem} -> {dependency}"
        for suite_file in SUITE_FILES
        for dependency in _load_suite(suite_file).get("depends_on", [])
        if dependency not in suite_ids
    ]
    assert not unknown, f"depends_on points at unknown suites: {unknown}"


def test_depends_on_has_no_cycles():
    graph = {
        suite_file.stem: _load_suite(suite_file).get("depends_on", [])
        for suite_file in SUITE_FILES
    }
    state = {}

    def visit(suite_id, path):
        if state.get(suite_id) == "done":
            return
        assert state.get(suite_id) != "visiting", (
            f"dependency cycle: {' -> '.join(path + [suite_id])}"
        )
        state[suite_id] = "visiting"
        for dependency in graph.get(suite_id, []):
            if dependency in graph:
                visit(dependency, path + [suite_id])
        state[suite_id] = "done"

    for suite_id in graph:
        visit(suite_id, [])
