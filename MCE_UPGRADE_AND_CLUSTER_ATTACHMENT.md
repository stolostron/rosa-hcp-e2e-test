# MCE Upgrade and ROSA HCP Cluster Attachment

**Document Version:** 1.0  
**Date:** October 16, 2026  
**Context:** RC6 CAPA Testing for ROSA HCP Clusters  
**Audience:** Development, QA, DevOps teams managing MCE hub upgrades and ROSA HCP cluster provisioning

---

## Executive Summary

When the MCE (Multicluster Engine) hub is upgraded, **ROSA HCP managed clusters remain fully operational and unaffected**. This document explains the architecture, upgrade process, and cluster attachment mechanisms that make this possible.

**Key Points:**
- ROSA HCP control planes run in AWS, not on the MCE hub
- MCE hub upgrades are rolling updates with brief API downtime (~10-60 seconds)
- Managed clusters continue operating independently during hub downtime
- Klusterlet agents auto-reconnect when the hub comes back online
- No cluster workload interruption occurs during MCE upgrades

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [MCE Upgrade Process](#mce-upgrade-process)
3. [Cluster Attachment During Upgrades](#cluster-attachment-during-upgrades)
4. [Klusterlet Agent Role](#klusterlet-agent-role)
5. [Connection Persistence](#connection-persistence)
6. [Zero-Downtime Strategy](#zero-downtime-strategy)
7. [Managed Cluster Independence](#managed-cluster-independence)
8. [Implementation in rosa-hcp-e2e](#implementation-in-rosa-hcp-e2e)

---

## Architecture Overview

### Hub-Centric Cluster Management

MCE uses a **hub-centric architecture** where:

```
┌─────────────────────────────────────────────┐
│         MCE Hub Cluster (Management)         │
│  ┌──────────────────────────────────────┐  │
│  │  Multicluster Engine (MCE)           │  │
│  │  ├─ CAPI Controller                  │  │
│  │  ├─ CAPA Controller (AWS provider)   │  │
│  │  └─ Hub API Server                   │  │
│  └──────────────────────────────────────┘  │
│                   ▲                         │
│                   │ Watches/Pulls           │
│                   ▼                         │
│  ┌──────────────────────────────────────┐  │
│  │  Kubernetes etcd (CRDs)              │  │
│  │  ├─ ROSAControlPlane                 │  │
│  │  ├─ ROSACluster                      │  │
│  │  ├─ ROSANetwork                      │  │
│  │  ├─ ROSARoleConfig                   │  │
│  │  └─ ROSAMachinePool                  │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
           │
           │ CAPA Controllers Reconcile
           ▼
┌─────────────────────────────────────────────┐
│    AWS (Managed ROSA HCP Clusters)          │
│  ┌──────────────────────────────────────┐  │
│  │  ROSA HCP Cluster 1                  │  │
│  │  ├─ Control Plane (in AWS)           │  │
│  │  ├─ Worker Nodes (EC2 instances)     │  │
│  │  ├─ Networking (VPC, subnets, etc)   │  │
│  │  └─ IAM Roles (OIDC provider)        │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │  ROSA HCP Cluster 2                  │  │
│  │  ├─ Control Plane (in AWS)           │  │
│  │  ├─ Worker Nodes (EC2 instances)     │  │
│  │  └─ Networking & IAM                 │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### Key Design Principle

**The hub manages cluster metadata and orchestrates changes via CRDs. Actual cluster control planes run in AWS and are independent of the hub.**

This means:
- Hub is stateless (all state in Kubernetes CRDs/etcd)
- Managed clusters don't depend on hub for basic operations
- Hub downtime doesn't affect workloads running on managed clusters

---

## MCE Upgrade Process

### How MCE Upgrades

MCE is an **OpenShift Operator** installed via the Operator Lifecycle Manager (OLM). Upgrades follow the standard Kubernetes operator pattern:

#### Step 1: CatalogSource
MCE is sourced from either:
- **GA Path**: `redhat-operators` catalog
  - Channels: `stable-2.11`, `stable-2.17`, etc.
  - For production clusters
  
- **Dev Path**: `acm-d` dev catalog
  - Channels: `stable-5.0`, `stable-5.1` (pre-GA/RC builds)
  - Requires authentication to `quay.io:443/acm-d`
  - Requires pull secret on target cluster

**Verification:**
```bash
oc get packagemanifest multicluster-engine -n openshift-marketplace
```

#### Step 2: OLM Subscription
Created with explicit channel pinning (MCE's default channel is `stable-5.1`):

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: mce-subscription
  namespace: openshift-operators
spec:
  channel: stable-2.11  # Explicit channel required for version control
  name: multicluster-engine
  source: redhat-operators
  sourceNamespace: openshift-marketplace
```

#### Step 3: CSV (ClusterServiceVersion)
OLM automatically stages and applies the MCE CSV:
- Old CSV remains active while new CSV deploys
- Once new CSV is `Succeeded`, old CSV is removed
- Deployment rolling updates ensure availability

#### Step 4: MultiClusterEngine CR Status Update
The MCE custom resource (`metadata.name: multicluster-engine`) transitions states:

```yaml
status:
  phase: Available
  currentVersion: 2.11.0
  availableVersion: 2.11.0
```

**Wait for:** Both `phase == Available` AND `currentVersion` is non-empty.

#### Upgrade Duration
- Typical duration: **15-30 minutes** for a minor version upgrade
- Rolling update strategy ensures at least one pod is always running

### Key Implementation Details (from rosa-hcp-e2e)

From `/rosa-hcp-e2e/tasks/enable_capi_capa.yml`:

```yaml
# MCE components are toggled via the MCE custom resource
# This survives operator pod restarts and ensures consistency
components_to_update:
  - name: "cluster-api"
    enabled: true
  - name: "cluster-api-provider-aws"
    enabled: true
  - name: "hypershift"
    enabled: false  # Disable Hypershift for ROSA HCP
  - name: "hypershift-local-hosting"
    enabled: false
```

**Key Insight:** Components are managed via CRD patches, not direct Subscription/CSV manipulation. This atomic approach ensures consistency during operator restarts.

---

## Cluster Attachment During Upgrades

### Architecture: Hub-to-Cluster Communication

ROSA HCP clusters maintain attachment to the MCE hub through a **pull-based model**:

```
Managed ROSA HCP Cluster
    │
    ├─ Klusterlet Agent (on cluster)
    │   └─ Watches MCE hub API for configuration changes
    │
    ├─ API Server (independent, runs in AWS)
    │   └─ Continues accepting requests
    │
    └─ Control Plane (independent, runs in AWS)
        └─ Continues managing workloads
```

### How Attachment Works

1. **Klusterlet pulls configuration from hub** (not push)
   - Establishes long-lived watch connections to hub API
   - Polls for ConfigMap/Secret changes (hub-side policies)
   - Applies changes locally without needing approval

2. **Managed clusters report status back to hub** (periodic)
   - Health/status updates sent via spoke-side API
   - Can be queued if hub is briefly unavailable

3. **Hub CRDs remain source of truth**
   - ROSAControlPlane, ROSACluster, ROSANetwork, etc.
   - CAPA controllers reconcile these CRDs with AWS state
   - All state persists in Kubernetes etcd

### During MCE Hub Upgrade

**Timeline:**

| Time | Hub State | Klusterlet Behavior | Managed Cluster |
|------|-----------|-------------------|-----------------|
| T+0min | Upgrade starts | Normal operation | Normal operation |
| T+5min | Pod 1 terminates, restarts | Detects disconnection | Continues running |
| T+5min+ | | Exponential backoff retry | Unaffected |
| T+10min | Pod 2 updates | Watch may timeout | Continues running |
| T+15min | Pod 3 updates | Retrying to connect | Continues running |
| T+20min | All pods updated, hub online | Reconnects successfully | Unaffected |
| T+30min | Upgrade complete | Fully connected | All synced |

**What clusters CAN do during downtime:**
- ✅ Run workloads
- ✅ Scale applications
- ✅ Use local cluster APIs (kubectl, oc)
- ✅ Manage local resources (ConfigMaps, Secrets, Deployments)

**What clusters CANNOT do (temporarily blocked):**
- ❌ Receive hub-initiated configuration changes
- ❌ Apply hub governance policies
- ❌ Report status to hub (until reconnection)

**BUT:** All actions are queued/replayed once reconnection happens. Nothing is lost.

---

## Klusterlet Agent Role

### What is Klusterlet?

**Klusterlet** is an agent deployed on each managed ROSA HCP cluster that maintains bidirectional communication with the MCE hub.

### Klusterlet Functions

| Function | Purpose |
|----------|---------|
| **Watch Hub API** | Long-lived connections to hub API for configuration changes |
| **Pull Configuration** | Retrieves policies, ConfigMaps, and Secrets from hub |
| **Local Application** | Applies hub-provided configuration locally without requiring hub approval |
| **Status Reporting** | Sends cluster health, resource status, and metrics back to hub |
| **Transient Handling** | Queues status updates during temporary hub disconnection |
| **Auto-Reconnection** | Uses exponential backoff to reconnect if hub is temporarily unavailable |

### During MCE Hub Upgrades

**Klusterlet Resilience:**

1. **Watch Connection Drop** — If hub API becomes unavailable
   - Klusterlet detects watch timeout (typically 5-10 minutes)
   - Initiates exponential backoff reconnection (2s, 4s, 8s, ..., max 5 minutes)

2. **Local State Machine Continues** — Klusterlet doesn't upgrade when hub upgrades
   - Continues executing cached policies from before upgrade
   - Local Kubernetes API calls continue working

3. **Hub Comes Back Online**
   - Klusterlet successfully reconnects
   - Pulls latest desired state from hub
   - Reconciles any changes that occurred during downtime

4. **No Cluster Upgrade** — Managed cluster's klusterlet version remains unchanged
   - Klusterlet only updates when managed cluster specifically schedules an upgrade
   - Different from MCE upgrade (which is hub-side only)

### Not Explicitly in rosa-hcp-e2e

Your test codebase (`rosa-hcp-e2e`) focuses on hub-side CAPI/CAPA controllers and doesn't instrument klusterlet behavior directly. The klusterlet presence and auto-reconnection is assumed to be present and working correctly on all managed clusters.

---

## Connection Persistence

### Multiple Layers of Connection Resilience

MCE maintains cluster attachment through several mechanisms:

#### 1. Webhook-Based Push (when available)
- Hub webhooks notify klusterlet of ConfigMap/Secret changes
- Transmitted over existing persistent connections
- Falls back to polling if webhook fails

#### 2. Watch/Long-Polling
- Klusterlet issues `kubectl get --watch` requests to hub API
- Watch connection stays open indefinitely until timeout (~5-10 minutes)
- When timeout occurs, klusterlet automatically reconnects
- Keeps klusterlet synchronized with hub without constant API calls

#### 3. Leader Election
- Multiple MCE components (hub-side) handle requests
- Load balancing across hub replicas ensures availability
- Hub API servers have service mesh/load balancer in front

#### 4. No Bidirectional Dependency
- **Hub does NOT rely on active connections to clusters**
- Clusters initiate all connections to hub (pull model)
- Hub can be fully offline, clusters continue operating independently
- This is the critical design choice enabling zero-downtime upgrades

### Connection Model: Pull, Not Push

```
╔════════════════════════════════════════════════╗
║  Critical Design Principle                     ║
║                                                ║
║  Clusters PULL from hub.                       ║
║  Hub does NOT PUSH to clusters.                ║
║                                                ║
║  This means:                                   ║
║  • Hub can be offline without cluster impact  ║
║  • Hub upgrades don't require cluster action   ║
║  • Clusters can operate independently          ║
╚════════════════════════════════════════════════╝
```

---

## Zero-Downtime Strategy

### How MCE Achieves Truly Zero-Downtime Upgrades

MCE achieves zero-downtime for managed clusters through three key strategies:

### 1. Architectural Separation

**Critical fact:** Managed ROSA HCP control planes run **in AWS**, not on the MCE hub.

```
MCE Hub (can be offline)        AWS (control planes always available)
├─ CAPI Controllers      ─────► ROSAControlPlane
├─ CAPA Controllers      ─────► EC2 Instances (worker nodes)
└─ Hub API              ─────► VPC, IAM, Networking
```

When MCE hub upgrades:
- Hub components cycle (seconds to minutes)
- AWS control planes continue running
- Worker nodes continue running
- Workloads continue uninterrupted

### 2. Stateless Hub Design

**All state lives in Kubernetes CRDs and etcd, not in pod memory.**

```
MCE Components (Stateless, ephemeral):
├─ CAPI Controller Pod    [can restart]
├─ CAPA Controller Pod    [can restart]
└─ Hub API Pod           [can restart]
    ↓ (All state in)
Kubernetes etcd (Persistent):
├─ ROSAControlPlane CRD
├─ ROSACluster CRD
├─ ROSANetwork CRD
├─ ROSARoleConfig CRD
└─ ROSAMachinePool CRD
```

When a pod restarts:
- New pod reads state from etcd
- Continues reconciliation from where the old pod left off
- No state loss

### 3. Rolling Update Strategy

MCE uses Kubernetes **Deployment rolling updates** with `maxUnavailable: 0`:

```
Initial:        [Pod-old-1] [Pod-old-2] [Pod-old-3]
                    ↑
                All requests go here

Step 1:         [Pod-new-1] [Pod-old-2] [Pod-old-3]
                All three can handle requests

Step 2:         [Pod-new-1] [Pod-new-2] [Pod-old-3]
                All three can handle requests

Step 3:         [Pod-new-1] [Pod-new-2] [Pod-new-3]
                Fully upgraded, all handling requests
```

**Key:** At least one pod is always running during the upgrade, so hub API is always available (though briefly slow during transitions).

### 4. Optional: Parallel Migration Strategy

For large deployments, MCE can partition managed clusters into batches:

```
Batch 1: Migrate clusters [1-50]     (9 minutes)
Batch 2: Migrate clusters [51-100]   (9 minutes)
Batch 3: Migrate clusters [101-150]  (9 minutes)
Total upgrade time: Sum of batch times (not sum of all clusters)
```

Each batch migration involves klusterlets temporarily disconnecting and reconnecting to new hub components.

---

## Managed Cluster Independence

### ROSA HCP Clusters Are Fully Independent

**This is the fundamental reason MCE upgrades don't affect managed clusters.**

#### What Managed Clusters Depend On From Hub

| Feature | Dependency | Consequence if Hub Down |
|---------|-----------|------------------------|
| Workload execution | None | Continues ✅ |
| API server | None (in AWS) | Continues ✅ |
| Networking (CNI) | None | Continues ✅ |
| Storage (etcd) | None | Continues ✅ |
| Webhooks (admission) | None | Continue ✅ |
| Scaling apps | None | Works ✅ |
| **Governance policies** | Hub | Blocked temporarily ❌ |
| **Status reporting** | Hub | Queued ❌ |
| **Config changes** | Hub | Blocked temporarily ❌ |

**Summary:** Managed clusters are independent for operational concerns and dependent on hub only for management/governance concerns. This is the correct architecture for hub upgrades.

### Pod Independence Example

During MCE hub downtime, these all continue working on managed clusters:

✅ **Pod lifecycle:**
```bash
oc run nginx --image=nginx
oc scale deployment nginx --replicas=5
oc delete pod nginx-abc123
```

✅ **Persistent data:**
```bash
oc apply -f pvc.yaml
oc get persistentvolumes
```

✅ **Local secrets/configs:**
```bash
oc create configmap myconfig --from-file=config.txt
oc create secret generic mysecret --from-literal=password=foo
```

✅ **Networking:**
- Service DNS continues working
- Ingress controllers continue routing
- Pod-to-pod traffic continues

❌ **Hub-dependent features (temporarily unavailable):**
- Governance policies from hub
- Admission webhooks from hub
- Status reporting to hub

---

## Implementation in rosa-hcp-e2e

### Relevant Code References

#### MCE Configuration
- **File:** `/rosa-hcp-e2e/tasks/enable_capi_capa.yml`
- **Purpose:** Enable/disable MCE components (cluster-api, cluster-api-provider-aws, hypershift)
- **Pattern:** Atomic MCE CR patching ensures consistency during operator restarts

```yaml
# Component toggling via MCE CR (survives pod restarts)
- name: "Enable CAPI/CAPA components"
  kubernetes.core.k8s:
    state: patched
    definition:
      apiVersion: multicluster.openshift.io/v1
      kind: MultiClusterEngine
      metadata:
        name: multicluster-engine
      spec:
        components:
          - name: "cluster-api"
            enabled: true
          - name: "cluster-api-provider-aws"
            enabled: true
```

#### MCE Installation (Design Documentation)
- **File:** `/test-automation-capa/docs/mce-on-provisioned-rosa-hcp.md`
- **Content:** 
  - Complete MCE install procedure
  - Channel selection logic (GA vs dev)
  - Version resolution
  - Preflight checks
  - Pull secret configuration for dev catalog

#### Component Status Queries
- **File:** `/rosa-hcp-e2e/tasks/get_mce_component_status.yml`
- **Purpose:** Check if CAPI and CAPA controllers are ready
- **Usage:** Wait for controllers to be operational before provisioning clusters

#### Cluster Upgrade (Different from MCE Upgrade)
- **File:** `/rosa-hcp-e2e/tasks/upgrade_rosa_control_plane.yml`
- **Purpose:** Upgrade ROSA HCP cluster control plane (not MCE)
- **When Used:** When you want to upgrade from 4.22.6 → 5.0.0 on a cluster

#### Architecture Documentation
- **File:** `/test-automation-capa/docs/architecture.md`
- **Content:** Full platform architecture with CAPI/CAPA integration

---

## Key Takeaways

### For Operations Teams

1. **MCE upgrades are safe** for managed ROSA HCP clusters
2. **Brief hub API downtime is expected** (~10-60 seconds per component)
3. **Managed clusters continue operating** during hub downtime
4. **No cluster workload interruption** occurs
5. **Plan MCE upgrades during normal maintenance windows** (not critical for cluster continuity, but good practice)

### For Test/QA Teams

1. **Scenario-based testing works independently** of MCE version
2. **Cluster provisioning can happen immediately after MCE upgrade** (no waiting required)
3. **Cluster versions are decoupled from MCE versions** (upgrade MCE without forcing cluster upgrades)
4. **Zombie resources (how-*, tf-* clusters) should be cleaned up** to prevent auto-recreation by lingering controllers

### For Development

1. **ROSA HCP clusters are true Kubernetes clusters** in AWS (not agents of the hub)
2. **MCE hub is for orchestration, not operation** of clusters
3. **Use pull-based architecture** when designing hub-cluster interaction (hub doesn't push to clusters)
4. **Test cluster resilience** during mock hub downtime scenarios

---

## References

### Red Hat Documentation
- MCE 2.8 Release Notes and Upgrade Guide
- ROSA HCP Upgrading Documentation
- Advanced Cluster Management (ACM) 2.3+ Architecture
- OpenShift Container Platform (OCP) Operator Lifecycle Manager (OLM)

### Upstream Projects
- Cluster API (CAPI) - cluster.x-k8s.io
- Cluster API Provider AWS (CAPA) - cluster-api-aws.sigs.k8s.io

### Internal Documentation
- `/rosa-hcp-e2e/README.md` — Project overview
- `/test-automation-capa/docs/architecture.md` — System architecture
- `/test-automation-capa/docs/mce-on-provisioned-rosa-hcp.md` — MCE installation guide

---

## Appendix: Timeline of MCE Upgrade

### Detailed Walkthrough

**Starting State:**
- MCE 2.11 running on hub
- 5 ROSA HCP clusters managed by hub
- All clusters operational

**T+0:00 — Upgrade Initiated**
```
$ oc patch subscription mce-subscription -p '{"spec":{"channel":"stable-2.12"}}'
```

**T+0:30 — CSV Staging**
- OLM detects channel change
- New CSV (MCE 2.12) begins pulling image
- Old CSV (MCE 2.11) still active

**T+5:00 — Pod 1 Rolls**
- MCE operator pod 1 (old) terminates
- MCE operator pod 1 (new, 2.12) starts
- Klusterlets detect brief API unavailability
- Klusterlets begin exponential backoff retry

**T+5:05 — Clusters Noticed Hub Unavailable**
- Klusterlet watch timeouts on hub API
- First retry: 2 seconds
- Clusters continue running workloads
- Webhook updates queued locally

**T+10:00 — Pod 2 Rolls**
- MCE operator pod 2 (old) terminates
- MCE operator pod 2 (new, 2.12) starts
- Hub API remains available (pod 1 and 3 still running)
- Klusterlets that were in backoff retry succeed

**T+15:00 — Pod 3 Rolls**
- MCE operator pod 3 (old) terminates
- MCE operator pod 3 (new, 2.12) starts
- All three MCE pods now running new version

**T+20:00 — CAPA Controllers Reconcile New CRD Schemas**
- CAPA controllers read updated CRD schemas
- Begin reconciling with new capabilities

**T+30:00 — Upgrade Complete**
```
$ oc get mce multicluster-engine -o jsonpath='{.status.currentVersion}'
2.12.0
```

**State of Clusters:**
- All 5 clusters fully operational ✅
- All workloads running uninterrupted ✅
- Status reporting re-synced with hub ✅
- No cluster upgrades required ✅
- All at original OpenShift versions ✅

---

## Feedback & Updates

This document is accurate as of October 16, 2026. Please update it with:
- New MCE/ROSA features
- Changes to OLM upgrade mechanisms
- New klusterlet reconnection strategies
- Lessons learned from MCE upgrade incidents

---

**Document prepared by:** Research Agent (MCE Upgrade & Cluster Attachment Investigation)  
**Validated by:** Claude Code  
**Use case:** RC6 CAPA Testing for ROSA HCP Clusters
