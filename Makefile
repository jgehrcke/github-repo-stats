GIT_COMMIT_HASH ?= $(shell git rev-parse --short=9 HEAD)

BASE_IMAGE_NAME = jgehrcke/github-repo-stats-base:5e4b35d29
NEW_BASE_IMAGE_NAME = jgehrcke/github-repo-stats-base:$(GIT_COMMIT_HASH)
CI_IMAGE = jgehrcke/github-repo-stats-ci:$(GIT_COMMIT_HASH)

.PHONY: new-base-image
new-base-image:
	docker build -f base.Dockerfile . -t $(NEW_BASE_IMAGE_NAME)

.PHONY: new-base-image-push
new-base-image-push:
	docker push $(NEW_BASE_IMAGE_NAME)

.PHONY: ci-image
ci-image:
	docker build -f ci.Dockerfile . -t $(CI_IMAGE)


# This is for testing the container image build based on Dockerfile, as
# executed by GH actions: `Dockerfile` at the root of the repository defines
# the container image that GH actions uses to spawn a container from when
# others use this GH action.
.PHONY: action-image
action-image:
	docker build -f Dockerfile . -t jgehrcke/github-repo-stats:local

.PHONY: bats-test
bats-test: ci-image
	docker run --entrypoint "/bin/bash" -v $(shell pwd):/cwd $(CI_IMAGE) \
		-c "cd /cwd && bats \
			--print-output-on-failure \
			tests/analyze.bats \
		"