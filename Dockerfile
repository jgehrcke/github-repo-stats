FROM python:3.8-slim-buster

RUN apt-get update && apt-get install -y -q --no-install-recommends \
    gnupg curl git jq moreutils ca-certificates unzip less tree pandoc

RUN curl -sS -o - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add
RUN echo "deb [arch=amd64]  http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list
RUN apt-get -y update
RUN apt-get -y install google-chrome-stable

# RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" | \
#     tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
# RUN curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
#     apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -
# RUN apt-get update && apt-get install -y -q --no-install-recommends google-cloud-sdk
# RUN apt-get -y autoclean

# RUN gcloud config set core/disable_usage_reporting true && \
#     gcloud config set component_manager/disable_update_check true && \
#     gcloud config set metrics/environment github_docker_image

# RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
#     unzip -q awscliv2.zip && \
#     ./aws/install && \
#     rm awscliv2.zip

RUN pip install pandas==1.2.4 PyGitHub==1.54.1 pytz retrying \
    selenium==3.141.0 webdriver_manager carbonplan[styles] altair==4.1.0

COPY fetch.py /fetch.py
COPY analyze.py /analyze.py
COPY pdf.py /pdf.py
COPY entrypoint.sh /entrypoint.sh
COPY resources /resources

RUN mkdir /rundir && cd /rundir
WORKDIR /rundir
ENTRYPOINT ["/entrypoint.sh"]
