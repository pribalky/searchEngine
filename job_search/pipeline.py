"""Orchestrates a single run: fetch -> dedupe -> verify -> re-validate ->
score -> tag -> persist state -> render report."""
import os
from dataclasses import asdict
from datetime import date
from typing import Callable, List, Optional, Set

import requests

from . import config, cv_loader, dedupe as dedupe_mod, report as report_mod, scoring, state as state_mod, tagging, verify
from .sources.base import JobPosting

DESCRIPTION_STORAGE_LIMIT = 3000


def run(
    cv_dir: str,
    state_path: str,
    reports_dir: str,
    sources: List[Callable[[str], List[JobPosting]]],
    role_families: Optional[List[str]] = None,
    max_days_old: int = config.MAX_POSTING_AGE_DAYS,
    verify_timeout: int = config.VERIFY_TIMEOUT_SECONDS,
    http_session: Optional[requests.Session] = None,
    today: Optional[date] = None,
    force: bool = False,
    sponsor_names_fetcher: Optional[Callable[[], Set[str]]] = None,
) -> dict:
    today = today or date.today()
    today_str = today.isoformat()
    role_families = role_families or config.ROLE_FAMILIES

    persisted_state = state_mod.load(state_path)
    if not force:
        days_since = state_mod.days_since_last_run(persisted_state, today=today)
        if days_since is not None and days_since < config.MIN_DAYS_BETWEEN_RUNS:
            return {
                "skipped": True,
                "reason": f"last successful run was {days_since} day(s) ago; "
                f"minimum gap is {config.MIN_DAYS_BETWEEN_RUNS} day(s)",
            }

    cvs = cv_loader.load_cvs(cv_dir)

    fetch_errors: List[str] = []
    sponsor_names: Set[str] = set()
    if sponsor_names_fetcher is not None:
        try:
            sponsor_names = sponsor_names_fetcher()
        except Exception as exc:  # external data source; degrade to "Unknown" rather than crash the run
            fetch_errors.append(f"sponsor register fetch failed: {exc}")

    raw_postings: List[JobPosting] = []
    for source_fn in sources:
        for role_family in role_families:
            try:
                raw_postings.extend(source_fn(role_family))
            except requests.RequestException as exc:
                fetch_errors.append(f"{getattr(source_fn, '__name__', source_fn)}({role_family}): {exc}")

    deduped = dedupe_mod.dedupe(raw_postings)
    verified, excluded = verify.verify_postings(
        deduped, max_days_old, verify_timeout, session=http_session, today=today
    )

    fresh_keys = {p.key for p in verified}
    revalidated = _revalidate_stored_jobs(
        persisted_state, fresh_keys, max_days_old, verify_timeout, http_session, today
    )
    verified.extend(revalidated)

    enriched = [_enrich(p, cvs, sponsor_names, max_days_old, today) for p in verified]

    for record in enriched:
        posting = record["posting"]
        state_mod.upsert_job(persisted_state, posting.key, _serialize_posting(posting), today_str)

    state_mod.record_run(persisted_state, today_str, "success", len(verified))
    state_mod.save(state_path, persisted_state)

    # Skip-decision records are still scored and kept in state (so re-runs
    # keep tracking them and decisions can improve as CVs change), but they
    # add noise rather than interview opportunities, so they're left out of
    # the report itself. See config.py for why some generic role families
    # were removed rather than just relying on this filter alone.
    report_records = [r for r in enriched if r["score"].decision != "Skip"]
    report_markdown = report_mod.build_report(
        today_str, report_records, len(excluded), len(cvs), total_verified_count=len(enriched)
    )
    report_path = os.path.join(reports_dir, f"{today_str}.md")
    os.makedirs(reports_dir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_markdown)

    return {
        "skipped": False,
        "report_markdown": report_markdown,
        "report_path": report_path,
        "verified_count": len(verified),
        "excluded_count": len(excluded),
        "fetch_errors": fetch_errors,
        "enriched": enriched,
    }


def _revalidate_stored_jobs(persisted_state, fresh_keys, max_days_old, verify_timeout, http_session, today):
    revalidated = []
    for key in list(state_mod.all_job_keys(persisted_state)):
        if key in fresh_keys:
            continue
        record = persisted_state["jobs"][key]
        still_recent = verify.is_within_age_window(record.get("posted_date", ""), max_days_old, today=today)
        still_resolves = still_recent and verify.link_resolves(record.get("url", ""), verify_timeout, session=http_session)
        if still_resolves:
            revalidated.append(_deserialize_posting(key, record))
        else:
            state_mod.remove_job(persisted_state, key)
    return revalidated


def _enrich(posting: JobPosting, cvs, sponsor_names: Set[str], max_days_old: int, today: date) -> dict:
    score = scoring.score_posting(posting.title, posting.description, cvs)
    return {
        "posting": posting,
        "score": score,
        "sector": tagging.tag_sector(posting.company),
        "role_categories": tagging.tag_role_categories(posting.title, posting.description),
        "work_pattern": tagging.tag_work_pattern(posting.description),
        "visa": tagging.tag_visa_sponsorship(posting.company, posting.description, sponsor_names),
        "stretch": score.career_stretch_level,
        "days_left": tagging.compute_days_left(posting.posted_date, max_days_old, today),
    }


def _serialize_posting(posting: JobPosting) -> dict:
    data = asdict(posting)
    data["description"] = data["description"][:DESCRIPTION_STORAGE_LIMIT]
    return data


def _deserialize_posting(key: str, record: dict) -> JobPosting:
    source, source_id = key.split(":", 1)
    return JobPosting(
        source=record.get("source", source),
        source_id=record.get("source_id", source_id),
        title=record.get("title", ""),
        company=record.get("company", ""),
        location=record.get("location", ""),
        description=record.get("description", ""),
        url=record.get("url", ""),
        posted_date=record.get("posted_date", ""),
        salary_raw=record.get("salary_raw"),
        role_family=record.get("role_family"),
    )
