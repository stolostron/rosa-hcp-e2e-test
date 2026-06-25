"""
Upstream repository polling and change detection.
"""

import fnmatch
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from .feature_guard_constants import UPSTREAM_FILE_MAP, UPSTREAM_SHARED_PATTERNS


def detect_upstream_impact(changed_files: List[str]) -> Dict[str, List[str]]:
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


def parse_pr_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.match(
        r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)',
        url,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def fetch_pr_files(owner_repo: str, pr_number: str) -> Optional[List[str]]:
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


def fetch_branch_sha(repo: str, branch: str) -> Optional[str]:
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


def fetch_commit_diff(repo: str, base_sha: str, head_sha: str) -> Optional[List[str]]:
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


def fetch_recent_pr_files(repo: str, branch: str, limit: int = 10) -> Optional[List[str]]:
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
            files = fetch_pr_files(repo, pr_num)
            if files:
                all_files.update(files)
        return sorted(all_files) if all_files else []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None
