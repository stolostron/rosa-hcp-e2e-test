"""
Agent Reporting & Analysis
==========================

Aggregates remediation outcomes, confidence scores, and issue patterns
into a summary report. Reads from the knowledge base files — no live
agent instances required.

Usage:
    python3 -m agents.report
    python3 -m agents.report --json
    python3 -m agents.report --since 2026-03-01
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def load_json(path: Path) -> dict | list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {} if path.suffix == ".json" else []


def filter_since(outcomes: List[Dict], since: Optional[str]) -> List[Dict]:
    if not since:
        return outcomes
    return [o for o in outcomes if o.get("timestamp", "") >= since]


def build_report(kb_dir: Path, since: Optional[str] = None) -> Dict:
    outcomes = load_json(kb_dir / "remediation_outcomes.json")
    if not isinstance(outcomes, list):
        outcomes = []
    outcomes = filter_since(outcomes, since)

    known_issues = load_json(kb_dir / "known_issues.json")
    patterns = known_issues.get("patterns", []) if isinstance(known_issues, dict) else []

    fix_strategies = load_json(kb_dir / "fix_strategies.json")
    if not isinstance(fix_strategies, dict):
        fix_strategies = {}

    # -- Outcome stats by issue type --
    by_issue: Dict[str, Dict] = defaultdict(lambda: {
        "successes": 0, "failures": 0, "total": 0,
        "fixes_used": defaultdict(int),
        "confidence_values": [],
        "first_seen": None, "last_seen": None,
        "resources_affected": set(),
    })

    for o in outcomes:
        issue = o["issue_type"]
        s = by_issue[issue]
        s["total"] += 1
        if o["success"]:
            s["successes"] += 1
        else:
            s["failures"] += 1
        s["fixes_used"][o.get("recommended_fix", "unknown")] += 1
        conf = o.get("confidence_used")
        if conf is not None:
            s["confidence_values"].append(conf)
        ts = o.get("timestamp", "")
        if ts:
            if s["first_seen"] is None or ts < s["first_seen"]:
                s["first_seen"] = ts
            if s["last_seen"] is None or ts > s["last_seen"]:
                s["last_seen"] = ts
        rk = o.get("resource_key", "")
        if rk:
            s["resources_affected"].add(rk)

    # -- Outcome stats by fix type --
    by_fix: Dict[str, Dict] = defaultdict(lambda: {
        "successes": 0, "failures": 0, "total": 0,
        "issue_types": set(),
    })

    for o in outcomes:
        fix = o.get("recommended_fix", "unknown")
        f = by_fix[fix]
        f["total"] += 1
        if o["success"]:
            f["successes"] += 1
        else:
            f["failures"] += 1
        f["issue_types"].add(o["issue_type"])

    # -- Confidence snapshot from known_issues.json --
    confidence_snapshot = []
    for p in patterns:
        entry = {
            "issue_type": p["type"],
            "severity": p.get("severity", "unknown"),
            "auto_fix": p.get("auto_fix", False),
        }
        if "learned_confidence" in p:
            entry["learned_confidence"] = p["learned_confidence"]
            entry["last_adjusted"] = p.get("last_adjusted", "")
            entry["adjustment_reason"] = p.get("adjustment_reason", "")
        confidence_snapshot.append(entry)

    # -- Coverage: which patterns have outcomes vs which don't --
    issue_types_with_outcomes = set(by_issue.keys())
    issue_types_defined = {p["type"] for p in patterns}
    untested_patterns = sorted(issue_types_defined - issue_types_with_outcomes)

    strategy_types = set(fix_strategies.keys()) - {"version", "description"}
    strategies_never_triggered = sorted(strategy_types - issue_types_with_outcomes)

    # -- Serialize --
    def serialize_issue_stats(stats):
        result = {}
        for issue, s in sorted(stats.items()):
            total = s["total"]
            rate = (s["successes"] / total * 100) if total else 0
            avg_conf = (sum(s["confidence_values"]) / len(s["confidence_values"])) if s["confidence_values"] else None
            result[issue] = {
                "successes": s["successes"],
                "failures": s["failures"],
                "total": total,
                "success_rate": f"{rate:.0f}%",
                "avg_confidence": round(avg_conf, 2) if avg_conf is not None else None,
                "confidence_range": [min(s["confidence_values"]), max(s["confidence_values"])] if s["confidence_values"] else None,
                "fixes_used": dict(s["fixes_used"]),
                "resources_affected": len(s["resources_affected"]),
                "first_seen": s["first_seen"],
                "last_seen": s["last_seen"],
            }
        return result

    def serialize_fix_stats(stats):
        result = {}
        for fix, f in sorted(stats.items()):
            total = f["total"]
            rate = (f["successes"] / total * 100) if total else 0
            result[fix] = {
                "successes": f["successes"],
                "failures": f["failures"],
                "total": total,
                "success_rate": f"{rate:.0f}%",
                "issue_types": sorted(f["issue_types"]),
            }
        return result

    return {
        "generated": datetime.now().isoformat(),
        "since": since,
        "total_outcomes": len(outcomes),
        "overall_success_rate": f"{(sum(1 for o in outcomes if o['success']) / len(outcomes) * 100):.0f}%" if outcomes else "N/A",
        "by_issue_type": serialize_issue_stats(by_issue),
        "by_fix_type": serialize_fix_stats(by_fix),
        "confidence_snapshot": confidence_snapshot,
        "coverage": {
            "patterns_defined": len(issue_types_defined),
            "patterns_with_outcomes": len(issue_types_with_outcomes),
            "untested_patterns": untested_patterns,
            "strategies_never_triggered": strategies_never_triggered,
        },
    }


def print_report(report: Dict):
    print("=" * 70)
    print("  AI Agent Remediation Report")
    print("=" * 70)
    since_text = f" (since {report['since']})" if report["since"] else ""
    print(f"  Generated: {report['generated']}{since_text}")
    print(f"  Total outcomes: {report['total_outcomes']}")
    print(f"  Overall success rate: {report['overall_success_rate']}")
    print()

    # -- By issue type --
    if report["by_issue_type"]:
        print("-" * 70)
        print("  Results by Issue Type")
        print("-" * 70)
        for issue, stats in report["by_issue_type"].items():
            print(f"\n  {issue}")
            print(f"    Success rate:  {stats['success_rate']} ({stats['successes']}/{stats['total']})")
            if stats["avg_confidence"] is not None:
                lo, hi = stats["confidence_range"]
                print(f"    Confidence:    avg {stats['avg_confidence']}  range [{lo}, {hi}]")
            print(f"    Fixes used:    {', '.join(f'{f} ({n}x)' for f, n in stats['fixes_used'].items())}")
            print(f"    Resources:     {stats['resources_affected']} unique")
            print(f"    Window:        {stats['first_seen'][:10]} to {stats['last_seen'][:10]}")
    print()

    # -- By fix type --
    if report["by_fix_type"]:
        print("-" * 70)
        print("  Results by Fix Type")
        print("-" * 70)
        for fix, stats in report["by_fix_type"].items():
            issues = ", ".join(stats["issue_types"])
            print(f"\n  {fix}")
            print(f"    Success rate:  {stats['success_rate']} ({stats['successes']}/{stats['total']})")
            print(f"    Issue types:   {issues}")
    print()

    # -- Confidence snapshot --
    print("-" * 70)
    print("  Confidence Scores (from knowledge base)")
    print("-" * 70)
    print(f"  {'Issue Type':<40} {'Sev':<8} {'Auto':<6} {'Learned':<10} {'Reason'}")
    print(f"  {'-'*38}   {'-'*5}  {'-'*4}   {'-'*7}    {'-'*20}")
    for c in report["confidence_snapshot"]:
        learned = str(c.get("learned_confidence", "-"))
        reason = c.get("adjustment_reason", "")
        if len(reason) > 30:
            reason = reason[:27] + "..."
        auto = "yes" if c["auto_fix"] else "no"
        print(f"  {c['issue_type']:<40} {c['severity']:<8} {auto:<6} {learned:<10} {reason}")
    print()

    # -- Coverage gaps --
    cov = report["coverage"]
    print("-" * 70)
    print("  Coverage")
    print("-" * 70)
    print(f"  Patterns defined:         {cov['patterns_defined']}")
    print(f"  Patterns with outcomes:   {cov['patterns_with_outcomes']}")
    if cov["untested_patterns"]:
        print(f"  No outcome data yet:      {', '.join(cov['untested_patterns'])}")
    if cov["strategies_never_triggered"]:
        print(f"  Strategies never used:    {', '.join(cov['strategies_never_triggered'])}")
    print()
    print("=" * 70)


def render_html(report: Dict) -> str:
    rows_issue = ""
    for issue, s in report["by_issue_type"].items():
        conf = s["avg_confidence"] if s["avg_confidence"] is not None else "-"
        conf_range = f"[{s['confidence_range'][0]}, {s['confidence_range'][1]}]" if s["confidence_range"] else "-"
        fixes = ", ".join(f"{f}&nbsp;({n}x)" for f, n in s["fixes_used"].items())
        rows_issue += f"""<tr>
            <td>{issue}</td>
            <td class="num">{s['success_rate']}</td>
            <td class="num">{s['successes']}</td>
            <td class="num">{s['failures']}</td>
            <td class="num">{conf}</td>
            <td class="num">{conf_range}</td>
            <td>{fixes}</td>
            <td class="num">{s['resources_affected']}</td>
            <td>{s['first_seen'][:10] if s['first_seen'] else '-'}</td>
            <td>{s['last_seen'][:10] if s['last_seen'] else '-'}</td>
        </tr>"""

    rows_fix = ""
    for fix, s in report["by_fix_type"].items():
        issues = ", ".join(s["issue_types"])
        rows_fix += f"""<tr>
            <td>{fix}</td>
            <td class="num">{s['success_rate']}</td>
            <td class="num">{s['successes']}</td>
            <td class="num">{s['failures']}</td>
            <td>{issues}</td>
        </tr>"""

    rows_conf = ""
    for c in report["confidence_snapshot"]:
        learned = c.get("learned_confidence", "-")
        reason = c.get("adjustment_reason", "")
        auto = "yes" if c["auto_fix"] else "no"
        sev_class = {"high": "sev-high", "medium": "sev-med", "low": "sev-low"}.get(c["severity"], "")
        rows_conf += f"""<tr>
            <td>{c['issue_type']}</td>
            <td class="{sev_class}">{c['severity']}</td>
            <td class="num">{auto}</td>
            <td class="num">{learned}</td>
            <td>{reason}</td>
        </tr>"""

    cov = report["coverage"]
    untested = ", ".join(cov["untested_patterns"]) if cov["untested_patterns"] else "none"
    unused_strats = ", ".join(cov["strategies_never_triggered"]) if cov["strategies_never_triggered"] else "none"
    since_text = f" (since {report['since']})" if report["since"] else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI Agent Remediation Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 2rem auto; max-width: 1200px; color: #1a1a1a; background: #f8f9fa; }}
  h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 0.5rem; }}
  h2 {{ color: #34495e; margin-top: 2rem; }}
  .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .cards {{ display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 8px; padding: 1.2rem 1.5rem;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 160px; }}
  .card .label {{ font-size: 0.8rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.8rem; font-weight: 700; color: #2c3e50; margin-top: 0.2rem; }}
  .card .value.green {{ color: #27ae60; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
           margin-bottom: 1.5rem; font-size: 0.9rem; }}
  th {{ background: #2c3e50; color: #fff; text-align: left; padding: 0.7rem 0.8rem;
        font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  td {{ padding: 0.6rem 0.8rem; border-bottom: 1px solid #eee; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover {{ background: #f0f6ff; }}
  .num {{ text-align: center; font-variant-numeric: tabular-nums; }}
  .sev-high {{ color: #c0392b; font-weight: 600; }}
  .sev-med {{ color: #e67e22; font-weight: 600; }}
  .sev-low {{ color: #27ae60; }}
  .coverage {{ background: #fff; border-radius: 8px; padding: 1rem 1.5rem;
               box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 0.9rem; }}
  .coverage dt {{ font-weight: 600; margin-top: 0.5rem; }}
  .coverage dd {{ margin-left: 1rem; color: #555; }}
  .gap {{ color: #e67e22; }}
</style>
</head>
<body>
<h1>AI Agent Remediation Report</h1>
<p class="meta">Generated: {report['generated'][:19]}{since_text}</p>

<div class="cards">
  <div class="card">
    <div class="label">Total Outcomes</div>
    <div class="value">{report['total_outcomes']}</div>
  </div>
  <div class="card">
    <div class="label">Overall Success Rate</div>
    <div class="value green">{report['overall_success_rate']}</div>
  </div>
  <div class="card">
    <div class="label">Patterns Defined</div>
    <div class="value">{cov['patterns_defined']}</div>
  </div>
  <div class="card">
    <div class="label">Patterns with Data</div>
    <div class="value">{cov['patterns_with_outcomes']}</div>
  </div>
</div>

<h2>Results by Issue Type</h2>
<table>
<tr>
  <th>Issue Type</th><th>Success Rate</th><th>Pass</th><th>Fail</th>
  <th>Avg Conf</th><th>Conf Range</th><th>Fixes Used</th>
  <th>Resources</th><th>First Seen</th><th>Last Seen</th>
</tr>
{rows_issue}
</table>

<h2>Results by Fix Type</h2>
<table>
<tr><th>Fix</th><th>Success Rate</th><th>Pass</th><th>Fail</th><th>Issue Types</th></tr>
{rows_fix}
</table>

<h2>Confidence Scores</h2>
<table>
<tr><th>Issue Type</th><th>Severity</th><th>Auto-Fix</th><th>Learned</th><th>Reason</th></tr>
{rows_conf}
</table>

<h2>Coverage Gaps</h2>
<div class="coverage">
<dl>
  <dt>Patterns with no outcome data yet</dt>
  <dd class="gap">{untested}</dd>
  <dt>Fix strategies never triggered</dt>
  <dd class="gap">{unused_strats}</dd>
</dl>
</div>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="AI Agent remediation report")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--html", type=str, default=None, metavar="FILE",
                        help="Write HTML report to file")
    parser.add_argument("--since", type=str, default=None,
                        help="Only include outcomes on or after this date (YYYY-MM-DD)")
    parser.add_argument("--kb-dir", type=str, default=None,
                        help="Path to knowledge_base directory")
    args = parser.parse_args()

    if args.kb_dir:
        kb_dir = Path(args.kb_dir)
    else:
        kb_dir = Path(__file__).parent / "knowledge_base"

    if not kb_dir.exists():
        print(f"Knowledge base directory not found: {kb_dir}", file=sys.stderr)
        sys.exit(1)

    report = build_report(kb_dir, since=args.since)

    if args.json:
        print(json.dumps(report, indent=2))
    elif args.html:
        html = render_html(report)
        out = Path(args.html)
        out.write_text(html)
        print(f"Report written to {out}")
    else:
        print_report(report)


if __name__ == "__main__":
    main()
