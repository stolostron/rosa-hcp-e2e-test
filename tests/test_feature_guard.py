"""Tests for FeatureGuard and DocGapAnalyzer."""

import json
import pytest
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta

from agents.feature_guard import (
    FeatureGuard,
    DocGapAnalyzer,
)
from agents.feature_guard_constants import (
    redact,
    redact_dict,
)


BASE_DIR = Path(__file__).parent.parent


class TestRedaction:
    def test_redact_sg_id(self):
        assert redact("sg-0123456789abcdef0") == "sg-<id>"

    def test_redact_vpc_id(self):
        assert redact("vpc-abcdef1234567890a") == "vpc-<id>"

    def test_redact_subnet_id(self):
        assert redact("subnet-0123456789abcdef0") == "subnet-<id>"

    def test_redact_arn(self):
        result = redact("arn:aws:kms:us-west-2:123456789012:key/abc-123")
        assert result == "arn:aws:***:***:***:***"

    def test_redact_access_key(self):
        assert redact("AKIAIOSFODNN7EXAMPLE") == "<access-key-id>"

    def test_redact_openshift_api_url(self):
        result = redact("https://api.my-cluster.abcd.p1.openshiftapps.com:6443")
        assert "api.my-cluster" not in result
        assert "<cluster>" in result

    def test_redact_uuid(self):
        result = redact("550e8400-e29b-41d4-a716-446655440000")
        assert result == "<uuid>"

    def test_redact_preserves_plain_text(self):
        assert redact("hello world") == "hello world"

    def test_redact_multiple_in_one_string(self):
        text = "VPC vpc-abc12345 has SG sg-def67890"
        result = redact(text)
        assert "vpc-<id>" in result
        assert "sg-<id>" in result

    def test_redact_dict_nested(self):
        data = {
            "vpc": "vpc-abc12345",
            "nested": {"sg": "sg-def67890"},
            "list_field": ["subnet-aaa11111"],
            "number": 42,
        }
        result = redact_dict(data)
        assert result["vpc"] == "vpc-<id>"
        assert result["nested"]["sg"] == "sg-<id>"
        assert result["list_field"][0] == "subnet-<id>"
        assert result["number"] == 42


class TestFeatureGuard:
    @pytest.fixture
    def agent(self):
        return FeatureGuard(BASE_DIR, verbose=False)

    def test_init(self, agent):
        assert agent.name == "FeatureGuard"
        assert agent.docs_dir.exists()

    def test_doc_path(self, agent):
        path = agent._doc_path("security_groups")
        assert path.name == "security-groups.md"

    def test_doc_path_no_cni(self, agent):
        path = agent._doc_path("no_cni")
        assert path.name == "no-cni.md"

    def test_feature_source_files_returns_list(self, agent):
        files = agent._feature_source_files("security_groups")
        assert isinstance(files, list)
        assert len(files) > 0

    def test_feature_source_files_includes_specific(self, agent):
        files = agent._feature_source_files("security_groups")
        assert "tasks/create_security_group.yml" in files

    def test_feature_source_files_includes_shared(self, agent):
        files = agent._feature_source_files("no_cni")
        assert "feature_manager.py" in files

    def test_get_doc_status(self, agent):
        statuses = agent.get_doc_status()
        assert isinstance(statuses, list)
        assert len(statuses) > 0
        first = statuses[0]
        assert "feature_id" in first
        assert "has_doc" in first
        assert "stale" in first

    def test_get_doc_status_includes_security_groups(self, agent):
        statuses = agent.get_doc_status()
        ids = [s["feature_id"] for s in statuses]
        assert "security_groups" in ids

    def test_existing_docs_found(self, agent):
        statuses = agent.get_doc_status()
        with_docs = [s for s in statuses if s["has_doc"]]
        assert len(with_docs) > 0

    def test_render_test_run_entry(self, agent):
        data = {"provision_result": "PASS", "region": "us-west-2"}
        entry = agent._render_test_run_entry(data, "2026-06-10", "manual test")
        assert "PASS" in entry
        assert "us-west-2" in entry
        assert "manual test" in entry

    def test_render_test_run_entry_redacted(self, agent):
        data = redact_dict({
            "vpc": "vpc-abc12345",
            "sg": "sg-def67890",
        })
        entry = agent._render_test_run_entry(data, "2026-06-10", "manual test")
        assert "vpc-abc12345" not in entry
        assert "sg-def67890" not in entry

    def test_detect_stale_no_crash(self, agent):
        stale = agent.detect_stale_docs(since="HEAD~0")
        assert isinstance(stale, dict)

    def test_generate_doc_from_template(self, agent, tmp_path):
        agent.docs_dir = tmp_path
        agent.template_path = BASE_DIR / "docs" / "features" / "_template.md"
        agent._generate_doc_from_template("security_groups")
        generated = tmp_path / "security-groups.md"
        assert generated.exists()
        content = generated.read_text()
        assert "security_groups" in content
        assert "Additional Security Groups" in content

    def test_update_live_test_record_creates_doc(self, agent, tmp_path):
        agent.docs_dir = tmp_path
        agent.template_path = BASE_DIR / "docs" / "features" / "_template.md"
        agent.tracker_path = tmp_path / "doc_tracker.json"
        agent._tracker = None

        ok = agent.update_live_test_record("security_groups", {
            "date": "2026-06-24",
            "provision_result": "PASS",
            "region": "us-west-2",
            "vpc": "vpc-abc12345",
        })
        assert ok
        content = (tmp_path / "security-groups.md").read_text()
        assert "PASS" in content
        assert "vpc-abc12345" not in content
        assert "vpc-<id>" in content

        tracker = json.loads((tmp_path / "doc_tracker.json").read_text())
        assert "security_groups" in tracker["features"]
        assert len(tracker["update_history"]) == 1


class TestDocGapAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return DocGapAnalyzer(BASE_DIR)

    def test_analyze_returns_structure(self, analyzer):
        report = analyzer.analyze()
        assert "total_features" in report
        assert "total_docs" in report
        assert "doc_coverage" in report
        assert "missing_docs" in report
        assert "untested_features" in report
        assert "suggestions" in report

    def test_analyze_total_features_positive(self, analyzer):
        report = analyzer.analyze()
        assert report["total_features"] > 0

    def test_analyze_suggestions_have_priority(self, analyzer):
        report = analyzer.analyze()
        for s in report["suggestions"]:
            assert s["priority"] in ("high", "medium", "low")
            assert "command" in s
            assert "reason" in s

    def test_analyze_suggestions_sorted_by_priority(self, analyzer):
        report = analyzer.analyze()
        priority_order = {"high": 0, "medium": 1, "low": 2}
        priorities = [priority_order[s["priority"]] for s in report["suggestions"]]
        assert priorities == sorted(priorities)

    def test_existing_docs_counted(self, analyzer):
        report = analyzer.analyze()
        assert report["total_docs"] > 0

    def test_print_report_no_crash(self, analyzer, capsys):
        report = analyzer.analyze()
        analyzer.print_report(report)
        captured = capsys.readouterr()
        assert "Feature Documentation Gap Analysis" in captured.out


class TestUpstreamImpact:
    @pytest.fixture
    def agent(self):
        return FeatureGuard(BASE_DIR, verbose=False)

    def test_dockerfile_affects_fips(self, agent):
        changed = ["stolostron/Dockerfile.stolostron"]
        affected = agent.detect_upstream_impact(changed)
        assert "fips" in affected

    def test_dockerfile_does_not_affect_etcd_kms(self, agent):
        changed = ["stolostron/Dockerfile.stolostron"]
        affected = agent.detect_upstream_impact(changed)
        assert "etcd_kms" not in affected

    def test_rosacontrolplane_types_affects_multiple(self, agent):
        changed = ["controlplane/rosa/api/v1beta2/rosacontrolplane_types.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "fips" in affected
        assert "etcd_kms" in affected
        assert "external_oidc" in affected
        assert "no_cni" in affected
        assert "private_network" in affected
        assert "security_groups" not in affected

    def test_rosamachinepool_types_affects_mp_features(self, agent):
        changed = ["exp/api/v1beta2/rosamachinepool_types.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "security_groups" in affected
        assert "parallel_upgrade" in affected
        assert "disk_size" in affected
        assert "fips" not in affected

    def test_external_auth_types_affects_oidc(self, agent):
        changed = ["controlplane/rosa/api/v1beta2/external_auth_types.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "external_oidc" in affected
        assert "fips" not in affected

    def test_controller_glob_matches(self, agent):
        changed = ["controlplane/rosa/controllers/rosacontrolplane_controller.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "fips" in affected
        assert "etcd_kms" in affected

    def test_exp_controller_glob_matches(self, agent):
        changed = ["exp/controllers/rosamachinepool_controller.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "security_groups" in affected
        assert "parallel_upgrade" in affected

    def test_unrelated_file_no_impact(self, agent):
        changed = ["README.md", "go.mod", "hack/tools.go"]
        affected = agent.detect_upstream_impact(changed)
        assert len(affected) == 0

    def test_webhook_affects_all_cp_features(self, agent):
        changed = ["controlplane/rosa/api/v1beta2/rosacontrolplane_webhook.go"]
        affected = agent.detect_upstream_impact(changed)
        assert len(affected) > 5

    def test_network_pkg_affects_networking_features(self, agent):
        changed = ["pkg/cloud/services/network/subnets.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "no_cni" in affected
        assert "private_network" in affected
        assert "availability_zones" in affected

    def test_kms_pkg_affects_etcd_kms(self, agent):
        changed = ["pkg/cloud/services/kms/kms.go"]
        affected = agent.detect_upstream_impact(changed)
        assert "etcd_kms" in affected
        assert "security_groups" not in affected

    def test_parse_pr_url(self):
        repo, num = FeatureGuard._parse_pr_url(
            "https://github.com/stolostron/cluster-api-provider-aws/pull/102"
        )
        assert repo == "stolostron/cluster-api-provider-aws"
        assert num == "102"

    def test_parse_pr_url_invalid(self):
        repo, num = FeatureGuard._parse_pr_url("https://example.com/foo")
        assert repo is None
        assert num is None

    def test_pr102_simulation(self, agent):
        changed = ["stolostron/Dockerfile.stolostron"]
        affected = agent.detect_upstream_impact(changed)
        assert "fips" in affected
        assert len(affected) == 1

    def test_rosa_service_pkg_is_shared(self, agent):
        changed = ["pkg/cloud/services/rosa/nodepools.go"]
        affected = agent.detect_upstream_impact(changed)
        assert len(affected) > 5


class TestCheckUpstream:
    @pytest.fixture
    def agent(self, tmp_path):
        a = FeatureGuard(BASE_DIR, verbose=False)
        a.tracker_path = tmp_path / "doc_tracker.json"
        a._tracker = None
        return a

    def test_check_upstream_up_to_date(self, agent):
        agent._tracker = {
            "features": {},
            "update_history": [],
            "upstream_last_sha": {"test/repo": "abc123"},
        }
        with patch.object(FeatureGuard, '_fetch_branch_sha', return_value="abc123"):
            result = agent.check_upstream(repo="test/repo", branch="main")
        assert result["status"] == "up_to_date"
        assert result["affected"] == {}

    def test_check_upstream_new_changes(self, agent):
        agent._tracker = {
            "features": {},
            "update_history": [],
            "upstream_last_sha": {"test/repo": "old_sha"},
        }
        with patch.object(FeatureGuard, '_fetch_branch_sha', return_value="new_sha"), \
             patch.object(FeatureGuard, '_fetch_commit_diff',
                          return_value=["stolostron/Dockerfile.stolostron"]):
            result = agent.check_upstream(repo="test/repo", branch="main")
        assert result["status"] == "new_changes"
        assert result["features_affected"] == 1
        assert "fips" in result["affected"]

    def test_check_upstream_first_run(self, agent):
        with patch.object(FeatureGuard, '_fetch_branch_sha', return_value="sha123"), \
             patch.object(FeatureGuard, '_fetch_recent_pr_files',
                          return_value=["exp/api/v1beta2/rosamachinepool_types.go"]):
            result = agent.check_upstream(repo="test/repo", branch="main")
        assert result["status"] == "new_changes"
        assert result["old_sha"] is None
        assert "security_groups" in result["affected"]

    def test_check_upstream_saves_sha(self, agent):
        with patch.object(FeatureGuard, '_fetch_branch_sha', return_value="sha999"), \
             patch.object(FeatureGuard, '_fetch_recent_pr_files', return_value=[]):
            agent.check_upstream(repo="test/repo", branch="main")
        assert agent.tracker["upstream_last_sha"]["test/repo"] == "sha999"

    def test_check_upstream_marks_features_stale(self, agent):
        agent._tracker = {
            "features": {},
            "update_history": [],
            "upstream_last_sha": {"test/repo": "old"},
        }
        with patch.object(FeatureGuard, '_fetch_branch_sha', return_value="new"), \
             patch.object(FeatureGuard, '_fetch_commit_diff',
                          return_value=["controlplane/rosa/api/v1beta2/rosacontrolplane_types.go"]):
            result = agent.check_upstream(repo="test/repo", branch="main")
        for feat_id in result["affected"]:
            entry = agent.tracker["features"][feat_id]
            assert entry["upstream_stale"] is True
            assert "upstream_stale_since" in entry

    def test_check_upstream_error_no_sha(self, agent):
        with patch.object(FeatureGuard, '_fetch_branch_sha', return_value=None):
            result = agent.check_upstream(repo="test/repo", branch="main")
        assert "error" in result


class TestCheckAll:
    @pytest.fixture
    def agent(self, tmp_path):
        a = FeatureGuard(BASE_DIR, verbose=False)
        a.tracker_path = tmp_path / "doc_tracker.json"
        a.docs_dir = tmp_path / "features"
        a.docs_dir.mkdir()
        a.kb_dir = tmp_path
        a._tracker = None
        return a

    def test_check_all_returns_structure(self, agent):
        with patch.object(agent, 'detect_stale_docs', return_value={}), \
             patch.object(agent, 'check_upstream', return_value={"status": "up_to_date", "sha": "abc123", "affected": {}}):
            result = agent.check_all()
        
        assert "local_stale" in result
        assert "upstream_stale" in result
        assert "both_stale" in result
        assert "all_clear" in result
        assert "upstream_status" in result
        assert "upstream_sha" in result
        assert "suggestions" in result

    def test_check_all_no_changes(self, agent):
        with patch.object(agent, 'detect_stale_docs', return_value={}), \
             patch.object(agent, 'check_upstream', return_value={"status": "up_to_date", "sha": "abc123", "affected": {}}):
            result = agent.check_all()
        
        assert result["local_stale"] == {}
        assert result["upstream_stale"] == {}
        assert result["both_stale"] == []
        assert len(result["all_clear"]) > 0
        assert result["upstream_status"] == "up_to_date"
        assert result["upstream_sha"] == "abc123"
        assert result["suggestions"] == []

    def test_check_all_local_changes_only(self, agent):
        local_stale = {"security_groups": ["tasks/create_security_group.yml"]}
        with patch.object(agent, 'detect_stale_docs', return_value=local_stale), \
             patch.object(agent, 'check_upstream', return_value={"status": "up_to_date", "sha": "abc123", "affected": {}}):
            result = agent.check_all()
        
        assert result["local_stale"] == local_stale
        assert result["upstream_stale"] == {}
        assert result["both_stale"] == []
        assert "security_groups" not in result["all_clear"]
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["source"] == "local"
        assert result["suggestions"][0]["feature_id"] == "security_groups"

    def test_check_all_upstream_changes_only(self, agent):
        upstream_stale = {"fips": ["stolostron/Dockerfile.stolostron"]}
        upstream_result = {"status": "new_changes", "new_sha": "def456", "affected": upstream_stale}
        with patch.object(agent, 'detect_stale_docs', return_value={}), \
             patch.object(agent, 'check_upstream', return_value=upstream_result):
            result = agent.check_all()
        
        assert result["local_stale"] == {}
        assert result["upstream_stale"] == upstream_stale
        assert result["both_stale"] == []
        assert "fips" not in result["all_clear"]
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["source"] == "upstream"
        assert result["suggestions"][0]["feature_id"] == "fips"

    def test_check_all_both_changes(self, agent):
        local_stale = {"security_groups": ["tasks/create_security_group.yml"]}
        upstream_stale = {"security_groups": ["exp/api/v1beta2/rosamachinepool_types.go"]}
        upstream_result = {"status": "new_changes", "new_sha": "def456", "affected": upstream_stale}
        with patch.object(agent, 'detect_stale_docs', return_value=local_stale), \
             patch.object(agent, 'check_upstream', return_value=upstream_result):
            result = agent.check_all()
        
        assert result["local_stale"] == local_stale
        assert result["upstream_stale"] == upstream_stale
        assert "security_groups" in result["both_stale"]
        assert "security_groups" not in result["all_clear"]
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["source"] == "both"
        assert result["suggestions"][0]["feature_id"] == "security_groups"

    def test_check_all_mixed_changes(self, agent):
        local_stale = {"security_groups": ["tasks/create_security_group.yml"], "fips": ["feature_manager.py"]}
        upstream_stale = {"etcd_kms": ["pkg/cloud/services/kms/kms.go"]}
        upstream_result = {"status": "new_changes", "new_sha": "def456", "affected": upstream_stale}
        with patch.object(agent, 'detect_stale_docs', return_value=local_stale), \
             patch.object(agent, 'check_upstream', return_value=upstream_result):
            result = agent.check_all()
        
        assert len(result["local_stale"]) == 2
        assert len(result["upstream_stale"]) == 1
        assert result["both_stale"] == []
        assert len(result["suggestions"]) == 3
        
        sources = [s["source"] for s in result["suggestions"]]
        assert "local" in sources
        assert "upstream" in sources

    def test_check_all_upstream_error(self, agent):
        with patch.object(agent, 'detect_stale_docs', return_value={}), \
             patch.object(agent, 'check_upstream', return_value={"error": "Could not fetch HEAD"}):
            result = agent.check_all()
        
        assert result["upstream_status"] == "error"
        assert result["upstream_sha"] is None
        assert result["upstream_stale"] == {}

    def test_check_all_suggestions_have_commands(self, agent):
        local_stale = {"security_groups": ["tasks/create_security_group.yml"]}
        with patch.object(agent, 'detect_stale_docs', return_value=local_stale), \
             patch.object(agent, 'check_upstream', return_value={"status": "up_to_date", "sha": "abc123", "affected": {}}):
            result = agent.check_all()
        
        suggestion = result["suggestions"][0]
        assert "command" in suggestion
        assert "./run-test-suite.py" in suggestion["command"]
        assert "--feature security-groups" in suggestion["command"]
        assert "--update-docs" in suggestion["command"]


class TestAdvisories:
    @pytest.fixture
    def agent(self, tmp_path):
        a = FeatureGuard(BASE_DIR, verbose=False)
        a.kb_dir = tmp_path
        a.tracker_path = tmp_path / "doc_tracker.json"
        a._tracker = None
        return a

    def test_add_advisory_auto_match(self, agent):
        adv = agent.add_advisory("CVE-2026-0001", "FIPS crypto module vulnerability", "")
        assert "fips" in adv["features"]
        assert adv["resolved"] is False

    def test_add_advisory_manual_features(self, agent):
        adv = agent.add_advisory("CVE-2026-0002", "Some issue", "",
                                 features=["etcd_kms", "fips"])
        assert adv["features"] == ["etcd_kms", "fips"]

    def test_add_advisory_with_url(self, agent):
        adv = agent.add_advisory("CVE-2026-0003", "KMS key rotation issue", "",
                                 url="https://access.redhat.com/security/cve/CVE-2026-0003")
        assert adv["url"] == "https://access.redhat.com/security/cve/CVE-2026-0003"
        assert "etcd_kms" in adv["features"]

    def test_advisory_persists(self, agent):
        agent.add_advisory("CVE-2026-0001", "FIPS issue", "")
        advisories = agent._load_advisories()
        assert len(advisories) == 1
        assert advisories[0]["id"] == "CVE-2026-0001"

    def test_advisory_dedup_by_id(self, agent):
        agent.add_advisory("CVE-2026-0001", "Old title", "")
        agent.add_advisory("CVE-2026-0001", "New title", "")
        advisories = agent._load_advisories()
        assert len(advisories) == 1
        assert advisories[0]["title"] == "New title"

    def test_resolve_advisory(self, agent):
        agent.add_advisory("CVE-2026-0001", "FIPS issue", "")
        ok = agent.resolve_advisory("CVE-2026-0001")
        assert ok
        active = agent.get_active_advisories()
        assert len(active) == 0

    def test_resolve_nonexistent(self, agent):
        ok = agent.resolve_advisory("CVE-NOPE")
        assert not ok

    def test_get_active_advisories(self, agent):
        agent.add_advisory("CVE-1", "FIPS crypto issue", "")
        agent.add_advisory("CVE-2", "etcd encryption bug", "")
        agent.resolve_advisory("CVE-1")
        active = agent.get_active_advisories()
        assert len(active) == 1
        assert active[0]["id"] == "CVE-2"

    def test_get_advisory_affected_features(self, agent):
        agent.add_advisory("CVE-1", "FIPS crypto issue", "", severity="critical")
        agent.add_advisory("CVE-2", "Security group firewall rule bypass", "", severity="high")
        affected = agent.get_advisory_affected_features()
        assert "fips" in affected
        assert "security_groups" in affected
        assert affected["fips"][0]["severity"] == "critical"

    def test_match_advisory_keywords_etcd(self):
        matched = FeatureGuard._match_advisory_to_features(
            "etcd data encryption at rest vulnerability"
        )
        assert "etcd_kms" in matched

    def test_match_advisory_keywords_oidc(self):
        matched = FeatureGuard._match_advisory_to_features(
            "OpenID Connect token validation bypass"
        )
        assert "external_oidc" in matched

    def test_match_advisory_keywords_multiple(self):
        matched = FeatureGuard._match_advisory_to_features(
            "FIPS cryptographic module and KMS key rotation issue"
        )
        assert "fips" in matched
        assert "etcd_kms" in matched

    def test_match_advisory_no_match(self):
        matched = FeatureGuard._match_advisory_to_features(
            "Unrelated Go compiler bug"
        )
        assert matched == []

    def test_advisory_in_check_all(self, agent):
        agent.add_advisory("CVE-1", "FIPS crypto issue", "", severity="critical")
        with patch.object(agent, 'detect_stale_docs', return_value={}), \
             patch.object(agent, 'check_upstream', return_value={"status": "up_to_date", "sha": "abc", "affected": {}}):
            result = agent.check_all()
        assert "advisory_affected" in result
        assert "fips" in result["advisory_affected"]
        assert "fips" not in result["all_clear"]
        adv_suggestions = [s for s in result["suggestions"] if s["source"] == "advisory"]
        assert len(adv_suggestions) == 1
        assert "CRITICAL" in adv_suggestions[0]["action"]

    def test_advisory_severity_levels(self, agent):
        agent.add_advisory("CVE-1", "FIPS issue", "", severity="critical")
        agent.add_advisory("CVE-2", "CNI plugin issue", "", severity="low")
        affected = agent.get_advisory_affected_features()
        assert affected["fips"][0]["severity"] == "critical"
        assert affected["no_cni"][0]["severity"] == "low"


class TestAdvisoryScanning:
    @pytest.fixture
    def agent(self, tmp_path):
        a = FeatureGuard(BASE_DIR, verbose=False)
        a.kb_dir = tmp_path
        a.tracker_path = tmp_path / "doc_tracker.json"
        a._tracker = {"features": {}, "update_history": []}
        return a

    @pytest.fixture
    def mock_redhat_response(self):
        return [
            {
                "id": "CVE-2026-0001",
                "title": "FIPS cryptographic module vulnerability allows bypass",
                "description": "FIPS crypto bypass",
                "severity": "high",
                "url": "https://access.redhat.com/security/cve/CVE-2026-0001",
                "source": "redhat"
            },
            {
                "id": "CVE-2026-0002", 
                "title": "etcd encryption at rest key rotation issue",
                "description": "etcd key rotation",
                "severity": "medium",
                "url": "https://access.redhat.com/security/cve/CVE-2026-0002",
                "source": "redhat"
            },
            {
                "id": "CVE-2026-0003",
                "title": "Unrelated Go compiler bug",
                "description": "Go compiler issue",
                "severity": "low",
                "url": "https://access.redhat.com/security/cve/CVE-2026-0003",
                "source": "redhat"
            }
        ]

    @pytest.fixture 
    def mock_github_response(self):
        return [
            {
                "id": "GHSA-2026-0001",
                "title": "Security groups bypass in cluster-api-provider-aws",
                "description": "Additional security groups validation can be bypassed",
                "severity": "high",
                "url": "https://github.com/advisories/GHSA-2026-0001",
                "source": "github"
            }
        ]

    def test_advisory_scan_default_date(self, agent):
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        expected_since = (datetime.now() - timedelta(days=30)).date().strftime("%Y-%m-%d")
        assert result["since"] == expected_since
        assert not result["dry_run"]

    def test_advisory_scan_custom_date(self, agent):
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan(since="2026-01-01")
        
        assert result["since"] == "2026-01-01"

    def test_advisory_scan_invalid_date(self, agent):
        result = agent.advisory_scan(since="invalid-date")
        assert "error" in result
        assert "Invalid date format" in result["error"]

    def test_advisory_scan_last_scan_date(self, agent):
        last_scan = (datetime.now() - timedelta(days=7)).isoformat()
        agent._tracker["advisory_last_scan"] = last_scan
        
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        expected_since = datetime.fromisoformat(last_scan).date().strftime("%Y-%m-%d")
        assert result["since"] == expected_since

    def test_advisory_scan_dry_run(self, agent, mock_redhat_response):
        with patch.object(agent, '_scan_redhat_security_api', return_value=mock_redhat_response), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]), \
             patch.object(agent, 'add_advisory') as mock_add:
            result = agent.advisory_scan(dry_run=True)
        
        assert result["dry_run"] is True
        assert len(result["added"]) == 2
        assert "CVE-2026-0001" in [a["id"] for a in result["added"]]
        assert "CVE-2026-0002" in [a["id"] for a in result["added"]]
        assert len(result["skipped"]) == 1
        mock_add.assert_not_called()

    def test_advisory_scan_adds_matching_cves(self, agent, mock_redhat_response):
        with patch.object(agent, '_scan_redhat_security_api', return_value=mock_redhat_response), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]), \
             patch.object(agent, 'add_advisory') as mock_add:
            result = agent.advisory_scan()
        
        assert len(result["added"]) == 2
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "no matching features"
        assert mock_add.call_count == 2

    def test_advisory_scan_skips_existing(self, agent):
        agent.add_advisory("CVE-2026-0001", "FIPS issue", "")
        
        mock_response = [{
            "id": "CVE-2026-0001",
            "title": "FIPS issue",
            "description": "FIPS issue",
            "severity": "high",
            "url": "https://example.com",
            "source": "redhat"
        }]
        
        with patch.object(agent, '_scan_redhat_security_api', return_value=mock_response), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        assert len(result["added"]) == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "already exists"

    def test_advisory_scan_github_integration(self, agent, mock_github_response):
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=mock_github_response):
            result = agent.advisory_scan()
        
        assert len(result["github_advisories"]) == 1
        assert len(result["added"]) == 1
        added = result["added"][0]
        assert added["id"] == "GHSA-2026-0001"
        assert "security_groups" in added["features"]

    def test_advisory_scan_updates_tracker(self, agent):
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        assert "advisory_last_scan" in agent.tracker
        scan_time = datetime.fromisoformat(agent.tracker["advisory_last_scan"])
        assert (datetime.now() - scan_time).total_seconds() < 5

    def test_advisory_scan_handles_api_errors(self, agent):
        with patch.object(agent, '_scan_redhat_security_api', side_effect=Exception("API down")), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        assert len(result["errors"]) == 1
        assert "Red Hat API error: API down" in result["errors"]

    def test_scan_redhat_security_api(self, agent):
        mock_response = json.dumps([{
            "CVE": "CVE-2026-0001",
            "severity": "important",
            "bugzilla_description": "FIPS cryptographic module issue",
            "resource_url": "https://example.com"
        }]).encode('utf-8')
        
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response_obj = MagicMock()
            mock_response_obj.read.return_value = mock_response
            mock_urlopen.return_value.__enter__.return_value = mock_response_obj
            
            cves = agent._scan_redhat_security_api("2026-01-01")
        
        assert len(cves) == 2
        assert cves[0]["id"] == "CVE-2026-0001"
        assert cves[0]["severity"] == "high"
        assert cves[0]["source"] == "redhat"

    def test_scan_redhat_security_api_timeout(self, agent):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError("timeout")):
            with pytest.raises(urllib.error.URLError):
                agent._scan_redhat_security_api("2026-01-01")

    def test_scan_github_security_advisories_repo_method(self, agent):
        mock_subprocess_output = "GHSA-2026-0001\nGHSA-2026-0002"
        advisory_detail = json.dumps({
            "ghsa_id": "GHSA-2026-0001",
            "summary": "Security groups issue",
            "description": "Additional security groups bypass",
            "severity": "high", 
            "html_url": "https://github.com/advisories/GHSA-2026-0001"
        })
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=mock_subprocess_output),
                MagicMock(returncode=0, stdout=advisory_detail),
                MagicMock(returncode=0, stdout='{"ghsa_id": "GHSA-2026-0002", "summary": "other", "severity": "low"}')
            ]
            
            advisories = agent._scan_github_security_advisories()
        
        assert len(advisories) >= 1
        assert advisories[0]["id"] == "GHSA-2026-0001"
        assert advisories[0]["severity"] == "high"

    def test_scan_github_security_advisories_fallback_method(self, agent):
        global_advisory_response = json.dumps([{
            "ghsa_id": "GHSA-2026-0001", 
            "summary": "Go module issue",
            "description": "cluster-api-provider-aws vulnerability",
            "severity": "medium",
            "html_url": "https://github.com/advisories/GHSA-2026-0001"
        }])
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1, stdout="", stderr="repo method failed"),
                MagicMock(returncode=0, stdout=global_advisory_response)
            ]
            
            advisories = agent._scan_github_security_advisories()
        
        assert len(advisories) == 1
        assert advisories[0]["id"] == "GHSA-2026-0001"

    def test_map_redhat_severity(self):
        assert FeatureGuard._map_redhat_severity("critical") == "critical"
        assert FeatureGuard._map_redhat_severity("important") == "high"
        assert FeatureGuard._map_redhat_severity("moderate") == "medium" 
        assert FeatureGuard._map_redhat_severity("low") == "low"
        assert FeatureGuard._map_redhat_severity("unknown") == "medium"
        assert FeatureGuard._map_redhat_severity("") == "medium"

    def test_advisory_scan_integration_with_existing_features(self, agent, mock_redhat_response, mock_github_response):
        agent.add_advisory("CVE-EXISTING", "Previous FIPS issue", "", severity="medium")
        
        with patch.object(agent, '_scan_redhat_security_api', return_value=mock_redhat_response), \
             patch.object(agent, '_scan_github_security_advisories', return_value=mock_github_response):
            result = agent.advisory_scan()
        
        all_advisories = agent._load_advisories()
        assert len(all_advisories) == 4
        
        fips_advisories = [a for a in all_advisories if "fips" in a.get("features", [])]
        assert len(fips_advisories) == 2
        
        sg_advisories = [a for a in all_advisories if "security_groups" in a.get("features", [])]
        assert len(sg_advisories) == 1

    def test_advisory_scan_feature_matching_edge_cases(self, agent):
        edge_case_cves = [{
            "id": "CVE-2026-MULTI",
            "title": "FIPS cryptographic module and etcd encryption at rest vulnerability",
            "description": "FIPS cryptographic module and etcd encryption at rest vulnerability",
            "severity": "critical",
            "url": "https://example.com",
            "source": "redhat"
        }]
        
        with patch.object(agent, '_scan_redhat_security_api', return_value=edge_case_cves), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        added = result["added"][0]
        assert "fips" in added["features"]
        assert "etcd_kms" in added["features"]
        assert len(added["features"]) == 2

    def test_advisory_scan_handles_empty_responses(self, agent):
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            result = agent.advisory_scan()
        
        assert result["redhat_cves"] == []
        assert result["github_advisories"] == []
        assert result["added"] == []
        assert result["skipped"] == []
        assert result["errors"] == []

    def test_advisory_scan_preserves_existing_tracker_data(self, agent):
        original_data = {
            "features": {"fips": {"last_updated": "2026-01-01"}},
            "update_history": [{"test": "data"}],
            "upstream_checks": [{"test": "check"}]
        }
        agent._tracker = original_data.copy()
        
        with patch.object(agent, '_scan_redhat_security_api', return_value=[]), \
             patch.object(agent, '_scan_github_security_advisories', return_value=[]):
            agent.advisory_scan()
        
        assert agent.tracker["features"]["fips"]["last_updated"] == "2026-01-01"
        assert len(agent.tracker["update_history"]) == 1
        assert len(agent.tracker["upstream_checks"]) == 1
        assert "advisory_last_scan" in agent.tracker


class TestAutoTest:
    @pytest.fixture
    def agent(self, tmp_path):
        a = FeatureGuard(BASE_DIR, verbose=False)
        a.tracker_path = tmp_path / "doc_tracker.json"
        a._tracker = {"features": {}, "update_history": []}
        return a

    def test_run_auto_test_no_features(self, agent):
        result = agent.run_auto_test([])
        assert not result["success"]
        assert "No features specified" in result["message"]
        assert result["duration"] == 0

    def test_run_auto_test_dry_run(self, agent):
        feature_ids = ["security_groups", "fips"]
        result = agent.run_auto_test(feature_ids, dry_run=True)
        
        assert result["success"]
        assert result["dry_run"]
        assert "Would execute" in result["message"]
        assert result["duration"] == 0
        expected_cmd = "./run-test-suite.py 20-rosa-hcp-provision --feature security-groups --feature fips --update-docs"
        assert result["command"] == expected_cmd

    def test_run_auto_test_single_feature_dry_run(self, agent):
        result = agent.run_auto_test(["etcd_kms"], dry_run=True)
        
        assert result["success"]
        assert result["dry_run"]
        expected_cmd = "./run-test-suite.py 20-rosa-hcp-provision --feature etcd-kms --update-docs"
        assert result["command"] == expected_cmd

    def test_run_auto_test_success(self, agent):
        feature_ids = ["security_groups"]
        
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [
            "Starting test execution...\n",
            "Running playbook: provision\n", 
            "Test completed successfully\n",
            ""
        ]
        mock_process.wait.return_value = 0
        
        with patch('subprocess.Popen', return_value=mock_process):
            result = agent.run_auto_test(feature_ids)
        
        assert result["success"]
        assert "completed successfully" in result["message"]
        assert result["features"] == feature_ids
        assert result["exit_code"] == 0
        assert "duration" in result
        assert "command" in result

    def test_run_auto_test_failure(self, agent):
        feature_ids = ["security_groups"]
        
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [
            "Starting test execution...\n",
            "Error: Test failed\n",
            ""
        ]
        mock_process.wait.return_value = 1
        
        with patch('subprocess.Popen', return_value=mock_process):
            result = agent.run_auto_test(feature_ids)
        
        assert not result["success"]
        assert "failed" in result["message"]
        assert result["exit_code"] == 1
        assert result["features"] == feature_ids

    def test_run_auto_test_subprocess_exception(self, agent):
        feature_ids = ["security_groups"]
        
        with patch('subprocess.Popen', side_effect=FileNotFoundError("Command not found")):
            result = agent.run_auto_test(feature_ids)
        
        assert not result["success"]
        assert "Failed to execute auto-test" in result["message"]
        assert result["exit_code"] == -1
        assert "duration" in result

    def test_run_auto_test_tracks_history(self, agent):
        feature_ids = ["security_groups"]
        
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = ["Test output\n", ""]
        mock_process.wait.return_value = 0
        
        with patch('subprocess.Popen', return_value=mock_process):
            result = agent.run_auto_test(feature_ids)
        
        assert "auto_test_history" in agent.tracker
        history = agent.tracker["auto_test_history"]
        assert len(history) == 1
        
        entry = history[0]
        assert entry["features"] == feature_ids
        assert entry["success"] is True
        assert entry["exit_code"] == 0
        assert "timestamp" in entry
        assert "duration" in entry
        assert "command" in entry

    def test_run_auto_test_multiple_features(self, agent):
        feature_ids = ["security_groups", "fips", "etcd_kms"]
        
        result = agent.run_auto_test(feature_ids, dry_run=True)
        
        expected_cmd = "./run-test-suite.py 20-rosa-hcp-provision --feature security-groups --feature fips --feature etcd-kms --update-docs"
        assert result["command"] == expected_cmd

    def test_run_auto_test_custom_suite_id(self, agent):
        feature_ids = ["security_groups"]
        
        result = agent.run_auto_test(feature_ids, dry_run=True, suite_id="custom-suite")
        
        expected_cmd = "./run-test-suite.py custom-suite --feature security-groups --update-docs"
        assert result["command"] == expected_cmd

    def test_run_auto_test_underscore_to_dash_conversion(self, agent):
        feature_ids = ["etcd_kms", "no_cni", "private_network"]
        
        result = agent.run_auto_test(feature_ids, dry_run=True)
        
        expected_cmd = "./run-test-suite.py 20-rosa-hcp-provision --feature etcd-kms --feature no-cni --feature private-network --update-docs"
        assert result["command"] == expected_cmd

    def test_run_auto_test_preserves_existing_tracker_data(self, agent):
        agent._tracker = {
            "features": {"existing": {"last_updated": "2026-01-01"}},
            "update_history": [{"existing": "data"}],
            "auto_test_history": [{"previous": "test"}]
        }
        
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = ["output\n", ""]
        mock_process.wait.return_value = 0
        
        with patch('subprocess.Popen', return_value=mock_process):
            agent.run_auto_test(["security_groups"])
        
        assert len(agent.tracker["auto_test_history"]) == 2
        assert agent.tracker["features"]["existing"]["last_updated"] == "2026-01-01"
        assert len(agent.tracker["update_history"]) == 1

    def test_run_auto_test_real_time_output(self, agent, capsys):
        feature_ids = ["security_groups"]
        
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [
            "Line 1\n",
            "Line 2\n",
            "Line 3\n",
            ""
        ]
        mock_process.wait.return_value = 0
        
        with patch('subprocess.Popen', return_value=mock_process):
            agent.run_auto_test(feature_ids)
        
        captured = capsys.readouterr()
        assert "Line 1" in captured.out
        assert "Line 2" in captured.out
        assert "Line 3" in captured.out
