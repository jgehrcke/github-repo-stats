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
import textwrap
import json
import glob
import subprocess
import shutil
import sys
from datetime import datetime
from io import StringIO

import pandas as pd
from github import Github
import requests
import retrying
import pytz

import matplotlib
from matplotlib import pyplot as plt


"""
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

NOW = datetime.utcnow()
TODAY = NOW.strftime("%Y-%m-%d")
OUTDIR = None


def analyse_referrer_snapshots(args):
    log.info("read referrer snapshots (CSV docs)")
    referrer_csvpaths = glob.glob(
        os.path.join(args.csvdir, "*_top_referrers_snapshot.csv")
    )
    log.info(
        "number of CSV files discovered for *_top_referrers_snapshot.csv %s",
        len(referrer_csvpaths),
    )
    dfs = []
    column_names_seen = set()
    for p in referrer_csvpaths:
        log.info("attempt to parse %s", p)
        # Expect each filename (basename) to have a prefix of format
        # %Y-%m-%d_%H%M%S encoding the snapshot time (in UTC).
        pprefix = os.path.basename(p).split("_top_referrers_snapshot.csv")[0]
        snapshot_time = pytz.timezone("UTC").localize(
            datetime.strptime(pprefix, "%Y-%m-%d_%H%M%S")
        )
        log.info("parsed timestamp from path: %s", snapshot_time)

        df = pd.read_csv(p)
        # Oversight. Maybe fix in CSVs?
        df.rename(columns={"referrers": "referrer"}, inplace=True)

        if column_names_seen and set(df.columns) != column_names_seen:
            log.error("columns seen so far: %s", column_names_seen)
            log.error("columns in %s: %s", p, df.columns)
            sys.exit(1)

        # attach snapshot time as meta data prop to df
        df.attrs["snapshot_time"] = snapshot_time

        column_names_seen.update(df.columns)
        dfs.append(df)

    for df in dfs:
        print(df)

    referrers = set()
    for df in dfs:
        referrers.update(df["referrer"].values)

    log.info("all referrers seen: %s", referrers)

    # Add bew column to each dataframe: `time`, with the same value for every
    # row: the snapshot time.
    for df in dfs:
        df["time"] = df.attrs["snapshot_time"]

    dfa = pd.concat(dfs)
    referrer_dfs = {}
    for referrer in referrers:
        log.info("create dataframe for referrer: %s", referrer)
        # Do a subselection
        rdf = dfa[dfa["referrer"] == referrer]
        # Now use datetime column as index
        rdf.index = rdf["time"]
        rdf.drop(columns=["time"])
        rdf = rdf.sort_index()
        print(rdf)
        referrer_dfs[referrer] = rdf

    # for df in dfs:
    #     print(df)

    # # dfat = dfa.transpose()
    # # dfx = dfa.groupby("referrers").cumcount()
    # dfa["refindex"] = dfa.groupby("referrers").cumcount()
    # dfa.set_index("refindex", append=True)
    # print(dfa)

    # # Build the set of all top referrers seen.
    # # eferrer_dfs = {}

    sys.exit(0)


def main():

    args = parse_args()

    analyse_referrer_snapshots(args)

    log.info("read views/clones time series fragments (CSV docs)")
    views_clones_csvpaths = glob.glob(os.path.join(args.csvdir, "*views_clones*.csv"))
    log.info(
        "number of CSV files discovered for views/clones: %s",
        len(views_clones_csvpaths),
    )

    dfs = []
    column_names_seen = set()
    for p in views_clones_csvpaths:
        log.info("attempt to parse %s", p)

        df = pd.read_csv(
            p,
            index_col=["time_iso8601"],
            date_parser=lambda col: pd.to_datetime(col, utc=True),
        )
        if column_names_seen and set(df.columns) != column_names_seen:
            log.error("columns seen so far: %s", column_names_seen)
            log.error("columns in %s: %s", p, df.columns)
            sys.exit(1)

        column_names_seen.update(df.columns)
        dfs.append(df)

    for df in dfs:
        print(df)

    log.info("total sample count: %s", sum(len(df) for df in dfs))
    log.info("build aggregate, drop duplicate data")

    dfa = pd.concat(dfs)
    dfa.sort_index(inplace=True)

    # Rename index (now of type `pd.DatetimeIndex`)
    dfa.index.rename("time", inplace=True)

    print(dfa)

    # drop_duplicates is too ignorant!
    # df_agg.drop_duplicates(inplace=True, keep="last")

    # Each dataframe corresponds to one time series fragment obtained from the
    # GitHub API. I've found that at the boundaries, the values returned by the
    # API may be inconsistent. For example, in a snapshot obtained Dec 15 the
    # sample for Dec 7 is within the mid part of the fragment and shows a value
    # of 73 for `clones_total`. The snapshot obtained on Dec 21 has the Dec 7
    # sample at the boundary towards the past, and that shows a value of 18 for
    # `clones_total`. That is, for aggregation we have to look for the max data
    # values for any given timestamp.
    df_agg = dfa.groupby(dfa.index).max()
    print(df_agg)

    # matplotlib_config()
    # log.info("aggregated sample count: %s", len(df_agg))
    # df_agg.plot(
    #     linestyle="solid",
    #     marker="o",
    #     markersize=5,
    #     subplots=True,
    #     # ylabel="count",
    #     xlabel="",
    #     # logy="sym",
    # )

    # plt.ylim([0, None])
    # plt.tight_layout()

    # plt.show()

    import altair as alt

    # alt.Chart(df_agg).mark_bar().encode(
    # x='x',
    # y='y',
    # )

    # for reset_index() see
    # https://github.com/altair-viz/altair/issues/271#issuecomment-573480284
    df_agg = df_agg.reset_index()

    df_agg_views = df_agg.drop(columns=["clones_unique", "clones_total"])
    df_agg_clones = df_agg.drop(columns=["views_unique", "views_total"])

    # for melt, see https://github.com/altair-viz/altair/issues/968
    # df_agg_views = df_agg.melt("time")
    # print(df_agg)

    ## .mark_area(color="lightblue", interpolate="step-after", line=True)
    # pip carbonplan[styles]

    alt.themes.enable("carbonplan_light")
    # https://github.com/altair-viz/altair/issues/673#issuecomment-566567828
    alt.renderers.set_embed_options(actions=False)

    PANEL_WIDTH = 360
    # PANEL_WIDTH = "container"
    PANEL_HEIGHT = 250

    panel_props = {"height": PANEL_HEIGHT, "width": PANEL_WIDTH, "padding": 10}

    chart_clones_unique = (
        (
            alt.Chart(df_agg_clones)
            .mark_line(point=True)
            .encode(
                alt.X("time", type="temporal", title="date"),
                alt.Y(
                    "clones_unique",
                    type="quantitative",
                    title="unique clones per day",
                    scale=alt.Scale(
                        domain=(0, df_agg_clones["clones_unique"].max() * 1.1),
                        zero=True,
                    ),
                ),
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=100)
        .properties(**panel_props)
    )

    chart_clones_total = (
        (
            alt.Chart(df_agg_clones)
            .mark_line(point=True)
            .encode(
                alt.X("time", type="temporal", title="date"),
                alt.Y(
                    "clones_total",
                    type="quantitative",
                    title="total clones per day",
                    scale=alt.Scale(
                        domain=(0, df_agg_clones["clones_total"].max() * 1.1),
                        zero=True,
                    ),
                ),
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=100)
        .properties(**panel_props)
    )

    chart_views_unique = (
        (
            alt.Chart(df_agg_views)
            .mark_line(point=True)
            .encode(
                alt.X("time", type="temporal", title="date"),
                alt.Y(
                    "views_unique",
                    type="quantitative",
                    title="unique views per day",
                    scale=alt.Scale(
                        domain=(0, df_agg_views["views_unique"].max() * 1.1),
                        zero=True,
                    ),
                ),
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=100)
        .properties(**panel_props)
    )

    chart_views_total = (
        (
            alt.Chart(df_agg_views)
            .mark_line(point=True)
            .encode(
                alt.X("time", type="temporal", title="date"),
                alt.Y(
                    "views_total",
                    type="quantitative",
                    title="total views per day",
                    scale=alt.Scale(
                        domain=(0, df_agg_views["views_total"].max() * 1.1),
                        zero=True,
                    ),
                ),
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=100)
        .properties(**panel_props)
    )

    # chart_views_unique.configure_axisY(labelFlush=True, labelFlushOffset=100)

    # alt.vconcat(
    #     alt.hconcat(chart_clones_unique, chart_clones_total),
    #     alt.hconcat(chart_views_unique, chart_views_total),
    # ).resolve_scale(x="shared").save("chart.html")

    # alt.hconcat(
    #     alt.vconcat(chart_clones_unique, chart_clones_total)
    #     .resolve_scale(x="shared")
    #     .properties(title="Clones"),
    #     alt.vconcat(chart_views_unique, chart_views_total)
    #     .resolve_scale(x="shared")
    #     .properties(title="Views"),
    # ).save("chart.html", embed_options={"renderer": "svg"})

    # https://github.com/altair-viz/altair/issues/1422#issuecomment-525866028
    # chart.show()
    # chart_clones_total.save("chart.html")

    chart_views_unique_spec = chart_views_unique.to_json(indent=None)
    chart_views_total_spec = chart_views_total.to_json(indent=None)
    chart_clones_unique_spec = chart_clones_unique.to_json(indent=None)
    chart_clones_total_spec = chart_clones_total.to_json(indent=None)

    # https://github.com/vega/vega-embed#options
    vega_embed_opts_json = json.dumps({"actions": False, "renderer": "svg"})

    now_text = NOW.strftime("%Y-%m-%d %H:%M UTC")
    markdownreport = StringIO()
    markdownreport.write(
        textwrap.dedent(
            f"""
    % Statistics for {args.repospec}
    % Generated with [jgehrcke/github-repo-stats](https://github.com/jgehrcke/github-repo-stats) at {now_text}.

    """
        ).strip()
    )

    markdownreport.write(
        textwrap.dedent(
            f"""


    ## Views

    <div id="chart_views_unique"></div>
    <div id="chart_views_total"></div>


    ## Clones

    <div id="chart_clones_unique"></div>
    <div id="chart_clones_total"></div>


    <script type="text/javascript">
    vegaEmbed('#chart_views_unique', {chart_views_unique_spec}, {vega_embed_opts_json}).catch(console.error);
    vegaEmbed('#chart_views_total', {chart_views_total_spec}, {vega_embed_opts_json}).catch(console.error);
    vegaEmbed('#chart_clones_unique', {chart_clones_unique_spec}, {vega_embed_opts_json}).catch(console.error);
    vegaEmbed('#chart_clones_total', {chart_clones_total_spec}, {vega_embed_opts_json}).catch(console.error);
    </script>

    """
        )
    )

    report_md_text = markdownreport.getvalue()
    md_report_filepath = os.path.join(OUTDIR, TODAY + "_report.md")
    log.info("Write generated Markdown report to: %s", md_report_filepath)
    with open(md_report_filepath, "wb") as f:
        f.write(report_md_text.encode("utf-8"))

    log.info("Copy resources directory into output directory")
    shutil.copytree(args.resources_directory, os.path.join(OUTDIR, "resources"))

    html_report_filepath = os.path.splitext(md_report_filepath)[0] + ".html"
    log.info("Trying to run Pandoc for generating HTML document")
    pandoc_cmd = [
        args.pandoc_command,
        # For allowing raw HTML in Markdown, ref
        # https://stackoverflow.com/a/39229302/145400.
        "--from=markdown_strict+pandoc_title_block",
        # "--toc",
        "--standalone",
        "--template=resources/template.html",
        md_report_filepath,
        "-o",
        html_report_filepath,
    ]
    log.info("Running command: %s", " ".join(pandoc_cmd))
    p = subprocess.run(pandoc_cmd)
    if p.returncode == 0:
        log.info("Pandoc terminated indicating success")
    else:
        log.info("Pandoc terminated indicating error")


def parse_args():
    global OUTDIR
    parser = argparse.ArgumentParser(description="")
    parser.add_argument("repospec", help="repo owner/name")
    parser.add_argument(
        "csvdir", metavar="PATH", help="path to directory containing CSV files"
    )
    parser.add_argument("--pandoc-command", default="pandoc")
    parser.add_argument("--resources-directory", default="resources")
    parser.add_argument("--output-directory", default=TODAY + "_report")
    args = parser.parse_args()

    if os.path.exists(args.output_directory):
        if not os.path.isdir(args.output_directory):
            log.error(
                "The specified output directory path does not point to a directory: %s",
                args.output_directory,
            )
            sys.exit(1)

        log.info("Remove output directory: %s", args.output_directory)
        shutil.rmtree(args.output_directory)

    log.info("Create output directory: %s", args.output_directory)
    os.makedirs(args.output_directory)

    OUTDIR = args.output_directory

    return args


def matplotlib_config():
    plt.style.use("ggplot")
    # import seaborn as sns

    # make the gray background of gg plot a little lighter
    plt.rcParams["axes.facecolor"] = "#eeeeee"
    matplotlib.rcParams["figure.figsize"] = [10.5, 7.0]
    matplotlib.rcParams["figure.dpi"] = 100
    matplotlib.rcParams["savefig.dpi"] = 150
    # mpl.rcParams['font.size'] = 12


if __name__ == "__main__":
    main()