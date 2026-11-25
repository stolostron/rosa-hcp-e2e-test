#!/usr/bin/env python3
"""Verify SKILLS.md against a feature that already exists in the repo.

SKILLS.md tells an agent which files to touch to add a feature test, and §9 lists
what "done" looks like. This script takes one shipped feature, derives what SKILLS.md
says every layer *should* contain from the registry alone, and checks each layer
actually contains it. A failure means either the doc drifted from the code or the
feature is incomplete; both are worth knowing.

Default feature is disk_size, because its feature id, CLI alias and var_map variable
are three different strings and it is a non-boolean on ROSAMachinePool -- so every
seam SKILLS.md warns about is actually load-bearing here. A feature whose id, alias
and variable are all the same string (fips, no_cni) would pass this script even with
var_map deleted.

    ./scripts/verify_skills_md.py [feature_id]
"""

import json
import re
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
TEMPLATE_VERSIONS = ("4.22", "5.0")
TEMPLATES = ("rosa-controlplane-only.yaml.j2", "rosa-combined-automation.yaml.j2")


class Report:
    """Collects pass/fail lines so every check runs before the script exits."""

    def __init__(self):
        self.failures = []

    def check(self, section, label, ok, detail=""):
        status = "ok  " if ok else "FAIL"
        print(f"  [{status}] {section:<9} {label}" + (f" -- {detail}" if detail else ""))
        if not ok:
            self.failures.append(f"{section} {label}: {detail}")
        return ok


def read(path):
    """Raw file contents -- used where the check is about literal text."""
    return (BASE / path).read_text()


def load(path):
    """Parsed YAML."""
    return yaml.safe_load(read(path))


def main(feature_id):
    registry = load("templates/schemas/feature-registry.yml")
    compat = load("templates/schemas/version-compatibility.yml")
    vff = read("playbooks/verify_feature_flags.yml")
    readme = read("README.md")
    rep = Report()

    features = {f["id"]: f for s in registry["suites"] for f in s.get("features", [])}
    if feature_id not in features:
        sys.exit(f"Unknown feature '{feature_id}'. Known: {', '.join(sorted(features))}")

    feat = features[feature_id]
    aliases = {v: k for k, v in registry["cli_aliases"].items()}

    # ---- The registry is the single source of truth (SKILLS.md §4): everything
    # ---- below is derived from it, then looked for in the layer that must agree.
    alias = aliases.get(feature_id, feature_id)
    var = registry.get("var_map", {}).get(feature_id, feature_id)
    k8s_field = feat.get("k8s_field", "")
    crd_field = k8s_field.removeprefix(".spec.")
    resource = feat.get("resource", "")
    min_version = compat["feature_availability"].get(feature_id, {}).get("min_version")

    print(f"\nVerifying SKILLS.md against feature '{feature_id}'")
    print(f"  derived from registry: alias={alias} var={var} "
          f"field={crd_field or '-'} resource={resource or '-'} min_version={min_version or '-'}\n")

    # ---- Step 1: registration --------------------------------------------------
    rep.check("step1", "listed in cli_features", feature_id in registry["cli_features"])
    rep.check("step1", "has k8s_field and resource", bool(k8s_field and resource),
              f"k8s_field={k8s_field!r} resource={resource!r}")
    rep.check("step1", "type is a known kind",
              feat.get("type") in {"boolean", "string", "number", "select", "list",
                                   "key_value", "range", "action", "version"},
              str(feat.get("type")))

    # ---- Step 2: version gate --------------------------------------------------
    rep.check("step2", "feature_availability entry exists", min_version is not None)
    registry_min = feat.get("min_version")
    rep.check("step2", "registry min_version agrees (if present)",
              registry_min is None or registry_min == min_version,
              f"registry={registry_min} compatibility={min_version}")

    # ---- Step 3: templates -----------------------------------------------------
    for version in TEMPLATE_VERSIONS:
        for name in TEMPLATES:
            body = read(f"templates/versions/{version}/features/{name}")
            rep.check("step3", f"{version}/{name} reads ${var}", var in body)
    same = all(
        (BASE / f"templates/versions/4.22/features/{n}").read_bytes()
        == (BASE / f"templates/versions/5.0/features/{n}").read_bytes()
        for n in TEMPLATES
    )
    rep.check("step3", "5.0 templates byte-identical to 4.22", same)

    # ---- Steps 4 & 5: verification wiring --------------------------------------
    mapped = re.search(rf"^      {feature_id}: \{{ crd: \"([^\"]+)\", field: \"([^\"]+)\" \}}",
                       vff, re.M)
    rep.check("step4", "crd_field_map entry exists", mapped is not None)
    if mapped:
        crd_name, mapped_field = mapped.groups()
        expected_crd = {
            "ROSAControlPlane": "rosacontrolplanes.controlplane.cluster.x-k8s.io",
            "ROSAMachinePool": "rosamachinepools.infrastructure.cluster.x-k8s.io",
            "ROSANetwork": "rosanetworks.infrastructure.cluster.x-k8s.io",
        }.get(resource)
        rep.check("step4", "crd_field_map CRD matches registry resource",
                  crd_name == expected_crd, f"{crd_name} vs {resource}")
        rep.check("step4", "crd_field_map field matches registry k8s_field",
                  mapped_field.split(".")[0] == crd_field.split(".")[0],
                  f"{mapped_field} vs {k8s_field}")

    task_rel = f"tasks/features/verify_{feature_id}.yml"
    include = f'include_tasks: "{{{{ playbook_dir }}}}/../{task_rel}"'
    rep.check("step5", "CHECK block includes the task file", include in vff)
    rep.check("step5", "CHECK is guarded by requested_features_list",
              f"when: \"'{feature_id}' in requested_features_list\"" in vff)

    # ---- Step 6: the verification task -----------------------------------------
    if rep.check("step6", "task file exists", (BASE / task_rel).exists(), task_rel):
        task = read(task_rel)
        rep.check("step6", "has block/rescue", "block:" in task and "rescue:" in task)
        rep.check("step6", "delegates to verify_feature_rescue.yml",
                  "verify_feature_rescue.yml" in task)
        rep.check("step6", "rescue passes the right feature_id",
                  re.search(rf"feature_id: {feature_id}\b", task) is not None)
        rep.check("step6", "increments features_passed", "features_passed" in task)
        rep.check("step6", "asserts carry PASS and FAIL messages",
                  "FAIL:" in task and "PASS:" in task)

    # ---- Step 9: documentation -------------------------------------------------
    pages = [p for p in (BASE / "docs/features").glob("*.md")
             if f"| Feature ID | `{feature_id}` |" in p.read_text()]
    if rep.check("step9", "docs page exists", len(pages) == 1,
                 f"found {[p.name for p in pages]}"):
        page = pages[0].read_text()
        for label, expected in (("CLI Flag", f"`--feature {alias}`"),
                                ("CRD Resource", f"`{resource}`"),
                                ("K8s Field", f"`{k8s_field}`"),
                                ("Ansible Variable", f"`{var}`")):
            # Containment, not equality: a feature with two destinations lists both
            # in one row (audit_logging -> cloudWatchlogForwarder + s3LogForwarder).
            row = re.search(rf"^\| {re.escape(label)} \| (.+) \|$", page, re.M)
            rep.check("step9", f"docs table '{label}' matches registry",
                      row is not None and expected in row.group(1),
                      f"want {expected} in {row.group(1) if row else '<row missing>'}")
        rep.check("step9", "docs page linked from README",
                  f"docs/features/{pages[0].name}" in readme)
    rep.check("step9", "README lists the CLI flag", f"--feature {alias}" in readme)

    # ---- The CLI actually resolves it the way the registry says -----------------
    sys.path.insert(0, str(BASE))
    from feature_manager import FeatureManager  # pylint: disable=import-outside-toplevel

    manager = FeatureManager(BASE)
    resolved = manager.resolve_to_extra_vars([alias])
    rep.check("cli", "alias resolves to the feature id",
              manager.resolve_alias(alias) == feature_id)
    rep.check("cli", "requested_features carries the id",
              feature_id in resolved.get("requested_features", "").split(","))
    if feat.get("type") == "boolean":
        rep.check("cli", f"emits {var}=true", resolved.get(var) == "true")
    else:
        ci_default = feat.get("ci_default")
        effective = ci_default if ci_default is not None else feat.get("default")
        if effective is None or effective in ("", {}, []):
            # SKILLS.md §8: a typed feature with an empty default emits no var at
            # all until the user passes -e. That is why required_vars exists.
            rep.check("cli", f"omits {var} (empty default, needs -e)",
                      var not in resolved, f"got {resolved.get(var)!r}")
        else:
            # Mirrors FeatureManager._serialize_value.
            expected = (json.dumps(effective)
                        if feat.get("type") in ("key_value", "list", "range")
                        else str(effective))
            rep.check("cli", f"emits {var}={expected} (ci_default or default)",
                      resolved.get(var) == expected, f"got {resolved.get(var)!r}")
        rep.check("cli", f"emits feature_{feature_id}_enabled=true",
                  resolved.get(f"feature_{feature_id}_enabled") == "true")
    if min_version:
        below = "4.18" if min_version != "4.18" else None
        if below:
            rep.check("cli", f"rejected below min_version ({below})",
                      bool(manager.validate_features([alias], below))
                      or min_version <= below)
    rep.check("cli", "accepted at min_version",
              not manager.validate_features([alias], min_version or "4.22"))

    print()
    if rep.failures:
        print(f"FAILED: {len(rep.failures)} check(s) disagree with SKILLS.md\n")
        for line in rep.failures:
            print(f"  - {line}")
        print("\nEither SKILLS.md drifted from the code, or this feature is incomplete.")
        return 1
    print(f"OK: '{feature_id}' matches every layer SKILLS.md describes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "disk_size"))
