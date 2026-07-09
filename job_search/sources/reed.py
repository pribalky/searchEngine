"""Reed Jobseeker API client (https://www.reed.co.uk/developers/jobseeker).

Endpoint: GET https://www.reed.co.uk/api/1.0/search
Auth: HTTP Basic Auth, API key as username, empty password.
"""
import requests

from .base import JobPosting

SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"


class ReedClient:
    def __init__(self, api_key: str, timeout: int = 15):
        if not api_key:
            raise ValueError("Reed api_key is required")
        self.api_key = api_key
        self.timeout = timeout

    def search(self, keyword: str, location: str = "UK", results_to_take: int = 50):
        params = {
            "keywords": keyword,
            "locationName": location,
            "resultsToTake": results_to_take,
        }
        resp = requests.get(
            SEARCH_URL,
            params=params,
            auth=(self.api_key, ""),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()

        postings = []
        for item in payload.get("results", []):
            postings.append(
                JobPosting(
                    source="reed",
                    source_id=str(item.get("jobId")),
                    title=(item.get("jobTitle") or "").strip(),
                    company=(item.get("employerName") or "").strip(),
                    location=(item.get("locationName") or "").strip(),
                    description=(item.get("jobDescription") or "").strip(),
                    url=item.get("jobUrl", ""),
                    posted_date=_normalise_date(item.get("date")),
                    salary_raw=_salary_raw(item),
                    role_family=keyword,
                )
            )
        return postings


def _normalise_date(date_str):
    # Reed returns dates like "09/07/2026"
    if not date_str or "/" not in date_str:
        return date_str or ""
    day, month, year = date_str.split("/")
    return f"{year}-{month}-{day}"


def _salary_raw(item: dict):
    lo = item.get("minimumSalary")
    hi = item.get("maximumSalary")
    if lo and hi:
        return f"{lo:.0f}-{hi:.0f}"
    return None
