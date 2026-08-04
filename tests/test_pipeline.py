import json
import os
from dataclasses import replace
from datetime import date

from job_search import applications as applications_mod, pipeline
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
    # Old Corp posting is excluded (too old, non-commutable Manchester
    # location, and "Head of Architecture" exceeds the seniority gap cap
    # -- any one of these would drop it); the Barclays role appears twice
    # (adzuna + reed) and should dedupe to one.
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
            title="Business Architect",
            company="American Express",
            location=location,
            description="Enterprise Business Architecture leadership role.",
            url=f"https://www.adzuna.co.uk/jobs/details/{source_id}",
            posted_date=posted_date,
        )

    def day1_sources():
        def adzuna_search(keyword):
            return [make_amex_posting("amex-1", "Edinburgh", "2026-07-02")]

        return [adzuna_search]

    def day2_sources():
        def adzuna_search(keyword):
            # amex-1 has dropped out of today's search results, but a new
            # listing id for the same role at a different location shows up.
            return [make_amex_posting("amex-2", "Glasgow", "2026-07-05")]

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


def test_pipeline_excludes_non_commutable_excluded_title_and_major_stretch_postings(tmp_path):
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")

    def make(source_id, title, company, location, description=""):
        return JobPosting(
            source="adzuna", source_id=source_id, title=title, company=company,
            location=location, description=description,
            url=f"https://www.adzuna.co.uk/jobs/details/{source_id}", posted_date="2026-07-01",
        )

    def sources():
        def adzuna_search(keyword):
            return [
                make("1", "Enterprise Architect", "GoodCo", "Edinburgh, UK"),  # passes everything
                make("2", "Enterprise Architect", "LondonCo", "London, UK"),  # fails: not commutable
                make("3", "Security Architect", "SecCo", "Edinburgh, UK"),  # fails: excluded title
                make("4", "Head of Architecture", "BigCo", "Glasgow, Scotland"),  # fails: gap=3 > cap
            ]

        return [adzuna_search]

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
    )

    assert result["verified_count"] == 1
    assert result["enriched"][0]["posting"].company == "GoodCo"


def test_pipeline_prunes_previously_stored_jobs_that_fail_new_filters(tmp_path):
    """Simulates the backlog-cleanup case: a job already sitting in
    state.json from before these filters existed should get dropped on
    the next run's re-validation pass, not kept forever."""
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    state_path = tmp_path / "data" / "seen_jobs.json"
    reports_dir = str(tmp_path / "reports")
    state_path.parent.mkdir(parents=True)

    import json as json_mod

    preexisting_state = {
        "schema_version": 1,
        "runs": [{"date": "2026-07-01", "status": "success", "found": 1}],
        "jobs": {
            "adzuna:old-1": {
                "source": "adzuna",
                "source_id": "old-1",
                "title": "Security Architect",
                "company": "OldCo",
                "location": "Edinburgh, UK",
                "description": "",
                "url": "https://www.adzuna.co.uk/jobs/details/old-1",
                "posted_date": "2026-06-25",
                "salary_raw": None,
                "role_family": "Enterprise Architect",
                "first_seen": "2026-07-01",
                "last_verified": "2026-07-01",
            }
        },
    }
    state_path.write_text(json_mod.dumps(preexisting_state))

    def sources():
        def adzuna_search(keyword):
            return []

        return [adzuna_search]

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=str(state_path),
        reports_dir=reports_dir,
        sources=sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
        force=True,
    )

    assert result["verified_count"] == 0
    with open(state_path, encoding="utf-8") as f:
        state = json_mod.load(f)
    assert "adzuna:old-1" not in state["jobs"]


def test_pipeline_populates_application_tracker(tmp_path):
    """End-to-end: applications_path wiring should upsert non-Skip
    postings into the tracker, ranked by priority. No Gemini key is
    passed, so LLM fields degrade gracefully rather than making a real
    API call -- exercises the same resilience path as a user running
    without GEMINI_API_KEY set."""
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir()
    (cv_dir / "architecture_governance.md").write_text(
        "Enterprise Architecture, Architecture Governance, Design Authority, "
        "Technology Strategy, Stakeholder Management, Banking experience."
    )
    state_path = str(tmp_path / "data" / "seen_jobs.json")
    reports_dir = str(tmp_path / "reports")
    applications_path = str(tmp_path / "data" / "applications.json")

    result = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 9),
        applications_path=applications_path,
        gemini_api_key=None,
    )

    assert os.path.exists(applications_path)
    apps = result["applications"]["applications"]
    non_skip = [r for r in result["enriched"] if r["score"].decision != "Skip"]
    assert len(apps) == len(non_skip) > 0
    for record in apps.values():
        assert record["stage"] == "Not Applied"
        assert record["llm_error"] == "GEMINI_API_KEY not set"
        assert record["priority_rank"] is not None

    # A second run shouldn't clobber a stage change made in between.
    apps_data = applications_mod.load(applications_path)
    first_key = next(iter(apps_data["applications"]))
    apps_data["applications"][first_key] = applications_mod.apply_stage_change(
        apps_data["applications"][first_key], "Applied", today="2026-07-10"
    )
    applications_mod.save(applications_path, apps_data)

    second = pipeline.run(
        cv_dir=str(cv_dir),
        state_path=state_path,
        reports_dir=reports_dir,
        sources=fixture_sources(),
        role_families=["Enterprise Architect"],
        http_session=FakeSession(),
        today=date(2026, 7, 11),
        force=True,
        applications_path=applications_path,
        gemini_api_key=None,
    )
    updated = second["applications"]["applications"][first_key]
    assert updated["stage"] == "Applied"
    assert updated["applied_date"] == "2026-07-10"
