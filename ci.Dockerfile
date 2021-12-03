FROM jgehrcke/github-repo-stats-base:6e6c3e4f8

# Install GNU parallel
RUN apt-get update && apt-get install -y -q --no-install-recommends \
    parallel && rm -rf /var/lib/apt/lists/*

COPY requirements-ci.txt .
RUN pip install -r requirements-ci.txt

# Install bats for running cmdline tests. This is the image used when invoking
# `make bats-test`.
RUN git clone https://github.com/bats-core/bats-core.git && cd bats-core && \
    git checkout v1.5.0 && ./install.sh /usr/local

RUN mkdir -p /bats-libraries
RUN git clone https://github.com/bats-core/bats-support /bats-libraries/bats-support
RUN git clone https://github.com/bats-core/bats-assert /bats-libraries/bats-assert
RUN git clone https://github.com/bats-core/bats-file /bats-libraries/bats-file

# check that this file exists
RUN stat /bats-libraries/bats-assert/load.bash

# Expect `bats` to work.
RUN bats --help

# This is also where the current checkout will be mounted to.
RUN mkdir -p /checkout
WORKDIR /checkout
