"""Manual intake for postings the automated pipeline missed: paste a URL
or raw job-description text, and it goes through the same rule-based
scoring (scoring.py) as pipeline-discovered postings, plus one Gemini call
that extracts structured fields (title/company/description) and runs the
usual qualitative analysis in a single request (see
llm_analysis.extract_and_analyze).

Deliberately bypasses the automated pipeline's commute/title-exclusion/
seniority-cap filters (see pipeline._passes_filters) and the "Skip"
decision filter that applications.upsert() applies by default -- those
exist to cut noise out of hundreds of auto-discovered postings, but a
manually-added posting is already a deliberate choice by the user, not
something that needs filtering.

Does not touch data/applications.json directly. build_manual_record()
returns a scored, analyzed record for the caller to merge and persist
however is appropriate for that caller (a local file for CLI use, or the
GitHub Contents API for the Streamlit app's ephemeral-filesystem
deployment) -- see applications.upsert().
"""
import hashlib
import re
from dataclasses import asdict
from datetime import date
from typing import Dict, Optional

import requests

from . import llm_analysis, scoring
from .sources.base import JobPosting

FETCH_TIMEOUT_SECONDS = 15
# Career-site pages can carry a lot of navigation/footer/boilerplate text
# alongside the actual posting; capped mainly to bound Gemini token cost,
# not because the content past this point is expected to matter.
MAX_SOURCE_TEXT_CHARS = 20000
MIN_FETCHED_TEXT_CHARS = 200  # below this, treat the fetch as "found nothing useful"
USER_AGENT = "Mozilla/5.0 (compatible; job-search-tracker/1.0)"

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


def fetch_page_text(url: str, timeout: int = FETCH_TIMEOUT_SECONDS, session: Optional[requests.Session] = None) -> str:
    """Best-effort HTML-to-text: strips script/style blocks and tags, then
    collapses whitespace. No JS rendering -- pages that need it (common on
    some ATS platforms) will yield thin or empty text, which the caller
    treats as a fetch failure rather than silently scoring near-nothing."""
    session = session or requests
    resp = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    text = _SCRIPT_STYLE_RE.sub(" ", resp.text)
    text = _TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n", text)
    return text.strip()[:MAX_SOURCE_TEXT_CHARS]


def _manual_source_id(url: str, jd_text: str) -> str:
    """Hash of the URL (or, if no URL, the pasted text) as the source_id --
    re-submitting the same URL/text upserts the same tracker row instead
    of creating a duplicate, same dedup philosophy as the rest of the
    pipeline (see sources/base.py's JobPosting.key)."""
    basis = url.strip() if url.strip() else jd_text.strip()
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def build_manual_record(
    cvs: Dict[str, str],
    url: str = "",
    jd_text: str = "",
    api_key: Optional[str] = None,
    model: str = llm_analysis.DEFAULT_MODEL,
    client_factory=None,
    http_session: Optional[requests.Session] = None,
    today: Optional[str] = None,
) -> dict:
    """Resolves a URL or pasted JD text into one scored+analyzed tracker
    record. Returns on success:
        {"ok": True, "record": {"posting": JobPosting, "score": ScoreResult,
         "days_left": None}, "llm_result": {...asdict(ManualPostingResult)},
         "title": ..., "company": ..., "decision": ..., "interview_probability": ...,
         "worth_applying": ...}
    or on failure:
        {"ok": False, "error": "..."}
    Never raises. Exactly one of `url`/`jd_text` should be non-empty; if
    both are given, the URL is fetched and the pasted text is ignored (the
    paste field exists for when a fetch fails, not as a second source)."""
    url = (url or "").strip()
    jd_text = (jd_text or "").strip()
    if not url and not jd_text:
        return {"ok": False, "error": "Provide a URL or paste the job description text."}

    source_text = jd_text
    if url:
        try:
            source_text = fetch_page_text(url, session=http_session)
        except requests.RequestException as exc:
            return {
                "ok": False,
                "error": f"Couldn't fetch that URL ({exc}). Try pasting the job description text instead.",
            }
        if len(source_text) < MIN_FETCHED_TEXT_CHARS:
            return {
                "ok": False,
                "error": "Fetched the page but found little to no text -- it may be JS-rendered or behind a "
                "login. Try pasting the job description text instead.",
            }

    result = llm_analysis.extract_and_analyze(source_text, cvs, api_key=api_key, model=model, client_factory=client_factory)
    if result.error:
        return {"ok": False, "error": f"Gemini analysis failed: {result.error}"}
    if not result.extraction_ok:
        return {"ok": False, "error": result.extraction_note or "Couldn't find a job description in the provided text."}

    today = today or date.today().isoformat()
    posting = JobPosting(
        source="manual",
        source_id=_manual_source_id(url, jd_text),
        title=result.title,
        company=result.company,
        location="Unknown",
        description=result.description_summary,
        url=url,
        posted_date=today,
        role_family=None,
    )
    score = scoring.score_posting(posting.title, posting.description, cvs)
    record = {"posting": posting, "score": score, "days_left": None}

    return {
        "ok": True,
        "record": record,
        "llm_result": asdict(result),
        "title": posting.title,
        "company": posting.company,
        "decision": score.decision,
        "interview_probability": score.interview_probability,
        "worth_applying": result.worth_applying,
    }
