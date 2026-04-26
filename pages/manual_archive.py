import streamlit as st
import pandas as pd
import requests
import io
import csv
from datetime import datetime, timezone

st.set_page_config(
    page_title="Manual Archive",
    page_icon="📦",
    layout="wide",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono:wght@400;500&display=swap');
    html, body, [class*="css"] { font-family: 'DM Mono', monospace; font-size: 13px; }
    h1, h2, h3 { font-family: 'Syne', sans-serif !important; }
    .block-container { padding-top: 2rem; max-width: 1100px; }
    .info-box {
        background: #111118;
        border: 1px solid #1e1e2e;
        border-radius: 4px;
        padding: 12px 16px;
        font-size: 12px;
        color: #64748b;
        margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
GITHUB_USER = "YOUR_GITHUB_USERNAME"
GITHUB_REPO = "historical-nyc-remote-job-postings"
BRANCH      = "main"
BASE_URL    = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{BRANCH}/data"

DETAILS_URL = f"{BASE_URL}/job_details.csv"
NYC_URL     = f"{BASE_URL}/nyc_jobs.csv"
REM_URL     = f"{BASE_URL}/remote_jobs.csv"

DETAILS_HEADERS = [
    "id", "company_name", "title", "job_url",
    "archive_url", "archive_source",
    "archive_status", "scrape_status",
    "category", "date_archived",
]

CATEGORIES = [
    "",
    "Software Engineering",
    "Data Analysis",
    "Machine Learning / AI",
    "Cybersecurity",
    "Product Management",
    "Quant / Finance",
    "IT Support",
    "Other",
]

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_csv_url(url):
    try:
        r = requests.get(url, timeout=15, headers={"Cache-Control": "no-cache"})
        if r.status_code == 200 and r.text.strip():
            return pd.read_csv(io.StringIO(r.text))
    except Exception:
        pass
    return pd.DataFrame()

# ── Page ──────────────────────────────────────────────────────────────────────
st.markdown("# Manual Archive Entry")
st.caption("Add or update an archive URL for any job that wasn't archived automatically")

if st.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

details_df = load_csv_url(DETAILS_URL)
nyc_df     = load_csv_url(NYC_URL)
rem_df     = load_csv_url(REM_URL)

# Combine nyc + remote for job lookup
all_jobs_df = pd.concat([nyc_df, rem_df], ignore_index=True).drop_duplicates(subset="id")

st.divider()

# ── Section 1: Update an existing job in job_details ─────────────────────────
st.markdown("### Update an existing job")
st.caption("Find a job that's already in job_details.csv and add or correct its archive URL")

if details_df.empty:
    st.info("job_details.csv is empty — no jobs to update yet.")
else:
    # Filter to jobs missing or failed archive
    needs_archive = details_df[
        details_df["archive_status"].isin(["failed", ""]) |
        details_df["archive_url"].isna() |
        (details_df["archive_url"] == "")
    ] if not details_df.empty else pd.DataFrame()

    tab_missing, tab_all = st.tabs([
        f"Needs archive ({len(needs_archive)})",
        f"All jobs ({len(details_df)})"
    ])

    def render_update_form(df, key_prefix):
        if df.empty:
            st.info("No jobs in this view.")
            return

        search = st.text_input("Search company or title", key=f"{key_prefix}_search")
        if search.strip():
            df = df[
                df["company_name"].str.contains(search, case=False, na=False) |
                df["title"].str.contains(search, case=False, na=False)
            ]

        options = [
            f"{row['company_name']} — {row['title']}"
            for _, row in df.iterrows()
        ]
        if not options:
            st.info("No matches.")
            return

        selected_label = st.selectbox("Select job", options=options, key=f"{key_prefix}_select")
        selected_idx   = options.index(selected_label)
        selected_row   = df.iloc[selected_idx]
        jid            = str(selected_row["id"])

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Company:** {selected_row['company_name']}")
            st.markdown(f"**Title:** {selected_row['title']}")
            if selected_row.get("job_url"):
                st.markdown(f"[🔗 Original posting]({selected_row['job_url']})")
        with col2:
            current_archive = selected_row.get("archive_url", "") or ""
            current_source  = selected_row.get("archive_source", "") or ""
            if current_archive:
                st.markdown(f"**Current archive:** [{current_source}]({current_archive})")
            else:
                st.caption("No archive URL yet")

        st.markdown("**Enter archive URL manually:**")
        new_archive_url = st.text_input(
            "Archive URL",
            placeholder="https://web.archive.org/web/.../... or https://archive.ph/...",
            key=f"{key_prefix}_url",
        )
        source = "wayback" if "web.archive.org" in new_archive_url else (
                 "archive.ph" if "archive.ph" in new_archive_url or "archive.today" in new_archive_url
                 else "manual")

        new_category = st.selectbox(
            "Category (optional)",
            CATEGORIES,
            index=CATEGORIES.index(str(selected_row.get("category","") or "")) if str(selected_row.get("category","") or "") in CATEGORIES else 0,
            key=f"{key_prefix}_cat",
        )

        if st.button("💾 Save update", key=f"{key_prefix}_save", use_container_width=True):
            if not new_archive_url.strip():
                st.warning("Please enter an archive URL.")
            else:
                if "pending_updates" not in st.session_state:
                    st.session_state["pending_updates"] = {}
                st.session_state["pending_updates"][jid] = {
                    "archive_url":    new_archive_url.strip(),
                    "archive_source": source,
                    "archive_status": "success",
                    "category":       new_category,
                }
                st.success(f"Saved! Download the updated CSV below.")

    with tab_missing:
        render_update_form(needs_archive, "missing")
    with tab_all:
        render_update_form(details_df, "all")

st.divider()

# ── Section 2: Add a new job entry manually ───────────────────────────────────
st.markdown("### Add a new job manually")
st.caption("For jobs that exist in nyc_jobs.csv or remote_jobs.csv but aren't in job_details.csv yet")

# Jobs in the CSVs but not yet in details
details_ids = set(details_df["id"].astype(str)) if not details_df.empty else set()
untracked = all_jobs_df[~all_jobs_df["id"].astype(str).isin(details_ids)] if not all_jobs_df.empty else pd.DataFrame()

if untracked.empty:
    st.info("All jobs from nyc_jobs.csv and remote_jobs.csv are already in job_details.csv.")
else:
    st.caption(f"{len(untracked):,} jobs not yet in job_details.csv")

    search2 = st.text_input("Search", key="new_search")
    df2 = untracked.copy()
    if search2.strip():
        df2 = df2[
            df2["company_name"].str.contains(search2, case=False, na=False) |
            df2["title"].str.contains(search2, case=False, na=False)
        ]

    if df2.empty:
        st.info("No matches.")
    else:
        options2 = [f"{r['company_name']} — {r['title']}" for _, r in df2.iterrows()]
        sel2     = st.selectbox("Select job", options2, key="new_select")
        sel_row  = df2.iloc[options2.index(sel2)]

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Company:** {sel_row['company_name']}")
            st.markdown(f"**Title:** {sel_row['title']}")
            st.markdown(f"**Season:** {sel_row.get('recruiting_season','')}")
            if sel_row.get("url"):
                st.markdown(f"[🔗 Original posting]({sel_row['url']})")
        with col2:
            new_arc_url2 = st.text_input(
                "Archive URL",
                placeholder="https://web.archive.org/web/... or https://archive.ph/...",
                key="new_arc_url",
            )
            new_cat2 = st.selectbox("Category", CATEGORIES, key="new_cat")

        if st.button("➕ Add to job_details", use_container_width=True, key="new_save"):
            if not new_arc_url2.strip():
                st.warning("Please enter an archive URL.")
            else:
                src2 = "wayback" if "web.archive.org" in new_arc_url2 else (
                       "archive.ph" if "archive.ph" in new_arc_url2 or "archive.today" in new_arc_url2
                       else "manual")
                new_entry = {
                    "id":             str(sel_row["id"]),
                    "company_name":   sel_row["company_name"],
                    "title":          sel_row["title"],
                    "job_url":        sel_row.get("url",""),
                    "archive_url":    new_arc_url2.strip(),
                    "archive_source": src2,
                    "archive_status": "success",
                    "scrape_status":  "manual",
                    "category":       new_cat2,
                    "date_archived":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                if "new_entries" not in st.session_state:
                    st.session_state["new_entries"] = []
                # Avoid duplicates
                existing_new_ids = {e["id"] for e in st.session_state["new_entries"]}
                if new_entry["id"] in existing_new_ids:
                    st.warning("Already queued — download the CSV below.")
                else:
                    st.session_state["new_entries"].append(new_entry)
                    st.success("Queued! Download the updated CSV below.")

st.divider()

# ── Download updated job_details.csv ─────────────────────────────────────────
pending_updates = st.session_state.get("pending_updates", {})
new_entries     = st.session_state.get("new_entries", [])
n_updates = len(pending_updates)
n_new     = len(new_entries)

if n_updates > 0 or n_new > 0:
    st.markdown(f"### Download updated job_details.csv")
    st.caption(f"{n_updates} updates · {n_new} new entries pending")

    # Apply updates to existing data
    updated_df = details_df.copy() if not details_df.empty else pd.DataFrame(columns=DETAILS_HEADERS)
    for jid, changes in pending_updates.items():
        mask = updated_df["id"].astype(str) == jid
        for col, val in changes.items():
            if col in updated_df.columns:
                updated_df.loc[mask, col] = val

    # Append new entries
    if new_entries:
        new_df = pd.DataFrame(new_entries, columns=DETAILS_HEADERS)
        updated_df = pd.concat([updated_df, new_df], ignore_index=True)

    # Ensure all columns present
    for col in DETAILS_HEADERS:
        if col not in updated_df.columns:
            updated_df[col] = ""

    st.download_button(
        "⬇ Download updated job_details.csv",
        data=updated_df[DETAILS_HEADERS].to_csv(index=False),
        file_name="job_details.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if st.button("🗑️ Clear pending changes"):
        st.session_state["pending_updates"] = {}
        st.session_state["new_entries"]     = []
        st.rerun()

    st.info(
        "Replace `data/job_details.csv` in your repo with the downloaded file and push. "
        "The dashboard will reflect changes on the next data refresh."
    )
else:
    st.caption("No pending changes — make updates above to generate a download.")