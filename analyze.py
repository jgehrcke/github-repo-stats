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

from typing import Iterable, Set, Any, Optional, Tuple, Iterator, cast
from datetime import datetime
from io import StringIO

import pandas as pd
import pytz
import altair as alt  # type: ignore


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

# Also see https://github.com/jgehrcke/github-repo-stats/issues/52
alt.data_transformers.disable_max_rows()

NOW = datetime.utcnow()
TODAY = NOW.strftime("%Y-%m-%d")
OUTDIR: Optional[str] = None

# https://stackoverflow.com/a/68855129/145400
# ARGS: Optional[argparse.Namespace] = None
ARGS: Any = None

# Individual code sections are supposed to add to this in-memory Markdown
# document as they desire.
MD_REPORT = StringIO()
JS_FOOTER_LINES: list[str] = []

# https://github.com/vega/vega-embed#options -- use SVG renderer so that PDF
# export (print) from browser view yields arbitrarily scalable (vector)
# graphics embedded in the PDF doc, instead of rasterized graphics.
VEGA_EMBED_OPTIONS_JSON = json.dumps({"actions": False, "renderer": "svg"})

DATE_LABEL_ANGLE = 25
DATETIME_AXIS_PROPERTIES = {
    "field": "time",
    "type": "temporal",
    "title": "date",
    "timeUnit": "yearmonthdate",
    "axis": {"labelAngle": DATE_LABEL_ANGLE},
}


def main() -> None:
    parse_args()
    configure_altair()

    df_stargazers = process_stargazer_input()
    df_forks = read_forks_over_time_from_csv()

    gen_report_preamble()

    # The plots in this section share the same time frame showns (time axis
    # limits): min across all view/clone data, max across all view/clone data.
    df_vc_agg = analyse_view_clones_ts_fragments()

    report_pdf_pagebreak()

    # Sync up the time window shown in the plots for forks and stars over time.
    # Stargazer and fork time series obtained from github go back in time up to
    # the first fork/stargazer event -- regardless of when data collection via
    # this tool was started. That is, the earliest point in time in the fork/sg
    # time series may be earlier (potentially much earlier -- years!) than the
    # oldest point in time in the views/clones time series (where the first
    # data point's time depends on the point in time GHRS was started to be
    # used). However, the other special case of views/clone data to start
    # before the first sg/fork event having happened is also possible. That is,
    # extract min and max timestamps from all available time series data:
    # views/clones, sg, forks).
    sf_date_axis_lim = gen_date_axis_lim((df_vc_agg, df_stargazers, df_forks))
    log.info("time window for stargazer/fork data: %s", sf_date_axis_lim)

    # If either of these two time series contains at least one data point then
    # `sf_date_axis_lim` is meaningful. Calculate non-None
    # `sf_starts_earlier_than_vc_data`.
    sf_starts_earlier_than_vc_data: None | bool = None
    if len(df_stargazers) or len(df_forks):
        # See if stars and/or fork timeseries starts earlier than view/count
        # time series. Do not crash when one of both data frames is of zero
        # length. Require sorted index.
        sf_starts_earlier_than_vc_data = (
            min(d.index.values[0] for d in [df_stargazers, df_forks] if len(d))
            < df_vc_agg.index.values[0]
        )

    # df_stargazers and df_forks may both be of zero length, in which case
    # the values for sf_date_axis_lim and sf_starts_earlier_than_vc_data are
    # meaningless. The two functions are expected to generate proper content
    # for
    add_stargazers_section(
        df_stargazers, sf_date_axis_lim, sf_starts_earlier_than_vc_data
    )

    add_fork_section(df_forks, sf_date_axis_lim, sf_starts_earlier_than_vc_data)

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

    # Use the same x (time) axis limit as for view/clone plots further above.
    analyse_top_x_snapshots("referrer", gen_date_axis_lim((df_vc_agg,)))
    analyse_top_x_snapshots("path", gen_date_axis_lim((df_vc_agg,)))

    gen_report_footer()
    finalize_and_render_report()


def gen_date_axis_lim(dfs: Iterable[pd.DataFrame]) -> Tuple[str, str]:
    # Find minimal first timestamp across dataframes, and maximal last
    # timestamp. Return in string representation, example:
    # ['2020-03-18', '2021-01-03']
    # Can be used for setting time axis limits in Altair.

    # If there is not at least one non-zero length dataframe in the sequence
    # then min()/max() will throw a ValueError.
    return (
        pd.to_datetime(min(df.index.values[0] for df in dfs if len(df))).strftime(
            "%Y-%m-%d"
        ),
        pd.to_datetime(max(df.index.values[-1] for df in dfs if len(df))).strftime(
            "%Y-%m-%d"
        ),
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

    # As of the time of writing, the `resources` source directory contains a
    # CSS file which must be part of the output -- and a template.html file
    # which is not needed in the output. Simply remove that again.
    os.unlink(os.path.join(OUTDIR, "resources", "template.html"))

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
    log.debug("parsed timestamp from path: %s", t)
    return t


def _get_snapshot_dfs(csvpaths, basename_suffix):
    snapshot_dfs = []
    column_names_seen = set()

    log.info(f"about to deserialize {len(csvpaths)} snapshot CSV files")

    for p in csvpaths:
        log.debug("attempt to parse %s", p)
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
    log.info("_build_entity_dfs. cmn_ename_prefix: %s", cmn_ename_prefix)
    log.info("dfa:\n%s", dfa)

    entity_dfs = {}
    for ename in unique_entity_names:
        # Do a subselection
        edf = dfa[dfa[entity_type] == ename]
        # Now use datetime column as index
        newindex = edf["time"]
        edf = edf.drop(columns=["time"])

        edf.index = newindex
        edf = edf.sort_index()

        # Do entity name processing
        log.debug("ename before transformation: %s", ename)
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
        log.debug("len(edf): %s", len(edf))
        log.debug("downsample entity DF into %s-hour bins", n_hour_bins)
        # Resample the DF into N-hour bins. Take max() for each group. Do
        # `dropna()` on the resampler to remove all up-sampled data points (in
        # case snapshots were taken at much lower frequency). Default behavior
        # of the resampling operation is to note the value for each bin at the
        # left edge of the bin, and to have the bin be closed on the left edge
        # (right edge of the bin belongs to next bin).
        edf = edf.resample(f"{n_hour_bins}h").max().dropna()
        # log.debug("len(edf): %s", len(edf))

        # print(edf)
        entity_dfs[ename] = edf
        log.info(f"created dataframe for {entity_type}: {ename} -- len: {len(edf)}")

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


def analyse_top_x_snapshots(entity_type, date_axis_lim):
    assert entity_type in ["referrer", "path"]

    heading = "Top referrers" if entity_type == "referrer" else "Top paths"

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

    if not len(snapshot_dfs):
        MD_REPORT.write(
            textwrap.dedent(
                f"""

        #### {heading}

        No {entity_type} data available.

        """
            )
        )
        return

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
        # TODO: do not pick max() value across time series for top-n
        # consideration. That represents a peak, a single point in time which
        # could be long ago. It's more meaningful to integerate over time,
        # considering the entire time frame. That however might put a little
        # too much weight on the past, too -- so maybe perform two
        # integrations: entire time frame, and last three weeks. Build top N
        # for both of these, and then merge.
        max_vu_map[ename] = edf["views_unique"].max()
    del ename, edf

    # Sort dict so that the first item is the referrer/path with the highest
    # views_unique seen.
    sorted_dict = {
        k: v for k, v in sorted(max_vu_map.items(), key=lambda i: i[1], reverse=True)
    }

    log.info(f"{entity_type}, highest views_unique seen: {sorted_dict}")

    # log.info(entity_dfs['linkedin.com'])
    # log.info(entity_dfs['vega.github.io'])
    # log.info(pd.concat(
    #     [
    #         pd.Series(entity_dfs['linkedin.com']["views_unique"], name='linkedin_com_views_unique') ,
    #         pd.Series(entity_dfs['vega.github.io']["views_unique"], name='vega_views_unique')
    #     ], axis=1))
    # sys.exit()

    top_n = 7
    top_n_enames = list(sorted_dict.keys())[:top_n]

    # Build individual views_unique over time series. These series might have
    # partially overlapping or non-overlapping datetime indices. Name these
    # series (ename is for example 'linkedin.com' if this is a top_referrers
    # analysis).
    individual_series = [
        pd.Series(entity_dfs[ename]["views_unique"], name=ename)
        for ename in top_n_enames
    ]

    # The individual series have overlapping or non-overlapping indices.
    # Concatenate the series (along the right, i.e. add each series as
    # individual column (which is why naming the series above is important)).
    # This fills NaN values for individual columns where appropriate.
    df_top_vu = pd.concat(individual_series, axis=1)

    log.info(
        "The top %s %s based on unique views, for the entire time range seen:\n%s",
        top_n,
        entity_type,
        df_top_vu,
    )

    n_datapoints = df_top_vu.shape[0] * df_top_vu.shape[1]
    if n_datapoints > 3000:
        log.info("df_top_vu has %s data points in total, downsample", n_datapoints)
        # min_count: "The required number of valid values to perform the operation.
        # If fewer than min_count non-NA values are present the result will be NA."
        # df_top_vu = df_top_vu.resample("3d").sum(min_count=1)
        # I had seen the mean value introduce a bunch of .3333, it's fine to round
        # them to two digits so that the JSON doc (below) does not contain largish
        # floats.
        # df_top_vu = df_top_vu.resample("5d", label="right").mean().round(decimals=2)
        # df_top_vu = df_top_vu.resample("5d").mean().round(decimals=2)
        # Each data point reflects the last 14 days. Taking the mean() for e.g. 5
        # of these creates a mean value of mean values. I think we can just drop
        # values, take the last one.
        # df_top_vu = df_top_vu.resample("5d", label="right", closed="right").last(

        # The outcommented linkes above show the experimentation leading up to
        # the following method. This following method effectively downsamples
        # by throwing away data points if there is more than one data point per
        # five days. In that case it uses the last one (the others are
        # dropped). That is, we do not build a mean of means, but simply pick
        # one of the means. The `origin="end"` argument aligns the resampler
        # bins so that the largest timestamp in the input ends up being the
        # "end of the bins", so that the newest/right-most data point in the
        # resulting graph has the same date as the newest data point.
        # Otherwise, it might go into the future (this is a cosmetic aspect,
        # though). Also see
        # https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.resample.html
        df_top_vu = df_top_vu.resample("5d", origin="end").last(min_count=1)
        log.info(
            "after downsample:\n%s",
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

    # See issue #52, chart.to_json() below did warn us when the df_melted got a
    # little too big. In a test case with daily data for more than a year a
    # top_n reduction from 10 to 7 reduced the row count from 5010 to 3507. I
    # think this makes sense, plotting data for top 10 was a tiny bit too busy
    # anyway I think. However, most of the reduction should come from
    # down-sampling (prior to plotting) to one sample per week or maybe to one
    # sample per three days instead of one per day. That's why above there is a
    # downsampling step. In the specific scenario described before, this
    # further reduced the number of rows from 3507 to 728.
    log.info("melted df shape: %s", df_melted.shape)

    if len(df_melted) > 5000:
        log.warning(
            "df_melted has more than 5000 rows -- think about reducing the data points to plot"
        )

    y_axis_scale_type = symlog_or_lin(df_melted, "views_unique_norm", 8)

    x_kwargs = DATETIME_AXIS_PROPERTIES.copy()
    if date_axis_lim is not None:
        log.info("custom time window for top %s plot: %s", entity_type, date_axis_lim)
        x_kwargs["scale"] = alt.Scale(domain=date_axis_lim)

    panel_props = {
        "height": 300,
        "width": "container",
        "padding": 10,
    }

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
            x=alt.X(**x_kwargs),
            y=alt.Y(
                "views_unique_norm",
                type="quantitative",
                title="unique visitors per day (mean from last 14 days)",
                scale=alt.Scale(
                    domain=(0, df_melted["views_unique_norm"].max() * 1.1),
                    zero=True,
                    type=y_axis_scale_type,
                ),
            ),
            color=alt.Color(
                entity_type,
                type="nominal",
                sort=alt.SortField("order"),
                # https://vega.github.io/vega-lite/docs/legend.html#legend-properties
                legend={
                    # "orient": "bottom",
                    "orient": "top",
                    "direction": "vertical",
                    # "legendX": 120,
                    # "legendY": 340,
                    "title": "Legend:",
                },
            ),
            tooltip=[
                entity_type,
                alt.Tooltip(
                    "views_unique_norm:Q", format=".2f", title="views (14d mean)"
                ),
                alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
            ],
        )
        .configure_point(size=30)
        .properties(**panel_props)
    )

    chart_spec = chart.to_json(indent=None)

    # From
    # https://altair-viz.github.io/user_guide/customization.html
    # "Note that this will only scale with the container if its parent element
    # has a size determined outside the chart itself; For example, the
    # container may be a <div> element that has style width: 100%; height:
    # 300px.""

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


def analyse_view_clones_ts_fragments() -> pd.DataFrame:
    log.info("read views/clones time series fragments (CSV docs)")

    basename_suffix = "_views_clones_series_fragment.csv"
    csvpaths = _glob_csvpaths(basename_suffix)

    snapshot_dfs: list[pd.DataFrame] = []
    column_names_seen: Set[str] = set()

    for p in csvpaths:
        log.info("attempt to parse %s", p)
        snapshot_time = _get_snapshot_time_from_path(p, basename_suffix)

        df = pd.read_csv(  # type: ignore
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

        # `.columns` is known to be only strings
        column_names_seen.update(cast(Iterator[str], df.columns))

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

        snapshot_dfs.append(df)

    # for df in snapshot_dfs:
    #     print(df)

    log.info("total sample count: %s", sum(len(df) for df in snapshot_dfs))

    if len(snapshot_dfs) == 0:
        log.info("special case: no snapshots read for views/clones")
    else:
        newest_snapshot_time = max(df.attrs["snapshot_time"] for df in snapshot_dfs)
        log.info("time of newest snapshot: %s", newest_snapshot_time)

    # Read previously created views/clones aggregate file if it exists.
    df_prev_agg = None
    if ARGS.views_clones_aggregate_inpath:
        if os.path.exists(ARGS.views_clones_aggregate_inpath):
            log.info("read previous aggregate: %s", ARGS.views_clones_aggregate_inpath)

            df_prev_agg = pd.read_csv(  # type: ignore
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

    if len(snapshot_dfs) == 0 and df_prev_agg is None:
        # The report structure is not prepared to make sense w/o availability
        # of view/clone data. This state is forbidden for now. In the future,
        # it miiiight make sense to allow this special case: only show
        # fork/star time series. But that is super distant from the actual
        # purpose of this GHRS project.
        log.error(
            "unexpected: no data for views/clones: no snapshots, no previous aggregate"
        )
        sys.exit(1)

    log.info("build aggregate, drop duplicate data")
    # Each dataframe in `snapshot_dfs` corresponds to one time series fragment
    # ("snapshot") obtained from the GitHub API. Each time series fragment
    # contains 15 samples (rows), with two adjacent samples being 24 hours
    # apart. Ideally, the time series fragments overlap in time. They overlap
    # potentially by a lot, depending on when the individual snapshots were
    # taken (think: take one snapshot per day; then 14 out of 15 data points
    # are expected to be "the same" as in the snapshot taken the day before).
    # Stich these fragments together (with a buch of "duplicate samples), and
    # then sort this result by time.
    if len(snapshot_dfs):
        # combine all snapshots
        log.info("pd.concat(snapshot_dfs)")
        df_allsnapshots = pd.concat(snapshot_dfs)

        # Combine the result of combine-all-snapshots with previous aggregate
        dfall = df_allsnapshots
        if df_prev_agg is not None:
            if set(df_prev_agg.columns) != set(df_allsnapshots.columns):
                log.error(
                    "set(df_prev_agg.columns) != set (dfall.columns): %s, %s",
                    df_prev_agg.columns,
                    df_allsnapshots.columns,
                )
                sys.exit(1)
            log.info("pd.concat(dfall, df_prev_agg)")
            dfall = pd.concat([df_allsnapshots, df_prev_agg])

    else:
        assert df_prev_agg is not None
        dfall = df_prev_agg

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
    df_agg: pd.DataFrame = dfall.groupby(dfall.index).max()
    log.info("shape of dataframe after dropping duplicates: %s", df_agg.shape)

    # Get time range, to be returned by this function. Used later for setting
    # plot x_limit in all views/clones plot, but also in other plots in the
    # report (views/clones is likely the most complete data -- i.e. the  widest
    # time window).
    date_axis_lim = gen_date_axis_lim([df_agg])
    log.info("time range of views/clones data: %s", date_axis_lim)

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
    # Use new name for df to be kept around for returning, before reset_index()
    # so that df.index is kept meaningful.
    df_agg_for_return = df_agg
    df_agg = df_agg.reset_index()
    df_agg_views = df_agg.drop(columns=["clones_unique", "clones_total"])
    df_agg_clones = df_agg.drop(columns=["views_unique", "views_total"])

    PANEL_WIDTH = "container"
    PANEL_HEIGHT = 200

    panel_props = {"height": PANEL_HEIGHT, "width": PANEL_WIDTH, "padding": 10}

    x_kwargs = DATETIME_AXIS_PROPERTIES.copy()

    # sync date axis range across all views/clone plots.
    x_kwargs["scale"] = alt.Scale(domain=date_axis_lim)

    yaxis = alt.Axis()
    yaxistype = symlog_or_lin(df_agg_clones, "clones_unique", 100)
    if yaxistype == "symlog":
        yaxis = alt.Axis(values=[1, 10, 50, 100, 500, 1000, 5000, 10000])
    chart_clones_unique = (
        (
            alt.Chart(df_agg_clones)
            .mark_line(point=True)
            .encode(
                alt.X(**x_kwargs),
                alt.Y(
                    "clones_unique",
                    type="quantitative",
                    title="unique clones per day",
                    axis=yaxis,
                    scale=alt.Scale(
                        domain=(0, df_agg_clones["clones_unique"].max() * 1.1),
                        zero=True,
                        type=yaxistype,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("clones_unique:Q", format=".1f", title="clones (u)"),
                    alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
                ],
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=20)
        .properties(**panel_props)
    )

    yaxis = alt.Axis()
    yaxistype = symlog_or_lin(df_agg_clones, "clones_total", 100)
    if yaxistype == "symlog":
        yaxis = alt.Axis(values=[1, 10, 50, 100, 500, 1000, 5000, 10000])
    chart_clones_total = (
        (
            alt.Chart(df_agg_clones)
            .mark_line(point=True)
            .encode(
                alt.X(**x_kwargs),
                alt.Y(
                    "clones_total",
                    type="quantitative",
                    title="total clones per day",
                    axis=yaxis,
                    scale=alt.Scale(
                        domain=(0, df_agg_clones["clones_total"].max() * 1.1),
                        zero=True,
                        type=yaxistype,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("clones_total:Q", format=".1f", title="clones (t)"),
                    alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
                ],
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=20)
        .properties(**panel_props)
    )

    yaxis = alt.Axis()
    yaxistype = symlog_or_lin(df_agg_views, "views_unique", 100)
    if yaxistype == "symlog":
        yaxis = alt.Axis(values=[1, 10, 50, 100, 500, 1000, 5000, 10000])
    chart_views_unique = (
        (
            alt.Chart(df_agg_views)
            .mark_line(point=True)
            .encode(
                alt.X(**x_kwargs),
                alt.Y(
                    "views_unique",
                    type="quantitative",
                    title="unique views per day",
                    axis=yaxis,
                    scale=alt.Scale(
                        domain=(0, df_agg_views["views_unique"].max() * 1.1),
                        zero=True,
                        type=yaxistype,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("views_unique:Q", format=".1f", title="views (u)"),
                    alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
                ],
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=20)
        .properties(**panel_props)
    )

    yaxis = alt.Axis()
    yaxistype = symlog_or_lin(df_agg_views, "views_total", 100)
    if yaxistype == "symlog":
        yaxis = alt.Axis(values=[1, 10, 50, 100, 500, 1000, 5000, 10000])
    chart_views_total = (
        (
            alt.Chart(df_agg_views)
            .mark_line(point=True)
            .encode(
                alt.X(**x_kwargs),
                alt.Y(
                    "views_total",
                    type="quantitative",
                    title="total views per day",
                    axis=yaxis,
                    scale=alt.Scale(
                        domain=(0, df_agg_views["views_total"].max() * 1.1),
                        zero=True,
                        type=yaxistype,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("views_total:Q", format=".1f", title="views (t)"),
                    alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
                ],
            )
        )
        .configure_axisY(labelBound=True)
        .configure_point(size=20)
        .properties(**panel_props)
    )

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

    Cumulative: {df_agg_views["views_unique"].sum()}

    #### Total views
    <div id="chart_views_total" class="full-width-chart"></div>

    Cumulative: {df_agg_views["views_total"].sum()}

    <div class="pagebreak-for-print"> </div>

    ## Clones

    #### Unique cloners
    <div id="chart_clones_unique" class="full-width-chart"></div>

    Cumulative: {df_agg_clones["clones_unique"].sum()}

    #### Total clones
    <div id="chart_clones_total" class="full-width-chart"></div>

    Cumulative: {df_agg_clones["clones_total"].sum()}

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

    return df_agg_for_return


def add_stargazers_section(
    df: pd.DataFrame,
    date_axis_lim: Tuple[str, str],
    starts_earlier_than_vc_data: None | bool,
):
    """

    Include a markdown section also for zero length time series (no stars)
    """
    if not len(df):
        MD_REPORT.write(
            textwrap.dedent(
                """

        ## Stargazers

        This repository has no stars yet.

        """
            )
        )
        return

    # date_axis_lim is expected to be of the form ["2019-01-01", "2019-12-31"]

    x_kwargs = DATETIME_AXIS_PROPERTIES.copy()

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
            tooltip=[
                alt.Tooltip("stars_cumulative:Q", format="d", title="stars"),
                alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
            ],
        )
        .configure_point(size=50)
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

    if starts_earlier_than_vc_data:
        MD_REPORT.write(
            "Note: this plot shows a larger time frame than the "
            + "view/clone plots above "
            + "because the star/fork data contains earlier samples.\n\n"
        )

    JS_FOOTER_LINES.append(
        f"vegaEmbed('#chart_stargazers', {chart_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);"
    )


def add_fork_section(
    df: pd.DataFrame,
    date_axis_lim: Tuple[str, str],
    starts_earlier_than_vc_data: None | bool,
):
    """

    Include a markdown section also for zero length time series (no forks)
    """
    if not len(df):
        MD_REPORT.write(
            textwrap.dedent(
                """

        ## Forks

        This repository has no forks yet.

        """
            )
        )
        return

    # date_axis_lim is expected to be of the form ["2019-01-01", "2019-12-31"])

    x_kwargs = DATETIME_AXIS_PROPERTIES.copy()

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
            tooltip=[
                alt.Tooltip("forks_cumulative:Q", format="d", title="forks"),
                alt.Tooltip("time:T", format="%B %e, %Y", title="date"),
            ],
        )
        .configure_point(size=50)
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

    if starts_earlier_than_vc_data:
        MD_REPORT.write(
            "Note: this plot shows a larger time frame than the "
            + "view/clone plots above "
            + "because the star/fork data contains earlier samples.\n\n"
        )

    JS_FOOTER_LINES.append(
        f"vegaEmbed('#chart_forks', {chart_spec}, {VEGA_EMBED_OPTIONS_JSON}).catch(console.error);"
    )


def symlog_or_lin(df, colname, threshold):
    """
    This is not a silver bullet solution so far, might show symlog scale where
    linear would be nicer.

    The main idea of using symlog is to not lose resolution around smaller
    values given the presence of visitor spikes/peaks.

    A half-decent algorithm to make the decision should look more closely at
    the distribution of values, not only at min and max.
    """
    rmin = df[colname].min()
    rmax = df[colname].max()
    log.info(f"df[{colname}] min: {rmin}, max: {rmax}")

    if rmax - rmin > threshold:
        log.info(f"df[{colname}]: use symlog scale, because range > {threshold}")
        return "symlog"

    log.info(f"df[{colname}]: use linear scale")
    return "linear"


def process_stargazer_input() -> pd.DataFrame:
    """
    Read stargazer data. Return dataframe to plot. Conditionally, (re-)write
    "resampled" stargazer timeseries for persistence in git.

    This has grown a bit chaotic in terms of requirements.

    The current design I think is / should be something like this:

    Do not require anything (do not treat missing data 'fatal') but try to read
    anything that's available and try to make sense of it.

    There are three sources:

    1) "raw": each stargazer event, limited to first 40 k. History may be
       re-written I think (data points from the past may change, I think (when
       a stargazer stops being a stargazer)
    2) "snapshots": the sum of stargazers, as seen by GHRS, at specific points
       in time. This history may not be re-written.
    3) "resampled": a previous down-sampled variant of 1+2, which when combined
       with an updated version of (2) may yield the current version of (3).

    Behavior:

    - Do work only when either (1) or (2) is provided. That is consistent with
      the idea that 'resampled' (3) is not directly meant as input for
      plotting.

    Treat permutations along the following cases:

    - "raw": yes/no
    - "snapshots": yes/no
    - "resampled": yes/no

       raw, snpshts, resampled | do work  read rs  rebuild rs
       ----------------------- | -------------------------------------------
    1  (True, True, True),     |  x       no       x (fresh build)
    2  (True, True, False),    |  x       no       x (fresh build)
    3  (True, False, True),    |  x       no       x (fresh build)
    4  (True, False, False),   |  x       no       x (fresh build)
    5  (False, True, True),    |  x       x        x (from previous, danger)
    6  (False, True, False),   |  x       no       no (just snapshots good enough)
    7  (False, False, True),   |  no
    8  (False, False, False)   |  no

    - no input data
    - only raw series
    - only snapshots




    """
    df_result = pd.DataFrame({"time": [], "stars_cumulative": []})

    if not ARGS.stargazer_ts_inpath and not ARGS.stargazer_ts_snapshot_inpath:
        # Cases 7 and 8.
        log.info(
            "stargazer_ts_inpath, stargazer_ts_snapshot_inpath not provided: terminate stargazer processing"
        )
        return df_result

    previous_ts_latest_datetime = None

    if os.path.exists(ARGS.stargazer_ts_inpath):
        log.info("Parse (raw) stargazer time series CSV: %s", ARGS.stargazer_ts_inpath)

        df_raw = pd.read_csv(  # type: ignore
            ARGS.stargazer_ts_inpath,
            index_col=["time_iso8601"],
            date_parser=lambda col: pd.to_datetime(col, utc=True),
        )
        df_raw.index.rename("time", inplace=True)
        log.info("stars_cumulative, raw ts: %s", df_raw["stars_cumulative"])

        if not len(df_raw):
            # Special case: no stargazers yet, the expected case for first
            # invocation for 0-stargazer repo (I think). Return empty
            # dataframe.
            log.info("no data: terminate stargazer processing")
            return df_result

        previous_ts_latest_datetime = df_raw.index[-1]
        # Just to reiterate, this is expected to be the 'raw' API-provided
        # timeseries, including each individual stargazer event up to 40k.
        # It may not be reasonable to plot this as-is, depending on density
        # and overall amount of data points.
        df_result = df_raw

    elif os.path.exists(ARGS.stargazer_ts_resampled_outpath):
        # Case 5 above: (False, True, True). This is interesting tidbit; no
        # 'raw' series was provided, but a previously written resampled
        # timeseries. Read this, assuming it reflects a downsampled version of
        # the first 40k stargazers.
        log.info(
            "No raw ts provided. Parse (previously resampled) stargazer time series CSV: %s",
            ARGS.stargazer_ts_resampled_outpath,
        )
        df_resampled = pd.read_csv(  # type: ignore
            ARGS.stargazer_ts_resampled_outpath,
            index_col=["time_iso8601"],
            date_parser=lambda col: pd.to_datetime(col, utc=True),
        )
        df_resampled.index.rename("time", inplace=True)
        log.info(
            "stars_cumulative, previously resampled: %s",
            df_resampled["stars_cumulative"],
        )

        previous_ts_latest_datetime = df_resampled.index[-1]
        df_result = df_resampled

    # When ending up here: there is at least one stargazer (fast exit above for
    # case 0). Note: the existence of the file `stargazer_ts_snapshot_inpath`
    # does not mean that there are more than 40k stargazers. This makes testing
    # more credible: execute this code path often.
    if os.path.exists(ARGS.stargazer_ts_snapshot_inpath):

        log.info(
            "Parse (snapshot) stargazer time series CSV: %s",
            ARGS.stargazer_ts_snapshot_inpath,
        )

        df_snapshots = pd.read_csv(  # type: ignore
            ARGS.stargazer_ts_snapshot_inpath,
            index_col=["time_iso8601"],
            date_parser=lambda col: pd.to_datetime(col, utc=True),
        )
        df_snapshots.index.rename("time", inplace=True)

        # Unsorted input is unlikely, but still.
        df_snapshots.sort_index(inplace=True)

        log.info("stargazer snapshots timeseries:\n%s", df_snapshots)

        # Defensive: select only those data points that are newer than those in
        # df_raw.
        # log.info("df_snapshots.index: %s", df_snapshots.index)
        if previous_ts_latest_datetime is not None:
            df_snapshots = df_snapshots[
                df_snapshots.index > previous_ts_latest_datetime
            ]

        # Is at least one data point left?
        if len(df_snapshots):
            # Concatenate with 'raw' timeseries, along the same column.
            df_snapshots.rename(
                columns={"stargazers_cumulative_snapshot": "stars_cumulative"},
                inplace=True,
            )

            # On purpose: overwrite object defined above.
            df_result = pd.concat([df_result, df_snapshots])  # type: ignore
            log.info("concat result:\n%s", df_result)

    # Make the stargazer timeseries that is going to be persisted via git
    # contain data from both, the raw timeseries (obtained from API) as well as
    # from the snapshots obtained so far; but downsample to at most one data
    # point per day. Note that this is for external usage, not used for GHRS.
    if ARGS.stargazer_ts_resampled_outpath:
        # The CSV file should contain integers after all (no ".0"), therefore
        # cast to int. There are no NaNs to be expected, i.e. this should work
        # reliably.
        # Note: there is a special case when the input here was previously
        # resampled using the same method; this should be fine but we need
        # to confirm this: if repeated execution leads to 'data loss' then
        # we would thin out data over time.
        df_for_csv_file = resample_to_1d_resolution(
            df_result, "stars_cumulative"
        ).astype(int)
        log.info(
            "stars_cumulative, for CSV file (resampled, from raw+snapshots): %s",
            df_for_csv_file,
        )
        log.info("write aggregate to %s", ARGS.stargazer_ts_resampled_outpath)

        # Pragmatic strategy against partial write / encoding problems.
        tpath = ARGS.stargazer_ts_resampled_outpath + ".tmp"
        df_for_csv_file.to_csv(tpath, index_label="time_iso8601")
        os.rename(tpath, ARGS.stargazer_ts_resampled_outpath)

    df_stargazers_for_plot = df_result

    # Many data points? Downsample, for plotting.
    if len(df_stargazers_for_plot) > 50:
        df_stargazers_for_plot = downsample_series_to_N_points(
            df_result, "stars_cumulative"
        )

    log.info("df_stargazers_for_plot:\n%s", df_stargazers_for_plot)
    return df_stargazers_for_plot


def read_forks_over_time_from_csv() -> pd.DataFrame:
    if not ARGS.fork_ts_inpath:
        log.info("fork_ts_inpath not provided, return emtpy df")
        return pd.DataFrame()

    log.info("Parse fork time series (raw) CSV: %s", ARGS.fork_ts_inpath)

    df = pd.read_csv(  # type: ignore
        ARGS.fork_ts_inpath,
        index_col=["time_iso8601"],
        date_parser=lambda col: pd.to_datetime(col, utc=True),
    )

    # df = df.astype(int)
    df.index.rename("time", inplace=True)
    log.info("forks_cumulative, raw data: %s", df["forks_cumulative"])

    if not len(df):
        log.info("CSV file did not contain data, return empty df")
        return df

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
    # Choose a bin time width for downsampling. Identify covered timespan
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
    # The resample operation might put the last data point into the future,
    # Let's correct for that by putting origin="end".
    s = s.resample(f"{bin_width_hours}h", origin="end").max().dropna()

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
        metavar="SNAPSHOT_DIR_PATH",
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
        help="Write resampled stargazer time series to CSV file (at most "
        "one sample per day). No file is created if time series is empty.",
    )

    parser.add_argument(
        "--stargazer-ts-inpath",
        default="",
        metavar="PATH",
        help="Read raw stargazer time series from CSV file. File must exist, may be empty.",
    )

    parser.add_argument(
        "--stargazer-ts-snapshot-inpath",
        default="",
        metavar="PATH",
        help="Read snapshot-based stargazer time series from CSV file "
        "(helps accounting for the 40k limit). File not required to exist. ",
    )

    parser.add_argument(
        "--fork-ts-resampled-outpath",
        default="",
        metavar="PATH",
        help="Write resampled fork time series to CSV file (at most "
        "one sample per day). No file is created if time series is empty.",
    )

    parser.add_argument(
        "--fork-ts-inpath",
        default="",
        metavar="PATH",
        help="Read raw fork time series from CSV file. File must exist, may be empty.",
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
