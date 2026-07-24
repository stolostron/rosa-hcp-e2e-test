export OCM_CLIENT_ID ?=
export OCM_API_URL ?=
export OCM_CLIENT_SECRET ?=
export AWS_B64ENCODED_CREDENTIALS ?=
export DEPLOYMENT_MODE ?= standalone
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
	@eval $$(crc console --credentials 2>/dev/null | grep kubeadmin | sed "s/.*'\(oc login[^']*\)'.*/\1/")
	DEPLOYMENT_MODE=standalone ./run-test-suite.py --tag smoke -vvv

crc-stop:
	crc stop
