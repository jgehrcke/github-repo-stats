GIT_COMMIT_HASH ?= $(shell git rev-parse --short=9 HEAD)

IMAGE_NAME = jgehrcke/github-repo-stats-base:$(GIT_COMMIT_HASH)

base-image:
	docker build -f base.Dockerfile . -t $(IMAGE_NAME)

base-image-push:
	docker push $(IMAGE_NAME)

# This is for testing the container image build based on Dockerfile, as
# executed by GH actions.
image:
	docker build -f Dockerfile . -t jgehrcke/github-repo-stats
