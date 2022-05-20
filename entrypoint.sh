#!/bin/bash -l

set -o errexit
set -o errtrace
set -o nounset
set -o pipefail

# GHRS: GitHub Repo Stats https://github.com/jgehrcke/github-repo-stats

echo "GHRS entrypoint.sh: pwd: $(pwd)"

RNDSTR=$(python -c 'import uuid; print(uuid.uuid4().hex.upper()[0:4])')
UPDATE_ID="$(date +"%m-%d-%H%M" --utc)-${RNDSTR}"

# For testing purposes, allow for overriding the path to the root of the
# GHRS repo. Default to /. Expected: /fetch.py, /analyze.py, etc.
GHRS_FILES_ROOT_PATH="${GHRS_FILES_ROOT_PATH:-/}"

# "When you specify an input to an action in a workflow file or use a default
# input value, GitHub creates an environment variable for the input with the
# name INPUT_<VARIABLE_NAME>. The environment variable created converts input
# names to uppercase letters and replaces spaces with _ characters."

# The data repository and the repository to fetch statistics for do not
# need to be the same!

# This is the repository to fetch data for.
STATS_REPOSPEC="${INPUT_REPOSITORY}"

# DATA_REPOSPEC is the repository to store data and report artifacts in.
# GITHUB_REPOSITORY is an environment variable specifying the repository this
# Action runs in. The repository this action runs in is (for now at least)
# by definition the data repository.
DATA_REPOSPEC="${GITHUB_REPOSITORY}"

# For local testing purposes: when run in a real GitHub Action then
# GITHUB_REPOSITORY cannot be set manually.

# allow using local copy of data repo for local testing.
if [ -z ${GHRS_DATA_REPOSPEC_OVERRIDE+x} ]; then
    echo "GHRS_DATA_REPOSPEC_OVERRIDE: not set"
else
    echo "GHRS_DATA_REPOSPEC_OVERRIDE set to '$GHRS_DATA_REPOSPEC_OVERRIDE'"
    echo "ignore GITHUB_REPOSITORY '$GITHUB_REPOSITORY'"
    DATA_REPOSPEC=${GHRS_DATA_REPOSPEC_OVERRIDE}
fi

# This is the API token used to fetch data (for the repo of interest) and
# to interact with the data repository.
export GHRS_GITHUB_API_TOKEN="${INPUT_GHTOKEN}"

# The name of the branch in the data repository.
DATA_BRANCH_NAME="${INPUT_DATABRANCH}"

# for diagnosis
echo "length of API TOKEN: ${#GHRS_GITHUB_API_TOKEN}"
echo "STATS_REPOSPEC: $STATS_REPOSPEC"
echo "DATA_REPOSPEC: $DATA_REPOSPEC"
echo "UPDATE_ID: $UPDATE_ID"

# I have seen in the wild that in some action workflows the current working
# directory is _not_ empty. In those cases, the `git clone` below may fail with
#  fatal: destination path '.' already exists and is not an empty directory.
# To conceptually prepare for this, create a new unique directory.
mkdir -p "$UPDATE_ID" && cd "$UPDATE_ID"

# allow using local copy of data repo for local testing.
if [ -z ${GHRS_TESTING_DATA_REPO_DIR+x} ]; then
    echo "GHRS_TESTING_DATA_REPO_DIR is unset"
else
    echo "GHRS_TESTING_DATA_REPO_DIR is set to '$GHRS_TESTING_DATA_REPO_DIR'"
    if [ ! -d "$GHRS_TESTING_DATA_REPO_DIR"/.git ]; then
        echo "does not appear to be a git repo. terminate."
        exit 1
    fi
    # copy contents, including dotfiles: https://superuser.com/a/367303
    cp -r "$GHRS_TESTING_DATA_REPO_DIR"/. .
fi

if [ ! -d ".git" ]; then
    echo "use 'git ls-remote' to check if data branch exists in data repo"
    set +e
    # Check out data branch only if it exists. To minimize overhead, also see
    # https://stackoverflow.com/a/4568323/145400.
    set -x
    git ls-remote --exit-code --heads https://ghactions:${GHRS_GITHUB_API_TOKEN}@github.com/${DATA_REPOSPEC}.git "${DATA_BRANCH_NAME}"
    LS_ECODE=$?
    set +x
    set -e
    if [ $LS_ECODE -eq 2 ]; then
        # expected failure: DATA_BRANCH_NAME branch doesn't exist (yet).
        # Do full clone and create branch.
        echo "data branch $DATA_BRANCH_NAME does not exist, do full clone"
        set -x
        git clone https://ghactions:${GHRS_GITHUB_API_TOKEN}@github.com/${DATA_REPOSPEC}.git .
        # note that the above fails with
        #  fatal: destination path '.' already exists and is not an empty directory.
        # if this is run locally in a non-empty dir
        git remote set-url origin https://ghactions:${GHRS_GITHUB_API_TOKEN}@github.com/${DATA_REPOSPEC}.git
        git checkout -b "${DATA_BRANCH_NAME}"
        set +x
    elif [ $LS_ECODE -eq 0 ]; then
        echo "$DATA_BRANCH_NAME branch exists. Perform shallow clone."
        set -x
        git clone --single-branch --branch "${DATA_BRANCH_NAME}" https://ghactions:${GHRS_GITHUB_API_TOKEN}@github.com/${DATA_REPOSPEC}.git .
        set +x
    else
        # unexpected failure of git ls-remote
        echo "git ls-remote failed unexpectedly with code $LS_ECODE"
        exit 1
    fi
else
    echo ".git directory is present, treat current dir as correct data repo checkout"
fi


set -x
git config --local user.email "action@github.com"
git config --local user.name "GitHub Action"
set +x

# Do not write to the root of the repository, but to a directory named after
# the stats respository (owner/repo). So that this data repository can be used
# by GHRS for more than one stats repository using the same git branch.
mkdir -p "${STATS_REPOSPEC}"
cd "${STATS_REPOSPEC}"

echo "operating in $(pwd)"

mkdir -p newsnapshots
echo "fetch.py for ${STATS_REPOSPEC}"

# Have CPython emit its stderr data immediately to the attached streams to
# reduce the likelihood for bad order of log lines in the GH Action log viewer
# (seen `error: fetch.py returned with code 1 -- exit.` before the last line of
# the CPython stderr stream was shown.)

export PYTHONUNBUFFERED="on"

set +e
# Note that the *-raw.csv files contain each star/fork event. These files do
# for now not need to be in the repository (but it will make sense to store
# them there once addressing the 10k star problem).
set -x
python "${GHRS_FILES_ROOT_PATH}/fetch.py" "${STATS_REPOSPEC}" \
    --snapshot-directory=newsnapshots \
    --fork-ts-outpath=forks-raw.csv \
    --stargazer-ts-outpath=stars-raw.csv
FETCH_ECODE=$?
set +x
set -e

if [ $FETCH_ECODE -ne 0 ]; then
    # Try to work around sluggish stderr/out interleaving in GH Action's log
    # viewer, give CPython's stderr emitted above a little time to be captured
    # and forwarded by the GH Action log viewer.
    sleep 0.1
    echo "error: fetch.py returned with code ${FETCH_ECODE} -- exit."
    exit $FETCH_ECODE
fi

echo "fetch.py returned with exit code 0. proceed."
echo "tree in $(pwd)/newsnapshots:"
tree newsnapshots

set -x
mkdir -p ghrs-data/snapshots
cp -a newsnapshots/* ghrs-data/snapshots || echo "copy failed, ignore (continue)"

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
set +e
set -x
python "${GHRS_FILES_ROOT_PATH}/analyze.py" \
    --resources-directory "${GHRS_FILES_ROOT_PATH}/resources" \
    --output-directory latest-report \
    --outfile-prefix "" \
    --stargazer-ts-inpath "stars-raw.csv" \
    --fork-ts-inpath "forks-raw.csv" \
    --stargazer-ts-resampled-outpath "ghrs-data/stargazers.csv" \
    --fork-ts-resampled-outpath "ghrs-data/forks.csv" \
    --views-clones-aggregate-outpath "ghrs-data/views_clones_aggregate.csv" \
    --views-clones-aggregate-inpath "ghrs-data/views_clones_aggregate.csv" \
    --delete-ts-fragments \
    "${STATS_REPOSPEC}" ghrs-data/snapshots
ANALYZE_ECODE=$?
set +x
set -e

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
# Note that either of ghrs-data/forks.csv or ghrs-data/stargazers.csv may
# be missing
git add ghrs-data/forks.csv ghrs-data/stargazers.csv || echo "git add failed, ignore (continue)"
git commit -m "ghrs: stars and forks ${UPDATE_ID} for ${STATS_REPOSPEC}" || echo "commit failed, ignore  (continue)"

echo "Translate HTML report into PDF, via headless Chrome"
python "${GHRS_FILES_ROOT_PATH}/pdf.py" latest-report/report_for_pdf.html latest-report/report.pdf

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

if [ -z ${GHRS_TESTING+x} ]; then
    echo "GHRS_TESTING is unset"
else
    echo "GHRS_TESTING is set. terminate before push/pull loop"
    exit 0
fi

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

    # Do a pull right before the push. They should be looked at as an 'atomic
    # unit', doing them right after one another in repeated fashion is the
    # recipe for long-term convergence here. The first push is quite likely to
    # succeed though: it is very unlikely that another racer pushes between the
    # pull/push below.

    # The pull may however also fail. In that case, stay in the loop. Two
    # expected pull failure modes that we thought about so far:
    #
    # - transient issues -- in thase case it's good to retry
    # - when further above the data branch was freshly created in the local
    #   checkout then this pull fails with "There is no tracking information
    #   for the current branch." -- in that case the subsequent push will
    #   succeed, and create the remote branch.

    set -x
    git pull origin "${DATA_BRANCH_NAME}" || echo "pull failed, ignore (continue)"

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
