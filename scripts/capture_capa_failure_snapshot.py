#!/usr/bin/env python3
"""Capture a pre-cleanup CAPA provisioning failure snapshot.

When a ROSA HCP provisioning run fails, the scenario runner still executes its
`always` cleanup stage, which deletes the RosaControlPlane. Any diagnostic
gathering that happens after cleanup therefore reads a resource that carries a
deletionTimestamp and conditions rewritten to "deleting" — the failure-time
status is gone. This script is invoked at failure time, before cleanup, so the
status that explains the failure is preserved.

Only an explicit allowlist of non-secret fields is copied. Annotations, labels,
managedFields, Secrets, kubeconfigs, tokens and every key that is not named
below are dropped rather than passed through. AWS account IDs are masked and
long strings are truncated, so an unredacted provider error cannot be written
out wholesale.

Usage:
  capture_capa_failure_snapshot.py --cluster-name NAME --namespace NS
                                   [--role-config NAME]
                                   [--fallback-dir DIR] [--timeout SECONDS]

The snapshot is written to $ARTIFACT_DIR when that variable is set and
non-empty, otherwise to --fallback-dir. The resulting path is printed on
stdout.

Every capture failure (missing `oc`, non-zero exit, timeout, unparseable
output, unwritable directory) exits 0: a failed capture must never mask the
test failure that triggered it, and must never stop the cleanup that follows
it. Only argparse rejecting the command line itself exits non-zero, and the
calling task sets `failed_when: false` regardless.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# Bound every captured string so an external error payload cannot be dumped
# wholesale into a public CI artifact.
MAX_STRING_LENGTH = 2000
# Bound list-valued fields so a pathological resource cannot inflate the file.
MAX_LIST_ITEMS = 25
# Per-`oc` invocation timeout. Two resources are read, so the whole capture is
# bounded by roughly twice this value.
DEFAULT_TIMEOUT_SECONDS = 30

ACCOUNT_ID_PLACEHOLDER = "<redacted-account-id>"
ACCESS_KEY_PLACEHOLDER = "<redacted-access-key-id>"
TRUNCATION_SUFFIX = "...[truncated]"

_ARN_ACCOUNT_RE = re.compile(r"(arn:aws[a-zA-Z0-9-]*:[^:\s]*:[^:\s]*:)(\d{12})")
_BARE_ACCOUNT_RE = re.compile(r"(?<![\d.-])\d{12}(?![\d.-])")
# AWS unique-identifier prefixes (access keys, temporary session keys, role and
# user ids). Provider error text routinely quotes these back.
_ACCESS_KEY_RE = re.compile(
    r"\b(?:A3T|ABIA|ACCA|AGPA|AIDA|AIPA|AKIA|ANPA|ANVA|APKA|AROA|ASCA|ASIA)[A-Z0-9]{12,}\b"
)

# Allowlisted fields. Nothing outside these names reaches the snapshot.
# deletionTimestamp is kept precisely so a reader can tell a pre-cleanup
# snapshot from one taken after the cleanup stage started deleting.
METADATA_FIELDS = ("name", "namespace", "creationTimestamp", "deletionTimestamp")
RCP_SPEC_FIELDS = (
    "version",
    "channelGroup",
    "region",
    "rosaClusterName",
    "domainPrefix",
)
# References are captured by name only — never the referenced object or its
# content. The credentials secret *name* tells a reader which identity the
# control plane used, which is what an STS 403 turns on; the Secret itself is
# never read.
RCP_SPEC_REF_FIELDS = ("rosaNetworkRef", "rosaRoleConfigRef", "credentialsSecretRef")
RCP_STATUS_FIELDS = (
    "ready",
    "id",
    "failureReason",
    "failureMessage",
    "oidcEndpointURL",
)

RRC_SPEC_NESTED_FIELDS = {
    "accountRoleConfig": ("prefix", "version", "path"),
    "operatorRoleConfig": ("prefix", "oidcID", "path"),
}
RRC_SPEC_FIELDS = ("oidcProviderType",)
RRC_STATUS_FIELDS = (
    "ready",
    "phase",
    "id",
    "oidcID",
    "oidcProviderArn",
    "installerRoleArn",
    "supportRoleArn",
    "workerRoleArn",
)

CONDITION_FIELDS = ("type", "status", "reason", "message", "lastTransitionTime")


def redact(value):
    """Mask AWS account IDs and key IDs, and bound the length of a string."""
    if not isinstance(value, str):
        return value
    masked = _ARN_ACCOUNT_RE.sub(r"\g<1>" + ACCOUNT_ID_PLACEHOLDER, value)
    masked = _BARE_ACCOUNT_RE.sub(ACCOUNT_ID_PLACEHOLDER, masked)
    masked = _ACCESS_KEY_RE.sub(ACCESS_KEY_PLACEHOLDER, masked)
    if len(masked) > MAX_STRING_LENGTH:
        masked = masked[:MAX_STRING_LENGTH] + TRUNCATION_SUFFIX
    return masked


def _scalar(value):
    """Return a redacted scalar, or None for anything that is not a scalar.

    Dicts and lists are rejected here on purpose: only fields explicitly
    handled by a nested allowlist may be structured.
    """
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return redact(value)
    return None


def _pick(source, fields):
    """Copy the allowlisted scalar fields that are present in `source`."""
    picked = {}
    if not isinstance(source, dict):
        return picked
    for field in fields:
        if field not in source:
            continue
        value = _scalar(source[field])
        if value is not None or source[field] is None:
            picked[field] = value
    return picked


def _pick_ref(source, fields):
    """Copy object references by name only, never the referenced content."""
    picked = {}
    if not isinstance(source, dict):
        return picked
    for field in fields:
        ref = source.get(field)
        if isinstance(ref, dict) and "name" in ref:
            picked[field] = {"name": _scalar(ref["name"])}
        elif isinstance(ref, str):
            picked[field] = {"name": redact(ref)}
    return picked


def reduce_conditions(conditions):
    """Reduce status conditions to the allowlisted, bounded summary fields."""
    reduced = []
    if not isinstance(conditions, list):
        return reduced
    for condition in conditions[:MAX_LIST_ITEMS]:
        if not isinstance(condition, dict):
            continue
        reduced.append(_pick(condition, CONDITION_FIELDS))
    return reduced


def _observed_kind(obj, expected):
    """Report the kind the server returned, not a hardcoded literal."""
    kind = _scalar(obj.get("kind"))
    return kind if isinstance(kind, str) and kind else expected


def summarize_control_plane(obj):
    """Build the allowlisted ROSAControlPlane summary."""
    if not isinstance(obj, dict):
        return None
    spec = obj.get("spec") if isinstance(obj.get("spec"), dict) else {}
    status = obj.get("status") if isinstance(obj.get("status"), dict) else {}
    summary_spec = _pick(spec, RCP_SPEC_FIELDS)
    summary_spec.update(_pick_ref(spec, RCP_SPEC_REF_FIELDS))
    return {
        "kind": _observed_kind(obj, "ROSAControlPlane"),
        "metadata": _pick(obj.get("metadata"), METADATA_FIELDS),
        "spec": summary_spec,
        "status": _pick(status, RCP_STATUS_FIELDS),
        "conditions": reduce_conditions(status.get("conditions")),
    }


def summarize_role_config(obj):
    """Build the allowlisted ROSARoleConfig summary."""
    if not isinstance(obj, dict):
        return None
    spec = obj.get("spec") if isinstance(obj.get("spec"), dict) else {}
    status = obj.get("status") if isinstance(obj.get("status"), dict) else {}
    summary_spec = _pick(spec, RRC_SPEC_FIELDS)
    for nested, fields in RRC_SPEC_NESTED_FIELDS.items():
        nested_summary = _pick(spec.get(nested), fields)
        if nested_summary:
            summary_spec[nested] = nested_summary
    return {
        "kind": _observed_kind(obj, "ROSARoleConfig"),
        "metadata": _pick(obj.get("metadata"), METADATA_FIELDS),
        "spec": summary_spec,
        "status": _pick(status, RRC_STATUS_FIELDS),
        "conditions": reduce_conditions(status.get("conditions")),
    }


def fetch_resource(kind, name, namespace, timeout):
    """Read one named resource with `oc get -o json`.

    Returns (parsed_object, error_message). Exactly one of the two is None.
    The call is read-only, explicitly typed and namespaced, and bounded by
    `timeout`; no failure mode raises.
    """
    command = ["oc", "get", f"{kind}/{name}", "-n", namespace, "-o", "json"]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s reading {kind}/{name}"
    except FileNotFoundError:
        return None, "oc binary not found"
    except OSError as exc:
        return None, f"failed to run oc for {kind}/{name}: {exc.__class__.__name__}"

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        reason = detail[0] if detail else "no stderr"
        return None, redact(
            f"oc get {kind}/{name} exited {completed.returncode}: {reason}"
        )

    try:
        parsed = json.loads(completed.stdout)
    except (ValueError, TypeError):
        return None, f"could not parse JSON for {kind}/{name}"

    if not isinstance(parsed, dict):
        return None, f"unexpected non-object JSON for {kind}/{name}"
    return parsed, None


def resolve_output_dir(fallback_dir):
    """$ARTIFACT_DIR wins when set and non-empty, otherwise the fallback."""
    artifact_dir = (os.environ.get("ARTIFACT_DIR") or "").strip()
    return artifact_dir if artifact_dir else fallback_dir


def build_snapshot(args, now):
    """Collect the allowlisted snapshot for the cluster named in `args`."""
    errors = []
    resources = {}

    control_plane, error = fetch_resource(
        "rosacontrolplane", args.cluster_name, args.namespace, args.timeout
    )
    if error:
        errors.append(error)
    resources["rosacontrolplane"] = summarize_control_plane(control_plane)

    if args.role_config:
        role_config, error = fetch_resource(
            "rosaroleconfig", args.role_config, args.namespace, args.timeout
        )
        if error:
            errors.append(error)
        resources["rosaroleconfig"] = summarize_role_config(role_config)

    return {
        "schemaVersion": 1,
        "capturedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": "pre-cleanup",
        "reason": "rosacontrolplane did not become ready",
        "cluster": {"name": args.cluster_name, "namespace": args.namespace},
        "resources": resources,
        "errors": errors[:MAX_LIST_ITEMS],
    }


def write_snapshot(snapshot, output_dir, now):
    """Write the snapshot JSON and return its path, or None if unwritable."""
    filename = f"capa-failure-snapshot-{now.strftime('%Y%m%dT%H%M%S')}.json"
    path = os.path.join(output_dir, filename)
    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        print(f"WARNING: could not write snapshot to {path}: {exc}", file=sys.stderr)
        return None
    return path


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--role-config", default="")
    parser.add_argument(
        "--fallback-dir",
        default="/tmp/diagnostics",
        help="Directory used when ARTIFACT_DIR is unset or empty",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args(argv)


def main(argv=None):
    """Capture the snapshot.

    Returns 0 for every capture failure so the real test failure and the
    cleanup that follows it are never affected; see the module docstring.
    """
    try:
        args = parse_args(argv)
        now = datetime.now(timezone.utc)
        snapshot = build_snapshot(args, now)
        path = write_snapshot(snapshot, resolve_output_dir(args.fallback_dir), now)
        if path:
            print(path)
    except Exception as exc:  # pylint: disable=broad-except
        print(
            f"WARNING: snapshot capture failed: {exc.__class__.__name__}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
