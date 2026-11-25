# SKILLS.md — Adding a New Feature Test

A procedure for adding a ROSA HCP feature test to this repository, written so that
an **AI agent** can execute it end to end from a single upstream PR link, and the
**end user** only has to confirm or correct what the agent derived.

The repo registers 28 features (`templates/schemas/feature-registry.yml`), 18 of
which are reachable from `--feature` (`cli_features`), with 19 pages under
`docs/features/` (18 features plus `automated-feature-verification.md`) and 21
verification tasks under `tasks/features/`. They all follow the same shape. This
document describes that shape, names every file that must change, and gives
copy-paste skeletons for each one.

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
11. [Reference implementations](#11-reference-implementations)

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

**Why (A) is the default.** A recollection of an API is not a spec. Reading the
source costs the agent two minutes and removes a whole class of silent failure,
where a test passes against a cluster on which the feature was never applied.
**Derive from the source; ask the user to confirm.**

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

The served API version for all three resources in this repo's templates is
`v1beta2` (`controlplane.cluster.x-k8s.io/v1beta2`,
`infrastructure.cluster.x-k8s.io/v1beta2`); the core CAPI `Cluster`/`MachinePool`
version is templated as `capi_core_api_version` and defaults to `v1beta1`.

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
feature does not exist here yet, a comment saying so. (`mutual_exclusions` is an
empty list in the registry today, so a new entry there is the first one.)

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

Note whether OCM stores a sentinel differently from the CRD. The conversion helper
is where such asymmetries are visible, and the verification task has to account for
them or it will fail against a correctly configured cluster.

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
pip install -r requirements-dev.txt     # pytest is not in requirements.txt
python3 -m pytest tests agents scripts -q 2>&1 | tail -3
```

That path set is what CI runs (`.github/workflows/ci.yml`, job `pytest`) and what
`pytest.ini` declares as `testpaths`; `python3 -m pytest` with no arguments picks up
the same three. Keep the number. You will need it in §7 to prove you added no
failures, and to avoid being blamed for ones that were already there. If the tree is
dirty, stash first (`git stash -q && python3 -m pytest -q; git stash pop -q`).

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

The example below is filled in from an already-shipped feature (`audit_logging`), to
show what a complete form looks like; a PR-sourced draft is identical with `[CRD]`
and `[webhook]` tags instead of `[live CRD]`.

````markdown
## Feature intake — DRAFT from <source>, please confirm

### Identity
- Feature name (human):            Audit Log Forwarding                  [registry]
- Feature ID (snake_case):         audit_logging                         [registry]
- CLI alias (kebab-case):          log-forwarding                        [registry]
- Registry suite:                  day2-operations                       [registry]
- Phase:                           Day2 (suite-level)                    [registry]
- Minimum OpenShift version:       4.20                                  [compatibility]
- Maximum / deprecated-in version: none

### Description
<!-- Agent: draft from the PR body + upstream book, 2-6 sentences. Say what the
     feature does, why we test it, and what breaks if it regresses. Link the PR and
     the issue it fixes. End user: rewrite freely — this is your text, it becomes
     the registry `description:` and the doc's Description section. -->

### Test logic — how the feature gets turned on
- Ansible variable that enables it:   log_forward_enabled                [var_map]
- Additional input vars:              log_forward_cloudwatch_role_arn,
                                      log_forward_cloudwatch_log_group,
                                      log_forward_s3_bucket,
                                      log_forward_applications           [template]
- Type:                               boolean                            [registry]
- Options (if select):                n/a
- Default when not requested:         false                              [registry]
- Value used in CI runs:              n/a (requires_input)
- Requires user input?                Yes — required_vars_any_of         [registry]
- Depends on other features:          none                               [registry]
- Mutually exclusive with:            none                               [registry]
- Mutable after creation?             Yes — applies_to: [create, apply]  [registry]
- Rendered manifest fragment:                                            [template]
  ```yaml
  spec:
    cloudWatchlogForwarder:
      cloudWatchLogRoleArn: arn:aws:iam::123456789012:role/example
  ```

### Verification — how we prove it worked
- CRD resource:                    ROSAControlPlane                      [registry]
- CRD field path:                  cloudWatchlogForwarder (or
                                   s3LogForwarder)                       [crd_field_map]
- Validation pattern:              n/a
- OCM API field:                   none used — CRD + AWS only            [verify task]
- OCM/CRD asymmetry:               n/a
- AWS / boto3 check:               iam:GetRole, logs:DescribeLogGroups,
                                   s3:HeadBucket                         [verify task]
- Assertions:
  - [ ] at least one complete destination was requested (pre-check)
  - [ ] .spec.cloudWatchlogForwarder or .spec.s3LogForwarder is present
  - [ ] the configured role ARN / log group / bucket matches what was requested
  - [ ] those AWS objects exist (boto3; skipped when boto3 is absent)
- Failure detail string:           "log forwarding destinations not found
                                   in AWS"
- Known platform limitations:      none

### Wiring
- Add to feature group:            day1-networking                       [registry]
- Add to a scenario:               follows from the group
- Needs its own test suite JSON:   No — verified by suite 21             [repo convention]
- Day-2 transitions in scope:      ?                                     ← CANNOT DERIVE
````

### Decisions the agent cannot derive — ask these

Everything above comes from the source. These four do not, because they are
judgments about *this* repo's test matrix and cost, not facts about the API. Ask
them in one batch, with a recommendation, at the same time as presenting the draft:

| Decision | Why the source cannot answer it | Default to recommend |
|---|---|---|
| **`min_version`** | The PR says when the field entered CAPA `main`, not which MCE/OCP build ships it. Only the team knows the pairing. | `default_version` (`4.22`), so the feature is runnable now and WARNs until the CRD lands. |
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
     crd_field_map entry →   my_feature: {crd: rosacontrolplanes…, field: myCrdField}   (line ~22)
     CHECK include →         when: "'my_feature' in requested_features_list"            (line ~52+)
     the check itself →      tasks/features/verify_my_feature.yml   (block / rescue)
     result →                tasks/features/report_feature_verification.yml
                             → test-results/feature-verification.json → one JUnit case per feature
```

Key invariant: **a feature that was not requested is SKIPped, never FAILed.** Every
check is guarded by `when: "'<id>' in requested_features_list"`, and
`requested_features` is produced by `FeatureManager.resolve_to_extra_vars()`
(`feature_manager.py:128`) from the `--feature` flags.

---

## 5. Agent procedure: the 10 steps

Throughout, replace `my_feature` / `my-feature` / `myCrdField` / `my_ansible_var`
with the confirmed values from §3.

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
   See the [skeleton](#61-registry-entry).

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
(`feature_manager.py:411` — `avail.get("min_version") or feat.get("min_version")`).
Only four registry entries carry a redundant `min_version:` today
(`external_oidc`, `break_glass_credentials`, `fips`, `no_cni`). If you add one,
**keep the two identical and add a test asserting they match** — nothing else
enforces it, and a disagreeing registry copy is invisible until someone deletes the
compatibility entry.

An entry here is not strictly mandatory — `default_autoscaling` has none, so it is
simply never version-gated and `--list-features` reports no floor for it. That is
almost always an oversight rather than a decision: add the entry unless the feature
really is available on every supported version.

Supported versions are `4.18`–`4.22` and `5.0`; `default_version` is `4.22`.

### Step 3 — Render it in the templates

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

So the default is: **edit `4.22`, copy to `5.0`, stop.** Touch `4.21`/`4.20` only if
the feature's `min_version` genuinely reaches that far *and* the user wants it
runnable there — and if you do, add the matching `(version, template_name)` pairs to
your render test, because nothing else will cover them.

A **ROSANetwork** feature does not belong in either of these templates — it renders
through `rosa-network-config.yaml.j2` via `rosa_network_config`, and some features
are consumed by the provisioning playbook with no template conditional at all. See
§10 before assuming this step applies.

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

`playbooks/verify_feature_flags.yml` → `vars.crd_field_map` (line 22; 18 entries
today):

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
suite 21** — unless it is listed in `externally_verified_features` (§10).

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
[skeleton](#63-verification-task). `setup_feature_verification.yml` has already set
the facts you can rely on: `rcp`, `rmp` (and `rmp_named`), `rnet`, `ocm_cluster`,
`ocm_available`, `ocm_api_url`, `ocm_token_result`, `boto3_check`,
`requested_features_list`. Non-negotiable parts:

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
side could not be verified"* → add the ID to `aws_dependent_features` (line 103;
`[audit_logging, etcd_kms, byon, private_network]` today). Without this, a run on a
machine with no boto3 reports a clean PASS while never having looked at AWS, and
`environment.degraded` in the artifact stays false.

### Step 8 — Extend setup only if a new resource is needed

`tasks/features/setup_feature_verification.yml` already logs in, validates
`cluster_name`, parses `requested_features_list`, and fetches `rcp`
(ROSAControlPlane), `rmp` (the cluster's ROSAMachinePool, selected by exact name
match), `rnet` (ROSANetwork), an OCM bearer token + `ocm_cluster`, and checks for
boto3. Add a lookup here only if your feature lives on a resource none of those
cover — and fail loudly rather than guessing when the resource is ambiguous (see how
`rmp_named` refuses to verify an arbitrary machine pool).

### Step 9 — Document it

- New file `docs/features/<feature-name>.md` from the [skeleton](#64-feature-doc),
  using the confirmed Description and Verification text from the intake form. Link
  the upstream PR and the upstream book page.
- Add the feature to **both** README tables, alphabetically within each:
  - the CLI flag table under `### Available Features` (around line 313);
  - the docs table under `## Feature Documentation` (around line 368).

### Step 10 — Extend the tests

In `tests/test_feature_manager.py` (1656 lines), add a `TestMyFeature` class. The
existing `TestNoCNI`, `TestExternalOIDC`, `TestPrivateClusterSubnets`, `TestBYON`
and `TestBreakGlassCredentials` classes are the models. Cover:

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
  feature is in `crd_field_map`. **Nothing in the suite asserts either today** —
  both are string references that fail only at runtime, so this is the highest-value
  test you can add.

If the feature joined a scenario, also add it to `SCENARIO_RENDER_EXPECTATIONS`
(`tests/test_feature_manager.py:1537`), and **update any existing test that asserts
that group's size or version list** — those changes are deliberate, so say why in the
docstring rather than just editing a number.

---

## 6. Copy-paste skeletons

### 6.1 Registry entry

`templates/schemas/feature-registry.yml`, under the chosen suite's `features:`
(`category:` and `phase:` come from the suite, not from here)

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
        #   - [log_forward_cloudwatch_role_arn, log_forward_cloudwatch_log_group]
        #   - [log_forward_s3_bucket]
        k8s_field: ".spec.myCrdField"
        resource: ROSAControlPlane
        # min_version: "4.22"      # redundant with version-compatibility.yml; keep in sync
        # placeholder: "arn:aws:kms:..."   # UI/doc hint for string inputs
        # max_length: 15
```

Action-type features (`type: action`, their own playbook) use a different subset —
see `cluster_delete`, `control_plane_upgrade`, `machine_pool_upgrade`:

```yaml
        playbook: playbooks/delete_rosa_hcp_cluster.yml
        wait_timeout: 3600
        # wait_resource / wait_field / wait_value   # readiness gate for upgrades
        destructive: true
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

`docs/features/my-feature.md` — the header table is the house style; see
`docs/features/disk-size.md` for a filled-in example.

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

# 5. The whole unit suite — same paths CI runs. Compare against the §2.7 baseline:
#    equal pass count plus your new tests, and NO new failures.
python3 -m pytest tests agents scripts -q

# 6. Lint, matching the CI jobs in .github/workflows/ci.yml
ansible-playbook --syntax-check playbooks/verify_feature_flags.yml
ansible-lint playbooks/
yamllint -f parsable --no-warnings playbooks/ tasks/
black --check *.py        # only if you touched a top-level .py
pylint *.py --disable=C,R

# 7. Everything the pre-commit hooks check
pre-commit run --all-files
```

CI gates on all of these plus a Trivy/TruffleHog scan and a `--list`/`--help`
dry run; the `all-checks-passed` job fails if any of them does.

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
See §2 and the first entry in §11's lessons.

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
if the feature is in `crd_field_map`; without an entry every rescue is a flat FAIL.
Do not reimplement this logic in a check.

**A brand-new upstream field will WARN, not PASS, and that is correct.** The API
server prunes the unknown key, verification finds nothing, and the rescue path
classifies it. Say so explicitly in your report and in the feature doc, so nobody
reads the WARN as a broken test — and so nobody "fixes" it by weakening the check.

**Boolean vs typed features resolve differently.** `resolve_to_extra_vars()` sets
`<var>=true` for `type: boolean`. For every other type it sets the var to
`ci_default` (falling back to `default`), *skips it entirely if that value is empty*
(`""`, `{}`, `[]`), and additionally sets `feature_<id>_enabled=true`. So a
`requires_input` feature with an empty default emits no var at all until the user
passes `-e` — which is exactly why `required_vars` exists.

**`var_map` name must equal the template variable name.** The registry emits
`var_map.get(id, id)` — so a missing entry silently emits the feature ID as the
variable name. If that disagrees with the Jinja, the feature renders as nothing and
the failure surfaces 40 minutes later as a verification FAIL. The render test in
Step 10 exists to catch this.

**`k8s_field` in the registry is documentation only.** Nothing reads it at runtime —
keep it accurate for the docs and for `--list-features`, but the field that actually
drives verification is `crd_field_map` in `playbooks/verify_feature_flags.yml`, and
the field that actually drives rendering is the `var_map` entry. All three must agree;
nothing enforces that but the tests you write.

**Adding a feature to a group raises that group's version floor.** A scenario is
valid only on versions where *every* feature is available, so one 4.22 feature makes
the whole group 4.22+. Check `scenario_versions()` before and after, tell the user,
and give them the explicit-flags fallback for older versions.

**5.0 templates must stay byte-identical to 4.22**, apart from the two version-
specific files named in `TestVersionTemplateParity.VERSION_SPECIFIC`. If a feature
genuinely must differ, change the test deliberately and say why.

**Suite JSON is a closed schema.** `templates/schemas/test-suite-schema.json` has
`additionalProperties: false`, so any key `run-test-suite.py` does not read fails
`tests/test_suite_json_schema.py`. Prose belongs in `docs/test-suites/<id>.md`, and
a `documentation` key in the JSON is rejected outright.

**CI fails on degraded verification.** If OCM is unreachable, or boto3 is missing for
an `aws_dependent_features` entry, `report_feature_verification.yml` fails the run
when the `CI` env var is truthy. Local runs record the degradation and continue. Do
not "fix" a degraded CI run by removing the feature from `aws_dependent_features`.

**Secrets.** Credentials go through `vars/user_vars.yml` (gitignored) or the
environment; account-specific values in scenarios use `${ENV_VAR}` expansion. Any
task touching credentials gets `no_log: true`. `detect-secrets` runs in pre-commit
against `.secrets.baseline`, and TruffleHog runs in CI — never commit an ARN, bucket
name, or key belonging to a real account (use `123456789012` and `example`).

**Cluster identifiers are truncated in output.** Follow the existing
`| truncate(4, true, '****', 0)` pattern when printing cluster or namespace names.

**Verification is the last chance to capture state.** Stage 30 deletes the cluster, so
anything not recorded into `feature-verification.json` at stage 21 is gone.

---

## 9. Definition of done

- [ ] Intake form complete — either drafted by the agent with every line sourced and **confirmed by the end user**, or supplied by the end user with the CRD resource and field path spot-checked against the live CRD (§2.3)
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
- [ ] All §7 commands pass; pytest shows no new failures against the §2.7 baseline
- [ ] Verification Jinja exercised against present / absent / empty fixtures
- [ ] Report states: what was derived vs assumed, pre-existing failures, side effects, and what was left out

---

## 10. Variants: features that do not fit the standard shape

**Feature with its own verification playbook** (`type: action`, `applies_to: [verify]`).
`break_glass_credentials` is the model: it has `playbook: playbooks/verify_break_glass_credentials.yml`
in the registry, and is listed in `externally_verified_features` in
`tasks/features/setup_feature_verification.yml` (line 44) so suite 21 drops it
instead of rejecting it as unknown. Add both, and give the feature its own task
files under `tasks/` (see `break_glass_preflight.yml`,
`break_glass_create_credential.yml`, `break_glass_diagnose_403.yml`).

**Feature needing an AWS resource created during provisioning.**
`security_groups` is the model: `tasks/create_security_group.yml` reads the VPC id
from the ROSANetwork mid-provision, validates it against `^vpc-[a-f0-9]+$`, creates
the group and appends its id to `additional_security_groups`. Such a feature is
`requires_input: false` even though it has a value, because the caller cannot supply
it before the VPC exists — say so in a comment next to the registry entry.

**Feature the provisioning playbook consumes, with no template conditional.**
Step 3 assumes the `var_map` variable is read by a Jinja `{% if %}` in the two
control-plane templates. For some features it is read by `tasks/provision_rosa_hcp_with_automation.yml`
instead, and never appears in a template at all:

- `byon` → `byon_vpc` is a control-flow flag: it forces `create_rosa_network: false`
  and gates the subnet-ID and AZ validation, so the real user inputs are
  `byon_subnet_ids` / `byon_availability_zones` (hence `required_vars`, and the
  comment next to the registry entry saying the mapped var is only the enable flag).
- `availability_zones` → `availability_zone_count` is defaulted in the same task and
  feeds `rosa_network_config.availability_zones`, which
  `templates/versions/<ver>/features/rosa-network-config.yaml.j2` loops over to build
  the ROSANetwork. **Any ROSANetwork feature renders through that third template, not
  the two in Step 3.**

For these, Step 3 becomes "wire it where the value is actually consumed", and the
Step 10 render test has to drive the playbook's variable, not just the template —
`TestBYON` is the model. Say in the feature doc which file consumes the variable;
that is the one thing a reader cannot guess from the registry.

**Feature needing its own test suite.** Only if it is a distinct lifecycle operation
rather than a flag on creation (upgrades, machine-pool add/delete, deletion). Then:

1. Add `test-suites/NN-<name>.json`. The schema
   (`templates/schemas/test-suite-schema.json`) is **closed**: `name`, `description`,
   `tags` (list of strings) and a non-empty `playbooks` array are required; optional
   keys are `stopOnFailure`, `depends_on`, `always`. Each playbook entry requires
   `name` and may carry `file`, `description`, `extra_vars`, `required`, `timeout`,
   `test_case_id`. Anything else fails `tests/test_suite_json_schema.py`.
2. Add `docs/test-suites/NN-<name>.md`. `tests/test_suite_docs.py` requires it to
   exist, to start with a level-1 title, and to contain the literal row
   `| **Suite ID** | `NN-<name>` |`.
3. Link that page from `README.md` as `docs/test-suites/NN-<name>.md` — also
   enforced by `test_suite_docs.py`.
4. Decide whether the suite belongs in `scenario_defaults.stages` or only in a
   specific scenario — and remember that any stage touching hub-wide state (like
   suites 40/41, which flip MCE between CAPI and HyperShift) must stay opt-in.

**Day-2 feature applied after creation.** Set it under a `phase: Day2` suite and
`applies_to: [apply]`/`[upgrade]`, keep it out of `cli_features`, and configure it
through a suite's `extra_vars` rather than `--feature`. `node_taints` and
`node_labels` are registry entries in this state today — registered and documented,
but not implemented by `add_rosa_machine_pool.yml`, which handles only
`instance_type` and `replicas`.

---

## 11. Reference implementations

There is no single canonical feature; pick the one whose shape matches yours and
read all four of its layers before writing anything.

| If your feature is… | Read | Why |
|---|---|---|
| A plain boolean on ROSAControlPlane | `no_cni` — `verify_no_cni.yml`, `docs/features/no-cni.md`, `tests/…::TestNoCNI` | The simplest complete example of all four layers |
| On ROSAMachinePool | `disk_size` — `verify_disk_size.yml`, `docs/features/disk-size.md` | The `GET /clusters/{id}/node_pools` cross-check, and a CRD assert that is unconditional rather than an OCM fallback |
| Requiring user input | `audit_logging` — registry `required_vars_any_of`, `verify_audit_logging.yml` | Alternative input groups, and the "no input ⇒ no rendered block ⇒ failure 40 minutes later" comment that explains why it is declared |
| Needing an AWS resource first | `security_groups` — `tasks/create_security_group.yml`, `verify_security_groups.yml` | Mid-provision resource creation feeding back into template vars |
| Pulling in another feature | `byon` (→ `private_network`), `fips` (→ `etcd_kms`) | `dependencies` and the render tests that prove the dependency actually lands |
| Verified by its own playbook | `break_glass_credentials` — `playbooks/verify_break_glass_credentials.yml` | `playbook:` + `externally_verified_features`, §10 |
| A lifecycle operation | `control_plane_upgrade`, `machine_pool_upgrade`, `cluster_delete` | `type: action`, `wait_*` gating, `destructive: true`, and their own suites (25/26/30) |

### Lessons worth keeping

**The request can describe the API wrong.** A past feature request named the wrong
resource *and* the wrong field name; the merged CRD disagreed on both. Had it been
built from the description, every layer would have been wrong and the test would
have "passed" by asserting nothing. §2 exists because of this.

**OCM and the CRD can disagree about a sentinel value.** The CRD may store an
explicit marker where the ROSA API stores nothing at all for the same state. A naive
equality cross-check then fails against a correctly configured cluster. The
conversion helper (`exp/utils/rosa_helper.go` upstream) is where that asymmetry is
visible — §2.5.

**ansible-lint catches bugs the unit tests cannot.** The two Jinja traps in §8
(`['items']` on a possibly-empty dict, and `map(attribute=…, default=…)`) both
produce checks that pass on a cluster where the feature was never configured. Unit
tests do not reach the verification task's Jinja; ansible-lint and §7's fixture
playbook are what prove the negative case fails.

**Joining a feature group can move that group's version floor.** Adding one 4.22
feature to a group that ran on 4.19 is a real side effect on users, not a test
detail. Flag it rather than burying it in a renamed test.
