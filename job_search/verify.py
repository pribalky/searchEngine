"""Real (non-LLM) verification that a vacancy is live: posted-date window
check plus an HTTP request confirming the application link resolves."""
from datetime import date, datetime, timedelta
from typing import List, Tuple

import requests

from .sources.base import JobPosting


def is_within_age_window(posted_date: str, max_days_old: int, today: date = None) -> bool:
    if not posted_date:
        return False
    today = today or date.today()
    try:
        posted = datetime.strptime(posted_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (today - posted) <= timedelta(days=max_days_old) and posted <= today


def link_resolves(url: str, timeout: int, session: requests.Session = None) -> bool:
    if not url:
        return False
    http = session or requests
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobSearchVerifier/1.0)"}
    try:
        resp = http.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if resp.status_code >= 400:
            resp = http.get(url, timeout=timeout, allow_redirects=True, headers=headers)
        return resp.status_code < 400
    except requests.RequestException:
        try:
            resp = http.get(url, timeout=timeout, allow_redirects=True, headers=headers)
            return resp.status_code < 400
        except requests.RequestException:
            return False


def verify_postings(
    postings: List[JobPosting],
    max_days_old: int,
    timeout: int,
    session: requests.Session = None,
    today: date = None,
) -> Tuple[List[JobPosting], List[Tuple[JobPosting, str]]]:
    """Returns (verified, excluded) where excluded is a list of
    (posting, reason) pairs so the caller/report can be transparent about
    what was dropped and why."""
    verified = []
    excluded = []
    for posting in postings:
        if not is_within_age_window(posting.posted_date, max_days_old, today=today):
            excluded.append((posting, "posted date outside verification window or missing"))
            continue
        if not link_resolves(posting.url, timeout, session=session):
            excluded.append((posting, "application link did not resolve"))
            continue
        verified.append(posting)
    return verified, excluded
