FROM jgehrcke/github-repo-stats-base:f9f4e16c1

COPY fetch.py /fetch.py
COPY analyze.py /analyze.py
COPY pdf.py /pdf.py
COPY entrypoint.sh /entrypoint.sh
COPY resources /resources

RUN mkdir /rundir && cd /rundir
WORKDIR /rundir
ENTRYPOINT ["/entrypoint.sh"]
