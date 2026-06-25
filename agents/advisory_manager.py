"""
Advisory and CVE management.
"""

import json
import subprocess
import urllib.parse
import urllib.request
from typing import Dict, List

from .feature_guard_constants import ADVISORY_KEYWORD_MAP, UPSTREAM_REPO


def match_advisory_to_features(text: str) -> List[str]:
    text_lower = text.lower()
    matched = []
    for feat_id, keywords in ADVISORY_KEYWORD_MAP.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(feat_id)
                break
    return matched


def map_redhat_severity(severity: str) -> str:
    severity_map = {
        "critical": "critical",
        "important": "high",
        "moderate": "medium",
        "low": "low",
    }
    return severity_map.get(severity.lower(), "medium")


def scan_redhat_security_api(since: str, log_fn=None) -> List[Dict]:
    cves = []

    for product in ["OpenShift Container Platform", "Red Hat OpenShift Service on AWS"]:
        url = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
        params = {
            "product": product,
            "after": since,
        }
        full_url = f"{url}?{urllib.parse.urlencode(params)}"

        try:
            if log_fn:
                log_fn(f"Fetching CVEs for '{product}' since {since}", "info")
            with urllib.request.urlopen(full_url, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))

            for item in data:
                severity = map_redhat_severity(item.get("severity", ""))
                description = item.get("bugzilla_description", "") or item.get("synopsis", "")

                cves.append({
                    "id": item["CVE"],
                    "title": description[:100] + "..." if len(description) > 100 else description,
                    "description": description,
                    "severity": severity,
                    "url": item.get("resource_url", ""),
                    "source": "redhat",
                })

        except Exception as e:
            if log_fn:
                log_fn(f"Failed to fetch Red Hat CVEs for '{product}': {e}", "warning")
            raise

    return cves


def scan_github_security_advisories(repo: str = UPSTREAM_REPO) -> List[Dict]:
    advisories = []

    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/security-advisories",
             "--paginate", "--jq", ".[].ghsa_id"],
            capture_output=True, text=True, timeout=60,
        )

        if result.returncode == 0:
            ghsa_ids = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]

            for ghsa_id in ghsa_ids:
                try:
                    detail_result = subprocess.run(
                        ["gh", "api", f"advisories/{ghsa_id}"],
                        capture_output=True, text=True, timeout=30,
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
                            "source": "github",
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
                capture_output=True, text=True, timeout=60,
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
                                "source": "github",
                            })
                except json.JSONDecodeError:
                    pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return advisories
