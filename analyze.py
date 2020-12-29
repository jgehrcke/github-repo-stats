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

# from collections import Counter,
from datetime import datetime
from io import StringIO

import pandas as pd
from github import Github
import requests
import retrying
import pytz

import altair as alt
import matplotlib

# from matplotlib import pyplot as plt


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

# Individual code sections are supposed to add to this in-memory Markdown
# document as they desire.
MD_REPORT = StringIO()
JS_FOOTER_LINES = []

# https://github.com/vega/vega-embed#options
VEGA_EMBED_OPTIONS_JSON = json.dumps({"actions": False, "renderer": "canvas"})


def main():
    args = parse_args()
    gen_report_preamble(args)
    configure_altair()
    analyse_view_clones_ts_fragments(args)
    analyse_top_x_snapshots("referrer", args)
    analyse_top_x_snapshots("path", args)
    gen_report_footer()
    finalize_and_render_report(args)


def configure_altair():
    # https://github.com/carbonplan/styles
    alt.themes.enable("carbonplan_light")
    # https://github.com/altair-viz/altair/issues/673#issuecomment-566567828
    alt.renderers.set_embed_options(actions=False)


def gen_report_footer():
    js_footer = "\n".join(JS_FOOTER_LINES)
    MD_REPORT.write(
        textwrap.dedent(
            f"""

    <script type="text/javascript">
    {js_footer}
    </script>

    """
        ).strip()
    )


def gen_report_preamble(args):
    now_text = NOW.strftime("%Y-%m-%d %H:%M UTC")
    MD_REPORT.write(
        textwrap.dedent(
            f"""
    % Statistics for {args.repospec}
    % Generated with [jgehrcke/github-repo-stats](https://github.com/jgehrcke/github-repo-stats) at {now_text}.

    """
        ).strip()
    )


def finalize_and_render_report(args):
    md_report_filepath = os.path.join(OUTDIR, TODAY + "_report.md")
    log.info("Write generated Markdown report to: %s", md_report_filepath)
    with open(md_report_filepath, "wb") as f:
        f.write(MD_REPORT.getvalue().encode("utf-8"))

    log.info("Copy resources directory into output directory")
    shutil.copytree(args.resources_directory, os.path.join(OUTDIR, "resources"))

    html_report_filepath = os.path.splitext(md_report_filepath)[0] + ".html"
    log.info("Trying to run Pandoc for generating HTML document")
    pandoc_cmd = [
        args.pandoc_command,
        # For allowing raw HTML in Markdown, ref
        # https://stackoverflow.com/a/39229302/145400.
        "--from=markdown+pandoc_title_block+native_divs",
        "--toc",
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


def top_x_snapshots_rename_columns(df):
    # mutate in-place.

    # As always, naming is hard. Names get clearer over time. Work with data
    # files that have non-ideal names. Semantically, there is a column name
    # oversight -- plural vs. singular. Maybe fix in CSVs? Either one of both
    # renames or both renames are OK to fail.
    try:
        df.rename(columns={"referrers": "referrer"}, inplace=True)
    except ValueError:
        pass

    try:
        df.rename(columns={"url_paths": "path"}, inplace=True)
    except ValueError:
        pass

    try:
        df.rename(columns={"count_unique": "views_unique"}, inplace=True)
    except ValueError:
        pass

    try:
        df.rename(columns={"count_total": "views_total"}, inplace=True)
    except ValueError:
        pass


def analyse_top_x_snapshots(entity_type, args):
    assert entity_type in ["referrer", "path"]

    log.info("read 'top %s' snapshots (CSV docs)", entity_type)

    basename_suffix = f"_top_{entity_type}s_snapshot.csv"
    basename_pattern = f"*{basename_suffix}"
    csvpaths = glob.glob(os.path.join(args.csvdir, basename_pattern))
    log.info(
        "number of CSV files discovered for %s: %s",
        basename_pattern,
        len(csvpaths),
    )

    snapshot_dfs = []
    column_names_seen = set()

    for p in csvpaths:
        log.info("attempt to parse %s", p)

        # Expect each filename (basename) to have a prefix of format
        # %Y-%m-%d_%H%M%S encoding the snapshot time (in UTC).
        basename_prefix = os.path.basename(p).split(basename_suffix)[0]

        snapshot_time = pytz.timezone("UTC").localize(
            datetime.strptime(basename_prefix, "%Y-%m-%d_%H%M%S")
        )
        log.info("parsed timestamp from path: %s", snapshot_time)

        df = pd.read_csv(p)
        # mutate column names in-place.
        top_x_snapshots_rename_columns(df)

        if column_names_seen and set(df.columns) != column_names_seen:
            log.error("columns seen so far: %s", column_names_seen)
            log.error("columns in %s: %s", p, df.columns)
            log.error("inconsistent set of column names across CSV files")
            sys.exit(1)

        # attach snapshot time as meta data prop to df
        df.attrs["snapshot_time"] = snapshot_time

        column_names_seen.update(df.columns)
        snapshot_dfs.append(df)

    for df in snapshot_dfs:
        print(df)

    # Keep in mind: an entity_type is either a top 'referrer', or a top 'path'.
    # Find all entities seen across snapshots, by their name. For type referrer
    # a specific entity(referrer) name might be `github.com`.
    unique_entity_names = set()
    for df in snapshot_dfs:
        unique_entity_names.update(df[entity_type].values)
    del df

    log.info("all %s entities seen: %s", entity_type, unique_entity_names)

    # Add bew column to each dataframe: `time`, with the same value for every
    # row: the snapshot time.
    for df in snapshot_dfs:
        df["time"] = df.attrs["snapshot_time"]
    del df

    # Clarification: each snapshot dataframe corresponds to a single point in
    # time (the snapshot time) and contains information about multiple top
    # referrers/paths. Now, invert that structure: work towards individual
    # dataframes where each dataframe corresponds to a single referrer/path,
    # and contains imformation about multiple timestamps

    # First, create a dataframe containing all information.
    dfa = pd.concat(snapshot_dfs)

    # Build a dict: key is referrer name, and value is DF with corresponding
    # raw time series.
    entity_dfs = {}
    for ename in unique_entity_names:
        log.info("create dataframe for %s: %s", entity_type, ename)
        # Do a subselection
        edf = dfa[dfa[entity_type] == ename]
        # Now use datetime column as index
        newindex = edf["time"]
        edf = edf.drop(columns=["time"])
        edf.index = newindex
        edf = edf.sort_index()
        print(edf)
        entity_dfs[ename] = edf

    del ename
    del edf

    # It's important to clarify what each data point in a per-referrer raw time
    # series means. Each data point has been returned by the GitHub traffic
    # API. Each sample (row in the df) I think it can/should be looked at as
    # the result of a rolling window analysis that shows cumulative values
    # summed up over a period of 14 days; noted at the _right edge_ of the
    # rolling time window.

    # Should see further verification, but I think the boundaries of the time
    # window actually move with sub-day resolution, i.e. the same query
    # performed within the same day may yield different outcomes. If that's
    # true, the rolling time window analysis performed internally at GitHub can
    # be perfectly inversed; yielding per-referrer traffic statistics at a
    # sub-day time resolution. That of course will require predictable,
    # periodic sampling. Let's keep that in mind for now.

    # One interesting way to look at the data: find the top 5 referrers based
    # on unique views, and for the entire time range seen.

    max_vu_map = {}
    for ename, edf in entity_dfs.items():
        max_vu_map[ename] = edf["views_unique"].max()
    del ename

    # Sort dict so that the first item is the referrer/path with the highest
    # views_unique seen.
    sorted_dict = {
        k: v for k, v in sorted(max_vu_map.items(), key=lambda i: i[1], reverse=True)
    }

    top_n = 10
    top_n_enames = list(sorted_dict.keys())[:top_n]

    # simulate a case where there are different timestamps across per-referrer
    # dfs: copy a 'row', and re-insert it with a different timestamp.
    # row = referrer_dfs["t.co"].take([-1])
    # print(row)
    # referrer_dfs["t.co"].loc["2020-12-30 12:25:08+00:00"] = row.iloc[0]
    # print(referrer_dfs["t.co"])

    df_top_vu = pd.DataFrame()
    for ename in top_n_enames:
        edf = entity_dfs[ename]
        print(edf)
        df_top_vu[ename] = edf["views_unique"]
    del ename

    log.info(
        "The top %s %ss based on unique views, for the entire time range seen:\n%s",
        entity_type,
        top_n,
        df_top_vu,
    )

    # For plotting with Altair, reshape the data using pd.melt() to combine the
    # multiple columns into one, where the referrer name is not a column label,
    # but a value in a column. Ooor we could use the
    # transform_fold() technique
    # https://altair-viz.github.io/user_guide/data.html#converting-between-long-form-and-wide-form-pandas
    # with .transform_fold(top_n_rnames, as_=["referrer", "views_unique"])
    # Also copy index into a normal column via `reset_index()` for
    # https://altair-viz.github.io/user_guide/data.html#including-index-data
    df_melted = df_top_vu.melt(
        var_name=entity_type, value_name="views_unique", ignore_index=False
    ).reset_index()
    print(df_melted)

    # Normalize main metric to show a view count _per day_, and clarify in the
    # plot that this is a _mean_ value derived from the _last 14 days_.
    df_melted["views_unique_norm"] = df_melted["views_unique"] / 14.0

    # For paths, it's relevant to identify the common prefix (repo owner/name)

    cmn_ename_prefix = os.path.commonprefix(list(unique_entity_names))
    log.info("cmn_ename_prefix: %s", cmn_ename_prefix)

    if entity_type == "path":
        log.info("remove common path prefix")
        df_melted["path"] = df_melted["path"].str.slice(start=len(cmn_ename_prefix))
        # The root path (e.g., `owner/repo`) is not an empty string. That's
        # not so cool, make the root be represented by a single slash.
        # df_melted[df_melted["path"] == ""]["path"] = "/"
        df_melted["path"].replace("", "/", inplace=True)

    panel_props = {"height": 300, "width": "container", "padding": 10}
    chart = (
        alt.Chart(df_melted)
        .mark_line(point=True)
        # .encode(x="time:T", y="views_unique:Q", color="referrer:N")
        .encode(
            alt.X("time", type="temporal", title="date"),
            alt.Y(
                "views_unique_norm",
                type="quantitative",
                title="unique visitors per day (mean from last 14 days)",
                scale=alt.Scale(
                    domain=(0, df_melted["views_unique_norm"].max() * 1.1),
                    zero=True,
                ),
            ),
            alt.Color(
                entity_type,
                type="nominal",
                sort=alt.SortField("order"),
            ),
        )
        .configure_point(size=100)
        .properties(**panel_props)
    )

    chart_spec = chart.to_json(indent=None)

    # From
    # https://altair-viz.github.io/user_guide/customization.html
    # "Note that this will only scale with the container if its parent element
    # has a size determined outside the chart itself; For example, the
    # container may be a <div> element that has style width: 100%; height:
    # 300px.""

    heading = "Top referrers" if entity_type == "referrer" else "Top paths"

    MD_REPORT.write(
        textwrap.dedent(
            f"""

    ## {heading}


    <div id="chart_{entity_type}s_top_n_alltime" class="full-width-chart"></div>


    """
        )
    )
    JS_FOOTER_LINES.append(
        f"vegaEmbed('#chart_{entity_type}s_top_n_alltime', {chart_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);"
    )


def analyse_view_clones_ts_fragments(args):

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

    # print(dfa)

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
    # print(df_agg)

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

    # Why reset_index()? See
    # https://github.com/altair-viz/altair/issues/271#issuecomment-573480284
    df_agg = df_agg.reset_index()
    df_agg_views = df_agg.drop(columns=["clones_unique", "clones_total"])
    df_agg_clones = df_agg.drop(columns=["views_unique", "views_total"])

    # for melt, see https://github.com/altair-viz/altair/issues/968
    # df_agg_views = df_agg.melt("time")
    # print(df_agg)
    ## .mark_area(color="lightblue", interpolate="step-after", line=True)

    # PANEL_WIDTH = 360
    PANEL_WIDTH = "container"
    PANEL_HEIGHT = 200

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

    MD_REPORT.write(
        textwrap.dedent(
            f"""


    ## Views

    #### Unique visitors
    <div id="chart_views_unique" class="full-width-chart"></div>

    #### Total views
    <div id="chart_views_total" class="full-width-chart"></div>


    ## Clones

    #### Unique cloners
    <div id="chart_clones_unique" class="full-width-chart"></div>

    #### Total clones
    <div id="chart_clones_total" class="full-width-chart"></div>

    """
        )
    )
    JS_FOOTER_LINES.extend(
        [
            f"vegaEmbed('#chart_views_unique', {chart_views_unique_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);",
            f"vegaEmbed('#chart_views_total', {chart_views_total_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);",
            f"vegaEmbed('#chart_clones_unique', {chart_clones_unique_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);",
            f"vegaEmbed('#chart_clones_total', {chart_clones_total_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);",
        ]
    )


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