export OCM_CLIENT_ID ?=
export OCM_API_URL ?=
export OCM_CLIENT_SECRET ?=
export AWS_B64ENCODED_CREDENTIALS ?=
DEFAULT_TEST_SUITE ?= --list
PULL_SECRET_FILE ?=

OCP_VERSION ?= 4.22.6

# Feature used as the probe for `make verify-skills`. disk_size is the default
# because its feature id, CLI alias (disk-size) and var_map variable
# (root_volume_size) are three different strings, and it is a non-boolean on
# ROSAMachinePool -- so every seam SKILLS.md warns about is load-bearing. A
# feature whose id, alias and variable are all the same string (fips, no_cni)
# would still pass with var_map deleted entirely.
FEATURE ?= disk_size

.PHONY: test scenarios scenario verify-skills crc-smoke crc-full crc-stop

test:
	./run-test-suite.py $(DEFAULT_TEST_SUITE) -vvv

# Check SKILLS.md still describes the code, by walking one shipped feature through
# every layer the doc says it must touch: registry, version gate, both 4.22/5.0
# templates, crd_field_map, the CHECK guard, the verification task, the docs page
# and README, then the extra vars the CLI actually resolves. Exits non-zero on the
# first disagreement -- which means either the doc drifted or that feature is
# incomplete.
#   make verify-skills
#   make verify-skills FEATURE=audit_logging
verify-skills:
	./scripts/verify_skills_md.py $(FEATURE)

# List runnable scenarios and the OpenShift versions each supports
scenarios:
	./run-test-suite.py --list-scenarios

# Run one scenario end to end, e.g.
#   make scenario SCENARIO=day1-security OCP_VERSION=5.0 NAME_PREFIX=qe6
scenario:
	@test -n "$(SCENARIO)" || { \
		echo "Error: set SCENARIO=<name> (see: make scenarios)"; exit 1; }
	./run-test-suite.py --scenario $(SCENARIO) \
		-e openshift_version=$(OCP_VERSION) \
		$(if $(NAME_PREFIX),-e name_prefix=$(NAME_PREFIX),) \
		$(if $(STAGES),--stages $(STAGES),) \
		-vvv

define crc-setup
	@command -v crc >/dev/null 2>&1 || { echo "Error: crc is not installed"; exit 1; }
	@command -v oc >/dev/null 2>&1 || { echo "Error: oc is not installed"; exit 1; }
	@command -v helm >/dev/null 2>&1 || { echo "Error: helm is not installed"; exit 1; }
	@if [ -n "$(PULL_SECRET_FILE)" ]; then \
		crc config set pull-secret-file "$(PULL_SECRET_FILE)"; \
	fi
	crc start
	@LOGIN_CMD=$$(crc console --credentials 2>/dev/null | grep kubeadmin | sed "s/.*'\(oc login[^']*\)'.*/\1/"); \
		if [ -z "$$LOGIN_CMD" ]; then echo "Error: failed to extract kubeadmin login from crc"; exit 1; fi; \
		eval "$$LOGIN_CMD"
endef

crc-smoke:
	$(crc-setup)
	NAME_PREFIX="lc$$(head -c 2 /dev/urandom | od -An -tx1 | tr -d ' ')" && \
	DEPLOYMENT_MODE=standalone ./run-test-suite.py --tag smoke --ai-agent -e name_prefix="$$NAME_PREFIX" -vvv

crc-full:
	$(crc-setup)
	NAME_PREFIX="lc$$(head -c 2 /dev/urandom | od -An -tx1 | tr -d ' ')" && \
	DEPLOYMENT_MODE=standalone ./run-test-suite.py --tag full --ai-agent -e name_prefix="$$NAME_PREFIX" -e reserve_upgrade_path=true -vvv

crc-stop:
	crc stop
