import json

from job_search import llm_analysis
from job_search.sources.base import JobPosting


class FakeResponse:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload)


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


VALID_PAYLOAD = {
    "cv_match_gap": "Strong overlap on governance work; missing AI adoption experience.",
    "recruiter_pass_pct": 72,
    "hiring_manager_pass_pct": 65,
    "worth_applying": "Yes",
    "worth_applying_reason": "Clear architecture governance match.",
    "cv_to_use": "governance_cv",
    "recommendation": "Add a bullet on AI governance work under the most recent role.",
}


def test_analyze_returns_error_when_api_key_missing():
    result = llm_analysis.analyze(
        "Enterprise Architect", "GoodCo", "Some JD", {"governance_cv": "CV text"}, api_key=None
    )
    assert result.error == "GEMINI_API_KEY not set"
    assert result.worth_applying == ""


def test_analyze_returns_error_when_no_cvs():
    result = llm_analysis.analyze("Enterprise Architect", "GoodCo", "Some JD", {}, api_key="fake-key")
    assert result.error == "no CVs loaded"


def test_analyze_success_path_via_injected_client():
    result = llm_analysis.analyze(
        "Enterprise Architect",
        "GoodCo",
        "Some JD requiring architecture governance.",
        {"governance_cv": "CV text mentioning governance."},
        api_key="fake-key",
        client_factory=lambda: FakeClient(VALID_PAYLOAD),
    )
    assert result.error is None
    assert result.worth_applying == "Yes"
    assert result.recruiter_pass_pct == 72
    assert result.hiring_manager_pass_pct == 65
    assert result.cv_to_use == "governance_cv"
    assert "AI adoption" in result.cv_match_gap


def test_analyze_degrades_gracefully_on_malformed_response():
    class BrokenClient:
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                return FakeResponse({"unexpected": "shape"})

    result = llm_analysis.analyze(
        "Enterprise Architect",
        "GoodCo",
        "Some JD",
        {"governance_cv": "CV text"},
        api_key="fake-key",
        client_factory=lambda: BrokenClient(),
    )
    assert result.error is not None
    assert result.worth_applying == ""


def _posting(source_id):
    return JobPosting(
        source="adzuna",
        source_id=source_id,
        title="Enterprise Architect",
        company="GoodCo",
        location="Edinburgh, UK",
        description="Architecture governance role.",
        url=f"https://example.com/{source_id}",
        posted_date="2026-07-01",
    )


def test_analyze_many_skips_already_analyzed_keys():
    eligible = [{"posting": _posting("1")}, {"posting": _posting("2")}]
    results = llm_analysis.analyze_many(
        eligible,
        {"governance_cv": "CV text"},
        already_analyzed_keys={"adzuna:1"},
        api_key="fake-key",
        client_factory=lambda: FakeClient(VALID_PAYLOAD),
    )
    assert set(results.keys()) == {"adzuna:2"}
    assert results["adzuna:2"]["worth_applying"] == "Yes"
