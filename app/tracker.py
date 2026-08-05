"""Application tracker UI. Reads/writes data/applications.json, which the
job_search pipeline auto-populates and re-prioritizes on every run (see
job_search/applications.py) -- this app only edits the user-owned columns:
Stage, and Notes.

Run locally:
    streamlit run app/tracker.py
Local runs with no GITHUB_TOKEN/GITHUB_REPOSITORY configured read/write
data/applications.json directly on disk.

Deployed (e.g. Streamlit Community Cloud): the filesystem is ephemeral, so
edits are committed back to the repo via the GitHub Contents API instead.
Set GITHUB_TOKEN (a fine-grained PAT scoped to this repo, Contents:
read/write only) and GITHUB_REPOSITORY (owner/repo) as app secrets --
see app/README.md.

Also supports manually adding a posting the pipeline missed (a URL to
fetch, or pasted JD text) -- requires GEMINI_API_KEY as an app secret (or
local env var) the same as the pipeline does.
"""
import base64
import json
import os
import sys
from datetime import date

import pandas as pd
import requests
import streamlit as st

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from job_search import applications as applications_mod, cv_loader, llm_analysis, manual_intake  # noqa: E402

DATA_PATH = os.path.join(REPO_ROOT, "data", "applications.json")
CONTENTS_PATH = "data/applications.json"
CV_DIR = os.path.join(REPO_ROOT, "cv")
KEY_COLUMN = "_key"

# Order here is display order. Anything not listed (llm_error, first_seen,
# last_updated, priority_score, ...) stays in the underlying record but is
# never shown -- it's bookkeeping, not something to eyeball or edit.
DISPLAY_COLUMNS = [
    "priority_rank",
    "company",
    "title",
    "source",
    "stage",
    "interview_probability",
    "llm_worth_applying",
    "llm_recruiter_pass_pct",
    "llm_hiring_manager_pass_pct",
    "llm_cv_to_use",
    "rule_based_cv",
    "career_stretch_level",
    "applied_date",
    "shortlisted_date",
    "interview_date",
    "followup_date",
    "llm_cv_match_gap",
    "llm_recommendation",
    "notes",
    "url",
]

EDITABLE_COLUMNS = {"stage", "notes"}

COLUMN_LABELS = {
    "priority_rank": "Priority",
    "company": "Company",
    "title": "Title",
    "source": "Source",
    "stage": "Stage",
    "interview_probability": "Interview Prob. %",
    "llm_worth_applying": "Worth Applying",
    "llm_recruiter_pass_pct": "Recruiter Pass %",
    "llm_hiring_manager_pass_pct": "HM Pass %",
    "llm_cv_to_use": "CV to Use",
    "rule_based_cv": "CV (rule-based)",
    "career_stretch_level": "Stretch",
    "applied_date": "Applied",
    "shortlisted_date": "Shortlisted",
    "interview_date": "Interview",
    "followup_date": "Followup",
    "llm_cv_match_gap": "CV Match / Gap",
    "llm_recommendation": "Edit Notes",
    "notes": "Notes",
    "url": "Link",
}


def _secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def _secret_or_env(name):
    return _secret(name) or os.environ.get(name)


def _github_config():
    return _secret_or_env("GITHUB_TOKEN"), _secret_or_env("GITHUB_REPOSITORY")


def _load_data():
    token, repo = _github_config()
    if token and repo:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/contents/{CONTENTS_PATH}",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if resp.status_code == 404:
            return applications_mod.load(DATA_PATH), None
        resp.raise_for_status()
        payload = resp.json()
        content = base64.b64decode(payload["content"]).decode("utf-8")
        data = json.loads(content)
        data.setdefault("applications", {})
        return data, payload["sha"]
    return applications_mod.load(DATA_PATH), None


def _save_data(data: dict, sha) -> None:
    token, repo = _github_config()
    body = json.dumps(data, indent=2, sort_keys=True)
    if token and repo:
        put_body = {
            "message": f"Update application tracker {date.today().isoformat()}",
            "content": base64.b64encode(body.encode("utf-8")).decode("utf-8"),
        }
        if sha:
            put_body["sha"] = sha
        resp = requests.put(
            f"https://api.github.com/repos/{repo}/contents/{CONTENTS_PATH}",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            json=put_body,
            timeout=15,
        )
        resp.raise_for_status()
    else:
        applications_mod.save(DATA_PATH, data)


def _to_dataframe(apps: dict) -> pd.DataFrame:
    rows = [{KEY_COLUMN: key, **record} for key, record in apps.items()]
    df = pd.DataFrame(rows)
    for col in DISPLAY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df.sort_values("priority_rank", na_position="last").reset_index(drop=True)


def _render_spend_summary(spend_log: list) -> None:
    """Cumulative Gemini spend across every run, sourced from the same
    llm_spend_log the pipeline appends to on each sync (see
    applications.sync) -- surfaced here so cost is visible without
    digging through GitHub Actions logs or the raw JSON file."""
    if not spend_log:
        return
    calls = sum(r.get("calls", 0) for r in spend_log)
    errors = sum(r.get("errors", 0) for r in spend_log)
    cost = sum(r.get("estimated_cost_usd", 0) for r in spend_log)
    cols = st.columns(4)
    cols[0].metric("Pipeline runs logged", len(spend_log))
    cols[1].metric("Gemini calls (total)", calls)
    cols[2].metric("Call errors (total)", errors)
    cols[3].metric("Est. spend (total)", f"${cost:.4f}")
    st.caption("Estimate only, placeholder pricing -- see .env.example. Per-run detail in data/applications.json's llm_spend_log.")


def _render_manual_add(data: dict, sha) -> None:
    """A posting the automated pipeline missed: fetch a URL, or paste the
    JD text directly, and it gets the same rule-based scoring plus one
    Gemini call (extraction + fit analysis) as everything else, then is
    force-included into the tracker regardless of how it scores -- a
    deliberate manual add shouldn't be silently dropped for scoring low,
    unlike auto-discovered postings (see manual_intake.py)."""
    with st.expander("+ Add a posting manually", expanded=False):
        st.caption("Fill in one of the two fields below, not both. The paste field is the fallback for pages a fetch can't read (JS-rendered, behind a login, etc).")
        url = st.text_input("Job posting URL", key="manual_url")
        jd_text = st.text_area("Or paste the job description text", key="manual_jd_text", height=150)

        if st.button("Add & Analyze"):
            cvs = cv_loader.load_cvs(CV_DIR)
            if not cvs:
                st.error("No CVs found in cv/ -- can't score a manual posting without at least one.")
                return
            if not url.strip() and not jd_text.strip():
                st.warning("Provide a URL or paste the job description text.")
                return

            api_key = _secret_or_env("GEMINI_API_KEY")
            model = _secret_or_env("GEMINI_MODEL") or llm_analysis.DEFAULT_MODEL
            with st.spinner("Fetching and analyzing..."):
                outcome = manual_intake.build_manual_record(cvs, url=url, jd_text=jd_text, api_key=api_key, model=model)

            if not outcome["ok"]:
                st.error(outcome["error"])
                return

            llm_results = {outcome["record"]["posting"].key: outcome["llm_result"]}
            spend = llm_analysis.summarize_spend(llm_results)
            applications_mod.upsert(data, [outcome["record"]], llm_results, llm_spend=spend, force_include=True)
            _save_data(data, sha)
            st.success(
                f"Added: {outcome['title']} @ {outcome['company']} -- {outcome['decision']} "
                f"({outcome['interview_probability']}% interview probability, Gemini says {outcome['worth_applying']})"
            )
            st.rerun()


def render() -> None:
    st.set_page_config(page_title="Job Application Tracker", layout="wide")
    st.title("Job Application Tracker")
    st.caption(
        "Priority, scores, and LLM analysis are auto-populated by the job_search pipeline. "
        "Edit Stage and Notes here, then Save -- everything else is read-only."
    )

    data, sha = _load_data()
    apps = data.get("applications", {})
    _render_spend_summary(data.get("llm_spend_log", []))
    _render_manual_add(data, sha)

    if not apps:
        st.info("No tracked applications yet -- run the job_search pipeline, or add one manually above.")
        return

    df = _to_dataframe(apps)
    keys = df[KEY_COLUMN].tolist()
    display_df = df[DISPLAY_COLUMNS].rename(columns=COLUMN_LABELS)

    edited = st.data_editor(
        display_df,
        column_config={
            COLUMN_LABELS["stage"]: st.column_config.SelectboxColumn(
                COLUMN_LABELS["stage"], options=applications_mod.STAGES, required=True
            ),
            COLUMN_LABELS["notes"]: st.column_config.TextColumn(COLUMN_LABELS["notes"]),
            COLUMN_LABELS["url"]: st.column_config.LinkColumn(COLUMN_LABELS["url"]),
        },
        disabled=[COLUMN_LABELS[c] for c in DISPLAY_COLUMNS if c not in EDITABLE_COLUMNS],
        hide_index=True,
        num_rows="fixed",
        use_container_width=True,
        key="tracker_editor",
    )

    if st.button("Save changes", type="primary"):
        today = date.today().isoformat()
        stage_col = COLUMN_LABELS["stage"]
        notes_col = COLUMN_LABELS["notes"]
        for pos, key in enumerate(keys):
            new_stage = edited.loc[pos, stage_col]
            new_notes = edited.loc[pos, notes_col]
            if new_stage != apps[key].get("stage"):
                apps[key] = applications_mod.apply_stage_change(apps[key], new_stage, today=today)
            apps[key]["notes"] = new_notes
        data["applications"] = apps
        _save_data(data, sha)
        st.success("Saved.")
        st.rerun()


render()
