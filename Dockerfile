FROM python:3.8-slim-buster

RUN apt-get update && apt-get install -y -q --no-install-recommends \
    gnupg curl git jq moreutils ca-certificates unzip less tree pandoc

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

RUN pip install pandas==1.1.5 PyGitHub==1.54 pytz retrying \
    selenium==3.141.0 carbonplan[styles] altair

COPY fetch.py /fetch.py
COPY analyze.py /analyze.py
COPY pdf.py /pdf.py
COPY entrypoint.sh /entrypoint.sh
COPY resources /resources

RUN mkdir /rundir && cd /rundir
WORKDIR /rundir
ENTRYPOINT ["/entrypoint.sh"]
