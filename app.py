import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import io
from datetime import datetime

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NYC & Remote Job Postings",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] { font-family: 'DM Mono', monospace; }

    h1, h2, h3 { font-family: 'Syne', sans-serif !important; }

    .block-container { padding-top: 2rem; max-width: 1400px; }

    div[data-testid="metric-container"] {
        background: #111118;
        border: 1px solid #1e1e2e;
        border-radius: 4px;
        padding: 1rem 1.25rem;
    }
    div[data-testid="metric-container"] label {
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #64748b !important;
        font-family: 'DM Mono', monospace !important;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-family: 'Syne', sans-serif !important;
        font-size: 2.2rem !important;
        font-weight: 800 !important;
    }

    .stTabs [data-baseweb="tab"] {
        font-family: 'DM Mono', monospace;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .stDataFrame { font-size: 12px; }

    .sidebar-section {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #64748b;
        margin: 1rem 0 0.4rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
GITHUB_USER = "abochnak"   # ← update this after pushing to GitHub
GITHUB_REPO = "historical-nyc-remote-job-postings"
BRANCH      = "main"

NYC_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
    f"/{BRANCH}/data/nyc_jobs.csv"
)
REM_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
    f"/{BRANCH}/data/remote_jobs.csv"
)
EXCLUDE_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
    f"/{BRANCH}/data/excluded_jobs.csv"
)

# Title patterns to flag as non-undergraduate internships
FILTER_PATTERNS = {
    "PhD positions":        r"\bphd\b|ph\.d|doctoral|postdoc",
    "Master's positions":   r"\bm\.s\b|\bms\b intern|\bmaster'?s\b",
    "Full-time / New Grad": r"new grad|full.time(?! student)|sde [i]+\b(?!ntern)",
    "Research Scientist":   r"research scientist(?! intern)",
}

NYC_COLOR    = "#f97316"
REMOTE_COLOR = "#38bdf8"

# ── Data loading ──────────────────────────────────────────────────────────────
# Set DEV=1 in your terminal to disable caching locally:
#   export DEV=1 && streamlit run app.py
import os
_cache_ttl = 0 if os.environ.get("DEV") else 300
@st.cache_data(ttl=_cache_ttl)
def load_data():
    def fetch(url):
        df = None
        fname = "nyc_jobs.csv" if "nyc" in url else "remote_jobs.csv"

        # Try GitHub — use a session with no conditional headers so we always
        # get a 200 with a body rather than a 304 with an empty body
        try:
            session = requests.Session()
            session.headers.update({
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
            })
            r = session.get(url, timeout=15)
            if r.status_code == 200 and r.text.strip():
                df = pd.read_csv(io.StringIO(r.text))
            elif r.status_code == 304:
                # 304 with no body — force a second request stripping all caching headers
                r2 = requests.get(url, timeout=15, headers={
                    "Cache-Control": "no-cache",
                    "If-None-Match": "",
                    "If-Modified-Since": "",
                })
                if r2.status_code == 200 and r2.text.strip():
                    df = pd.read_csv(io.StringIO(r2.text))
        except Exception:
            pass  # fall through to local

        # Fall back to local data/ folder (for local development)
        if df is None:
            local_paths = [
                f"data/{fname}",
                fname,
                f"../data/{fname}",
            ]
            for path in local_paths:
                try:
                    df = pd.read_csv(path)
                    break
                except FileNotFoundError:
                    continue

        if df is None:
            st.error(
                f"Could not load data.\n\n"
                f"**GitHub URL:** {url}\n\n"
                f"**Local fallback:** place `{fname}` in a `data/` folder next to `app.py`"
            )
            st.stop()
        return df

    nyc = fetch(NYC_URL)
    rem = fetch(REM_URL)

    # Load exclusion rules from excluded_jobs.csv
    excluded_ids = set()
    try:
        excl_df = fetch(EXCLUDE_URL)
        if "id" in excl_df.columns:
            excluded_ids = set(excl_df["id"].dropna().str.strip())
            excluded_ids.discard("")
    except Exception:
        pass  # exclusions are optional — proceed without them

    def apply_exclusions(df):
        return df[~df["id"].isin(excluded_ids)].reset_index(drop=True)

    nyc = apply_exclusions(nyc)
    rem = apply_exclusions(rem)

    for df, label in [(nyc, "NYC"), (rem, "Remote")]:
        df["dataset"] = label
        # Parse first_seen_date
        df["first_seen_date"] = pd.to_datetime(df["first_seen_date"], utc=True, errors="coerce")
        df["first_seen_month"] = df["first_seen_date"].dt.tz_localize(None).dt.to_period("M").astype(str)
        df["first_seen_year"]  = df["first_seen_date"].dt.year
        # Parse date_posted — handles Unix timestamps (seconds) and MM/DD/YYYY strings
        def parse_date_posted(series):
            results = []
            for val in series:
                if pd.isna(val):
                    results.append(pd.NaT)
                    continue
                s = str(val).strip()
                if s.isdigit() and len(s) >= 9:
                    results.append(pd.Timestamp(int(s), unit="s", tz="UTC"))
                else:
                    try:
                        results.append(pd.Timestamp(datetime.strptime(s, "%m/%d/%Y")).tz_localize("UTC"))
                    except Exception:
                        results.append(pd.NaT)
            return pd.Series(pd.to_datetime(results, utc=True, errors="coerce"))
        df["date_posted_dt"] = parse_date_posted(df["date_posted"]).values
        df["post_month"]     = df["date_posted_dt"].dt.month
        df["post_month_name"]= df["date_posted_dt"].dt.strftime("%B")
        df["title"]          = df["title"].str.strip()
        df["company_name"]   = df["company_name"].str.strip()

    return nyc, rem


def apply_filters(df, exclude_flags):
    mask = pd.Series(True, index=df.index)
    for flag, pattern in FILTER_PATTERNS.items():
        if flag in exclude_flags:
            mask &= ~df["title"].str.contains(pattern, case=False, na=False, regex=True)
    return df[mask]


# ── Load ──────────────────────────────────────────────────────────────────────
nyc_raw, rem_raw = load_data()

# ── Clear stale season widget state so defaults always reflect current year ──
_current_year = datetime.now().year
for _k in list(st.session_state.keys()):
    if _k.startswith("ts_seasons") and _k != f"ts_seasons_{_current_year}":
        del st.session_state[_k]

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧹 Data Cleaning")
    st.markdown('<div class="sidebar-section">Exclude title types</div>', unsafe_allow_html=True)

    exclude_flags = []
    for flag in FILTER_PATTERNS:
        if st.checkbox(flag, value=(flag == "PhD positions")):
            exclude_flags.append(flag)

    st.markdown('<div class="sidebar-section">Custom keyword filter</div>', unsafe_allow_html=True)
    custom_exclude = st.text_input(
        "Exclude titles containing",
        placeholder="e.g. staff, principal, director",
        label_visibility="collapsed",
    )

    st.markdown('<div class="sidebar-section">Seasons</div>', unsafe_allow_html=True)
    all_seasons = sorted(
        set(nyc_raw["recruiting_season"].dropna().unique())
        | set(rem_raw["recruiting_season"].dropna().unique())
    )
    # Pull out individual seasons from pipe-separated values
    flat_seasons = sorted(set(
        s.strip()
        for row in all_seasons
        for s in row.split("|")
        if s.strip() and s.strip() != "N/A"
    ))
    selected_seasons = st.multiselect(
        "Filter by season",
        options=flat_seasons,
        default=[],
        placeholder="All seasons",
        label_visibility="collapsed",
    )

    st.markdown('<div class="sidebar-section">Dataset</div>', unsafe_allow_html=True)
    dataset_choice = st.radio(
        "Show",
        ["NYC + Remote", "NYC only", "Remote only"],
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("🔄 Refresh data now", width='stretch'):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"Auto-refreshes every hour · Last load: {datetime.now().strftime('%H:%M:%S')}")


# ── Apply filters ─────────────────────────────────────────────────────────────
def season_match(df, selected):
    if not selected:
        return df
    mask = df["recruiting_season"].apply(
        lambda x: any(s in str(x) for s in selected) if pd.notna(x) else False
    )
    return df[mask]

nyc = apply_filters(nyc_raw, exclude_flags)
rem = apply_filters(rem_raw, exclude_flags)

if custom_exclude.strip():
    terms = [t.strip() for t in custom_exclude.split(",") if t.strip()]
    pattern = "|".join(terms)
    nyc = nyc[~nyc["title"].str.contains(pattern, case=False, na=False)]
    rem = rem[~rem["title"].str.contains(pattern, case=False, na=False)]

nyc = season_match(nyc, selected_seasons)
rem = season_match(rem, selected_seasons)

if dataset_choice == "NYC only":
    combined = nyc.copy()
elif dataset_choice == "Remote only":
    combined = rem.copy()
else:
    combined = pd.concat([nyc, rem], ignore_index=True)

removed_nyc = len(nyc_raw) - len(nyc)
removed_rem = len(rem_raw) - len(rem)


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# NYC & Remote Job Postings")
st.caption(f"SimplifyJobs · Aug 2023 – present · {removed_nyc + removed_rem:,} rows filtered out")

# ── Stats ─────────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("NYC Jobs",         f"{len(nyc):,}")
c2.metric("Remote Jobs",      f"{len(rem):,}")
c3.metric("Total",            f"{len(combined):,}")
c4.metric("Companies",        f"{combined['company_name'].nunique():,}")
c5.metric("Unique Titles",    f"{combined['title'].nunique():,}")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_trend, tab_timeseries, tab_companies, tab_titles, tab_seasons, tab_cleaner = st.tabs([
    "📈 Trends Over Time",
    "📊 Season Time Series",
    "🏢 Companies",
    "🔤 Job Titles",
    "📅 Seasons",
    "🧹 Raw Data & Cleaner",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — TRENDS OVER TIME
# ════════════════════════════════════════════════════════════════════════════
with tab_trend:
    st.markdown("### New postings per month")
    st.caption("Each bar = job IDs first appearing in the repo that month")

    nyc_monthly = nyc.groupby("first_seen_month").size().reset_index(name="count")
    nyc_monthly["dataset"] = "NYC"
    rem_monthly = rem.groupby("first_seen_month").size().reset_index(name="count")
    rem_monthly["dataset"] = "Remote"
    monthly = pd.concat([nyc_monthly, rem_monthly])

    fig = px.bar(
        monthly, x="first_seen_month", y="count", color="dataset",
        color_discrete_map={"NYC": NYC_COLOR, "Remote": REMOTE_COLOR},
        barmode="group",
        labels={"first_seen_month": "", "count": "New postings", "dataset": ""},
        height=380,
    )
    fig.update_layout(
        plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
        font_color="#e2e8f0", font_family="DM Mono",
        legend=dict(orientation="h", y=1.1),
        xaxis=dict(tickangle=-45, gridcolor="#1e1e2e"),
        yaxis=dict(gridcolor="#1e1e2e"),
        margin=dict(l=0, r=0, t=20, b=0),
    )
    st.plotly_chart(fig, width='stretch')





# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — SEASON TIME SERIES
# ════════════════════════════════════════════════════════════════════════════
with tab_timeseries:
    st.markdown("### When do companies first post jobs?")
    st.caption("Each point = new job postings first appearing in the repo that period, by recruiting season")

    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 2, 1])

    with col_ctrl1:
        current_year = datetime.now().year
        # Build season list — cap at current_year to exclude future seasons
        # outliers that come from multi-season postings (e.g. "Summer 2028")
        all_flat_seasons = sorted(set(
            s.strip()
            for row in combined["recruiting_season"].dropna()
            for s in str(row).split("|")
            if s.strip() and s.strip() not in ("N/A", "nan")
        ), key=lambda s: (
            int(s.split()[-1]) if s.split()[-1].isdigit() else 9999,
            ["Summer","Fall","Winter","Spring"].index(s.split()[0])
            if s.split()[0] in ["Summer","Fall","Winter","Spring"] else 99
        ))
        # Default: Summer current_year + Summer next_year (e.g. Summer 2026, Summer 2027)
        target = {f"Summer {current_year}", f"Summer {current_year + 1}"}
        default_ts = [s for s in all_flat_seasons if s in target]
        if not default_ts:
            default_ts = all_flat_seasons[-2:] if len(all_flat_seasons) >= 2 else all_flat_seasons
        ts_seasons = st.multiselect(
            "Recruiting seasons to display",
            options=all_flat_seasons,
            default=default_ts,
            key=f"ts_seasons_{current_year}",
        )

    with col_ctrl2:
        ts_dataset = st.radio(
            "Dataset",
            ["NYC + Remote", "NYC only", "Remote only"],
            horizontal=True,
            key="ts_dataset",
        )

    with col_ctrl3:
        ts_granularity = st.radio("Granularity", ["Daily", "Weekly", "Monthly"], key="ts_granularity")
        show_total = st.checkbox("Show total line", value=True, key="ts_show_total")

    if not ts_seasons:
        st.info("Select at least one recruiting season above.")
    else:
        if ts_dataset == "NYC only":
            df_ts_src = nyc.copy()
        elif ts_dataset == "Remote only":
            df_ts_src = rem.copy()
        else:
            df_ts_src = combined.copy()

        TOTAL_LABEL = "── Total (all seasons) ──"

        # Always use first_seen_date — most reliable timeline indicator
        # Per-season rows: one entry per job x season pair
        rows_ts = []
        for _, row in df_ts_src.iterrows():
            for s in str(row["recruiting_season"]).split("|"):
                s = s.strip()
                if s and s not in ("N/A", "nan") and s in ts_seasons:
                    rows_ts.append({"season": s, "date_val": row["first_seen_date"]})

        # Total line: every unique job regardless of season
        rows_total = [
            {"season": TOTAL_LABEL, "date_val": row["first_seen_date"]}
            for _, row in df_ts_src.iterrows()
        ]

        all_rows = rows_ts + (rows_total if show_total else [])

        if not all_rows:
            st.warning("No data found for the selected seasons and dataset.")
        else:
            st.caption(
                "Each season line counts jobs whose recruiting season includes that label, "
                "grouped by **first seen date** (when our scraper first discovered the job). "
                "The **Total** line counts every unique job regardless of season."
            )

            df_ts = pd.DataFrame(all_rows)
            df_ts["date_val"] = pd.to_datetime(df_ts["date_val"], utc=True, errors="coerce")
            df_ts = df_ts.dropna(subset=["date_val"])

            # Strip timezone before to_period() to avoid pandas UserWarning
            df_ts["date_val_naive"] = df_ts["date_val"].dt.tz_localize(None) \
                if df_ts["date_val"].dt.tz is None else df_ts["date_val"].dt.tz_convert(None)

            if ts_granularity == "Daily":
                df_ts["period"] = df_ts["date_val_naive"].dt.to_period("D").apply(lambda p: p.start_time)
                fill_freq = "D"
                tick_fmt  = "%b %d, %Y"
            elif ts_granularity == "Weekly":
                df_ts["period"] = df_ts["date_val_naive"].dt.to_period("W").apply(lambda p: p.start_time)
                fill_freq = "W-MON"
                tick_fmt  = "%b %d, %Y"
            else:
                df_ts["period"] = df_ts["date_val_naive"].dt.to_period("M").apply(lambda p: p.start_time)
                fill_freq = "MS"
                tick_fmt  = "%b %Y"

            all_season_labels = ts_seasons + ([TOTAL_LABEL] if show_total else [])

            weekly = (
                df_ts.groupby(["period", "season"])
                .size()
                .reset_index(name="count")
            )

            all_periods = pd.date_range(
                start=weekly["period"].min(),
                end=weekly["period"].max(),
                freq=fill_freq,
            )
            idx = pd.MultiIndex.from_product([all_periods, all_season_labels], names=["period", "season"])
            weekly = (
                weekly.set_index(["period", "season"])
                .reindex(idx, fill_value=0)
                .reset_index()
            )
            weekly["week"] = pd.to_datetime(weekly["period"])

            season_order_ts = sorted(
                ts_seasons,
                key=lambda s: (
                    int(s.split()[-1]) if s.split()[-1].isdigit() else 9999,
                    ["Summer","Fall","Winter","Spring"].index(s.split()[0])
                    if s.split()[0] in ["Summer","Fall","Winter","Spring"] else 99
                )
            ) + ([TOTAL_LABEL] if show_total else [])

            color_seq = px.colors.qualitative.Bold
            color_map = {s: color_seq[i % len(color_seq)] for i, s in enumerate(ts_seasons)}
            if show_total:
                color_map[TOTAL_LABEL] = "#94a3b8"

            fig_ts = px.line(
                weekly,
                x="week",
                y="count",
                color="season",
                category_orders={"season": season_order_ts},
                color_discrete_map=color_map,
                labels={"week": "", "count": "New postings", "season": "Season"},
                height=460,
            )
            fig_ts.update_traces(line_width=2.5, mode="lines+markers", marker_size=4)
            for trace in fig_ts.data:
                if TOTAL_LABEL in trace.name:
                    trace.line.dash = "dot"
                    trace.line.width = 2
                    trace.marker.size = 3
            fig_ts.update_layout(
                plot_bgcolor="#0a0a0f",
                paper_bgcolor="#0a0a0f",
                font_color="#e2e8f0",
                font_family="DM Mono",
                legend=dict(orientation="h", y=-0.18, x=0, font_size=11),
                xaxis=dict(gridcolor="#1e1e2e", tickformat=tick_fmt, tickangle=-30),
                yaxis=dict(gridcolor="#1e1e2e"),
                margin=dict(l=0, r=0, t=30, b=80),
                hovermode="x unified",
            )

            selected = st.plotly_chart(
                fig_ts,
                width='stretch',
                on_select="rerun",
                key="ts_chart",
            )

            # ── Peak period table ─────────────────────────────────────────
            st.markdown("#### Peak posting period per season (by first seen date)")
            peak_df = weekly[weekly["season"] != TOTAL_LABEL]
            if not peak_df.empty:
                peak = (
                    peak_df.loc[peak_df.groupby("season")["count"].idxmax()]
                    [["season", "week", "count"]]
                    .rename(columns={"season": "Season", "week": "Peak Period", "count": "Postings"})
                    .sort_values("Season")
                    .reset_index(drop=True)
                )
                peak["Peak Period"] = peak["Peak Period"].dt.strftime(tick_fmt)
                st.dataframe(peak, width='stretch', hide_index=True)

            # ── Drill-down ────────────────────────────────────────────────
            st.markdown("#### Drill-down: jobs posted in a period")
            st.caption("Click a point on the chart, or pick a date in the calendar below")

            # Calendar bounds based on first_seen_date
            bound_dates = pd.to_datetime(df_ts_src["first_seen_date"], utc=True, errors="coerce").dropna()
            min_date    = bound_dates.min().date()
            max_date    = bound_dates.max().date()

            # Parse clicked point — store in a separate key so it doesn't
            # conflict with the date_input widget's own state management
            if selected and selected.get("selection") and selected["selection"].get("points"):
                pt = selected["selection"]["points"][0]
                raw_x = pt.get("x", "")
                if raw_x:
                    try:
                        clicked = pd.to_datetime(raw_x).date()
                        clicked = max(min_date, min(max_date, clicked))
                        # Only update if different from current value to avoid
                        # infinite rerun loops
                        if st.session_state.get("drill_date_clicked") != clicked:
                            st.session_state["drill_date_clicked"] = clicked
                            st.session_state["drill_date_value"]   = clicked
                    except Exception:
                        pass

            # Use separate value state — lets the user also change it freely
            # without fighting the chart click
            current_drill_date = st.session_state.get("drill_date_value", min_date)

            drill_col1, drill_col2 = st.columns([2, 3])
            with drill_col1:
                drill_date = st.date_input(
                    "Pick a date",
                    value=current_drill_date,
                    min_value=min_date,
                    max_value=max_date,
                    label_visibility="collapsed",
                )
                # Write user's manual selection back to state
                st.session_state["drill_date_value"] = drill_date
                if st.session_state.get("drill_date_clicked") == drill_date:
                    st.caption("📍 Synced from chart click")
            with drill_col2:
                drill_season = st.multiselect(
                    "Filter by season",
                    options=ts_seasons,
                    default=[],
                    key="drill_season",
                    placeholder="All selected seasons",
                    label_visibility="collapsed",
                )

            # Filter by first_seen_date — most reliable timeline indicator
            drill_src = df_ts_src.copy()
            drill_dates = pd.to_datetime(drill_src["first_seen_date"], utc=True, errors="coerce")
            if hasattr(drill_dates.dtype, "tz") and drill_dates.dtype.tz is not None:
                drill_dates = drill_dates.dt.tz_localize(None)
            drill_src["_drill_date"] = drill_dates

            drill_date_ts = pd.Timestamp(drill_date)  # timezone-naive

            if ts_granularity == "Daily":
                day_start = drill_date_ts
                day_end   = drill_date_ts + pd.Timedelta(days=1)
                drill_result = drill_src[
                    (drill_src["_drill_date"] >= day_start) &
                    (drill_src["_drill_date"] <  day_end)
                ].copy()
                period_label = drill_date_ts.strftime("%b %d, %Y")
            elif ts_granularity == "Weekly":
                week_start = drill_date_ts - pd.Timedelta(days=drill_date_ts.weekday())
                week_end   = week_start + pd.Timedelta(days=6)
                drill_result = drill_src[
                    (drill_src["_drill_date"] >= week_start) &
                    (drill_src["_drill_date"] <= week_end)
                ].copy()
                period_label = f"week of {week_start.strftime('%b %d, %Y')}"
            else:
                drill_result = drill_src[
                    (drill_src["_drill_date"].dt.year  == drill_date_ts.year) &
                    (drill_src["_drill_date"].dt.month == drill_date_ts.month)
                ].copy()
                period_label = drill_date_ts.strftime("%B %Y")

            if drill_season:
                drill_result = drill_result[
                    drill_result["recruiting_season"].apply(
                        lambda x: any(s in str(x) for s in drill_season)
                    )
                ]

            drill_result = drill_result.sort_values(["company_name", "title"])

            if drill_result.empty:
                st.info(f"No jobs found for {period_label}.")
            else:
                st.caption(f"**{len(drill_result):,} jobs** posted during {period_label}")
                show_drill_cols = ["company_name", "title", "recruiting_season", "url"]
                available = [c for c in show_drill_cols if c in drill_result.columns]
                st.dataframe(
                    drill_result[available]
                    .rename(columns={
                        "company_name": "Company",
                        "title": "Title",
                        "recruiting_season": "Season",
                        "url": "URL",
                    })
                    .reset_index(drop=True),
                    width='stretch',
                    height=min(400, 40 + len(drill_result) * 35),
                )

            with st.expander("Show full data table"):
                pivot = (
                    weekly.pivot(index="week", columns="season", values="count")
                    .fillna(0).astype(int)
                    .sort_index(ascending=False)
                    .reset_index()
                )
                pivot["week"] = pivot["week"].dt.strftime(tick_fmt)
                pivot = pivot.rename(columns={"week": "Period"})
                st.dataframe(pivot, width='stretch', hide_index=True)

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMPANIES
# ════════════════════════════════════════════════════════════════════════════
with tab_companies:
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.markdown("### Top companies by posting volume")
        top_n = st.slider("Show top N companies", 5, 30, 15, key="top_n_co")
        view  = st.radio("Dataset", ["NYC", "Remote", "Both"], horizontal=True, key="co_view")

        if view == "NYC":
            df_co = nyc
            color = NYC_COLOR
        elif view == "Remote":
            df_co = rem
            color = REMOTE_COLOR
        else:
            df_co = combined
            color = "#a78bfa"

        co_counts = (
            df_co.groupby("company_name").size()
            .sort_values(ascending=True)
            .tail(top_n)
            .reset_index(name="count")
        )
        fig3 = px.bar(
            co_counts, x="count", y="company_name", orientation="h",
            color_discrete_sequence=[color],
            labels={"count": "Postings", "company_name": ""},
            height=max(350, top_n * 28),
        )
        fig3.update_layout(
            plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
            font_color="#e2e8f0", font_family="DM Mono",
            xaxis=dict(gridcolor="#1e1e2e"),
            yaxis=dict(gridcolor="rgba(0,0,0,0)"),
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig3, width='stretch')

    with col_r:
        st.markdown("### Average posting month by company")
        st.caption("Which month of the year companies typically post internships")

        df_avg = combined.dropna(subset=["post_month"])
        avg_month = (
            df_avg.groupby("company_name")["post_month"]
            .mean()
            .reset_index(name="avg_post_month")
        )
        count_per = df_avg.groupby("company_name").size().reset_index(name="total")
        avg_month = avg_month.merge(count_per, on="company_name")
        avg_month = avg_month[avg_month["total"] >= 3].sort_values("avg_post_month")
        avg_month["month_name"] = avg_month["avg_post_month"].apply(
            lambda m: datetime(2000, round(m), 1).strftime("%b") if 1 <= round(m) <= 12 else "?"
        )

        st.dataframe(
            avg_month[["company_name", "month_name", "total"]]
            .rename(columns={"company_name": "Company", "month_name": "Avg Post Month", "total": "# Postings"})
            .reset_index(drop=True),
            width='stretch',
            height=500,
        )


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — JOB TITLES
# ════════════════════════════════════════════════════════════════════════════
with tab_titles:
    st.markdown("### Title distribution")

    col_a, col_b = st.columns([1, 1])

    with col_a:
        st.markdown("#### Top titles by frequency")
        n_titles = st.slider("Show top N titles", 10, 50, 20, key="n_titles")
        view_t = st.radio("Dataset", ["NYC", "Remote", "Both"], horizontal=True, key="title_view")

        df_t = {"NYC": nyc, "Remote": rem, "Both": combined}[view_t]
        title_counts = (
            df_t.groupby("title").size()
            .sort_values(ascending=True)
            .tail(n_titles)
            .reset_index(name="count")
        )
        color_t = {"NYC": NYC_COLOR, "Remote": REMOTE_COLOR, "Both": "#a78bfa"}[view_t]
        fig4 = px.bar(
            title_counts, x="count", y="title", orientation="h",
            color_discrete_sequence=[color_t],
            labels={"count": "Postings", "title": ""},
            height=max(400, n_titles * 26),
        )
        fig4.update_layout(
            plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
            font_color="#e2e8f0", font_family="DM Mono",
            xaxis=dict(gridcolor="#1e1e2e"),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(size=11)),
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig4, width='stretch')

    with col_b:
        st.markdown("#### Title category breakdown")
        st.caption("Rough groupings by keyword match")

        def categorize(title):
            t = str(title).lower()
            if any(x in t for x in ["software", "swe", "sde"]): return "Software Engineering"
            if any(x in t for x in ["data science", "data scientist"]): return "Data Science"
            if any(x in t for x in ["data engineer", "data infra"]): return "Data Engineering"
            if any(x in t for x in ["machine learning", "ml engineer", "ai/ml"]): return "ML / AI"
            if any(x in t for x in ["product manager", "pm intern", "product management"]): return "Product"
            if any(x in t for x in ["quant", "quantitative"]): return "Quant"
            if any(x in t for x in ["finance", "investment", "banking", "trading"]): return "Finance"
            if any(x in t for x in ["design", "ux", "ui "]): return "Design"
            if any(x in t for x in ["security", "cybersecurity", "infosec"]): return "Security"
            if any(x in t for x in ["research"]): return "Research"
            if any(x in t for x in ["devops", "cloud", "platform", "infrastructure", "sre"]): return "DevOps / Infra"
            if any(x in t for x in ["analyst", "analytics", "business intelligence"]): return "Analytics"
            return "Other"

        df_t2 = combined.copy()
        df_t2["category"] = df_t2["title"].apply(categorize)
        cat_counts = df_t2["category"].value_counts().reset_index()
        cat_counts.columns = ["category", "count"]

        fig5 = px.pie(
            cat_counts, names="category", values="count",
            color_discrete_sequence=px.colors.qualitative.Set3,
            height=400,
        )
        fig5.update_traces(textinfo="label+percent", textfont_size=11)
        fig5.update_layout(
            plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
            font_color="#e2e8f0", font_family="DM Mono",
            showlegend=False,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig5, width='stretch')

    st.markdown("#### All titles — searchable table")
    search = st.text_input("Search titles", placeholder="e.g. machine learning, quant, design")
    df_titles_all = combined[["title", "company_name", "recruiting_season", "dataset", "first_seen_date"]].copy()
    df_titles_all["first_seen_date"] = df_titles_all["first_seen_date"].dt.strftime("%Y-%m-%d")
    if search.strip():
        df_titles_all = df_titles_all[
            df_titles_all["title"].str.contains(search.strip(), case=False, na=False)
        ]
    st.dataframe(
        df_titles_all.rename(columns={
            "title": "Title", "company_name": "Company",
            "recruiting_season": "Season", "dataset": "Type",
            "first_seen_date": "First Seen",
        }).reset_index(drop=True),
        width='stretch',
        height=400,
    )
    st.caption(f"{len(df_titles_all):,} rows shown")


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — SEASONS
# ════════════════════════════════════════════════════════════════════════════
with tab_seasons:
    st.markdown("### Postings by recruiting season")

    def expand_seasons(df):
        rows = []
        for _, row in df.iterrows():
            seasons = [s.strip() for s in str(row["recruiting_season"]).split("|") if s.strip() and s.strip() != "N/A"]
            for s in seasons:
                rows.append({"season": s, "dataset": row["dataset"]})
        return pd.DataFrame(rows)

    seasons_expanded = expand_seasons(combined)
    season_order = sorted(
        seasons_expanded["season"].unique(),
        key=lambda s: (
            int(s.split()[-1]) if s.split()[-1].isdigit() else 9999,
            ["Summer","Fall","Winter","Spring"].index(s.split()[0]) if s.split()[0] in ["Summer","Fall","Winter","Spring"] else 99
        )
    )

    fig6 = px.histogram(
        seasons_expanded, x="season", color="dataset",
        color_discrete_map={"NYC": NYC_COLOR, "Remote": REMOTE_COLOR},
        barmode="group",
        category_orders={"season": season_order},
        labels={"season": "", "count": "Postings", "dataset": ""},
        height=380,
    )
    fig6.update_layout(
        plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
        font_color="#e2e8f0", font_family="DM Mono",
        legend=dict(orientation="h", y=1.1),
        xaxis=dict(tickangle=-45, gridcolor="#1e1e2e"),
        yaxis=dict(gridcolor="#1e1e2e"),
        margin=dict(l=0, r=0, t=20, b=0),
    )
    st.plotly_chart(fig6, width='stretch')

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### NYC seasons")
        nyc_s = expand_seasons(nyc)["season"].value_counts().reset_index()
        nyc_s.columns = ["Season", "Postings"]
        st.dataframe(nyc_s, width='stretch', height=300)
    with col2:
        st.markdown("#### Remote seasons")
        rem_s = expand_seasons(rem)["season"].value_counts().reset_index()
        rem_s.columns = ["Season", "Postings"]
        st.dataframe(rem_s, width='stretch', height=300)


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — RAW DATA & CLEANER
# ════════════════════════════════════════════════════════════════════════════
with tab_cleaner:
    st.markdown("### Raw data viewer & cleaner")

    col_cfg, _ = st.columns([2, 3])
    with col_cfg:
        show_ds   = st.radio("Dataset", ["NYC", "Remote"], horizontal=True, key="raw_ds")
        show_cols = st.multiselect(
            "Columns to show",
            options=["company_name", "title", "recruiting_season", "date_posted", "first_seen_date", "url", "id"],
            default=["company_name", "title", "recruiting_season", "date_posted", "first_seen_date"],
        )

    df_raw = nyc if show_ds == "NYC" else rem
    df_display = df_raw[show_cols].copy()
    if "first_seen_date" in df_display.columns:
        df_display["first_seen_date"] = df_display["first_seen_date"].dt.strftime("%Y-%m-%d")

    # Show what's being filtered
    if exclude_flags or custom_exclude.strip():
        st.info(
            f"Active filters: {', '.join(exclude_flags)}"
            + (f" + custom: '{custom_exclude}'" if custom_exclude.strip() else "")
            + f"  →  {len(nyc_raw) - len(nyc):,} NYC rows and {len(rem_raw) - len(rem):,} remote rows removed"
        )

    st.dataframe(
        df_display.rename(columns={
            "company_name": "Company", "title": "Title",
            "recruiting_season": "Season", "date_posted": "Posted",
            "first_seen_date": "First Seen", "url": "URL", "id": "ID",
        }).reset_index(drop=True),
        width='stretch',
        height=500,
    )
    st.caption(f"{len(df_display):,} rows · use sidebar filters to clean")

    st.markdown("#### Download filtered data")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "⬇ Download filtered NYC CSV",
            data=nyc.drop(columns=["first_seen_month","first_seen_year","date_posted_dt","post_month","post_month_name","dataset"], errors="ignore").to_csv(index=False),
            file_name="nyc_jobs_filtered.csv",
            mime="text/csv",
            width='stretch',
        )
    with col_dl2:
        st.download_button(
            "⬇ Download filtered Remote CSV",
            data=rem.drop(columns=["first_seen_month","first_seen_year","date_posted_dt","post_month","post_month_name","dataset"], errors="ignore").to_csv(index=False),
            file_name="remote_jobs_filtered.csv",
            mime="text/csv",
            width='stretch',
        )