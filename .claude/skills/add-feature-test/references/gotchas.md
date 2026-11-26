# Rules and gotchas

Most of these produce a test that *passes* while proving nothing. Read before
writing the verification task.

**Verify the API; do not trust the description of it.** Including the end user's.
See `intake.md` Part 1 and the first entry in `variants.md`'s lessons.

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
Step 10 exists to catch this, and `make verify-skills FEATURE=<id>` checks that both
4.22 templates actually read the mapped variable.

**`k8s_field` in the registry is documentation only.** Nothing reads it at runtime —
keep it accurate for the docs and for `--list-features`, but the field that actually
drives verification is `crd_field_map` in `playbooks/verify_feature_flags.yml`, and
the field that actually drives rendering is the `var_map` entry. All three must agree;
nothing enforces that but the tests you write and `make verify-skills`.

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
