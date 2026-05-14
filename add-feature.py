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
    --type boolean \\
    --default false \\
    --k8s-field ".spec.myField" \\
    --resource ROSAControlPlane \\
    --suite cluster-config \\
    --min-version 4.20 \\
    --depends-on other_feature \\
    --template-block 'myField: {{ my_ansible_var }}'

  ./add-feature.py --list-suites    # Show available suite IDs
  ./add-feature.py --dry-run ...    # Show changes without applying
"""

import argparse
import re
import sys
from pathlib import Path

import yaml


BASE_DIR = Path(__file__).parent
REGISTRY_PATH = BASE_DIR / "templates" / "schemas" / "feature-registry.yml"
COMPAT_PATH = BASE_DIR / "templates" / "schemas" / "version-compatibility.yml"
TEMPLATE_DIR = BASE_DIR / "templates" / "versions"
TEMPLATE_NAME = "rosa-controlplane-only.yaml.j2"


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def save_yaml_preserving_comments(path, original_text, data):
    """Write YAML back, preserving comments by doing targeted insertions."""
    with open(path, "w") as f:
        f.write(original_text)


def read_text(path):
    with open(path) as f:
        return f.read()


def write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


def list_suites(registry):
    print("\nAvailable suites:\n")
    for suite in registry.get("suites", []):
        print(f"  {suite['id']:25s} {suite['name']} ({suite.get('phase', 'Day1')})")
    print()


def insert_after_last_match(text, pattern, insertion):
    """Insert text after the last line matching pattern."""
    lines = text.split("\n")
    last_idx = -1
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            last_idx = i
    if last_idx == -1:
        return text
    lines.insert(last_idx + 1, insertion)
    return "\n".join(lines)


def insert_before_pattern(text, pattern, insertion):
    """Insert text before the first line matching pattern."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            lines.insert(i, insertion)
            return "\n".join(lines)
    return text


def add_to_registry(registry_text, feature_id, alias, var_name, suite_id, feature_def):
    """Add var_map, cli_alias, cli_feature, and suite entry to the registry."""
    # 1. Add var_map entry
    registry_text = insert_after_last_match(
        registry_text,
        r"^  \w+: \w+",  # last var_map entry
        f"  {feature_id}: {var_name}"
    )

    # 2. Add cli_alias
    if alias:
        registry_text = insert_after_last_match(
            registry_text,
            r"^  [\w-]+: \w+",  # last alias entry (after var_map section)
            f"  {alias}: {feature_id}"
        )

    # 3. Add to cli_features
    registry_text = insert_after_last_match(
        registry_text,
        r"^  - \w+$",  # last cli_feature entry
        f"  - {feature_id}"
    )

    # 4. Add feature definition to the appropriate suite
    feature_yaml = yaml.dump([feature_def], default_flow_style=False, sort_keys=False)
    # Indent for suite features list
    indented = "\n".join("      " + line if line.strip() else "" for line in feature_yaml.split("\n"))
    # Find the suite and add before the next suite or end
    suite_pattern = rf"  - id: {re.escape(suite_id)}"
    lines = registry_text.split("\n")
    in_target_suite = False
    last_feature_line = -1
    for i, line in enumerate(lines):
        if re.search(suite_pattern, line):
            in_target_suite = True
        elif in_target_suite and re.match(r"  - id: ", line):
            break
        if in_target_suite and re.match(r"      - id: ", line):
            last_feature_line = i

    if last_feature_line > 0:
        # Find the end of the last feature in this suite
        end_idx = last_feature_line + 1
        while end_idx < len(lines) and lines[end_idx].startswith("        "):
            end_idx += 1
        # Insert the new feature
        new_feature_lines = [
            "",
            f"      - id: {feature_id}",
            f"        name: {feature_def['name']}",
            f"        description: \"{feature_def['description']}\"",
            f"        type: {feature_def['type']}",
            f"        mutable: {str(feature_def.get('mutable', False)).lower()}",
            f"        applies_to: [{', '.join(feature_def.get('applies_to', ['create']))}]",
            f"        default: {feature_def.get('default', 'false')}",
            f"        k8s_field: \"{feature_def['k8s_field']}\"",
            f"        resource: {feature_def['resource']}",
        ]
        if feature_def.get("min_version"):
            new_feature_lines.append(f"        min_version: \"{feature_def['min_version']}\"")
        for idx, fl in enumerate(new_feature_lines):
            lines.insert(end_idx + idx, fl)
        registry_text = "\n".join(lines)

    return registry_text


def add_to_version_compat(compat_text, feature_id, min_version):
    """Add feature_availability entry."""
    entry = f"  {feature_id}:\n    min_version: \"{min_version}\"\n    max_version: null"
    return insert_after_last_match(
        compat_text,
        r"^\s+max_version:",
        entry
    )


def add_to_templates(feature_id, var_name, feat_type, template_block, min_version, dry_run):
    """Add conditional block to rosa-controlplane-only templates."""
    if not template_block:
        if feat_type == "boolean":
            template_block = f"  {var_name}: true"
        else:
            template_block = f"  {var_name}: {{{{ {var_name} }}}}"

    # Build the Jinja2 conditional
    if feat_type == "boolean":
        conditional = f"{{% if {var_name} is defined and {var_name} | bool %}}\n{template_block}\n{{% endif %}}"
    else:
        conditional = f"{{% if {var_name} is defined and {var_name} %}}\n{template_block}\n{{% endif %}}"

    min_minor = min_version.replace("4.", "") if min_version else "18"
    versions_to_update = []
    for ver_dir in sorted(TEMPLATE_DIR.iterdir()):
        if not ver_dir.is_dir():
            continue
        ver = ver_dir.name
        try:
            ver_minor = int(ver.replace("4.", ""))
        except ValueError:
            continue
        if ver_minor >= int(min_minor):
            template_path = ver_dir / "features" / TEMPLATE_NAME
            if template_path.exists():
                versions_to_update.append((ver, template_path))

    changes = []
    for ver, template_path in versions_to_update:
        text = read_text(template_path)
        # Insert before the log forwarding section or before the MachinePool section
        marker = "{% if log_forward_enabled"
        if marker not in text:
            marker = "---\napiVersion: cluster.x-k8s.io"

        if marker in text:
            new_text = text.replace(marker, f"{conditional}\n\n{marker}")
            changes.append((ver, template_path, new_text))

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="Add a new feature to the ROSA HCP feature registry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("feature_id", nargs="?", help="Feature ID (e.g., my_feature)")
    parser.add_argument("--alias", help="CLI alias (e.g., my-feature)")
    parser.add_argument("--name", help="Display name (e.g., 'My Feature')")
    parser.add_argument("--description", help="Short description")
    parser.add_argument("--var", help="Ansible extra var name")
    parser.add_argument("--type", default="boolean", choices=["boolean", "string", "number", "select", "list", "key_value", "range"],
                        help="Feature type (default: boolean)")
    parser.add_argument("--default", default="false", help="Default value (default: false)")
    parser.add_argument("--k8s-field", help="K8s spec field (e.g., .spec.myField)")
    parser.add_argument("--resource", default="ROSAControlPlane", help="K8s resource (default: ROSAControlPlane)")
    parser.add_argument("--suite", default="cluster-config", help="Suite to add feature to (default: cluster-config)")
    parser.add_argument("--min-version", default="4.19", help="Minimum OpenShift version (default: 4.19)")
    parser.add_argument("--depends-on", help="Feature ID this depends on")
    parser.add_argument("--template-block", help="Jinja2 YAML block to insert in template (indented, no conditionals)")
    parser.add_argument("--mutable", action="store_true", help="Feature can be changed after creation")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--list-suites", action="store_true", help="List available suite IDs")

    args = parser.parse_args()

    registry = load_yaml(REGISTRY_PATH)

    if args.list_suites:
        list_suites(registry)
        return 0

    if not args.feature_id:
        parser.print_help()
        return 1

    # Validate required args
    if not all([args.name, args.description, args.var, args.k8s_field]):
        print("Error: --name, --description, --var, and --k8s-field are required")
        return 1

    feature_id = args.feature_id
    alias = args.alias or feature_id.replace("_", "-")
    var_name = args.var

    # Check for duplicates
    if feature_id in registry.get("var_map", {}):
        print(f"Error: feature '{feature_id}' already exists in var_map")
        return 1

    # Validate suite exists
    suite_ids = [s["id"] for s in registry.get("suites", [])]
    if args.suite not in suite_ids:
        print(f"Error: suite '{args.suite}' not found. Use --list-suites to see options.")
        return 1

    feature_def = {
        "id": feature_id,
        "name": args.name,
        "description": args.description,
        "type": args.type,
        "mutable": args.mutable,
        "applies_to": ["create", "apply"] if args.mutable else ["create"],
        "default": args.default,
        "k8s_field": args.k8s_field,
        "resource": args.resource,
    }
    if args.min_version != "4.18":
        feature_def["min_version"] = args.min_version

    # Read current file contents
    registry_text = read_text(REGISTRY_PATH)
    compat_text = read_text(COMPAT_PATH)

    # Apply changes
    new_registry = add_to_registry(registry_text, feature_id, alias, var_name, args.suite, feature_def)
    new_compat = add_to_version_compat(compat_text, feature_id, args.min_version)
    template_changes = add_to_templates(feature_id, var_name, args.type, args.template_block, args.min_version, args.dry_run)

    # Handle dependencies
    if args.depends_on:
        dep_line = f"  {feature_id}:\n    - {args.depends_on}"
        new_registry = insert_after_last_match(
            new_registry,
            r"^\s+- \w+$",  # last dependency entry
            dep_line
        )

    # Show changes
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
    for ver, path, _ in template_changes:
        print(f"  3. {path.relative_to(BASE_DIR)}")
        print(f"     - conditional block for {var_name}")
    print()

    if args.dry_run:
        print("No changes made (dry-run mode)")
        return 0

    # Write changes
    write_text(REGISTRY_PATH, new_registry)
    print(f"  Updated {REGISTRY_PATH.relative_to(BASE_DIR)}")

    write_text(COMPAT_PATH, new_compat)
    print(f"  Updated {COMPAT_PATH.relative_to(BASE_DIR)}")

    for ver, path, new_text in template_changes:
        write_text(path, new_text)
        print(f"  Updated {path.relative_to(BASE_DIR)}")

    print(f"\nFeature '{feature_id}' added successfully!")
    print(f"\nVerify with: ./run-test-suite.py --list-features | grep {feature_id}")
    print(f"Test with:   ./run-test-suite.py 20-rosa-hcp-provision --feature {alias} --dry-run -e name_prefix=test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
