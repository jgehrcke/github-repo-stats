FROM python:3.10-slim-buster

RUN apt-get update && apt-get install -y -q --no-install-recommends \
    gnupg curl git jq moreutils ca-certificates unzip less tree pandoc \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sS -o - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add
RUN echo "deb [arch=amd64]  http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list
RUN apt-get -y update
RUN apt-get -y install google-chrome-stable

RUN pip install pip==21.3.1

# Dependencies for fetch.py & analyze.py
COPY requirements-fa.txt .
RUN pip install -r requirements-fa.txt

# Dependencies for pdf.py
# Explore bumping selenium to 4.x
RUN pip install selenium==3.141.0 webdriver_manager==3.5.2

# Install bats for running cmdline tests, also used in GHRS CI
RUN git clone https://github.com/bats-core/bats-core.git && cd bats-core && \
    git checkout v1.5.0 && ./install.sh /usr/local

RUN mkdir -p /bats-libraries
RUN git clone https://github.com/bats-core/bats-support /bats-libraries/bats-support
RUN git clone https://github.com/bats-core/bats-assert /bats-libraries/bats-assert

# check that this file exists
RUN stat /bats-libraries/bats-assert/load.bash

# Expect `bats` to work.
RUN bats --help
