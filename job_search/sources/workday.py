"""Generic adapter for employers whose careers site runs on Workday
(myworkdayjobs.com) -- confirmed for Barclays, abrdn, and Baillie
Gifford by inspecting their public career site URLs. Workday's own
search UI calls a consistent, unauthenticated JSON API (the "CXS" --
Career Site -- endpoint), so this queries that directly instead of
scraping rendered HTML.

Could NOT be tested against the live API from within this sandbox --
outbound requests to myworkdayjobs.com are blocked by this environment's
network policy (the same restriction that affected Adzuna/Reed/gov.uk
earlier in this project). Built against Workday's well-documented,
widely-used CXS request/response shape; needs a real GitHub Actions run
to confirm the exact field names (particularly the detail endpoint's
description/date fields) match what's assumed here.

Unlike Adzuna/Reed, Workday's job-list endpoint only returns title,
location, and a coarse relative posted-date string -- no description.
Since scoring now weights demonstrated-responsibility text far more than
title text, a per-job detail fetch (also JSON) is required to get real
description text; otherwise every Workday-sourced posting would score
near zero regardless of actual fit."""
import html as html_module
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import List, Optional

import requests

from .base import JobPosting

_TAG_RE = re.compile(r"<[^>]+>")
_RELATIVE_DAYS_RE = re.compile(r"(\d+)\+?\s*day", re.IGNORECASE)
DEFAULT_DETAIL_FETCH_WORKERS = 10


def _strip_html(raw_html: str) -> str:
    text = _TAG_RE.sub(" ", raw_html or "")
    return html_module.unescape(" ".join(text.split()))


def _parse_relative_posted_date(posted_on: str, today: date) -> str:
    """Workday buckets old postings as "Posted 30+ Days Ago" -- treated
    here as exactly 30 days old, which understates true age for postings
    older than that. _fetch_detail tries to get an exact date from the
    per-job detail response first; this is only the fallback."""
    text = (posted_on or "").lower()
    if "today" in text:
        return today.isoformat()
    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()
    match = _RELATIVE_DAYS_RE.search(text)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    return today.isoformat()


class WorkdayClient:
    def __init__(self, tenant: str, host: str, site: str, company_name: str, timeout: int = 15):
        self.tenant = tenant
        self.host = host
        self.site = site
        self.company_name = company_name
        self.timeout = timeout
        self.base_url = f"https://{tenant}.{host}.myworkdayjobs.com/{site}"
        self.search_url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        self._headers = {"Content-Type": "application/json", "Accept": "application/json"}

    def search(self, keyword: str, limit: int = 20, session: Optional[requests.Session] = None) -> List[JobPosting]:
        http = session or requests
        resp = http.post(
            self.search_url,
            json={"appliedFacets": {}, "limit": limit, "offset": 0, "searchText": keyword},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        job_postings = resp.json().get("jobPostings", [])

        postings: List[JobPosting] = []
        if not job_postings:
            return postings

        with ThreadPoolExecutor(max_workers=DEFAULT_DETAIL_FETCH_WORKERS) as executor:
            future_to_jp = {
                executor.submit(self._fetch_detail, jp.get("externalPath", ""), http): jp for jp in job_postings
            }
            for future in as_completed(future_to_jp):
                jp = future_to_jp[future]
                description, exact_date = future.result()
                postings.append(self._to_job_posting(jp, keyword, description, exact_date))
        return postings

    def _fetch_detail(self, external_path: str, http) -> tuple:
        """Returns (description_text, iso_date_or_none). Both are
        best-effort -- an unreachable/unexpected detail response degrades
        to an empty description and no exact date rather than failing
        the whole search."""
        if not external_path:
            return "", None
        detail_url = f"https://{self.tenant}.{self.host}.myworkdayjobs.com/wday/cxs/{self.tenant}/{self.site}{external_path}"
        try:
            resp = http.get(detail_url, headers=self._headers, timeout=self.timeout)
            resp.raise_for_status()
            info = resp.json().get("jobPostingInfo", {})
        except (requests.RequestException, ValueError):
            return "", None

        description = _strip_html(info.get("jobDescription", ""))
        exact_date = None
        start_date = info.get("startDate")
        if start_date:
            try:
                exact_date = start_date[:10]  # Workday dates are typically ISO-prefixed
            except (TypeError, IndexError):
                exact_date = None
        return description, exact_date

    def _to_job_posting(self, jp: dict, keyword: str, description: str, exact_date: Optional[str]) -> JobPosting:
        external_path = jp.get("externalPath", "")
        req_id = next(
            (b for b in jp.get("bulletFields", []) if isinstance(b, str) and b),
            external_path,
        )
        posted_date = exact_date or _parse_relative_posted_date(jp.get("postedOn", ""), today=date.today())
        return JobPosting(
            source="workday",
            source_id=f"{self.tenant}:{req_id}",
            title=(jp.get("title") or "").strip(),
            company=self.company_name,
            location=(jp.get("locationsText") or "").strip(),
            description=description,
            url=f"{self.base_url}{external_path}",
            posted_date=posted_date,
            role_family=keyword,
        )
