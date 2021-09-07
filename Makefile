GIT_COMMIT_HASH ?= $(shell git rev-parse --short=9 HEAD)

IMAGE_NAME = jgehrcke/github-repo-stats:$(GIT_COMMIT_HASH)

image:
	docker build -f Dockerfile . -t $(IMAGE_NAME)

image-push:
	docker push $(IMAGE_NAME)
