export OCM_CLIENT_ID ?=
export OCM_API_URL ?=
export OCM_CLIENT_SECRET ?=
export AWS_B64ENCODED_CREDENTIALS ?=
DEFAULT_TEST_SUITE ?= --list # setting the command arg as list for the moment to have clean output without error.
DEPLOYMENT_MODE ?= standalone

.PHONY: test

test:
	./run-test-suite.py $(DEFAULT_TEST_SUITE) $(DEPLOYMENT_MODE) -vvv
