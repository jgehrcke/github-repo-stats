# Changelog

## 1.1.1 (in development)

* Fix an edge case for exclusively empty views/clones fragments ([issue #15](https://github.com/jgehrcke/github-repo-stats/issues/15)).

## 1.1.0 (2021-04-14)

Job robustness:

* Consolidate data branch writing so that multiple jobs operating concurrently on the same branch are less likely to fail ([issue #9](https://github.com/jgehrcke/github-repo-stats/issues/9)). Thanks to Henry Bley-Vroman and Dmytro Chasovskyi for the feedback.
* Fix an edge case for missing path/referrer data ([issue #8](https://github.com/jgehrcke/github-repo-stats/issues/8)).
* Attempt to fix an edge case for missing views/clones data ([issue #11](https://github.com/jgehrcke/github-repo-stats/issues/11)).
* Log output: work towards less interleaved stdout/err in the GH Actions log viewer.

Data handling:

* Fix a rare view / clone count data loss condition ([issue #4](https://github.com/jgehrcke/github-repo-stats/issues/4)). Thanks to Davis J. McGregor.
* Write stargazer and fork time series to data repository as CSV files, with at most one data point per day (resampled).

Plot improvements:

* Synchronize the time window shown for stargazer and fork time series.
* Decrease marker size in the referrer / paths plots.

Report generation:

* Tweak CSS for mobile view / narrow screens.
* Link to stats repository in HTML report.

## 1.0.0 (2021-01-14)

Initial release.
