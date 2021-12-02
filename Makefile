GIT_COMMIT_HASH ?= $(shell git rev-parse --short=9 HEAD)

BASE_IMAGE_NAME = jgehrcke/github-repo-stats-base:3aa1455e0
NEW_BASE_IMAGE_NAME = jgehrcke/github-repo-stats-base:$(GIT_COMMIT_HASH)

new-base-image:
	docker build -f base.Dockerfile . -t $(NEW_BASE_IMAGE_NAME)

new-base-image-push:
	docker push $(NEW_BASE_IMAGE_NAME)

# This is for testing the container image build based on Dockerfile, as
# executed by GH actions.
image:
	docker build -f Dockerfile . -t jgehrcke/github-repo-stats:local

bats-test:
	docker run --entrypoint "/bin/bash" -v $(shell pwd):/cwd $(BASE_IMAGE_NAME) \
		-c "cd /cwd && bats \
			--print-output-on-failure \
			tests/analyze.bats \
		"