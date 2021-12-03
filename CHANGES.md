# Changelog

## 1.3.0 (2021-12-03)

Thanks for all the feedback and contributions.

Report improvements:

* Automatically use semi-logarithmic plotting when it appears to make sense. This is supposed to help in cases of traffic spikes much higher than the baseline. (With linear plotting, the normal traffic level would then appear to be very close to zero, and variations around it would hardly be visible.)
* Add data point tooltips as mouse hover effect in the HTML report (also see #28).
* Display cumulative view/clone counts (total count until day of report generation, also see #31).
* Top referrer/path plots: move the legend so that these plots have the same width as all other plots, making comparison easier.
* Synchronize date axes where it makes sense:
  * The plots for view/clone data now all show the same time window.
  * The plots for star/fork data always show the same time window.
  * The star/fork plots only show the same time window as the view/clone plots when data collection started at the time of or before the first star/fork event. Else, the star/fork plots go further into the past.
* Create a meaningful fork/stargazer section for the special cases of zero forks/stars, respectively (also see #41, #43).
* Tweak plot style (marker size, tick label angle, and others).

Job robustness and performance:

* Perform a shallow clone of the data repository for faster job execution (#32, #34).

Bug fixes:

* Fix a path/referrer snapshot time series aggregation bug where a significant fraction of the available data was not visualized (#36).
* View/clone analysis: do not crash anymore when there is an aggregate file but no new snapshots (#37).
* Fix `git pull` and `git push` errors for the first-run scenario where the data branch does not yet exist on the data repository (see #30, #33, #35).

Misc:

* Reduce log verbosity.
* Update several dependencies (for example, use Altair 4.2.0 with Vega-Lite 4.17.0).

**Testing:** important changes coming hand-in-hand with this release are on the testing and continuous integration (CI) front.
Given the growing user base, I did not feel comfortable anymore with the reliance on manual testing.
I introduced a framework for high-level CLI invocation tests with specific data scenarios, now executed by CI as part of every commit.
This will help prevent regressions from happening.
The `README` contains instructions for how to run these tests locally.
I have also introduced more linting, and added a `mypy` check to CI (starting out with very basic typing information in the code base here and there).

## 1.2.0 (2021-09-11)

Data handling:

* Fix an edge case for exclusively empty views/clones fragments ([issue #15](https://github.com/jgehrcke/github-repo-stats/issues/15)).
* Expect an edge case where `fetch.py` exits without having generated new snapshot files: in that case, regenerate the report using the most recent set of data ([issue #17](https://github.com/jgehrcke/github-repo-stats/issues/17)).

Documentation:

* Fix cron syntax in README ([issue #20](https://github.com/jgehrcke/github-repo-stats/issues/20)).
* Document elegant method for a multi-repo workflow using the `matrix` approach ([PR #26](https://github.com/jgehrcke/github-repo-stats/pull/26)). Thanks to David Farrell and to Egil Hansen.

Job robustness and performance:

* Use a pre-built Docker container image ([jgehrcke/github-repo-stats-base](https://hub.docker.com/r/jgehrcke/github-repo-stats-base)) to base this action on. This image includes heavy Python and browser dependencies. This approach significantly reduces the probability for an action run to fail as of one of the many potential transient issues affecting a complex Docker image build. This also significantly reduces the time it takes for completing the `Build container for action use` build step (from ~2 minutes to ~30 seconds). Context: [issue #24](https://github.com/jgehrcke/github-repo-stats/issues/24) and [PR #25](https://github.com/jgehrcke/github-repo-stats/pull/25). If you have security concerns please open an issue and let's talk it through.

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
