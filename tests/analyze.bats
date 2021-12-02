@test "analyze.py: snapshots: some, vcagg: yes, stars: some, forks: none" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --stargazer-ts-resampled-outpath stargazers-rs.csv \
    --fork-ts-resampled-outpath forks-rs.csv \
    --views-clones-aggregate-inpath tests/data/A/views_clones_aggregate.csv \
    --stargazer-ts-inpath=tests/data/A/stars.csv
  [ "$status" -eq 0 ]
}

@test "analyze.py: snapshots: some, vcagg: yes, stars: none, forks: some" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --stargazer-ts-resampled-outpath stargazers-rs.csv \
    --fork-ts-resampled-outpath forks-rs.csv \
    --views-clones-aggregate-inpath tests/data/A/views_clones_aggregate.csv \
    --fork-ts-inpath=tests/data/A/forks.csv
  [ "$status" -eq 0 ]
}

@test "analyze.py: snapshots: some, vcagg: yes, stars: some, forks: some" {
  run python analyze.py owner/repo tests/data/A/snapshots \
    --resources-directory=resources \
    --stargazer-ts-resampled-outpath stargazers-rs.csv \
    --fork-ts-resampled-outpath forks-rs.csv \
    --views-clones-aggregate-inpath tests/data/A/views_clones_aggregate.csv \
    --fork-ts-inpath=tests/data/A/forks.csv \
    --stargazer-ts-inpath=tests/data/A/stars.csv
  [ "$status" -eq 0 ]
}