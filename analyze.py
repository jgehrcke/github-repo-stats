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
import tempfile

from datetime import datetime
from io import StringIO

import pandas as pd
from github import Github
import pytz

import altair as alt


"""
makes use of code and methods from my other projects at
https://github.com/jgehrcke/dcos-dev-prod-analysis
https://github.com/jgehrcke/bouncer-log-analysis
https://github.com/jgehrcke/goeffel
"""


log = logging.getLogger()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%y%m%d-%H:%M:%S",
)


NOW = datetime.utcnow()
TODAY = NOW.strftime("%Y-%m-%d")
OUTDIR = None
ARGS = None


# Individual code sections are supposed to add to this in-memory Markdown
# document as they desire.
MD_REPORT = StringIO()
JS_FOOTER_LINES = []

# https://github.com/vega/vega-embed#options -- use SVG renderer so that PDF
# export (print) from browser view yields arbitrarily scalable (vector)
# graphics embedded in the PDF doc, instead of rasterized graphics.
VEGA_EMBED_OPTIONS_JSON = json.dumps({"actions": False, "renderer": "svg"})


def main():
    if not os.environ.get("GHRS_GITHUB_API_TOKEN", None):
        sys.exit("error: environment variable GHRS_GITHUB_API_TOKEN empty or not set")

    parse_args()
    configure_altair()

    df_stargazers = get_stars_over_time()
    df_forks = get_forks_over_time()

    gen_report_preamble()

    analyse_view_clones_ts_fragments()
    report_pdf_pagebreak()

    sf_date_axis_lim = None
    if len(df_stargazers) and len(df_forks):
        # Sync up the time window shown in the plots for forks and stars over time.
        sf_date_axis_lim = gen_date_axis_lim((df_stargazers, df_forks))
        log.info("time window for stargazer/fork plots: %s", sf_date_axis_lim)

    if len(df_stargazers):
        add_stargazers_section(df_stargazers, sf_date_axis_lim)

    if len(df_forks):
        add_fork_section(df_forks, sf_date_axis_lim)

    report_pdf_pagebreak()

    MD_REPORT.write(
        textwrap.dedent(
            """

    ## Top referrers and paths


    Note: Each data point in the plots shown below is influenced by the 14 days
    leading up to it. Each data point is the arithmetic mean of the "unique
    visitors per day" metric, built from a time window of 14 days width, and
    plotted at the right edge of that very time window. That is, these plots
    respond slowly to change (narrow peaks are smoothed out).

    """
        )
    )

    analyse_top_x_snapshots("referrer")
    analyse_top_x_snapshots("path")

    gen_report_footer()
    finalize_and_render_report()


def gen_date_axis_lim(dfs):
    # Find minimal first timestamp across dataframes, and maximal last
    # timestamp. Return in string representation, example:
    # ['2020-03-18', '2021-01-03']
    # Can be used for setting time axis limits in Altair.
    return (
        pd.to_datetime(min(df.index.values[0] for df in dfs)).strftime("%Y-%m-%d"),
        pd.to_datetime(max(df.index.values[-1] for df in dfs)).strftime("%Y-%m-%d"),
    )


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


def gen_report_preamble():
    now_text = NOW.strftime("%Y-%m-%d %H:%M UTC")
    attr_link = (
        "[jgehrcke/github-repo-stats](https://github.com/jgehrcke/github-repo-stats)"
    )
    MD_REPORT.write(
        textwrap.dedent(
            f"""
    % Statistics for {ARGS.repospec}
    % Generated for [{ARGS.repospec}](https://github.com/{ARGS.repospec}) with {attr_link} at {now_text}.

    """
        ).strip()
    )


def report_pdf_pagebreak():
    # This adds a div to the HTML report output that will only take effect
    # upon print, i.e. for PDF generation.
    # https://stackoverflow.com/a/1664058/145400
    MD_REPORT.write('\n\n<div class="pagebreak-for-print"> </div>\n\n')


def finalize_and_render_report():
    md_report_filepath = os.path.join(OUTDIR, f"{ARGS.outfile_prefix}report.md")
    log.info("Write generated Markdown report to: %s", md_report_filepath)
    with open(md_report_filepath, "wb") as f:
        f.write(MD_REPORT.getvalue().encode("utf-8"))

    log.info("Copy resources directory into output directory")
    shutil.copytree(ARGS.resources_directory, os.path.join(OUTDIR, "resources"))

    # Generate HTML doc for browser view
    html_template_filepath = gen_pandoc_html_template("html_browser_view")
    run_pandoc(
        md_report_filepath,
        html_template_filepath,
        html_output_filepath=os.path.splitext(md_report_filepath)[0] + ".html",
    )
    os.unlink(html_template_filepath)

    # Generate HTML doc that will be used for rendering a PDF doc.
    html_template_filepath = gen_pandoc_html_template("html_pdf_view")
    run_pandoc(
        md_report_filepath,
        html_template_filepath,
        html_output_filepath=os.path.splitext(md_report_filepath)[0] + "_for_pdf.html",
    )
    os.unlink(html_template_filepath)


def run_pandoc(md_report_filepath, html_template_filepath, html_output_filepath):

    pandoc_cmd = [
        ARGS.pandoc_command,
        # For allowing raw HTML in Markdown, ref
        # https://stackoverflow.com/a/39229302/145400.
        "--from=markdown+pandoc_title_block+native_divs",
        "--toc",
        "--standalone",
        f"--template={html_template_filepath}",
        md_report_filepath,
        "-o",
        html_output_filepath,
    ]

    log.info("Running command: %s", " ".join(pandoc_cmd))
    p = subprocess.run(pandoc_cmd)

    if p.returncode == 0:
        log.info("Pandoc terminated indicating success")
    else:
        log.info("Pandoc terminated indicating error: exit code %s", p.returncode)


def gen_pandoc_html_template(target):
    # Generally, a lot could be done with the same pandoc HTML template and
    # using CSS @media print. Took the more flexible and generic approach
    # here, though, where we're able to generate two completely different
    # HTML templates, if needed.

    assert target in ["html_browser_view", "html_pdf_view"]

    if target == "html_browser_view":
        main_style_block = textwrap.dedent(
            """
            <style>
                body {
                    box-sizing: border-box;
                    min-width: 200px;
                    max-width: 980px;
                    margin: 0 auto;
                    padding: 5px;
                }

                div.full-width-chart {
                    width: 100%;
                }
            </style>
        """
        )

    if target == "html_pdf_view":
        main_style_block = textwrap.dedent(
            """
            <style>
                @media print {
                  .pagebreak-for-print {
                      clear: both;
                      page-break-after: always;
                   }
                }

                body {
                    margin: 0;
                    padding: 0;
                }

                div.full-width-chart {
                    width: 100%;
                }
            </style>
        """
        )

    with open(os.path.join(ARGS.resources_directory, "template.html"), "rb") as f:
        tpl_text = f.read().decode("utf-8")

    # Do simple string replacement instead of picking one of the established
    # templating methods: the pandoc template language uses dollar signs, and
    # the CSS in the file uses curly braces.
    rendered_pandoc_template = tpl_text.replace("MAIN_STYLE_BLOCK", main_style_block)

    # Do a pragmatic close/unlink effort at end of program. It's not so bad in
    # this case when either does not happen. Note that if the temp file path
    # has no extension then pandoc seems to append `.html` before opening the
    # file -- which the fails with ENOENT.
    tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
    log.info("creating %s", tmpf.name)
    tmpf.write(rendered_pandoc_template.encode("utf-8"))
    tmpf.close()

    # Return path to pandoc template.
    return tmpf.name


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
        df.rename(columns={"url_path": "path"}, inplace=True)
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


def _get_snapshot_time_from_path(p, basename_suffix):
    # Expect each filename (basename) to have a prefix of format
    # %Y-%m-%d_%H%M%S encoding the snapshot time (in UTC). Isolate that as
    # tz-aware datetime object, return.
    basename_prefix = os.path.basename(p).split(basename_suffix)[0]
    t = pytz.timezone("UTC").localize(
        datetime.strptime(basename_prefix, "%Y-%m-%d_%H%M%S")
    )
    log.info("parsed timestamp from path: %s", t)
    return t


def _get_snapshot_dfs(csvpaths, basename_suffix):

    snapshot_dfs = []
    column_names_seen = set()

    for p in csvpaths:
        log.info("attempt to parse %s", p)
        snapshot_time = _get_snapshot_time_from_path(p, basename_suffix)
        df = pd.read_csv(p)

        # mutate column names in-place.
        top_x_snapshots_rename_columns(df)

        # attach snapshot time as meta data prop to df
        df.attrs["snapshot_time"] = snapshot_time

        # Add new column to each dataframe: `time`, with the same value for
        # every row: the snapshot time.
        df["time"] = snapshot_time

        if column_names_seen and set(df.columns) != column_names_seen:
            log.error("columns seen so far: %s", column_names_seen)
            log.error("columns in %s: %s", p, df.columns)
            log.error("inconsistent set of column names across CSV files")
            sys.exit(1)

        column_names_seen.update(df.columns)
        snapshot_dfs.append(df)

    return snapshot_dfs


def _build_entity_dfs(dfa, entity_type, unique_entity_names):

    cmn_ename_prefix = os.path.commonprefix(list(unique_entity_names))
    log.info("cmn_ename_prefix: %s", cmn_ename_prefix)

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

        # Do entity name processing
        if entity_type == "path":
            entity_name_transformed = ename[len(cmn_ename_prefix) :]
            # The root path (e.g., `owner/repo`) is now an empty string. That's
            # not so cool, make the root be represented by a single slash.
            if entity_name_transformed == "":
                entity_name_transformed = "/"
            edf.rename(columns={ename: entity_name_transformed}, inplace=True)
            # Also change `ename` from here on, so that `entity_dfs` is built
            # up using the transformed ename.
            ename = entity_name_transformed

        # Make it so that there is at most one data point per day, in case
        # individual snapshots were taken with higher frequency.
        n_hour_bins = 24
        log.info("len(edf): %s", len(edf))
        log.info("downsample entity DF into %s-hour bins", n_hour_bins)
        # Resample the DF into N-hour bins. Take max() for each group. Do
        # `dropna()` on the resampler to remove all up-sampled data points (in
        # case snapshots were taken at much lower frequency). Default behavior
        # of the resampling operation is to note the value for each bin at the
        # left edge of the bin, and to have the bin be closed on the left edge
        # (right edge of the bin belongs to next bin).
        edf = edf.resample(f"{n_hour_bins}h").max().dropna()
        log.info("len(edf): %s", len(edf))

        # print(edf)
        entity_dfs[ename] = edf

    return entity_dfs


def _glob_csvpaths(basename_suffix):
    basename_pattern = f"*{basename_suffix}"
    csvpaths = glob.glob(os.path.join(ARGS.snapshotdir, basename_pattern))
    log.info(
        "number of CSV files discovered for %s: %s",
        basename_pattern,
        len(csvpaths),
    )
    return csvpaths


def analyse_top_x_snapshots(entity_type):
    assert entity_type in ["referrer", "path"]

    log.info("read 'top %s' snapshots (CSV docs)", entity_type)
    basename_suffix = f"_top_{entity_type}s_snapshot.csv"
    csvpaths = _glob_csvpaths(basename_suffix)
    snapshot_dfs = _get_snapshot_dfs(csvpaths, basename_suffix)

    # for df in snapshot_dfs:
    #     print(df)

    # Keep in mind: an entity_type is either a top 'referrer', or a top 'path'.
    # Find all entities seen across snapshots, by their name. For type referrer
    # a specific entity(referrer) name might be `github.com`.

    def _get_uens(snapshot_dfs):
        unique_entity_names = set()
        for df in snapshot_dfs:
            unique_entity_names.update(df[entity_type].values)

        return unique_entity_names

    unique_entity_names = _get_uens(snapshot_dfs)
    log.info("all %s entities seen: %s", entity_type, unique_entity_names)

    # Clarification: each snapshot dataframe corresponds to a single point in
    # time (the snapshot time) and contains information about multiple top
    # referrers/paths. Now, invert that structure: work towards individual
    # dataframes where each dataframe corresponds to a single referrer/path,
    # and contains imformation about multiple timestamps

    # First, create a dataframe containing all information.
    dfa = pd.concat(snapshot_dfs)

    if len(dfa) == 0:
        log.info("leave early: no data for entity of type %s", entity_type)
        return

    # Build a dict: key is path/referrer name, and value is DF with
    # corresponding raw time series.
    entity_dfs = _build_entity_dfs(dfa, entity_type, unique_entity_names)

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
        # print(edf)
        df_top_vu[ename] = edf["views_unique"]
    # del ename

    log.info(
        "The top %s %s based on unique views, for the entire time range seen:\n%s",
        top_n,
        entity_type,
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
    # print(df_melted)

    # Normalize main metric to show a view count _per day_, and clarify in the
    # plot that this is a _mean_ value derived from the _last 14 days_.
    df_melted["views_unique_norm"] = df_melted["views_unique"] / 14.0

    # For paths, it's relevant to identify the common prefix (repo owner/name)

    # cmn_ename_prefix = os.path.commonprefix(list(unique_entity_names))
    # log.info("cmn_ename_prefix: %s", cmn_ename_prefix)

    # if entity_type == "path":
    #     log.info("remove common path prefix")
    #     df_melted["path"] = df_melted["path"].str.slice(start=len(cmn_ename_prefix))
    #     # The root path (e.g., `owner/repo`) is not an empty string. That's
    #     # not so cool, make the root be represented by a single slash.
    #     # df_melted[df_melted["path"] == ""]["path"] = "/"
    #     df_melted["path"].replace("", "/", inplace=True)

    panel_props = {"height": 300, "width": "container", "padding": 10}
    chart = (
        alt.Chart(df_melted)
        .mark_line(point=True)
        # .encode(x="time:T", y="views_unique:Q", color="referrer:N")
        # the pandas dataframe datetimeindex contains timing information at
        # much higher resolution than 1 day. The resulting vega spec may
        # then see time values like this: `"time": "2021-01-03T00:00:00+00:00"`
        # -- suggesting to vega that we care about showing hours and minutes.
        # instruct vega to only care about _days_ (dates), via an altair-based
        # timeout unit transformation. Ref:
        # https://altair-viz.github.io/user_guide/transform/timeunit.html
        .encode(
            alt.X("time", type="temporal", title="date", timeUnit="yearmonthdate"),
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
        .configure_point(size=50)
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

    # Textual form: larger N, and no cutoff (arbitrary length and legend of
    # plot don't go well with each other).
    top_n = 15
    top_n_enames = list(sorted_dict.keys())[:top_n]
    top_n_enames_string_for_md = ", ".join(
        f"{str(i).zfill(2)}: `{n}`" for i, n in enumerate(top_n_enames, 1)
    )

    MD_REPORT.write(
        textwrap.dedent(
            f"""


    #### {heading}


    <div id="chart_{entity_type}s_top_n_alltime" class="full-width-chart"></div>

    Top {top_n} {entity_type}s: {top_n_enames_string_for_md}


    """
        )
    )
    JS_FOOTER_LINES.append(
        f"vegaEmbed('#chart_{entity_type}s_top_n_alltime', {chart_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);"
    )


def analyse_view_clones_ts_fragments():

    log.info("read views/clones time series fragments (CSV docs)")

    basename_suffix = "_views_clones_series_fragment.csv"
    csvpaths = _glob_csvpaths(basename_suffix)

    dfs = []
    column_names_seen = set()

    for p in csvpaths:
        log.info("attempt to parse %s", p)
        snapshot_time = _get_snapshot_time_from_path(p, basename_suffix)

        df = pd.read_csv(
            p,
            index_col=["time_iso8601"],
            date_parser=lambda col: pd.to_datetime(col, utc=True),
        )

        # Skip logic for empty data frames. The CSV files written should never
        # be empty, but if such a bad file made it into the file system then
        # skipping here facilitates debugging and enhanced robustness.
        if len(df) == 0:
            log.warning("empty dataframe parsed from %s, skip", p)
            continue

        # A time series fragment might look like this:
        #
        # df_views_clones:
        #                            clones_total  ...  views_unique
        # time_iso8601                             ...
        # 2020-12-21 00:00:00+00:00           NaN  ...             2
        # 2020-12-22 00:00:00+00:00           2.0  ...            23
        # 2020-12-23 00:00:00+00:00           2.0  ...            20
        # ...
        # 2021-01-03 00:00:00+00:00           8.0  ...            21
        # 2021-01-04 00:00:00+00:00           7.0  ...            18
        #
        # Note the NaN and the floaty type.

        # All metrics are known to be integers by definition here. NaN values
        # are expected to be present anywhere in this dataframe, and they
        # semantically mean "0". Therefore, replace those with zeros. Also see
        # https://github.com/jgehrcke/github-repo-stats/issues/4
        df = df.fillna(0)
        # Make sure numbers are treated as integers from here on. This actually
        # matters in a cosmetic way only for outputting the aggregate CSV later
        # #       # not for plotting and number crunching).
        df = df.astype(int)

        # attach snapshot time as meta data prop to df
        df.attrs["snapshot_time"] = snapshot_time

        # The index is not of string type anymore, but of type
        # `pd.DatetimeIndex`. Reflect that in the name.
        df.index.rename("time", inplace=True)

        if column_names_seen and set(df.columns) != column_names_seen:
            log.error("columns seen so far: %s", column_names_seen)
            log.error("columns in %s: %s", p, df.columns)
            sys.exit(1)

        column_names_seen.update(df.columns)

        df = df.sort_index()

        # Sanity check: snapshot time _after_ latest timestamp in time series?
        # This could hit in on a machine with a bad time setting when fetching
        # data.
        if df.index.max() > snapshot_time:
            log.error(
                "for CSV file %s the snapshot time %s is older than the newest sample",
                p,
                snapshot_time,
            )
            sys.exit(1)

        dfs.append(df)

    # for df in dfs:
    #     print(df)

    log.info("total sample count: %s", sum(len(df) for df in dfs))

    if len(dfs) == 0:
        log.info("leave early: no data for views/clones")
        return

    newest_snapshot_time = max(df.attrs["snapshot_time"] for df in dfs)

    df_prev_agg = None
    if ARGS.views_clones_aggregate_inpath:
        if os.path.exists(ARGS.views_clones_aggregate_inpath):
            log.info("read previous aggregate: %s", ARGS.views_clones_aggregate_inpath)
            df_prev_agg = pd.read_csv(
                ARGS.views_clones_aggregate_inpath,
                index_col=["time_iso8601"],
                date_parser=lambda col: pd.to_datetime(col, utc=True),
            )
            df_prev_agg.index.rename("time", inplace=True)
        else:
            log.info(
                "previous aggregate file does not exist: %s",
                ARGS.views_clones_aggregate_inpath,
            )

    log.info("time of newest snapshot: %s", newest_snapshot_time)
    log.info("build aggregate, drop duplicate data")

    # Each dataframe in `dfs` corresponds to one time series fragment
    # ("snapshot") obtained from the GitHub API. Each time series fragment
    # contains 15 samples (rows), with two adjacent samples being 24 hours
    # apart. Ideally, the time series fragments overlap in time. They overlap
    # potentially by a lot, depending on when the individual snapshots were
    # taken (think: take one snapshot per day; then 14 out of 15 data points
    # are expected to be "the same" as in the snapshot taken the day before).
    # Stich these fragments together (with a buch of "duplicate samples), and
    # then sort this result by time.
    log.info("pd.concat(dfs)")
    dfall = pd.concat(dfs)

    if df_prev_agg is not None:
        if set(df_prev_agg.columns) != set(dfall.columns):
            log.error(
                "set(df_prev_agg.columns) != set (dfall.columns): %s, %s",
                df_prev_agg.columns,
                dfall.columns,
            )
            sys.exit(1)
        log.info("pd.concat(dfall, df_prev_agg)")
        dfall = pd.concat([dfall, df_prev_agg])

    dfall.sort_index(inplace=True)

    log.info("shape of dataframe before dropping duplicates: %s", dfall.shape)
    # print(dfall)

    # Now, the goal is to drop duplicate data. And again, as of a lot of
    # overlap between snapshots there's a lot of duplicate data to be expected.
    # What does "duplicat data" mean? We expect that there are multiple samples
    # from different snapshots with equivalent timestamp. OK, we should just
    # take any one of them. They should all be the same, right? They are not
    # all equivalent. I've found that at the boundaries of each time series
    # fragment, the values returned by the GitHub API are subject to a
    # non-obvious cutoff effect: for example, in a snapshot obtained on Dec 15,
    # the sample for Dec 7 is within the mid part of the fragment and shows a
    # value of 73 for `clones_total`. The snapshot obtained on Dec 21 has the
    # sample for Dec 7 at the boundary (left-hand, towards the past), and that
    # shows a value of 18 for `clones_total`. 73 vs 18 -- how is that possible?
    # That's easily possible, assuming that GitHub uses a rolling window of 14
    # days width with a precision higher than 1 day and after all the cutoff
    # for the data points at the boundary depends on the _exact time_ when the
    # snapshot was taken. That is, for aggregation (for dropping duplicate/bad
    # data) we want to look for the maximum data value for any given timestamp.
    # Using that method, we effectively ignore said cutoff artifact. In short:
    # group by timestamp (index), take the maximum.
    df_agg = dfall.groupby(dfall.index).max()

    log.info("shape of dataframe after dropping duplicates: %s", df_agg.shape)

    # Write aggregate
    # agg_fname = (
    #     datetime.strftime(newest_snapshot_time, "%Y-%m-%d_%H%M%S")
    #     + "_views_clones_aggregate.csv"
    # )
    # agg_fpath = os.path.join(ARGS.snapshotdir, agg_fname)
    if ARGS.views_clones_aggregate_outpath:

        if os.path.exists(ARGS.views_clones_aggregate_outpath):
            log.info("file exists: %s", ARGS.views_clones_aggregate_outpath)
            if not ARGS.views_clones_aggregate_inpath:
                log.error(
                    "would overwrite output aggregate w/o reading input aggregate -- you know what you're doing?"
                )
                sys.exit(1)

        log.info("write aggregate to %s", ARGS.views_clones_aggregate_outpath)
        # Pragmatic strategy against partial write / encoding problems.
        tpath = ARGS.views_clones_aggregate_outpath + ".tmp"
        df_agg.to_csv(tpath, index_label="time_iso8601")
        os.rename(tpath, ARGS.views_clones_aggregate_outpath)

        if ARGS.delete_ts_fragments:
            # Iterate through precisely the set of files that was read above.
            # If unlinkling fails at OS boundary then don't crash this program.
            for p in csvpaths:
                log.info("delete %s as of --delete-ts-fragments", p)
                try:
                    os.unlink(p)
                except Exception as e:
                    log.warning("could not unlink %s: %s", p, str(e))

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

    PANEL_WIDTH = "container"
    PANEL_HEIGHT = 200

    panel_props = {"height": PANEL_HEIGHT, "width": PANEL_WIDTH, "padding": 10}

    chart_clones_unique = (
        (
            alt.Chart(df_agg_clones)
            .mark_line(point=True)
            .encode(
                alt.X("time", type="temporal", title="date", timeUnit="yearmonthdate"),
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
                alt.X("time", type="temporal", title="date", timeUnit="yearmonthdate"),
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
                alt.X("time", type="temporal", title="date", timeUnit="yearmonthdate"),
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
                alt.X("time", type="temporal", title="date", timeUnit="yearmonthdate"),
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

    chart_views_unique_spec = chart_views_unique.to_json(indent=None)
    chart_views_total_spec = chart_views_total.to_json(indent=None)
    chart_clones_unique_spec = chart_clones_unique.to_json(indent=None)
    chart_clones_total_spec = chart_clones_total.to_json(indent=None)

    MD_REPORT.write(
        textwrap.dedent(
            """


    ## Views

    #### Unique visitors
    <div id="chart_views_unique" class="full-width-chart"></div>

    #### Total views
    <div id="chart_views_total" class="full-width-chart"></div>

    <div class="pagebreak-for-print"> </div>


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


def add_stargazers_section(df, date_axis_lim):
    # date_axis_lim is expected to be of the form ["2019-01-01", "2019-12-31"]

    x_kwargs = {
        "field": "time",
        "type": "temporal",
        "title": "date",
        "timeUnit": "yearmonthdate",
    }

    if date_axis_lim is not None:
        log.info("custom time window for stargazer plot: %s", date_axis_lim)
        x_kwargs["scale"] = alt.Scale(domain=date_axis_lim)

    panel_props = {"height": 300, "width": "container", "padding": 10}
    chart = (
        alt.Chart(df.reset_index())
        .mark_line(point=True)
        .encode(
            alt.X(**x_kwargs),
            alt.Y(
                "stars_cumulative",
                type="quantitative",
                title="stargazer count (cumulative)",
                scale=alt.Scale(
                    domain=(0, df["stars_cumulative"].max() * 1.1),
                    zero=True,
                ),
            ),
        )
        .configure_point(size=100)
        .properties(**panel_props)
    )

    chart_spec = chart.to_json(indent=None)

    MD_REPORT.write(
        textwrap.dedent(
            """

    ## Stargazers

    Each data point corresponds to at least one stargazer event.
    The time resolution is one day.

    <div id="chart_stargazers" class="full-width-chart"></div>


    """
        )
    )
    JS_FOOTER_LINES.append(
        f"vegaEmbed('#chart_stargazers', {chart_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);"
    )


def add_fork_section(df, date_axis_lim):
    # date_axis_lim is expected to be of the form ["2019-01-01", "2019-12-31"])

    x_kwargs = {
        "field": "time",
        "type": "temporal",
        "title": "date",
        "timeUnit": "yearmonthdate",
    }

    if date_axis_lim:
        log.info("custom time window for fork plot: %s", date_axis_lim)
        x_kwargs["scale"] = alt.Scale(domain=date_axis_lim)

    panel_props = {"height": 300, "width": "container", "padding": 10}
    chart = (
        alt.Chart(df.reset_index())
        .mark_line(point=True)
        .encode(
            alt.X(**x_kwargs),
            alt.Y(
                "forks_cumulative",
                type="quantitative",
                title="fork count (cumulative)",
                scale=alt.Scale(
                    domain=(0, df["forks_cumulative"].max() * 1.1),
                    zero=True,
                ),
            ),
        )
        .configure_point(size=100)
        .properties(**panel_props)
    )

    chart_spec = chart.to_json(indent=None)

    MD_REPORT.write(
        textwrap.dedent(
            """

    ## Forks

    Each data point corresponds to at least one fork event.
    The time resolution is one day.

    <div id="chart_forks" class="full-width-chart"></div>


    """
        )
    )
    JS_FOOTER_LINES.append(
        f"vegaEmbed('#chart_forks', {chart_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);"
    )


def get_stars_over_time():
    # TODO: for ~10k stars repositories, this operation is too costly for doing
    # it as part of each analyzer invocation. Move this to the fetcher, and
    # persist the data.
    log.info("fetch stargazer time series for repo %s", ARGS.repospec)

    hub = Github(
        login_or_token=os.environ["GHRS_GITHUB_API_TOKEN"].strip(), per_page=100
    )
    repo = hub.get_repo(ARGS.repospec)

    reqlimit_before = hub.get_rate_limit().core.remaining

    log.info("GH request limit before fetch operation: %s", reqlimit_before)

    gazers = []

    # TODO for addressing the 10ks challenge: save state to disk, and refresh
    # using reverse order iteration. See for repo in user.get_repos().reversed
    for count, gazer in enumerate(repo.get_stargazers_with_dates(), 1):
        # Store `PullRequest` object with integer key in dictionary.
        gazers.append(gazer)
        if count % 200 == 0:
            log.info("%s gazers fetched", count)

    reqlimit_after = hub.get_rate_limit().core.remaining
    log.info("GH request limit after fetch operation: %s", reqlimit_after)
    log.info("http requests made (approximately): %s", reqlimit_before - reqlimit_after)
    log.info("stargazer count: %s", len(gazers))

    # The GitHub API returns ISO 8601 timestamp strings encoding the timezone
    # via the Z suffix, i.e. Zulu time, i.e. UTC. pygithub doesn't parze that
    # timezone. That is, whereas the API returns `starred_at` in UTC, the
    # datetime obj created by pygithub is a naive one. Correct for that.
    startimes_aware = [pytz.timezone("UTC").localize(g.starred_at) for g in gazers]

    # Work towards a dataframe of the following shape:
    #                            star_events  stars_cumulative
    # time
    # 2020-11-26 16:25:37+00:00            1                 1
    # 2020-11-26 16:27:23+00:00            1                 2
    # 2020-11-26 16:30:05+00:00            1                 3
    # 2020-11-26 17:31:57+00:00            1                 4
    # 2020-11-26 17:48:48+00:00            1                 5
    # ...                                ...               ...
    # 2020-12-19 19:48:58+00:00            1               327
    # 2020-12-22 04:44:35+00:00            1               328
    # 2020-12-22 19:00:42+00:00            1               329
    # 2020-12-25 05:01:42+00:00            1               330
    # 2020-12-28 01:07:55+00:00            1               331

    # Create sorted pandas DatetimeIndex
    dtidx = pd.to_datetime(startimes_aware)
    dtidx = dtidx.sort_values()

    # Each timestamp corresponds to *1* star event. Build cumulative sum over
    # time.
    df = pd.DataFrame(
        data={"star_events": [1] * len(gazers)},
        index=dtidx,
    )
    df.index.name = "time"

    df["stars_cumulative"] = df["star_events"].cumsum()

    log.info("stars_cumulative, raw data: %s", df["stars_cumulative"])

    # As noted above, this should actually be part of the fetcher.
    if ARGS.stargazer_ts_resampled_outpath:
        # The CSV file should contain integers after all (no ".0"), therefore
        # cast to int. There are no NaNs to be expected, i.e. this should work
        # reliably.
        df_for_csv_file = resample_to_1d_resolution(df, "stars_cumulative").astype(int)
        log.info("stars_cumulative, for CSV file (resampled): %s", df_for_csv_file)
        log.info("write aggregate to %s", ARGS.views_clones_aggregate_outpath)
        # Pragmatic strategy against partial write / encoding problems.
        tpath = ARGS.stargazer_ts_resampled_outpath + ".tmp"
        df_for_csv_file.to_csv(tpath, index_label="time_iso8601")
        os.rename(tpath, ARGS.stargazer_ts_resampled_outpath)

    # Many data points? Downsample, for plotting.
    if len(df) > 50:
        df = downsample_series_to_N_points(df, "stars_cumulative")

    return df


def get_forks_over_time():
    # TODO: for ~10k forks repositories, this operation is too costly for doing
    # it as part of each analyzer invocation. Move this to the fetcher, and
    # persist the data.
    log.info("fetch fork time series for repo %s", ARGS.repospec)

    hub = Github(
        login_or_token=os.environ["GHRS_GITHUB_API_TOKEN"].strip(), per_page=100
    )
    repo = hub.get_repo(ARGS.repospec)
    reqlimit_before = hub.get_rate_limit().core.remaining
    log.info("GH request limit before fetch operation: %s", reqlimit_before)

    forks = []
    for count, fork in enumerate(repo.get_forks(), 1):
        # Store `PullRequest` object with integer key in dictionary.
        forks.append(fork)
        if count % 200 == 0:
            log.info("%s forks fetched", count)

    reqlimit_after = hub.get_rate_limit().core.remaining
    log.info("GH request limit after fetch operation: %s", reqlimit_after)
    log.info("http requests made (approximately): %s", reqlimit_before - reqlimit_after)
    log.info("current fork count: %s", len(forks))

    # The GitHub API returns ISO 8601 timestamp strings encoding the timezone
    # via the Z suffix, i.e. Zulu time, i.e. UTC. pygithub doesn't parse that
    # timezone. That is, whereas the API returns `starred_at` in UTC, the
    # datetime obj created by pygithub is a naive one. Correct for that.
    forktimes_aware = [pytz.timezone("UTC").localize(f.created_at) for f in forks]

    # Create sorted pandas DatetimeIndex
    dtidx = pd.to_datetime(forktimes_aware)
    dtidx = dtidx.sort_values()

    # Each timestamp corresponds to *1* fork event. Build cumulative sum over
    # time.
    df = pd.DataFrame(
        data={"fork_events": [1] * len(forks)},
        index=dtidx,
    )
    df.index.name = "time"
    df["forks_cumulative"] = df["fork_events"].cumsum()

    # As noted above, this should actually be part of the fetcher.
    if ARGS.fork_ts_resampled_outpath:
        # The CSV file should contain integers after all (no ".0"), therefore
        # cast to int. There are no NaNs to be expected, i.e. this should work
        # reliably.
        df_for_csv_file = resample_to_1d_resolution(df, "forks_cumulative").astype(int)
        log.info("forks_cumulative, for CSV file (resampled): %s", df_for_csv_file)
        log.info("write aggregate to %s", ARGS.fork_ts_resampled_outpath)
        # Pragmatic strategy against partial write / encoding problems.
        tpath = ARGS.fork_ts_resampled_outpath + ".tmp"
        df_for_csv_file.to_csv(tpath, index_label="time_iso8601")
        os.rename(tpath, ARGS.fork_ts_resampled_outpath)

    # Many data points? Downsample.
    if len(df) > 80:
        df = downsample_series_to_N_points(df, "forks_cumulative")

    return df


def downsample_series_to_N_points(df, column):
    # Choose a bin time width for downsampling. Identify tovered timespan
    # first.

    timespan_hours = int(
        pd.Timedelta(df.index.values[-1] - df.index.values[0]).total_seconds() / 3600
    )
    log.info(
        "timespan covererd, in hours (approximately): %s (%.1f days)",
        timespan_hours,
        timespan_hours / 24.0,
    )

    # Adjust this bin width to the timeframe covered. Make it so that there
    # are not more than ~100 data points for the entire time frame.
    # total_width / bin_width = n_bins -> bin_width = total_width / n_bins
    # Approximate integer result is fine.
    bin_width_hours = int(timespan_hours / 100)
    log.info("choosing bin_width_hours: %s", bin_width_hours)

    # n_hour_bins = 24

    s = df[column]

    log.info("len(series): %s", len(s))
    log.info("downsample series into %s-hour bins", bin_width_hours)

    # Resample the series into N-hour bins. Take max() for each group (assume
    # this is a cumsum series). Do `dropna()` on the resampler to remove all
    # up-sampled data points (so that each data point still reflects an actual
    # event or a group of events, but when there was no event within a bin then
    # that bin does not appear with a data point in the resulting plot).
    s = s.resample(f"{bin_width_hours}h").max().dropna()

    log.info("len(series): %s", len(s))

    # Turn Series object into Dataframe object again. The values column
    # retains the original column name
    return s.to_frame()


def resample_to_1d_resolution(df, column):
    """
    Have at most one data point per day. For days w/o change, have no data
    point.

    Before:

    2020-03-18 16:42:31+00:00      1
    2020-03-19 20:17:10+00:00      2
    2020-03-20 05:31:25+00:00      3
    2020-03-20 09:01:38+00:00      4
    2020-03-20 14:03:45+00:00      5
    ...

    After:

    2020-03-18 00:00:00+00:00 1.0
    2020-03-19 00:00:00+00:00 2.0
    2020-03-20 00:00:00+00:00 7.0
    2020-03-21 00:00:00+00:00 9.0
    """
    s = df[column]
    log.info("len(series): %s", len(s))
    log.info("resample series into 1d bins")

    # Take max() for each group (assume this is a cumsum series). Do `dropna()`
    # on the resampler to remove all up-sampled data points (so that each data
    # point still reflects an actual event or a group of events, but when there
    # was no event within a bin then that bin does not appear with a data point
    # in the resulting plot).
    s = s.resample("1d").max().dropna()
    log.info("len(series): %s", len(s))

    # Turn Series object into Dataframe object again. The values column
    # retains the original column name
    return s.to_frame()


def parse_args():
    global OUTDIR
    global ARGS
    parser = argparse.ArgumentParser(description="")

    parser.add_argument(
        "repospec",
        metavar="REPOSITORY",
        help="Owner/organization and repository. Must contain a slash. "
        "Example: coke/truck",
    )

    parser.add_argument(
        "snapshotdir",
        metavar="PATH",
        help="path to directory containing CSV files of data snapshots / time series fragments, obtained via fetch.py",
    )

    parser.add_argument("--pandoc-command", default="pandoc")
    parser.add_argument("--resources-directory", default="resources")
    parser.add_argument("--output-directory", default=TODAY + "_report")
    parser.add_argument("--outfile-prefix", default=TODAY + "_")

    parser.add_argument(
        "--stargazer-ts-resampled-outpath",
        default="",
        metavar="PATH",
        help="Write resampled stargazer time series to CSV file",
    )

    parser.add_argument(
        "--fork-ts-resampled-outpath",
        default="",
        metavar="PATH",
        help="Write resampled fork time series to CSV file",
    )

    parser.add_argument(
        "--views-clones-aggregate-outpath",
        default="",
        metavar="PATH",
        help="Write aggregate CSV file from discovered time series snapshots",
    )

    parser.add_argument(
        "--views-clones-aggregate-inpath",
        default="",
        metavar="PATH",
        help="Read aggregate CSV file in addition to regular time series snapshots discovery",
    )

    parser.add_argument(
        "--delete-ts-fragments",
        default=False,
        action="store_true",
        help="Delete individual fragment CSV files after having written aggregate CSV file",
    )

    args = parser.parse_args()

    if "/" not in args.repospec:
        sys.exit("missing slash in REPOSITORY spec")

    if args.delete_ts_fragments:
        if not args.views_clones_aggregate_outpath:
            sys.exit(
                "--delete-ts-fragments must only be set with --views-clones-aggregate-outpath"
            )

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
    ARGS = args


if __name__ == "__main__":
    main()
