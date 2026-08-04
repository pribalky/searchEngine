"""Tracks user-facing application state (data/applications.json): scored
postings the pipeline surfaces, enriched with LLM analysis (see
llm_analysis.py) and merged with user-owned tracking fields (stage,
per-stage dates, notes) that must survive across runs.

Two families of fields per record:
 - pipeline-owned: everything derived from scoring/LLM analysis -- always
   overwritten on each run so the tracker reflects the latest posting data.
 - user-owned: stage, per-stage dates, notes -- set from the Streamlit
   tracker (see app/tracker.py), never overwritten by a pipeline run except
   to backfill defaults on a brand-new record.
"""
import json
import os
from datetime import date
from typing import Dict, List, Optional

STAGES = ["Not Applied", "Applied", "Shortlisted", "Interview", "Followup", "Offer", "Rejected", "Withdrawn"]

# Maps a stage to the record field that gets stamped with today's date the
# first time a record reaches that stage. "Not Applied" has no date field.
STAGE_DATE_FIELDS = {
    "Applied": "applied_date",
    "Shortlisted": "shortlisted_date",
    "Interview": "interview_date",
    "Followup": "followup_date",
    "Offer": "offer_date",
    "Rejected": "rejected_date",
    "Withdrawn": "withdrawn_date",
}

# Stages excluded from priority ranking -- no point ranking a role you've
# already been rejected from or withdrawn against active candidates.
INACTIVE_STAGES = {"Rejected", "Withdrawn"}

DEFAULT_STATE = {"schema_version": 1, "applications": {}}


def load(path: str) -> dict:
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_STATE))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("applications", {})
    return data


def save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _pipeline_fields(record: dict, llm_result: Optional[dict], today: str) -> dict:
    posting = record["posting"]
    score = record["score"]
    fields = {
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "url": posting.url,
        "posted_date": posting.posted_date,
        "source": posting.source,
        "role_family": posting.role_family,
        "overall_fit": score.overall_fit,
        "ats_match": score.ats_match,
        "recruiter_match": score.recruiter_match,
        "hiring_manager_match": score.hiring_manager_match,
        "semantic_match": score.semantic_match,
        "interview_probability": score.interview_probability,
        "decision": score.decision,
        "career_stretch_level": score.career_stretch_level,
        "rule_based_cv": score.best_cv,
        "days_left": record.get("days_left"),
        "last_updated": today,
    }
    if llm_result is not None:
        fields.update(
            {
                "llm_cv_match_gap": llm_result.get("cv_match_gap"),
                "llm_recruiter_pass_pct": llm_result.get("recruiter_pass_pct"),
                "llm_hiring_manager_pass_pct": llm_result.get("hiring_manager_pass_pct"),
                "llm_worth_applying": llm_result.get("worth_applying"),
                "llm_worth_applying_reason": llm_result.get("worth_applying_reason"),
                "llm_cv_to_use": llm_result.get("cv_to_use"),
                "llm_recommendation": llm_result.get("recommendation"),
                "llm_analyzed_at": today,
                "llm_error": llm_result.get("error"),
            }
        )
    return fields


def _default_user_fields(today: str) -> dict:
    fields = {"stage": "Not Applied", "notes": "", "first_seen": today}
    for date_field in STAGE_DATE_FIELDS.values():
        fields[date_field] = None
    return fields


def sync(
    path: str,
    enriched: List[dict],
    llm_results: Dict[str, dict],
    today: Optional[str] = None,
    llm_spend: Optional[dict] = None,
) -> dict:
    """Upserts scored postings into the tracker. Pipeline-derived fields
    are always refreshed from this run's scoring/LLM output; stage,
    per-stage dates, and notes are preserved for existing records and only
    defaulted on brand-new ones. Only non-"Skip" postings are tracked, same
    bar as the report. Records already in the tracker but absent from this
    run's `enriched` (e.g. a listing aged out) are left untouched -- the
    tracker is an append/update log, not pruned in lockstep with
    seen_jobs.json, so application history survives a listing's expiry.

    `llm_spend` (see llm_analysis.summarize_spend), when given, is appended
    to `llm_spend_log` -- a per-run history alongside the data it was spent
    analyzing, mirroring state.py's `runs` log."""
    today = today or date.today().isoformat()
    data = load(path)
    apps = data["applications"]

    eligible = [r for r in enriched if r["score"].decision != "Skip"]
    for record in eligible:
        key = record["posting"].key
        llm_result = llm_results.get(key)
        pipeline_fields = _pipeline_fields(record, llm_result, today)
        if key in apps:
            apps[key].update(pipeline_fields)
        else:
            apps[key] = {**_default_user_fields(today), **pipeline_fields}

    _recompute_priority(apps)
    data["applications"] = apps
    if llm_spend is not None:
        data.setdefault("llm_spend_log", []).append({"date": today, **llm_spend})
    save(path, data)
    return data


def _recompute_priority(apps: dict) -> None:
    active_keys = [k for k, v in apps.items() if v.get("stage") not in INACTIVE_STAGES]
    ranked = sorted(active_keys, key=lambda k: apps[k].get("interview_probability", 0), reverse=True)
    for record in apps.values():
        record["priority_score"] = record.get("interview_probability", 0)
        record["priority_rank"] = None
    for rank, key in enumerate(ranked, start=1):
        apps[key]["priority_rank"] = rank


def apply_stage_change(record: dict, new_stage: str, today: Optional[str] = None) -> dict:
    """Returns a copy of `record` with `stage` set to `new_stage`, stamping
    the matching stage-date field with today's date -- but only if that
    field isn't already set, so re-selecting a stage (or a stray click)
    can't overwrite the date a stage was first reached."""
    today = today or date.today().isoformat()
    updated = dict(record)
    updated["stage"] = new_stage
    date_field = STAGE_DATE_FIELDS.get(new_stage)
    if date_field and not updated.get(date_field):
        updated[date_field] = today
    return updated
