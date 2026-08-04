import json

from job_search import llm_analysis
from job_search.sources.base import JobPosting


class FakeUsage:
    def __init__(self, prompt_tokens=1000, output_tokens=200, total_tokens=1200):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = output_tokens
        self.total_token_count = total_tokens


class FakeResponse:
    def __init__(self, payload: dict, usage: FakeUsage = None):
        self.text = json.dumps(payload)
        self.usage_metadata = usage if usage is not None else FakeUsage()


class FakeModels:
    def __init__(self, payload: dict, usage: FakeUsage = None):
        self.payload = payload
        self.usage = usage
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return FakeResponse(self.payload, self.usage)


class FakeClient:
    def __init__(self, payload: dict, usage: FakeUsage = None):
        self.models = FakeModels(payload, usage)


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


def test_analyze_captures_token_usage():
    result = llm_analysis.analyze(
        "Enterprise Architect",
        "GoodCo",
        "Some JD",
        {"governance_cv": "CV text"},
        api_key="fake-key",
        client_factory=lambda: FakeClient(VALID_PAYLOAD, FakeUsage(1500, 300, 1800)),
    )
    assert result.prompt_tokens == 1500
    assert result.output_tokens == 300
    assert result.total_tokens == 1800


def test_analyze_error_results_carry_no_token_usage():
    result = llm_analysis.analyze("Enterprise Architect", "GoodCo", "Some JD", {}, api_key="fake-key")
    assert result.prompt_tokens is None
    assert result.output_tokens is None


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


def test_estimate_cost_usd_uses_configured_rates(monkeypatch):
    monkeypatch.setattr(llm_analysis, "INPUT_PRICE_PER_MTOK", 1.0)
    monkeypatch.setattr(llm_analysis, "OUTPUT_PRICE_PER_MTOK", 2.0)
    # 1,000,000 prompt tokens @ $1/MTok + 500,000 output tokens @ $2/MTok = $1 + $1
    assert llm_analysis.estimate_cost_usd(1_000_000, 500_000) == 2.0


def test_summarize_spend_aggregates_successes_and_errors():
    results = {
        "adzuna:1": {"prompt_tokens": 1000, "output_tokens": 200, "total_tokens": 1200, "error": None},
        "adzuna:2": {"prompt_tokens": 800, "output_tokens": 150, "total_tokens": 950, "error": None},
        "adzuna:3": {"prompt_tokens": None, "output_tokens": None, "total_tokens": None, "error": "boom"},
    }
    summary = llm_analysis.summarize_spend(results)
    assert summary["calls"] == 3
    assert summary["errors"] == 1
    assert summary["prompt_tokens"] == 1800
    assert summary["output_tokens"] == 350
    assert summary["total_tokens"] == 2150
    assert summary["estimated_cost_usd"] > 0


def test_summarize_spend_with_no_results():
    summary = llm_analysis.summarize_spend({})
    assert summary == {
        "calls": 0,
        "errors": 0,
        "prompt_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }
