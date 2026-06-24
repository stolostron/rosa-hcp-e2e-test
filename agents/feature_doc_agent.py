"""
Feature Documentation Agent
============================

Manages the lifecycle of per-feature documentation pages:
  1. Detects code changes that affect a feature and flags the doc as stale.
  2. Injects live test results into feature docs with automatic redaction.
  3. Analyzes coverage gaps and suggests new feature tests.

Integrates with the existing BaseAgent framework and FeatureManager.

Author: Tina Fitzgerald
"""

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base_agent import BaseAgent

REDACTION_PATTERNS: List[Tuple[str, str]] = [
    (r'arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s,\]"]+', "arn:aws:***:***:***:***"),
    (r'sg-[0-9a-f]{8,17}', "sg-<id>"),
    (r'vpc-[0-9a-f]{8,17}', "vpc-<id>"),
    (r'subnet-[0-9a-f]{8,17}', "subnet-<id>"),
    (r'igw-[0-9a-f]{8,17}', "igw-<id>"),
    (r'nat-[0-9a-f]{8,17}', "nat-<id>"),
    (r'rtb-[0-9a-f]{8,17}', "rtb-<id>"),
    (r'eni-[0-9a-f]{8,17}', "eni-<id>"),
    (r'i-[0-9a-f]{8,17}', "i-<id>"),
    (r'ami-[0-9a-f]{8,17}', "ami-<id>"),
    (r'vol-[0-9a-f]{8,17}', "vol-<id>"),
    (r'snap-[0-9a-f]{8,17}', "snap-<id>"),
    (r'AKIA[0-9A-Z]{16}', "<access-key-id>"),
    (r'https?://api\.[a-z0-9.-]+\.openshiftapps\.com[^\s]*', "https://api.<cluster>.<domain>:443"),
    (r'https?://console-openshift-console\.[a-z0-9.-]+\.openshiftapps\.com[^\s]*', "https://console.<cluster>.<domain>"),
    (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', "<uuid>"),
    (r'\b\d{12}\b(?=\s|$|[,\]}])', "<account-id>"),
]

FEATURE_FILE_PATTERNS: Dict[str, List[str]] = {
    "security_groups": [
        "tasks/create_security_group.yml",
        "tasks/delete_security_group.yml",
    ],
    "etcd_kms": [],
    "fips": [],
    "external_oidc": [],
    "no_cni": [],
    "private_network": [],
}

SHARED_FILE_PATTERNS: List[str] = [
    "tasks/provision_rosa_hcp_with_automation.yml",
    "tasks/delete_rosa_hcp_resources.yml",
    "tasks/create_rosa_control_plane_versioned.yml",
    "feature_manager.py",
    "templates/schemas/feature-registry.yml",
    "templates/versions/*/features/*.yaml.j2",
]

IGNORED_PATH_PREFIXES: List[str] = [
    "tests/",
    "docs/",
    "scripts/",
    "agents/",
    "test-results/",
    ".github/",
]

ADVISORY_KEYWORD_MAP: Dict[str, List[str]] = {
    "fips": ["fips", "fips-140", "fips 140", "cryptographic", "crypto module"],
    "etcd_kms": ["etcd", "kms", "encryption at rest", "etcdEncryptionKMS"],
    "security_groups": ["security group", "securitygroup", "additionalSecurityGroups", "firewall rule"],
    "external_oidc": ["oidc", "openid connect", "external auth", "identity provider", "oauth"],
    "no_cni": ["cni", "network plugin", "networkType", "cilium", "calico", "ovn"],
    "private_network": ["private cluster", "endpoint access", "private endpoint", "endpointAccess"],
    "additional_tags": ["resource tag", "additionalTags", "aws tag"],
    "domain_prefix": ["domain prefix", "domainPrefix", "dns"],
    "channel_group": ["channel group", "channelGroup", "upgrade channel"],
    "image_registry": ["image registry", "registry config", "clusterRegistryConfig", "container registry"],
    "parallel_upgrade": ["rolling update", "node upgrade", "rollingUpdate", "maxSurge", "maxUnavailable"],
    "disk_size": ["disk size", "volume size", "volumeSize", "root volume", "ebs"],
    "availability_zones": ["availability zone", "multi-az", "az", "availabilityZones"],
    "user_agent": ["user agent", "userAgent"],
    "default_autoscaling": ["autoscal", "machine pool scaling", "defaultMachinePoolSpec"],
    "cluster_autoscaler_expander": ["cluster autoscaler", "expander", "autoscaler expander"],
    "audit_logging": ["audit log", "cloudwatch", "log forward", "cloudWatchlogForwarder"],
}

UPSTREAM_REPO = "stolostron/cluster-api-provider-aws"

UPSTREAM_FILE_MAP: Dict[str, List[str]] = {
    "fips": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "Dockerfile*",
        "stolostron/Dockerfile*",
    ],
    "etcd_kms": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/kms/*",
        "pkg/cloud/services/rosa/*",
    ],
    "security_groups": [
        "exp/api/v1beta2/rosamachinepool_types.go",
        "exp/controllers/*",
        "exp/internal/controllers/*",
        "pkg/cloud/services/ec2/*",
        "pkg/cloud/services/securitygroup/*",
    ],
    "external_oidc": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/api/v1beta2/external_auth_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/oidc/*",
    ],
    "no_cni": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/network/*",
    ],
    "private_network": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/network/*",
        "pkg/cloud/services/ec2/*",
    ],
    "additional_tags": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/tags/*",
    ],
    "domain_prefix": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "channel_group": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "image_registry": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "parallel_upgrade": [
        "exp/api/v1beta2/rosamachinepool_types.go",
        "exp/controllers/*",
        "exp/internal/controllers/*",
    ],
    "disk_size": [
        "exp/api/v1beta2/rosamachinepool_types.go",
        "exp/controllers/*",
        "exp/internal/controllers/*",
    ],
    "availability_zones": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/network/*",
    ],
    "user_agent": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "default_autoscaling": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "cluster_autoscaler_expander": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
    ],
    "audit_logging": [
        "controlplane/rosa/api/v1beta2/rosacontrolplane_types.go",
        "controlplane/rosa/controllers/*",
        "controlplane/rosa/internal/controllers/*",
        "pkg/cloud/services/cloudwatch/*",
    ],
}

UPSTREAM_SHARED_PATTERNS: List[str] = [
    "controlplane/rosa/api/v1beta2/rosacontrolplane_webhook.go",
    "exp/internal/webhooks/rosamachinepool_webhook.go",
    "controlplane/rosa/api/v1beta2/defaults.go",
    "pkg/cloud/services/rosa/*",
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTION_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def redact_dict(data: dict) -> dict:
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = redact(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [
                redact(v) if isinstance(v, str) else
                redact_dict(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            result[key] = value
    return result


class FeatureDocAgent(BaseAgent):

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False):
        super().__init__("FeatureDoc", base_dir, enabled, verbose)
        self.docs_dir = base_dir / "docs" / "features"
        self.template_path = self.docs_dir / "_template.md"
        self.tracker_path = self.kb_dir / "doc_tracker.json"
        self._tracker: Optional[Dict] = None
        self._fm = None

    @property
    def feature_manager(self):
        if self._fm is None:
            from feature_manager import FeatureManager
            self._fm = FeatureManager(self.base_dir)
        return self._fm

    @property
    def tracker(self) -> Dict:
        if self._tracker is None:
            self._tracker = self._load_tracker()
        return self._tracker

    def _load_tracker(self) -> Dict:
        if self.tracker_path.exists():
            try:
                with open(self.tracker_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                self.log("Failed to load doc_tracker.json, starting fresh", "warning")
        return {"features": {}, "update_history": []}

    def _save_tracker(self):
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        with open(self.tracker_path, "w") as f:
            json.dump(self.tracker, f, indent=2)

    def _git_changed_files(self, since: str = "HEAD~1") -> List[str]:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since],
                capture_output=True, text=True, cwd=self.base_dir,
            )
            if result.returncode == 0:
                return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except FileNotFoundError:
            self.log("git not found", "warning")
        return []

    def _doc_path(self, feature_id: str) -> Path:
        slug = feature_id.replace("_", "-")
        return self.docs_dir / f"{slug}.md"

    def _feature_source_files(self, feature_id: str) -> List[str]:
        fm = self.feature_manager
        feat = fm.get_feature(feature_id)
        files: List[str] = []

        files.extend(FEATURE_FILE_PATTERNS.get(feature_id, []))

        if feat:
            resource = feat.get("resource", "")
            k8s_field = feat.get("k8s_field", "")
            var_name = fm._var_map.get(feature_id, feature_id)

            for tmpl_dir in (self.base_dir / "templates" / "versions").iterdir():
                if tmpl_dir.is_dir():
                    for tmpl_file in tmpl_dir.rglob("*.yaml.j2"):
                        try:
                            content = tmpl_file.read_text()
                            if var_name in content or feature_id in content:
                                files.append(str(tmpl_file.relative_to(self.base_dir)))
                        except OSError:
                            pass

        files.extend(SHARED_FILE_PATTERNS)
        return list(dict.fromkeys(files))

    def detect_stale_docs(self, since: str = "HEAD~1") -> Dict[str, List[str]]:
        all_changed = self._git_changed_files(since)
        changed = set(
            f for f in all_changed
            if not any(f.startswith(p) for p in IGNORED_PATH_PREFIXES)
        )
        stale: Dict[str, List[str]] = {}

        for feat_id in self.feature_manager._cli_features:
            source_files = self._feature_source_files(feat_id)
            hits = []
            for src in source_files:
                for pat in [src]:
                    if "*" in pat:
                        import fnmatch
                        hits.extend(f for f in changed if fnmatch.fnmatch(f, pat))
                    elif pat in changed:
                        hits.append(pat)
            if hits:
                stale[feat_id] = sorted(set(hits))

        return stale

    def update_live_test_record(self, feature_id: str, test_data: Dict) -> bool:
        doc_path = self._doc_path(feature_id)
        if not doc_path.exists():
            self.log(f"No doc page for {feature_id}, generating from template", "info")
            self._generate_doc_from_template(feature_id)

        try:
            content = doc_path.read_text()
        except OSError as e:
            self.log(f"Cannot read {doc_path}: {e}", "error")
            return False

        safe_data = redact_dict(test_data)
        new_record = self._render_live_test_table(safe_data)

        pattern = r'## Live Test Record\n\n\|[^#]+'
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, new_record, content, count=1, flags=re.DOTALL)
        else:
            content = content.rstrip() + "\n\n" + new_record + "\n"

        doc_path.write_text(content)
        self.log(f"Updated live test record for {feature_id}", "success")

        try:
            doc_rel = str(doc_path.relative_to(self.base_dir))
        except ValueError:
            doc_rel = str(doc_path)
        self.tracker.setdefault("features", {})[feature_id] = {
            "last_updated": datetime.now().isoformat(),
            "last_test_result": safe_data.get("result", "UNKNOWN"),
            "doc_path": doc_rel,
        }
        self.tracker.setdefault("update_history", []).append({
            "timestamp": datetime.now().isoformat(),
            "feature_id": feature_id,
            "action": "live_test_update",
            "result": safe_data.get("result", "UNKNOWN"),
        })
        self._save_tracker()
        self.record_intervention("doc_update", {"feature_id": feature_id})
        return True

    def _render_live_test_table(self, data: Dict) -> str:
        lines = [
            "## Live Test Record",
            "",
            "| Field | Value |",
            "|-------|-------|",
        ]
        field_order = [
            ("date", "Date"),
            ("hub_cluster", "Hub Cluster"),
            ("cluster_name", "Cluster Name"),
            ("ocm_id", "OCM ID"),
            ("version", "Version"),
            ("region", "Region"),
            ("api_url", "API URL"),
            ("provision_result", "Provision Result"),
            ("provision_duration", "Provision Duration"),
            ("delete_result", "Delete Result"),
            ("delete_duration", "Delete Duration"),
            ("orphan_check", "Orphan Check"),
        ]
        for key, label in field_order:
            value = data.get(key, data.get(label, ""))
            if value:
                if isinstance(value, str) and not value.startswith("`"):
                    value = f"`{value}`"
                lines.append(f"| {label} | {value} |")

        for key, value in data.items():
            normalized = key.lower().replace(" ", "_")
            if normalized not in [fo[0] for fo in field_order] and key != "result":
                if isinstance(value, str) and not value.startswith("`"):
                    value = f"`{value}`"
                lines.append(f"| {key} | {value} |")

        lines.append("")
        return "\n".join(lines)

    def _generate_doc_from_template(self, feature_id: str):
        fm = self.feature_manager
        feat = fm.get_feature(feature_id)
        if not feat:
            self.log(f"Feature {feature_id} not in registry", "error")
            return

        if self.template_path.exists():
            template = self.template_path.read_text()
        else:
            template = "# {version} Feature Testing: {feature_name}\n\n(generated stub)\n"

        cli_alias = feature_id.replace("_", "-")
        for alias, fid in fm._cli_aliases.items():
            if fid == feature_id:
                cli_alias = alias
                break

        var_name = fm._var_map.get(feature_id, feature_id)

        group_name = ""
        for gname, gdata in fm._feature_groups.items():
            if feature_id in gdata.get("features", []):
                group_name = gname
                break

        k8s_field = feat.get("k8s_field", "")
        k8s_short = k8s_field.rsplit(".", 1)[-1] if k8s_field else ""

        replacements = {
            "{version}": "4.22",
            "{feature_name}": feat.get("name", feature_id),
            "{feature_id}": feature_id,
            "{cli_alias}": cli_alias,
            "{category}": feat.get("suite_name", ""),
            "{phase}": feat.get("phase", "Day1"),
            "{feature_type}": feat.get("type", "boolean"),
            "{mutable}": "Yes" if feat.get("mutable") else "No",
            "{requires_input}": "Yes" if feat.get("requires_input") else "No",
            "{resource}": feat.get("resource", ""),
            "{k8s_field}": k8s_field,
            "{min_version}": feat.get("min_version", "4.19"),
            "{ansible_var}": var_name,
            "{description}": feat.get("description", ""),
            "{k8s_field_short}": k8s_short,
            "{rendered_value}": "<value>",
            "{verification_notes}": "TODO: Add verification steps",
            "{file_table_rows}": "| | |",
            "{test_table_rows}": "| | | |",
            "{suggested_tests}": "- Run gap analysis: `python3 scripts/update_feature_docs.py --gaps`",
            "{feature_group}": group_name,
        }

        content = template
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, str(value))

        doc_path = self._doc_path(feature_id)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content)
        self.log(f"Generated doc stub for {feature_id} at {doc_path}", "success")

    def detect_upstream_impact(self, changed_files: List[str]) -> Dict[str, List[str]]:
        import fnmatch
        affected: Dict[str, List[str]] = {}

        for feat_id, patterns in UPSTREAM_FILE_MAP.items():
            all_patterns = patterns + UPSTREAM_SHARED_PATTERNS
            hits = []
            for f in changed_files:
                for pat in all_patterns:
                    if "*" in pat:
                        if fnmatch.fnmatch(f, pat):
                            hits.append(f)
                            break
                    elif f == pat:
                        hits.append(f)
                        break
            if hits:
                affected[feat_id] = sorted(set(hits))

        return affected

    def detect_upstream_pr_impact(self, pr_url: str) -> Dict:
        owner_repo, pr_number = self._parse_pr_url(pr_url)
        if not owner_repo:
            self.log(f"Could not parse PR URL: {pr_url}", "error")
            return {"error": f"Invalid PR URL: {pr_url}"}

        changed_files = self._fetch_pr_files(owner_repo, pr_number)
        if changed_files is None:
            return {"error": f"Could not fetch files for {pr_url}"}

        affected = self.detect_upstream_impact(changed_files)

        result = {
            "pr_url": pr_url,
            "repo": owner_repo,
            "pr_number": pr_number,
            "upstream_files_changed": len(changed_files),
            "features_affected": len(affected),
            "affected": affected,
            "files": changed_files,
        }

        if affected:
            self.tracker.setdefault("upstream_checks", []).append({
                "timestamp": datetime.now().isoformat(),
                "pr_url": pr_url,
                "features_affected": sorted(affected.keys()),
            })
            self._save_tracker()

        return result

    @staticmethod
    def _parse_pr_url(url: str) -> Tuple[Optional[str], Optional[str]]:
        m = re.match(
            r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)',
            url,
        )
        if m:
            return m.group(1), m.group(2)
        return None, None

    @staticmethod
    def _fetch_pr_files(owner_repo: str, pr_number: str) -> Optional[List[str]]:
        try:
            result = subprocess.run(
                ["gh", "pr", "view", pr_number,
                 "--repo", owner_repo,
                 "--json", "files",
                 "--jq", ".[].path // .files[].path"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["gh", "api",
                     f"repos/{owner_repo}/pulls/{pr_number}/files",
                     "--jq", ".[].filename"],
                    capture_output=True, text=True, timeout=30,
                )
            if result.returncode == 0:
                return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def check_upstream(self, repo: str = UPSTREAM_REPO, branch: str = "backplane-2.11") -> Dict:
        last_checked = self.tracker.get("upstream_last_sha", {}).get(repo)

        current_sha = self._fetch_branch_sha(repo, branch)
        if not current_sha:
            self.log(f"Could not fetch HEAD SHA for {repo}:{branch}", "error")
            return {"error": f"Could not fetch HEAD for {repo}:{branch}"}

        if current_sha == last_checked:
            self.log(f"No new commits on {repo}:{branch} since last check", "info")
            return {"status": "up_to_date", "sha": current_sha, "affected": {}}

        if last_checked:
            changed_files = self._fetch_commit_diff(repo, last_checked, current_sha)
        else:
            changed_files = self._fetch_recent_pr_files(repo, branch)

        if changed_files is None:
            changed_files = []

        affected = self.detect_upstream_impact(changed_files)

        self.tracker.setdefault("upstream_last_sha", {})[repo] = current_sha
        if affected:
            self.tracker.setdefault("upstream_checks", []).append({
                "timestamp": datetime.now().isoformat(),
                "repo": repo,
                "branch": branch,
                "old_sha": last_checked,
                "new_sha": current_sha,
                "files_changed": len(changed_files),
                "features_affected": sorted(affected.keys()),
            })

            for feat_id in affected:
                entry = self.tracker.setdefault("features", {}).setdefault(feat_id, {})
                entry["upstream_stale"] = True
                entry["upstream_stale_since"] = datetime.now().isoformat()
                entry["upstream_stale_repo"] = repo
                entry["upstream_stale_files"] = affected[feat_id]

        self._save_tracker()

        return {
            "status": "new_changes",
            "repo": repo,
            "branch": branch,
            "old_sha": last_checked,
            "new_sha": current_sha,
            "files_changed": len(changed_files),
            "features_affected": len(affected),
            "affected": affected,
        }

    @staticmethod
    def _fetch_branch_sha(repo: str, branch: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/git/ref/heads/{branch}",
                 "--jq", ".object.sha"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                sha = result.stdout.strip()
                if sha:
                    return sha
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def _fetch_commit_diff(repo: str, base_sha: str, head_sha: str) -> Optional[List[str]]:
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/compare/{base_sha}...{head_sha}",
                 "--jq", ".files[].filename"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def _fetch_recent_pr_files(repo: str, branch: str, limit: int = 10) -> Optional[List[str]]:
        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--repo", repo,
                 "--base", branch, "--state", "merged",
                 "--limit", str(limit), "--json", "number",
                 "--jq", ".[].number"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return None
            pr_numbers = [l.strip() for l in result.stdout.splitlines() if l.strip()]

            all_files = set()
            for pr_num in pr_numbers:
                files = FeatureDocAgent._fetch_pr_files(repo, pr_num)
                if files:
                    all_files.update(files)
            return sorted(all_files) if all_files else []
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def refresh_stale_docs(self, since: str = "HEAD~1") -> Dict[str, List[str]]:
        stale = self.detect_stale_docs(since)
        for feat_id, changed_files in stale.items():
            self.log(f"Feature '{feat_id}' has stale docs due to: {', '.join(changed_files)}", "warning")
            entry = self.tracker.setdefault("features", {}).setdefault(feat_id, {})
            entry["stale"] = True
            entry["stale_reason"] = changed_files
            entry["stale_since"] = datetime.now().isoformat()

        if stale:
            self._save_tracker()
        return stale

    def get_doc_status(self) -> List[Dict]:
        fm = self.feature_manager
        results = []
        for feat_id in sorted(fm._cli_features):
            feat = fm.get_feature(feat_id)
            if not feat:
                continue
            doc_path = self._doc_path(feat_id)
            tracker_entry = self.tracker.get("features", {}).get(feat_id, {})
            results.append({
                "feature_id": feat_id,
                "name": feat.get("name", ""),
                "has_doc": doc_path.exists(),
                "doc_path": str(doc_path.relative_to(self.base_dir)) if doc_path.exists() else None,
                "stale": tracker_entry.get("stale", False),
                "last_updated": tracker_entry.get("last_updated"),
                "last_test_result": tracker_entry.get("last_test_result"),
            })
        return results

    def _advisories_path(self) -> Path:
        return self.kb_dir / "advisories.json"

    def _load_advisories(self) -> List[Dict]:
        path = self._advisories_path()
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_advisories(self, advisories: List[Dict]):
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        with open(self._advisories_path(), "w") as f:
            json.dump(advisories, f, indent=2)

    def add_advisory(self, advisory_id: str, title: str, description: str,
                     severity: str = "medium",
                     features: Optional[List[str]] = None,
                     url: str = "") -> Dict:
        if features:
            matched = list(features)
        else:
            matched = self._match_advisory_to_features(title + " " + description)

        advisory = {
            "id": advisory_id,
            "title": title,
            "description": description,
            "severity": severity,
            "url": url,
            "features": sorted(set(matched)),
            "added": datetime.now().isoformat(),
            "resolved": False,
        }

        advisories = self._load_advisories()
        advisories = [a for a in advisories if a["id"] != advisory_id]
        advisories.append(advisory)
        self._save_advisories(advisories)

        self.log(f"Advisory {advisory_id} added, affects: {', '.join(matched) or 'none'}", "info")
        return advisory

    def resolve_advisory(self, advisory_id: str) -> bool:
        advisories = self._load_advisories()
        for a in advisories:
            if a["id"] == advisory_id:
                a["resolved"] = True
                a["resolved_date"] = datetime.now().isoformat()
                self._save_advisories(advisories)
                self.log(f"Advisory {advisory_id} marked resolved", "success")
                return True
        return False

    def get_active_advisories(self) -> List[Dict]:
        return [a for a in self._load_advisories() if not a.get("resolved")]

    def get_advisory_affected_features(self) -> Dict[str, List[Dict]]:
        result: Dict[str, List[Dict]] = {}
        for a in self.get_active_advisories():
            for feat_id in a.get("features", []):
                result.setdefault(feat_id, []).append({
                    "id": a["id"],
                    "title": a["title"],
                    "severity": a["severity"],
                    "url": a.get("url", ""),
                })
        return result

    @staticmethod
    def _match_advisory_to_features(text: str) -> List[str]:
        text_lower = text.lower()
        matched = []
        for feat_id, keywords in ADVISORY_KEYWORD_MAP.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    matched.append(feat_id)
                    break
        return matched

    def advisory_scan(self, since: Optional[str] = None, dry_run: bool = False) -> Dict:
        if since is None:
            last_scan = self.tracker.get("advisory_last_scan")
            if last_scan:
                since_date = datetime.fromisoformat(last_scan).date()
            else:
                since_date = (datetime.now() - timedelta(days=30)).date()
            since = since_date.strftime("%Y-%m-%d")
        else:
            try:
                since_date = datetime.strptime(since, "%Y-%m-%d").date()
            except ValueError:
                return {"error": f"Invalid date format: {since}. Use YYYY-MM-DD"}

        self.log(f"Scanning for CVEs since {since}", "info")
        
        result = {
            "scan_date": datetime.now().isoformat(),
            "since": since,
            "dry_run": dry_run,
            "redhat_cves": [],
            "github_advisories": [],
            "added": [],
            "skipped": [],
            "errors": [],
        }

        existing_advisories = self._load_advisories()
        existing_ids = {a["id"] for a in existing_advisories}

        redhat_cves = []
        try:
            redhat_cves = self._scan_redhat_security_api(since)
            result["redhat_cves"] = redhat_cves
            self.log(f"Found {len(redhat_cves)} Red Hat CVEs", "info")
        except Exception as e:
            error_msg = f"Red Hat API error: {e}"
            self.log(error_msg, "warning")
            result["errors"].append(error_msg)
            result["redhat_cves"] = []

        github_advisories = []
        try:
            github_advisories = self._scan_github_security_advisories()
            result["github_advisories"] = github_advisories
            self.log(f"Found {len(github_advisories)} GitHub advisories", "info")
        except Exception as e:
            error_msg = f"GitHub API error: {e}"
            self.log(error_msg, "warning")
            result["errors"].append(error_msg)
            result["github_advisories"] = []

        all_cves = []
        for cve in redhat_cves:
            all_cves.append({
                "id": cve["id"],
                "title": cve.get("title", ""),
                "description": cve.get("description", ""),
                "severity": cve.get("severity", "medium"),
                "url": cve.get("url", ""),
                "source": cve.get("source", "redhat")
            })
        
        for advisory in github_advisories:
            all_cves.append({
                "id": advisory["id"],
                "title": advisory.get("title", ""),
                "description": advisory.get("description", ""),
                "severity": advisory.get("severity", "medium"),
                "url": advisory.get("url", ""),
                "source": advisory.get("source", "github")
            })

        for cve in all_cves:
            cve_id = cve["id"]
            
            if cve_id in existing_ids:
                result["skipped"].append({
                    "id": cve_id,
                    "reason": "already exists"
                })
                continue

            text_to_match = cve.get("title", "") + " " + cve.get("description", "")
            matched_features = self._match_advisory_to_features(text_to_match)
            
            if not matched_features:
                result["skipped"].append({
                    "id": cve_id,
                    "reason": "no matching features"
                })
                continue

            if not dry_run:
                self.add_advisory(
                    advisory_id=cve_id,
                    title=cve.get("title", ""),
                    description=cve.get("description", ""),
                    severity=cve.get("severity", "medium"),
                    features=matched_features,
                    url=cve.get("url", "")
                )

            result["added"].append({
                "id": cve_id,
                "title": cve.get("title", ""),
                "severity": cve.get("severity", "medium"),
                "features": matched_features,
                "url": cve.get("url", "")
            })

        if not dry_run:
            self.tracker["advisory_last_scan"] = datetime.now().isoformat()
            self._save_tracker()

        summary = f"Scan complete: {len(result['added'])} added, {len(result['skipped'])} skipped"
        if result["errors"]:
            summary += f", {len(result['errors'])} errors"
        self.log(summary, "success" if not result["errors"] else "warning")

        return result

    def _scan_redhat_security_api(self, since: str) -> List[Dict]:
        cves = []
        
        for product in ["OpenShift Container Platform", "Red Hat OpenShift Service on AWS"]:
            url = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
            params = {
                "product": product,
                "after": since
            }
            full_url = f"{url}?{urllib.parse.urlencode(params)}"
            
            try:
                self.log(f"Fetching CVEs for '{product}' since {since}", "info")
                with urllib.request.urlopen(full_url, timeout=30) as response:
                    data = json.loads(response.read().decode('utf-8'))
                
                for item in data:
                    severity = self._map_redhat_severity(item.get("severity", ""))
                    description = item.get("bugzilla_description", "") or item.get("synopsis", "")
                    
                    cves.append({
                        "id": item["CVE"],
                        "title": description[:100] + "..." if len(description) > 100 else description,
                        "description": description,
                        "severity": severity,
                        "url": item.get("resource_url", ""),
                        "source": "redhat"
                    })
                    
            except Exception as e:
                self.log(f"Failed to fetch Red Hat CVEs for '{product}': {e}", "warning")
                raise

        return cves

    def _scan_github_security_advisories(self) -> List[Dict]:
        advisories = []
        
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{UPSTREAM_REPO}/security-advisories",
                 "--paginate", "--jq", ".[].ghsa_id"],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode == 0:
                ghsa_ids = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
                
                for ghsa_id in ghsa_ids:
                    try:
                        detail_result = subprocess.run(
                            ["gh", "api", f"advisories/{ghsa_id}"],
                            capture_output=True, text=True, timeout=30
                        )
                        
                        if detail_result.returncode == 0:
                            advisory_data = json.loads(detail_result.stdout)
                            severity = advisory_data.get("severity", "medium").lower()
                            
                            advisories.append({
                                "id": ghsa_id,
                                "title": advisory_data.get("summary", ""),
                                "description": advisory_data.get("description", ""),
                                "severity": severity,
                                "url": advisory_data.get("html_url", ""),
                                "source": "github"
                            })
                    except (json.JSONDecodeError, subprocess.TimeoutExpired):
                        continue
                        
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        if not advisories:
            try:
                result = subprocess.run(
                    ["gh", "api", "/advisories",
                     "--field", "ecosystem=go",
                     "--field", "affects=sigs.k8s.io/cluster-api-provider-aws",
                     "--paginate"],
                    capture_output=True, text=True, timeout=60
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        data = json.loads(result.stdout)
                        if isinstance(data, list):
                            for item in data:
                                severity = item.get("severity", "medium").lower()
                                advisories.append({
                                    "id": item["ghsa_id"],
                                    "title": item.get("summary", ""),
                                    "description": item.get("description", ""),
                                    "severity": severity,
                                    "url": item.get("html_url", ""),
                                    "source": "github"
                                })
                    except json.JSONDecodeError:
                        pass
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return advisories

    @staticmethod
    def _map_redhat_severity(severity: str) -> str:
        severity_map = {
            "critical": "critical",
            "important": "high",
            "moderate": "medium", 
            "low": "low"
        }
        return severity_map.get(severity.lower(), "medium")

    def run_auto_test(self, feature_ids: List[str], dry_run: bool = False, suite_id: str = "20-rosa-hcp-provision") -> Dict:
        if not feature_ids:
            return {
                "success": False,
                "message": "No features specified for auto-test",
                "duration": 0
            }

        feature_args = []
        for feat_id in feature_ids:
            feature_args.extend(["--feature", feat_id.replace("_", "-")])

        cmd = ["./run-test-suite.py", suite_id] + feature_args + ["--update-docs"]

        if dry_run:
            return {
                "success": True,
                "message": f"Would execute: {' '.join(cmd)}",
                "command": ' '.join(cmd),
                "duration": 0,
                "dry_run": True
            }

        self.log(f"Starting auto-test for features: {', '.join(feature_ids)}", "info")
        start_time = datetime.now()

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=self.base_dir
            )

            output_lines = []
            for line in iter(process.stdout.readline, ''):
                if line:
                    stripped = line.rstrip()
                    print(stripped)
                    output_lines.append(stripped)

            process.stdout.close()
            return_code = process.wait()
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to execute auto-test: {e}",
                "duration": (datetime.now() - start_time).total_seconds(),
                "exit_code": -1
            }

        duration = (datetime.now() - start_time).total_seconds()
        success = return_code == 0

        self.tracker.setdefault("auto_test_history", []).append({
            "timestamp": start_time.isoformat(),
            "features": feature_ids,
            "command": ' '.join(cmd),
            "success": success,
            "duration": duration,
            "exit_code": return_code
        })
        self._save_tracker()

        result = {
            "success": success,
            "message": f"Auto-test {'completed successfully' if success else 'failed'}",
            "features": feature_ids,
            "duration": duration,
            "exit_code": return_code,
            "command": ' '.join(cmd)
        }

        if success:
            self.log(f"Auto-test completed successfully for {len(feature_ids)} feature(s) in {duration:.1f}s", "success")
        else:
            self.log(f"Auto-test failed after {duration:.1f}s with exit code {return_code}", "error")

        return result

    def check_all(self, since: str = "HEAD~1") -> Dict:
        local_stale = self.detect_stale_docs(since)

        upstream_result = self.check_upstream()
        upstream_status = "up_to_date"
        upstream_sha = None
        upstream_stale = {}

        if "error" in upstream_result:
            upstream_status = "error"
        else:
            upstream_status = upstream_result["status"]
            upstream_sha = upstream_result.get("new_sha") or upstream_result.get("sha")
            if upstream_result["status"] == "new_changes":
                upstream_stale = upstream_result.get("affected", {})

        advisory_affected = self.get_advisory_affected_features()

        both_stale = []
        all_clear = []

        fm = self.feature_manager
        for feat_id in fm._cli_features:
            is_local = feat_id in local_stale
            is_upstream = feat_id in upstream_stale
            is_advisory = feat_id in advisory_affected

            if is_local and is_upstream:
                both_stale.append(feat_id)
            elif not is_local and not is_upstream and not is_advisory:
                all_clear.append(feat_id)

        suggestions = []

        for feat_id, files in local_stale.items():
            source = "both" if feat_id in upstream_stale else "local"
            suggestions.append({
                "feature_id": feat_id,
                "source": source,
                "action": "Review implementation changes and update docs",
                "files_changed": files,
                "command": f"./run-test-suite.py 20-rosa-hcp-provision --feature {feat_id.replace('_', '-')} --update-docs",
            })

        for feat_id, files in upstream_stale.items():
            if feat_id not in local_stale:
                suggestions.append({
                    "feature_id": feat_id,
                    "source": "upstream",
                    "action": "Review upstream changes and test feature",
                    "files_changed": files,
                    "command": f"./run-test-suite.py 20-rosa-hcp-provision --feature {feat_id.replace('_', '-')} --update-docs",
                })

        for feat_id, advs in advisory_affected.items():
            for adv in advs:
                suggestions.append({
                    "feature_id": feat_id,
                    "source": "advisory",
                    "action": f"[{adv['severity'].upper()}] {adv['title']}",
                    "advisory_id": adv["id"],
                    "advisory_url": adv.get("url", ""),
                    "command": f"./run-test-suite.py 20-rosa-hcp-provision --feature {feat_id.replace('_', '-')} --update-docs",
                })

        return {
            "local_stale": local_stale,
            "upstream_stale": upstream_stale,
            "advisory_affected": advisory_affected,
            "both_stale": sorted(both_stale),
            "all_clear": sorted(all_clear),
            "upstream_status": upstream_status,
            "upstream_sha": upstream_sha,
            "suggestions": suggestions,
        }


class DocGapAnalyzer:

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.docs_dir = base_dir / "docs" / "features"
        self._fm = None

    @property
    def feature_manager(self):
        if self._fm is None:
            from feature_manager import FeatureManager
            self._fm = FeatureManager(self.base_dir)
        return self._fm

    def analyze(self) -> Dict:
        fm = self.feature_manager
        all_features = {}
        for feat_id in fm._features:
            all_features[feat_id] = fm.get_feature(feat_id)

        cli_features = fm._cli_features

        existing_docs = set()
        for md in self.docs_dir.glob("*.md"):
            if md.name.startswith("_"):
                continue
            slug = md.stem
            feat_id = slug.replace("-", "_")
            existing_docs.add(feat_id)

        missing_docs = sorted(cli_features - existing_docs)

        test_dir = self.base_dir / "tests"
        tested_features = set()
        if test_dir.exists():
            for test_file in test_dir.glob("test_*.py"):
                try:
                    content = test_file.read_text()
                    for feat_id in cli_features:
                        if feat_id in content:
                            tested_features.add(feat_id)
                except OSError:
                    pass

        untested = sorted(cli_features - tested_features)

        docs_without_live_record = []
        for feat_id in sorted(existing_docs & cli_features):
            doc_path = self.docs_dir / f"{feat_id.replace('_', '-')}.md"
            if doc_path.exists():
                content = doc_path.read_text()
                if "PENDING" in content or "## Live Test Record" not in content:
                    docs_without_live_record.append(feat_id)

        suggestions = self._build_suggestions(
            missing_docs, untested, docs_without_live_record, fm
        )

        return {
            "total_features": len(cli_features),
            "total_docs": len(existing_docs & cli_features),
            "doc_coverage": f"{len(existing_docs & cli_features)}/{len(cli_features)}",
            "missing_docs": missing_docs,
            "untested_features": untested,
            "docs_needing_live_data": docs_without_live_record,
            "suggestions": suggestions,
        }

    def _build_suggestions(
        self,
        missing_docs: List[str],
        untested: List[str],
        needs_live_data: List[str],
        fm,
    ) -> List[Dict]:
        suggestions = []

        for feat_id in missing_docs:
            feat = fm.get_feature(feat_id)
            suggestions.append({
                "feature_id": feat_id,
                "action": "create_doc",
                "priority": "high",
                "reason": f"No doc page exists for CLI feature '{feat_id}'",
                "command": f"python3 scripts/update_feature_docs.py --generate {feat_id}",
            })

        for feat_id in untested:
            if feat_id not in missing_docs:
                suggestions.append({
                    "feature_id": feat_id,
                    "action": "add_tests",
                    "priority": "medium",
                    "reason": f"Feature '{feat_id}' has no unit test references",
                    "command": f"Add tests for {feat_id} in tests/test_feature_manager.py",
                })

        for feat_id in needs_live_data:
            suggestions.append({
                "feature_id": feat_id,
                "action": "run_live_test",
                "priority": "medium",
                "reason": f"Doc for '{feat_id}' has no live test record or is still PENDING",
                "command": f"./run-test-suite.py 20-rosa-hcp-provision --feature {feat_id.replace('_', '-')} --update-docs",
            })

        for group_name, group_data in fm._feature_groups.items():
            group_feats = group_data.get("features", [])
            tested_in_group = [f for f in group_feats if f not in untested]
            if len(tested_in_group) > 0 and len(tested_in_group) < len(group_feats):
                missing_in_group = [f for f in group_feats if f in untested]
                suggestions.append({
                    "feature_id": group_name,
                    "action": "complete_group",
                    "priority": "low",
                    "reason": (
                        f"Group '{group_name}' is partially tested "
                        f"({len(tested_in_group)}/{len(group_feats)}). "
                        f"Missing: {', '.join(missing_in_group)}"
                    ),
                    "command": f"./run-test-suite.py 20-rosa-hcp-provision --feature-group {group_name} --update-docs",
                })

        suggestions.sort(key=lambda s: {"high": 0, "medium": 1, "low": 2}[s["priority"]])
        return suggestions

    def print_report(self, report: Optional[Dict] = None):
        if report is None:
            report = self.analyze()

        print("=" * 70)
        print("  Feature Documentation Gap Analysis")
        print("=" * 70)
        print(f"  Coverage: {report['doc_coverage']} features have doc pages")
        print()

        if report["missing_docs"]:
            print(f"  Missing docs ({len(report['missing_docs'])}):")
            for feat_id in report["missing_docs"]:
                print(f"    - {feat_id}")
            print()

        if report["untested_features"]:
            print(f"  Untested features ({len(report['untested_features'])}):")
            for feat_id in report["untested_features"]:
                print(f"    - {feat_id}")
            print()

        if report["docs_needing_live_data"]:
            print(f"  Docs needing live test data ({len(report['docs_needing_live_data'])}):")
            for feat_id in report["docs_needing_live_data"]:
                print(f"    - {feat_id}")
            print()

        if report["suggestions"]:
            print("-" * 70)
            print("  Suggested Actions")
            print("-" * 70)
            for s in report["suggestions"]:
                icon = {"high": "!!!", "medium": " ! ", "low": "   "}[s["priority"]]
                print(f"\n  [{icon}] {s['feature_id']}: {s['action']}")
                print(f"        {s['reason']}")
                print(f"        $ {s['command']}")
            print()

        print("=" * 70)
