#!/usr/bin/env python3
"""Verify the add-feature-test skill against features that already exist in the repo.

`.claude/skills/add-feature-test/SKILL.md` tells an agent which files to touch to add
a feature test, and its Definition of Done lists what "done" looks like. This script
takes a shipped feature, derives what the skill says every layer *should* contain
from the registry alone, and checks each layer actually contains it. A failure means
either the doc drifted from the code or the feature is incomplete; both are worth
knowing. `SKILLS.md` at the repo root is the human entry point to the same procedure.

Default feature is disk_size, because its feature id, CLI alias and var_map variable
are three different strings and it is a non-boolean on ROSAMachinePool -- so every
seam the skill warns about is actually load-bearing here. A feature whose id, alias
and variable are all the same string (fips, no_cni) would pass this script even with
var_map deleted.

Not every feature is wired the standard way. The skill documents three variants
(references/variants.md) and this script derives each from repo data rather than
carrying a list of forgiven feature ids, which would rot the moment someone added to
it to turn CI green:

  * externally verified -- listed in `externally_verified_features` in
    tasks/features/setup_feature_verification.yml, so suite 21 drops it instead of
    rejecting it. Steps 4-6 do not apply; instead we check that the registry
    `playbook:` key and that list agree.
  * ROSANetwork -- renders through rosa-network-config.yaml.j2, not the two
    control-plane templates, so the template seam is checked against that file.
  * consumed by a playbook -- the mapped variable is read by a task rather than a
    template conditional (byon's `byon_vpc` is a control-flow flag). We cannot tell
    that shape apart from a genuinely unwired variable by data alone, so a variable
    missing from the expected templates but present elsewhere in the repo is a WARN
    naming where it was found; missing everywhere stays a FAIL.

    ./scripts/verify_skills_md.py [feature_id]
    ./scripts/verify_skills_md.py --all
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
TEMPLATE_VERSIONS = ("4.22", "5.0")
TEMPLATES = ("rosa-controlplane-only.yaml.j2", "rosa-combined-automation.yaml.j2")
NETWORK_TEMPLATE = "rosa-network-config.yaml.j2"
CRD_FOR_RESOURCE = {
    "ROSAControlPlane": "rosacontrolplanes.controlplane.cluster.x-k8s.io",
    "ROSAMachinePool": "rosamachinepools.infrastructure.cluster.x-k8s.io",
    "ROSANetwork": "rosanetworks.infrastructure.cluster.x-k8s.io",
}


class Report:
    """Collects pass/fail lines so every check runs before the script exits."""

    def __init__(self, quiet=False):
        self.failures = []
        self.warnings = []
        self.quiet = quiet

    def _emit(self, status, section, label, detail):
        if not self.quiet:
            print(
                f"  [{status}] {section:<9} {label}"
                + (f" -- {detail}" if detail else "")
            )

    def check(self, section, label, ok, detail=""):
        self._emit("ok  " if ok else "FAIL", section, label, detail)
        if not ok:
            self.failures.append(f"{section} {label}: {detail}")
        return ok

    def warn(self, section, label, detail=""):
        """A check that does not apply in the shape this feature actually has."""
        self._emit("warn", section, label, detail)
        self.warnings.append(f"{section} {label}: {detail}")
        return True


def read(path):
    """Raw file contents -- used where the check is about literal text."""
    return (BASE / path).read_text()


def load(path):
    """Parsed YAML."""
    return yaml.safe_load(read(path))


def task_var(path, name):
    """Find a `vars:` value by name anywhere in a task file.

    Read rather than duplicated: these lists are what actually run, and a copy here
    would be one more thing to drift.
    """
    for task in load(path):
        value = (task.get("vars") or {}).get(name)
        if value is not None:
            return value
    return None


def externally_verified():
    """Features suite 21 deliberately does not verify, read from the playbook itself."""
    return set(
        task_var(
            "tasks/features/setup_feature_verification.yml",
            "externally_verified_features",
        )
        or []
    )


def grep_repo(needle):
    """Where else in the tracked tree does this variable appear?

    Used only to turn 'variable is absent from the templates' into either a WARN
    (it is consumed somewhere else, which is a documented variant) or a FAIL (it is
    wired nowhere, which is the bug the skill warns about).
    """
    try:
        out = subprocess.run(
            [
                "git",
                "grep",
                "-l",
                needle,
                "--",
                "playbooks",
                "tasks",
                "roles",
                "templates",
            ],
            cwd=BASE,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.stdout.splitlines() if line]


def is_provisioning_consumer(path):
    """Could this file plausibly be what reads the template variable?

    Deliberately narrow. The question being answered is "is this feature wired
    somewhere other than the template, or is it wired nowhere?", and only the
    provisioning path can answer yes.
    """
    if path.startswith("templates/"):
        return False
    if path.startswith("tasks/features/"):
        return False
    return path != "playbooks/verify_feature_flags.yml"


def playbook_tasks(path):
    """Every task of a single-play playbook, as parsed YAML."""
    plays = load(path)
    return [t for play in plays for t in (play.get("tasks") or [])]


def guards_on_membership(when, feature_id):
    """Is this `when:` exactly the positive membership test the skill requires?

    Matched exactly rather than by substring, because a substring search accepts
    `not ('x' in requested_features_list)` -- which contains the needle while
    inverting the meaning, skipping verification for a feature that *was* requested
    and running it for one that was not.

    A list is Ansible's implicit AND, so one element matching exactly is enough.
    """
    expected = f"'{feature_id}' in requested_features_list"
    if when is None:
        return False
    conditions = when if isinstance(when, list) else [when]
    return any(str(c).strip() == expected for c in conditions)


def find_check_task(tasks, task_rel):
    """The task that includes `task_rel`, and the `when:` that guards *it*.

    Returned together on purpose. Asking 'is the include present?' and 'does the
    guard string appear?' as two independent text searches lets a guard on an
    unrelated task vouch for an unguarded include.
    """
    for task in tasks:
        target = task.get("ansible.builtin.include_tasks") or task.get("include_tasks")
        if isinstance(target, dict):
            target = target.get("file")
        if isinstance(target, str) and target.endswith(task_rel.removeprefix("tasks/")):
            # Returned raw, list included: joining a list into one string would
            # hide which individual condition guards the include.
            return task, task.get("when")
    return None, None


def check_template_seam(rep, feat, var):
    """Step 3 -- the seam between the registry variable and the rendered manifest.

    variants.md: a ROSANetwork feature renders through rosa-network-config.yaml.j2
    rather than the two control-plane templates, so we look in the right file for
    the shape the registry declares.
    """
    expected = (
        (NETWORK_TEMPLATE,) if feat.get("resource") == "ROSANetwork" else TEMPLATES
    )
    for version in TEMPLATE_VERSIONS:
        for name in expected:
            body = read(f"templates/versions/{version}/features/{name}")
            if var in body:
                rep.check("step3", f"{version}/{name} reads ${var}", True)
                continue
            # Absent from the template. Consumed by a task or playbook is a
            # documented variant (byon's byon_vpc is a control-flow flag the
            # provisioning playbook reads); consumed nowhere is the failure mode
            # the skill exists to prevent, where the feature silently renders
            # nothing.
            #
            # Only a consumer on the *provisioning* path earns the downgrade to a
            # warning, and the exclusions matter:
            #   templates/ -- a sibling template must not excuse a missing one.
            #     Dropping the block from rosa-controlplane-only.yaml.j2 while
            #     leaving it in rosa-combined-automation.yaml.j2 is exactly the
            #     half-wired feature this check is for.
            #   the verification layer -- tasks/features/ and
            #     verify_feature_flags.yml name feature *ids*, and for a feature
            #     whose var equals its id (fips, no_cni) every one of those
            #     mentions would otherwise look like a consumer.
            found = [p for p in grep_repo(var) if is_provisioning_consumer(p)]
            if found:
                rep.warn(
                    "step3",
                    f"{version}/{name} does not read ${var}",
                    f"consumed instead by {', '.join(found[:3])}",
                )
            else:
                rep.check(
                    "step3",
                    f"{version}/{name} reads ${var}",
                    False,
                    f"${var} is read by no template and by nothing on the "
                    f"provisioning path -- the feature would render nothing",
                )


def verify(feature_id, quiet=False):
    """Run every check for one feature. Returns (failures, warnings) as string lists."""
    registry = load("templates/schemas/feature-registry.yml")
    compat = load("templates/schemas/version-compatibility.yml")
    vff = read("playbooks/verify_feature_flags.yml")
    vff_tasks = playbook_tasks("playbooks/verify_feature_flags.yml")
    readme = read("README.md")
    rep = Report(quiet=quiet)

    features = {f["id"]: f for s in registry["suites"] for f in s.get("features", [])}
    if feature_id not in features:
        raise KeyError(
            f"Unknown feature '{feature_id}'. Known: {', '.join(sorted(features))}"
        )

    feat = features[feature_id]
    aliases = {v: k for k, v in registry["cli_aliases"].items()}

    # ---- The registry is the single source of truth (SKILL.md, Architecture):
    # ---- everything below is derived from it, then looked for in the layer that
    # ---- must agree.
    alias = aliases.get(feature_id, feature_id)
    var = registry.get("var_map", {}).get(feature_id, feature_id)
    k8s_field = feat.get("k8s_field", "")
    crd_field = k8s_field.removeprefix(".spec.")
    resource = feat.get("resource", "")
    min_version = compat["feature_availability"].get(feature_id, {}).get("min_version")
    external = feature_id in externally_verified()

    if not quiet:
        print(f"\nVerifying the add-feature-test skill against feature '{feature_id}'")
        print(
            f"  derived from registry: alias={alias} var={var} "
            f"field={crd_field or '-'} resource={resource or '-'} "
            f"min_version={min_version or '-'}"
            + (" [externally verified]" if external else "")
            + "\n"
        )

    # ---- Step 1: registration --------------------------------------------------
    rep.check(
        "step1",
        "listed in cli_features",
        feature_id in registry["cli_features"],
        f"feature-registry.yml cli_features has no '{feature_id}'",
    )
    rep.check(
        "step1",
        "has k8s_field and resource",
        bool(k8s_field and resource),
        f"k8s_field={k8s_field!r} resource={resource!r}",
    )
    rep.check(
        "step1",
        "type is a known kind",
        feat.get("type")
        in {
            "boolean",
            "string",
            "number",
            "select",
            "list",
            "key_value",
            "range",
            "action",
            "version",
        },
        str(feat.get("type")),
    )
    # variants.md: a feature with its own verification playbook must also be in
    # externally_verified_features, or suite 21 rejects it as unknown at runtime.
    rep.check(
        "step1",
        "registry playbook: and externally_verified_features agree",
        bool(feat.get("playbook")) == external,
        f"playbook={feat.get('playbook')!r} externally_verified={external}",
    )

    # ---- Step 2: version gate --------------------------------------------------
    rep.check(
        "step2",
        "feature_availability entry exists",
        min_version is not None,
        f"version-compatibility.yml feature_availability has no '{feature_id}' "
        f"-- the feature is gated on no version at all",
    )
    registry_min = feat.get("min_version")
    rep.check(
        "step2",
        "registry min_version agrees (if present)",
        registry_min is None or registry_min == min_version,
        f"registry={registry_min} compatibility={min_version}",
    )

    # ---- Step 3: templates -----------------------------------------------------
    if external:
        rep.warn(
            "step3",
            "template seam not checked",
            "externally verified: rendered by its own playbook",
        )
    else:
        check_template_seam(rep, feat, var)
    same = all(
        (BASE / f"templates/versions/4.22/features/{n}").read_bytes()
        == (BASE / f"templates/versions/5.0/features/{n}").read_bytes()
        for n in TEMPLATES
    )
    differing = [
        n
        for n in TEMPLATES
        if (BASE / f"templates/versions/4.22/features/{n}").read_bytes()
        != (BASE / f"templates/versions/5.0/features/{n}").read_bytes()
    ]
    rep.check(
        "step3",
        "5.0 templates byte-identical to 4.22",
        same,
        f"differs: {', '.join(differing)}" if differing else "",
    )

    # ---- Steps 4 & 5: verification wiring --------------------------------------
    if external:
        rep.warn(
            "step4",
            "crd_field_map / CHECK / task not checked",
            "externally verified: see its own playbook",
        )
    else:
        mapped = re.search(
            rf"^      {feature_id}: \{{ crd: \"([^\"]+)\", field: \"([^\"]+)\" \}}",
            vff,
            re.M,
        )
        rep.check(
            "step4",
            "crd_field_map entry exists",
            mapped is not None,
            f"verify_feature_flags.yml crd_field_map has no '{feature_id}' entry "
            f"-- every rescue for it would be a flat FAIL",
        )
        if mapped:
            crd_name, mapped_field = mapped.groups()
            rep.check(
                "step4",
                "crd_field_map CRD matches registry resource",
                crd_name == CRD_FOR_RESOURCE.get(resource),
                f"{crd_name} vs {resource}",
            )
            # The mapped field may name the registry path or one of its parents --
            # the rescue path schema-checks the first segment, so pointing at a
            # parent (defaultMachinePoolSpec for .spec.defaultMachinePoolSpec.
            # autoscaling) is legitimate. What must not pass is a *sibling* under
            # the same top-level key, which comparing first segments would allow.
            rep.check(
                "step4",
                "crd_field_map field matches registry k8s_field",
                crd_field == mapped_field or crd_field.startswith(mapped_field + "."),
                f"{mapped_field} vs {k8s_field}",
            )

        task_rel = f"tasks/features/verify_{feature_id}.yml"
        include_task, include_when = find_check_task(vff_tasks, task_rel)
        rep.check(
            "step5",
            "CHECK block includes the task file",
            include_task is not None,
            f"no task in verify_feature_flags.yml includes {task_rel}",
        )
        # Checked on the including task itself, not anywhere in the file: a guard
        # on an unrelated task would otherwise satisfy a plain text search while
        # this feature's check ran unguarded on every suite-21 run.
        rep.check(
            "step5",
            "CHECK is guarded by requested_features_list",
            guards_on_membership(include_when, feature_id),
            f"when={include_when!r}",
        )

        # ---- Step 6: the verification task -------------------------------------
        if rep.check("step6", "task file exists", (BASE / task_rel).exists(), task_rel):
            task = read(task_rel)
            rep.check(
                "step6", "has block/rescue", "block:" in task and "rescue:" in task
            )
            rep.check(
                "step6",
                "delegates to verify_feature_rescue.yml",
                "verify_feature_rescue.yml" in task,
            )
            rep.check(
                "step6",
                "rescue passes the right feature_id",
                re.search(rf"feature_id: {feature_id}\b", task) is not None,
            )
            rep.check("step6", "increments features_passed", "features_passed" in task)
            rep.check(
                "step6",
                "asserts carry PASS and FAIL messages",
                "FAIL:" in task and "PASS:" in task,
            )

    # ---- Step 7: AWS dependence ------------------------------------------------
    # A check that calls boto3 but is not declared reports a clean PASS on a machine
    # with no boto3, having never looked at AWS.
    task_path = BASE / f"tasks/features/verify_{feature_id}.yml"
    if task_path.exists():
        uses_boto3 = "boto3" in task_path.read_text()
        declared = feature_id in (
            task_var(
                "tasks/features/report_feature_verification.yml",
                "aws_dependent_features",
            )
            or []
        )
        rep.check(
            "step7",
            "boto3 use declared in aws_dependent_features",
            uses_boto3 == declared,
            f"uses boto3={uses_boto3} declared={declared}",
        )

    # ---- Step 9: documentation -------------------------------------------------
    pages = [
        p
        for p in (BASE / "docs/features").glob("*.md")
        if f"| Feature ID | `{feature_id}` |" in p.read_text()
    ]
    if rep.check(
        "step9", "docs page exists", len(pages) == 1, f"found {[p.name for p in pages]}"
    ):
        page = pages[0].read_text()
        rows = (
            ("CLI Flag", f"`--feature {alias}`"),
            ("CRD Resource", f"`{resource}`"),
            ("K8s Field", f"`{k8s_field}`"),
            ("Ansible Variable", f"`{var}`"),
            ("Min Version", str(min_version)),
        )
        for label, expected in rows:
            # Containment, not equality: a feature with two destinations lists both
            # in one row (audit_logging -> cloudWatchlogForwarder + s3LogForwarder).
            row = re.search(rf"^\| {re.escape(label)} \| (.+) \|$", page, re.M)
            rep.check(
                "step9",
                f"docs table '{label}' matches registry",
                row is not None and expected in row.group(1),
                f"want {expected} in {row.group(1) if row else '<row missing>'}",
            )
        rep.check(
            "step9",
            "docs page linked from README",
            f"docs/features/{pages[0].name}" in readme,
            f"README.md contains no link to docs/features/{pages[0].name}",
        )
    rep.check(
        "step9",
        "README lists the CLI flag",
        f"--feature {alias}" in readme,
        f"README.md does not contain '--feature {alias}'",
    )

    # ---- The CLI actually resolves it the way the registry says -----------------
    sys.path.insert(0, str(BASE))
    # Imported here, not at module scope, because it only resolves after the
    # sys.path insert above -- pylint cannot see that, hence import-error too.
    # pylint: disable-next=import-outside-toplevel,import-error
    from feature_manager import FeatureManager

    manager = FeatureManager(BASE)
    resolved = manager.resolve_to_extra_vars([alias])
    rep.check(
        "cli",
        "alias resolves to the feature id",
        manager.resolve_alias(alias) == feature_id,
    )
    rep.check(
        "cli",
        "requested_features carries the id",
        feature_id in resolved.get("requested_features", "").split(","),
    )
    if feat.get("type") == "boolean":
        rep.check("cli", f"emits {var}=true", resolved.get(var) == "true")
    else:
        ci_default = feat.get("ci_default")
        effective = ci_default if ci_default is not None else feat.get("default")
        if effective is None or effective in ("", {}, []):
            # gotchas.md: a typed feature with an empty default emits no var at
            # all until the user passes -e. That is why required_vars exists.
            rep.check(
                "cli",
                f"omits {var} (empty default, needs -e)",
                var not in resolved,
                f"got {resolved.get(var)!r}",
            )
        else:
            # Mirrors FeatureManager._serialize_value.
            expected = (
                json.dumps(effective)
                if feat.get("type") in ("key_value", "list", "range")
                else str(effective)
            )
            rep.check(
                "cli",
                f"emits {var}={expected} (ci_default or default)",
                resolved.get(var) == expected,
                f"got {resolved.get(var)!r}",
            )
        rep.check(
            "cli",
            f"emits feature_{feature_id}_enabled=true",
            resolved.get(f"feature_{feature_id}_enabled") == "true",
        )
    if min_version:
        below = "4.18" if min_version != "4.18" else None
        if below:
            rep.check(
                "cli",
                f"rejected below min_version ({below})",
                bool(manager.validate_features([alias], below)) or min_version <= below,
            )
    rep.check(
        "cli",
        "accepted at min_version",
        not manager.validate_features([alias], min_version or "4.22"),
    )

    return rep.failures, rep.warnings


def cli_features():
    """Every feature reachable from --feature, in registry order."""
    return load("templates/schemas/feature-registry.yml")["cli_features"]


def main(argv):
    if argv and argv[0] == "--all":
        worst = 0
        for feature_id in cli_features():
            failures, warnings = verify(feature_id, quiet=True)
            status = "FAIL" if failures else ("warn" if warnings else "ok  ")
            print(f"[{status}] {feature_id}")
            for line in failures:
                print(f"         FAIL {line}")
            for line in warnings:
                print(f"         warn {line}")
            worst = max(worst, 1 if failures else 0)
        print(
            "\n"
            + ("FAILED: see above" if worst else "OK: every feature matches the skill")
        )
        return worst

    feature_id = argv[0] if argv else "disk_size"
    try:
        failures, _ = verify(feature_id)
    except KeyError as exc:
        sys.exit(str(exc).strip('"'))

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s) disagree with the skill\n")
        for line in failures:
            print(f"  - {line}")
        print(
            "\nEither the skill drifted from the code, or this feature is incomplete."
        )
        return 1
    print(f"OK: '{feature_id}' matches every layer the skill describes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
