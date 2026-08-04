"""Orchestrates a single run: fetch -> dedupe -> verify -> re-validate ->
score -> tag -> persist state -> render report."""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date
from typing import Callable, List, Optional, Set

import requests

from . import applications as applications_mod, config, cv_loader, dedupe as dedupe_mod, llm_analysis, report as report_mod, scoring, seniority, state as state_mod, tagging, verify
from .sources.base import JobPosting

DESCRIPTION_STORAGE_LIMIT = 3000
# Each named employer (Workday or otherwise) is its own source function, so
# this loop's work is sources x role_families -- with 15 sources x 27
# keywords, sequential fetching stretched a single run to 20+ minutes.
# Bounded parallelism keeps that from growing linearly as more employers
# are added in later phases.
FETCH_MAX_WORKERS = 10


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
    applications_path: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    gemini_model: str = llm_analysis.DEFAULT_MODEL,
    llm_client_factory=None,
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
    fetch_tasks = [(source_fn, role_family) for source_fn in sources for role_family in role_families]
    with ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as executor:
        future_to_task = {executor.submit(source_fn, role_family): (source_fn, role_family) for source_fn, role_family in fetch_tasks}
        for future in as_completed(future_to_task):
            source_fn, role_family = future_to_task[future]
            try:
                raw_postings.extend(future.result())
            except requests.RequestException as exc:
                fetch_errors.append(f"{getattr(source_fn, '__name__', source_fn)}({role_family}): {exc}")

    deduped = [p for p in dedupe_mod.dedupe(raw_postings) if _passes_filters(p)]
    verified, excluded = verify.verify_postings(
        deduped, max_days_old, verify_timeout, session=http_session, today=today
    )

    fresh_keys = {p.key for p in verified}
    revalidated = _revalidate_stored_jobs(
        persisted_state, fresh_keys, max_days_old, verify_timeout, http_session, today
    )
    # Re-validated postings are only checked against fresh ones by exact
    # source:id key, not by company+title, so the same role listed under a
    # different source id (e.g. re-posted at another Adzuna location) can
    # slip through as a near-duplicate. Dedupe the combined set again to
    # collapse those.
    verified = dedupe_mod.dedupe(verified + revalidated)

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

    applications_result = None
    llm_spend = None
    if applications_path is not None:
        applications_result, llm_spend = _sync_applications(
            applications_path, enriched, cvs, today_str, gemini_api_key, gemini_model, llm_client_factory
        )

    return {
        "skipped": False,
        "report_markdown": report_markdown,
        "report_path": report_path,
        "verified_count": len(verified),
        "excluded_count": len(excluded),
        "fetch_errors": fetch_errors,
        "enriched": enriched,
        "applications": applications_result,
        "llm_spend": llm_spend,
    }


def _sync_applications(
    applications_path: str,
    enriched: List[dict],
    cvs: dict,
    today_str: str,
    gemini_api_key: Optional[str],
    gemini_model: str,
    llm_client_factory,
):
    """Analyzes only postings the tracker hasn't seen before (see
    llm_analysis.analyze_many), then upserts everything non-Skip into
    data/applications.json -- new postings get default tracking fields,
    existing ones keep their stage/dates/notes untouched. Returns
    (applications_data, llm_spend_summary)."""
    eligible = [r for r in enriched if r["score"].decision != "Skip"]
    existing = applications_mod.load(applications_path)
    already_analyzed = set(existing["applications"].keys())
    llm_results = llm_analysis.analyze_many(
        eligible,
        cvs,
        already_analyzed_keys=already_analyzed,
        api_key=gemini_api_key,
        model=gemini_model,
        client_factory=llm_client_factory,
    )
    spend = llm_analysis.summarize_spend(llm_results)
    data = applications_mod.sync(applications_path, enriched, llm_results, today=today_str, llm_spend=spend)
    return data, spend


def _passes_filters(posting: JobPosting) -> bool:
    """Cheap, CV-independent pre-scoring filters: commute feasibility,
    excluded role types, and seniority stretch cap. Applied before the
    expensive HTTP verification pass (saves wasted link checks) and again
    when re-validating previously-stored jobs, so the accumulated backlog
    in state.json gets pruned over subsequent runs as old entries are
    re-evaluated against these newer criteria."""
    work_pattern = tagging.tag_work_pattern(posting.description)
    if not tagging.is_commutable(posting.location, work_pattern):
        return False
    if tagging.is_excluded_title(posting.title):
        return False
    gap = seniority.compute_gap(posting.title)
    if gap is not None and gap > config.MAX_ACCEPTABLE_SENIORITY_GAP:
        return False
    return True


def _revalidate_stored_jobs(persisted_state, fresh_keys, max_days_old, verify_timeout, http_session, today):
    """Re-checks previously-stored jobs not present in today's fresh
    fetch. Age and filter checks are cheap and done inline first, so only
    postings that could actually still qualify pay for an HTTP link
    check -- and those checks run on a thread pool, not sequentially.
    With a backlog in the thousands, a one-request-at-a-time loop here
    was the direct cause of a run taking 20+ minutes even after the
    fresh-fetch verification path was already parallelized."""
    candidates = []  # (key, posting) pairs still worth an HTTP link check
    for key in list(state_mod.all_job_keys(persisted_state)):
        if key in fresh_keys:
            continue
        record = persisted_state["jobs"][key]
        still_recent = verify.is_within_age_window(record.get("posted_date", ""), max_days_old, today=today)
        if not still_recent:
            state_mod.remove_job(persisted_state, key)
            continue
        posting = _deserialize_posting(key, record)
        if not _passes_filters(posting):
            state_mod.remove_job(persisted_state, key)
            continue
        candidates.append((key, posting))

    revalidated = []
    if candidates:
        with ThreadPoolExecutor(max_workers=verify.DEFAULT_MAX_WORKERS) as executor:
            future_to_item = {
                executor.submit(verify.link_resolves, posting.url, verify_timeout, http_session): (key, posting)
                for key, posting in candidates
            }
            for future in as_completed(future_to_item):
                key, posting = future_to_item[future]
                if future.result():
                    revalidated.append(posting)
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
