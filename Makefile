export OCM_CLIENT_ID ?=
export OCM_API_URL ?=
export OCM_CLIENT_SECRET ?=
export AWS_B64ENCODED_CREDENTIALS ?=
DEFAULT_TEST_SUITE ?= --list
PULL_SECRET_FILE ?=

.PHONY: test crc-standalone crc-stop

test:
	./run-test-suite.py $(DEFAULT_TEST_SUITE) -vvv

crc-standalone:
	@command -v crc >/dev/null 2>&1 || { echo "Error: crc is not installed"; exit 1; }
	@command -v oc >/dev/null 2>&1 || { echo "Error: oc is not installed"; exit 1; }
	@command -v helm >/dev/null 2>&1 || { echo "Error: helm is not installed"; exit 1; }
	@if [ -n "$(PULL_SECRET_FILE)" ]; then \
		crc config set pull-secret-file $(PULL_SECRET_FILE); \
	fi
	crc start
	@LOGIN_CMD=$$(crc console --credentials 2>/dev/null | grep kubeadmin | sed "s/.*'\(oc login[^']*\)'.*/\1/"); \
		if [ -z "$$LOGIN_CMD" ]; then echo "Error: failed to extract kubeadmin login from crc"; exit 1; fi; \
		eval "$$LOGIN_CMD"
	NAME_PREFIX="lc$$(head -c 2 /dev/urandom | od -An -tx1 | tr -d ' ')" && \
	DEPLOYMENT_MODE=standalone ./run-test-suite.py --tag smoke --ai-agent -e name_prefix="$$NAME_PREFIX" -vvv

crc-stop:
	crc stop
