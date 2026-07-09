"""Adzuna Job Search API client (https://developer.adzuna.com/).

Endpoint: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
Auth: app_id + app_key query params.
"""
import requests

from .base import JobPosting

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaClient:
    def __init__(self, app_id: str, app_key: str, country: str = "gb", timeout: int = 15):
        if not app_id or not app_key:
            raise ValueError("Adzuna app_id and app_key are required")
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.timeout = timeout

    def search(self, keyword: str, max_days_old: int, results_per_page: int = 50, page: int = 1):
        """Return a list of JobPosting for a single role-family keyword search."""
        url = BASE_URL.format(country=self.country, page=page)
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": keyword,
            "results_per_page": results_per_page,
            "max_days_old": max_days_old,
            "sort_by": "date",
            "content-type": "application/json",
        }
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()

        postings = []
        for item in payload.get("results", []):
            postings.append(
                JobPosting(
                    source="adzuna",
                    source_id=str(item.get("id")),
                    title=item.get("title", "").strip(),
                    company=(item.get("company") or {}).get("display_name", "").strip(),
                    location=(item.get("location") or {}).get("display_name", "").strip(),
                    description=item.get("description", "").strip(),
                    url=item.get("redirect_url", ""),
                    posted_date=(item.get("created") or "")[:10],
                    salary_raw=_salary_raw(item),
                    role_family=keyword,
                )
            )
        return postings


def _salary_raw(item: dict):
    lo = item.get("salary_min")
    hi = item.get("salary_max")
    if lo and hi:
        return f"{lo:.0f}-{hi:.0f}"
    return None
