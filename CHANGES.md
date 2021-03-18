# Changelog

## 1.1.0 (in development)

Data handling:

* Fix a rare view / clone count data loss condition ([issue #4](https://github.com/jgehrcke/github-repo-stats/issues/4)). Thanks to Davis J. McGregor.
* Write stargazer and fork timeseries to data repository as CSV files, with at most one data point per day (resampled).

Plot improvements:

* Synchronize the time window shown for stargazer and fork time series.
* Decrease marker size in the referrer / paths plots.

Report generation:

* Tweak CSS for mobile view / narrow screens.
* Link to stats repository in HTML report.

## 1.0.0 (2021-01-14)

Initial release.
