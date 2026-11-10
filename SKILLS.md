# SKILLS.md — Adding a New Feature Test

A procedure for adding a ROSA HCP feature test to this repository, written so that
an **AI agent** can execute it end to end from a single upstream PR link, and the
**end user** only has to confirm or correct what the agent derived.

The repo contains ~20 feature tests (`docs/features/`). They all follow the same
shape. This document describes that shape, names every file that must change, and
gives copy-paste skeletons for each one.

**Contents**

1. [The flow](#1-the-flow)
2. [Step 0: fill the intake form from whatever source exists](#2-step-0-fill-the-intake-form-from-whatever-source-exists) — *agent; skip if the user filled the form*
3. [Feature intake form](#3-feature-intake-form) — *agent drafts and user confirms, or user fills directly*
4. [Architecture: what a "feature test" is made of](#4-architecture-what-a-feature-test-is-made-of)
5. [Agent procedure: the 10 steps](#5-agent-procedure-the-10-steps)
6. [Copy-paste skeletons](#6-copy-paste-skeletons)
7. [Validation: commands to run before declaring done](#7-validation-commands-to-run-before-declaring-done)
8. [Rules and gotchas](#8-rules-and-gotchas)
9. [Definition of done](#9-definition-of-done)
10. [Variants: features that do not fit the standard shape](#10-variants-features-that-do-not-fit-the-standard-shape)
11. [Worked example: spot instances](#11-worked-example-spot-instances)

---

## 1. The flow

**A PR is not required.** Most features already in this repo had none — they were
tested because the field already existed in the shipped CRD. What the procedure
needs is a *filled intake form* (§3); a PR is simply the richest source to fill it
from, not the only one.

Either direction works:

```
  (A) AGENT-DRAFTED — the default. Start here whenever any source exists.

  END USER     "Add a feature test for <X>."  + any one of:
                 • an upstream PR or issue link       → richest
                 • a CRD field name, if it already ships → §2.3, just as authoritative
                 • a doc link, Jira/RHACM4K ticket, or a plain description
      │
      ▼
  AGENT        Step 0 (§2): read whatever source exists. Extract the CRD resource,
               exact field path and type, validation pattern, immutability rules,
               OCM field, upstream docs.
      │
      ▼
  AGENT        Draft the intake form (§3) with every derivable field filled in and
               its source cited. Flag what could not be derived.
      │
      ▼
  AGENT        Ask ONLY the decisions in §3's "Cannot be derived" block — typically
               2 questions. Present the drafted form for confirmation at the same time.
      │
      ▼
  END USER     Confirm, or correct any line. This is the only required input.
      │
      ▼
  AGENT        Implement §5, validate §7, report against §9.


  (B) USER-FILLED — when you already know the answers, or there is nothing to read.

  END USER     Fill the §3 form yourself and hand it over. Skip Step 0 entirely.
      │
      ▼
  AGENT        Verify the few facts that are cheap to check against the live CRD
               (§2.3) — resource, field path, type. Flag any disagreement rather
               than silently following either version. Then implement.
```

**Why (A) is the default.** The end user's recollection of an API is not a reliable
spec — on the worked example in §11 the request named the wrong resource *and* the
wrong field name. Reading the source costs the agent two minutes and removes a whole
class of silent failure, where a test passes against a cluster on which the feature
was never applied. **Derive from the source; ask the user to confirm.**

**Why (B) is still fine.** The form is the contract, not the PR. A user who knows
the field, the resource and the assertions has supplied everything §5 consumes. The
agent should still spot-check the field path against the live CRD — that is one
command, and it is the exact thing memory gets wrong.

---

## 2. Step 0: fill the intake form from whatever source exists

Run these before writing anything. Each answers a specific line of the intake form.
**Skip this section entirely if the end user filled the form themselves** — do only
the §2.3 spot-check.

Pick your source. They are listed by richness, not by preference; §2.3 is just as
authoritative as §2.2 for the field shape:

| You have | Use | Gets you |
|---|---|---|
| An upstream PR | §2.1–2.2, §2.4–2.6 | Everything, including immutability rules and Day-2 semantics |
| A field that already ships in the CRD | **§2.3**, §2.5–2.6 | Resource, path, type, default, pattern, description, immutability (CEL) |
| Only a feature name or ticket | §2.3 to find the field, then as above | Enough, once the field is identified |
| Nothing but a description | Ask the user for the CRD resource + field path | Those two are the minimum — see §3 |

§2.7 applies in every case.

### 2.1 What the PR is and what it touched

```bash
gh pr view <N> --repo kubernetes-sigs/cluster-api-provider-aws \
  --json title,body,files,state,url
```

→ feature name, the "Special notes for your reviewer" section (usually states the
Day-1/Day-2 constraints verbatim), and the file list that tells you which API group
changed. **Check `state` — if it is not `MERGED`, say so in your report; the API can
still change.**

### 2.2 The authoritative field shape — the generated CRD

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws \
  | grep -A40 'config/crd/bases/.*\.yaml'
```

The generated CRD is the single best source: it gives the exact YAML key, nesting,
type, `default`, and any `pattern`. **Prefer it over the Go types** — the JSON tag
can differ from the Go field name, and the kubebuilder markers are already resolved.

→ CRD resource, field path, type, default, validation pattern.

### 2.3 No PR? Read the live CRD — equally authoritative

If the field already ships, the installed CRD gives the same facts §2.2 extracts
from a diff, for a field that is **actually present on the hub you will test
against** — which the PR cannot tell you. Use this whenever there is no PR, and as
the spot-check in flow (B).

```bash
# What the installed CRD says about one field
oc get crd rosamachinepools.infrastructure.cluster.x-k8s.io -o json \
  | jq '.spec.versions[] | select(.served) |
        .schema.openAPIV3Schema.properties.spec.properties.myField'
```

→ type, `default`, `pattern`, `description`, nested properties — everything §2.2
gives. If it returns `null`, the field is not in this CRD: either the name is wrong
or the provider is too old. Both are worth saying out loud before building on it.

```bash
# Don't know the field name? List what the resource supports and grep for it
oc get crd rosacontrolplanes.controlplane.cluster.x-k8s.io -o json \
  | jq -r '.spec.versions[] | select(.served) |
           .schema.openAPIV3Schema.properties.spec.properties | keys[]'

# Which of the three resources owns it?
for c in rosacontrolplanes.controlplane rosamachinepools.infrastructure \
         rosanetworks.infrastructure; do
  echo "== $c"
  oc get crd $c.cluster.x-k8s.io -o json 2>/dev/null \
    | jq -r '.spec.versions[] | select(.served) |
             .schema.openAPIV3Schema.properties.spec.properties | keys[]' \
    | grep -i '<partial-name>'
done
```

No cluster to hand? The same schema, for a given provider version, is in the
upstream repo — substitute the branch or tag you care about:

```bash
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/cluster-api-provider-aws/main/config/crd/bases/infrastructure.cluster.x-k8s.io_rosamachinepools.yaml" \
  | grep -A20 'myField:'
```

Immutability is visible here too, as a CEL rule on the field
(`x-kubernetes-validations` with `self == oldSelf`) — that is `mutable: false`.

### 2.4 Immutability and conflict rules — the webhook

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws \
  | grep -B5 -A40 'webhook.go'
```

→ `mutable:`, `applies_to:`, and any mutual exclusion. A webhook that rejects
`fooOptions` alongside `barID` is a `mutual_exclusions` entry — or, if the other
feature does not exist here yet, a comment saying so.

Without a PR, the webhook source is still readable directly
(`exp/webhooks/<resource>_webhook.go` upstream), and the CEL rules in §2.3 cover
most immutability. If neither is conclusive, ask the user — guessing `mutable`
wrong produces a feature that is registered as Day-1 but silently never re-checked.

### 2.5 The OCM representation — for the cross-check

The CRD proves the operator accepted a value; OCM proves the service applied it.
Find the OCM field by following the controller's conversion helper:

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws | grep -A20 'rosa_helper.go'
```

Without a PR, search the OCM model directly for the field — this works from the
field name alone and needs no diff:

```bash
gh api -X GET search/code \
  -f q="<field_name> repo:openshift-online/ocm-api-model" --jq '.items[].path'
```

Then confirm the wire name in the generated codec — **not** the `.model` file, whose
attribute casing is not the JSON name:

```bash
curl -s "https://raw.githubusercontent.com/openshift-online/ocm-api-model/main/clientapi/clustersmgmt/v1/<type>_type_json.go" \
  | grep 'WriteObjectField'
```

→ the OCM JSON path, in snake_case, verified rather than guessed.

Note whether OCM stores a sentinel differently from the CRD. On the worked example
the ROSA API stores *no* value where the CRD stores `"on-demand"` — the conversion
helper is where such asymmetries are visible, and the verification task has to
account for them or it will fail against a correctly configured cluster.

### 2.6 User-facing semantics — the upstream book

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws | grep -A60 'docs/book/src/topics'
```

→ ready-made prose, YAML examples, and usually a Day-2 transition table. Worth
reading before writing `docs/features/<feature>.md`; cite it rather than paraphrase.

Without a PR, the same pages are published at
`https://cluster-api-aws.sigs.k8s.io/topics/rosa/`, and the field-level reference at
`https://cluster-api-aws.sigs.k8s.io/crd/`.

### 2.7 Record the baseline before you change anything

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
```

Keep this number. You will need it in §7 to prove you added no failures, and to
avoid being blamed for ones that were already there. If the tree is dirty, stash
first (`git stash -q && python3 -m pytest tests/ -q; git stash pop -q`).

---

## 3. Feature intake form

**This form is the contract.** Everything §5 implements comes from here, and nothing
else is required to start. It can be filled either way:

- **Flow (A), the default** — the agent fills it from §2 and presents it for
  confirmation. The end user's only required action is to confirm or correct it.
- **Flow (B)** — the end user fills it in and hands it over. Perfectly valid; copy
  the block below, delete the `[source]` tags, and write what you know.

Three lines are **required** however it is filled: **feature ID**, **CRD resource**,
and **CRD field path**. Without them nothing downstream can be written correctly —
guessing a field path yields a test that passes against a cluster where the feature
was never applied. If the user cannot supply them, find them with §2.3; if that
fails too, ask rather than guess. Everything else has a workable default.

When the agent drafts, cite a source for every derived line — `[CRD]`, `[live CRD]`,
`[webhook]`, `[OCM]`, `[book]`, `[proposed]` — so the user can see what was read
versus assumed. Write `?` where §2 gave no answer.

The example below is filled from a PR; a `[live CRD]`-sourced draft looks the same
with different tags.

````markdown
## Feature intake — DRAFT from <source>, please confirm

### Identity
- Feature name (human):            Spot Instances                        [PR title]
- Feature ID (snake_case):         spot_market_options                   [CRD field]
- CLI alias (kebab-case):          spot                                  [proposed]
- Registry suite:                  node-config                           [proposed]
- Phase:                           Day1                                  [webhook: immutable]
- Minimum OpenShift version:       ?                                     ← CANNOT DERIVE
- Maximum / deprecated-in version: none

### Description
<!-- Agent: draft from the PR body + upstream book, 2-6 sentences. Say what the
     feature does, why we test it, and what breaks if it regresses. Link the PR and
     the issue it fixes. End user: rewrite freely — this is your text, it becomes
     the registry `description:` and the doc's Description section. -->

### Test logic — how the feature gets turned on
- Ansible variable that enables it:   spot_instances                     [proposed]
- Additional input vars:              spot_max_price                     [CRD]
- Type:                               boolean                            [CRD]
- Options (if select):                n/a
- Default when not requested:         absent                             [CRD omitempty]
- Value used in CI runs:              ?                                  ← CANNOT DERIVE
- Requires user input?                No — the CRD defaults maxPrice     [CRD default]
- Depends on other features:          none                               [webhook]
- Mutually exclusive with:            capacityReservationID — no such
                                      feature in this repo yet           [webhook]
- Mutable after creation?             No (field); maxPrice one-way only  [webhook]
- Rendered manifest fragment:                                            [CRD]
  ```yaml
  spec:
    spotMarketOptions:
      maxPrice: "on-demand"
  ```

### Verification — how we prove it worked
- CRD resource:                    ROSAMachinePool                       [CRD]
- CRD field path:                  spotMarketOptions.maxPrice            [CRD]
- Validation pattern:              ^([1-9][0-9]*(\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*|on-demand)$  [CRD]
- OCM API field:                   aws_node_pool.spot_market_options.max_price   [OCM codec]
- OCM/CRD asymmetry:               OCM stores no max_price for an
                                   on-demand bid                         [rosa_helper.go]
- AWS / boto3 check:               describe_instances →
                                   InstanceLifecycle == 'spot'           [proposed]
- Assertions:
  - [ ] .spec.spotMarketOptions.maxPrice equals the requested bid
  - [ ] at least one OCM node pool reports spot_market_options
  - [ ] at least one running worker reports InstanceLifecycle == spot
- Failure detail string:           "spotMarketOptions not set on ROSAMachinePool
                                   or workers are not Spot instances"
- Known platform limitations:      field absent from every shipped MCE CRD
                                   today → suite 21 WARNs until one ships

### Wiring
- Add to feature group:            ?                                     ← CANNOT DERIVE
- Add to a scenario:               follows from the group
- Needs its own test suite JSON:   No — verified by suite 21             [repo convention]
- Day-2 transitions in scope:      ?                                     ← CANNOT DERIVE
````

### Decisions the agent cannot derive — ask these

Everything above comes from the PR. These four do not, because they are judgments
about *this* repo's test matrix and cost, not facts about the API. Ask them in one
batch, with a recommendation, at the same time as presenting the draft:

| Decision | Why the PR cannot answer it | Default to recommend |
|---|---|---|
| **`min_version`** | The PR says when the field entered CAPA `main`, not which MCE/OCP build ships it. Only the team knows the pairing. | The repo's `default_version`, so the feature is runnable now and WARNs until the CRD lands. |
| **Feature group / scenario** | Trades coverage against blast radius, and can raise a whole group's version floor (see §8). | No group, unless the feature is cheap and deterministic. |
| **CI-safe default value** | Which value is safe in automation is an operational judgment — a plausible-looking value can make clusters fail to provision for reasons unrelated to the test. | The most conservative value that still exercises the feature. |
| **Day-2 scope** | The PR may document mutations this repo has no suite for. | Day-1 only; note Day-2 as follow-up. |

Do not block on anything else. If the user confirms with no changes, proceed.

In flow (B) the user has usually answered these already by filling the form. Ask
only about the ones they left blank.

---

## 4. Architecture: what a "feature test" is made of

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

Key invariant: **a feature that was not requested is SKIPped, never FAILed.** Every
check is guarded by `when: "'<id>' in requested_features_list"`, and
`requested_features` is produced by `FeatureManager.resolve_to_extra_vars()`
(`feature_manager.py:129`) from the `--feature` flags.

---

## 5. Agent procedure: the 10 steps

Throughout, replace `my_feature` / `my-feature` / `myCrdField` / `my_ansible_var`
with the confirmed values from §3.

### Step 1 — Register the feature

`templates/schemas/feature-registry.yml`, four edits:

1. **`var_map`** — feature ID → the Ansible variable the template reads.
   Skip only if the ID and the variable are identical *and* the template uses the ID.
2. **`cli_aliases`** — short kebab-case name users type.
3. **`cli_features`** — add the ID if it is a Day-1 creation feature settable through
   a flat extra var. If it is not, leave it out **and add a comment under
   "Excluded from CLI (with reason)" saying why** — that comment block is load-bearing
   documentation, `validate_features()` rejects anything not in `cli_features`.
4. **`suites[].features[]`** — the feature definition itself, in the confirmed suite.
   See the [skeleton](#61-registry-entry).

Optionally also: `dependencies`, `mutual_exclusions`, `feature_groups`, `scenarios`.
If the feature joins a group, **update that group's and scenario's `description:`**
too — `--list-scenarios` prints it, and a stale description is a silent lie.

### Step 2 — Declare version availability

`templates/schemas/version-compatibility.yml` → `feature_availability:`

```yaml
  my_feature:
    min_version: "4.22"
    max_version: null
```

`min_version` must also be repeated as `min_version:` on the registry entry
(the registry copy is what `docs/` and `--list-features` show; the compatibility
copy is what `validate_features()` enforces). Keep them identical — and add a test
asserting they match, since nothing else enforces it.

### Step 3 — Render it in the templates

Add the conditional to **both** control-plane templates, for **every** version
directory at or above `min_version`:

- `templates/versions/<ver>/features/rosa-controlplane-only.yaml.j2`
- `templates/versions/<ver>/features/rosa-combined-automation.yaml.j2`

> **5.0 is a byte-for-byte copy of 4.22.** `tests/test_feature_manager.py::TestVersionTemplateParity::test_50_templates_match_422`
> compares the two directories with `filecmp`. After editing `4.22`, copy the file to
> `5.0` (`cp templates/versions/4.22/features/X.j2 templates/versions/5.0/features/X.j2`).

Place the block where it belongs structurally in the `spec:` (tags near tags,
network near network, machine-pool fields on the `ROSAMachinePool` document) and
guard it so an unrequested feature renders *nothing*:

```jinja
{% if my_ansible_var is defined and my_ansible_var | bool %}
  myCrdField: ...
{% endif %}
```

**Emit sub-fields explicitly rather than relying on CRD defaulting.** If the template
writes `{}` and lets the API server fill in a default, the value verification compares
against is one nobody in this repo chose, and a change to the upstream default breaks
the test silently.

### Step 4 — Map the CRD field for verification

`playbooks/verify_feature_flags.yml` → `vars.crd_field_map`:

```yaml
      my_feature: {crd: "rosacontrolplanes.controlplane.cluster.x-k8s.io", field: "myCrdField"}
```

CRD names in use:

| Resource | CRD name |
|---|---|
| ROSAControlPlane | `rosacontrolplanes.controlplane.cluster.x-k8s.io` |
| ROSAMachinePool  | `rosamachinepools.infrastructure.cluster.x-k8s.io` |
| ROSANetwork      | `rosanetworks.infrastructure.cluster.x-k8s.io` |

This map does double duty: the rescue path uses it to distinguish "CRD does not
support this field yet" (**WARN**, platform limitation) from "CRD supports it but the
value is missing" (**FAIL**, real bug), and `setup_feature_verification.yml` derives
the list of valid `--feature` values for verification from its keys. **A feature
absent from this map is rejected as unknown by suite 21.**

### Step 5 — Add the CHECK block

`playbooks/verify_feature_flags.yml`, in the `FEATURE CHECKS` section, in rough
registry order:

```yaml
    - name: "CHECK: My Feature"
      ansible.builtin.include_tasks: "{{ playbook_dir }}/../tasks/features/verify_my_feature.yml"
      when: "'my_feature' in requested_features_list"
```

### Step 6 — Write the verification task

New file `tasks/features/verify_my_feature.yml`, following the
[skeleton](#63-verification-task). Non-negotiable parts:

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
first**. A typo then fails in one second instead of after a 40-minute provision.

### Step 7 — Declare AWS dependence (only if the check uses boto3)

`tasks/features/report_feature_verification.yml` → task *"Find features whose AWS
side could not be verified"* → add the ID to `aws_dependent_features`. Without this,
a run on a machine with no boto3 reports a clean PASS while never having looked at
AWS, and `environment.degraded` in the artifact stays false.

### Step 8 — Extend setup only if a new resource is needed

`tasks/features/setup_feature_verification.yml` already fetches `rcp`
(ROSAControlPlane), `rmp` (the cluster's ROSAMachinePool), `rnet` (ROSANetwork),
an OCM bearer token + `ocm_cluster`, and checks for boto3. Add a lookup here only if
your feature lives on a resource none of those cover — and fail loudly rather than
guessing when the resource is ambiguous (see how `rmp_named` refuses to verify an
arbitrary machine pool).

### Step 9 — Document it

- New file `docs/features/<feature-name>.md` from the [skeleton](#64-feature-doc),
  using the confirmed Description and Verification text from the intake form. Link
  the upstream PR and the upstream book page.
- Add a row to the feature table in `README.md` (around line 318), alphabetically.

### Step 10 — Extend the tests

In `tests/test_feature_manager.py`, add a `TestMyFeature` class covering:

- **the registry↔template seam** — render both templates, on every applicable
  version, and assert the field reaches the manifest with the right value *and the
  right type*. This catches a `var_map` name that disagrees with the template
  variable, the single most common bug in this seam;
- **absent when not requested** — renders nothing, not an empty block;
- **the version gate** — rejected one version below `min_version`, accepted at it;
- **registry and compatibility agree** on `min_version`;
- **required inputs** — warning when missing, silence when satisfied;
- **the verification task file exists** at the path the playbook includes, and the
  feature is in `crd_field_map` — both are string references nothing else checks.

If the feature joined a scenario, also add it to `SCENARIO_RENDER_EXPECTATIONS`, and
**update any existing test that asserts that group's size or version list** — those
changes are deliberate, so say why in the docstring rather than just editing a number.

---

## 6. Copy-paste skeletons

### 6.1 Registry entry

`templates/schemas/feature-registry.yml`, under the chosen suite's `features:`

```yaml
      - id: my_feature
        name: My Feature
        description: >-
          One or two sentences from the intake form. Mention required -e vars here;
          this string is what --list-features prints.
        type: boolean              # boolean|string|number|select|list|key_value|range|action|version
        # options: ["a", "b"]      # select only
        mutable: false             # can it change after cluster creation?
        applies_to: [create]       # create|apply|upgrade|delete|verify
        default: false
        # ci_default: 2            # value used in CI when it differs from default
        # requires_input: true     # user must pass values; pair with one of the two below
        # required_vars: [foo, bar]
        # required_vars_any_of:
        #   - [cw_role_arn, cw_log_group]
        #   - [s3_bucket]
        k8s_field: ".spec.myCrdField"
        resource: ROSAControlPlane
        min_version: "4.22"
        # placeholder: "arn:aws:kms:..."   # UI/doc hint for string inputs
        # max_length: 15
```

and the three one-liners:

```yaml
var_map:
  my_feature: my_ansible_var

cli_aliases:
  my-feature: my_feature

cli_features:
  - my_feature
```

### 6.2 Template conditional

```jinja
{% if my_ansible_var is defined and my_ansible_var | bool %}
  myCrdField:
    someKey: "{{ my_sub_var | default('default-value') }}"
{% endif %}
```

For non-boolean features test truthiness of the value itself, the way
`etcd_encryption_kms_arn` does:

```jinja
{% if my_ansible_var is defined and my_ansible_var %}
  myCrdField: {{ my_ansible_var }}
{% endif %}
```

Quote values the CRD types as strings — an unquoted `0.5` renders as a float and the
API server rejects it.

### 6.3 Verification task

`tasks/features/verify_my_feature.yml`

```yaml
---
# Feature Check: My Feature (via OCM API + CRD [+ boto3])

- name: Verify My Feature
  vars:
    expected_value: "{{ my_expected | default('something') }}"
    # Same pattern the CRD enforces, so a typo fails now rather than in 40 minutes.
    value_pattern: '^(...)$'
  block:
    - name: Assert the requested value is one the CRD would accept
      ansible.builtin.assert:
        that:
          - expected_value is match(value_pattern)
        fail_msg: "FAIL: '{{ expected_value }}' is not a valid value for my_feature"
        success_msg: "PASS: requested value '{{ expected_value }}' is valid"

    - name: Assert my feature via OCM
      ansible.builtin.assert:
        that:
          - ocm_cluster.my_field is defined
          - ocm_cluster.my_field == expected_value
        fail_msg: "FAIL: OCM reports my feature is not configured"
        success_msg: "PASS: OCM confirms my feature is configured"
      when: ocm_available

    - name: Assert my feature via CRD (fallback)
      ansible.builtin.assert:
        that:
          - rcp.spec.myCrdField is defined
          - rcp.spec.myCrdField == expected_value
        fail_msg: "FAIL: CRD myCrdField is not {{ expected_value }}"
        success_msg: "PASS: CRD confirms myCrdField (CRD fallback)"
      when: not ocm_available

    # Optional AWS cross-check. Keep the Python inline, pass inputs through the
    # environment (never interpolate cluster data into the source), and set
    # changed_when: false / failed_when: false so a missing AWS side degrades
    # rather than crashing the play. Add the id to aws_dependent_features (Step 7).
    - name: Check the AWS side via boto3
      ansible.builtin.command:
        argv:
          - python3
          - -c
          - |
            import boto3, json, os
            client = boto3.client('ec2', region_name=os.environ['VERIFY_REGION'])
            # ... query, then: print(json.dumps({...}))
      environment:
        VERIFY_REGION: "{{ aws_region | default(rcp.spec.region | default('us-west-2')) }}"
        CLUSTER_NAME: "{{ cluster_name }}"
      register: boto3_my_feature_check
      changed_when: false
      failed_when: false
      no_log: true

    - name: Skip AWS check (boto3 failed)
      ansible.builtin.debug:
        msg: "WARN: boto3 lookup failed — my feature verified via CRD/OCM only"
      when: boto3_my_feature_check.rc != 0

    - ansible.builtin.set_fact:
        features_passed: "{{ features_passed | int + 1 }}"
  rescue:
    - ansible.builtin.include_tasks: "{{ playbook_dir }}/../tasks/verify_feature_rescue.yml"
      vars:
        feature_id: my_feature
        fail_detail: "my feature not present on ROSAControlPlane"
```

For a **ROSAMachinePool** feature, replace the OCM block with a node-pool query:

```yaml
    - name: Query OCM node pools
      ansible.builtin.uri:
        url: "{{ ocm_api_url }}/api/clusters_mgmt/v1/clusters/{{ ocm_cluster.id }}/node_pools"
        method: GET
        headers:
          Authorization: "Bearer {{ ocm_token_result.json.access_token }}"
          Accept: application/json
        status_code: 200
        timeout: 15
      register: ocm_my_node_pools
      failed_when: false
      changed_when: false
      no_log: true
      when: ocm_available and ocm_cluster.id is defined

    - name: Cross-check via OCM node pool
      ansible.builtin.assert:
        that:
          - pools | length > 0
          - pools | selectattr('aws_node_pool.my_field', 'defined') | list | length > 0
        fail_msg: "FAIL: no OCM node pool reports my_field"
        success_msg: "PASS: OCM node pool confirms my_field"
      vars:
        # .get(), NOT ['items'] — see §8.
        pools: "{{ (ocm_my_node_pools.json | default({})).get('items', []) }}"
      when:
        - ocm_available
        - ocm_my_node_pools is defined
        - ocm_my_node_pools.json is defined
```

### 6.4 Feature doc

`docs/features/my-feature.md`

````markdown
# 4.22 Feature Testing: My Feature

| Field | Value |
|-------|-------|
| Feature ID | `my_feature` |
| CLI Flag | `--feature my-feature` |
| Category | Security & Authentication |
| Phase | Day1 |
| Type | boolean |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAControlPlane` |
| K8s Field | `.spec.myCrdField` |
| Min Version | 4.22 |
| Ansible Variable | `my_ansible_var` |

## Description

<!-- Confirmed description from the intake form. Link the upstream PR. -->

## Usage

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature -e name_prefix=qe6
```

## Template Rendering

When `my_ansible_var` is `true`:

```yaml
spec:
  myCrdField: ...
```

## Verification

<!-- Confirmed verification logic, as the assertions the task makes. -->

Asserts:
- ...

## Constraints

<!-- Immutability and mutual exclusions, from the webhook. -->

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- Upstream PR: <url>
- Feature Group: `day1-...`
````

---

## 7. Validation: commands to run before declaring done

Run these in order; each catches a different class of mistake. None provisions a
cluster or costs AWS money.

```bash
# 1. Registry parses, feature visible with the right metadata, group/scenario
#    descriptions updated
./run-test-suite.py --list-features
./run-test-suite.py --list-scenarios

# 2. Flag resolution, dependency resolution, version gating, required inputs
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature --validate-only

# 3. Rejected below min_version. Check the EXIT CODE, not the message —
#    piping to tail masks it.
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature \
  -e openshift_version=4.21 --validate-only >/dev/null 2>&1; echo "exit=$?"   # expect 1

# 4. If it joined a scenario: resolves, and emits the var the template reads
./run-test-suite.py --scenario day1-combo -e openshift_version=4.22 --validate-only

# 5. The whole unit suite. Compare against the §2.7 baseline — equal pass count
#    plus your new tests, and NO new failures.
python3 -m pytest tests/ -q

# 6. Syntax + lint. ansible-lint is the only thing that catches bad Jinja.
ansible-playbook --syntax-check playbooks/verify_feature_flags.yml
ansible-lint tasks/features/verify_my_feature.yml playbooks/verify_feature_flags.yml
yamllint -d '{extends: default, rules: {line-length: {max: 200}}}' \
  tasks/features/verify_my_feature.yml

# 7. Everything the pre-commit hooks check
pre-commit run --all-files
```

### Prove the logic no unit test reaches

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

### Only a real provision proves it end to end

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature my-feature -e name_prefix=qe6
./run-test-suite.py 21-verify-feature-flags --feature my-feature -e cluster_name=qe6-rosa-hcp
jq '.features[] | select(.id=="my_feature")' test-results/feature-verification.json
./run-test-suite.py 30-rosa-hcp-delete -e cluster_name=qe6-rosa-hcp
```

**Never run a provision without being asked.** It takes ~40 minutes and spends real
AWS money. Report that the dry validation passed and let the user decide.

---

## 8. Rules and gotchas

**Verify the API; do not trust the description of it.** Including the end user's.
See §2 and the correction in §11.

**Establish the baseline before editing.** Report pre-existing failures as
pre-existing, with evidence (`git stash`, re-run, restore). Never present someone
else's broken test as yours, or yours as theirs.

**`{}['items']` is the `dict.items` method, not a missing key.** So
`(x | default({}))['items'] | default([])` silently yields a bound method and
`default([])` never fires — ansible-lint reports it as
`jinja[invalid]: Type 'method' is unsupported for variable storage`. Use
`.get('items', [])`.

**`map(attribute=…, default=…) | select('defined')` filters nothing.** The default
makes every element defined, so the assertion passes even when the field is absent
everywhere. Use `selectattr('a.b.c', 'defined')`, which handles dotted paths.

**Not-requested means SKIP, never FAIL.** Every check in `verify_feature_flags.yml`
is guarded by `'<id>' in requested_features_list`. Do not add an unconditional check
unless it is a universal invariant — the only current example is
`verify_long_cluster_name.yml`.

**WARN vs FAIL is decided for you.** `tasks/verify_feature_rescue.yml` queries the
live CRD schema: field absent → WARN (platform limitation), field present but value
missing → FAIL (bug), `oc`/`jq` error → FAIL (never silently WARN). This only works
if the feature is in `crd_field_map`. Do not reimplement this logic in a check.

**A brand-new upstream field will WARN, not PASS, and that is correct.** The API
server prunes the unknown key, verification finds nothing, and the rescue path
classifies it. Say so explicitly in your report and in the feature doc, so nobody
reads the WARN as a broken test — and so nobody "fixes" it by weakening the check.

**Boolean vs typed features resolve differently.** `resolve_to_extra_vars()` sets
`<var>=true` for `type: boolean`. For every other type it sets the var to
`ci_default` (falling back to `default`), *skips it entirely if that value is empty*,
and additionally sets `feature_<id>_enabled=true`. So a `requires_input` feature with
an empty default emits no var at all until the user passes `-e` — which is exactly why
`required_vars` exists.

**`var_map` name must equal the template variable name.** The registry emits
`var_map[id]`; the Jinja template reads some name. If they differ the feature renders
as nothing and the failure surfaces 40 minutes later as a verification FAIL. The
render test in Step 10 exists to catch this.

**`k8s_field` in the registry is documentation only.** Nothing reads it at runtime —
keep it accurate for the docs and for `--list-features`, but the field that actually
drives verification is `crd_field_map` in `playbooks/verify_feature_flags.yml`, and
the field that actually drives rendering is the `var_map` entry. All three must agree;
nothing enforces that but the tests you write.

**Adding a feature to a group raises that group's version floor.** A scenario is
valid only on versions where *every* feature is available, so one 4.22 feature makes
the whole group 4.22+. Check `scenario_versions()` before and after, tell the user,
and give them the explicit-flags fallback for older versions.

**5.0 templates must stay byte-identical to 4.22.** Enforced by `filecmp`. If a
feature genuinely must differ, change the test deliberately and say why.

**CI fails on degraded verification.** If OCM is unreachable, or boto3 is missing for
an `aws_dependent_features` entry, `report_feature_verification.yml` fails the run
when `CI` is truthy. Local runs record the degradation and continue. Do not "fix" a
degraded CI run by removing the feature from `aws_dependent_features`.

**Secrets.** Credentials go through `vars/user_vars.yml` (gitignored) or the
environment; account-specific values in scenarios use `${ENV_VAR}` expansion. Any
task touching credentials gets `no_log: true`. `detect-secrets` runs in pre-commit
against `.secrets.baseline` — never commit an ARN, bucket name, or key belonging to a
real account (use `123456789012` and `example`).

**Cluster identifiers are truncated in output.** Follow the existing
`| truncate(4, true, '****', 0)` pattern when printing cluster or namespace names.

**Verification is the last chance to capture state.** Stage 30 deletes the cluster, so
anything not recorded into `feature-verification.json` at stage 21 is gone.

---

## 9. Definition of done

- [ ] Intake form complete — either drafted by the agent with every line sourced and **confirmed by the end user**, or supplied by the end user with the CRD resource and field path spot-checked against the live CRD (§2.3)
- [ ] Registry entry added under the right suite, with accurate `k8s_field`, `resource`, `type`, `default`
- [ ] `var_map`, `cli_aliases`, `cli_features` updated (or an explicit comment saying why not in `cli_features`)
- [ ] `dependencies` / `required_vars` / `required_vars_any_of` / `mutual_exclusions` declared if applicable
- [ ] `feature_availability` entry, `min_version` matching the registry
- [ ] Group and scenario `description:` updated if the feature joined one
- [ ] Template conditional in `rosa-controlplane-only.yaml.j2` **and** `rosa-combined-automation.yaml.j2`, for every applicable version dir
- [ ] `5.0` templates byte-identical to `4.22`
- [ ] `crd_field_map` entry and `CHECK:` include added, guarded by `requested_features_list`
- [ ] `tasks/features/verify_<id>.yml` written with block/rescue, input pre-check, CRD + OCM layers, PASS/FAIL messages, `features_passed` increment
- [ ] Added to `aws_dependent_features` if it uses boto3
- [ ] `docs/features/<feature>.md` written, linking the upstream PR; row added to `README.md`
- [ ] Tests added: render seam, absent-when-unrequested, version gate, min_version agreement, task-file existence, `crd_field_map` membership
- [ ] Existing tests that this deliberately changes are updated **with a docstring saying why**
- [ ] All §7 commands pass; pytest shows no new failures against the §2.7 baseline
- [ ] Verification Jinja exercised against present / absent / empty fixtures
- [ ] Report states: what was derived vs assumed, pre-existing failures, side effects, and what was left out

---

## 10. Variants: features that do not fit the standard shape

**Feature with its own verification playbook** (`type: action`, `applies_to: [verify]`).
`break_glass_credentials` is the model: it has `playbook: playbooks/verify_break_glass_credentials.yml`
in the registry, and is listed in `externally_verified_features` in
`tasks/features/setup_feature_verification.yml` so suite 21 drops it instead of
rejecting it as unknown. Add both, and give the feature its own task files under
`tasks/` (see `break_glass_preflight.yml`, `break_glass_create_credential.yml`,
`break_glass_diagnose_403.yml`).

**Feature needing an AWS resource created during provisioning.**
`security_groups` is the model: `tasks/create_security_group.yml` reads the VPC from
the ROSANetwork status mid-provision and appends the created id to
`additional_security_groups`. Such a feature is `requires_input: false` even though it
has a value, because the caller cannot supply it before the VPC exists — say so in a
comment next to the registry entry.

**Feature needing its own test suite.** Only if it is a distinct lifecycle operation
rather than a flag on creation (upgrades, machine-pool add/delete, deletion). Add
`test-suites/NN-<name>.json`; `tests/test_suite_json_schema.py` requires `name`,
`description`, non-empty `playbooks` with existing `file` paths and a `name` each,
`tags` as a list of strings, and a `documentation` section with `prerequisites`. Then
decide whether the suite belongs in `scenario_defaults.stages` or only in a specific
scenario — and remember that any stage touching hub-wide state (like suites 40/41,
which flip MCE between CAPI and HyperShift) must stay opt-in.

**Day-2 feature applied after creation.** Set `phase: Day2` and
`applies_to: [apply]`/`[upgrade]`, keep it out of `cli_features`, and configure it
through a suite's `extra_vars` rather than `--feature`. `node_taints` and
`node_labels` are registry entries in this state today — registered and documented,
but not implemented by `add_rosa_machine_pool.yml`, which handles only
`instance_type` and `replicas`.

---

## 11. Worked example: spot instances

`spot_market_options` was added with exactly this procedure. Read its files as the
reference implementation:

| Layer | File |
|---|---|
| Registry | `templates/schemas/feature-registry.yml` (`node-config` suite) |
| Version gate | `templates/schemas/version-compatibility.yml` |
| Template | `templates/versions/{4.22,5.0}/features/rosa-{controlplane-only,combined-automation}.yaml.j2` |
| Verification | `tasks/features/verify_spot_market_options.yml` |
| Docs | `docs/features/spot-instances.md` |
| Tests | `tests/test_feature_manager.py::TestSpotMarketOptions` |

Upstream: [cluster-api-provider-aws#6334](https://github.com/kubernetes-sigs/cluster-api-provider-aws/pull/6334).

Four things that run is worth remembering for:

**The request described the API wrong.** It named `ROSAControlPlane.spec.spotInstanceOption.maxPrices`.
The merged CRD says `ROSAMachinePool.spec.spotMarketOptions.maxPrice` — wrong
resource, wrong field name, wrong plurality. Had the agent built from the
description, every layer would have been wrong and the test would have "passed" by
asserting nothing. §2 exists because of this.

**OCM and the CRD disagreed about the sentinel.** The CRD stores `maxPrice:
"on-demand"`; the ROSA API stores *no* `max_price` at all for the same state. A naive
equality cross-check fails against a correctly configured cluster. The conversion
helper (`exp/utils/rosa_helper.go`) is where that asymmetry was visible — §2.5.

**ansible-lint caught a bug the unit tests could not.** The first draft used
`(json | default({}))['items']`, which yields `dict.items`, and
`map(attribute=…, default={}) | select('defined')`, which filters nothing — so a
cluster with no spot configuration would have passed. Both are now in §8, and §7's
fixture check is what proves the negative case fails.

**Joining `day1-combo` moved that group's floor from 4.19 to 4.22.** A real
side effect on users who run the group on older versions, flagged to the user rather
than buried in a renamed test.
