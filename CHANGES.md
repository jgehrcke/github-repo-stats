# Changelog

## 1.2.0 (2021-09-11)

Data handling:

- Fix an edge case for exclusively empty views/clones fragments ([issue #15](https://github.com/jgehrcke/github-repo-stats/issues/15)).
- Expect an edge case where `fetch.py` exits without having generated new snapshot files: in that case, regenerate the report using the most recent set of data ([issue #17](https://github.com/jgehrcke/github-repo-stats/issues/17)).

Documentation:

- Fix cron syntax in README ([issue #20](https://github.com/jgehrcke/github-repo-stats/issues/20)).
- Document elegant method for a multi-repo workflow using the `matrix` approach ([PR #26](https://github.com/jgehrcke/github-repo-stats/pull/26)). Thanks to David Farrell and to Egil Hansen.

Job robustness and performance:

- Use a pre-built Docker container image ([jgehrcke/github-repo-stats-base](https://hub.docker.com/r/jgehrcke/github-repo-stats-base)) to base this action on. This image includes heavy Python and browser dependencies. This approach significantly reduces the probability for an action run to fail as of one of the many potential transient issues affecting a complex Docker image build. This also significantly reduces the time it takes for completing the `Build container for action use` build step (from ~2 minutes to ~30 seconds). Context: [issue #24](https://github.com/jgehrcke/github-repo-stats/issues/24) and [PR #25](https://github.com/jgehrcke/github-repo-stats/pull/25). If you have security concerns please open an issue and let's talk it through.

## 1.1.0 (2021-04-14)

Job robustness:

- Consolidate data branch writing so that multiple jobs operating concurrently on the same branch are less likely to fail ([issue #9](https://github.com/jgehrcke/github-repo-stats/issues/9)). Thanks to Henry Bley-Vroman and Dmytro Chasovskyi for the feedback.
- Fix an edge case for missing path/referrer data ([issue #8](https://github.com/jgehrcke/github-repo-stats/issues/8)).
- Attempt to fix an edge case for missing views/clones data ([issue #11](https://github.com/jgehrcke/github-repo-stats/issues/11)).
- Log output: work towards less interleaved stdout/err in the GH Actions log viewer.

Data handling:

- Fix a rare view / clone count data loss condition ([issue #4](https://github.com/jgehrcke/github-repo-stats/issues/4)). Thanks to Davis J. McGregor.
- Write stargazer and fork time series to data repository as CSV files, with at most one data point per day (resampled).

Plot improvements:

- Synchronize the time window shown for stargazer and fork time series.
- Decrease marker size in the referrer / paths plots.

Report generation:

- Tweak CSS for mobile view / narrow screens.
- Link to stats repository in HTML report.

## 1.0.0 (2021-01-14)

Initial release.
