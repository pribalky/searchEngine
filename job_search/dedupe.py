from dataclasses import replace
from typing import List

from .sources.base import JobPosting


def dedupe(postings: List[JobPosting]) -> List[JobPosting]:
    """Collapse postings that represent the same role at the same company,
    even if returned by multiple sources. Keeps the earliest posted_date and
    the fuller description among duplicates."""
    best = {}
    for posting in postings:
        key = posting.dedupe_key
        existing = best.get(key)
        if existing is None:
            best[key] = posting
            continue

        earliest_date = _earliest(existing.posted_date, posting.posted_date)
        fuller = posting if len(posting.description) > len(existing.description) else existing
        best[key] = replace(fuller, posted_date=earliest_date)

    return list(best.values())


def _earliest(date_a: str, date_b: str) -> str:
    if date_a and date_b:
        return min(date_a, date_b)
    return date_a or date_b
