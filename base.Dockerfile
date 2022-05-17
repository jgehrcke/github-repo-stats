FROM python:3.10-slim-buster

RUN apt-get update && apt-get install -y -q --no-install-recommends \
        gnupg curl git jq moreutils ca-certificates unzip less tree pandoc \
    && curl -sS -o - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add \
    && echo "deb [arch=amd64]  http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y -q --no-install-recommends \
        google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

RUN pip install pip==22.1

# requirements-fa.txt: dependencies for fetch.py & analyze.py
# for pdf.py: Note Explore bumping selenium to 4.x
COPY requirements-fa.txt .
RUN pip install -r requirements-fa.txt \
    && pip install selenium==3.141.0 webdriver_manager==3.5.2 #  Dependencies for pdf.py \
    && pip cache purge

RUN echo "biggest dirs"
RUN cd / && du -ha . | sort -r -h | head -n 50 || true