"""
FeatureGuard
============

Manages the lifecycle of per-feature documentation pages:
  1. Detects code changes that affect a feature and flags the doc as stale.
  2. Injects live test results into feature docs with automatic redaction.
  3. Analyzes coverage gaps and suggests new feature tests.

Integrates with the existing BaseAgent framework and FeatureManager.

Author: Tina Fitzgerald
"""

import fnmatch
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base_agent import BaseAgent
from .feature_guard_constants import (
    FEATURE_FILE_PATTERNS, SHARED_FILE_PATTERNS,
    IGNORED_PATH_PREFIXES, UPSTREAM_REPO, RETENTION,
    redact, redact_dict,
)
from . import upstream_poller
from . import advisory_manager
from . import test_runner as test_runner_mod


class FeatureGuard(BaseAgent):

    def __init__(self, base_dir: Path, enabled: bool = True, verbose: bool = False):
        super().__init__("FeatureGuard", base_dir, enabled, verbose)
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
                        hits.extend(f for f in changed if fnmatch.fnmatch(f, pat))
                    elif pat in changed:
                        hits.append(pat)
            if hits:
                stale[feat_id] = sorted(set(hits))

        return stale

    def update_live_test_record(self, feature_id: str, test_data: Dict, trigger: str = "manual test") -> bool:
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
        test_date = safe_data.get("date", datetime.now().strftime("%Y-%m-%d"))
        if isinstance(test_date, str) and len(test_date) == 10:
            pass
        else:
            test_date = datetime.now().strftime("%Y-%m-%d")
        new_test_run = self._render_test_run_entry(safe_data, test_date, trigger)

        test_history_pattern = r'(## Test Run History\n\n)(.*?)(?=\n## |\n$)'
        match = re.search(test_history_pattern, content, re.DOTALL)
        
        if match:
            header = match.group(1)
            existing_content = match.group(2).strip()
            
            existing_runs = []
            if existing_content:
                run_pattern = r'### (\d{4}-\d{2}-\d{2})\n\| Field \| Value \|\n\|-------|-------\|(.*?)(?=\n### |\n$)'
                existing_runs = re.findall(run_pattern, existing_content, re.DOTALL)
            
            all_runs = [(test_date, new_test_run)] + [(date, run) for date, run in existing_runs]
            all_runs = all_runs[:RETENTION["max_test_runs"]]
            
            new_content = header
            for date, run_content in all_runs:
                new_content += f"### {date}\n| Field | Value |\n|-------|-------|{run_content}\n\n"
            
            content = re.sub(test_history_pattern, new_content.rstrip() + "\n", content, flags=re.DOTALL)
        else:
            legacy_pattern = r'## Live Test Record\n\n\|[^#]+'
            if re.search(legacy_pattern, content, re.DOTALL):
                content = re.sub(legacy_pattern, f"## Test Run History\n\n### {test_date}\n| Field | Value |\n|-------|-------|{new_test_run}\n", content, count=1, flags=re.DOTALL)
            else:
                test_section = f"""## Test Run History

### {test_date}
| Field | Value |
|-------|-------|{new_test_run}

"""
                pattern = r'(## Suggested Related Tests\n)'
                if re.search(pattern, content):
                    content = re.sub(pattern, test_section + r'\1', content)
                else:
                    content = content.rstrip() + "\n\n" + test_section

        doc_path.write_text(content)
        self.log(f"Updated live test record for {feature_id}", "success")

        try:
            doc_rel = str(doc_path.relative_to(self.base_dir))
        except ValueError:
            doc_rel = str(doc_path)
        
        tracker_entry = self.tracker.setdefault("features", {})[feature_id] = {
            "last_updated": datetime.now().isoformat(),
            "last_test_result": safe_data.get("result", "UNKNOWN"),
            "doc_path": doc_rel,
        }
        
        test_history = tracker_entry.setdefault("test_history", [])
        test_history.insert(0, {
            "timestamp": datetime.now().isoformat(),
            "date": test_date,
            "result": safe_data.get("result", "UNKNOWN"),
            "trigger": trigger,
            "test_data": safe_data
        })
        test_history = test_history[:RETENTION["max_test_runs"] * 2]
        tracker_entry["test_history"] = test_history
        
        history = self.tracker.setdefault("update_history", [])
        history.append({
            "timestamp": datetime.now().isoformat(),
            "feature_id": feature_id,
            "action": "live_test_update",
            "result": safe_data.get("result", "UNKNOWN"),
            "trigger": trigger,
        })
        self.tracker["update_history"] = history[-RETENTION["max_tracker_history"]:]
        self._save_tracker()
        self.record_intervention("doc_update", {"feature_id": feature_id})
        return True

    def _render_test_run_entry(self, data: Dict, test_date: str, trigger: str) -> str:
        lines = []
        field_order = [
            ("version", "Version"),
            ("region", "Region"),
            ("provision_result", "Provision Result"),
            ("provision_duration", "Provision Duration"),
            ("delete_result", "Delete Result"),
            ("delete_duration", "Delete Duration"),
            ("orphan_check", "Orphan Check"),
        ]
        
        for key, label in field_order:
            value = data.get(key, "")
            if value:
                if isinstance(value, str) and not value.startswith("`"):
                    value = f"`{value}`"
                lines.append(f"\n| {label} | {value} |")

        lines.append(f"\n| Trigger | {trigger} |")
        
        for key, value in data.items():
            normalized = key.lower().replace(" ", "_")
            if normalized not in [fo[0] for fo in field_order] and key not in ["result", "date"]:
                if isinstance(value, str) and not value.startswith("`"):
                    value = f"`{value}`"
                lines.append(f"\n| {key} | {value} |")

        return "".join(lines)

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

        audit_status = self.compute_audit_status(feature_id)
        current_date = datetime.now().strftime("%Y-%m-%d")
        
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
            "{suggested_tests}": "- Run gap analysis: `python3 scripts/feature_guard.py --gaps`",
            "{feature_group}": group_name,
            "{audit_last_verified}": audit_status["last_verified"],
            "{audit_last_result}": audit_status["last_result"],
            "{audit_days_since_test}": audit_status["days_since_test"],
            "{audit_open_advisories}": audit_status["open_advisories"],
            "{audit_local_stale}": audit_status["local_stale"],
            "{audit_upstream_stale}": audit_status["upstream_stale"],
            "{audit_confidence}": audit_status["confidence"],
            "{change_history_rows}": "| | | | |",
            "{test_run_date}": current_date,
            "{test_run_version}": "`<version>`",
            "{test_run_region}": "`<region>`",
            "{test_run_result}": "PENDING",
            "{test_run_duration}": "`<duration>`",
            "{test_run_trigger}": "initial generation",
        }

        content = template
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, str(value))

        doc_path = self._doc_path(feature_id)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content)
        self.log(f"Generated doc stub for {feature_id} at {doc_path}", "success")

    def detect_upstream_impact(self, changed_files: List[str]) -> Dict[str, List[str]]:
        return upstream_poller.detect_upstream_impact(changed_files)

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
            checks = self.tracker.setdefault("upstream_checks", [])
            checks.append({
                "timestamp": datetime.now().isoformat(),
                "pr_url": pr_url,
                "features_affected": sorted(affected.keys()),
            })
            self.tracker["upstream_checks"] = checks[-RETENTION["max_tracker_history"]:]
            self._save_tracker()

        return result

    @staticmethod
    def _parse_pr_url(url: str) -> Tuple[Optional[str], Optional[str]]:
        return upstream_poller.parse_pr_url(url)

    @staticmethod
    def _fetch_pr_files(owner_repo: str, pr_number: str) -> Optional[List[str]]:
        return upstream_poller.fetch_pr_files(owner_repo, pr_number)

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
            checks = self.tracker.setdefault("upstream_checks", [])
            checks.append({
                "timestamp": datetime.now().isoformat(),
                "repo": repo,
                "branch": branch,
                "old_sha": last_checked,
                "new_sha": current_sha,
                "files_changed": len(changed_files),
                "features_affected": sorted(affected.keys()),
            })
            self.tracker["upstream_checks"] = checks[-RETENTION["max_tracker_history"]:]

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
        return upstream_poller.fetch_branch_sha(repo, branch)

    @staticmethod
    def _fetch_commit_diff(repo: str, base_sha: str, head_sha: str) -> Optional[List[str]]:
        return upstream_poller.fetch_commit_diff(repo, base_sha, head_sha)

    @staticmethod
    def _fetch_recent_pr_files(repo: str, branch: str, limit: int = 10) -> Optional[List[str]]:
        return upstream_poller.fetch_recent_pr_files(repo, branch, limit)

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
        return advisory_manager.match_advisory_to_features(text)

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
        return advisory_manager.scan_redhat_security_api(since, log_fn=self.log)

    def _scan_github_security_advisories(self) -> List[Dict]:
        return advisory_manager.scan_github_security_advisories()

    @staticmethod
    def _map_redhat_severity(severity: str) -> str:
        return advisory_manager.map_redhat_severity(severity)

    def run_auto_test(self, feature_ids: List[str], dry_run: bool = False, suite_id: str = "20-rosa-hcp-provision") -> Dict:
        if not feature_ids:
            return {
                "success": False,
                "message": "No features specified for auto-test",
                "duration": 0,
            }

        cmd = test_runner_mod.build_test_command(feature_ids, suite_id)

        if dry_run:
            return {
                "success": True,
                "message": f"Would execute: {' '.join(cmd)}",
                "command": " ".join(cmd),
                "duration": 0,
                "dry_run": True,
            }

        self.log(f"Starting auto-test for features: {', '.join(feature_ids)}", "info")

        exec_result = test_runner_mod.execute_test(cmd, self.base_dir)

        at_history = self.tracker.setdefault("auto_test_history", [])
        at_history.append({
            "timestamp": datetime.now().isoformat(),
            "features": feature_ids,
            "command": exec_result.get("command", ""),
            "success": exec_result["success"],
            "duration": exec_result["duration"],
            "exit_code": exec_result.get("exit_code", -1),
        })
        self.tracker["auto_test_history"] = at_history[-RETENTION["max_tracker_history"]:]
        self._save_tracker()

        message = exec_result.get("message", f"Auto-test {'completed successfully' if exec_result['success'] else 'failed'}")
        result = {
            "success": exec_result["success"],
            "message": message,
            "features": feature_ids,
            "duration": exec_result["duration"],
            "exit_code": exec_result.get("exit_code", -1),
            "command": exec_result.get("command", ""),
        }

        if exec_result["success"]:
            self.log(f"Auto-test completed successfully for {len(feature_ids)} feature(s) in {exec_result['duration']:.1f}s", "success")
        else:
            self.log(f"Auto-test failed after {exec_result['duration']:.1f}s with exit code {exec_result.get('exit_code', -1)}", "error")

        return result

    def record_change(self, feature_id: str, source: str, event: str, details: str, link: Optional[str] = None) -> bool:
        try:
            doc_path = self._doc_path(feature_id)
            if not doc_path.exists():
                self.log(f"No doc page for {feature_id}, skipping change record", "warning")
                return False

            content = doc_path.read_text()
            timestamp = datetime.now().strftime("%Y-%m-%d")
            
            new_row = f"| {timestamp} | {source} | {event} | {details}"
            if link:
                new_row += f" ([link]({link}))"
            new_row += " |"

            change_header_marker = "## Change History"
            
            if change_header_marker in content:
                change_start = content.find(change_header_marker)
                section_start = content.find("| Date | Source | Event | Details |", change_start)
                
                if section_start != -1:
                    section_end = len(content)
                    next_section = content.find("\n## ", section_start)
                    if next_section != -1:
                        section_end = next_section
                    
                    section_content = content[section_start:section_end]
                    lines = section_content.split('\n')
                    
                    existing_rows = []
                    for line in lines[2:]:
                        line = line.strip()
                        if line and line.startswith('|') and line.endswith('|') and ' | ' in line:
                            existing_rows.append(line)
                    
                    new_fields = (source, event, details.split(" (")[0])
                    for row in existing_rows:
                        parts = [p.strip() for p in row.split("|") if p.strip()]
                        if len(parts) >= 4:
                            row_fields = (parts[1], parts[2], parts[3].split(" (")[0])
                            if new_fields == row_fields:
                                return True

                    all_rows = [new_row] + existing_rows
                    trimmed_rows = all_rows[:RETENTION["max_change_history"]]
                    
                    new_section_lines = [
                        "| Date | Source | Event | Details |",
                        "|------|--------|-------|---------|"
                    ] + trimmed_rows
                    
                    new_section_content = '\n'.join(new_section_lines)
                    
                    before = content[:section_start]
                    after = content[section_end:]
                    content = before + new_section_content + after
            else:
                change_section = f"""## Change History

| Date | Source | Event | Details |
|------|--------|-------|---------|
{new_row}

"""
                test_coverage_marker = '\n## Test Coverage\n'
                test_coverage_pos = content.find(test_coverage_marker)
                
                if test_coverage_pos != -1:
                    before = content[:test_coverage_pos].rstrip()
                    after = content[test_coverage_pos:]
                    content = before + "\n\n" + change_section.rstrip() + "\n" + after
                else:
                    content = content.rstrip() + "\n\n" + change_section

            doc_path.write_text(content)
            
            tracker_entry = self.tracker.setdefault("features", {}).setdefault(feature_id, {})
            change_history = tracker_entry.setdefault("change_history", [])
            change_history.insert(0, {
                "timestamp": datetime.now().isoformat(),
                "source": source,
                "event": event,
                "details": details,
                "link": link
            })
            
            change_history = change_history[:RETENTION["max_change_history"] * 2]
            tracker_entry["change_history"] = change_history
            
            self._save_tracker()
            self.log(f"Recorded change for {feature_id}: {source} - {event}", "info")
            return True

        except Exception as e:
            self.log(f"Failed to record change for {feature_id}: {e}", "error")
            return False

    def _get_current_commit_sha(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=self.base_dir,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except FileNotFoundError:
            pass
        return None

    def compute_audit_status(self, feature_id: str) -> Dict:
        tracker_entry = self.tracker.get("features", {}).get(feature_id, {})
        
        last_verified = "Never"
        last_result = "UNKNOWN"
        days_since_test = "N/A"
        confidence = "UNKNOWN"
        
        last_updated = tracker_entry.get("last_updated")
        if last_updated:
            try:
                last_date = datetime.fromisoformat(last_updated)
                last_verified = last_date.strftime("%Y-%m-%d")
                days_since = (datetime.now() - last_date).days
                days_since_test = str(days_since)
                last_result = tracker_entry.get("last_test_result", "UNKNOWN")
            except (ValueError, TypeError):
                pass

        open_advisories = 0
        advisory_affected = self.get_advisory_affected_features()
        if feature_id in advisory_affected:
            open_advisories = len(advisory_affected[feature_id])

        local_stale = tracker_entry.get("stale", False)
        upstream_stale = tracker_entry.get("upstream_stale", False)

        if last_updated:
            try:
                last_date = datetime.fromisoformat(last_updated)
                days_since = (datetime.now() - last_date).days
                
                if last_result == "FAIL":
                    confidence = "LOW"
                elif days_since <= 7 and last_result == "PASS" and open_advisories == 0 and not local_stale and not upstream_stale:
                    confidence = "HIGH"
                elif days_since <= 30 and open_advisories == 0:
                    confidence = "MEDIUM"
                else:
                    confidence = "LOW"
            except (ValueError, TypeError):
                confidence = "UNKNOWN"

        return {
            "last_verified": last_verified,
            "last_result": last_result,
            "days_since_test": days_since_test,
            "open_advisories": str(open_advisories),
            "local_stale": "Yes" if local_stale else "No",
            "upstream_stale": "Yes" if upstream_stale else "No",
            "confidence": confidence
        }

    def update_audit_badge(self, feature_id: str) -> bool:
        try:
            doc_path = self._doc_path(feature_id)
            if not doc_path.exists():
                self.log(f"No doc page for {feature_id}, skipping audit badge update", "warning")
                return False

            content = doc_path.read_text()
            audit_status = self.compute_audit_status(feature_id)
            
            new_badge = f"""## Audit Status

| Metric | Value |
|--------|-------|
| Last Verified | {audit_status['last_verified']} |
| Last Result | {audit_status['last_result']} |
| Days Since Last Test | {audit_status['days_since_test']} |
| Open Advisories | {audit_status['open_advisories']} |
| Local Code Stale | {audit_status['local_stale']} |
| Upstream Stale | {audit_status['upstream_stale']} |
| Test Confidence | {audit_status['confidence']} |

"""

            audit_pattern = r'## Audit Status\n\n\| Metric \| Value \|\n\|--------|-------\|\n.*?\n(?=\n## |\n$)'
            if re.search(audit_pattern, content, re.DOTALL):
                content = re.sub(audit_pattern, new_badge.rstrip() + "\n", content, flags=re.DOTALL)
            else:
                pattern = r'(\| Ansible Variable \| `.*?` \|\n\n)'
                if re.search(pattern, content):
                    content = re.sub(pattern, r'\1' + new_badge, content)
                else:
                    content = content.rstrip() + "\n\n" + new_badge

            doc_path.write_text(content)
            self.log(f"Updated audit badge for {feature_id} (confidence: {audit_status['confidence']})", "info")
            return True

        except Exception as e:
            self.log(f"Failed to update audit badge for {feature_id}: {e}", "error")
            return False

    def check_all(self, since: str = "HEAD~1", record: bool = False) -> Dict:
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

        git_sha = self._get_current_commit_sha()

        for feat_id, files in local_stale.items():
            source = "both" if feat_id in upstream_stale else "local"
            details = f"`{files[0]}`" + (f" (+{len(files)-1} more)" if len(files) > 1 else "")
            link = f"#{git_sha[:7]}" if git_sha else None

            if record:
                self.record_change(feat_id, "local", "Code change", details, link)

            suggestions.append({
                "feature_id": feat_id,
                "source": source,
                "action": "Review implementation changes and update docs",
                "files_changed": files,
                "command": f"./run-test-suite.py 20-rosa-hcp-provision --feature {feat_id.replace('_', '-')} --update-docs",
            })

        for feat_id, files in upstream_stale.items():
            if feat_id not in local_stale:
                upstream_sha = upstream_result.get("new_sha", "")[:7]
                details = f"`{files[0]}`" + (f" (+{len(files)-1} more)" if len(files) > 1 else "")
                link = f"https://github.com/{UPSTREAM_REPO}/commit/{upstream_sha}" if upstream_sha else None

                if record:
                    self.record_change(feat_id, "upstream", "PR merged", details, link)

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


    def render_dashboard(self, check_result: Optional[Dict] = None) -> str:
        if check_result is None:
            check_result = self.check_all()

        doc_status = self.get_doc_status()
        advisories = self.get_active_advisories()
        advisory_affected = check_result.get("advisory_affected", {})
        generated = datetime.now().strftime("%-m/%d/%Y, %-I:%M:%S %p")

        total = len(doc_status)
        with_docs = sum(1 for s in doc_status if s["has_doc"])
        local_count = len(check_result.get("local_stale", {}))
        upstream_count = len(check_result.get("upstream_stale", {}))
        advisory_count = len(advisory_affected)
        clear_count = len(check_result.get("all_clear", []))
        needs_attention = total - clear_count

        overall = "Passed" if advisory_count == 0 and local_count == 0 and upstream_count == 0 else "Action Required"
        overall_cls = "passed" if overall == "Passed" else "failed"

        upstream_sha = check_result.get("upstream_sha", "")
        upstream_status = check_result.get("upstream_status", "unknown")

        feature_rows = ""
        for s in doc_status:
            fid = s["feature_id"]
            slug = fid.replace("_", "-")

            icon_doc = "check" if s["has_doc"] else "x"
            doc_link = f"docs/features/{slug}.md" if s["has_doc"] else ""

            is_local_stale = fid in check_result.get("local_stale", {})
            icon_local = "x" if is_local_stale else "check"
            local_link = f"docs/features/{slug}.md" if is_local_stale and s["has_doc"] else ""

            is_upstream_stale = fid in check_result.get("upstream_stale", {})
            icon_upstream = "x" if is_upstream_stale else "check"
            upstream_link = ""
            if is_upstream_stale and upstream_sha:
                upstream_link = f"https://github.com/{UPSTREAM_REPO}/commit/{upstream_sha}"

            icon_adv = "x" if fid in advisory_affected else "check"
            adv_link = ""
            adv_badges = ""
            if fid in advisory_affected:
                for a in advisory_affected[fid]:
                    sev_cls = {"critical": "sev-critical", "high": "sev-high", "medium": "sev-med", "low": "sev-low"}.get(a["severity"], "")
                    adv_badges += f'<span class="pill {sev_cls}">{a["severity"].upper()}</span> '
                    if not adv_link and a.get("url"):
                        adv_link = a["url"]

            audit = self.compute_audit_status(fid)
            conf = audit["confidence"]
            conf_cls = {"HIGH": "conf-high", "MEDIUM": "conf-med", "LOW": "conf-low"}.get(conf, "conf-unknown")

            last_test = s.get("last_test_result") or "-"
            last_date = (s.get("last_updated") or "")[:10] or "Never"
            results_link = "test-results/latest-provision.html"

            def _icon(icon_type, link=""):
                span = f'<span class="icon-{icon_type}"></span>'
                if link and icon_type == "x":
                    return f'<a href="{link}" title="View details">{span}</a>'
                if link and icon_type == "check":
                    return f'<a href="{link}">{span}</a>'
                return span

            icon_doc_html = _icon(icon_doc, doc_link)
            icon_local_html = _icon(icon_local, local_link)
            icon_upstream_html = _icon(icon_upstream, upstream_link)
            icon_adv_html = _icon(icon_adv, adv_link)

            last_result_html = last_test
            if last_test not in ("-", "UNKNOWN"):
                last_result_html = f'<a href="{results_link}">{last_test}</a>'

            feature_rows += f"""<tr>
                <td class="feat-name">{slug}</td>
                <td class="num">{icon_doc_html}</td>
                <td class="num">{icon_local_html}</td>
                <td class="num">{icon_upstream_html}</td>
                <td>{icon_adv_html} {adv_badges}</td>
                <td class="num"><span class="conf {conf_cls}">{conf}</span></td>
                <td class="num">{last_result_html}</td>
                <td class="num">{last_date}</td>
            </tr>"""

        advisory_rows = ""
        for a in advisories:
            sev_cls = {"critical": "sev-critical", "high": "sev-high", "medium": "sev-med", "low": "sev-low"}.get(a["severity"], "")
            features = ", ".join(f.replace("_", "-") for f in a.get("features", []))
            url_link = f'<a href="{a["url"]}">{a["id"]}</a>' if a.get("url") else a["id"]
            advisory_rows += f"""<tr>
                <td>{url_link}</td>
                <td><span class="pill {sev_cls}">{a['severity'].upper()}</span></td>
                <td>{a['title']}</td>
                <td>{features}</td>
                <td>{a.get('added', '')[:10]}</td>
            </tr>"""

        suggestion_rows = ""
        for s in check_result.get("suggestions", []):
            source_cls = {"local": "src-local", "upstream": "src-upstream", "advisory": "src-advisory", "both": "src-both"}.get(s["source"], "")
            suggestion_rows += f"""<tr>
                <td class="feat-name">{s['feature_id'].replace('_', '-')}</td>
                <td><span class="pill {source_cls}">{s['source']}</span></td>
                <td>{s['action']}</td>
                <td><code>{s['command']}</code></td>
            </tr>"""

        adv_section = ""
        if advisories:
            adv_section = f"""<div class="section-card">
<div class="section-header"><h2>Active Advisories</h2></div>
<table>
<tr><th>ID</th><th>Severity</th><th>Title</th><th>Features</th><th>Added</th></tr>
{advisory_rows}
</table>
</div>"""

        action_section = ""
        if suggestion_rows:
            action_section = f"""<div class="section-card">
<div class="section-header"><h2>Recommended Actions</h2></div>
<table>
<tr><th>Feature</th><th>Source</th><th>Action</th><th>Command</th></tr>
{suggestion_rows}
</table>
</div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FeatureGuard Dashboard</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0; color: #1a1a1a; background: #f0f2f5; }}
  .header {{ background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
             padding: 0.9rem 2rem; display: flex; align-items: center; justify-content: space-between; }}
  .header h1 {{ color: #fff; margin: 0; font-size: 1.2rem; font-weight: 600; }}
  .header-nav {{ display: flex; gap: 0.5rem; }}
  .header-nav span {{ background: rgba(255,255,255,0.15); color: #fff; padding: 0.35rem 0.9rem;
                      border-radius: 6px; font-size: 0.8rem; font-weight: 500; }}
  .top-bar {{ background: #fff; border-bottom: 1px solid #e8eaed; padding: 0.7rem 2rem;
              display: flex; align-items: center; gap: 1rem; font-size: 0.85rem; color: #555; }}
  .top-bar .env {{ font-weight: 600; color: #1a73e8; }}
  .status-badge {{ display: inline-flex; align-items: center; gap: 0.4rem; border: 1.5px solid #ddd;
                   border-radius: 20px; padding: 0.3rem 1rem; font-size: 0.82rem; margin-left: auto; }}
  .status-badge.passed {{ border-color: #27ae60; }}
  .status-badge.failed {{ border-color: #e74c3c; }}
  .status-badge .dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .status-badge.passed .dot {{ background: #27ae60; }}
  .status-badge.failed .dot {{ background: #e74c3c; }}
  .status-badge .label {{ font-weight: 600; }}
  .status-badge.passed .label {{ color: #27ae60; }}
  .status-badge.failed .label {{ color: #e74c3c; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 1.5rem 2rem; }}
  .cards {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 12px; padding: 1.2rem 1.5rem; flex: 1; min-width: 130px;
           box-shadow: 0 1px 4px rgba(0,0,0,0.06); border: 1px solid #e8eaed; text-align: center; }}
  .card .card-label {{ font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.3rem; }}
  .card .card-value {{ font-size: 1.8rem; font-weight: 700; }}
  .card .card-value.green {{ color: #27ae60; }}
  .card .card-value.red {{ color: #e74c3c; }}
  .card .card-value.yellow {{ color: #e67e22; }}
  .card .card-value.blue {{ color: #1a73e8; }}
  .section-card {{ background: #fff; border-radius: 12px; border: 1px solid #e8eaed;
                   box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin-bottom: 1.5rem; overflow: hidden; }}
  .section-header {{ padding: 1rem 1.5rem 0.5rem; }}
  .section-header h2 {{ margin: 0; font-size: 1.05rem; color: #1a1a1a; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ background: #f8f9fa; color: #555; text-align: left; padding: 0.6rem 1rem;
        font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
        border-bottom: 2px solid #e8eaed; }}
  td {{ padding: 0.6rem 1rem; border-bottom: 1px solid #f0f0f0; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover {{ background: #f8fafe; }}
  .num {{ text-align: center; }}
  .feat-name {{ font-weight: 600; color: #1a1a1a; }}
  .icon-check::before {{ content: ""; display: inline-block; width: 18px; height: 18px;
                         background: #27ae60; border-radius: 50%; vertical-align: middle;
                         background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z'/%3E%3C/svg%3E");
                         background-size: 12px; background-repeat: no-repeat; background-position: center; }}
  .icon-x::before {{ content: ""; display: inline-block; width: 18px; height: 18px;
                     background: #e74c3c; border-radius: 50%; vertical-align: middle;
                     background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z'/%3E%3C/svg%3E");
                     background-size: 12px; background-repeat: no-repeat; background-position: center; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.72rem; font-weight: 600; }}
  .sev-critical {{ background: #fde8e8; color: #c0392b; }}
  .sev-high {{ background: #fef3e2; color: #d35400; }}
  .sev-med {{ background: #fef9e7; color: #b7950b; }}
  .sev-low {{ background: #eafaf1; color: #1e8449; }}
  .conf {{ padding: 2px 10px; border-radius: 10px; font-size: 0.78rem; font-weight: 600; }}
  .conf-high {{ background: #eafaf1; color: #1e8449; }}
  .conf-med {{ background: #fef9e7; color: #b7950b; }}
  .conf-low {{ background: #fde8e8; color: #c0392b; }}
  .conf-unknown {{ background: #f4f4f4; color: #999; }}
  .src-local {{ background: #e8f0fe; color: #1a73e8; }}
  .src-upstream {{ background: #f3e8fd; color: #7c3aed; }}
  .src-advisory {{ background: #fde8e8; color: #c0392b; }}
  .src-both {{ background: #fef3e2; color: #d35400; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; font-size: 0.78rem; color: #333; }}
</style>
</head>
<body>

<div class="header">
  <h1>FeatureGuard</h1>
  <div class="header-nav">
    <span>Dashboard</span>
    <span>Manifests</span>
    <span>Advisories</span>
  </div>
</div>

<div class="top-bar">
  <span>Upstream:</span>
  <span class="env">{upstream_status}</span>
  <span>{(upstream_sha or 'N/A')[:12]}</span>
  <span>Features: {total}</span>
  <span>Manifests: {with_docs}/{total}</span>
  <div class="status-badge {overall_cls}">
    <span class="dot"></span>
    Last verified: {generated}
    <span class="label">{overall}</span>
  </div>
</div>

<div class="container">

<div class="cards">
  <div class="card">
    <div class="card-label">Total Features</div>
    <div class="card-value blue">{total}</div>
  </div>
  <div class="card">
    <div class="card-label">Manifests</div>
    <div class="card-value {'green' if with_docs == total else 'yellow'}">{with_docs}/{total}</div>
  </div>
  <div class="card">
    <div class="card-label">Local Stale</div>
    <div class="card-value {'green' if local_count == 0 else 'yellow'}">{local_count}</div>
  </div>
  <div class="card">
    <div class="card-label">Upstream Stale</div>
    <div class="card-value {'green' if upstream_count == 0 else 'yellow'}">{upstream_count}</div>
  </div>
  <div class="card">
    <div class="card-label">Advisories</div>
    <div class="card-value {'green' if advisory_count == 0 else 'red'}">{advisory_count}</div>
  </div>
  <div class="card">
    <div class="card-label">All Clear</div>
    <div class="card-value green">{clear_count}</div>
  </div>
</div>

<div class="section-card">
<div class="section-header"><h2>Feature Status</h2></div>
<table>
<tr>
  <th>Feature</th><th>Manifest</th><th>Local</th><th>Upstream</th>
  <th>Advisory</th><th>Confidence</th><th>Last Result</th><th>Last Tested</th>
</tr>
{feature_rows}
</table>
</div>

{adv_section}

{action_section}

</div>
</body>
</html>"""


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
                "command": f"python3 scripts/feature_guard.py --generate {feat_id}",
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
