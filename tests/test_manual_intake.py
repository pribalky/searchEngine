import json

import requests

from job_search import manual_intake


class FakeResponse:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload)

        class Usage:
            prompt_token_count = 900
            candidates_token_count = 180
            total_token_count = 1080

        self.usage_metadata = Usage()


class FakeModels:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return FakeResponse(self.payload)


class FakeClient:
    def __init__(self, payload: dict):
        self.models = FakeModels(payload)


VALID_EXTRACTION_PAYLOAD = {
    "extraction_ok": True,
    "extraction_note": "",
    "title": "Enterprise Architect",
    "company": "Barclays",
    "description_summary": "Own architecture governance and design authority for the retail bank.",
    "cv_match_gap": "Strong governance overlap; missing recent AI governance work.",
    "recruiter_pass_pct": 75,
    "hiring_manager_pass_pct": 68,
    "worth_applying": "Yes",
    "worth_applying_reason": "Clear architecture governance match at a named priority employer.",
    "cv_to_use": "governance_cv",
    "recommendation": "Add a bullet quantifying governance framework adoption.",
}

FAILED_EXTRACTION_PAYLOAD = {
    "extraction_ok": False,
    "extraction_note": "The page appears to require login and contains no visible job description.",
    "title": "",
    "company": "",
    "description_summary": "",
    "cv_match_gap": "",
    "recruiter_pass_pct": 0,
    "hiring_manager_pass_pct": 0,
    "worth_applying": "No",
    "worth_applying_reason": "",
    "cv_to_use": "",
    "recommendation": "",
}


class FakeHTTPResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeHTTPSession:
    def __init__(self, text=None, exc=None):
        self.text = text
        self.exc = exc

    def get(self, url, timeout=None, headers=None):
        if self.exc:
            raise self.exc
        return FakeHTTPResponse(self.text)


def test_fetch_page_text_strips_tags_and_scripts():
    html = """
    <html><head><script>var x = 1;</script><style>.a{color:red}</style></head>
    <body><nav>Home | About</nav><h1>Enterprise Architect</h1><p>Own governance.</p></body></html>
    """
    session = FakeHTTPSession(text=html)
    text = manual_intake.fetch_page_text("https://example.com/job", session=session)
    assert "<script>" not in text
    assert "var x = 1" not in text
    assert "color:red" not in text
    assert "Enterprise Architect" in text
    assert "Own governance." in text


def test_build_manual_record_requires_url_or_jd_text():
    result = manual_intake.build_manual_record({"cv": "text"}, url="", jd_text="")
    assert result["ok"] is False
    assert "Provide a URL" in result["error"]


def test_build_manual_record_reports_fetch_failure():
    session = FakeHTTPSession(exc=requests.ConnectionError("DNS failure"))
    result = manual_intake.build_manual_record(
        {"cv": "text"}, url="https://example.com/job", http_session=session, api_key="fake-key"
    )
    assert result["ok"] is False
    assert "Couldn't fetch that URL" in result["error"]
    assert "pasting the job description" in result["error"]


def test_build_manual_record_reports_thin_fetch_as_failure():
    session = FakeHTTPSession(text="short")
    result = manual_intake.build_manual_record(
        {"cv": "text"}, url="https://example.com/job", http_session=session, api_key="fake-key"
    )
    assert result["ok"] is False
    assert "little to no text" in result["error"]


def test_build_manual_record_reports_extraction_failure():
    result = manual_intake.build_manual_record(
        {"cv": "text"},
        jd_text="Please log in to view this posting.",
        api_key="fake-key",
        client_factory=lambda: FakeClient(FAILED_EXTRACTION_PAYLOAD),
    )
    assert result["ok"] is False
    assert "login" in result["error"]


def test_build_manual_record_success_path_via_pasted_jd():
    cvs = {"governance_cv": "Architecture governance and design authority experience."}
    result = manual_intake.build_manual_record(
        cvs,
        jd_text="Enterprise Architect at Barclays, own architecture governance...",
        api_key="fake-key",
        client_factory=lambda: FakeClient(VALID_EXTRACTION_PAYLOAD),
        today="2026-08-05",
    )
    assert result["ok"] is True
    assert result["title"] == "Enterprise Architect"
    assert result["company"] == "Barclays"
    assert result["worth_applying"] == "Yes"

    record = result["record"]
    posting = record["posting"]
    assert posting.source == "manual"
    assert posting.title == "Enterprise Architect"
    assert posting.company == "Barclays"
    assert posting.posted_date == "2026-08-05"
    assert posting.url == ""
    # Scored via the real rule-based scorer, not stubbed.
    assert record["score"].decision is not None
    assert record["days_left"] is None

    llm_result = result["llm_result"]
    assert llm_result["worth_applying"] == "Yes"
    assert llm_result["prompt_tokens"] == 900


def test_build_manual_record_success_path_via_url_reuses_same_key_on_resubmit():
    session = FakeHTTPSession(text="<html><body>" + "Job content. " * 50 + "</body></html>")
    cvs = {"governance_cv": "Architecture governance experience."}

    first = manual_intake.build_manual_record(
        cvs,
        url="https://example.com/jobs/enterprise-architect",
        http_session=session,
        api_key="fake-key",
        client_factory=lambda: FakeClient(VALID_EXTRACTION_PAYLOAD),
    )
    second = manual_intake.build_manual_record(
        cvs,
        url="https://example.com/jobs/enterprise-architect",
        http_session=session,
        api_key="fake-key",
        client_factory=lambda: FakeClient(VALID_EXTRACTION_PAYLOAD),
    )
    assert first["ok"] is True and second["ok"] is True
    assert first["record"]["posting"].key == second["record"]["posting"].key


def test_build_manual_record_prefers_url_over_jd_text_when_both_given():
    session = FakeHTTPSession(text="<html><body>" + "Fetched page content. " * 30 + "</body></html>")
    cvs = {"governance_cv": "Architecture governance experience."}

    client = FakeClient(VALID_EXTRACTION_PAYLOAD)

    result = manual_intake.build_manual_record(
        cvs,
        url="https://example.com/job",
        jd_text="this pasted text should be ignored since a URL was provided",
        http_session=session,
        api_key="fake-key",
        client_factory=lambda: client,
    )
    assert result["ok"] is True
    assert result["record"]["posting"].url == "https://example.com/job"
    sent_prompt = client.models.calls[0]["contents"]
    assert "Fetched page content." in sent_prompt
    assert "this pasted text should be ignored" not in sent_prompt
