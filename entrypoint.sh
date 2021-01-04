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

# Do not write to the root of the repository, but to a directory named after
# the stats respository (owner/repo). So that, in theory, this data repository
# can be used by GHRS for more than one stats repositories, using the same git.
# branch.
mkdir -p "${STATS_REPOSPEC}"
cd "${STATS_REPOSPEC}"

echo "operating in $(pwd)"

mkdir newdata
echo "Fetch new data snapshot for ${STATS_REPOSPEC}"
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
mkdir -p ghrs-data/snapshots
cp -a newdata/* ghrs-data/snapshots

# New data files: show them from git's point of view.
git status --untracked=no --porcelain
git add ghrs-data/snapshots
git commit -m "ghrs: snap ${UPDATE_ID} for ${STATS_REPOSPEC}"

# Pragmatic method against interleaved stderr/out in GHA log viewer.
set +x
sleep 1

echo "Parse data files, perform aggregation and analysis, generate Markdown report and render as HTML"
set -x
python /analyze.py \
    --resources-directory /resources \
    --output-directory latest-report \
    --outfile-prefix "" \
    --views-clones-aggregate-outpath "ghrs-data/views_clones_aggregate.csv" \
    --views-clones-aggregate-inpath "ghrs-data/views_clones_aggregate.csv" \
    --delete-ts-fragments \
    "${STATS_REPOSPEC}" ghrs-data/snapshots
ANALYZE_ECODE=$?
set +x

if [ $ANALYZE_ECODE -ne 0 ]; then
    echo "error: analyze.py returned with code ${ANALYZE_ECODE} -- exit."
    exit $ANALYZE_ECODE
fi

# Commit the changed view/clone aggregate, and the deletion of snapshot files
git add ghrs-data/views_clones_aggregate.csv
git add ghrs-data/snapshots
git commit -m "ghrs: vc agg ${UPDATE_ID} for ${STATS_REPOSPEC}"

echo "Translate HTML report into PDF, via headless Chrome"
set -x
python /pdf.py latest-report/report_for_pdf.html latest-report/report.pdf

# Add directory contents (markdown, HTML, PDF).
git add latest-report

set +x
echo "generate README.md"
cat << EOF > README.md
## github-repo-stats for ${STATS_REPOSPEC}

- statistics for repository https://github.com/${STATS_REPOSPEC}
- managed by GitHub Action: https://github.com/jgehrcke/github-repo-stats
- workflow that created this file: \`${GITHUB_WORKFLOW}\`

**Latest report PDF**: [report.pdf](https://github.com/${DATA_REPOSPEC}/raw/${DATA_BRANCH_NAME}/${STATS_REPOSPEC}/latest-report/report.pdf)

EOF

# If the GitHub pages prefix is set in the action config then add a link to
# the HTML report to the README.

if [[ "${INPUT_GHPAGESPREFIX}" != "none" ]]; then

cat << EOF >> README.md

**Latest report HTML via GitHub pages**: [report.html](${INPUT_GHPAGESPREFIX}/${STATS_REPOSPEC}/latest-report/report.html)
EOF

fi

set -x
git add README.md
git commit -m "ghrs: report ${UPDATE_ID} for ${STATS_REPOSPEC}"
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