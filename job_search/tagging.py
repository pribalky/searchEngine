import re
from datetime import date, datetime
from typing import Optional, Set

from . import config
from .sponsors import is_registered_sponsor

_EXCLUDED_TITLE_RE = re.compile(
    "|".join(rf"\b{re.escape(kw.lower())}\b" for kw in config.EXCLUDED_TITLE_KEYWORDS)
)


def tag_sector(company: str) -> str:
    company_lower = (company or "").lower()
    for name in config.BANKING_EMPLOYERS:
        if name.lower() in company_lower:
            return "Banking"
    for name in config.CONSULTING_EMPLOYERS:
        if name.lower() in company_lower:
            return "Consulting"
    return "Other"


def is_named_employer(company: str) -> bool:
    return tag_sector(company) in ("Banking", "Consulting")


def tag_role_categories(title: str, description: str):
    text = f"{title} {description}".lower()
    return [
        category
        for category, keywords in config.ROLE_CATEGORY_RULES.items()
        if any(kw in text for kw in keywords)
    ]


def tag_work_pattern(description: str) -> str:
    text = (description or "").lower()
    if any(p in text for p in config.HYBRID_PHRASES):
        return "Hybrid"
    if any(p in text for p in config.REMOTE_PHRASES):
        return "Remote"
    return "Unknown"


def tag_visa_sponsorship(company: str, description: str, sponsor_names: Optional[Set[str]] = None) -> str:
    """Primary signal is a real cross-check against the UK Home Office's
    published Register of Licensed Sponsors (see sponsors.py) -- a keyword
    guess against job description text is not a substitute for "known
    sponsor". Falls back to a clearly-labelled weak guess only when the
    registry couldn't be fetched this run."""
    if sponsor_names:
        return "Registered Sponsor" if is_registered_sponsor(company, sponsor_names) else "Not Registered"

    text = (description or "").lower()
    if any(p in text for p in config.VISA_NEGATIVE_PHRASES):
        return "Unknown (registry unavailable; JD says no sponsorship)"
    if any(p in text for p in config.VISA_POSITIVE_PHRASES):
        return "Unknown (registry unavailable; JD suggests sponsorship)"
    return "Unknown (registry unavailable)"


def is_commutable(location: str, work_pattern: str) -> bool:
    """Fully remote roles are location-agnostic. Everything else (Hybrid,
    Onsite, Unknown) still requires an in-person office presence, so it
    only counts if that office is actually reachable -- checked against
    config.ACCEPTABLE_LOCATIONS."""
    if work_pattern == "Remote":
        return True
    location_lower = (location or "").lower()
    return any(loc.lower() in location_lower for loc in config.ACCEPTABLE_LOCATIONS)


def is_excluded_title(title: str) -> bool:
    return bool(_EXCLUDED_TITLE_RE.search((title or "").lower()))


def compute_days_left(posted_date: str, max_days_old: int, today: Optional[date] = None) -> Optional[int]:
    """Days remaining before a posting ages out of the verification window
    (config.MAX_POSTING_AGE_DAYS) -- the closest proxy available to a real
    application deadline, since job boards don't expose one. Returns None
    if posted_date is missing/unparseable."""
    if not posted_date:
        return None
    today = today or date.today()
    try:
        posted = datetime.strptime(posted_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    days_since_posted = (today - posted).days
    return max_days_old - days_since_posted
