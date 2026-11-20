#!/usr/bin/env python3
"""
Tests for TestSuiteRunner from run-test-suite.py.

Validates runner functionality without executing playbooks:
    - Suite loading from JSON files
    - Listing available suites
    - Extra vars merging
    - Suite label extraction
    - Tag filtering
"""

import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# Import run-test-suite.py via importlib (filename contains a hyphen)
_spec = importlib.util.spec_from_file_location(
    "run_test_suite", BASE_DIR / "run-test-suite.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
TestSuiteRunner = _module.TestSuiteRunner


def _make_runner(**kwargs):
    """Create a TestSuiteRunner with AI agents disabled and BASE_DIR set."""
    defaults = {"base_dir": BASE_DIR, "ai_agent_enabled": False}
    defaults.update(kwargs)
    return TestSuiteRunner(**defaults)


# ================================================================
# Suite Loading
# ================================================================

def test_load_valid_suite():
    runner = _make_runner()
    suite = runner.load_test_suite("20-rosa-hcp-provision")
    assert suite is not None, "Should load a valid suite"
    assert "name" in suite
    assert "playbooks" in suite


def test_load_nonexistent_suite():
    runner = _make_runner()
    suite = runner.load_test_suite("99-does-not-exist")
    assert suite is None, "Loading a nonexistent suite should return None"


def test_load_all_suite_files():
    runner = _make_runner()
    suite_ids = [
        "05-verify-mce-environment",
        "10-configure-mce-environment",
        "11-install-capi-standalone",
        "20-rosa-hcp-provision",
        "27-rosa-hcp-add-machinepool",
        "28-rosa-hcp-delete-machinepool",
        "30-rosa-hcp-delete",
        "40-enable-capi-disable-hypershift",
        "41-disable-capi-enable-hypershift",
    ]
    for suite_id in suite_ids:
        suite = runner.load_test_suite(suite_id)
        assert suite is not None, f"Failed to load suite: {suite_id}"


# ================================================================
# Listing Suites
# ================================================================

def test_list_test_suites_returns_all():
    runner = _make_runner()
    suites = runner.list_test_suites()
    assert len(suites) >= 8, \
        f"Expected at least 8 suites, got {len(suites)}"


def test_list_test_suites_fields():
    runner = _make_runner()
    suites = runner.list_test_suites()
    for suite in suites:
        assert "id" in suite, "Listed suite missing 'id'"
        assert "name" in suite, "Listed suite missing 'name'"
        assert "tags" in suite, "Listed suite missing 'tags'"
        assert "playbook_count" in suite, "Listed suite missing 'playbook_count'"


def test_list_suites_sorted():
    runner = _make_runner()
    suites = runner.list_test_suites()
    ids = [s["id"] for s in suites]
    assert ids == sorted(ids), "Suites should be listed in sorted order"


# ================================================================
# Extra Vars
# ================================================================

def test_extra_vars_default_automation_path():
    runner = _make_runner()
    assert "AUTOMATION_PATH" in runner.extra_vars, \
        "Runner should set AUTOMATION_PATH by default"
    assert runner.extra_vars["AUTOMATION_PATH"] == str(BASE_DIR.absolute())


def test_extra_vars_override():
    runner = _make_runner(extra_vars={"cluster_name": "test-cluster", "replicas": "2"})
    assert runner.extra_vars["cluster_name"] == "test-cluster"
    assert runner.extra_vars["replicas"] == "2"
    # AUTOMATION_PATH should still be present
    assert "AUTOMATION_PATH" in runner.extra_vars


def test_extra_vars_override_automation_path():
    custom_path = "/custom/path"
    runner = _make_runner(extra_vars={"AUTOMATION_PATH": custom_path})
    assert runner.extra_vars["AUTOMATION_PATH"] == custom_path, \
        "Extra vars should be able to override AUTOMATION_PATH"


def test_build_ansible_cmd_complex_list():
    import json
    apps = ["audit", "oauth", "general"]
    runner = _make_runner(extra_vars={"log_forward_applications": apps})
    cmd = runner._build_ansible_cmd(Path("playbooks/test.yml"), {})

    # The list should NOT be passed as a single-quoted Python string: key=['...']
    assert not any(arg.startswith("log_forward_applications=[") for arg in cmd)

    # It should be serialized inside a JSON extra_vars blob
    json_args = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e" and i + 1 < len(cmd)]
    parsed_json = {}
    for j_arg in json_args:
        try:
            parsed_json.update(json.loads(j_arg))
        except (json.JSONDecodeError, TypeError):
            pass

    assert "log_forward_applications" in parsed_json
    assert parsed_json["log_forward_applications"] == apps


def test_build_ansible_cmd_complex_dict():
    import json
    tags = {"env": "test", "owner": "ci"}
    runner = _make_runner(extra_vars={"custom_tags": tags})
    cmd = runner._build_ansible_cmd(Path("playbooks/test.yml"), {})

    json_args = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e" and i + 1 < len(cmd)]
    parsed_json = {}
    for j_arg in json_args:
        try:
            parsed_json.update(json.loads(j_arg))
        except (json.JSONDecodeError, TypeError):
            pass

    assert "custom_tags" in parsed_json
    assert parsed_json["custom_tags"] == tags


def test_build_ansible_cmd_simple_vars():
    import json
    runner = _make_runner(extra_vars={"simple_key": "simple_value"})
    cmd = runner._build_ansible_cmd(Path("playbooks/test.yml"), {})

    json_args = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"]
    assert len(json_args) == 1, "All extra vars must be one JSON blob"
    parsed_json = json.loads(json_args[0])
    assert parsed_json["simple_key"] == "simple_value"


def test_build_ansible_cmd_preserves_spaces_and_types():
    import json
    runner = _make_runner(
        extra_vars={"flag": True, "count": 3, "message": "hello world"}
    )
    cmd = runner._build_ansible_cmd(Path("playbooks/test.yml"), {})

    json_args = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"]
    assert len(json_args) == 1, "All extra vars must be one JSON blob"
    parsed_json = json.loads(json_args[0])

    assert parsed_json["flag"] is True
    assert parsed_json["count"] == 3
    assert parsed_json["message"] == "hello world"
    assert not any(arg.startswith("message=") for arg in cmd)


# ================================================================
# Suite Label Extraction
# ================================================================

def test_extract_suite_label_drops_only_the_number_prefix():
    runner = _make_runner()
    assert runner._extract_suite_label("10-configure-mce-environment") == \
        "configure-mce-environment"


def test_extract_suite_label_keeps_the_whole_slug():
    runner = _make_runner()
    assert runner._extract_suite_label("20-rosa-hcp-provision") == "rosa-hcp-provision"
    assert runner._extract_suite_label("30-rosa-hcp-delete") == "rosa-hcp-delete"
    assert runner._extract_suite_label("05-verify-mce-environment") == \
        "verify-mce-environment"


def test_extract_suite_label_without_a_prefix_is_unchanged():
    runner = _make_runner()
    assert runner._extract_suite_label("something-unknown") == "something-unknown"


def test_suite_labels_are_unique_across_suites():
    """Each suite must own its latest-<label> report."""
    runner = _make_runner()
    labels = [runner._extract_suite_label(s["id"])
              for s in runner.list_test_suites()]
    assert len(labels) == len(set(labels)), f"duplicate suite labels: {labels}"


# ================================================================
# Tag Filtering
# ================================================================

def test_tag_filter_rosa():
    runner = _make_runner()
    suites = runner.list_test_suites()
    rosa_suites = [s for s in suites if "rosa" in s.get("tags", [])]
    assert len(rosa_suites) >= 1, "Should find at least one suite tagged 'rosa'"


def test_tag_filter_machinepool():
    runner = _make_runner()
    suites = runner.list_test_suites()
    mp_suites = [s for s in suites if "machinepool" in s.get("tags", [])]
    assert len(mp_suites) == 2, \
        f"Expected 2 machinepool-tagged suites, got {len(mp_suites)}"


def test_tag_filter_no_match():
    runner = _make_runner()
    suites = runner.list_test_suites()
    none_suites = [s for s in suites if "nonexistent-tag-xyz" in s.get("tags", [])]
    assert len(none_suites) == 0, "Nonexistent tag should match no suites"


# ================================================================
# Suite Dependencies
# ================================================================

def _suite(suite_id, depends_on=None):
    suite = {"id": suite_id, "name": suite_id, "tags": []}
    if depends_on:
        suite["depends_on"] = depends_on
    return suite


def test_depends_on_orders_the_dependency_first():
    runner = _make_runner()
    suites = [_suite("b", ["a"]), _suite("a"), _suite("c")]
    ordered = runner._order_by_dependencies(suites)
    assert [s["id"] for s in ordered] == ["a", "b", "c"]


def test_depends_on_keeps_independent_order():
    runner = _make_runner()
    suites = [_suite("20"), _suite("21"), _suite("30")]
    ordered = runner._order_by_dependencies(suites)
    assert [s["id"] for s in ordered] == ["20", "21", "30"]


def test_depends_on_ignores_dependencies_outside_the_selection():
    """A tag run cannot run suites the tag did not select."""
    runner = _make_runner()
    ordered = runner._order_by_dependencies([_suite("b", ["a"])])
    assert [s["id"] for s in ordered] == ["b"]


def test_dependent_suite_is_skipped_when_dependency_fails(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(
        runner, "list_test_suites",
        lambda: [_suite("a"), _suite("b", ["a"]), _suite("c")],
    )
    ran = []

    def fake_run(suite_id):
        ran.append(suite_id)
        return suite_id != "a"

    monkeypatch.setattr(runner, "run_test_suite", fake_run)

    assert runner.run_all_suites() is False
    assert ran == ["a", "c"], "b must not run after its dependency failed"


def test_always_suite_runs_after_dependency_fails(monkeypatch):
    """Cleanup suites must still run when provisioning failed."""
    runner = _make_runner()
    cleanup = _suite("c", ["a"])
    cleanup["always"] = True
    monkeypatch.setattr(
        runner, "list_test_suites", lambda: [_suite("a"), _suite("b", ["a"]), cleanup]
    )
    ran = []
    monkeypatch.setattr(
        runner, "run_test_suite", lambda suite_id: ran.append(suite_id) or suite_id != "a"
    )

    assert runner.run_all_suites() is False
    assert ran == ["a", "c"], "the always suite must run even though 'a' failed"


def test_suite_runs_when_dependency_is_not_selected(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(runner, "list_test_suites", lambda: [_suite("b", ["a"])])
    ran = []
    monkeypatch.setattr(
        runner, "run_test_suite", lambda suite_id: ran.append(suite_id) or True
    )

    assert runner.run_all_suites() is True
    assert ran == ["b"]


def test_run_test_suite_reports_only_its_own_outcome(monkeypatch):
    runner = _make_runner()
    runner.results["failed"] = 1  # an earlier suite failed
    monkeypatch.setattr(
        runner, "load_test_suite",
        lambda suite_id: {"name": "suite", "playbooks": [{"name": "p"}]},
    )
    monkeypatch.setattr(
        runner, "run_playbook",
        lambda playbook, suite_name: {
            "name": "p", "file": "f", "description": "", "test_case_id": "",
            "success": True, "duration": 0.0,
        },
    )
    monkeypatch.setattr(runner, "_print_suite_header", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_print_suite_summary", lambda *a, **k: None)

    assert runner.run_test_suite("suite") is True


# ================================================================
# Runner Initialization
# ================================================================

def test_runner_ai_agent_disabled():
    runner = _make_runner(ai_agent_enabled=False)
    assert runner.ai_agent_enabled is False
    assert runner.monitor_agent is None


def test_runner_results_initialized():
    runner = _make_runner()
    assert runner.results["total_tests"] == 0
    assert runner.results["passed"] == 0
    assert runner.results["failed"] == 0


# ================================================================
# Scenario Stage Execution
# ================================================================

def _scenario(stages, name="test-scenario"):
    return {
        "name": name,
        "description": "fixture scenario",
        "features": ["feat_a"],
        "stages": stages,
        "version": "4.22",
        "estimated_minutes": None,
    }


def _stub_stages(runner, failing):
    """Replace run_test_suite with a stub; record call order, fail named suites."""
    called = []

    def _fake(suite_id):
        called.append(suite_id)
        if suite_id in failing:
            runner.results["failed"] += 1
            return False
        runner.results["passed"] += 1
        return True

    runner.run_test_suite = _fake
    return called


def test_scenario_runs_all_stages_when_passing():
    runner = _make_runner()
    stages = [
        {"suite": "10-configure-mce-environment", "always": False},
        {"suite": "20-rosa-hcp-provision", "always": False},
        {"suite": "30-rosa-hcp-delete", "always": True},
    ]
    called = _stub_stages(runner, failing=set())
    assert runner.run_scenario(_scenario(stages)) is True
    assert called == [
        "10-configure-mce-environment",
        "20-rosa-hcp-provision",
        "30-rosa-hcp-delete",
    ]


def test_scenario_skips_normal_stages_after_failure():
    runner = _make_runner()
    stages = [
        {"suite": "20-rosa-hcp-provision", "always": False},
        {"suite": "21-verify-feature-flags", "always": False},
    ]
    called = _stub_stages(runner, failing={"20-rosa-hcp-provision"})
    assert runner.run_scenario(_scenario(stages)) is False
    assert called == ["20-rosa-hcp-provision"]


def test_scenario_still_runs_cleanup_after_failure():
    """A failed provision must not leak the cluster or leave CAPA enabled."""
    runner = _make_runner()
    stages = [
        {"suite": "20-rosa-hcp-provision", "always": False},
        {"suite": "21-verify-feature-flags", "always": False},
        {"suite": "30-rosa-hcp-delete", "always": True},
        {"suite": "41-disable-capi-enable-hypershift", "always": True},
    ]
    called = _stub_stages(runner, failing={"20-rosa-hcp-provision"})
    assert runner.run_scenario(_scenario(stages)) is False
    assert "21-verify-feature-flags" not in called
    assert called == [
        "20-rosa-hcp-provision",
        "30-rosa-hcp-delete",
        "41-disable-capi-enable-hypershift",
    ]


def test_scenario_passing_cleanup_does_not_mask_earlier_failure():
    runner = _make_runner()
    stages = [
        {"suite": "20-rosa-hcp-provision", "always": False},
        {"suite": "30-rosa-hcp-delete", "always": True},
    ]
    _stub_stages(runner, failing={"20-rosa-hcp-provision"})
    assert runner.run_scenario(_scenario(stages)) is False


def test_scenario_reports_failure_when_only_cleanup_fails():
    runner = _make_runner()
    stages = [
        {"suite": "20-rosa-hcp-provision", "always": False},
        {"suite": "30-rosa-hcp-delete", "always": True},
    ]
    _stub_stages(runner, failing={"30-rosa-hcp-delete"})
    assert runner.run_scenario(_scenario(stages)) is False


def test_scenario_sets_suite_label():
    runner = _make_runner()
    stages = [{"suite": "20-rosa-hcp-provision", "always": False}]
    _stub_stages(runner, failing=set())
    runner.run_scenario(_scenario(stages, name="day1-security"))
    assert runner.suite_label == "scenario-day1-security"


# ================================================================
# Per-feature JUnit expansion
# ================================================================

def _suite_with_verify(duration=120.0, success=True, **extra):
    """A one-playbook suite result standing in for stage 21."""
    playbook = {
        "name": "Verify Feature Flags",
        "file": "playbooks/verify_feature_flags.yml",
        "description": "Checks each requested feature",
        "success": success,
        "duration": duration,
    }
    playbook.update(extra)
    return {
        "name": "Verify Feature Flags",
        "start_time": "2026-10-05T16:52:17",
        "duration": duration,
        "playbooks": [playbook],
    }


def _feature_data(features):
    return {"schema_version": 1, "features": features}


def _runner_with_results(suites, duration=120.0):
    runner = _make_runner()
    runner.results["suites"] = suites
    runner.results["duration"] = duration
    return runner


def _parse(xml_text):
    import xml.etree.ElementTree as ET
    return ET.fromstring(xml_text)


def test_feature_testcases_expands_one_case_per_feature():
    runner = _make_runner()
    data = _feature_data([
        {"id": "channel_group", "status": "passed"},
        {"id": "fips", "status": "warned", "detail": "CRD has no field fips"},
        {"id": "audit_logging", "status": "failed", "detail": "no destination"},
    ])
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"}, data
    )
    assert [c["name"] for c in cases] == ["channel_group", "fips", "audit_logging"]
    assert [c["outcome"] for c in cases] == ["passed", "skipped", "failed"]
    # Stable classname is what lets CI trend a single feature across builds.
    assert {c["classname"] for c in cases} == {"FeatureVerification"}


def test_feature_testcases_ignores_other_playbooks():
    runner = _make_runner()
    data = _feature_data([{"id": "fips", "status": "passed"}])
    assert runner._feature_testcases(
        {"file": "playbooks/create_rosa_hcp_cluster.yml"}, data
    ) is None


def test_feature_testcases_without_artifact_falls_back():
    runner = _make_runner()
    pb = {"file": "playbooks/verify_feature_flags.yml"}
    assert runner._feature_testcases(pb, None) is None
    assert runner._feature_testcases(pb, _feature_data([])) is None


def test_junit_expands_features_into_testcases():
    runner = _runner_with_results([_suite_with_verify()])
    runner.load_feature_verification = lambda: _feature_data([
        {"id": "domain_prefix", "status": "passed"},
        {"id": "channel_group", "status": "passed"},
        {"id": "fips", "status": "warned", "detail": "CRD has no field fips"},
    ])
    root = _parse(runner._generate_junit_xml())

    assert root.get("tests") == "3", "One testcase per feature, not per playbook"
    assert root.get("skipped") == "1"
    assert root.get("failures") == "0"

    names = [tc.get("name") for tc in root.iter("testcase")]
    assert names == ["domain_prefix", "channel_group", "fips"]

    fips = [tc for tc in root.iter("testcase") if tc.get("name") == "fips"][0]
    skipped = fips.find("skipped")
    assert skipped is not None, "A CRD gap is a skip, not a failure"
    assert "CRD has no field fips" in skipped.get("message", "")


def test_junit_marks_failed_feature_as_failure():
    runner = _runner_with_results([_suite_with_verify(success=False, error="boom")])
    runner.load_feature_verification = lambda: _feature_data([
        {"id": "audit_logging", "status": "failed", "detail": "no destination"},
        {"id": "fips", "status": "passed"},
    ])
    root = _parse(runner._generate_junit_xml())

    assert root.get("failures") == "1"
    failure = root.find(".//testcase[@name='audit_logging']/failure")
    assert failure is not None
    assert "no destination" in failure.get("message", "")
    # The passing feature is still reported, not masked by the failure.
    assert root.find(".//testcase[@name='fips']") is not None


def test_junit_falls_back_when_no_artifact():
    """A playbook that died before writing results keeps its raw error."""
    runner = _runner_with_results([
        _suite_with_verify(success=False, error="login failed", output="trace")
    ])
    runner.load_feature_verification = lambda: None
    root = _parse(runner._generate_junit_xml())

    assert root.get("tests") == "1"
    assert root.get("failures") == "1"
    failure = root.find(".//testcase/failure")
    assert "login failed" in failure.get("message", "")


def test_junit_suite_and_root_totals_agree():
    """Root totals must equal the sum over suites once features are expanded."""
    runner = _runner_with_results([
        _suite_with_verify(),
        {
            "name": "CAPA Cluster Provisioning",
            "start_time": "2026-10-05T16:34:36",
            "duration": 1060.5,
            "playbooks": [{
                "name": "Create CAPA Cluster",
                "file": "playbooks/create_rosa_hcp_cluster.yml",
                "description": "Provisions a cluster",
                "success": True,
                "duration": 1060.5,
            }],
        },
    ])
    runner.load_feature_verification = lambda: _feature_data([
        {"id": "a", "status": "passed"},
        {"id": "b", "status": "failed", "detail": "x"},
    ])
    root = _parse(runner._generate_junit_xml())

    suites = list(root.iter("testsuite"))
    assert int(root.get("tests")) == sum(int(s.get("tests")) for s in suites)
    assert int(root.get("failures")) == sum(int(s.get("failures")) for s in suites)
    assert int(root.get("tests")) == 3  # 2 features + 1 provisioning playbook


def test_load_feature_verification_rejects_stale_artifact(tmp_path):
    """A file left by an earlier run must not be attributed to this one."""
    import json as _json
    import time as _time

    runner = _make_runner()
    runner.results_dir = tmp_path
    artifact = tmp_path / _module.FEATURE_VERIFICATION_FILE
    artifact.write_text(_json.dumps({"features": [{"id": "fips", "status": "passed"}]}))

    runner._started_at = _time.time() + 60  # pretend the run started later
    assert runner.load_feature_verification() is None

    runner._started_at = 0
    assert runner.load_feature_verification() is not None


# ================================================================
# version_overrides build pinning
# ================================================================

def _validate_only(version):
    """Run the CLI in --validate-only (offline, no ansible) and return stdout."""
    import subprocess
    result = subprocess.run(
        [str(BASE_DIR / "run-test-suite.py"), "--scenario", "day1-basic",
         "--stages", "21", "--validate-only",
         "-e", f"openshift_version={version}", "-e", "name_prefix=tf1"],
        capture_output=True, text=True, cwd=BASE_DIR,
    )
    # Without this, a crashed script returns empty stdout and every negative
    # assertion ("pins OpenShift" not in out) passes vacuously.
    assert result.returncode == 0, f"exit {result.returncode}\n{result.stderr}"
    return result.stdout


def _registry_pin(family="5.0"):
    """The pinned build for a release family, read from the registry.

    Read rather than hardcoded: when the EC build rolls to rc.1, one legitimate
    registry edit should not break two tests.
    """
    import yaml
    registry = yaml.safe_load(
        (BASE_DIR / "templates" / "schemas" / "feature-registry.yml").read_text()
    )
    return registry["scenario_defaults"]["version_overrides"][family]["openshift_version"]


def test_bare_five_zero_is_pinned_to_the_ec_build():
    """A bare 5.0 reaches OCM as a family it cannot resolve, so it must be pinned.

    Left unpinned, OCM's search= query invents a 5.0.0 that does not exist and
    the run provisions a doomed cluster for ~40 minutes of real AWS spend.
    """
    out = _validate_only("5.0")
    assert f"openshift_version={_registry_pin()}" in out
    assert "pins OpenShift 5.0" in out, "The substitution should be announced"


def test_exact_build_is_never_rewritten():
    """Naming an exact build is an explicit choice; the pin must not clobber it."""
    out = _validate_only("5.0.0-rc.1")
    assert "openshift_version=5.0.0-rc.1" in out
    assert "pins OpenShift" not in out
    # The family's other overrides still apply.
    assert "channel_group=candidate" in out


def test_unpinned_family_passes_through():
    out = _validate_only("4.22")
    assert "openshift_version=4.22" in out
    assert "pins OpenShift" not in out


def _validate_scenario(scenario, prefix="tf1", extra=()):
    """--validate-only for an arbitrary scenario; returns stdout."""
    import subprocess
    cmd = [str(BASE_DIR / "run-test-suite.py"), "--scenario", scenario,
           "--validate-only", "-e", "openshift_version=5.0",
           "-e", f"name_prefix={prefix}"]
    for pair in extra:
        cmd += ["-e", pair]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)
    assert result.returncode == 0, f"exit {result.returncode}\n{result.stderr}"
    return result.stdout


def test_pool_name_is_scoped_to_the_name_prefix():
    """Unscoped pool names collide across clusters in the shared namespace.

    Both machinepool playbooks default pool_name to the literal "extra-pool"
    and every cluster lives in ns-rosa-hcp, so without this the second
    concurrent run fails on "already exists" and stage 28 deletes the other
    cluster's pool. Mirrors the nightly's -e pool_name="${NAME_PREFIX}-mp".
    """
    out = _validate_scenario("day2-machinepool", prefix="mp1")
    assert "pool_name=mp1-mp" in out
    assert "pool_name=extra-pool" not in out


def test_explicit_pool_name_is_not_overridden():
    """Deriving a default must not clobber a caller who named the pool."""
    out = _validate_scenario("day2-machinepool", prefix="mp1",
                             extra=["pool_name=custom-pool"])
    assert "pool_name=custom-pool" in out
    assert "pool_name=mp1-mp" not in out


def test_derived_pool_name_fits_the_fifteen_char_limit():
    """add_rosa_machine_pool.yml rejects pool_name over 15 chars (nodePoolName).

    The derived form is <prefix>-mp, so prefixes up to 12 chars are safe; the
    4-char prefixes in use leave plenty of room.
    """
    out = _validate_scenario("day2-machinepool", prefix="mp1")
    pool = [ln.split("pool_name=")[1].strip()
            for ln in out.splitlines() if "pool_name=" in ln][0]
    assert len(pool) <= 15, f"{pool!r} is {len(pool)} chars"


def test_registry_pins_both_version_and_channel_for_five_zero():
    """Guard the registry entry itself, not just the runner behaviour."""
    import yaml
    registry = yaml.safe_load(
        (BASE_DIR / "templates" / "schemas" / "feature-registry.yml").read_text()
    )
    override = registry["scenario_defaults"]["version_overrides"]["5.0"]
    assert override["channel_group"] == "candidate"
    # Shape, not an exact string: this guards against the pin being deleted or
    # pointed at the wrong release family, without breaking on an rc bump.
    pinned = override["openshift_version"]
    assert pinned.startswith("5.0."), f"pin {pinned!r} is not a 5.0 build"
    assert pinned != "5.0", "the pin must name an exact build, not the family"


# ================================================================
# Degraded (OCM-less) verification
# ================================================================

def _degraded_data(features, degraded=True):
    return {
        "schema_version": 1,
        "features": features,
        "environment": {
            "ocm_available": not degraded,
            "degraded": degraded,
            "degraded_reason": "OCM API unreachable — CRDs only",
        },
    }


def test_degraded_run_adds_a_reachability_testcase(monkeypatch):
    """The degradation needs a testcase of its own, or CI never sees it."""
    monkeypatch.delenv("CI", raising=False)
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        _degraded_data([{"id": "fips", "status": "passed"}]),
    )
    assert [c["name"] for c in cases] == ["ocm_reachability", "fips"]
    assert cases[0]["outcome"] == "skipped", "Local runs stay usable offline"
    assert "OCM API unreachable" in cases[0]["message"]


def test_degraded_run_fails_under_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        _degraded_data([{"id": "fips", "status": "passed"}]),
    )
    assert cases[0]["outcome"] == "failed", "A half-verified build must not be green"


def test_healthy_run_adds_no_reachability_testcase(monkeypatch):
    monkeypatch.setenv("CI", "true")
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        _degraded_data([{"id": "fips", "status": "passed"}], degraded=False),
    )
    assert [c["name"] for c in cases] == ["fips"]


def test_degraded_junit_counts_the_failure(monkeypatch):
    monkeypatch.setenv("CI", "true")
    runner = _runner_with_results([_suite_with_verify()])
    runner.load_feature_verification = lambda: _degraded_data([
        {"id": "a", "status": "passed"}, {"id": "b", "status": "passed"},
    ])
    root = _parse(runner._generate_junit_xml())
    assert root.get("tests") == "3"
    assert root.get("failures") == "1"
    assert root.find(".//testcase[@name='ocm_reachability']/failure") is not None


def test_artifact_without_environment_key_is_safe():
    """Older artifacts predate the degraded field; expansion must not raise."""
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        {"features": [{"id": "fips", "status": "passed"}]},
    )
    assert [c["name"] for c in cases] == ["fips"]


def test_unrecognised_feature_status_fails_closed(monkeypatch):
    """An unknown status must not render as a green testcase."""
    monkeypatch.delenv("CI", raising=False)
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        _feature_data([{"id": "x", "status": "bogus"}]),
    )
    assert cases[0]["outcome"] == "error"
    assert "bogus" in cases[0]["message"]


def test_malformed_features_does_not_raise(monkeypatch):
    """A bad artifact must not crash report generation after a 75-minute run."""
    runner = _make_runner()
    pb = {"file": "playbooks/verify_feature_flags.yml"}
    for bad in ({"fips": {}}, "fips", 5, None):
        assert runner._feature_testcases(pb, {"features": bad}) is None
    # A list whose elements are not dicts: elements are skipped, no raise.
    assert runner._feature_testcases(pb, {"features": ["fips"]}) == []


def test_degraded_string_false_is_not_treated_as_degraded(monkeypatch):
    """Guards against a jinja2_native change turning the bool into "False"."""
    monkeypatch.setenv("CI", "true")
    runner = _make_runner()
    data = {"features": [{"id": "a", "status": "passed"}],
            "environment": {"degraded": "False"}}
    cases = runner._feature_testcases({"file": "playbooks/verify_feature_flags.yml"}, data)
    assert [c["name"] for c in cases] == ["a"], "string 'False' must not be truthy here"


def test_features_without_ids_get_distinct_names():
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        _feature_data([{"status": "passed"}, {"status": "passed"}]),
    )
    assert len({c["name"] for c in cases}) == 2, "duplicate classname+name breaks CI trending"


# ================================================================
# Output preservation and counting consistency
# ================================================================

def test_failed_expansion_keeps_the_ansible_log():
    """Per-feature detail says which feature broke; the log says why."""
    runner = _runner_with_results([
        _suite_with_verify(success=False, error="assertion failed",
                           output="TASK [Assert fips] ***\nfatal: ...full log...")
    ])
    runner.load_feature_verification = lambda: _feature_data([
        {"id": "fips", "status": "failed", "detail": "fips not enabled"},
    ])
    root = _parse(runner._generate_junit_xml())

    assert root.find(".//testcase[@name='fips']/failure") is not None
    sysout = root.find(".//system-out")
    assert sysout is not None, "ansible log must survive the expansion"
    assert "full log" in sysout.text


def test_playbook_failure_outside_feature_results_is_not_green():
    """A failure after the artifact write must not report an all-green suite."""
    runner = _runner_with_results([
        _suite_with_verify(success=False, error="died after writing results",
                           output="trace")
    ])
    runner.load_feature_verification = lambda: _feature_data([
        {"id": "a", "status": "passed"}, {"id": "b", "status": "passed"},
    ])
    root = _parse(runner._generate_junit_xml())

    assert int(root.get("failures")) == 1, "non-zero exit must surface as a failure"
    extra = root.find(".//testcase[@name='Verify Feature Flags (playbook exit)']")
    assert extra is not None
    assert "died after writing results" in extra.find("failure").get("message")


def test_console_counts_come_from_the_xml_build():
    runner = _runner_with_results([_suite_with_verify()])
    runner.load_feature_verification = lambda: _feature_data([
        {"id": "a", "status": "passed"},
        {"id": "b", "status": "failed", "detail": "x"},
        {"id": "c", "status": "warned", "detail": "y"},
    ])
    assert runner.last_junit_counts is None, "no counts before a build"
    root = _parse(runner._generate_junit_xml())
    counts = runner.last_junit_counts
    assert counts == {"tests": int(root.get("tests")),
                      "failures": int(root.get("failures")),
                      "errors": int(root.get("errors")),
                      "skipped": int(root.get("skipped"))}


def test_ci_false_is_not_treated_as_ci(monkeypatch):
    for value, expected in [("true", True), ("1", True), ("yes", True),
                            ("false", False), ("0", False), ("no", False),
                            ("", False), ("  ", False), ("TRUE", True)]:
        monkeypatch.setenv("CI", value)
        assert _module._in_ci() is expected, f"CI={value!r}"
    monkeypatch.delenv("CI", raising=False)
    assert _module._in_ci() is False


def test_degraded_is_skipped_when_ci_is_false(monkeypatch):
    monkeypatch.setenv("CI", "false")
    runner = _make_runner()
    cases = runner._feature_testcases(
        {"file": "playbooks/verify_feature_flags.yml"},
        _degraded_data([{"id": "fips", "status": "passed"}]),
    )
    assert cases[0]["outcome"] == "skipped", "CI=false must not fail the build"


def test_artifact_archived_once_per_run(tmp_path, monkeypatch):
    """save_results runs once per --format; the archive must not triple."""
    import json as _json
    runner = _make_runner()
    runner.results_dir = tmp_path
    runner.results["suites"] = []
    runner.results["duration"] = 1.0
    runner._started_at = 0
    (tmp_path / _module.FEATURE_VERIFICATION_FILE).write_text(
        _json.dumps({"features": [{"id": "fips", "status": "passed"}]}))

    # Count the writes, not the files. The filename carries a %H%M%S timestamp,
    # so three calls inside one second collide on one path and a file count
    # passes even with the guard removed — verified by reverting it.
    writes = []
    real_dump = _module.json.dump
    def counting_dump(obj, fp, **kw):
        name = getattr(fp, "name", "")
        if "feature-verification-" in str(name):
            writes.append(name)
        return real_dump(obj, fp, **kw)
    monkeypatch.setattr(_module.json, "dump", counting_dump)

    for fmt in ("json", "html", "junit"):
        runner.save_results(output_format=fmt)

    assert len(writes) == 1, f"archive written {len(writes)}x, expected once per run"
    assert list(tmp_path.rglob("feature-verification-*.json"))


def test_save_results_writes_one_junit_file_per_run(tmp_path):
    """A run must produce exactly one file for Jenkins' test-results/**/*.xml glob."""
    runner = _make_runner()
    runner.results_dir = tmp_path
    runner.suite_label = "rosa-hcp-provision"
    runner.results["suites"] = []
    runner.results["duration"] = 1.0

    path = runner.save_results(output_format="junit")

    xmls = list(tmp_path.rglob("*.xml"))
    assert xmls == [path], f"expected one JUnit file, found {xmls}"
    assert not list(tmp_path.glob("latest*.xml")), \
        "a latest-*.xml copy would be counted twice by Jenkins"


def test_json_and_html_still_write_a_latest_copy(tmp_path):
    runner = _make_runner()
    runner.results_dir = tmp_path
    runner.suite_label = "rosa-hcp-provision"
    runner.results["suites"] = []
    runner.results["duration"] = 1.0

    runner.save_results(output_format="json")
    runner.save_results(output_format="html")

    assert (tmp_path / "latest-rosa-hcp-provision.json").exists()
    assert (tmp_path / "latest-rosa-hcp-provision.html").exists()


def test_total_tests_accumulates_across_suites(monkeypatch):
    """A multi-suite run reports every executed playbook, not just the last suite."""
    runner = _make_runner()

    def fake_playbook(playbook, suite_name):
        return {
            "name": playbook.get("name", ""),
            "file": playbook.get("file", ""),
            "description": "",
            "test_case_id": "",
            "success": True,
            "is_error": False,
            "error": None,
            "duration": 0.0,
        }

    monkeypatch.setattr(runner, "run_playbook", fake_playbook)
    monkeypatch.setattr(runner, "_print_suite_header", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_print_suite_summary", lambda *a, **k: None)

    first = runner.load_test_suite("20-rosa-hcp-provision")
    second = runner.load_test_suite("30-rosa-hcp-delete")
    runner.run_test_suite("20-rosa-hcp-provision")
    runner.run_test_suite("30-rosa-hcp-delete")

    expected = len(first["playbooks"]) + len(second["playbooks"])
    assert runner.results["total_tests"] == expected
    assert runner.results["total_tests"] == (
        runner.results["passed"] + runner.results["failed"]
    )


# ================================================================
# main() exit codes
# ================================================================

def test_main_returns_1_without_a_suite(monkeypatch):
    monkeypatch.setattr(_module.sys, "argv", ["run-test-suite.py"])
    assert _module.main() == 1


def test_main_returns_0_when_suite_passes(monkeypatch):
    monkeypatch.setattr(
        _module.sys, "argv",
        ["run-test-suite.py", "20-rosa-hcp-provision", "--no-save"],
    )
    monkeypatch.setattr(
        _module.TestSuiteRunner, "run_test_suite",
        lambda self, suite_id: True,
    )
    assert _module.main() == 0


def test_main_returns_1_when_suite_fails(monkeypatch):
    monkeypatch.setattr(
        _module.sys, "argv",
        ["run-test-suite.py", "20-rosa-hcp-provision", "--no-save"],
    )
    monkeypatch.setattr(
        _module.TestSuiteRunner, "run_test_suite",
        lambda self, suite_id: False,
    )
    assert _module.main() == 1


# ================================================================
# Timeout enforcement
# ================================================================

def test_run_playbook_enforces_timeout_while_streaming(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.stdout = iter(["line one\n", "line two\n"])
            self.killed = False
            self.returncode = None

        def wait(self, timeout=None):
            if timeout is not None:
                raise _module.subprocess.TimeoutExpired("ansible-playbook", timeout)
            self.returncode = -15
            return self.returncode

        def kill(self):
            self.killed = True

        def poll(self):
            return None

    fake = FakeProcess()
    monkeypatch.setattr(_module.subprocess, "Popen", lambda *args, **kwargs: fake)

    runner = _make_runner()
    result = runner.run_playbook(
        {
            "name": "timeout-test",
            "file": "playbooks/create_rosa_hcp_cluster.yml",
            "description": "timeout test",
            "timeout": 0.1,
        },
        "test-suite",
    )

    assert result["success"] is False
    assert "Timeout" in result["error"]
    assert fake.killed is True
    assert "line one" in result["output"]
