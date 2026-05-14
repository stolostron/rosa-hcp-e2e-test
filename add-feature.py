#!/usr/bin/env python3
"""
Add a new feature to the ROSA HCP feature registry.

Updates all required files:
  1. templates/schemas/feature-registry.yml (var_map, cli_aliases, cli_features, suite)
  2. templates/schemas/version-compatibility.yml (feature_availability)
  3. templates/versions/{version}/features/rosa-controlplane-only.yaml.j2 (conditional block)

Usage:
  ./add-feature.py my_feature_id \\
    --alias my-feature \\
    --name "My Feature" \\
    --description "Enable my feature" \\
    --var my_ansible_var \\
    --k8s-field ".spec.myField" \\
    --min-version 4.20

  ./add-feature.py --list-suites
  ./add-feature.py --dry-run ...
"""

import argparse
import copy
import re
import shutil
import sys
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).parent
REGISTRY_PATH = BASE_DIR / "templates" / "schemas" / "feature-registry.yml"
COMPAT_PATH = BASE_DIR / "templates" / "schemas" / "version-compatibility.yml"
TEMPLATE_DIR = BASE_DIR / "templates" / "versions"
TEMPLATE_NAME = "rosa-controlplane-only.yaml.j2"
FEATURE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, width=120)


def read_text(path):
    with open(path) as f:
        return f.read()


def write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


def err(msg):
    print(f"Error: {msg}", file=sys.stderr)


def parse_version_minor(ver):
    parts = ver.split(".")
    return int(parts[1]) if len(parts) >= 2 else int(parts[0])


def list_suites(registry):
    print("\nAvailable suites:\n")
    for suite in registry.get("suites", []):
        print(f"  {suite['id']:25s} {suite['name']} ({suite.get('phase', 'Day1')})")
    print()


def validate_inputs(args, registry):
    errors = []

    if not FEATURE_ID_RE.match(args.feature_id):
        errors.append(f"Invalid feature_id '{args.feature_id}'. Must be lowercase alphanumeric with underscores (e.g., my_feature)")

    if not all([args.name, args.description, args.var, args.k8s_field]):
        errors.append("--name, --description, --var, and --k8s-field are required")

    if args.feature_id in registry.get("var_map", {}):
        errors.append(f"Feature '{args.feature_id}' already exists in var_map")

    alias = args.alias or args.feature_id.replace("_", "-")
    if alias in registry.get("cli_aliases", {}):
        errors.append(f"Alias '{alias}' already exists in cli_aliases")

    if args.feature_id in registry.get("cli_features", []):
        errors.append(f"Feature '{args.feature_id}' already in cli_features")

    suite_ids = [s["id"] for s in registry.get("suites", [])]
    if args.suite not in suite_ids:
        errors.append(f"Suite '{args.suite}' not found. Use --list-suites to see options.")

    if args.depends_on and args.depends_on not in registry.get("var_map", {}):
        errors.append(f"Dependency '{args.depends_on}' not found in registry")

    return errors


def update_registry(registry, feature_id, alias, var_name, suite_id, feature_def, depends_on):
    reg = copy.deepcopy(registry)

    reg["var_map"][feature_id] = var_name
    reg["cli_aliases"][alias] = feature_id
    reg["cli_features"].append(feature_id)

    if depends_on:
        reg.setdefault("dependencies", {})[feature_id] = [depends_on]

    for suite in reg["suites"]:
        if suite["id"] == suite_id:
            suite.setdefault("features", []).append(feature_def)
            break

    return reg


def update_version_compat(compat, feature_id, min_version):
    comp = copy.deepcopy(compat)
    comp.setdefault("feature_availability", {})[feature_id] = {
        "min_version": min_version,
        "max_version": None,
    }
    return comp


def build_template_conditional(var_name, feat_type, template_block):
    if not template_block:
        if feat_type == "boolean":
            template_block = f"  {var_name}: true"
        else:
            template_block = f"  {var_name}: {{{{ {var_name} }}}}"

    if feat_type == "boolean":
        return f"{{% if {var_name} is defined and {var_name} | bool %}}\n{template_block}\n{{% endif %}}"
    else:
        return f"{{% if {var_name} is defined and {var_name} %}}\n{template_block}\n{{% endif %}}"


def add_to_templates(var_name, feat_type, template_block, min_version):
    conditional = build_template_conditional(var_name, feat_type, template_block)
    min_minor = parse_version_minor(min_version)

    changes = []
    for ver_dir in sorted(TEMPLATE_DIR.iterdir()):
        if not ver_dir.is_dir():
            continue
        try:
            ver_minor = parse_version_minor(ver_dir.name)
        except (ValueError, IndexError):
            continue
        if ver_minor < min_minor:
            continue

        template_path = ver_dir / "features" / TEMPLATE_NAME
        if not template_path.exists():
            continue

        text = read_text(template_path)

        # Insert before the log forwarding comment block
        marker = "  # ======================================\n  # LOG FORWARDING CONFIGURATION"
        if marker in text:
            new_text = text.replace(marker, f"{conditional}\n\n{marker}", 1)
            changes.append((ver_dir.name, template_path, new_text))
        else:
            # Fallback: insert before the MachinePool separator
            marker2 = "---\napiVersion: cluster.x-k8s.io"
            if marker2 in text:
                new_text = text.replace(marker2, f"{conditional}\n\n{marker2}", 1)
                changes.append((ver_dir.name, template_path, new_text))

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="Add a new feature to the ROSA HCP feature registry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("feature_id", nargs="?", help="Feature ID (e.g., my_feature)")
    parser.add_argument("--alias", help="CLI alias (e.g., my-feature). Default: feature_id with - instead of _")
    parser.add_argument("--name", help="Display name (e.g., 'My Feature')")
    parser.add_argument("--description", help="Short description")
    parser.add_argument("--var", help="Ansible extra var name")
    parser.add_argument("--type", default="boolean",
                        choices=["boolean", "string", "number", "select", "list", "key_value", "range"],
                        help="Feature type (default: boolean)")
    parser.add_argument("--default", default="false", help="Default value (default: false)")
    parser.add_argument("--k8s-field", help="K8s spec field (e.g., .spec.myField)")
    parser.add_argument("--resource", default="ROSAControlPlane", help="K8s resource (default: ROSAControlPlane)")
    parser.add_argument("--suite", default="cluster-config", help="Suite ID (default: cluster-config)")
    parser.add_argument("--min-version", default="4.19", help="Minimum OpenShift version (default: 4.19)")
    parser.add_argument("--depends-on", help="Feature ID this depends on")
    parser.add_argument("--template-block", help="Jinja2 YAML block to insert (indented, no conditionals)")
    parser.add_argument("--mutable", action="store_true", help="Feature can be changed after creation")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--list-suites", action="store_true", help="List available suite IDs")

    args = parser.parse_args()

    try:
        registry = load_yaml(REGISTRY_PATH)
    except FileNotFoundError:
        err(f"Registry not found: {REGISTRY_PATH}")
        return 1

    if args.list_suites:
        list_suites(registry)
        return 0

    if not args.feature_id:
        parser.print_help()
        return 1

    errors = validate_inputs(args, registry)
    if errors:
        for e in errors:
            err(e)
        return 1

    feature_id = args.feature_id
    alias = args.alias or feature_id.replace("_", "-")
    var_name = args.var

    feature_def = {
        "id": feature_id,
        "name": args.name,
        "description": args.description,
        "type": args.type,
        "mutable": args.mutable,
        "applies_to": ["create", "apply"] if args.mutable else ["create"],
        "default": yaml.safe_load(args.default) if args.default else False,
        "k8s_field": args.k8s_field,
        "resource": args.resource,
    }
    if args.min_version != "4.18":
        feature_def["min_version"] = args.min_version

    try:
        compat = load_yaml(COMPAT_PATH)
    except FileNotFoundError:
        err(f"Version compatibility file not found: {COMPAT_PATH}")
        return 1

    # Build all changes before writing anything
    new_registry = update_registry(registry, feature_id, alias, var_name, args.suite, feature_def, args.depends_on)
    new_compat = update_version_compat(compat, feature_id, args.min_version)
    template_changes = add_to_templates(var_name, args.type, args.template_block, args.min_version)

    # Show summary
    print(f"\n{'DRY RUN - ' if args.dry_run else ''}Adding feature: {feature_id}")
    print(f"  Alias: --feature {alias}")
    print(f"  Var: {var_name}")
    print(f"  Type: {args.type}")
    print(f"  Suite: {args.suite}")
    print(f"  Min version: {args.min_version}")
    if args.depends_on:
        print(f"  Depends on: {args.depends_on}")
    print()

    print("Files to update:")
    print(f"  1. {REGISTRY_PATH.relative_to(BASE_DIR)}")
    print(f"     - var_map: {feature_id} -> {var_name}")
    print(f"     - cli_aliases: {alias} -> {feature_id}")
    print(f"     - cli_features: + {feature_id}")
    print(f"     - suites.{args.suite}: + feature definition")
    print(f"  2. {COMPAT_PATH.relative_to(BASE_DIR)}")
    print(f"     - feature_availability: {feature_id} (min: {args.min_version})")
    for i, (ver, path, _) in enumerate(template_changes, 3):
        print(f"  {i}. {path.relative_to(BASE_DIR)}")
        print(f"     - conditional block for {var_name}")
    print()

    if args.dry_run:
        print("No changes made (dry-run mode)")
        return 0

    # Create backups
    backups = []
    try:
        for path in [REGISTRY_PATH, COMPAT_PATH] + [p for _, p, _ in template_changes]:
            backup = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup)
            backups.append((path, backup))

        # Write all changes
        save_yaml(REGISTRY_PATH, new_registry)
        print(f"  Updated {REGISTRY_PATH.relative_to(BASE_DIR)}")

        save_yaml(COMPAT_PATH, new_compat)
        print(f"  Updated {COMPAT_PATH.relative_to(BASE_DIR)}")

        for ver, path, new_text in template_changes:
            write_text(path, new_text)
            print(f"  Updated {path.relative_to(BASE_DIR)}")

        # Remove backups on success
        for _, backup in backups:
            backup.unlink(missing_ok=True)

    except Exception as e:
        err(f"Failed to write: {e}")
        err("Restoring from backups...")
        for path, backup in backups:
            if backup.exists():
                shutil.copy2(backup, path)
                backup.unlink()
        return 1

    print(f"\nFeature '{feature_id}' added successfully!")
    print(f"\nVerify with: ./run-test-suite.py --list-features | grep {feature_id}")
    print(f"Test with:   ./run-test-suite.py 20-rosa-hcp-provision --feature {alias} --dry-run -e name_prefix=test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
