# Validation: commands to run before declaring done

Run these in order; each catches a different class of mistake. None provisions a
cluster or costs AWS money.

```bash
# 1. Registry parses, feature visible with the right metadata, group/scenario
#    descriptions updated
./run-test-suite.py --list-features
./run-test-suite.py --list-groups
./run-test-suite.py --list-scenarios

# 2. Flag resolution, dependency resolution, version gating, required inputs
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature --validate-only

# 3. Rejected below min_version. Check the EXIT CODE, not the message —
#    piping to tail masks it.
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature \
  -e openshift_version=4.21 --validate-only >/dev/null 2>&1; echo "exit=$?"   # expect 1

# 4. If it joined a scenario: resolves, and emits the var the template reads
./run-test-suite.py --scenario day1-combo -e openshift_version=4.22 --validate-only

# 5. Every layer this skill describes, for your feature specifically: registry,
#    version gate, the templates, crd_field_map, the CHECK guard, the verification
#    task, the boto3 declaration, the docs page, both README tables, and the extra
#    vars the CLI actually resolves. Exits non-zero on the first disagreement.
make verify-skills FEATURE=my_feature

#    ...and the same across every --feature, which is what CI gates on
#    (tests/test_skills_md.py). Run it if you touched a shared file.
make verify-skills-all

# 6. The whole unit suite — same paths CI runs. Compare against the baseline you
#    recorded in intake.md §1.7: equal pass count plus your new tests, and NO new
#    failures.
python3 -m pytest tests agents scripts -q

# 7. Lint, matching the CI jobs in .github/workflows/ci.yml
ansible-playbook --syntax-check playbooks/verify_feature_flags.yml
ansible-lint playbooks/
yamllint -f parsable --no-warnings playbooks/ tasks/
black --check *.py        # only if you touched a top-level .py
pylint *.py --disable=C,R

# 8. Everything the pre-commit hooks check
pre-commit run --all-files
```

CI gates on all of these plus a Trivy/TruffleHog scan and a `--list`/`--help`
dry run; the `all-checks-passed` job fails if any of them does.

---

## Prove the logic no unit test reaches

The pytest suite covers the registry and the templates. It does **not** cover the
Jinja inside your verification task — and that is where subtle bugs hide. Exercise
the assertions against mock data with a throwaway playbook:

```yaml
# /tmp/check/t.yml — delete afterwards
- hosts: localhost
  gather_facts: false
  vars:
    fixture_present: {items: [{aws_node_pool: {my_field: {k: "v"}}}]}
    fixture_absent:  {items: [{aws_node_pool: {}}]}
    fixture_empty:   {}
  tasks:
    - ansible.builtin.debug:
        msg: "{{ item.label }}: found={{ p | selectattr('aws_node_pool.my_field', 'defined') | list | length > 0 }}"
      vars:
        p: "{{ (item.json | default({})).get('items', []) }}"
      loop:
        - {label: present, json: "{{ fixture_present }}"}
        - {label: absent,  json: "{{ fixture_absent }}"}
        - {label: empty,   json: "{{ fixture_empty }}"}
```

A check that cannot distinguish *present* from *absent* is worse than no check. Run
the negative fixture and confirm it reports `false`.

---

## Only a real provision proves it end to end

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature -e name_prefix=qe6
./run-test-suite.py 21-verify-feature-flags --feature my-feature -e cluster_name=qe6-rosa-hcp
jq '.features[] | select(.id=="my_feature")' test-results/feature-verification.json
./run-test-suite.py 30-rosa-hcp-delete -e cluster_name=qe6-rosa-hcp
```

**Never run a provision without being asked.** It takes ~40 minutes and spends real
AWS money. Report that the dry validation passed and let the user decide.
