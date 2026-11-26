# Step 0 and the intake form

Read this before writing anything. Part 1 fills the form from whatever source
exists; part 2 is the form itself, which is the contract everything downstream
consumes.

---

## Part 1 — Fill the form from whatever source exists

Run these before writing anything. Each answers a specific line of the intake form.
**Skip this part entirely if the end user filled the form themselves** — do only
the §1.3 spot-check.

Pick your source. They are listed by richness, not by preference; §1.3 is just as
authoritative as §1.2 for the field shape:

| You have | Use | Gets you |
|---|---|---|
| An upstream PR | §1.1–1.2, §1.4–1.6 | Everything, including immutability rules and Day-2 semantics |
| A field that already ships in the CRD | **§1.3**, §1.5–1.6 | Resource, path, type, default, pattern, description, immutability (CEL) |
| Only a feature name or ticket | §1.3 to find the field, then as above | Enough, once the field is identified |
| Nothing but a description | Ask the user for the CRD resource + field path | Those two are the minimum — see Part 2 |

§1.7 applies in every case.

### 1.1 What the PR is and what it touched

```bash
gh pr view <N> --repo kubernetes-sigs/cluster-api-provider-aws \
  --json title,body,files,state,url
```

→ feature name, the "Special notes for your reviewer" section (usually states the
Day-1/Day-2 constraints verbatim), and the file list that tells you which API group
changed. **Check `state` — if it is not `MERGED`, say so in your report; the API can
still change.**

### 1.2 The authoritative field shape — the generated CRD

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws \
  | grep -A40 'config/crd/bases/.*\.yaml'
```

The generated CRD is the single best source: it gives the exact YAML key, nesting,
type, `default`, and any `pattern`. **Prefer it over the Go types** — the JSON tag
can differ from the Go field name, and the kubebuilder markers are already resolved.

→ CRD resource, field path, type, default, validation pattern.

### 1.3 No PR? Read the live CRD — equally authoritative

If the field already ships, the installed CRD gives the same facts §1.2 extracts
from a diff, for a field that is **actually present on the hub you will test
against** — which the PR cannot tell you. Use this whenever there is no PR, and as
the spot-check in flow (B).

```bash
# What the installed CRD says about one field
oc get crd rosamachinepools.infrastructure.cluster.x-k8s.io -o json \
  | jq '.spec.versions[] | select(.served) |
        .schema.openAPIV3Schema.properties.spec.properties.myField'
```

→ type, `default`, `pattern`, `description`, nested properties — everything §1.2
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

### 1.4 Immutability and conflict rules — the webhook

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws \
  | grep -B5 -A40 'webhook.go'
```

→ `mutable:`, `applies_to:`, and any mutual exclusion. A webhook that rejects
`fooOptions` alongside `barID` is a `mutual_exclusions` entry — or, if the other
feature does not exist here yet, a comment saying so. (`mutual_exclusions` is an
empty list in the registry today, so a new entry there is the first one.)

**Why this step exists.** The three facts it yields are written down nowhere else,
and they fail in three different ways:

- **Cross-field conflicts appear in no schema.** §1.3's CEL rules give you
  single-field immutability (`x-kubernetes-validations` with `self == oldSelf`),
  but a rule of the form *"reject `fooOptions` when `barID` is set"* is ordinary Go
  in the webhook. No CRD schema, no generated reference, and no amount of reading
  the field's own definition will surface it. If you skip this step, the first time
  anyone learns about the conflict is when a cluster fails to provision.
- **`mutual_exclusions` is enforced, and it converts an expensive failure into a
  cheap one.** `validate_features()` rejects a conflicting pair before anything is
  applied (`grep -n 'mutual_exclusions' feature_manager.py` → `"Features [...] are
  mutually exclusive"`), so the user sees it in about a second from
  `--validate-only`. Leave the entry out and the identical conflict reappears as a
  webhook rejection partway through a 40-minute provision, phrased in upstream's
  words rather than ours, after the AWS spend.
- **`mutable:` and `applies_to:` are read by nothing at runtime.** Grep them and
  every hit is the registry itself — they are documentation, exactly like
  `k8s_field`. That is what makes them easy to get wrong and slow to notice: they
  are what the feature's docs page and `--list-features` tell everyone else.
  Marking an immutable field `mutable: true` invites the next person to build a
  Day-2 mutation suite against a field the API server will reject with
  `self == oldSelf` — and they pay for the mistake, not you.

Without a PR, the webhook source is still readable directly
(`exp/webhooks/<resource>_webhook.go` upstream), and the CEL rules in §1.3 cover
most immutability. If neither is conclusive, ask the user. A wrong `mutable:` costs
nobody a failed run today, which is precisely why it survives long enough to
mislead someone later.

### 1.5 The OCM representation — for the cross-check

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

### 1.6 User-facing semantics — the upstream book

```bash
gh pr diff <N> --repo kubernetes-sigs/cluster-api-provider-aws | grep -A60 'docs/book/src/topics'
```

→ ready-made prose, YAML examples, and usually a Day-2 transition table. Worth
reading before writing `docs/features/<feature>.md`; cite it rather than paraphrase.

Without a PR, the same pages are published at
`https://cluster-api-aws.sigs.k8s.io/topics/rosa/`, and the field-level reference at
`https://cluster-api-aws.sigs.k8s.io/crd/`.

### 1.7 Record the baseline before you change anything

```bash
pip install -r requirements-dev.txt     # pytest is not in requirements.txt
python3 -m pytest tests agents scripts -q 2>&1 | tail -3
```

That path set is what CI runs (`.github/workflows/ci.yml`, job `pytest`) and what
`pytest.ini` declares as `testpaths`; `python3 -m pytest` with no arguments picks up
the same three. Keep the number. You will need it later to prove you added no
failures, and to avoid being blamed for ones that were already there.

**If the tree is dirty, measure the baseline in a throwaway worktree** rather than
stashing:

```bash
git worktree add --detach /tmp/rosa-baseline HEAD
(cd /tmp/rosa-baseline && python3 -m pytest tests agents scripts -q | tail -3)
git worktree remove /tmp/rosa-baseline
```

> **Do not reach for `git stash -q && … ; git stash pop -q`.** When the tree holds
> only *untracked* files, `git stash` has nothing to save, creates no entry, and
> still exits `0` — so the `pop` that follows applies, and deletes, whatever
> unrelated stash happened to be on top of the stack. It also leaves those
> untracked files in place, so the "clean" baseline was never clean. The worktree
> touches neither the working tree nor the stash stack.

---

## Part 2 — The intake form

**This form is the contract.** Everything the 10 steps implement comes from here, and
nothing else is required to start. It can be filled either way:

- **Flow (A), the default** — the agent fills it from Part 1 and presents it for
  confirmation. The end user's only required action is to confirm or correct it.
- **Flow (B)** — the end user fills it in and hands it over. Perfectly valid; copy
  the block below, delete the `[source]` tags, and write what you know.

Three lines are **required** however it is filled: **feature ID**, **CRD resource**,
and **CRD field path**. Without them nothing downstream can be written correctly —
guessing a field path yields a test that passes against a cluster where the feature
was never applied. If the user cannot supply them, find them with §1.3; if that
fails too, ask rather than guess. Everything else has a workable default.

When the agent drafts, cite a source for every derived line — `[CRD]`, `[live CRD]`,
`[webhook]`, `[OCM]`, `[book]`, `[proposed]` — so the user can see what was read
versus assumed. Write `?` where Part 1 gave no answer.

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
| **Feature group / scenario** | Trades coverage against blast radius, and can raise a whole group's version floor. | No group, unless the feature is cheap and deterministic. |
| **CI-safe default value** | Which value is safe in automation is an operational judgment — a plausible-looking value can make clusters fail to provision for reasons unrelated to the test. | The most conservative value that still exercises the feature. |
| **Day-2 scope** | The PR may document mutations this repo has no suite for. | Day-1 only; note Day-2 as follow-up. |

Do not block on anything else. If the user confirms with no changes, proceed.

In flow (B) the user has usually answered these already by filling the form. Ask
only about the ones they left blank.
