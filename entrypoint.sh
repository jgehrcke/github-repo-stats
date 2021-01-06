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
- workflow that created this README: \`${GITHUB_WORKFLOW}\`

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

echo "finished"
exit 0
