#!/bin/bash
# Cleanup orphaned IAM roles from ROSA HCP test runs
#
# Each test run creates 11 IAM roles + 1 OIDC provider per NAME_PREFIX.
# If builds fail or are cancelled before the Delete stage, these accumulate.
#
# Usage:
#   # Dry run (list only):
#   ./scripts/cleanup_orphaned_iam_roles.sh
#
#   # Actually delete:
#   ./scripts/cleanup_orphaned_iam_roles.sh --delete
#
# Requires: AWS CLI configured with credentials for the test account

set -euo pipefail

DELETE_MODE=false
if [[ "${1:-}" == "--delete" ]]; then
    DELETE_MODE=true
    echo "*** DELETE MODE - will remove roles ***"
else
    echo "*** DRY RUN - listing only (use --delete to remove) ***"
fi
echo ""

REGION="${AWS_REGION:-us-west-2}"

# Patterns that match ROSA HCP test roles
ACCOUNT_ROLE_PATTERNS=(
    "HCP-ROSA-Installer-Role"
    "HCP-ROSA-Support-Role"
    "HCP-ROSA-Worker-Role"
)

OPERATOR_ROLE_PATTERNS=(
    "kube-system-control-plane-operator"
    "openshift-image-registry-installer-cloud-credentials"
    "openshift-ingress-operator-cloud-credentials"
    "kube-system-kms-provider"
    "kube-system-kube-controller-manager"
    "openshift-cloud-network-config-controller-cloud-credentials"
    "kube-system-capa-controller-manager"
    "openshift-cluster-csi-drivers-ebs-cloud-credentials"
)

echo "Scanning IAM roles..."
ALL_ROLES=$(aws iam list-roles --query 'Roles[].RoleName' --output text | tr '\t' '\n')

MATCHING_ROLES=()
for role in $ALL_ROLES; do
    for pattern in "${ACCOUNT_ROLE_PATTERNS[@]}" "${OPERATOR_ROLE_PATTERNS[@]}"; do
        if [[ "$role" == *"$pattern"* ]]; then
            MATCHING_ROLES+=("$role")
            break
        fi
    done
done

if [[ ${#MATCHING_ROLES[@]} -eq 0 ]]; then
    echo "No orphaned ROSA test roles found."
    exit 0
fi

# Group by prefix
declare -A PREFIXES
for role in "${MATCHING_ROLES[@]}"; do
    # Extract prefix (everything before the first known pattern)
    for pattern in "${ACCOUNT_ROLE_PATTERNS[@]}" "${OPERATOR_ROLE_PATTERNS[@]}"; do
        if [[ "$role" == *"$pattern"* ]]; then
            prefix="${role%%"-$pattern"*}"
            # Handle operator roles with different separator
            if [[ "$prefix" == "$role" ]]; then
                prefix="${role%%-kube-system-*}"
                if [[ "$prefix" == "$role" ]]; then
                    prefix="${role%%-openshift-*}"
                fi
            fi
            PREFIXES["$prefix"]=1
            break
        fi
    done
done

echo ""
echo "Found ${#MATCHING_ROLES[@]} ROSA test roles across ${#PREFIXES[@]} prefix(es):"
echo ""

for prefix in $(echo "${!PREFIXES[@]}" | tr ' ' '\n' | sort); do
    echo "  Prefix: $prefix"
    count=0
    for role in "${MATCHING_ROLES[@]}"; do
        if [[ "$role" == "$prefix"* ]]; then
            echo "    - $role"
            count=$((count + 1))
        fi
    done
    echo "    ($count roles)"
    echo ""
done

echo "Total: ${#MATCHING_ROLES[@]} roles"
echo ""

# Check for OIDC providers too
echo "Scanning OIDC providers..."
OIDC_PROVIDERS=$(aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text 2>/dev/null | tr '\t' '\n')
ROSA_OIDC=()
for arn in $OIDC_PROVIDERS; do
    if [[ "$arn" == *"oidc.os1.devshift.org"* ]]; then
        ROSA_OIDC+=("$arn")
    fi
done

if [[ ${#ROSA_OIDC[@]} -gt 0 ]]; then
    echo "Found ${#ROSA_OIDC[@]} ROSA OIDC provider(s):"
    for arn in "${ROSA_OIDC[@]}"; do
        echo "  - $arn"
    done
    echo ""
fi

if [[ "$DELETE_MODE" != true ]]; then
    echo "To delete these roles, run:"
    echo "  $0 --delete"
    exit 0
fi

echo "Deleting roles..."
DELETED=0
FAILED=0

for role in "${MATCHING_ROLES[@]}"; do
    echo -n "  Deleting $role ... "

    # First, detach all managed policies
    POLICIES=$(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null | tr '\t' '\n')
    for policy_arn in $POLICIES; do
        if [[ -n "$policy_arn" ]]; then
            aws iam detach-role-policy --role-name "$role" --policy-arn "$policy_arn" 2>/dev/null || true
        fi
    done

    # Delete inline policies
    INLINE=$(aws iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text 2>/dev/null | tr '\t' '\n')
    for policy_name in $INLINE; do
        if [[ -n "$policy_name" ]]; then
            aws iam delete-role-policy --role-name "$role" --policy-name "$policy_name" 2>/dev/null || true
        fi
    done

    # Delete instance profiles
    PROFILES=$(aws iam list-instance-profiles-for-role --role-name "$role" --query 'InstanceProfiles[].InstanceProfileName' --output text 2>/dev/null | tr '\t' '\n')
    for profile in $PROFILES; do
        if [[ -n "$profile" ]]; then
            aws iam remove-role-from-instance-profile --role-name "$role" --instance-profile-name "$profile" 2>/dev/null || true
        fi
    done

    # Delete the role
    if aws iam delete-role --role-name "$role" 2>/dev/null; then
        echo "OK"
        DELETED=$((DELETED + 1))
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
    fi
done

# Delete OIDC providers
for arn in "${ROSA_OIDC[@]}"; do
    echo -n "  Deleting OIDC $arn ... "
    if aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$arn" 2>/dev/null; then
        echo "OK"
        DELETED=$((DELETED + 1))
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "Done: $DELETED deleted, $FAILED failed"
