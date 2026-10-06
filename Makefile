export OCM_CLIENT_ID ?=
export OCM_API_URL ?=
export OCM_CLIENT_SECRET ?=
export AWS_B64ENCODED_CREDENTIALS ?=
DEFAULT_TEST_SUITE ?= --list
PULL_SECRET_FILE ?=

OCP_VERSION ?= 4.22.6

.PHONY: test scenarios scenario crc-smoke crc-full crc-stop

test:
	./run-test-suite.py $(DEFAULT_TEST_SUITE) -vvv

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
