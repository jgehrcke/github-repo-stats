#!/usr/bin/env python
# Copyright 2018 - 2020 Dr. Jan-Philip Gehrcke
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

import argparse
import logging
import os
import json
from datetime import datetime

import sys

import pandas as pd
from github import Github
import requests
import retrying
import pytz


"""
prior art
https://github.com/MTG/github-traffic
https://github.com/nchah/github-traffic-stats/
https://github.com/sangonzal/repository-traffic-action

makes use of code and methods from my other projects at
https://github.com/jgehrcke/dcos-dev-prod-analysis
https://github.com/jgehrcke/bouncer-log-analysis
https://github.com/jgehrcke/goeffel
"""


log = logging.getLogger()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s:%(threadName)s: %(message)s",
    datefmt="%y%m%d-%H:%M:%S",
)


# Get tz-aware datetime object corresponding to invocation time.
NOW = pytz.timezone("UTC").localize(datetime.utcnow())
INVOCATION_TIME_STRING = NOW.strftime("%Y-%m-%d_%H%M%S")

if not os.environ.get("GHRS_GITHUB_API_TOKEN", None):
    sys.exit("error: environment variable GHRS_GITHUB_API_TOKEN empty or not set")

GHUB = Github(login_or_token=os.environ["GHRS_GITHUB_API_TOKEN"].strip(), per_page=100)


def main():
    args = parse_args()
    # Full name of repo with slash (including owner/org)
    repo = GHUB.get_repo(args.repo)
    log.info("Working with repository `%s`", repo)
    log.info("Request quota limit: %s", GHUB.get_rate_limit())

    (
        df_views_clones,
        df_referrers_snapshot_now,
        df_paths_snapshot_now,
    ) = fetch_all_traffic_api_endpoints(repo)

    outdir_path = args.output_directory
    log.info("current working directory: %s", os.getcwd())
    log.info("write output CSV files to directory: %s", outdir_path)

    df_views_clones.to_csv(
        os.path.join(
            outdir_path, f"{INVOCATION_TIME_STRING}_views_clones_series_fragment.csv"
        )
    )
    df_referrers_snapshot_now.to_csv(
        os.path.join(
            outdir_path, f"{INVOCATION_TIME_STRING}_top_referrers_snapshot.csv"
        )
    )
    df_paths_snapshot_now.to_csv(
        os.path.join(outdir_path, f"{INVOCATION_TIME_STRING}_top_paths_snapshot.csv")
    )

    log.info("done!")


def fetch_all_traffic_api_endpoints(repo):

    log.info("fetch top referrers")
    df_referrers_snapshot_now = referrers_to_df(fetch_top_referrers(repo))

    log.info("fetch top paths")
    df_paths_snapshot_now = paths_to_df(fetch_top_paths(repo))

    log.info("fetch data for clones")
    df_clones = clones_or_views_to_df(fetch_clones(repo), "clones")

    log.info("fetch data for views")
    df_views = clones_or_views_to_df(fetch_views(repo), "views")

    # Note that df_clones and df_views should have the same datetime index, but
    # there is no guarantee for that. Create two separate data frames, then
    # merge / align dynamically.
    if not df_clones.index.equals(df_views.index):
        log.info("special case: df_views and df_clones have different index")
    else:
        log.info("indices of df_views and df_clones are equal")

    log.info("union-merge views and clones")
    # https://pandas.pydata.org/pandas-docs/stable/user_guide/merging.html#set-logic-on-the-other-axes
    # Build union of the two data frames. Zero information loss, in case the
    # two indices aree different.
    df_views_clones = pd.concat([df_clones, df_views], axis=1, join="outer")
    log.info("df_views_clones:\n%s", df_views_clones)

    return df_views_clones, df_referrers_snapshot_now, df_paths_snapshot_now


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch traffic data for GitHub repository. Requires the "
        "environment variables GITHUB_USERNAME and GITHUB_APITOKEN to be set."
    )

    parser.add_argument(
        "repo",
        metavar="REPOSITORY",
        help="Owner/organization and repository. Must contain a slash. "
        "Example: coke/truck",
    )

    parser.add_argument(
        "--output-directory",
        type=str,
        default="",
        help="default: _ghrs_{owner}_{repo}",
    )

    args = parser.parse_args()

    if "/" not in args.repo:
        sys.exit("missing slash in REPOSITORY spec")

    ownerid, repoid = args.repo.split("/")
    outdir_path_default = f"_ghrs_{ownerid}_{repoid}"

    if not args.output_directory:
        args.output_directory = outdir_path_default

    log.info("processed args: %s", json.dumps(vars(args), indent=2))

    if os.path.exists(args.output_directory):
        if not os.path.isdir(args.output_directory):
            log.error(
                "the specified output directory path does not point to a directory: %s",
                args.output_directory,
            )
            sys.exit(1)

        log.info("output directory already exists: %s", args.output_directory)

    else:
        log.info("create output directory: %s", args.output_directory)
        log.info("absolute path: %s", os.path.abspath(args.output_directory))
        # If there is a race: do not error out.
        os.makedirs(args.output_directory, exist_ok=True)

    return args


def referrers_to_df(top_referrers):
    series_referrers = []
    series_views_unique = []
    series_views_total = []
    for p in top_referrers:
        series_referrers.append(p.referrer)
        series_views_total.append(int(p.count))
        series_views_unique.append(int(p.uniques))

    df = pd.DataFrame(
        data={
            "views_total": series_views_total,
            "views_unique": series_views_unique,
        },
        index=series_referrers,
    )
    df.index.name = "referrer"

    # Attach metadata to dataframe, still experimental -- also see
    # https://stackoverflow.com/q/52122674/145400
    df.attrs["snapshot_time"] = NOW.isoformat()
    return df


def paths_to_df(top_paths):

    series_url_paths = []
    series_views_unique = []
    series_views_total = []
    for p in top_paths:
        series_url_paths.append(p.path)
        series_views_total.append(int(p.count))
        series_views_unique.append(int(p.uniques))

    df = pd.DataFrame(
        data={
            "views_total": series_views_total,
            "views_unique": series_views_unique,
        },
        index=series_url_paths,
    )
    df.index.name = "url_path"

    # Attach metadata to dataframe, new as of pandas 1.0 -- also see
    # https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.attrs.html
    # https://github.com/pandas-dev/pandas/issues/28283
    # https://stackoverflow.com/q/52122674/145400
    df.attrs["snapshot_time"] = NOW.isoformat()
    return df


def clones_or_views_to_df(items, metric):
    assert metric in ["clones", "views"]

    series_count_total = []
    series_count_unique = []
    series_timestamps = []
    for sample in items:
        # GitHub API docs say
        # "Timestamps are aligned to UTC"
        # `sample.timestamp` is a naive datetime object. Make it tz-aware.
        ts_aware = pytz.timezone("UTC").localize(sample.timestamp)
        series_timestamps.append(ts_aware)
        series_count_total.append(int(sample.count))
        series_count_unique.append(int(sample.uniques))

    df = pd.DataFrame(
        data={
            f"{metric}_total": series_count_total,
            f"{metric}_unique": series_count_unique,
        },
        index=series_timestamps,
    )
    df.index.name = "time_iso8601"

    # log.info("built dataframe for %s:\n%s", metric, df)
    # log.info("dataframe datetimeindex detail: %s", df.index)
    return df


def handle_rate_limit_error(exc):

    if "wait a few minutes before you try again" in str(exc):
        log.warning("GitHub abuse mechanism triggered, wait 60 s, retry")
        return True

    if "403" in str(exc):
        if "Resource not accessible by integration" in str(exc):
            log.error(
                'this appears to be a permanent error, as in "access denied -- do not retry: %s',
                str(exc),
            )
            sys.exit(1)

        log.warning("Exception contains 403, wait 60 s, retry: %s", str(exc))
        # The request count quota is not necessarily responsible for this
        # exception, but it usually is. Log the expected local time when the
        # new quota arrives.
        unix_timestamp_quota_reset = GHUB.rate_limiting_resettime
        local_time = datetime.fromtimestamp(unix_timestamp_quota_reset)
        log.info("New req count quota at: %s", local_time.strftime("%Y-%m-%d %H:%M:%S"))
        return True

    # For example, `RemoteDisconnected` is a case I have seen in production.
    if isinstance(exc, requests.exceptions.RequestException):
        log.warning("RequestException, wait 60 s, retry: %s", str(exc))
        return True

    return False


@retrying.retry(wait_fixed=60000, retry_on_exception=handle_rate_limit_error)
def fetch_clones(repo):
    clones = repo.get_clones_traffic()
    return clones["clones"]


@retrying.retry(wait_fixed=60000, retry_on_exception=handle_rate_limit_error)
def fetch_views(repo):
    views = repo.get_views_traffic()
    return views["views"]


@retrying.retry(wait_fixed=60000, retry_on_exception=handle_rate_limit_error)
def fetch_top_referrers(repo):
    return repo.get_top_referrers()


@retrying.retry(wait_fixed=60000, retry_on_exception=handle_rate_limit_error)
def fetch_top_paths(repo):
    return repo.get_top_paths()


if __name__ == "__main__":
    main()
