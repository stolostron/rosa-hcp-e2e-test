---
name: add-feature-test
description: Add a ROSA HCP feature test to this repository end to end — registry entry, version gate, template conditionals, crd_field_map, verification task, docs and unit tests. Use whenever the user asks to add, wire up, or test a new `--feature`, asks to cover a new ROSA/CAPA CRD field or upstream PR, or asks which files a feature test has to touch. Also use when auditing an existing feature for missing layers.
---

# Adding a New Feature Test

A procedure for adding a ROSA HCP feature test to this repository, written so that
an **AI agent** can execute it end to end from a single upstream PR link, and the
**end user** only has to confirm or correct what the agent derived.

The repo registers 28 features (`templates/schemas/feature-registry.yml`), 18 of
which are reachable from `--feature` (`cli_features`), with 19 pages under
`docs/features/` (18 features plus `automated-feature-verification.md`) and 19
`verify_*.yml` tasks under `tasks/features/` (plus the shared
`setup_feature_verification.yml` and `report_feature_verification.yml`). They all
follow the same shape. This skill describes that shape, names every file that must
change, and points at copy-paste skeletons for each one.

**Read these when you reach them — not up front:**

| File | What it holds | Read it at |
|---|---|---|
| `references/intake.md` | Step 0 source-reading recipes, and the intake form that is the contract | **Before writing anything** |
| `references/skeletons.md` | Copy-paste blocks for the registry, templates, verification task, feature doc | Steps 1, 3, 6, 9 |
| `references/validation.md` | Every command to run before declaring done | Step 10 onward |
| `references/gotchas.md` | The rules that produce silently-passing tests when broken | Before Step 6, and when a check misbehaves |
| `references/variants.md` | Features that do not fit this shape, and reference implementations | Step 3, or whenever the standard shape does not fit |

---

## 1. The flow

**A PR is not required.** Most features already in this repo had none — they were
tested because the field already existed in the shipped CRD. What the procedure
needs is a *filled intake form* (`references/intake.md`); a PR is simply the richest
source to fill it from, not the only one.

Either direction works:

```
  (A) AGENT-DRAFTED — the default. Start here whenever any source exists.

  END USER     "Add a feature test for <X>."  + any one of:
                 • an upstream PR or issue link       → richest
                 • a CRD field name, if it already ships → just as authoritative
                 • a doc link, Jira/RHACM4K ticket, or a plain description
      │
      ▼
  AGENT        Step 0: read whatever source exists. Extract the CRD resource,
               exact field path and type, validation pattern, immutability rules,
               OCM field, upstream docs.
      │
      ▼
  AGENT        Draft the intake form with every derivable field filled in and
               its source cited. Flag what could not be derived.
      │
      ▼
  AGENT        Ask ONLY the decisions in the "Cannot be derived" block — typically
               2 questions. Present the drafted form for confirmation at the same time.
      │
      ▼
  END USER     Confirm, or correct any line. This is the only required input.
      │
      ▼
  AGENT        Implement §3, validate, report against the Definition of Done.


  (B) USER-FILLED — when you already know the answers, or there is nothing to read.

  END USER     Fill the form yourself and hand it over. Skip Step 0 entirely.
      │
      ▼
  AGENT        Verify the few facts that are cheap to check against the live CRD —
               resource, field path, type. Flag any disagreement rather than
               silently following either version. Then implement.
```

**Why (A) is the default.** A recollection of an API is not a spec. Reading the
source costs the agent two minutes and removes a whole class of silent failure,
where a test passes against a cluster on which the feature was never applied.
**Derive from the source; ask the user to confirm.**

**Why (B) is still fine.** The form is the contract, not the PR. A user who knows
the field, the resource and the assertions has supplied everything §3 consumes. The
agent should still spot-check the field path against the live CRD — that is one
command, and it is the exact thing memory gets wrong.

> **Do not write a single line until the intake form is filled and confirmed.**
> Open `references/intake.md` now: it holds the source-reading commands (Step 0) and
> the form itself. Three lines are required however it is filled — **feature ID**,
> **CRD resource**, **CRD field path** — because guessing a field path yields a test
> that passes against a cluster where the feature was never applied.

---

## 2. Architecture: what a "feature test" is made of

A feature flows through four layers. A complete feature test touches all four.

```
  USER INPUT                 ./run-test-suite.py 20-rosa-hcp-provision --feature my-feature -e foo=bar
      │
      ▼
  ① REGISTRY                 templates/schemas/feature-registry.yml
     resolve alias →         cli_aliases:  my-feature → my_feature
     validate version →      version-compatibility.yml: feature_availability.my_feature.min_version
     resolve deps →          dependencies: my_feature → [other_feature]
     check inputs →          requires_input / required_vars / required_vars_any_of
     emit extra_vars →       var_map: my_feature → my_ansible_var  (+ requested_features=my_feature,...)
      │                      (feature_manager.py does all of this)
      ▼
  ② TEMPLATE                 templates/versions/<ver>/features/rosa-controlplane-only.yaml.j2
     render manifest →       {% if my_ansible_var is defined and my_ansible_var | bool %}
                               myCrdField: ...
                             {% endif %}
                             …and the same block in rosa-combined-automation.yaml.j2
      │
      ▼
  ③ PROVISION                playbooks/create_rosa_hcp_cluster.yml  (suite 20) — applies the manifest
      │                      No change needed unless the feature needs an AWS resource created first.
      ▼
  ④ VERIFY                   playbooks/verify_feature_flags.yml     (suite 21)
     crd_field_map entry →   my_feature: {crd: rosacontrolplanes…, field: myCrdField}
     CHECK include →         when: "'my_feature' in requested_features_list"
     the check itself →      tasks/features/verify_my_feature.yml   (block / rescue)
     result →                tasks/features/report_feature_verification.yml
                             → test-results/feature-verification.json → one JUnit case per feature
```

Key invariant: **a feature that was not requested means SKIP, never FAIL.** Every
check is guarded by `when: "'<id>' in requested_features_list"`, and
`requested_features` is produced by `FeatureManager.resolve_to_extra_vars()`
(`grep -n 'def resolve_to_extra_vars' feature_manager.py`) from the `--feature` flags.

---

## 3. The 10 steps

Throughout, replace `my_feature` / `my-feature` / `myCrdField` / `my_ansible_var`
with the confirmed values from the intake form.

### Step 1 — Register the feature

`templates/schemas/feature-registry.yml`, four edits:

1. **`var_map`** — feature ID → the Ansible variable the template reads.
   `resolve_to_extra_vars()` falls back to the feature ID when there is no entry, so
   you may skip this only if the ID and the variable name are identical. When you do
   skip it, leave a comment saying why — the file already does this for
   `instance_type` and `break_glass_credentials`.
2. **`cli_aliases`** — short kebab-case name users type. Optional when the ID is
   already short and has no underscores: `fips` ships with no alias and is typed as
   `--feature fips`. Add one whenever the ID is long or snake_case.
3. **`cli_features`** — add the ID if it is a Day-1 creation feature settable through
   a flat extra var. If it is not, leave it out **and add a comment under
   "Excluded from CLI (with reason)" saying why** — that comment block is load-bearing
   documentation, `validate_features()` rejects anything not in `cli_features`.
4. **`suites[].features[]`** — the feature definition itself, in the confirmed suite.
   See the registry skeleton in `references/skeletons.md`.

`category:` and `phase:` are **suite-level** keys, not per-feature ones — a feature
inherits them from the suite it is filed under. Pick the suite accordingly rather
than adding those keys to the feature entry.

Optionally also: `dependencies`, `mutual_exclusions`, `feature_groups`, `scenarios`.
If the feature joins a group, **update that group's and scenario's `description:`**
too — `--list-scenarios` and `--list-groups` print it, and a stale description is a
silent lie.

### Step 2 — Declare version availability

`templates/schemas/version-compatibility.yml` → `feature_availability:`

```yaml
  my_feature:
    min_version: "4.22"
    max_version: null
```

This is the copy that matters: both `validate_features()` and `list_features()` read
`feature_availability` first, and only fall back to the registry entry's own
`min_version:` when there is no compatibility entry
(`grep -n 'avail.get("min_version") or feat.get' feature_manager.py`). Only four
registry entries carry a redundant `min_version:` today (`external_oidc`,
`break_glass_credentials`, `fips`, `no_cni`). If you add one, **keep the two
identical and add a test asserting they match** — nothing else enforces it, and a
disagreeing registry copy is invisible until someone deletes the compatibility entry.

An entry here is not strictly mandatory, and 10 of the 28 registered features have
none. For `action` and `version` types that drive their own lifecycle suites
(`cluster_delete`, `control_plane_upgrade`, `machine_pool_upgrade`) and for Day-2
entries configured through suite `extra_vars` rather than `--feature` (`node_taints`,
`node_labels`, `instance_type`, `machine_pool_autoscaling`), ungated is a reasonable
default — nothing resolves them through the version gate. For a Day-1 `--feature`
flag it is almost always an oversight: `default_autoscaling` and `sts` are gated
nowhere and `--list-features` reports no floor for them. **Add the entry unless your
feature is one of those lifecycle or Day-2 shapes.**

Supported versions are `4.18`–`4.22` and `5.0`; `default_version` is `4.22`.

### Step 3 — Render it in the templates

> If the feature lives on **ROSANetwork**, is consumed by the provisioning playbook
> with no template conditional, or has its own verification playbook, this step is
> different — read `references/variants.md` before editing anything.

The seam is two templates per version directory:

- `templates/versions/<ver>/features/rosa-controlplane-only.yaml.j2`
- `templates/versions/<ver>/features/rosa-combined-automation.yaml.j2`

They exist for **4.20, 4.21, 4.22 and 5.0 only**. The `4.18` and `4.19` feature
directories hold older static fixtures (`rcp-*.yaml`, `rosa-network-test.yaml`) and
are not part of this seam — do not add a conditional there.

**Not every version directory is wired, and you should not wire the stale ones on
your way past.** Only 4.22 and 5.0 carry the full set of feature conditionals; 4.21
has them in `rosa-controlplane-only` but not in `rosa-combined-automation`, and 4.20
has almost none. The render tests parametrize over exactly that reality:

| Version | `rosa-controlplane-only` | `rosa-combined-automation` |
|---|---|---|
| 4.22 / 5.0 | fully wired — **edit here** | fully wired — **edit here** |
| 4.21 | partially wired | not wired |
| 4.20 | barely wired | not wired |

So the default is: **edit `4.22`, copy to `5.0`, stop.**

**The version gate and the templates must agree, and nothing enforces that for you.**
`min_version` controls which versions `validate_features()` *accepts*; the templates
control which versions actually *render* the field. Set `min_version: "4.20"` without
wiring 4.20 and the CLI cheerfully accepts `-e openshift_version=4.20`, the manifest
comes out without your field, and the feature silently does nothing — the exact
failure this seam exists to prevent, arriving 40 minutes later as a verification
WARN. So:

> **`min_version` must not be lower than the oldest version you wired.** Either wire
> every version the gate admits, or raise `min_version` to the oldest wired one.
> With the default edit-4.22-and-stop path that means `min_version: "4.22"`.

Touch `4.21`/`4.20` only if the feature genuinely has to run there — and if you do,
wire **both** templates for those versions and add the matching
`(version, template_name)` pairs to your render test, because nothing else will
cover them.

Both templates are multi-document: `ManagedCluster`, `Cluster`, `ROSACluster`,
`ROSAControlPlane`, `MachinePool`, `ROSAMachinePool`, in that order. A machine-pool
field belongs in the **last** document, not in the `ROSAControlPlane` one.

> **5.0 shares 4.22's templates byte for byte.**
> `tests/test_feature_manager.py::TestVersionTemplateParity::test_50_templates_match_422`
> compares the directories with `filecmp`, and allows exactly two 5.0-only files
> (`rosa-private-cluster.yaml.j2`, `rosa-no-cni-cluster.yaml.j2`, used by suites 22
> and 23) listed in its `VERSION_SPECIFIC` set. After editing `4.22`, copy the file
> to `5.0` (`cp templates/versions/4.22/features/X.j2 templates/versions/5.0/features/X.j2`).

Place the block where it belongs structurally in the `spec:` (tags near tags,
network near network, machine-pool fields on the `ROSAMachinePool` document) and
guard it so an unrequested feature renders *nothing*. See the template skeletons in
`references/skeletons.md`.

**Emit sub-fields explicitly rather than relying on CRD defaulting.** If the template
writes `{}` and lets the API server fill in a default, the value verification compares
against is one nobody in this repo chose, and a change to the upstream default breaks
the test silently.

### Step 4 — Map the CRD field for verification

`playbooks/verify_feature_flags.yml` → `vars.crd_field_map`
(`grep -n 'crd_field_map:' playbooks/verify_feature_flags.yml`; 18 entries today):

```yaml
      my_feature: {crd: "rosacontrolplanes.controlplane.cluster.x-k8s.io", field: "myCrdField"}
```

CRD names in use:

| Resource | CRD name |
|---|---|
| ROSAControlPlane | `rosacontrolplanes.controlplane.cluster.x-k8s.io` |
| ROSAMachinePool  | `rosamachinepools.infrastructure.cluster.x-k8s.io` |
| ROSANetwork      | `rosanetworks.infrastructure.cluster.x-k8s.io` |

Use a dotted path (`network.networkType`) when the field is nested; the rescue path
splits on `.` and schema-checks only the first segment.

This map does double duty: the rescue path uses it to distinguish "CRD does not
support this field yet" (**WARN**, platform limitation) from "CRD supports it but the
value is missing" (**FAIL**, real bug), and `setup_feature_verification.yml` derives
the list of valid `--feature` values for verification from its keys plus
`long_cluster_name`. **A feature absent from this map is rejected as unknown by
suite 21** — unless it is listed in `externally_verified_features`
(see `references/variants.md`).

### Step 5 — Add the CHECK block

`playbooks/verify_feature_flags.yml`, in the `FEATURE CHECKS` section, in rough
registry order:

```yaml
    - name: "CHECK: My Feature"
      ansible.builtin.include_tasks: "{{ playbook_dir }}/../tasks/features/verify_my_feature.yml"
      when: "'my_feature' in requested_features_list"
```

### Step 6 — Write the verification task

New file `tasks/features/verify_my_feature.yml`, following the skeleton in
`references/skeletons.md`. **Read `references/gotchas.md` first** — the two Jinja
traps it documents both produce checks that pass on a cluster where the feature was
never configured, and no unit test reaches them.

`setup_feature_verification.yml` has already set the facts you can rely on: `rcp`,
`rmp` (and `rmp_named`), `rnet`, `ocm_cluster`, `ocm_available`, `ocm_api_url`,
`ocm_token_result`, `boto3_check`, `requested_features_list`. Non-negotiable parts:

- a single top-level `block:` / `rescue:` pair;
- for a **ROSAControlPlane** feature: OCM assertion guarded by `when: ocm_available`,
  CRD assertion guarded by `when: not ocm_available` (CRD is the *fallback*);
- for a **ROSAMachinePool** feature: CRD assertion unconditional against `rmp`, plus
  an OCM cross-check via `GET /clusters/{id}/node_pools` — the cluster object OCM
  returns for `?search=` does not carry node-pool fields. See `verify_disk_size.yml`;
- every assert has both `fail_msg: "FAIL: …"` and `success_msg: "PASS: …"`;
- last task of the block increments `features_passed`;
- `rescue:` includes `tasks/verify_feature_rescue.yml` with `feature_id` and
  `fail_detail` — never hand-roll the fail/warn accounting.

If the feature declares a validation pattern, **assert the requested input against it
as the first task in the block**. Be clear about what that does and does not buy you:
this task runs in suite 21, *after* suite 20 has already provisioned, so it cannot
save you the 40 minutes. What it does is fail on the first line with
`'<value>' is not a valid value` instead of further down with a confusing "field not
found on the CRD", which is otherwise indistinguishable from a platform limitation.

Nothing checks the value *before* provisioning: `validate_features()` and
`--validate-only` check the feature name, its dependencies and the version gate, not
the shape of `-e` values, and the registry does not record the CRD's pattern. If you
want a typo caught in one second rather than forty minutes, that check has to go in
the CLI validation path, and the pattern has to come from the CRD schema.

### Step 7 — Declare AWS dependence (only if the check uses boto3)

`tasks/features/report_feature_verification.yml` → task *"Find features whose AWS
side could not be verified"* → add the ID to `aws_dependent_features`
(`grep -n 'aws_dependent_features:' tasks/features/report_feature_verification.yml`;
`[audit_logging, etcd_kms, byon, private_network, fips]` today). Without this, a run
on a machine with no boto3 reports a clean PASS while never having looked at AWS, and
`environment.degraded` in the artifact stays false.

`make verify-skills FEATURE=<id>` checks this both ways — a task that mentions boto3
but is not declared, and a declared feature whose task never calls boto3, both fail.
`fips` was found by exactly that check.

### Step 8 — Extend setup only if a new resource is needed

`tasks/features/setup_feature_verification.yml` already logs in, validates
`cluster_name`, parses `requested_features_list`, and fetches `rcp`
(ROSAControlPlane), `rmp` (the cluster's ROSAMachinePool, selected by exact name
match), `rnet` (ROSANetwork), an OCM bearer token + `ocm_cluster`, and checks for
boto3. Add a lookup here only if your feature lives on a resource none of those
cover — and fail loudly rather than guessing when the resource is ambiguous (see how
`rmp_named` refuses to verify an arbitrary machine pool).

### Step 9 — Document it

- New file `docs/features/<feature-name>.md` from the skeleton in
  `references/skeletons.md`, using the confirmed Description and Verification text
  from the intake form. Link the upstream PR and the upstream book page.
- Add the feature to **both** README tables, alphabetically within each:
  - the CLI flag table under `### Available Features`;
  - the docs table under `## Feature Documentation`.

### Step 10 — Extend the tests

In `tests/test_feature_manager.py`, add a `TestMyFeature` class. The existing
`TestNoCNI`, `TestExternalOIDC`, `TestPrivateClusterSubnets`, `TestBYON` and
`TestBreakGlassCredentials` classes are the models. Cover:

- **the registry↔template seam** — render both templates, on every applicable
  version, and assert the field reaches the manifest with the right value *and the
  right type*. This catches a `var_map` name that disagrees with the template
  variable, the single most common bug in this seam;
- **absent when not requested** — renders nothing, not an empty block;
- **the version gate** — rejected one version below `min_version`, accepted at it;
- **registry and compatibility agree** on `min_version` (only if you added the
  redundant registry copy — see Step 2);
- **required inputs** — warning when missing, silence when satisfied;
- **the verification task file exists** at the path the playbook includes, and the
  feature is in `crd_field_map`. **Nothing in the pytest suite asserts either today** —
  both are string references that fail only at runtime, so this is the highest-value
  test you can add. (`make verify-skills FEATURE=my_feature` checks both for one
  feature; a unit test keeps it checked for everyone.)

If the feature joined a scenario, also add it to `SCENARIO_RENDER_EXPECTATIONS`
(`grep -n 'SCENARIO_RENDER_EXPECTATIONS' tests/test_feature_manager.py`), and
**update any existing test that asserts that group's size or version list** — those
changes are deliberate, so say why in the docstring rather than just editing a number.

---

## 4. Validate, then report

Run everything in `references/validation.md` before declaring done. The fastest
single check that your feature matches every layer described above is:

```bash
make verify-skills FEATURE=my_feature   # your feature
make verify-skills-all                  # every --feature, which is what CI gates on
```

`tests/test_skills_md.py` runs the same checks in CI, one test per feature. If your
feature is a documented variant (`references/variants.md`) the checker says so rather
than failing: an externally-verified feature skips Steps 4–6, a ROSANetwork feature
is checked against `rosa-network-config.yaml.j2`, and a variable consumed by a
playbook instead of a template is a **warn** naming the file that reads it. A
variable found in *no* file is still a failure — that is the feature-renders-nothing
bug this whole seam exists to catch.

**Never run a provision without being asked.** It takes ~40 minutes and spends real
AWS money. Report that the dry validation passed and let the user decide.

---

## 5. Definition of done

- [ ] Intake form complete — either drafted by the agent with every line sourced and **confirmed by the end user**, or supplied by the end user with the CRD resource and field path spot-checked against the live CRD
- [ ] Registry entry added under the right suite, with accurate `k8s_field`, `resource`, `type`, `default`
- [ ] `var_map`, `cli_aliases`, `cli_features` updated (or an explicit comment saying why not in `cli_features` / `var_map`)
- [ ] `dependencies` / `required_vars` / `required_vars_any_of` / `mutual_exclusions` declared if applicable
- [ ] `feature_availability` entry in `version-compatibility.yml`; any registry `min_version:` copy matches it
- [ ] Group and scenario `description:` updated if the feature joined one
- [ ] Template conditional in `rosa-controlplane-only.yaml.j2` **and** `rosa-combined-automation.yaml.j2` for `4.22` (and any older version dir you deliberately wired — see Step 3)
- [ ] `5.0` templates byte-identical to `4.22`
- [ ] `crd_field_map` entry and `CHECK:` include added, guarded by `requested_features_list`
- [ ] `tasks/features/verify_<id>.yml` written with block/rescue, input pre-check, CRD + OCM layers, PASS/FAIL messages, `features_passed` increment
- [ ] Added to `aws_dependent_features` if it uses boto3
- [ ] `docs/features/<feature>.md` written, linking the upstream PR; rows added to **both** README tables
- [ ] Tests added: render seam, absent-when-unrequested, version gate, min_version agreement, task-file existence, `crd_field_map` membership
- [ ] Existing tests that this deliberately changes are updated **with a docstring saying why**
- [ ] All `references/validation.md` commands pass; pytest shows no new failures against the baseline
- [ ] `make verify-skills FEATURE=<id>` passes, and the feature is **not** added to `KNOWN_GAPS` in `tests/test_skills_md.py` to make it pass
- [ ] Verification Jinja exercised against present / absent / empty fixtures
- [ ] Report states: what was derived vs assumed, pre-existing failures, side effects, and what was left out
