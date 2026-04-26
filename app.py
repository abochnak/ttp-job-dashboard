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
GITHUB_USER = "YOUR_GITHUB_USERNAME"   # ← update this after pushing to GitHub
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
@st.cache_data(ttl=3600)   # refresh every hour
def load_data():
    def fetch(url):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
        except Exception:
            # Fall back to local files for development
            fname = "nyc_jobs.csv" if "nyc" in url else "remote_jobs.csv"
            try:
                df = pd.read_csv(f"data/{fname}")
            except FileNotFoundError:
                st.error(f"Could not load data from {url} or local data/ folder.")
                st.stop()
        return df

    nyc = fetch(NYC_URL)
    rem = fetch(REM_URL)

    for df, label in [(nyc, "NYC"), (rem, "Remote")]:
        df["dataset"] = label
        # Parse first_seen_date
        df["first_seen_date"] = pd.to_datetime(df["first_seen_date"], utc=True, errors="coerce")
        df["first_seen_month"] = df["first_seen_date"].dt.to_period("M").astype(str)
        df["first_seen_year"]  = df["first_seen_date"].dt.year
        # Parse date_posted (MM/DD/YYYY)
        df["date_posted_dt"] = pd.to_datetime(df["date_posted"], format="%m/%d/%Y", errors="coerce")
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
    if st.button("🔄 Refresh data now", use_container_width=True):
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
tab_trend, tab_companies, tab_titles, tab_seasons, tab_cleaner = st.tabs([
    "📈 Trends Over Time",
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
    st.plotly_chart(fig, use_container_width=True)

    # Cumulative
    st.markdown("### Cumulative postings over time")
    nyc_cum = nyc.groupby("first_seen_month").size().cumsum().reset_index(name="count")
    nyc_cum["dataset"] = "NYC"
    rem_cum = rem.groupby("first_seen_month").size().cumsum().reset_index(name="count")
    rem_cum["dataset"] = "Remote"
    cum = pd.concat([nyc_cum, rem_cum])

    fig2 = px.line(
        cum, x="first_seen_month", y="count", color="dataset",
        color_discrete_map={"NYC": NYC_COLOR, "Remote": REMOTE_COLOR},
        labels={"first_seen_month": "", "count": "Cumulative postings", "dataset": ""},
        height=320,
    )
    fig2.update_traces(line_width=2.5)
    fig2.update_layout(
        plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
        font_color="#e2e8f0", font_family="DM Mono",
        legend=dict(orientation="h", y=1.1),
        xaxis=dict(tickangle=-45, gridcolor="#1e1e2e"),
        yaxis=dict(gridcolor="#1e1e2e"),
        margin=dict(l=0, r=0, t=20, b=0),
    )
    st.plotly_chart(fig2, use_container_width=True)


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
        st.plotly_chart(fig3, use_container_width=True)

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
            use_container_width=True,
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
        st.plotly_chart(fig4, use_container_width=True)

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
        st.plotly_chart(fig5, use_container_width=True)

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
        use_container_width=True,
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
    st.plotly_chart(fig6, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### NYC seasons")
        nyc_s = expand_seasons(nyc)["season"].value_counts().reset_index()
        nyc_s.columns = ["Season", "Postings"]
        st.dataframe(nyc_s, use_container_width=True, height=300)
    with col2:
        st.markdown("#### Remote seasons")
        rem_s = expand_seasons(rem)["season"].value_counts().reset_index()
        rem_s.columns = ["Season", "Postings"]
        st.dataframe(rem_s, use_container_width=True, height=300)


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
        use_container_width=True,
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
            use_container_width=True,
        )
    with col_dl2:
        st.download_button(
            "⬇ Download filtered Remote CSV",
            data=rem.drop(columns=["first_seen_month","first_seen_year","date_posted_dt","post_month","post_month_name","dataset"], errors="ignore").to_csv(index=False),
            file_name="remote_jobs_filtered.csv",
            mime="text/csv",
            use_container_width=True,
        )