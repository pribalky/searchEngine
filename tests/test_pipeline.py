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
