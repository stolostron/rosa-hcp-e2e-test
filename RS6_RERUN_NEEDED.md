# RS6 Rerun Required

**Date:** October 16, 2026  
**Status:** Test stopped, needs to be rerun

## Summary

RS6 (day2-machinepool) test was started but stopped due to long provisioning time. The cluster (rs6-rosa-hcp) is ready and machine pools were created but test did not complete.

## Current State

- ✅ Cluster rs6-rosa-hcp: READY
- ⏳ Machine pools (rs6-mp): Created but not fully provisioned
- ❌ Test process: Stopped (not running)
- ❌ Verification stage: Not completed
- ❌ Deletion stage: Not started

## What Needs to Happen

1. **Resume or rerun rs6 test:**
   ```bash
   /run-v5-rc-tests day2-machinepool rs6 5.0.0-rc.6
   ```

2. **OR manually clean up and retry:**
   ```bash
   # Delete the partial rs6 resources
   oc delete rosacontrolplane rs6-rosa-hcp -n ns-rosa-hcp --force --grace-period=0
   
   # Rerun test
   /run-v5-rc-tests day2-machinepool rs6 5.0.0-rc.6
   ```

## Expected Behavior

When rerun, the test should:
1. Complete machine pool provisioning (10-15 min)
2. Verify 3 day2-machinepool features:
   - multi_zone_machinepool
   - heterogeneous_worker_nodes
   - machinepool_autoscaling
3. Delete cluster and resources
4. Update RC6_TEST_RESULTS.md with results

## Time Estimate

Full test run: 25-30 minutes

## Notes

- Cluster creation takes 15-20 min (longest part)
- Machine pool provisioning takes 5-10 min
- Verification/cleanup: 2-3 min

Start fresh if the partial cluster causes issues.
