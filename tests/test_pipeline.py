import json
import os
from dataclasses import replace
from datetime import date

from job_search import pipeline
from job_search.sources.base import JobPosting

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeSession:
    """Resolves every URL as live unless explicitly listed as dead."""

    def __init__(self, dead_urls=None):
        self.dead_urls = dead_urls or set()

    def head(self, url, **kwargs):
        return FakeResponse(404 if url in self.dead_urls else 200)

    def get(self, url, **kwargs):
        return FakeResponse(404 if url in self.dead_urls else 200)


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return [JobPosting(**item) for item in json.load(f)]


def fixture_sources():
    def adzuna_search(keyword):
        return [replace(p, role_family=keyword) for p in _load_fixture("adzuna_sample.json")]

    def reed_search(keyword):
        return [replace(p, role_family=keyword) for p in _load_fixture("reed_sample.json")]

    return [adzuna_search, reed_search]


def test_pipeline_end_to_end(tmp_path):
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    (cv_dir / "architecture_governance.md").write_text(
        "Enterprise Architecture, Architecture Governance, Design Authority, "
        "Technology Strategy, Stakeholder Management, Banking experience."
    )

    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
    )

    assert result["skipped"] is False
    # Old Corp posting (2026-01-01) must be excluded by the age window;
    # the Barclays role appears twice (adzuna + reed) and should dedupe to one.
    assert result["verified_count"] == 3  # Barclays (deduped), Random Fintech, Deloitte
    assert os.path.exists(result["report_path"])
    with open(result["report_path"], encoding="utf-8") as f:
        assert "Barclays" in f.read()

    assert os.path.exists(state_path)
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    assert len(state["jobs"]) == 3
    assert state["runs"][-1]["status"] == "success"


def test_pipeline_skips_within_min_gap(tmp_path):
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    common_kwargs = dict(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
    )

    first = pipeline.run(today=date(2026, 7, 9), **common_kwargs)
    assert first["skipped"] is False

    second = pipeline.run(today=date(2026, 7, 10), **common_kwargs)
    assert second["skipped"] is True

    third = pipeline.run(today=date(2026, 7, 11), **common_kwargs)
    assert third["skipped"] is False

    forced = pipeline.run(today=date(2026, 7, 10), force=True, **common_kwargs)
    assert forced["skipped"] is False


def test_pipeline_revalidates_previously_seen_jobs(tmp_path):
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    def only_barclays(keyword):
        return [p for p in _load_fixture("adzuna_sample.json") if p.company == "Barclays"]

    first = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=[only_barclays],
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
    )
    assert first["verified_count"] == 1

    # Next run's fresh fetch returns nothing new; the previously seen
    # Barclays job should be re-validated (still resolves) and retained.
    def nothing(keyword):
        return []

    second = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=[nothing],
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 11),
        force=True,
    )
    assert second["verified_count"] == 1

    # Now simulate the link going dead -- it should be dropped from state.
    third = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=[nothing],
        role_families=["Enterprise Architect"],
        http_session=FakeSession(dead_urls={"https://www.adzuna.co.uk/"}),
        today=date(2026, 7, 13),
        force=True,
    )
    assert third["verified_count"] == 0


def test_pipeline_report_omits_skip_decisions_but_state_keeps_everything(tmp_path):
    """With a CV that doesn't match any of the fixture postings, every
    posting should score as 'Skip' -- state should still track all of them
    (for re-validation), but the report/issue body should show none, while
    still reporting the true total in its header stats."""
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    (cv_dir / "unrelated.md").write_text("Career history in retail management and logistics.")

    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
    )

    assert result["verified_count"] == 3
    assert all(r["score"].decision == "Skip" for r in result["enriched"])
    assert "Verified vacancies:** 3" in result["report_markdown"]
    assert "Shown below (Stretch/Apply/Priority Apply only, Skip omitted):** 0" in result["report_markdown"]

    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    assert len(state["jobs"]) == 3


def test_pipeline_wires_sponsor_registry_into_visa_tag(tmp_path):
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    (cv_dir / "architecture_governance.md").write_text(
        "Enterprise Architecture, Architecture Governance, Design Authority, "
        "Technology Strategy, Stakeholder Management, Banking experience."
    )
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
        sponsor_names_fetcher=lambda: {"barclays bank"},
    )

    by_company = {r["posting"].company: r["visa"] for r in result["enriched"]}
    assert by_company["Barclays"] == "Registered Sponsor"
    assert by_company["Deloitte"] == "Not Registered"


def test_pipeline_degrades_gracefully_when_sponsor_fetch_fails(tmp_path):
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    def failing_fetcher():
        raise RuntimeError("gov.uk page structure changed")

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
        sponsor_names_fetcher=failing_fetcher,
    )

    assert result["skipped"] is False
    assert any("sponsor register fetch failed" in e for e in result["fetch_errors"])
    assert all(r["visa"].startswith("Unknown (registry unavailable") for r in result["enriched"])


def test_pipeline_dedupes_revalidated_jobs_against_fresh_fetch(tmp_path):
    """Reproduces the real duplicate seen in production: the same role at
    the same company posted under two different Adzuna listing ids (e.g.
    re-posted at a different office location). One id shows up in today's
    fresh fetch; the other only survives via state re-validation from a
    prior run. They should still collapse to a single report row."""
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    def make_amex_posting(source_id, location, posted_date):
        return JobPosting(
            source="adzuna",
            source_id=source_id,
            title="Director - Enterprise Business Architecture",
            company="American Express",
            location=location,
            description="Enterprise Business Architecture leadership role.",
            url=f"https://www.adzuna.co.uk/jobs/details/{source_id}",
            posted_date=posted_date,
        )

    def day1_sources():
        def adzuna_search(keyword):
            return [make_amex_posting("amex-1", "Burgess Hill", "2026-07-02")]

        return [adzuna_search]

    def day2_sources():
        def adzuna_search(keyword):
            # amex-1 has dropped out of today's search results, but a new
            # listing id for the same role at a different location shows up.
            return [make_amex_posting("amex-2", "London", "2026-07-05")]

        return [adzuna_search]

    first = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=day1_sources(),
        role_families=["Director of Architecture"],
        http_session=FakeSession(),
        today=date(2026, 7, 2),
    )
    assert first["verified_count"] == 1

    second = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=day2_sources(),
        role_families=["Director of Architecture"],
        http_session=FakeSession(),
        today=date(2026, 7, 5),
        force=True,
    )

    assert second["verified_count"] == 1  # collapsed, not 2
    assert len({r["posting"].company for r in second["enriched"]}) == 1
