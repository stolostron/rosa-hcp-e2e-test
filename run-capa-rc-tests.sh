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

# Check if --help requested
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: /run-capa-rc-tests [SCENARIO] [PREFIX] [VERSION] [--keep-cluster]"
  echo ""
  echo "Interactive mode (prompts for inputs):"
  echo "  /run-capa-rc-tests"
  echo ""
  echo "Command-line mode (all arguments provided):"
  echo "  /run-capa-rc-tests day1-basic rs1 5.0.0-rc.6"
  echo ""
  echo "Keep cluster for debugging:"
  echo "  /run-capa-rc-tests day1-basic rs1 5.0.0-rc.6 --keep-cluster"
  exit 0
fi

# Parse positional arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-cluster)
      KEEP_CLUSTER=true
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

# Load credentials from vars/user_vars.yml if not already set in environment
if [ -f "vars/user_vars.yml" ] && [ -z "$OCP_HUB_API_URL" ]; then
  echo -e "${YELLOW}Loading credentials from vars/user_vars.yml...${ENDC}"
  export OCP_HUB_API_URL=$(grep "^OCP_HUB_API_URL:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
  export OCP_HUB_CLUSTER_USER=$(grep "^OCP_HUB_CLUSTER_USER:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
  export OCP_HUB_CLUSTER_PASSWORD=$(grep "^OCP_HUB_CLUSTER_PASSWORD:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
  export AWS_ACCESS_KEY_ID=$(grep "^AWS_ACCESS_KEY_ID:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
  export AWS_SECRET_ACCESS_KEY=$(grep "^AWS_SECRET_ACCESS_KEY:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
  export OCM_CLIENT_ID=$(grep "^OCM_CLIENT_ID:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
  export OCM_CLIENT_SECRET=$(grep "^OCM_CLIENT_SECRET:" vars/user_vars.yml | cut -d' ' -f2 | tr -d '"')
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
  echo "  export OCP_HUB_API_URL=\"https://...\""
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
echo -e "${YELLOW}⏳ Starting test... (this will take ~20-25 minutes)${ENDC}"
echo ""

# Build the command
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SCRIPT="$REPO_ROOT/run-test-suite.py"

CMD="$RUN_SCRIPT --scenario $SCENARIO -e name_prefix=$PREFIX -e openshift_version=$VERSION -e channel_group=$CHANNEL_GROUP"

if [ "$KEEP_CLUSTER" = true ]; then
  CMD="$CMD -e keep_cluster=true"
fi

# Run the test suite with live monitoring
echo "Running: $CMD"
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════════${ENDC}"
echo -e "${GREEN}Live Monitoring (refreshes every 30 seconds):${ENDC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${ENDC}"
echo ""

# Execute the command and capture output with progress monitoring
cd "$REPO_ROOT"

# Create a named pipe for real-time output
FIFO=$(mktemp -u)
mkfifo "$FIFO"

# Run the test in background, redirecting output to FIFO
eval "$CMD" > "$FIFO" 2>&1 &
TEST_PID=$!

# Monitor output and show progress
START_TIME=$(date +%s)
LAST_ACTIVITY=$(date +%s)
STAGE_COUNT=0

echo -e "${BLUE}⏳ Test started at $(date '+%H:%M:%S')${ENDC}"
echo ""

while IFS= read -r line; do
  # Print the line
  echo "$line"

  # Track activity and update last activity time
  LAST_ACTIVITY=$(date +%s)

  # Count stage completions
  if [[ "$line" =~ "✓ Completed successfully" ]] || [[ "$line" =~ "PLAY RECAP" ]]; then
    STAGE_COUNT=$((STAGE_COUNT + 1))
  fi

  # Show progress every 30 seconds of inactivity
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))

done < "$FIFO"

# Wait for test to complete
wait $TEST_PID
TEST_EXIT=$?

# Clean up FIFO
rm -f "$FIFO"

# Show final status
TOTAL_TIME=$(($(date +%s) - START_TIME))
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════════${ENDC}"
if [ $TEST_EXIT -eq 0 ]; then
  echo -e "${GREEN}✅ Test completed successfully!${ENDC}"
  echo -e "${GREEN}Total time: $(($TOTAL_TIME / 60))m $((TOTAL_TIME % 60))s${ENDC}"
else
  echo -e "${RED}❌ Test failed with exit code: $TEST_EXIT${ENDC}"
  echo -e "${RED}Elapsed time: $(($TOTAL_TIME / 60))m $((TOTAL_TIME % 60))s${ENDC}"
fi
echo -e "${GREEN}════════════════════════════════════════════════════════════════${ENDC}"
echo ""

exit $TEST_EXIT
