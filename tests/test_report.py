from job_search.report import build_report
from job_search.scoring import ScoreResult
from job_search.sources.base import JobPosting


def make_record(title, company, decision="Apply", interview_probability=80, overall_fit=80, sector="Banking", days_left=None):
    posting = JobPosting(
        source="adzuna",
        source_id=title,
        title=title,
        company=company,
        location="London",
        description=f"{title} at {company} requiring Architecture Governance and Design Authority.",
        url="https://example.com/job",
        posted_date="2026-07-08",
    )
    score = ScoreResult(
        overall_fit=overall_fit,
        ats_match=70,
        recruiter_match=70,
        hiring_manager_match=70,
        interview_probability=interview_probability,
        best_cv="architecture_governance",
        missing_keywords=["Responsible AI"],
        rewrite_effort="Minor (30 mins)",
        decision=decision,
    )
    return {
        "posting": posting,
        "score": score,
        "sector": sector,
        "role_categories": ["Governance Roles", "Design Authority Roles"],
        "work_pattern": "Hybrid",
        "visa": "Unclear",
        "stretch": "Core",
        "days_left": days_left,
    }


def test_build_report_contains_expected_sections():
    records = [
        make_record("Enterprise Architect", "Barclays", decision="Priority Apply", interview_probability=90),
        make_record("Business Architect", "Deloitte", sector="Consulting", interview_probability=72),
    ]
    report = build_report("2026-07-09", records, excluded_count=1, cvs_loaded=4)

    assert "Execution date:** 2026-07-09" in report
    assert "Enterprise Architect" in report
    assert "## Master Table" in report
    assert "## Top 10 Highest Fit" in report
    assert "## Banking Opportunities" in report
    assert "## Consulting Opportunities" in report
    assert "## Governance Roles" in report
    assert "## Market Analysis" in report
    assert "Step 8" in report


def test_build_report_handles_empty_records():
    report = build_report("2026-07-09", [], excluded_count=0, cvs_loaded=0)
    assert "No verified vacancies" in report


def test_closing_soon_section_includes_urgent_apply_roles_sorted_by_urgency():
    records = [
        make_record("Enterprise Architect", "Barclays", decision="Priority Apply", days_left=8),
        make_record("Business Architect", "Deloitte", decision="Apply", days_left=2),
        make_record("Solution Architect", "HSBC", decision="Priority Apply", days_left=None),  # unknown, excluded
        make_record("Governance Lead", "NatWest", decision="Stretch", days_left=1),  # not Apply+, excluded
        make_record("Head of Architecture", "PwC", decision="Apply", days_left=40),  # not urgent, excluded
    ]
    report = build_report("2026-07-09", records, excluded_count=0, cvs_loaded=3)

    assert "## Apply Now -- Closing Soon" in report
    closing_section = report.split("## Apply Now -- Closing Soon")[1].split("## Top 10 Highest Fit")[0]
    deloitte_pos = closing_section.index("Deloitte")
    barclays_pos = closing_section.index("Barclays")
    assert deloitte_pos < barclays_pos  # 2 days left sorts before 8 days left
    assert "HSBC" not in closing_section
    assert "NatWest" not in closing_section
    assert "PwC" not in closing_section


def test_days_left_column_renders_in_table():
    records = [make_record("Enterprise Architect", "Barclays", days_left=12)]
    report = build_report("2026-07-09", records, excluded_count=0, cvs_loaded=1)
    assert "Days Left" in report
    assert "| 12 |" in report
