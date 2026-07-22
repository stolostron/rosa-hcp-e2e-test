#!/usr/bin/env bash
# Check which feature fields actually exist in the installed ROSA CRDs
# Usage:
#   ./scripts/check_crd_feature_support.sh                    # interactive output
#   ./scripts/check_crd_feature_support.sh --json              # JSON output for report
#   ./scripts/check_crd_feature_support.sh --kubeconfig PATH   # use specific kubeconfig

set -euo pipefail

KUBECONFIG_FLAG=""
JSON_MODE=false
ENV_LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig) KUBECONFIG_FLAG="--kubeconfig=$2"; shift 2 ;;
    --json) JSON_MODE=true; shift ;;
    --label) ENV_LABEL="$2"; shift 2 ;;
    *) shift ;;
  esac
done

OC="oc $KUBECONFIG_FLAG"

RCP_CRD="rosacontrolplanes.controlplane.cluster.x-k8s.io"
RMP_CRD="rosamachinepools.infrastructure.cluster.x-k8s.io"

header() { printf "\n\033[1;36m=== %s ===\033[0m\n" "$1"; }
ok()     { printf "  \033[1;32m%-30s YES\033[0m\n" "$1"; }
fail()   { printf "  \033[1;31m%-30s NO\033[0m\n" "$1"; }

RESULTS_KEYS=()
RESULTS_VALS=()

check_field() {
  local crd="$1" path="$2" label="$3"
  local jq_path
  jq_path=$(echo "$path" | sed 's/\./\.properties\./g' | sed 's/^\.properties\.//')

  local result
  result=$($OC get crd "$crd" -o json 2>/dev/null \
    | jq -r ".spec.versions[] | select(.served==true) | .schema.openAPIV3Schema.properties.spec.properties.${jq_path} // empty" 2>/dev/null)

  if [[ -n "$result" && "$result" != "null" ]]; then
    $JSON_MODE || ok "$label"
    RESULTS_KEYS+=("$label")
    RESULTS_VALS+=("YES")
    return 0
  else
    $JSON_MODE || fail "$label"
    RESULTS_KEYS+=("$label")
    RESULTS_VALS+=("NO")
    return 1
  fi
}

HUB_URL=$($OC whoami --show-server 2>/dev/null || echo "unknown")
OCP_VERSION=$($OC get clusterversion version -o jsonpath='{.status.desired.version}' 2>/dev/null || echo "unknown")
K8S_VERSION=$($OC version -o json 2>/dev/null | jq -r '.serverVersion.gitVersion // "unknown"' 2>/dev/null || echo "unknown")
PLATFORM=$($OC get infrastructure cluster -o jsonpath='{.status.platform}' 2>/dev/null || echo "unknown")
ACM_VERSION=$($OC get csv -n ocm -o json 2>/dev/null | jq -r '.items[] | select(.metadata.name | startswith("advanced-cluster-management")) | .spec.version' 2>/dev/null || echo "unknown")
MCE_VERSION=$($OC get csv -n multicluster-engine -o json 2>/dev/null | jq -r '.items[] | select(.metadata.name | startswith("multicluster-engine")) | .spec.version' 2>/dev/null || echo "unknown")
CAPA_IMAGE=$($OC get deploy capa-controller-manager -n multicluster-engine -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
CRD_API=$($OC get crd "$RCP_CRD" -o json 2>/dev/null | jq -r '[.spec.versions[] | select(.served==true) | .name] | join(", ")' 2>/dev/null || echo "NOT FOUND")
CHECK_DATE=$(date +%Y-%m-%d)

RCP_FIELDS=$($OC get crd "$RCP_CRD" -o json 2>/dev/null \
  | jq -r '.spec.versions[] | select(.served==true) | .schema.openAPIV3Schema.properties.spec.properties | keys | join(", ")' 2>/dev/null || echo "none")
RMP_FIELDS=$($OC get crd "$RMP_CRD" -o json 2>/dev/null \
  | jq -r '.spec.versions[] | select(.served==true) | .schema.openAPIV3Schema.properties.spec.properties | keys | join(", ")' 2>/dev/null || echo "none")

if ! $JSON_MODE; then
  header "Environment"
  printf "  %-25s %s\n" "Hub URL:" "$HUB_URL"
  printf "  %-25s %s\n" "OCP Version:" "$OCP_VERSION"
  printf "  %-25s %s\n" "Kubernetes:" "$K8S_VERSION"
  printf "  %-25s %s\n" "Platform:" "$PLATFORM"
  printf "  %-25s %s\n" "ACM Version:" "$ACM_VERSION"
  printf "  %-25s %s\n" "MCE Version:" "$MCE_VERSION"
  printf "  %-25s %s\n" "CAPA Image:" "$CAPA_IMAGE"
  printf "  %-25s %s\n" "CRD API Version:" "$CRD_API"
  printf "  %-25s %s\n" "Date:" "$CHECK_DATE"
fi

if ! $JSON_MODE; then
  header "CRD Versions Installed"
  for crd in "$RCP_CRD" "$RMP_CRD"; do
    versions=$($OC get crd "$crd" -o json 2>/dev/null \
      | jq -r '[.spec.versions[] | select(.served==true) | .name] | join(", ")' 2>/dev/null || echo "NOT FOUND")
    printf "  %-55s %s\n" "$crd" "$versions"
  done
fi

$JSON_MODE || header "ROSAControlPlane Feature Fields"
PASS=0; TOTAL=0
declare -a RCP_FEATURES=(
  "autoscaler.expanders|autoscaler (expanders)"
  "userAgent|user_agent"
  "clusterRegistryConfig|image_registry"
  "network.networkType|no_cni (networkType)"
  "enableExternalAuthProviders|external_oidc"
  "etcdEncryptionKMSARN|etcd_kms"
  "fips|fips"
  "auditLogRoleARN|audit_logging (auditLogRoleARN)"
  "cloudWatchlogForwarder|audit_logging (cloudWatch)"
  "additionalTags|additionalTags"
  "domainPrefix|domainPrefix"
  "channelGroup|channelGroup"
  "additionalSecurityGroups|security_groups (on RCP)"
  "proxy|http_proxy"
  "endpointAccess|private_network"
)

for entry in "${RCP_FEATURES[@]}"; do
  field="${entry%%|*}"
  label="${entry##*|}"
  TOTAL=$((TOTAL + 1))
  if check_field "$RCP_CRD" "$field" "$label"; then
    PASS=$((PASS + 1))
  fi
done
$JSON_MODE || printf "\n  ROSAControlPlane: %d/%d fields found\n" "$PASS" "$TOTAL"
RCP_SCORE="$PASS/$TOTAL"

$JSON_MODE || header "ROSAMachinePool Feature Fields"
PASS=0; TOTAL=0
declare -a RMP_FEATURES=(
  "rootVolume|disk_size (rootVolume)"
  "rootVolume.size|disk_size (rootVolume.size)"
  "volumeSize|disk_size (volumeSize)"
  "updateConfig|parallel_upgrade (updateConfig)"
  "updateConfig.rollingUpdate|parallel_upgrade (rollingUpdate)"
  "additionalSecurityGroups|security_groups"
  "availabilityZone|availabilityZone"
  "instanceType|instanceType"
  "nodePoolName|nodePoolName"
)

for entry in "${RMP_FEATURES[@]}"; do
  field="${entry%%|*}"
  label="${entry##*|}"
  TOTAL=$((TOTAL + 1))
  if check_field "$RMP_CRD" "$field" "$label"; then
    PASS=$((PASS + 1))
  fi
done
$JSON_MODE || printf "\n  ROSAMachinePool: %d/%d fields found\n" "$PASS" "$TOTAL"
RMP_SCORE="$PASS/$TOTAL"

if ! $JSON_MODE; then
  header "Full CRD Spec Field Dump (top-level)"
  printf "\n  ROSAControlPlane spec fields:\n"
  echo "$RCP_FIELDS" | tr ', ' '\n' | sed '/^$/d' | sed 's/^/    /'

  printf "\n  ROSAMachinePool spec fields:\n"
  echo "$RMP_FIELDS" | tr ', ' '\n' | sed '/^$/d' | sed 's/^/    /'

  header "Summary"
  echo "  ROSAControlPlane: $RCP_SCORE"
  echo "  ROSAMachinePool:  $RMP_SCORE"
  echo ""
  echo "  To save JSON for the report: ./scripts/check_crd_feature_support.sh --json"
fi

if $JSON_MODE; then
  ENV_LABEL="${ENV_LABEL:-$HUB_URL}"
  cat <<ENDJSON
{
  "label": "$ENV_LABEL",
  "hub_url": "$HUB_URL",
  "ocp_version": "$OCP_VERSION",
  "kubernetes": "$K8S_VERSION",
  "platform": "$PLATFORM",
  "acm_version": "$ACM_VERSION",
  "mce_version": "$MCE_VERSION",
  "capa_image": "$CAPA_IMAGE",
  "crd_api_version": "$CRD_API",
  "date": "$CHECK_DATE",
  "rcp_score": "$RCP_SCORE",
  "rmp_score": "$RMP_SCORE",
  "rcp_all_fields": "$RCP_FIELDS",
  "rmp_all_fields": "$RMP_FIELDS",
  "features": {
$(first=true; for i in "${!RESULTS_KEYS[@]}"; do
  $first || echo ","
  printf '    "%s": "%s"' "${RESULTS_KEYS[$i]}" "${RESULTS_VALS[$i]}"
  first=false
done)
  }
}
ENDJSON
fi
