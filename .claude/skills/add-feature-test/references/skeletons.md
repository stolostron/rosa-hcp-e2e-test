# Copy-paste skeletons

Blocks for Steps 1, 3, 6 and 9. Replace `my_feature` / `my-feature` / `myCrdField` /
`my_ansible_var` with the confirmed values from the intake form.

---

## 1. Registry entry

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

---

## 2. Template conditional

```jinja
{% if my_ansible_var is defined and my_ansible_var | bool %}
  myCrdField:
    someKey: "{{ my_sub_var | default('default-value') }}"
{% endif %}
```

For non-boolean features, **test for definedness, not truthiness**:

```jinja
{% if my_ansible_var is defined and my_ansible_var is not none
      and my_ansible_var != '' %}
  myCrdField: {{ my_ansible_var }}
{% endif %}
```

The empty-input rule this encodes: render whenever the user supplied a value,
and skip only `undefined`, `none` and the empty string. For a `list` or
`key_value` feature add `and my_ansible_var | length > 0`, since an empty
collection means "nothing requested" there too.

> **Why not `and my_ansible_var` on its own.** A bare truthiness test is what
> `etcd_encryption_kms_arn` uses, and it is fine for an ARN — but **Jinja counts
> `0` as false**. Copy that pattern to a numeric feature whose valid domain
> includes zero and `-e my_var=0` renders nothing at all: the cluster provisions
> with the default instead of the requested value, and verification reports the
> field missing rather than wrong. No feature registered today declares `0` as
> valid, so this is a trap for the next numeric one, not a current bug.

Quote values the CRD types as strings — an unquoted `0.5` renders as a float and the
API server rejects it.

---

## 3. Verification task

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

    # A failed lookup is NOT the same as boto3 being absent, and the report does
    # not currently distinguish them -- `aws_unverified_features` is derived from
    # `boto3_check.rc` (is boto3 importable at all), so a lookup that fails on a
    # machine where boto3 *is* installed leaves environment.degraded false and the
    # feature counts as a full PASS with its AWS side unchecked. Until the report
    # grows a per-feature signal, say so loudly rather than quietly.
    - name: Skip AWS check (boto3 failed)
      ansible.builtin.debug:
        msg: >-
          WARN: boto3 lookup failed (rc={{ boto3_my_feature_check.rc }}) —
          my feature verified via CRD/OCM only, AWS side NOT checked
      when: boto3_my_feature_check.rc != 0

    - ansible.builtin.set_fact:
        features_passed: "{{ features_passed | int + 1 }}"
  rescue:
    - ansible.builtin.include_tasks: "{{ playbook_dir }}/../tasks/verify_feature_rescue.yml"
      vars:
        feature_id: my_feature
        fail_detail: "my feature not present on ROSAControlPlane"
```

For a **ROSAMachinePool** feature, replace **both** the OCM assert *and* the CRD
fallback above with the block below. Replacing only the OCM assert is a trap: the
fallback asserts `rcp.spec.myCrdField` on the **ROSAControlPlane**, so with OCM
reachable the machine-pool field is never checked at all, and with OCM unreachable
it looks for the field on the wrong resource and fails against a correctly
configured cluster.

The CRD assert is **unconditional** here — for a machine-pool feature the CRD is the
primary evidence and OCM is the cross-check, which is the reverse of the
ROSAControlPlane shape above:

```yaml
    - name: Assert myCrdField via CRD
      ansible.builtin.assert:
        that:
          - rmp.spec.myCrdField is defined
          - rmp.spec.myCrdField == expected_value
        fail_msg: >-
          FAIL: CRD myCrdField is
          {{ rmp.spec.myCrdField | default('undefined') }}, expected {{ expected_value }}
        success_msg: "PASS: CRD confirms myCrdField={{ expected_value }}"

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
          # The request succeeded. Without this, a non-JSON error body leaves
          # .json undefined, and a `json is defined` guard would skip the whole
          # assert while the block still counts the feature as passed.
          - ocm_my_node_pools.status | default(0) == 200
          # The cluster's OWN pool was found, not just any pool.
          - target_pool | length == 1
          # ...and it carries the requested value, not merely the key.
          - target_pool[0].aws_node_pool.my_field is defined
          - target_pool[0].aws_node_pool.my_field == expected_value
        fail_msg: >-
          FAIL: OCM node pool '{{ pool_name }}' does not report
          my_field={{ expected_value }}
          (HTTP {{ ocm_my_node_pools.status | default('none') }},
          {{ pools | length }} pool(s) returned)
        success_msg: "PASS: OCM node pool confirms my_field={{ expected_value }}"
      vars:
        # .get(), NOT ['items'] — see gotchas.md.
        pools: "{{ (ocm_my_node_pools.json | default({})).get('items', []) }}"
        # The OCM node pool id comes from .spec.nodePoolName, NOT metadata.name --
        # the templates set nodePoolName to a derived "<prefix>-np" string.
        pool_name: "{{ rmp.spec.nodePoolName | default(rmp.metadata.name) }}"
        target_pool: "{{ pools | selectattr('id', 'equalto', pool_name) | list }}"
      # No `json is defined` guard: when OCM is available this assert must run,
      # and the status check above is what reports a failed request.
      when:
        - ocm_available
        - ocm_my_node_pools is defined
```

Three things in that assert are easy to get wrong, and all three produce a check
that passes against a cluster where the feature was never applied:

- **Assert the status.** `failed_when: false` on the query means a failed request
  is not an error; nothing else notices unless you look at `.status`.
- **Select the cluster's own pool.** `pools | selectattr('aws_node_pool.my_field',
  'defined')` is satisfied by *any* pool in the account's cluster — including one
  that has nothing to do with the machine pool you are verifying. Match the pool
  `id` against **`rmp.spec.nodePoolName`** — that is what becomes the OCM node pool
  id. It is *not* `rmp.metadata.name`: the templates set `nodePoolName` to a derived
  `<prefix>-np` string, so matching on the Kubernetes object name finds nothing and
  the assert fails on a correctly configured cluster.
- **Compare the value.** `is defined` only proves OCM knows the key exists. A pool
  configured with the wrong value passes a definedness check.

> `verify_disk_size.yml` is cited elsewhere as the model for machine-pool features
> and is worth reading for its structure, but prefer the assert above: that file
> indexes `['items'][0]` rather than selecting by name. `verify_default_autoscaling.yml`
> is the better model for the assert itself.

---

## 4. Feature doc

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

The header-table rows marked `CLI Flag`, `CRD Resource`, `K8s Field` and
`Ansible Variable` are checked against the registry by
`make verify-skills FEATURE=my_feature` — keep them exact.
