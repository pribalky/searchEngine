from datetime import date

from job_search.verify import is_within_age_window, link_resolves, verify_postings
from job_search.sources.base import JobPosting


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeSession:
    def __init__(self, status_by_url):
        self.status_by_url = status_by_url

    def head(self, url, **kwargs):
        return FakeResponse(self.status_by_url.get(url, 404))

    def get(self, url, **kwargs):
        return FakeResponse(self.status_by_url.get(url, 404))


def test_is_within_age_window():
    today = date(2026, 7, 9)
    assert is_within_age_window("2026-07-01", 45, today=today) is True
    assert is_within_age_window("2026-01-01", 45, today=today) is False
    assert is_within_age_window("", 45, today=today) is False
    assert is_within_age_window("2026-07-10", 45, today=today) is False  # future date


def test_link_resolves_true_and_false():
    session = FakeSession({"https://good.example/job": 200, "https://dead.example/job": 404})
    assert link_resolves("https://good.example/job", timeout=5, session=session) is True
    assert link_resolves("https://dead.example/job", timeout=5, session=session) is False
    assert link_resolves("", timeout=5, session=session) is False


def test_verify_postings_excludes_old_and_dead():
    today = date(2026, 7, 9)
    postings = [
        JobPosting(
            source="adzuna", source_id="1", title="A", company="Barclays", location="London",
            description="d", url="https://good.example/1", posted_date="2026-07-01",
        ),
        JobPosting(
            source="adzuna", source_id="2", title="B", company="Old Corp", location="London",
            description="d", url="https://good.example/2", posted_date="2026-01-01",
        ),
        JobPosting(
            source="adzuna", source_id="3", title="C", company="Dead Co", location="London",
            description="d", url="https://dead.example/3", posted_date="2026-07-01",
        ),
    ]
    session = FakeSession({"https://good.example/1": 200, "https://good.example/2": 200, "https://dead.example/3": 404})
    verified, excluded = verify_postings(postings, max_days_old=45, timeout=5, session=session, today=today)

    assert [p.source_id for p in verified] == ["1"]
    assert {p.source_id for p, _ in excluded} == {"2", "3"}


def test_verify_postings_concurrent_verification_is_correct():
    """Link resolution runs on a thread pool -- verify it still produces
    the right verified/excluded split with many postings in flight at once."""
    today = date(2026, 7, 9)
    good_urls = {f"https://good.example/{i}": 200 for i in range(30)}
    dead_urls = {f"https://dead.example/{i}": 404 for i in range(20)}
    session = FakeSession({**good_urls, **dead_urls})

    postings = [
        JobPosting(
            source="adzuna", source_id=f"good-{i}", title="T", company="C", location="L",
            description="d", url=f"https://good.example/{i}", posted_date="2026-07-01",
        )
        for i in range(30)
    ] + [
        JobPosting(
            source="adzuna", source_id=f"dead-{i}", title="T", company="C", location="L",
            description="d", url=f"https://dead.example/{i}", posted_date="2026-07-01",
        )
        for i in range(20)
    ]

    verified, excluded = verify_postings(postings, max_days_old=45, timeout=5, session=session, today=today)

    assert {p.source_id for p in verified} == {f"good-{i}" for i in range(30)}
    assert {p.source_id for p, _ in excluded} == {f"dead-{i}" for i in range(20)}
