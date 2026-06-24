#!/usr/bin/env python3
"""
Feature Documentation Manager CLI
===================================

Manages the lifecycle of per-feature documentation pages.

Usage:
    python3 scripts/update_feature_docs.py --status
    python3 scripts/update_feature_docs.py --gaps
    python3 scripts/update_feature_docs.py --stale
    python3 scripts/update_feature_docs.py --stale --since HEAD~5
    python3 scripts/update_feature_docs.py --generate security_groups
    python3 scripts/update_feature_docs.py --generate-all
    python3 scripts/update_feature_docs.py --update security_groups --test-data '{"result":"PASS",...}'
    python3 scripts/update_feature_docs.py --update security_groups --results-file test-results/latest-provision.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.feature_doc_agent import FeatureDocAgent, DocGapAnalyzer


def cmd_status(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    statuses = agent.get_doc_status()

    print(f"\n{'Feature':<30} {'Doc?':<6} {'Stale?':<7} {'Last Updated':<22} {'Last Result'}")
    print("-" * 95)
    for s in statuses:
        doc = "YES" if s["has_doc"] else "NO"
        stale = "STALE" if s["stale"] else "OK"
        updated = (s["last_updated"] or "")[:19]
        result = s["last_test_result"] or ""
        print(f"  {s['feature_id']:<28} {doc:<6} {stale:<7} {updated:<22} {result}")
    print()


def cmd_gaps(args):
    analyzer = DocGapAnalyzer(args.base_dir)
    report = analyzer.analyze()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        analyzer.print_report(report)


def cmd_stale(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    stale = agent.refresh_stale_docs(since=args.since)
    if not stale:
        print("No stale feature docs detected.")
        return
    print(f"\n{len(stale)} feature doc(s) are stale:\n")
    for feat_id, files in stale.items():
        print(f"  {feat_id}:")
        for f in files:
            print(f"    - {f}")
    print()


def cmd_generate(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    if args.feature_id == "ALL":
        fm = agent.feature_manager
        for feat_id in sorted(fm._cli_features):
            doc_path = agent._doc_path(feat_id)
            if not doc_path.exists():
                agent._generate_doc_from_template(feat_id)
            else:
                print(f"  Skipping {feat_id} (doc already exists)")
    else:
        agent._generate_doc_from_template(args.feature_id)


def cmd_update(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)

    if args.results_file:
        results_path = Path(args.results_file)
        if not results_path.is_absolute():
            results_path = args.base_dir / results_path
        if not results_path.exists():
            print(f"Results file not found: {results_path}", file=sys.stderr)
            sys.exit(1)
        with open(results_path) as f:
            full_results = json.load(f)
        test_data = _extract_test_data(full_results, args.feature_id)
    elif args.test_data:
        test_data = json.loads(args.test_data)
    else:
        print("Provide --test-data or --results-file", file=sys.stderr)
        sys.exit(1)

    ok = agent.update_live_test_record(args.feature_id, test_data)
    sys.exit(0 if ok else 1)


def cmd_upstream(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    result = agent.detect_upstream_pr_impact(args.pr_url)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"\nUpstream PR: {result['pr_url']}")
    print(f"Files changed: {result['upstream_files_changed']}")
    print(f"Features affected: {result['features_affected']}")

    if result["affected"]:
        print(f"\nAffected features:")
        for feat_id, files in sorted(result["affected"].items()):
            print(f"\n  {feat_id}:")
            for f in files:
                print(f"    - {f}")

        print(f"\nRecommended actions:")
        for feat_id in sorted(result["affected"]):
            slug = feat_id.replace('_', '-')
            print(f"  - Review docs/features/{slug}.md")
            print(f"    $ ./run-test-suite.py 20-rosa-hcp-provision --feature {slug} --update-docs")
    else:
        print("\nNo tracked features affected by this PR.")
    print()


def cmd_watch(args):
    from agents.feature_doc_agent import UPSTREAM_REPO
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    repo = args.repo or UPSTREAM_REPO
    branch = args.branch

    result = agent.check_upstream(repo=repo, branch=branch)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["status"] == "up_to_date":
        print(f"\nNo new changes on {repo}:{branch}")
        print(f"HEAD: {result['sha'][:12]}")
        return

    print(f"\nNew changes detected on {repo}:{branch}")
    print(f"  {(result.get('old_sha') or 'initial')[:12]} -> {result['new_sha'][:12]}")
    print(f"  Files changed: {result['files_changed']}")
    print(f"  Features affected: {result['features_affected']}")

    if result["affected"]:
        print(f"\nAffected features:")
        for feat_id, files in sorted(result["affected"].items()):
            print(f"\n  {feat_id}:")
            for f in files:
                print(f"    - {f}")

        print(f"\nRecommended actions:")
        for feat_id in sorted(result["affected"]):
            slug = feat_id.replace('_', '-')
            print(f"  - Review docs/features/{slug}.md")
            print(f"    $ ./run-test-suite.py 20-rosa-hcp-provision --feature {slug} --update-docs")
    else:
        print("\nNo tracked features affected.")
    print()


def cmd_check(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    result = agent.check_all(since=args.since)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 80)
    print("  Unified Change Detection Report")
    print("=" * 80)

    print(f"\nUpstream Status: {result['upstream_status']}")
    if result['upstream_sha']:
        print(f"Upstream SHA: {result['upstream_sha'][:12]}...")

    advisory_affected = result.get('advisory_affected', {})
    local_count = len(result['local_stale'])
    upstream_count = len(result['upstream_stale'])
    advisory_count = len(advisory_affected)
    both_count = len(result['both_stale'])
    clear_count = len(result['all_clear'])

    print(f"\nSummary:")
    print(f"  - Local changes affecting {local_count} feature(s)")
    print(f"  - Upstream changes affecting {upstream_count} feature(s)")
    print(f"  - Advisories affecting {advisory_count} feature(s)")
    print(f"  - Both local & upstream: {both_count} feature(s)")
    print(f"  - All clear: {clear_count} feature(s)")

    all_affected = set(result['local_stale'].keys()) | set(result['upstream_stale'].keys()) | set(advisory_affected.keys())
    if all_affected:
        print("\n" + "-" * 90)
        print("  Feature Status Table")
        print("-" * 90)
        print(f"{'Feature':<25} {'Local':<8} {'Upstream':<10} {'Advisory':<10} {'Action'}")
        print("-" * 90)

        for feat_id in sorted(all_affected):
            local_status = "STALE" if feat_id in result['local_stale'] else "OK"
            up_status = "STALE" if feat_id in result['upstream_stale'] else "OK"
            adv_status = "ALERT" if feat_id in advisory_affected else "OK"

            if feat_id in result['both_stale']:
                action = "Review both"
            elif feat_id in result['local_stale']:
                action = "Review local"
            elif feat_id in result['upstream_stale']:
                action = "Test upstream"
            elif feat_id in advisory_affected:
                sevs = [a["severity"] for a in advisory_affected[feat_id]]
                worst = "critical" if "critical" in sevs else "high" if "high" in sevs else sevs[0]
                action = f"Advisory ({worst})"
            else:
                action = "OK"

            print(f"  {feat_id:<23} {local_status:<8} {up_status:<10} {adv_status:<10} {action}")

        if result['suggestions']:
            print(f"\n{'-' * 90}")
            print("  Recommended Actions")
            print("-" * 90)
            for suggestion in result['suggestions']:
                source = suggestion['source']
                print(f"\n  {suggestion['feature_id']} ({source}):")
                print(f"    {suggestion['action']}")
                if 'files_changed' in suggestion:
                    print(f"    Files: {', '.join(suggestion['files_changed'][:3])}")
                    if len(suggestion['files_changed']) > 3:
                        print(f"           ... and {len(suggestion['files_changed']) - 3} more")
                if suggestion.get('advisory_url'):
                    print(f"    URL: {suggestion['advisory_url']}")
                print(f"    $ {suggestion['command']}")

    else:
        print(f"\nAll features are up to date!")

    if hasattr(args, 'auto_test') and (args.auto_test or args.auto_test_dry_run):
        print(f"\n{'=' * 80}")
        print("  Auto-Test Execution")
        print("=" * 80)

        unique_feature_ids = set()
        for suggestion in result['suggestions']:
            unique_feature_ids.add(suggestion['feature_id'])

        feature_ids = sorted(list(unique_feature_ids))

        if not feature_ids:
            print("\nNo features need testing. All documentation is up to date.")
        else:
            max_features = getattr(args, 'auto_test_max', 5)
            if len(feature_ids) > max_features:
                print(f"\nError: {len(feature_ids)} features affected, but limit is {max_features}.")
                print(f"Features: {', '.join(feature_ids)}")
                print(f"Use --auto-test-max {len(feature_ids)} to override the limit.")
                sys.exit(1)

            if args.auto_test_dry_run:
                dry_result = agent.run_auto_test(feature_ids, dry_run=True)
                print(f"\nDry run - would test {len(feature_ids)} feature(s): {', '.join(feature_ids)}")
                print(f"Command: {dry_result['command']}")
            else:
                print(f"\nExecuting auto-test for {len(feature_ids)} feature(s): {', '.join(feature_ids)}")
                test_result = agent.run_auto_test(feature_ids, dry_run=False)
                
                print(f"\n{'=' * 80}")
                print("  Auto-Test Summary")
                print("=" * 80)
                print(f"Features tested: {', '.join(test_result['features'])}")
                print(f"Result: {'PASS' if test_result['success'] else 'FAIL'}")
                print(f"Duration: {test_result['duration']:.1f}s")
                print(f"Exit code: {test_result['exit_code']}")
                
                if not test_result['success']:
                    sys.exit(1)

    print(f"\n{'=' * 90}\n")


def cmd_advisory_add(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    features = args.features.split(",") if args.features else None
    adv = agent.add_advisory(
        advisory_id=args.advisory_id,
        title=args.title,
        description=args.description or "",
        severity=args.severity,
        features=features,
        url=args.url or "",
    )

    if args.json:
        print(json.dumps(adv, indent=2))
    else:
        print(f"\nAdvisory added: {adv['id']}")
        print(f"  Title: {adv['title']}")
        print(f"  Severity: {adv['severity']}")
        print(f"  Features: {', '.join(adv['features']) or 'none (auto-match found nothing)'}")
        if adv.get('url'):
            print(f"  URL: {adv['url']}")
        print()


def cmd_advisory_list(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    if args.all:
        advisories = agent._load_advisories()
    else:
        advisories = agent.get_active_advisories()

    if args.json:
        print(json.dumps(advisories, indent=2))
        return

    label = "All" if args.all else "Active"
    print(f"\n{label} Advisories ({len(advisories)}):\n")
    if not advisories:
        print("  (none)")
    for a in advisories:
        resolved = " [RESOLVED]" if a.get("resolved") else ""
        print(f"  {a['id']} [{a['severity'].upper()}]{resolved}")
        print(f"    {a['title']}")
        print(f"    Features: {', '.join(a.get('features', []))}")
        if a.get("url"):
            print(f"    URL: {a['url']}")
        print()


def cmd_advisory_resolve(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    ok = agent.resolve_advisory(args.advisory_id)
    if ok:
        print(f"Advisory {args.advisory_id} marked as resolved.")
    else:
        print(f"Advisory {args.advisory_id} not found.")
        sys.exit(1)


def cmd_advisory_scan(args):
    agent = FeatureDocAgent(args.base_dir, verbose=args.verbose)
    result = agent.advisory_scan(since=args.since, dry_run=args.dry_run)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    
    if args.json:
        print(json.dumps(result, indent=2))
        return
    
    print(f"\nAdvisory Scan Results (since {result['since']}):")
    print(f"  Scan date: {result['scan_date'][:19]}")
    print(f"  Dry run: {'Yes' if result['dry_run'] else 'No'}")
    
    if result["errors"]:
        print(f"\nErrors encountered:")
        for error in result["errors"]:
            print(f"  - {error}")
    
    print(f"\nSources checked:")
    print(f"  - Red Hat Security Data API: {len(result['redhat_cves'])} CVEs")
    print(f"  - GitHub Security Advisories: {len(result['github_advisories'])} advisories")
    
    if result["added"]:
        print(f"\nAdded {len(result['added'])} new advisories:")
        for adv in result["added"]:
            print(f"  {adv['id']} [{adv['severity'].upper()}]")
            print(f"    {adv['title']}")
            print(f"    Features: {', '.join(adv['features'])}")
            if adv.get('url'):
                print(f"    URL: {adv['url']}")
            print()
    
    if result["skipped"]:
        print(f"\nSkipped {len(result['skipped'])} advisories:")
        for skip in result["skipped"]:
            print(f"  {skip['id']} - {skip['reason']}")
    
    if not result["added"] and not result["skipped"]:
        print("\nNo new advisories found.")
    
    print()


def _extract_test_data(results: dict, feature_id: str) -> dict:
    from datetime import datetime

    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "result": "UNKNOWN",
    }

    for suite in results.get("suites", []):
        for pb in suite.get("playbooks", []):
            if pb.get("success") and pb.get("output"):
                import re
                output = pb["output"]

                m = re.search(r'cluster[_-]?name[=:\s]+([^\s,]+)', output, re.IGNORECASE)
                if m:
                    data["cluster_name"] = m.group(1)

                m = re.search(r'region[=:\s]+([a-z]{2}-[a-z]+-\d)', output, re.IGNORECASE)
                if m:
                    data["region"] = m.group(1)

                m = re.search(r'version[=:\s]+(4\.\d+\.\d+[^\s]*)', output, re.IGNORECASE)
                if m:
                    data["version"] = m.group(1)

    all_passed = all(
        pb.get("success", False)
        for suite in results.get("suites", [])
        for pb in suite.get("playbooks", [])
    )
    data["provision_result"] = "PASS" if all_passed else "FAIL"
    data["result"] = data["provision_result"]

    total_duration = results.get("duration", 0)
    if total_duration:
        mins = int(total_duration / 60)
        secs = int(total_duration % 60)
        data["provision_duration"] = f"{mins}m {secs}s"

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Feature Documentation Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--base-dir", type=Path,
        default=Path(__file__).resolve().parent.parent,
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show doc status for all features")

    gaps_p = sub.add_parser("gaps", help="Run gap analysis")
    gaps_p.add_argument("--json", action="store_true")

    stale_p = sub.add_parser("stale", help="Detect stale docs from git changes")
    stale_p.add_argument("--since", default="HEAD~1")

    gen_p = sub.add_parser("generate", help="Generate doc from template")
    gen_p.add_argument("feature_id", help="Feature ID or ALL")

    upd_p = sub.add_parser("update", help="Update live test record")
    upd_p.add_argument("feature_id")
    upd_p.add_argument("--test-data", type=str)
    upd_p.add_argument("--results-file", type=str)

    ups_p = sub.add_parser("upstream", help="Check a specific upstream CAPA PR impact on features")
    ups_p.add_argument("pr_url", help="GitHub PR URL (e.g., https://github.com/stolostron/cluster-api-provider-aws/pull/102)")
    ups_p.add_argument("--json", action="store_true")

    watch_p = sub.add_parser("watch", help="Auto-check upstream repo for new changes affecting features")
    watch_p.add_argument("--repo", type=str, default=None,
                         help="Upstream repo (default: stolostron/cluster-api-provider-aws)")
    watch_p.add_argument("--branch", type=str, default="backplane-2.11",
                         help="Branch to watch (default: backplane-2.11)")
    watch_p.add_argument("--json", action="store_true")

    check_p = sub.add_parser("check", help="Unified check for local and upstream changes")
    check_p.add_argument("--since", default="HEAD~1",
                         help="Git reference for local change detection (default: HEAD~1)")
    check_p.add_argument("--json", action="store_true",
                         help="Output in JSON format for CI use")
    check_p.add_argument("--auto-test", action="store_true",
                         help="Automatically execute tests for affected features")
    check_p.add_argument("--auto-test-dry-run", action="store_true",
                         help="Show what tests would run without executing")
    check_p.add_argument("--auto-test-max", type=int, default=5,
                         help="Maximum number of features to auto-test (default: 5)")

    adv_add_p = sub.add_parser("advisory-add", help="Add a security advisory / CVE")
    adv_add_p.add_argument("advisory_id", help="Advisory ID (e.g., CVE-2026-12345)")
    adv_add_p.add_argument("title", help="Short title")
    adv_add_p.add_argument("--description", type=str, default="")
    adv_add_p.add_argument("--severity", choices=["critical", "high", "medium", "low"], default="medium")
    adv_add_p.add_argument("--features", type=str, default=None,
                           help="Comma-separated feature IDs (auto-detected from title if omitted)")
    adv_add_p.add_argument("--url", type=str, default="")
    adv_add_p.add_argument("--json", action="store_true")

    adv_list_p = sub.add_parser("advisory-list", help="List advisories")
    adv_list_p.add_argument("--all", action="store_true", help="Include resolved")
    adv_list_p.add_argument("--json", action="store_true")

    adv_resolve_p = sub.add_parser("advisory-resolve", help="Mark advisory as resolved")
    adv_resolve_p.add_argument("advisory_id")

    adv_scan_p = sub.add_parser("advisory-scan", help="Scan for new CVEs and advisories")
    adv_scan_p.add_argument("--since", type=str, default=None,
                            help="Scan for CVEs since date (YYYY-MM-DD, default: 30 days ago or last scan)")
    adv_scan_p.add_argument("--dry-run", action="store_true",
                            help="Show what would be added without adding")
    adv_scan_p.add_argument("--json", action="store_true",
                            help="Output results as JSON")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "gaps":
        cmd_gaps(args)
    elif args.command == "stale":
        cmd_stale(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "upstream":
        cmd_upstream(args)
    elif args.command == "watch":
        cmd_watch(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "advisory-add":
        cmd_advisory_add(args)
    elif args.command == "advisory-list":
        cmd_advisory_list(args)
    elif args.command == "advisory-resolve":
        cmd_advisory_resolve(args)
    elif args.command == "advisory-scan":
        cmd_advisory_scan(args)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
