from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobPosting:
    source: str  # "adzuna" | "reed" | "workday"
    source_id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    posted_date: str  # ISO 8601 date, e.g. "2026-07-01"
    salary_raw: Optional[str] = None
    role_family: Optional[str] = None  # the search query that surfaced this posting

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def dedupe_key(self) -> str:
        norm_title = "".join(ch.lower() for ch in self.title if ch.isalnum())
        norm_company = "".join(ch.lower() for ch in self.company if ch.isalnum())
        return f"{norm_company}|{norm_title}"
