# 4.22 Feature Testing: Spot Market Options

| Field | Value |
|-------|-------|
| Feature ID | `spot_market_options` |
| CLI Flag | `--feature spot` |
| Category | Node Configuration |
| Phase | Day1 |
| Type | string |
| Mutable | No |
| Requires Input | No |
| CRD Resource | `ROSAMachinePool` |
| K8s Field | `.spec.spotMarketOptions` |
| Min Version | 4.22 |
| Ansible Variable | `spot_max_price` |

## Description

Runs the machine pool's nodes on AWS Spot instances, which cost less than on-demand
instances but can be reclaimed by AWS at any time. `maxPrice` caps the hourly bid in
USD, or the string `"on-demand"` bids the on-demand price with no separate cap —
you pay no more than on-demand while still benefiting from Spot pricing.

A numeric price must be greater than zero, so `"0"` and `"0.0"` are rejected by the
CRD. Setting `maxPrice` below the current Spot price means the node pool will not
get capacity, which presents as a pool that never becomes ready rather than as an
explicit error.

We test it because it is a cost-control feature whose two representations disagree
(see Verification), so a regression in the conversion layer would silently produce a
pool that is not actually on Spot — or one whose bid cap was dropped.

- Upstream PR: <https://github.com/kubernetes-sigs/cluster-api-provider-aws/pull/6334>
- Upstream docs: <https://cluster-api-aws.sigs.k8s.io/topics/rosa/creating-rosa-machinepools>

## Usage

```bash
# Bid the on-demand price with no separate cap (the CI default)
./run-test-suite.py 20-rosa-hcp-provision --feature spot -e name_prefix=qe6

# Cap the hourly bid instead
./run-test-suite.py 20-rosa-hcp-provision --feature spot \
  -e spot_max_price=0.5 -e name_prefix=qe6
```

## Template Rendering

When `spot_max_price` is set, on the **ROSAMachinePool** document:

```yaml
spec:
  spotMarketOptions:
    maxPrice: "on-demand"
```

`maxPrice` is emitted explicitly rather than rendering `spotMarketOptions: {}` and
letting the API server apply its default, so verification compares against a value
this repo chose.

## Verification

> **The CRD and OCM deliberately disagree about the default**, and the check is
> built around that. `exp/utils/rosa_helper.go` upstream: *"The ROSA API stores no
> max_price for an on-demand-priced spot pool, which is exactly what the sentinel
> means."* So `maxPrice: "on-demand"` on the CRD corresponds to a
> `spot_market_options` object in OCM with **no `max_price` key at all**. Asserting
> `max_price == "on-demand"` would fail against a correctly configured cluster.

Asserts:

- the requested value matches the CRD's pattern
  `^([1-9][0-9]*(\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*|on-demand)$`
- `.spec.spotMarketOptions.maxPrice` on the ROSAMachinePool equals the requested value
- OCM returns this cluster's own node pool, matched on `.spec.nodePoolName`, and its
  `aws_node_pool` carries a `spot_market_options` key — presence of the key, not its
  contents, is what marks the pool as Spot
- when the request was `on-demand`: OCM stores **no** `max_price`
- when the request was numeric: OCM's `max_price` equals the requested bid

No AWS/boto3 check: OCM already proves the ROSA service applied the setting, and the
pool's EC2 instances may not exist yet when suite 21 runs.

## Constraints

From the upstream webhook (`exp/webhooks/rosamachinepool_webhook.go`):

- **Cannot be added or removed after the machine pool is created.** The registry
  records `mutable: false` / `applies_to: [create]` for this reason.
- **A numeric `maxPrice` may be raised or lowered Day-2, but never set back to
  `"on-demand"`** once a price has been set. The registry's single `mutable:`
  boolean cannot express that partial mutability, hence Day-1 only; a Day-2
  transition suite would be a follow-up.
- **Mutually exclusive with `.spec.capacityReservationID`** — the webhook rejects
  both together. This is not a `mutual_exclusions` registry entry because
  `capacityReservationID` is not a registered feature in this repo; add one if it
  ever becomes one.

## Related

- [Automated Feature Verification](automated-feature-verification.md)
- [Disk Size](disk-size.md) — the other ROSAMachinePool Day-1 field
