# github-repo-stats

A GitHub Action to periodically inspect a target repository and generate a report for it.

The primary purpose of this Action is to overcome the [14-day limitation](https://github.com/isaacs/github/issues/399) of GitHub's built-in traffic statistics.

## Demo

* Report:
  * [HTML report](https://jgehrcke.github.io/ghrs-test/jgehrcke/covid-19-germany-gae/latest-report/report.html)
  * [PDF report](https://jgehrcke.github.io/ghrs-test/jgehrcke/covid-19-germany-gae/latest-report/report.pdf)
* Action setup (how the above's report is generated):
  * [Workflow file](https://github.com/jgehrcke/ghrs-test/blob/github-repo-stats/.github/workflows/github-repo-stats.yml)
  * [Data branch](https://github.com/jgehrcke/ghrs-test/tree/github-repo-stats/jgehrcke/covid-19-germany-gae)


## Features

* The report is generated as an HTML document, with a plotting solution based on [Altair](https://github.com/altair-viz/altair)/[Vega](https://vega.github.io/vega/).
* The report is also generated as a PDF document from the HTML document, using a headless browser.
* Charts are rendered with SVG elements, and therefore the PDF report contains vector graphics, too.
* Data updates, aggregation results, and report files are stored in the git repository that you install this Action in: this Action commits changes to a special branch. No cloud storage or database needed. As a result, you have complete and transparent history for data updates and reports, with clear commit messages, in a single place.
* The observed repository (the one to build the report for) can be different from the repository you install this Action in.
* Careful data handling: there are a number of traps when aggregating data based on what the GitHub Traffic API returns. This project tries to not fall for them.


**The report contains:**

* Traffic stats:
  * Unique and total views per day
  * Unique and total clones per day
  * Top referrers (where people come from when they land in your repository)
  * Top paths (what people like to look at in your repository)
* Evolution of stargazers
* Evolution of forks


## Documentation

### Clarification: "stats repository" vs. "data repository"

* The "stats repository" is the repository to fetch stats for and to generate the report for.
* The "data repository" is the repository to store data and report files in.

These two repositories can be the same. But they don't have to be :-).

That is, you can for example set up this Action in a private repository but have it observe  public repository.


### Setup

The recommended way to run this Action is on a schedule, once per day.

Create a GitHub Actions workflow file (for example `.github/workflows/github-repo-stats.yml`) with for example the following contents:

```yaml
on:
  schedule:
    # Run this once per day (hours in UTC time zone).
    - cron: "* 7 * * *"
  workflow_dispatch: # Allow for running this manually.

jobs:
  j1:
    name: github-repo-stats
    runs-on: ubuntu-latest
    steps:
      - name: GHRS
        uses: jgehrcke/github-repo-stats@HEAD
        with:
          # Define the target repository, the repo to fetch
          # stats for and to generate the report for.
          # Leave this undefined when stats repository
          # and data repository should be the same.
          repository: jgehrcke/covid-19-germany-gae
          # Required token privileges: Can read the target
          # repo, and can push to the repository this
          # workflow file lives in (to store data and
          # the report files).
          ghtoken: ${{ secrets.ghrs_github_api_token }}

```


### Input parameter reference

Extract from `action.yml`:

```yaml
  repository:
    description: >
      Repository spec (<owner-or-org>/<reponame>) for the repository to fetch
      statistics for.
    default: ${{ github.repository }}
  ghtoken:
    description: >
      GitHub API token for reading repo stats and for interacting with the data
      repo (must be set if repo to fetch stats for is not the data repo).
    default: ${{ github.token }}
  databranch:
    description: >
      Data branch: Branch to push data to (in the data repo).
    default: github-repo-stats
  ghpagesprefix:
    description: >
      Set this if the data branch in the data repo is exposed via GitHub pages.
      Must not end with a slash. Example: https://jgehrcke.github.io/ghrs-test
    default: none
```

It's recommended that you create the data branch and delete all files from that branch before setting this Aaction up in your reposistory, so that this data branch appears as a tidy environment.
You can of course do that later, too.

## Resources

* [GitHub Traffic API docs](https://docs.github.com/en/free-pro-team@latest/rest/reference/repos#traffic)
* [Do your own views count?](https://stackoverflow.com/a/63697886/145400)
