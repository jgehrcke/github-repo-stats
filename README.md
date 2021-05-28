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

## Highlights

* The report is generated in two document formats: HTML and PDF.
* The HTML report resembles how GitHub renders Markdown and is meant to be exposed via GitHub pages.
* Charts are based on [Altair](https://github.com/altair-viz/altair)/[Vega](https://vega.github.io/vega/).
* The PDF report contains vector graphics.
* Data updates, aggregation results, and report files are stored in the git repository that you install this Action in: this Action commits changes to a special branch. No cloud storage or database needed. As a result, you have complete and transparent history for data updates and reports, with clear commit messages, in a single place.
* The observed repository (the one to build the report for) can be different from the repository you install this Action in.
* The HTML report can be served right away via GitHub pages (that is how the demo above works).
* Careful data analysis: there are a number of traps ([example](https://github.com/jgehrcke/github-repo-stats/blob/5fefc527288995e2e7e35593db496451580f51db/analyze.py#L748)) when aggregating data based on what the GitHub Traffic API returns. This project tries to not fall for them. One goal of this project is to perform [advanced analysis](https://github.com/jgehrcke/github-repo-stats/blob/5fefc527288995e2e7e35593db496451580f51db/analyze.py#L478) where possible.

**As of now, the report contains:**

* Traffic stats:
  * Unique and total views per day
  * Unique and total clones per day
  * Top referrers (where people come from when they land in your repository)
  * Top paths (what people like to look at in your repository)
* Evolution of stargazers
* Evolution of forks

## Documentation

### Clarification: "stats repository" vs. "data repository"

Naming is hard :-). Let's define two concepts and their names:

* The *stats repository* is the repository to fetch stats for and to generate the report for.
* The *data repository* is the repository to store data and report files in.

These two repositories can be the same. But they don't have to be :-).

That is, you can for example set up this Action in a private repository but have it observe a public repository.

### Setup

Example scenario:

* stats repository: `bob/nice-project`
* data repository: `bob/private-ghrs-data-repo`

Create a GitHub Actions workflow file in the *data repository* (in the example this is the repo `bob/private-ghrs-data-repo`). Example path: `.github/workflows/repostats-for-nice-project.yml`.

Example workflow file content with code comments:

```yaml
on:
  schedule:
    # Run this once per day, towards the end of the day for keeping the most
    # recent data point most meaningful (hours are interpreted in UTC).
    - cron: "0 23 * * *"
  workflow_dispatch: # Allow for running this manually.

jobs:
  j1:
    name: repostats-for-nice-project
    runs-on: ubuntu-latest
    steps:
      - name: run-ghrs
        uses: jgehrcke/github-repo-stats@v1.1.0
        with:
          # Define the stats repository (the repo to fetch
          # stats for and to generate the report for).
          # Remove the parameter when the stats repository
          # and the data repository are the same.
          repository: bob/nice-project
          # Set a GitHub API token that can read the stats
          # repository, and that can push to the data
          # repository (which this workflow file lives in),
          # to store data and the report files.
          ghtoken: ${{ secrets.ghrs_github_api_token }}

```

**Note:** the recommended way to run this Action is on a schedule, once per day. Really.

**Note:** if you set `ghtoken: ${{ secrets.ghrs_github_api_token }}` as above then in the _data_ repository (where the action is executed) you need to have a secret defined, with the name `GHRS_GITHUB_API_TOKEN` (of course you can change the name in both places).
The content of the secret needs to be an API token that has the `repo` scope for accessing the _stats_ repository.
You can create such a personal access token under https://github.com/settings/tokens.

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

It's recommended that you create the data branch and delete all files from that branch before setting this Action up in your reposistory, so that this data branch appears as a tidy environment.
You can of course do that later, too.

## Further resources

* [“GitHub Stars” -- useful for *what*?](https://opensource.stackexchange.com/questions/5110/github-stars-is-a-very-useful-metric-but-for-what/5114#5114)
* [GitHub Traffic API docs](https://docs.github.com/en/free-pro-team@latest/rest/reference/repos#traffic)
* [Do your own views count?](https://stackoverflow.com/a/63697886/145400)
