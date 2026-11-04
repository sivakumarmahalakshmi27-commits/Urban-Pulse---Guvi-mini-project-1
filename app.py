"""
Urban Pulse NYC - Streamlit dashboard

Where this file lives:  C:/Users/skmah/urban_pulse/app.py
How to run (from a terminal opened in that folder):
    streamlit run app.py

What it contains
  - Sidebar: page selector + filters (date range, borough, complaint type)
  - Overview page: the five KPIs and a filtered record preview
  - Analyst pages covering Tasks 1-15 (each: question, sample size, chart,
    observed pattern, cautious interpretation)
"""

import os
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

st.set_page_config(page_title="Urban Pulse NYC", layout="wide")

DB_NAME = "urban_pulse_db"
THRESHOLD_HOURS = 72    # project-defined, illustrative cut-off (not an official SLA)
MIN_N = 100             # group medians/rates are only compared when n >= 100
PREVIEW_ROWS = 100
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FLAG_COLS = ["zip_invalid_flag", "coord_missing_flag", "coord_out_of_nyc_flag",
             "is_closed", "resolution_outlier_flag"]


# ===========================================================================
# 1. DATABASE
# ===========================================================================
@st.cache_resource
def get_engine():
    """Create the database connection once and reuse it."""
    url = URL.create(
        "mysql+pymysql",
        username=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=DB_NAME,
    )
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=3600)
def load_filter_options():
    """Values that fill the sidebar: date limits, boroughs, complaint types."""
    with get_engine().connect() as conn:
        limits = pd.read_sql(
            text("SELECT MIN(created_date) AS first_d, MAX(created_date) AS last_d "
                 "FROM service_requests"), conn)
        boroughs = pd.read_sql(
            text("SELECT DISTINCT borough FROM service_requests "
                 "WHERE borough IS NOT NULL ORDER BY borough"), conn)
        types = pd.read_sql(
            text("SELECT DISTINCT complaint_type FROM service_requests "
                 "WHERE complaint_type IS NOT NULL ORDER BY complaint_type"), conn)
    return {
        "min_date": limits["first_d"].iloc[0].date(),
        "max_date": limits["last_d"].iloc[0].date(),
        "boroughs": boroughs["borough"].tolist(),
        "complaint_types": types["complaint_type"].tolist(),
    }


def build_query(start_date, end_date, boroughs, complaint_types):
    """
    Return (sql_text, params).
    The SQL contains only fixed text and placeholders like :b0, :c1.
    The values the user picked travel separately in `params`, so a value such as
    "x'; DROP TABLE service_requests; --" is treated as plain text, not as SQL.
    """
    sql = (
        "SELECT unique_key, created_date, closed_date, agency, complaint_type, "
        "descriptor, borough, incident_zip, status, latitude, longitude, "
        "zip_invalid_flag, coord_missing_flag, coord_out_of_nyc_flag, "
        "is_closed, resolution_hours, resolution_outlier_flag, "
        "created_ym, created_weekday, created_hour "
        "FROM service_requests "
        "WHERE created_date >= :start_dt AND created_date < :end_dt"
    )
    params = {
        "start_dt": pd.Timestamp(start_date).to_pydatetime(),
        # end date is inclusive, so go up to (but not including) the next midnight
        "end_dt": (pd.Timestamp(end_date) + timedelta(days=1)).to_pydatetime(),
    }
    if boroughs:
        names = [f":b{i}" for i in range(len(boroughs))]
        sql += f" AND borough IN ({', '.join(names)})"
        params.update({f"b{i}": v for i, v in enumerate(boroughs)})
    if complaint_types:
        names = [f":c{i}" for i in range(len(complaint_types))]
        sql += f" AND complaint_type IN ({', '.join(names)})"
        params.update({f"c{i}": v for i, v in enumerate(complaint_types)})
    return sql, params


def clean_types(df):
    """Make flag columns plain 0/1 numbers (NULL -> 0) and hours numeric."""
    df = df.copy()
    for c in FLAG_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["resolution_hours"] = pd.to_numeric(df["resolution_hours"], errors="coerce")
    df["created_hour"] = pd.to_numeric(df["created_hour"], errors="coerce")
    return df


@st.cache_data(ttl=600)
def load_data(start_date, end_date, boroughs, complaint_types):
    """Run the filtered query. Arguments are tuples so Streamlit can cache them."""
    sql, params = build_query(start_date, end_date, boroughs, complaint_types)
    with get_engine().connect() as conn:
        return clean_types(pd.read_sql(text(sql), conn, params=params))


# ===========================================================================
# 2. SMALL HELPERS
# ===========================================================================
def valid(df):
    """Rows with a valid resolution duration."""
    return df.dropna(subset=["resolution_hours"])


def fmt(value, pattern):
    """Show 'n/a' instead of 'nan' when a number cannot be calculated."""
    return "n/a" if pd.isna(value) else pattern.format(value)


def compute_kpis(df):
    """The five KPIs (definitions from the project document)."""
    v = df["resolution_hours"].dropna()
    total_rows = len(df)
    closed_rows = int((df["is_closed"] == 1).sum())
    return {
        "total_requests": int(df["unique_key"].nunique()),
        "closure_pct": 100 * closed_rows / total_rows if total_rows else float("nan"),
        "open_requests": total_rows - closed_rows,
        "median_hours": v.median() if len(v) else float("nan"),
        "over_72_pct": 100 * (v > THRESHOLD_HOURS).sum() / len(v) if len(v) else float("nan"),
        "valid_durations": int(len(v)),
    }


def count_table(df, col):
    """Requests per category, largest first, with share of the filtered data."""
    t = (df[col].fillna("(blank)").value_counts()
         .rename_axis(col).reset_index(name="requests"))
    t["pct_of_filtered"] = (100 * t["requests"] / len(df)).round(2)
    return t


def group_median(df, by):
    """Median / mean resolution hours per group (valid durations only)."""
    g = (valid(df).groupby(by)["resolution_hours"]
         .agg(valid_durations="count", median_hours="median", mean_hours="mean")
         .reset_index())
    g["median_hours"] = g["median_hours"].round(2)
    g["mean_hours"] = g["mean_hours"].round(2)
    return g


def header(title, question, sample):
    st.subheader(title)
    st.markdown(f"**Question:** {question}")
    st.caption(f"Sample size: {sample}")


def observed(text_):
    st.markdown(f"**Observed pattern:** {text_}")


def caution(text_):
    st.info(f"**Cautious interpretation:** {text_}")


def show_fig(fig):
    st.pyplot(fig)
    plt.close(fig)


def hbar(labels, values, title, xlabel="Requests", fmt_="{:,.0f}"):
    """Horizontal bar chart with value labels."""
    fig, ax = plt.subplots(figsize=(8, max(2.5, 0.38 * len(labels) + 1)))
    ypos = np.arange(len(labels))
    ax.barh(ypos, values)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    for y, v in zip(ypos, values):
        ax.text(v, y, " " + fmt_.format(v), va="center", fontsize=8)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.margins(x=0.15)
    fig.tight_layout()
    show_fig(fig)


# ===========================================================================
# 3. PAGES
# ===========================================================================
def page_overview(df):
    st.header("Overview")
    k = compute_kpis(df)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total requests", f"{k['total_requests']:,}")
    c2.metric("Recorded closure", fmt(k["closure_pct"], "{:.2f}%"))
    c3.metric("Open requests", f"{k['open_requests']:,}")
    c4.metric("Median resolution", fmt(k["median_hours"], "{:,.2f} h"))
    c5.metric(f"Over {THRESHOLD_HOURS} hours", fmt(k["over_72_pct"], "{:.2f}%"))
    st.caption(
        f"Median and over-{THRESHOLD_HOURS}-hour share use {k['valid_durations']:,} "
        "valid resolution durations. Closure is based on a recorded closed date, "
        "not on citizen satisfaction. The 72-hour threshold is a project-defined "
        "cut-off, not an official service standard.")

    st.subheader("Filtered record preview")
    shown = min(PREVIEW_ROWS, len(df))
    st.caption(f"Showing the {shown:,} most recent of {len(df):,} filtered rows.")
    cols = ["unique_key", "created_date", "closed_date", "agency", "complaint_type",
            "descriptor", "borough", "incident_zip", "status", "is_closed", "resolution_hours"]
    st.dataframe(df.sort_values("created_date", ascending=False).head(PREVIEW_ROWS)[cols])


def page_volume(df):
    st.header("Volume and mix of requests (Tasks 1-4)")

    header("Task 1 - Total distinct request volume",
           "How many distinct requests are in the filtered data?", f"{len(df):,} rows")
    c1, c2, c3 = st.columns(3)
    c1.metric("Distinct requests", f"{df['unique_key'].nunique():,}")
    c2.metric("First request", str(df["created_date"].min())[:16])
    c3.metric("Last request", str(df["created_date"].max())[:16])
    caution("The data is a ~3% systematic sample, so this shows the sample size, "
            "not the citywide volume.")

    t = count_table(df, "complaint_type").head(10)
    header("Task 2 - Top 10 complaint categories",
           "Which complaint types are reported most often?", f"{len(df):,} requests")
    hbar(t["complaint_type"].tolist(), t["requests"].tolist(), "Top 10 complaint types")
    st.dataframe(t, hide_index=True)
    observed(f"The top 10 types make up {t['requests'].sum() / len(df) * 100:.1f}% of the "
             f"filtered requests; the largest is {t.iloc[0]['complaint_type']} "
             f"({t.iloc[0]['pct_of_filtered']:.2f}%).")
    caution("311 shows what people report, not the true prevalence of problems. "
            "Easy-to-report problems (parking, noise) can look larger.")

    t = count_table(df, "agency")
    header("Task 3 - Agency workload distribution",
           "How are recorded requests distributed across agencies?", f"{len(df):,} requests")
    hbar(t["agency"].tolist(), t["requests"].tolist(), "Requests by agency")
    st.dataframe(t, hide_index=True)
    top2 = t.head(2)
    observed(f"{' and '.join(top2['agency'])} together account for "
             f"{top2['requests'].sum() / len(df) * 100:.1f}% of the filtered requests.")
    caution("These are recorded requests, not staff effort or performance. "
            "Very small agencies are too small to compare.")

    t = count_table(df, "borough")
    header("Task 4 - Request volume by borough",
           "How do request counts compare across boroughs?", f"{len(df):,} requests")
    hbar(t["borough"].tolist(), t["requests"].tolist(), "Requests by borough")
    st.dataframe(t, hide_index=True)
    observed(f"{t.iloc[0]['borough']} has the most requests ({t.iloc[0]['pct_of_filtered']:.2f}%).")
    caution("Counts are raw volumes, not per-capita. No population data is used.")


def page_time(df):
    st.header("Time patterns (Tasks 5-6)")

    m = df.groupby("created_ym").size().rename("requests").reset_index().sort_values("created_ym")
    header("Task 5 - Monthly request trend",
           "How does request volume change month by month?", f"{len(df):,} requests, {len(m)} months")
    st.line_chart(m.set_index("created_ym")["requests"])
    st.dataframe(m, hide_index=True)
    hi, lo = m.loc[m["requests"].idxmax()], m.loc[m["requests"].idxmin()]
    observed(f"Highest month {hi['created_ym']} ({int(hi['requests']):,}); "
             f"lowest {lo['created_ym']} ({int(lo['requests']):,}).")
    caution("The data covers at most 12 months, so seasonality cannot be separated "
            "from one-off events. Month length is not adjusted.")

    header("Task 6 - Demand by weekday and hour",
           "When during the week are requests created?", f"{len(df):,} requests")
    grid = (df.pivot_table(index="created_weekday", columns="created_hour",
                           values="unique_key", aggfunc="count")
            .reindex(WEEKDAYS).reindex(columns=range(24)).fillna(0))
    fig, ax = plt.subplots(figsize=(10, 3.8))
    im = ax.imshow(grid.values, aspect="auto")
    ax.set_yticks(range(7))
    ax.set_yticklabels(WEEKDAYS)
    ax.set_xticks(range(24))
    ax.set_xlabel("Hour of day created")
    ax.set_title("Requests by weekday and hour")
    fig.colorbar(im, ax=ax, label="Requests")
    fig.tight_layout()
    show_fig(fig)
    wk = df["created_weekday"].value_counts().reindex(WEEKDAYS).fillna(0).astype(int)
    hr = df["created_hour"].value_counts().sort_values(ascending=False).head(5)
    wk_df = wk.reset_index()
    wk_df.columns = ["Weekday", "Requests"]
    wk_chart = alt.Chart(wk_df).mark_bar().encode(
        x=alt.X("Weekday:N", sort=WEEKDAYS, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Requests:Q"),
        tooltip=["Weekday", alt.Tooltip("Requests:Q", format=",")],
    )
    st.altair_chart(wk_chart)
    observed(f"Busiest weekday: {wk.idxmax()} ({wk.max():,}); quietest: {wk.idxmin()} ({wk.min():,}). "
             f"Top hours: {', '.join(str(int(h)) + 'h' for h in hr.index)}.")
    caution("This shows when requests were created, not when problems happened.")


def page_status(df):
    st.header("Status and closure (Tasks 7 and 14)")

    t = (df.groupby("status").agg(requests=("unique_key", "size"),
                                  rows_with_closed_date=("is_closed", "sum"))
         .reset_index().sort_values("requests", ascending=False))
    t["pct_of_filtered"] = (100 * t["requests"] / len(df)).round(2)
    header("Task 7 - Distribution of recorded request statuses",
           "What statuses do requests carry, and do they agree with the closed date?",
           f"{len(df):,} requests")
    hbar(t["status"].tolist(), t["requests"].tolist(), "Requests by recorded status")
    st.dataframe(t, hide_index=True)
    mismatch = int(t.loc[t["status"] != "Closed", "rows_with_closed_date"].sum())
    observed(f"{mismatch:,} rows are not labelled 'Closed' but still have a recorded closed date.")
    caution("Status is the recorded label, not verified resolution. Status and closed "
            "date do not always agree, so the labels may follow different rules.")

    header("Task 14 - Recorded closure-rate comparison",
           "How does the share of rows marked closed differ by borough, agency and month?",
           f"{len(df):,} requests")
    st.metric("Overall recorded closure", fmt(100 * df["is_closed"].mean(), "{:.2f}%"))

    def rate_table(col):
        r = (df.groupby(col).agg(requests=("unique_key", "size"), closed=("is_closed", "sum"))
             .reset_index())
        r["closure_rate_pct"] = (100 * r["closed"] / r["requests"]).round(2)
        r["note"] = np.where(r["requests"] < MIN_N, f"n<{MIN_N}: not compared", "")
        return r.sort_values("closure_rate_pct", ascending=False)

    for col, label in [("borough", "borough"), ("agency", "agency")]:
        r = rate_table(col)
        big = r[r["requests"] >= MIN_N]
        if len(big):
            hbar(big[col].tolist(), big["closure_rate_pct"].tolist(),
                 f"Recorded closure rate by {label} (n >= {MIN_N})", xlabel="% closed", fmt_="{:.2f}")
        st.dataframe(r, hide_index=True)
        if len(big) >= 2:
            observed(f"Among {label}s with n >= {MIN_N}: highest {big.iloc[0][col]} "
                     f"({big.iloc[0]['closure_rate_pct']:.2f}%), lowest {big.iloc[-1][col]} "
                     f"({big.iloc[-1]['closure_rate_pct']:.2f}%).")

    mo = rate_table("created_ym").sort_values("created_ym")
    st.line_chart(mo.set_index("created_ym")["closure_rate_pct"])
    caution("Closure means a recorded closed date only, not satisfaction or verified resolution. "
            "Newer months have had less time to close, so a falling rate is not proof that "
            "service worsened. Low rates at some agencies may reflect how they record closure.")


def page_resolution(df):
    st.header("Resolution time (Tasks 8, 9, 10 and 12)")
    v = valid(df)["resolution_hours"]
    if v.empty:
        st.warning("No valid resolution durations in the filtered data.")
        return

    header("Task 8 - Descriptive statistics for valid resolution durations",
           "What do the valid resolution durations look like numerically?",
           f"{len(v):,} valid durations")
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    stats = [("Valid durations (n)", len(v)), ("Mean (h)", v.mean()), ("Median (h)", v.median()),
             ("Mode (h, rounded to whole hours)", v.round(0).mode().iloc[0]),
             ("Minimum (h)", v.min()), ("Maximum (h)", v.max()), ("Range (h)", v.max() - v.min()),
             ("Q1 (h)", q1), ("Q3 (h)", q3), ("IQR (h)", q3 - q1),
             ("Variance (h²)", v.var()), ("Standard deviation (h)", v.std()),
             ("Skewness", v.skew()), ("Excess kurtosis", v.kurt()),
             ("90th percentile (h)", v.quantile(0.90)), ("95th percentile (h)", v.quantile(0.95)),
             ("99th percentile (h)", v.quantile(0.99))]
    st.dataframe(pd.DataFrame({"statistic": [s[0] for s in stats],
                               "value": [round(float(s[1]), 2) for s in stats]}), hide_index=True)
    observed(f"The mean ({v.mean():,.1f} h) is far above the median ({v.median():,.1f} h): "
             "a few very long cases pull the mean up.")
    caution("The standard deviation is much larger than the mean. "
            "Long cases may be legitimate.")

    header("Task 12 - Resolution-time skewness and distribution",
           "How is resolution time distributed, and how skewed is it?", f"{len(v):,} valid durations")
    p95 = v.quantile(0.95)
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    axes[0, 0].hist(v, bins=50)
    axes[0, 0].set_title("Histogram (all valid durations)")
    axes[0, 1].hist(v[v <= p95], bins=50)
    axes[0, 1].set_title(f"Zoomed histogram (up to 95th percentile, {p95:,.0f} h)")
    pos = v[v > 0]
    if len(pos):
        axes[1, 0].boxplot(pos)
        axes[1, 0].set_yscale("log")
    axes[1, 0].set_title("Boxplot, log scale (zero hours not shown)")
    axes[1, 1].hist(np.log1p(v), bins=50)
    axes[1, 1].set_title("Histogram of log(1 + hours)")
    for a in axes.ravel():
        a.set_xlabel("")
    fig.tight_layout()
    show_fig(fig)

    bins = [-np.inf, 1, 24, 72, 168, np.inf]
    labels = ["1) under 1 hour", "2) 1 to 24 hours", "3) 24 to 72 hours",
              "4) 3 to 7 days", "5) over 7 days"]
    b = pd.cut(v, bins=bins, labels=labels, right=False).value_counts().reindex(labels)
    bt = pd.DataFrame({"duration_bucket": labels, "requests": b.values.astype(int)})
    bt["pct_of_valid"] = (100 * bt["requests"] / len(v)).round(2)
    st.dataframe(bt, hide_index=True)
    observed(f"{(v > THRESHOLD_HOURS).mean() * 100:.2f}% of valid durations exceed "
             f"{THRESHOLD_HOURS} h; skewness is {v.skew():.2f}.")
    caution("Outliers are retained. A mix of different request types and processes "
            "probably shapes the distribution (not tested here).")

    g = group_median(df, "complaint_type")
    elig = g[g["valid_durations"] >= MIN_N]
    header("Task 9 - Median resolution duration by complaint category",
           f"Which complaint types take longest/shortest to reach recorded closure (n >= {MIN_N})?",
           f"{len(elig)} categories with n >= {MIN_N}; {int(elig['valid_durations'].sum()):,} "
           f"of {len(v):,} valid durations")
    if elig.empty:
        st.info(f"No complaint type has {MIN_N}+ valid durations in the filtered data.")
    else:
        longest = elig.nlargest(10, "median_hours")
        hbar([f"{c} (n={n})" for c, n in zip(longest["complaint_type"], longest["valid_durations"])],
             longest["median_hours"].tolist(), "10 longest median resolution times",
             xlabel="Median hours", fmt_="{:,.1f}")
        st.dataframe(elig.sort_values("median_hours", ascending=False), hide_index=True)
        shortest = elig.nsmallest(1, "median_hours").iloc[0]
        observed(f"Longest median: {longest.iloc[0]['complaint_type']} "
                 f"({longest.iloc[0]['median_hours']:,.1f} h). Shortest: {shortest['complaint_type']} "
                 f"({shortest['median_hours']:,.2f} h).")
    caution("Medians reflect time to recorded closure and different process types, "
            "not service quality. Category differences may reflect case complexity.")

    g = group_median(df, "agency")
    g["note"] = np.where(g["valid_durations"] < MIN_N, f"n<{MIN_N}: not compared", "")
    elig = g[g["valid_durations"] >= MIN_N].sort_values("median_hours", ascending=False)
    header("Task 10 - Median resolution duration by agency",
           f"How do median resolution times differ by agency (n >= {MIN_N})?",
           f"{len(elig)} agencies with n >= {MIN_N}")
    if elig.empty:
        st.info(f"No agency has {MIN_N}+ valid durations in the filtered data.")
    else:
        hbar([f"{a} (n={n})" for a, n in zip(elig["agency"], elig["valid_durations"])],
             elig["median_hours"].tolist(), "Median resolution hours by agency",
             xlabel="Median hours", fmt_="{:,.1f}")
        observed(f"Medians range from {elig['median_hours'].min():,.2f} h "
                 f"({elig.iloc[-1]['agency']}) to {elig['median_hours'].max():,.2f} h "
                 f"({elig.iloc[0]['agency']}).")
    st.dataframe(g.sort_values("median_hours", ascending=False), hide_index=True)
    caution("Agency medians reflect case mix and operational definitions, not performance. "
            "One agency can dominate the overall median because of its volume.")


def page_outliers(df):
    st.header("IQR outlier investigation (Task 11)")
    v = valid(df)
    if v.empty:
        st.warning("No valid resolution durations in the filtered data.")
        return
    total = int(v["resolution_outlier_flag"].sum())
    header("Task 11 - IQR-based outlier investigation",
           "Which agencies and complaint types hold the long-duration outliers?",
           f"{len(v):,} valid durations; {total:,} flagged ({100 * total / len(v):.2f}%)")
    st.caption("Flag = stored resolution_outlier_flag: duration above Q3 + 1.5 x IQR, "
               "with Q1 and Q3 calculated once on the full dataset (not on the filtered rows).")

    def outlier_table(col):
        t = (v.groupby(col).agg(valid_durations=("resolution_hours", "size"),
                                outliers=("resolution_outlier_flag", "sum")).reset_index())
        t["outlier_pct"] = (100 * t["outliers"] / t["valid_durations"]).round(1)
        t["share_of_all_outliers"] = (100 * t["outliers"] / total).round(2) if total else 0.0
        return t.sort_values("outliers", ascending=False)

    ta = outlier_table("agency")
    top = ta.head(10)
    hbar(top["agency"].tolist(), top["outliers"].tolist(), "Outlier COUNT by agency", xlabel="Outliers")
    rate = ta[ta["valid_durations"] >= MIN_N].sort_values("outlier_pct", ascending=False)
    if len(rate):
        hbar(rate["agency"].tolist(), rate["outlier_pct"].tolist(),
             f"Outlier RATE by agency (n >= {MIN_N})", xlabel="% of agency's durations", fmt_="{:.1f}")
    st.dataframe(ta, hide_index=True)

    tc = outlier_table("complaint_type").head(10)
    st.markdown("**Top 10 complaint types by outlier count**")
    st.dataframe(tc, hide_index=True)
    if total:
        observed(f"{ta.iloc[0]['agency']} holds the most outliers ({int(ta.iloc[0]['outliers']):,}, "
                 f"{ta.iloc[0]['share_of_all_outliers']:.1f}% of all outliers).")
    caution("Count and rate tell different stories: large agencies lead on count because of "
            "volume. Where more than half of a category's durations are flagged, the pooled "
            "rule is flagging routine long cases. Outliers are investigation prompts, "
            "not deletion rules; all rows are retained.")


def page_geography(df):
    st.header("Geographic concentration (Task 13)")
    usable = df[(df["coord_missing_flag"] == 0) & (df["coord_out_of_nyc_flag"] == 0)
                & df["latitude"].notna() & df["longitude"].notna()]
    header("Task 13 - Geographic complaint concentration",
           "Where are requests concentrated (usable coordinates, ZIP codes, boroughs)?",
           f"{len(df):,} requests; {len(usable):,} with usable coordinates")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total requests", f"{len(df):,}")
    c2.metric("Missing coordinates", f"{int(df['coord_missing_flag'].sum()):,}")
    c3.metric("Outside NYC box", f"{int(df['coord_out_of_nyc_flag'].sum()):,}")
    c4.metric("Usable coordinates", f"{len(usable):,}")

    if len(usable) >= 10:
        fig, ax = plt.subplots(figsize=(7, 7))
        hb = ax.hexbin(usable["longitude"], usable["latitude"], gridsize=80, bins="log", mincnt=1)
        ax.set_aspect(1.3)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title("Request density (hexbin, log colour scale)")
        fig.colorbar(hb, ax=ax, label="log10(requests)")
        fig.tight_layout()
        show_fig(fig)
    else:
        st.info("Too few usable coordinates to draw a density map for these filters.")

    z = df[df["incident_zip"].notna() & (df["zip_invalid_flag"] == 0)]
    zt = (z["incident_zip"].value_counts().head(10).rename_axis("incident_zip")
          .reset_index(name="requests"))
    if len(zt):
        zt["pct_of_valid_zip"] = (100 * zt["requests"] / len(z)).round(2)
        hbar(zt["incident_zip"].tolist(), zt["requests"].tolist(), "Top 10 ZIP codes")
        st.dataframe(zt, hide_index=True)
        observed(f"The top 10 ZIP codes hold {zt['requests'].sum() / len(z) * 100:.1f}% of requests "
                 "that have a valid ZIP.")

    b = df[df["borough"] != "UNSPECIFIED"]
    if len(b):
        c = (b.groupby(["borough", "complaint_type"]).size().rename("requests").reset_index()
             .sort_values(["borough", "requests", "complaint_type"], ascending=[True, False, True]))
        c["borough_total"] = c.groupby("borough")["requests"].transform("sum")
        c["rank_in_borough"] = c.groupby("borough").cumcount() + 1
        c["pct_of_borough"] = (100 * c["requests"] / c["borough_total"]).round(1)
        st.markdown("**Top 3 complaint types in each borough**")
        st.dataframe(c[c["rank_in_borough"] <= 3][["borough", "rank_in_borough", "complaint_type",
                                                   "requests", "pct_of_borough"]], hide_index=True)
    caution("These are raw counts, not per-area or per-capita. Blank map areas are often water "
            "or parks. Rows without usable coordinates are left out of the map only.")


def page_priority(df):
    st.header("High volume and long resolution (Task 15)")
    vol = df.groupby("complaint_type").size().rename("requests")
    g = group_median(df, "complaint_type").set_index("complaint_type")
    m = g.join(vol, how="inner").reset_index()
    elig = m[m["valid_durations"] >= MIN_N]
    header("Task 15 - Categories with both high volume and long median resolution",
           "Which complaint types combine many requests with long median resolution times?",
           f"{len(elig)} categories with n >= {MIN_N} valid durations")
    if len(elig) < 4:
        st.info(f"Fewer than 4 complaint types have {MIN_N}+ valid durations with these filters, "
                "so a quadrant comparison is not meaningful. Widen the filters.")
        return
    vcut = elig["requests"].quantile(0.75)
    mcut = elig["median_hours"].quantile(0.75)
    both = elig[(elig["requests"] >= vcut) & (elig["median_hours"] >= mcut)]
    st.caption(f"Project-defined cut-offs (75th percentile among eligible categories): "
               f"volume >= {vcut:,.0f} requests; median >= {mcut:,.1f} h.")

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.scatter(elig["requests"], elig["median_hours"].clip(lower=0.1), alpha=0.6)
    ax.scatter(both["requests"], both["median_hours"].clip(lower=0.1), color="red")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.axvline(vcut, color="gray", linestyle="--")
    ax.axhline(mcut, color="gray", linestyle="--")
    ax.axhline(THRESHOLD_HOURS, color="lightgray", linestyle=":")
    for i, (_, r) in enumerate(both.sort_values("requests").iterrows()):
        up = (i % 2 == 1)
        ax.annotate(r["complaint_type"], (r["requests"], max(r["median_hours"], 0.1)),
                    xytext=(8, 16) if up else (-8, -20), textcoords="offset points",
                    ha="left" if up else "right", fontsize=8,
                    arrowprops={"arrowstyle": "-", "color": "gray", "lw": 0.6})
    ax.text(elig["requests"].max(), THRESHOLD_HOURS, "illustrative 72 h ",
            ha="right", va="bottom", fontsize=8, color="gray")
    ax.set_xlabel("Requests (log scale)")
    ax.set_ylabel("Median resolution hours (log scale)")
    ax.set_title("Volume vs median resolution time by complaint type")
    fig.tight_layout()
    show_fig(fig)

    if both.empty:
        observed("No category is in the top-right quadrant for these filters.")
    else:
        observed(f"{len(both)} categor{'y' if len(both) == 1 else 'ies'} combine high volume and "
                 f"long median: {', '.join(both.sort_values('requests', ascending=False)['complaint_type'])}.")
        out = both.copy()
        out["pct_of_filtered"] = (100 * out["requests"] / len(df)).round(2)
        st.dataframe(out.sort_values("requests", ascending=False), hide_index=True)
    caution("The cut-offs are analytical choices, not official standards. The median shows "
            "time to recorded closure, not quality. Only categories with n >= "
            f"{MIN_N} are ranked, and the quadrant depends on the percentile rule.")


PAGES = {
    "Overview and KPIs": page_overview,
    "Volume and mix (Tasks 1-4)": page_volume,
    "Time patterns (Tasks 5-6)": page_time,
    "Status and closure (Tasks 7, 14)": page_status,
    "Resolution time (Tasks 8-10, 12)": page_resolution,
    "Outliers (Task 11)": page_outliers,
    "Geography (Task 13)": page_geography,
    "Volume vs delay (Task 15)": page_priority,
}


# ===========================================================================
# 4. SIDEBAR FILTERS AND MAIN
# ===========================================================================
def sidebar_filters(opts):
    st.sidebar.header("Filters")
    dates = st.sidebar.date_input(
        "Created date range",
        value=(opts["min_date"], opts["max_date"]),
        min_value=opts["min_date"],
        max_value=opts["max_date"],
    )
    # While the user is picking, Streamlit may return only the start date
    if not (isinstance(dates, (tuple, list)) and len(dates) == 2):
        st.info("Select both a start date and an end date in the sidebar.")
        st.stop()
    boroughs = st.sidebar.multiselect(
        "Borough", opts["boroughs"], help="Leave empty to include all boroughs.")
    types = st.sidebar.multiselect(
        "Complaint type", opts["complaint_types"],
        help="Leave empty to include all complaint types.")
    return dates[0], dates[1], tuple(boroughs), tuple(types)


def main():
    st.title("Urban Pulse NYC")
    st.caption(
        "Citizen complaint intelligence & resolution analytics - NYC 311, "
        "about 3% sample, Oct 2025 to Sep 2026")

    st.sidebar.header("Analyst page")
    page = st.sidebar.radio("Choose a page", list(PAGES), label_visibility="collapsed")

    # Connection-error handling: show a readable message, not a crash
    try:
        opts = load_filter_options()
        start, end, boroughs, types = sidebar_filters(opts)
        df = load_data(start, end, boroughs, types)
    except Exception as exc:
        st.error(
            "Could not read the data from MySQL. Please check that:\n"
            "1. MySQL is running (XAMPP Control Panel -> Start next to MySQL)\n"
            "2. The database `urban_pulse_db` and table `service_requests` exist "
            "(run load_to_mysql.py if not)\n"
            "3. Your MYSQL_USER / MYSQL_PASSWORD settings are correct")
        with st.expander("Technical details"):
            st.code(str(exc))
        st.stop()

    st.caption(
        f"Filters: {start} to {end} | "
        f"Borough: {', '.join(boroughs) if boroughs else 'all'} | "
        f"Complaint type: {', '.join(types) if types else 'all'}")

    # Empty-state handling
    if df.empty:
        st.warning("No requests match these filters. Try a wider date range "
                   "or clear the borough / complaint-type selections.")
        st.stop()

    PAGES[page](df)


main()
