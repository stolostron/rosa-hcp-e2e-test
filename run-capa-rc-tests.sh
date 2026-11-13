#!/bin/bash
#
# Interactive wrapper for /run-capa-rc-tests skill
# Prompts for scenario, prefix, and version if not provided via command line
#

set -e

# Color codes for output
BLUE='\033[94m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
ENDC='\033[0m'

# Parse command-line arguments
SCENARIO=""
PREFIX=""
VERSION=""
CHANNEL_GROUP=""
KEEP_CLUSTER=false
DRY_RUN=false

# Check if --help requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: /run-capa-rc-tests [SCENARIO] [PREFIX] [VERSION] [--keep-cluster] [--dry-run]"
  echo ""
  echo "Interactive mode (prompts for inputs):"
  echo "  /run-capa-rc-tests"
  echo ""
  echo "Command-line mode (all arguments provided):"
  echo "  /run-capa-rc-tests day1-basic rs1 5.0.0-rc.6"
  echo ""
  echo "Keep cluster for debugging:"
  echo "  /run-capa-rc-tests day1-basic rs1 5.0.0-rc.6 --keep-cluster"
  echo ""
  echo "Validate configuration without running test:"
  echo "  /run-capa-rc-tests day1-basic rs1 5.0.0-rc.6 --dry-run"
  exit 0
fi

# Parse positional arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-cluster)
      KEEP_CLUSTER=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --scenario)
      SCENARIO="$2"
      shift 2
      ;;
    --prefix)
      PREFIX="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --channel-group)
      CHANNEL_GROUP="$2"
      shift 2
      ;;
    --*)
      echo "Unknown flag: $1" >&2
      exit 1
      ;;
    *)
      if [ -z "$SCENARIO" ]; then
        SCENARIO="$1"
      elif [ -z "$PREFIX" ]; then
        PREFIX="$1"
      elif [ -z "$VERSION" ]; then
        VERSION="$1"
      elif [ -z "$CHANNEL_GROUP" ]; then
        CHANNEL_GROUP="$1"
      fi
      shift
      ;;
  esac
done

# Function to prompt for scenario
prompt_scenario() {
  echo ""
  echo -e "${BLUE}? Which scenario?${ENDC}"
  PS3="  > "
  select scenario in "day1-basic" "day1-combo" "day1-networking" "day1-security" "day2-machinepool"; do
    if [ -n "$scenario" ]; then
      SCENARIO="$scenario"
      break
    else
      echo "  Invalid selection"
    fi
  done
}

# Function to prompt for prefix
prompt_prefix() {
  echo ""
  read -p "$(echo -e ${BLUE}?)$(echo -e ${ENDC}) Cluster prefix? (e.g., rs1, rs2, rs3): " PREFIX
  if [ -z "$PREFIX" ]; then
    echo -e "${RED}Error: Prefix cannot be empty${ENDC}"
    prompt_prefix
  fi
}

# Function to prompt for version
prompt_version() {
  echo ""
  read -p "$(echo -e ${BLUE}?)$(echo -e ${ENDC}) OpenShift/ROSA version? (e.g., 5.0.0-rc.6, 4.22.6): " VERSION
  if [ -z "$VERSION" ]; then
    echo -e "${RED}Error: Version cannot be empty${ENDC}"
    prompt_version
  fi
}

# Function to prompt for channel group
prompt_channel_group() {
  echo ""
  read -p "$(echo -e ${BLUE}?)$(echo -e ${ENDC}) Channel group? (candidate, stable) [default: candidate]: " CHANNEL_GROUP
  CHANNEL_GROUP="${CHANNEL_GROUP:-candidate}"
}

# Function to prompt for keep-cluster
prompt_keep_cluster() {
  echo ""
  read -p "$(echo -e ${BLUE}?)$(echo -e ${ENDC}) Keep cluster running after test? (y/n): " keep_response
  case "$keep_response" in
    [Yy]*)
      KEEP_CLUSTER=true
      ;;
    [Nn]*)
      KEEP_CLUSTER=false
      ;;
    *)
      echo "  Please answer y or n"
      prompt_keep_cluster
      ;;
  esac
}

# Prompt for missing parameters
if [ -z "$SCENARIO" ]; then
  prompt_scenario
fi

if [ -z "$PREFIX" ]; then
  prompt_prefix
fi

if [ -z "$VERSION" ]; then
  prompt_version
fi

if [ -z "$CHANNEL_GROUP" ]; then
  prompt_channel_group
fi

prompt_keep_cluster

# Validate scenario
case "$SCENARIO" in
  day1-basic|day1-combo|day1-networking|day1-security|day2-machinepool)
    ;;
  *)
    echo -e "${RED}Error: Invalid scenario '$SCENARIO'${ENDC}"
    echo "Valid scenarios: day1-basic, day1-combo, day1-networking, day1-security, day2-machinepool"
    exit 1
    ;;
esac

# Function to parse YAML values robustly
parse_yaml_value() {
  local key="$1"
  local file="$2"

  # Try yq first if available (most robust)
  if command -v yq &> /dev/null; then
    yq eval ".${key}" "$file" 2>/dev/null | grep -v "null"
    return $?
  fi

  # Fallback to grep with YAML-aware parsing
  # Handles: key: value, key: "value", key: 'value', key: "value with spaces"
  local value=$(grep "^${key}:" "$file" | sed -E 's/^[^:]*:[[:space:]]*//; s/^["'"'"']//; s/["'"'"']$//')
  echo "$value"
}

# Load credentials from vars/user_vars.yml if not already set in environment
if [ -f "vars/user_vars.yml" ] && [ -z "$OCP_HUB_API_URL" ]; then
  echo -e "${YELLOW}Loading credentials from vars/user_vars.yml...${ENDC}"
  export OCP_HUB_API_URL=$(parse_yaml_value "OCP_HUB_API_URL" "vars/user_vars.yml")
  export OCP_HUB_CLUSTER_USER=$(parse_yaml_value "OCP_HUB_CLUSTER_USER" "vars/user_vars.yml")
  export OCP_HUB_CLUSTER_PASSWORD=$(parse_yaml_value "OCP_HUB_CLUSTER_PASSWORD" "vars/user_vars.yml")
  export AWS_ACCESS_KEY_ID=$(parse_yaml_value "AWS_ACCESS_KEY_ID" "vars/user_vars.yml")
  export AWS_SECRET_ACCESS_KEY=$(parse_yaml_value "AWS_SECRET_ACCESS_KEY" "vars/user_vars.yml")
  export OCM_CLIENT_ID=$(parse_yaml_value "OCM_CLIENT_ID" "vars/user_vars.yml")
  export OCM_CLIENT_SECRET=$(parse_yaml_value "OCM_CLIENT_SECRET" "vars/user_vars.yml")
fi

# Validate credentials before running test
echo ""
echo -e "${YELLOW}Checking credentials...${ENDC}"
echo ""

MISSING_CREDS=()

# Check OCP/Hub cluster credentials
if [ -z "$OCP_HUB_API_URL" ]; then
  MISSING_CREDS+=("OCP_HUB_API_URL (hub cluster API URL)")
fi

if [ -z "$OCP_HUB_CLUSTER_USER" ]; then
  MISSING_CREDS+=("OCP_HUB_CLUSTER_USER (hub cluster username)")
fi

if [ -z "$OCP_HUB_CLUSTER_PASSWORD" ]; then
  MISSING_CREDS+=("OCP_HUB_CLUSTER_PASSWORD (hub cluster password)")
fi

# Check AWS credentials
if [ -z "$AWS_ACCESS_KEY_ID" ]; then
  MISSING_CREDS+=("AWS_ACCESS_KEY_ID (AWS access key)")
fi

if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
  MISSING_CREDS+=("AWS_SECRET_ACCESS_KEY (AWS secret key)")
fi

# Check OCM credentials
if [ -z "$OCM_CLIENT_ID" ]; then
  MISSING_CREDS+=("OCM_CLIENT_ID (OCM API client ID)")
fi

if [ -z "$OCM_CLIENT_SECRET" ]; then
  MISSING_CREDS+=("OCM_CLIENT_SECRET (OCM API client secret)")
fi

# Validate credential formats
validate_credentials() {
  local validation_failed=false

  # Validate OCP_HUB_API_URL format
  if ! [[ "$OCP_HUB_API_URL" =~ ^https:// ]]; then
    echo -e "${RED}✗ OCP_HUB_API_URL: Must start with https://${ENDC}"
    validation_failed=true
  fi

  if ! [[ "$OCP_HUB_API_URL" =~ :[0-9]+$ ]]; then
    echo -e "${RED}✗ OCP_HUB_API_URL: Must include port (e.g., :6443)${ENDC}"
    validation_failed=true
  fi

  # Validate AWS_ACCESS_KEY_ID format
  if [ ${#AWS_ACCESS_KEY_ID} -lt 20 ]; then
    echo -e "${RED}✗ AWS_ACCESS_KEY_ID: Invalid format (too short, expected ~20 characters)${ENDC}"
    validation_failed=true
  fi

  # Validate AWS_SECRET_ACCESS_KEY format
  if [ ${#AWS_SECRET_ACCESS_KEY} -lt 40 ]; then
    echo -e "${RED}✗ AWS_SECRET_ACCESS_KEY: Invalid format (too short, expected ~40 characters)${ENDC}"
    validation_failed=true
  fi

  if [ "$validation_failed" = true ]; then
    echo ""
    echo -e "${YELLOW}Credential format validation failed. Please check your credentials.${ENDC}"
    return 1
  fi

  return 0
}

# Report missing credentials
if [ ${#MISSING_CREDS[@]} -gt 0 ]; then
  echo -e "${RED}❌ Missing required credentials:${ENDC}"
  echo ""
  for cred in "${MISSING_CREDS[@]}"; do
    echo "  • $cred"
  done
  echo ""
  echo -e "${YELLOW}Set credentials using one of these methods:${ENDC}"
  echo ""
  echo "Option 1: Environment variables"
  echo "  export OCP_HUB_API_URL=\"https://...:6443\""
  echo "  export OCP_HUB_CLUSTER_USER=\"kubeadmin\""
  echo "  export OCP_HUB_CLUSTER_PASSWORD=\"...\""
  echo "  export AWS_ACCESS_KEY_ID=\"...\""
  echo "  export AWS_SECRET_ACCESS_KEY=\"...\""
  echo "  export OCM_CLIENT_ID=\"...\""
  echo "  export OCM_CLIENT_SECRET=\"...\""
  echo ""
  echo "Option 2: vars/user_vars.yml"
  echo "  Create vars/user_vars.yml with all required variables"
  echo ""
  exit 1
fi

# Validate credential formats
echo -e "${YELLOW}Validating credential formats...${ENDC}"
if ! validate_credentials; then
  exit 1
fi

echo -e "${GREEN}✅ All required credentials found${ENDC}"
echo ""

# Validate version format (basic check)
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo -e "${RED}Error: Invalid version format '$VERSION'${ENDC}"
  echo "Expected format: X.Y.Z or X.Y.Z-rcN (e.g., 5.0.0-rc.6)"
  exit 1
fi

# Show configuration
echo ""
echo -e "${GREEN}✅ Configuration:${ENDC}"
echo "   Scenario: $SCENARIO"
echo "   Prefix: $PREFIX"
echo "   Version: $VERSION"
echo "   Channel: $CHANNEL_GROUP"
echo "   Keep cluster: $([ "$KEEP_CLUSTER" = true ] && echo "yes" || echo "no")"
echo ""

# Handle --dry-run mode
if [ "$DRY_RUN" = true ]; then
  echo -e "${GREEN}✅ Configuration is valid.${ENDC}"
  echo ""

  # Build the command (same as normal)
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  RUN_SCRIPT="$REPO_ROOT/run-test-suite.py"
  CMD="$RUN_SCRIPT --scenario $SCENARIO -e name_prefix=$PREFIX -e openshift_version=$VERSION -e channel_group=$CHANNEL_GROUP"

  if [ "$KEEP_CLUSTER" = true ]; then
    CMD="$CMD -e keep_cluster=true"
  fi

  echo -e "${YELLOW}Would execute:${ENDC}"
  echo "  $CMD"
  echo ""
  exit 0
fi

echo -e "${YELLOW}⏳ Starting test... (this will take ~20-25 minutes)${ENDC}"
echo ""

# Build the command
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_SCRIPT="$REPO_ROOT/run-test-suite.py"

CMD="$RUN_SCRIPT --scenario $SCENARIO -e name_prefix=$PREFIX -e openshift_version=$VERSION -e channel_group=$CHANNEL_GROUP"

if [ "$KEEP_CLUSTER" = true ]; then
  CMD="$CMD -e keep_cluster=true"
fi

# Run the test suite
echo "Running: $CMD"
echo ""

# Execute the command
cd "$REPO_ROOT"
eval "$CMD"
