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

# For debugging, let's be sure that the GHRS_GITHUB_API_TOKEN is non-empty.
echo "length of API TOKEN: ${#GHRS_GITHUB_API_TOKEN}"

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

# Have CPython emit its stderr data immediately to the attached
# streams to reduce the likelihood for bad order of log lines in the GH
# Action log viewer (seen `error: fetch.py returned with code 1 -- exit.`
# before the last line of the CPython stderr stream was shown.)

export PYTHONUNBUFFERED="on"

set +e
python /fetch.py "${STATS_REPOSPEC}" --output-directory=newdata
FETCH_ECODE=$?
set -e

set +x
if [ $FETCH_ECODE -ne 0 ]; then
    # Try to work around sluggish stderr/out interleaving in GH Action's log
    # viewer, give CPython's stderr emitted above a little time to be captured
    # and forwarded by the GH Action log viewer.
    sleep 0.1
    echo "error: fetch.py returned with code ${FETCH_ECODE} -- exit."
    exit $FETCH_ECODE
fi

echo "fetch.py returned with exit code 0. proceed."
echo "tree in $(pwd)/newdata:"
tree newdata

set -x
mkdir -p ghrs-data/snapshots
cp -a newdata/* ghrs-data/snapshots || echo "copy failed, ignore (continue)"

# New data files: show them from git's point of view.
git status --untracked=no --porcelain

# exit code 0 when nothing added
git add ghrs-data/snapshots

# exit code 1 upon 'nothing to commit, working tree clean'
git commit -m "ghrs: snap ${UPDATE_ID} for ${STATS_REPOSPEC}" || echo "commit failed, ignore (continue)"

# Pragmatic wait, against interleaved stderr/out in GHA log viewer.
set +x
sleep 1

echo "Parse data files, perform aggregation and analysis, generate Markdown report and render as HTML"
set -x
set +e
python /analyze.py \
    --resources-directory /resources \
    --output-directory latest-report \
    --outfile-prefix "" \
    --stargazer-ts-resampled-outpath "ghrs-data/stargazers.csv" \
    --fork-ts-resampled-outpath "ghrs-data/forks.csv" \
    --views-clones-aggregate-outpath "ghrs-data/views_clones_aggregate.csv" \
    --views-clones-aggregate-inpath "ghrs-data/views_clones_aggregate.csv" \
    --delete-ts-fragments \
    "${STATS_REPOSPEC}" ghrs-data/snapshots
ANALYZE_ECODE=$?
set -e

set +x
if [ $ANALYZE_ECODE -ne 0 ]; then
    echo "error: analyze.py returned with code ${ANALYZE_ECODE} -- exit."
    exit $ANALYZE_ECODE
fi

set -x
# Commit the changed view/clone aggregate, and the deletion of snapshot files
git add ghrs-data/views_clones_aggregate.csv
git add ghrs-data/snapshots

# exit code 1 upon 'nothing to commit, working tree clean'
git commit -m "ghrs: vc agg ${UPDATE_ID} for ${STATS_REPOSPEC}" || echo "commit failed, ignore (continue)"

# Commit the updated stargazer / fork. Do not error out if nothing changed.
git add ghrs-data/forks.csv ghrs-data/stargazers.csv
git commit -m "ghrs: stars and forks ${UPDATE_ID} for ${STATS_REPOSPEC}" || echo "commit failed, ignore  (continue)"

echo "Translate HTML report into PDF, via headless Chrome"
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
set +x

# Now, push the changes to the remote branch. Note that there might have been
# other jobs running, pushing to the same branch in the meantime. In that case,
# the push fails with "updates were rejected because the remote contains work
# that you do not have locally." -- assume that changes are actually isolated
# (not in conflict, but happening in distinct directories) and therefore assume
# that a rather simple pull/push loop will after all help synchronize the
# concurrent racers here. Also see issue #9 and #11.

# Abort waiting upon this deadline.
MAX_WAIT_SECONDS=500
DEADLINE=$(($(date +%s) + ${MAX_WAIT_SECONDS}))

while true
do

    if (( $(date +%s) > ${DEADLINE} )); then
        echo "pull/push loop: deadline hit: waited for ${MAX_WAIT_SECONDS} s"
        exit 1
    fi


    # Do a pull right before the push, they should be looked at as an 'atomic
    # unit', doing them right after one another is the recipe for long-term
    # convergence here -- of course that means that even the first push is
    # quite likely to succeed. Not sure if more than 1 loop iteration will
    # ever be hit in the real world.
    set -x
    git pull # error out if pull fails (errexit)

    set +e
    git push --set-upstream origin "${DATA_BRANCH_NAME}"
    PUSH_ECODE=$?
    set -e
    set +x

    if [ $PUSH_ECODE -ne 0 ]; then
        echo "warn: git push returned with code ${PUSH_ECODE}, retry soon"
    else
        echo "pull/push loop: push succeeded, leave loop"
        break
    fi

    echo "pull/push loop:sleep for 10 s"
    sleep 10
done

echo "finished"
exit 0
