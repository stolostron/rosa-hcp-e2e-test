# 4.22 Feature Testing: Spot Instances

| Field | Value |
|-------|-------|
| Feature ID | `spot_market_options` |
| CLI Flag | `--feature spot` |
| Category | Node Configuration |
| Phase | Day1 |
| Type | boolean |
| Mutable | No (the field is immutable; only `maxPrice` can change — see [Changing the bid later](#changing-the-bid-later)) |
| Requires Input | No (`spot_max_price` defaults to `on-demand`) |
| CRD Resource | `ROSAMachinePool` |
| K8s Field | `.spec.spotMarketOptions.maxPrice` |
| Min Version | 4.22 |
| Ansible Variable | `spot_instances` (enable), `spot_max_price` (bid cap) |

## Description

Runs the cluster's machine pool worker nodes on AWS Spot instances instead of
on-demand instances. Spot capacity costs substantially less, but AWS can reclaim
it at any time, so the nodes can disappear mid-run.

`maxPrice` is the maximum hourly bid in USD, or the sentinel `on-demand`, which
bids the on-demand price with no separate cap. `on-demand` is the default here
and the right choice for CI: a numeric bid below the live Spot price means the
node pool never gets capacity, and the cluster fails to provision for a reason
that has nothing to do with the code under test.

Added upstream in [cluster-api-provider-aws#6334](https://github.com/kubernetes-sigs/cluster-api-provider-aws/pull/6334)
(merged 2026-11-09, fixes [#6214](https://github.com/kubernetes-sigs/cluster-api-provider-aws/issues/6214)).

> **Until an MCE build ships a CAPA with this field, suite 21 reports this
> feature as WARN, not FAIL.** The API server prunes the unknown
> `spotMarketOptions` key from the applied ROSAMachinePool, verification finds
> nothing, and `tasks/verify_feature_rescue.yml` checks the live CRD schema,
> sees the field is absent, and classifies it as a platform limitation. The test
> starts genuinely passing with no edits once the CRD carries the field.

## Usage

### Spot at the on-demand price (default)

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature spot -e name_prefix=qe6
```

### Spot with a capped hourly bid

```bash
./run-test-suite.py 20-rosa-hcp-provision --feature spot \
  -e spot_max_price=0.5 \
  -e name_prefix=qe6
```

`spot_max_price` accepts a price greater than zero (`0.5`, `10`, `0.042`) or the
string `on-demand`. `0` and `0.0` are rejected, by the CRD pattern upstream and
by this suite's own pre-check.

### As part of the day1-combo group

```bash
./run-test-suite.py --scenario day1-combo -e openshift_version=4.22 -e name_prefix=qe6
```

## Template Rendering

When `spot_instances` is `true`, on the `ROSAMachinePool` document:

```yaml
spec:
  spotMarketOptions:
    maxPrice: "on-demand"     # or the value of spot_max_price
```

`maxPrice` is always written out rather than left to the CRD's default, so the
value verification compares against is the value the template asked for.

## Verification

`tasks/features/verify_spot_market_options.yml`, three layers:

1. **Input pre-check** — the requested `spot_max_price` matches the same pattern
   the CRD enforces (`^([1-9][0-9]*(\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*|on-demand)$`),
   so a typo fails immediately instead of 40 minutes later.
2. **CRD** — reads the cluster's `ROSAMachinePool`.
3. **OCM** — `GET /api/clusters_mgmt/v1/clusters/{id}/node_pools`, reading
   `aws_node_pool.spot_market_options.max_price`.
4. **AWS (boto3)** — `describe_instances` filtered on
   `tag:kubernetes.io/cluster/<cluster>=owned` and `instance-state-name=running`,
   counting instances whose `InstanceLifecycle` is `spot`.

Asserts:

- `.spec.spotMarketOptions.maxPrice` is defined on the `ROSAMachinePool` and
  equals the requested bid
- at least one OCM node pool reports `aws_node_pool.spot_market_options`; for a
  numeric bid, that one of them reports the matching `max_price`
- at least one running worker instance reports `InstanceLifecycle == spot`

Notes:

- The ROSA API stores **no** `max_price` for an on-demand-priced Spot pool, which
  is exactly what the sentinel means (see `NodePoolToRosaMachinePoolSpec` in
  `exp/utils/rosa_helper.go` upstream). So the OCM equality check only runs for a
  numeric bid; for `on-demand` it is enough that `spot_market_options` is present.
- `spot_market_options` is listed in `aws_dependent_features`, so if boto3 is
  unavailable the run is recorded as **degraded** — the CRD/OCM side alone cannot
  prove AWS actually launched Spot capacity. In CI a degraded run fails.

## Constraints

- **Immutable on/off.** A pool created with `spotMarketOptions` cannot drop it,
  and an on-demand pool cannot gain it. Switching requires replacing the
  MachinePool. This is why the registry marks the feature `mutable: false` and
  `applies_to: [create]`.
- **Not combinable with a capacity reservation.** Upstream rejects
  `spotMarketOptions` together with `capacityReservationID`. No
  `capacity_reservation` feature exists in this repo yet; add a
  `mutual_exclusions` pair when one does.

### Changing the bid later

`maxPrice` is the one part that can change after creation, and only in one
direction:

| Change | Supported |
| --- | --- |
| `on-demand` → a price (e.g. `0.5`) | Yes |
| One price → another (e.g. `0.5` → `0.4`) | Yes |
| A price → `on-demand` | **No** |

Removing `maxPrice` is treated the same as setting it back to `on-demand`, and is
refused by the ROSAMachinePool webhook. This Day-2 transition is **not** exercised
by this feature — it belongs with the machine pool suites (27/28) if it is added.

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- [Disk Size](disk-size.md) — the other `ROSAMachinePool` field verified the same way
- [Upstream: Creating ROSA MachinePools — Spot Instances](https://cluster-api-aws.sigs.k8s.io/topics/rosa/creating-rosa-machinepools)
- Feature Group: `day1-combo`
