setup() {
  load '/bats-libraries/bats-support/load.bash'
  load '/bats-libraries/bats-assert/load.bash'
  load '/bats-libraries/bats-file/load.bash'
}

@test "analyze.py: snapshots: some, vcagg: yes, stars: some, forks: none" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --output-directory $BATS_TEST_TMPDIR \
    --stargazer-ts-resampled-outpath stargazers-rs.csv \
    --fork-ts-resampled-outpath forks-rs.csv \
    --views-clones-aggregate-inpath tests/data/A/views_clones_aggregate.csv \
    --stargazer-ts-inpath=tests/data/A/stars.csv
  [ "$status" -eq 0 ]
}

@test "analyze.py: snapshots: some, vcagg: yes, stars: none, forks: some" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --output-directory $BATS_TEST_TMPDIR \
    --stargazer-ts-resampled-outpath stargazers-rs.csv \
    --fork-ts-resampled-outpath forks-rs.csv \
    --views-clones-aggregate-inpath tests/data/A/views_clones_aggregate.csv \
    --fork-ts-inpath=tests/data/A/forks.csv
  [ "$status" -eq 0 ]
}

@test "analyze.py: snapshots: some, vcagg: yes, stars: some, forks: some" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --output-directory $BATS_TEST_TMPDIR/outdir \
    --outfile-prefix "" \
    --stargazer-ts-resampled-outpath stargazers-rs.csv \
    --fork-ts-resampled-outpath forks-rs.csv \
    --views-clones-aggregate-inpath tests/data/A/views_clones_aggregate.csv \
    --fork-ts-inpath=tests/data/A/forks.csv \
    --stargazer-ts-inpath=tests/data/A/stars.csv
  [ "$status" -eq 0 ]
  assert_exist $BATS_TEST_TMPDIR/outdir/report_for_pdf.html
}

@test "analyze.py: snapshots: some, vcagg: no, stars: some, forks: some" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --fork-ts-resampled-outpath forks-rs.csv \
    --fork-ts-inpath=tests/data/A/forks.csv \
    --stargazer-ts-inpath=tests/data/A/stars.csv
  # when invoking `run` above with --separate-stderr then the var
  # $stderr is populated with stderr, but I could not make this work with
  # assert_output
  assert_output --partial "unexpected: no data for views/clones"
  [ "$status" -eq 1 ]
}