# SKILLS.md — Adding a New Feature Test

The procedure for adding a ROSA HCP feature test to this repository lives in
`.claude/skills/add-feature-test/`, as a Claude Code skill. An agent working in this
repo loads it automatically when asked to add or wire up a `--feature`; this page is
the entry point for everyone else.

It is written so that an **AI agent** can execute it end to end from a single
upstream PR link, and the **end user** only has to confirm or correct what the agent
derived.

## Where it lives

| File | What it covers |
|---|---|
| [`.claude/skills/add-feature-test/SKILL.md`](.claude/skills/add-feature-test/SKILL.md) | The flow, the four layers a feature passes through, the 10 implementation steps, and the definition of done |
| [`references/intake.md`](.claude/skills/add-feature-test/references/intake.md) | Step 0 — reading the upstream PR, the live CRD, the webhook, the OCM model — and the intake form that is the contract |
| [`references/skeletons.md`](.claude/skills/add-feature-test/references/skeletons.md) | Copy-paste blocks: registry entry, template conditional, verification task, feature doc |
| [`references/validation.md`](.claude/skills/add-feature-test/references/validation.md) | Every command to run before declaring done |
| [`references/gotchas.md`](.claude/skills/add-feature-test/references/gotchas.md) | The rules that, when broken, produce a test that passes while proving nothing |
| [`references/variants.md`](.claude/skills/add-feature-test/references/variants.md) | Features that do not fit the standard shape, plus reference implementations |

Start with `SKILL.md`. It says which reference to open at which step; reading them
all up front is not the intent.

## Keeping it honest

A procedure doc rots silently. `scripts/verify_skills_md.py` walks one shipped
feature through every layer the skill claims it must touch — registry, version gate,
both 4.22/5.0 templates, `crd_field_map`, the CHECK guard, the verification task, the
docs page, both README tables, and the extra vars the CLI actually resolves — and
exits non-zero on the first disagreement:

```bash
make verify-skills                        # probes disk_size
make verify-skills FEATURE=audit_logging  # or any registered feature
make verify-skills-all                    # every feature reachable from --feature
```

A failure means either the doc drifted from the code or that feature is incomplete.
Both are worth knowing. `tests/test_skills_md.py` runs the same checks in CI, one
test per feature, so drift fails a build rather than waiting to be noticed.

Features that are wired a non-standard way are derived from repo data rather than
excused by name: an externally-verified feature is read from
`externally_verified_features`, a ROSANetwork feature is checked against
`rosa-network-config.yaml.j2`, and a variable a playbook consumes instead of a
template warns and names the file that reads it. Only a variable that appears
nowhere fails.

`disk_size` is the default probe because its feature id, CLI alias (`disk-size`) and
`var_map` variable (`root_volume_size`) are three different strings, and it is a
non-boolean on `ROSAMachinePool` — so every seam the skill warns about is
load-bearing there. A feature whose id, alias and variable are all the same string
(`fips`, `no_cni`) would still pass with `var_map` deleted entirely.
