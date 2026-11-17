#!/usr/bin/env python3
"""Guards for suite documentation.

Each test suite owns a human-readable page under docs/test-suites/<id>.md.
The suite JSON stays an execution contract: prose belongs in the page, not in
a ``documentation`` key the runner never reads.
"""

import json
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
SUITE_DIR = BASE_DIR / "test-suites"
DOCS_DIR = BASE_DIR / "docs" / "test-suites"
README = BASE_DIR / "README.md"

SUITE_FILES = sorted(SUITE_DIR.glob("*.json"))


@pytest.mark.parametrize("suite_file", SUITE_FILES, ids=lambda path: path.stem)
def test_suite_has_a_docs_page(suite_file):
    docs_page = DOCS_DIR / f"{suite_file.stem}.md"
    assert docs_page.exists(), (
        f"Missing docs page: {docs_page.relative_to(BASE_DIR)}"
    )


@pytest.mark.parametrize("suite_file", SUITE_FILES, ids=lambda path: path.stem)
def test_docs_page_has_a_title_and_suite_id(suite_file):
    docs_page = DOCS_DIR / f"{suite_file.stem}.md"
    text = docs_page.read_text()
    assert text.startswith("# "), "docs page must start with a level-1 title"
    assert f"| **Suite ID** | `{suite_file.stem}` |" in text


@pytest.mark.parametrize("suite_file", SUITE_FILES, ids=lambda path: path.stem)
def test_suite_json_has_no_embedded_documentation(suite_file):
    suite = json.loads(suite_file.read_text())
    assert "documentation" not in suite, (
        "documentation belongs in docs/test-suites/<id>.md, not the suite JSON"
    )


def test_docs_pages_are_linked_from_readme():
    readme = README.read_text()
    missing = [
        suite_file.stem
        for suite_file in SUITE_FILES
        if f"docs/test-suites/{suite_file.stem}.md" not in readme
    ]
    assert not missing, f"docs pages not linked from README: {missing}"


def test_docs_pages_have_a_matching_suite():
    suite_ids = {suite_file.stem for suite_file in SUITE_FILES}
    docs_ids = {docs_page.stem for docs_page in DOCS_DIR.glob("*.md")}
    assert docs_ids - suite_ids == set(), (
        f"docs pages without a suite: {sorted(docs_ids - suite_ids)}"
    )
