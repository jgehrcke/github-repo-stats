#!/bin/bash -l

# GHRS: GitHub Repo Stats https://github.com/jgehrcke/github-repo-stats

echo "GHRS entrypoint.sh: pwd: $(pwd)"

# Arguments in GH actions will be passed/defined via the action.yaml file.

# Default to GITHUB_REPOSITORY.
REPOSPEC="${GITHUB_REPOSITORY}"

# TODO: can be overridden to use a repository _different_ from where the
# workflow is being executed.
#REPOSPEC="${GHRS_REPO_SPEC}"

# For now: hard-code
REPOSPEC="jgehrcke/covid-19-germany-gae"

if [[ ! $GHRS_GCS_BUCKET_NAME ]]; then
    echo "error: the env var GHRS_GCS_BUCKET_NAME appears to be empty or not set"
    exit 1
fi


# Construct 'absolute path' to 'directory' in bucket where individual
# fragment/snapshopt files will be stored to. The list of objects in this
# 'directory' may grow large but certainly manageable. Note: `${REPOSPEC/\//_}`
# replaces the slash in the repo spec with an underscore. Pieces of
# information: bucket name, 'github-repostats', repo owner/org and repo name.
GCS_DIRECTORY_ABSPATH="${GHRS_GCS_BUCKET_NAME}/github-repo-stats_${REPOSPEC/\//_}"


# Do a bit of validation.
if [[ $(echo "$GHRS_GCS_SVC_ACC_JSON" | wc -l ) -lt 3 ]]; then
    echo "error: env var GHRS_GCS_SVC_ACC_JSON has less than 3 lines of text"
    exit 1
fi
if jq -e . >/dev/null 2>&1 <<< "$GHRS_GCS_SVC_ACC_JSON"; then
    echo "env var GHRS_GCS_SVC_ACC_JSON: looks like valid JSON"
else
    echo "error: env var GHRS_GCS_SVC_ACC_JSON: failed to parse JSON"
    exit 1
fi

# Assume ephemeral container file system, store this at the root.
GCP_CREDENTIAL_FILE="/gcs_svc_acc.json"
echo "$GHRS_GCS_SVC_ACC_JSON" > ${GCP_CREDENTIAL_FILE}
chmod 600 ${GCP_CREDENTIAL_FILE}

GHRS_OUTDIR="newdata"
# The container
echo "change to /rundir"
cd /rundir
mkdir "${GHRS_OUTDIR}"

echo "Fetch new data"
set -x
python /fetch.py "${REPOSPEC}" --output-directory=${GHRS_OUTDIR}
FETCH_ECODE=$?
set +x

if [ $FETCH_ECODE -ne 0 ]; then
    echo "error: fetch.py returned with code ${FETCH_ECODE} -- exit."
    exit $FETCH_ECODE
fi

echo "fetch.py returned with exit code 0. proceed."

echo "tree in $(pwd):"
tree


# Brief sleep as a workaround for having non-interleaving output of `tree` and
# `gcloud auth`.
sleep 1

# Do not use `-d/--delete` so that remote data is not deleted. Plan with a flat
# file hierarchy / set of files in GHRS_OUTDIR, i.e. do not use `-r`. Sync the
# contents of GHRS_OUTDIR to the storage bucket.
set -x
gcloud auth activate-service-account --key-file ${GCP_CREDENTIAL_FILE}
gsutil rsync "${GHRS_OUTDIR}" "gs://$GCS_DIRECTORY_ABSPATH"
SYNC_ECODE=$?
set +x

if [ $SYNC_ECODE -ne 0 ]; then
    echo "error: gsutil returned with code ${SYNC_ECODE} -- exit."
    exit $SYNC_ECODE
fi


# "At the end of every upload, the gsutil rsync command validates that the
# checksum of the source file/object matches the checksum of the destination
# file/object. If the checksums do not match, gsutil will delete the invalid
# copy and print a warning message." and "The rsync command will retry when
# failures occur, but if enough failures happen during a particular copy or
# delete operation the command will fail."

echo "finished"