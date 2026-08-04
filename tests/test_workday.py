from datetime import date

from job_search.sources.workday import WorkdayClient, _parse_relative_posted_date, _strip_html


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakeSession:
    def __init__(self, search_response, detail_responses=None, detail_error_paths=None):
        self.search_response = search_response
        self.detail_responses = detail_responses or {}
        self.detail_error_paths = detail_error_paths or set()
        self.posted_urls = []
        self.get_urls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posted_urls.append((url, json))
        return FakeResponse(self.search_response)

    def get(self, url, headers=None, timeout=None):
        self.get_urls.append(url)
        for path, response in self.detail_responses.items():
            if url.endswith(path):
                return FakeResponse(response)
        return FakeResponse({"jobPostingInfo": {}})


SAMPLE_SEARCH_RESPONSE = {
    "total": 2,
    "jobPostings": [
        {
            "title": "Enterprise Architect",
            "externalPath": "/job/Edinburgh/Enterprise-Architect_R0001111",
            "locationsText": "Edinburgh, UK",
            "postedOn": "Posted 3 Days Ago",
            "bulletFields": ["R0001111"],
        },
        {
            "title": "Business Architect",
            "externalPath": "/job/London/Business-Architect_R0002222",
            "locationsText": "London, UK",
            "postedOn": "Posted Today",
            "bulletFields": ["R0002222"],
        },
    ],
}


def test_search_posts_correct_payload_and_url():
    session = FakeSession(SAMPLE_SEARCH_RESPONSE)
    client = WorkdayClient(tenant="abrdn", host="wd3", site="abrdn", company_name="abrdn")

    client.search("Enterprise Architect", session=session)

    assert len(session.posted_urls) == 1
    url, payload = session.posted_urls[0]
    assert url == "https://abrdn.wd3.myworkdayjobs.com/wday/cxs/abrdn/abrdn/jobs"
    assert payload["searchText"] == "Enterprise Architect"


def test_search_parses_job_postings_and_fetches_detail():
    detail_responses = {
        "R0001111": {"jobPostingInfo": {"jobDescription": "<p>Architecture <b>Governance</b> role.</p>"}},
        "R0002222": {"jobPostingInfo": {"jobDescription": "<p>Business Architecture responsibilities.</p>"}},
    }
    session = FakeSession(SAMPLE_SEARCH_RESPONSE, detail_responses=detail_responses)
    client = WorkdayClient(tenant="abrdn", host="wd3", site="abrdn", company_name="abrdn")

    postings = client.search("Architect", session=session)

    assert len(postings) == 2
    by_title = {p.title: p for p in postings}

    ea = by_title["Enterprise Architect"]
    assert ea.source == "workday"
    assert ea.source_id == "abrdn:R0001111"
    assert ea.company == "abrdn"
    assert ea.location == "Edinburgh, UK"
    assert "Architecture Governance role" in ea.description
    assert ea.url == "https://abrdn.wd3.myworkdayjobs.com/abrdn/job/Edinburgh/Enterprise-Architect_R0001111"
    assert ea.role_family == "Architect"

    ba = by_title["Business Architect"]
    assert "Business Architecture responsibilities" in ba.description


def test_search_uses_exact_start_date_when_available():
    detail_responses = {
        "R0001111": {"jobPostingInfo": {"jobDescription": "desc", "startDate": "2026-06-15T00:00:00.000Z"}},
    }
    session = FakeSession(
        {"jobPostings": [SAMPLE_SEARCH_RESPONSE["jobPostings"][0]]}, detail_responses=detail_responses
    )
    client = WorkdayClient(tenant="abrdn", host="wd3", site="abrdn", company_name="abrdn")

    postings = client.search("Enterprise Architect", session=session)
    assert postings[0].posted_date == "2026-06-15"


def test_search_falls_back_to_relative_date_when_no_exact_date():
    session = FakeSession(
        {"jobPostings": [SAMPLE_SEARCH_RESPONSE["jobPostings"][0]]},
        detail_responses={"R0001111": {"jobPostingInfo": {"jobDescription": "desc"}}},
    )
    client = WorkdayClient(tenant="abrdn", host="wd3", site="abrdn", company_name="abrdn")

    postings = client.search("Enterprise Architect", session=session)
    expected = (date.today() - __import__("datetime").timedelta(days=3)).isoformat()
    assert postings[0].posted_date == expected


def test_detail_fetch_failure_degrades_gracefully():
    import requests

    class RequestExceptionSession(FakeSession):
        def get(self, url, headers=None, timeout=None):
            raise requests.RequestException("network error")

    session = RequestExceptionSession(SAMPLE_SEARCH_RESPONSE)
    client = WorkdayClient(tenant="abrdn", host="wd3", site="abrdn", company_name="abrdn")
    postings = client.search("Enterprise Architect", session=session)

    assert len(postings) == 2
    assert all(p.description == "" for p in postings)


def test_parse_relative_posted_date():
    today = date(2026, 7, 9)
    assert _parse_relative_posted_date("Posted Today", today) == "2026-07-09"
    assert _parse_relative_posted_date("Posted Yesterday", today) == "2026-07-08"
    assert _parse_relative_posted_date("Posted 3 Days Ago", today) == "2026-07-06"
    assert _parse_relative_posted_date("Posted 30+ Days Ago", today) == "2026-06-09"
    assert _parse_relative_posted_date("", today) == "2026-07-09"


def test_strip_html_removes_tags_and_unescapes_entities():
    assert _strip_html("<p>Architecture &amp; Governance</p>") == "Architecture & Governance"
    assert _strip_html("<ul><li>One</li><li>Two</li></ul>") == "One Two"
    assert _strip_html("") == ""
    assert _strip_html(None) == ""
