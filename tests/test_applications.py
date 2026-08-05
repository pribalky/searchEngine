import json
import os

from job_search import applications
from job_search.scoring import ScoreResult
from job_search.sources.base import JobPosting


def _make_record(source_id="1", interview_probability=80, decision="Priority Apply", days_left=5):
    posting = JobPosting(
        source="adzuna",
        source_id=source_id,
        title="Enterprise Architect",
        company="GoodCo",
        location="Edinburgh, UK",
        description="Architecture governance role.",
        url=f"https://example.com/{source_id}",
        posted_date="2026-07-01",
        role_family="Enterprise Architect",
    )
    score = ScoreResult(
        overall_fit=80,
        ats_match=80,
        recruiter_match=70,
        hiring_manager_match=75,
        interview_probability=interview_probability,
        best_cv="architecture_governance",
        missing_keywords=[],
        rewrite_effort="None",
        decision=decision,
        seniority_gap=0,
        career_stretch_level="Same Level",
        semantic_match=60,
    )
    return {"posting": posting, "score": score, "days_left": days_left}


def test_sync_creates_new_record_with_defaults(tmp_path):
    path = str(tmp_path / "applications.json")
    data = applications.sync(path, [_make_record()], llm_results={}, today="2026-07-09")

    record = data["applications"]["adzuna:1"]
    assert record["stage"] == "Not Applied"
    assert record["notes"] == ""
    assert record["applied_date"] is None
    assert record["company"] == "GoodCo"
    assert record["priority_rank"] == 1
    assert record["first_seen"] == "2026-07-09"


def test_sync_omits_skip_decisions(tmp_path):
    path = str(tmp_path / "applications.json")
    data = applications.sync(path, [_make_record(decision="Skip")], llm_results={}, today="2026-07-09")
    assert data["applications"] == {}


def test_sync_preserves_stage_and_dates_across_runs(tmp_path):
    path = str(tmp_path / "applications.json")
    applications.sync(path, [_make_record()], llm_results={}, today="2026-07-09")

    data = applications.load(path)
    data["applications"]["adzuna:1"] = applications.apply_stage_change(
        data["applications"]["adzuna:1"], "Applied", today="2026-07-10"
    )
    applications.save(path, data)

    # Next run: score changes, but stage/applied_date must survive.
    rerun_record = _make_record(interview_probability=90)
    data = applications.sync(path, [rerun_record], llm_results={}, today="2026-07-15")

    record = data["applications"]["adzuna:1"]
    assert record["stage"] == "Applied"
    assert record["applied_date"] == "2026-07-10"
    assert record["interview_probability"] == 90  # pipeline-owned field refreshed


def test_sync_merges_llm_results(tmp_path):
    path = str(tmp_path / "applications.json")
    llm_results = {
        "adzuna:1": {
            "cv_match_gap": "Strong overlap on governance, missing AI adoption experience.",
            "recruiter_pass_pct": 70,
            "hiring_manager_pass_pct": 60,
            "worth_applying": "Yes",
            "worth_applying_reason": "Clear architecture governance match.",
            "cv_to_use": "governanceCVBarclays",
            "recommendation": "Add a bullet on AI governance work.",
            "error": None,
        }
    }
    data = applications.sync(path, [_make_record()], llm_results=llm_results, today="2026-07-09")
    record = data["applications"]["adzuna:1"]
    assert record["llm_worth_applying"] == "Yes"
    assert record["llm_cv_to_use"] == "governanceCVBarclays"
    assert record["llm_recruiter_pass_pct"] == 70


def test_priority_rank_excludes_rejected_and_withdrawn(tmp_path):
    path = str(tmp_path / "applications.json")
    records = [
        _make_record(source_id="1", interview_probability=90),
        _make_record(source_id="2", interview_probability=80),
        _make_record(source_id="3", interview_probability=70),
    ]
    data = applications.sync(path, records, llm_results={}, today="2026-07-09")
    data["applications"]["adzuna:1"] = applications.apply_stage_change(
        data["applications"]["adzuna:1"], "Rejected", today="2026-07-10"
    )
    applications.save(path, data)

    # Re-sync (e.g. next run) should keep the rejected posting out of ranking.
    data = applications.sync(path, records, llm_results={}, today="2026-07-11")

    assert data["applications"]["adzuna:1"]["priority_rank"] is None
    assert data["applications"]["adzuna:2"]["priority_rank"] == 1
    assert data["applications"]["adzuna:3"]["priority_rank"] == 2


def test_apply_stage_change_stamps_date_once():
    record = {"stage": "Not Applied", "applied_date": None}
    updated = applications.apply_stage_change(record, "Applied", today="2026-07-10")
    assert updated["applied_date"] == "2026-07-10"

    updated_again = applications.apply_stage_change(updated, "Applied", today="2026-07-20")
    assert updated_again["applied_date"] == "2026-07-10"  # not overwritten


def test_apply_stage_change_not_applied_has_no_date_field():
    record = {"stage": "Applied", "applied_date": "2026-07-10"}
    updated = applications.apply_stage_change(record, "Not Applied", today="2026-07-20")
    assert updated["stage"] == "Not Applied"
    assert updated["applied_date"] == "2026-07-10"  # untouched, no date field for this stage


def test_sync_appends_llm_spend_log(tmp_path):
    path = str(tmp_path / "applications.json")
    spend = {"calls": 2, "errors": 0, "prompt_tokens": 1800, "output_tokens": 350, "total_tokens": 2150, "estimated_cost_usd": 0.0014}
    data = applications.sync(path, [_make_record()], llm_results={}, today="2026-07-09", llm_spend=spend)
    assert data["llm_spend_log"] == [{"date": "2026-07-09", **spend}]

    # A second run appends rather than overwriting.
    data = applications.sync(path, [_make_record()], llm_results={}, today="2026-07-15", llm_spend=spend)
    assert len(data["llm_spend_log"]) == 2
    assert data["llm_spend_log"][-1]["date"] == "2026-07-15"


def test_sync_without_llm_spend_leaves_log_unset(tmp_path):
    path = str(tmp_path / "applications.json")
    data = applications.sync(path, [_make_record()], llm_results={}, today="2026-07-09")
    assert "llm_spend_log" not in data


def test_upsert_operates_on_in_memory_data_without_file_io(tmp_path):
    data = {"schema_version": 1, "applications": {}}
    result = applications.upsert(data, [_make_record()], llm_results={}, today="2026-07-09")
    assert result is data  # mutated and returned in place, no file touched
    assert "adzuna:1" in data["applications"]
    assert not (tmp_path / "applications.json").exists()


def test_sync_is_a_thin_wrapper_around_upsert(tmp_path):
    path = str(tmp_path / "applications.json")
    via_sync = applications.sync(path, [_make_record()], llm_results={}, today="2026-07-09")
    assert via_sync["applications"]["adzuna:1"]["company"] == "GoodCo"
    # File was actually written (sync's job beyond upsert).
    assert applications.load(path)["applications"]["adzuna:1"]["company"] == "GoodCo"


def test_force_include_bypasses_skip_filter(tmp_path):
    path = str(tmp_path / "applications.json")
    skip_record = _make_record(decision="Skip", interview_probability=10)
    data = applications.sync(path, [skip_record], llm_results={}, today="2026-07-09", force_include=True)
    assert "adzuna:1" in data["applications"]
    assert data["applications"]["adzuna:1"]["decision"] == "Skip"


def test_force_include_still_ranks_forced_records_by_priority(tmp_path):
    path = str(tmp_path / "applications.json")
    records = [
        _make_record(source_id="1", interview_probability=10, decision="Skip"),
        _make_record(source_id="2", interview_probability=80, decision="Priority Apply"),
    ]
    data = applications.sync(path, records, llm_results={}, today="2026-07-09", force_include=True)
    assert data["applications"]["adzuna:2"]["priority_rank"] == 1
    assert data["applications"]["adzuna:1"]["priority_rank"] == 2


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "nested" / "applications.json")
    data = applications.sync(path, [_make_record()], llm_results={}, today="2026-07-09")
    assert os.path.exists(path)

    reloaded = applications.load(path)
    assert reloaded["applications"]["adzuna:1"]["company"] == "GoodCo"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw == reloaded
