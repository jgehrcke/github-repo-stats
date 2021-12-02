FROM jgehrcke/github-repo-stats-base:5e4b35d29

# Install bats for running cmdline tests, also used in GHRS CI
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
