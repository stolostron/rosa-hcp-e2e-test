# Variants and reference implementations

## 1. Features that do not fit the standard shape

**Feature with its own verification playbook** (`type: action`, `applies_to: [verify]`).
`break_glass_credentials` is the model: it has `playbook: playbooks/verify_break_glass_credentials.yml`
in the registry, and is listed in `externally_verified_features` in
`tasks/features/setup_feature_verification.yml` so suite 21 drops it instead of
rejecting it as unknown. Add both, and give the feature its own task files under
`tasks/` (see `break_glass_preflight.yml`, `break_glass_create_credential.yml`,
`break_glass_diagnose_403.yml`). Such a feature has no `crd_field_map` entry and no
`tasks/features/verify_<id>.yml` by design — it is the one `cli_features` entry that
is expected to fail the standard structural checks.

**Feature needing an AWS resource created during provisioning.**
`security_groups` is the model: `tasks/create_security_group.yml` reads the VPC id
from the ROSANetwork mid-provision, validates it against `^vpc-[a-f0-9]+$`, creates
the group and appends its id to `additional_security_groups`. Such a feature is
`requires_input: false` even though it has a value, because the caller cannot supply
it before the VPC exists — say so in a comment next to the registry entry.

**Feature the provisioning playbook consumes, with no template conditional.**
Step 3 assumes the `var_map` variable is read by a Jinja `{% if %}` in the two
control-plane templates. For some features it is read by
`tasks/provision_rosa_hcp_with_automation.yml` instead, and never appears in a
template at all:

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

## 2. Reference implementations

There is no single canonical feature; pick the one whose shape matches yours and
read all four of its layers before writing anything.

| If your feature is… | Read | Why |
|---|---|---|
| A plain boolean on ROSAControlPlane | `no_cni` — `verify_no_cni.yml`, `docs/features/no-cni.md`, `tests/…::TestNoCNI` | The simplest complete example of all four layers |
| On ROSAMachinePool | `disk_size` — `verify_disk_size.yml`, `docs/features/disk-size.md` | The `GET /clusters/{id}/node_pools` cross-check, and a CRD assert that is unconditional rather than an OCM fallback |
| Requiring user input | `audit_logging` — registry `required_vars_any_of`, `verify_audit_logging.yml` | Alternative input groups, and the "no input ⇒ no rendered block ⇒ failure 40 minutes later" comment that explains why it is declared |
| Needing an AWS resource first | `security_groups` — `tasks/create_security_group.yml`, `verify_security_groups.yml` | Mid-provision resource creation feeding back into template vars |
| Pulling in another feature | `byon` (→ `private_network`), `fips` (→ `etcd_kms`) | `dependencies` and the render tests that prove the dependency actually lands |
| Verified by its own playbook | `break_glass_credentials` — `playbooks/verify_break_glass_credentials.yml` | `playbook:` + `externally_verified_features`, §1 above |
| A lifecycle operation | `control_plane_upgrade`, `machine_pool_upgrade`, `cluster_delete` | `type: action`, `wait_*` gating, `destructive: true`, and their own suites (25/26/30) |

---

## 3. Lessons worth keeping

**The request can describe the API wrong.** A past feature request named the wrong
resource *and* the wrong field name; the merged CRD disagreed on both. Had it been
built from the description, every layer would have been wrong and the test would
have "passed" by asserting nothing. Step 0 in `intake.md` exists because of this.

**OCM and the CRD can disagree about a sentinel value.** The CRD may store an
explicit marker where the ROSA API stores nothing at all for the same state. A naive
equality cross-check then fails against a correctly configured cluster. The
conversion helper (`exp/utils/rosa_helper.go` upstream) is where that asymmetry is
visible — `intake.md` §1.5.

**ansible-lint catches bugs the unit tests cannot.** The two Jinja traps in
`gotchas.md` (`['items']` on a possibly-empty dict, and `map(attribute=…, default=…)`)
both produce checks that pass on a cluster where the feature was never configured.
Unit tests do not reach the verification task's Jinja; ansible-lint and the fixture
playbook in `validation.md` are what prove the negative case fails.

**Joining a feature group can move that group's version floor.** Adding one 4.22
feature to a group that ran on 4.19 is a real side effect on users, not a test
detail. Flag it rather than burying it in a renamed test.
