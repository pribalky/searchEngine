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
from job_search import applications as applications_mod  # noqa: E402

DATA_PATH = os.path.join(REPO_ROOT, "data", "applications.json")
CONTENTS_PATH = "data/applications.json"
KEY_COLUMN = "_key"

# Order here is display order. Anything not listed (llm_error, first_seen,
# last_updated, priority_score, ...) stays in the underlying record but is
# never shown -- it's bookkeeping, not something to eyeball or edit.
DISPLAY_COLUMNS = [
    "priority_rank",
    "company",
    "title",
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


def _github_config():
    token = _secret("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = _secret("GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    return token, repo


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

    if not apps:
        st.info("No tracked applications yet -- run the job_search pipeline to populate this tracker.")
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
