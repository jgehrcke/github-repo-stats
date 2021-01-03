#!/bin/bash -l

set -o errexit
set -o errtrace
set -o nounset
set -o pipefail

# GHRS: GitHub Repo Stats https://github.com/jgehrcke/github-repo-stats

echo "GHRS entrypoint.sh: pwd: $(pwd)"

RNDSTR=$(python -c 'import uuid; print(uuid.uuid4().hex.upper()[0:4])')
UPDATE_ID="$(date +"%m-%d-%H%M" --utc)-${RNDSTR}"


# "When you specify an input to an action in a workflow file or use a default
# input value, GitHub creates an environment variable for the input with the
# name INPUT_<VARIABLE_NAME>. The environment variable created converts input
# names to uppercase letters and replaces spaces with _ characters."

# The data repository and the repository to fetch statistics for do not
# need to be the same!

# This is the repository to fetch data for.
STATS_REPOSPEC="${INPUT_REPOSITORY}"

# This is the repository to store data and reports in.
DATA_REPOSPEC="${GITHUB_REPOSITORY}"

# This is the API token used to fetch data (for the repo of interest) and
# to interact with the data repository.
export GHRS_GITHUB_API_TOKEN="${INPUT_GHTOKEN}"

# The name of the branch in the data repository.
DATA_BRANCH_NAME="${INPUT_DATABRANCH}"

set -x

# Clone / check out specific branch only (to minimize overhead, also see
# https://stackoverflow.com/a/4568323/145400).
# git clone -b "${DATA_BRANCH_NAME}" \
#     --single-branch git@github.com:${REPOSPEC}.git

git clone https://ghactions:${GHRS_GITHUB_API_TOKEN}@github.com/${DATA_REPOSPEC}.git .
git remote set-url origin https://ghactions:${GHRS_GITHUB_API_TOKEN}@github.com/${DATA_REPOSPEC}.git
git checkout "${DATA_BRANCH_NAME}" || git checkout -b "${DATA_BRANCH_NAME}"

git config --local user.email "action@github.com"
git config --local user.name "GitHub Action"

mkdir newdata
echo "Fetch new data for ${STATS_REPOSPEC}"
python /fetch.py "${STATS_REPOSPEC}" --output-directory=newdata
FETCH_ECODE=$?
set +x

if [ $FETCH_ECODE -ne 0 ]; then
    echo "error: fetch.py returned with code ${FETCH_ECODE} -- exit."
    exit $FETCH_ECODE
fi

echo "fetch.py returned with exit code 0. proceed."
echo "tree in $(pwd)/newdata:"
tree newdata

set -x
mkdir -p ghrs_data_snapshots
cp -a newdata/* ghrs_data_snapshots

# New data files: show them from git's point of view.
git status --untracked=no --porcelain
git add ghrs_data_snapshots
git commit -m "github-repo-stats: new snapshot ${UPDATE_ID}"


echo "Generate new HTML report"
python /analyze.py \
    --resources-directory /resources \
    --output-directory newreport \
    "${STATS_REPOSPEC}" ghrs_data_snapshots


stat newreport/*_report_for_pdf.html

echo "Translate HTML report into PDF with headless Chrome"
python /pdf.py newreport/*_report_for_pdf.html

mv report.pdf current-report.pdf
git add current-report.pdf
git commit -m "github-repo-stats: add PDF report ${UPDATE_ID}"


git push --set-upstream origin "${DATA_BRANCH_NAME}"

# Ignore GCS approach for now.
exit 0

# Brief sleep as a workaround for having non-interleaving output of `tree` and
# `gcloud auth`.
sleep 1


if [[ ! $GHRS_GCS_BUCKET_NAME ]]; then
    echo "bad env: GHRS_GCS_BUCKET_NAME appears to be empty or not set"
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