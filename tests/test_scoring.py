from job_search.scoring import score_posting


JD_TITLE = "Enterprise Architect"
JD_DESCRIPTION = (
    "We need an Enterprise Architect with Architecture Governance, Design Authority "
    "and Stakeholder Management experience. Essential: Technology Strategy background."
)


def test_score_posting_prefers_matching_cv():
    strong_cv = "Extensive Enterprise Architecture, Architecture Governance, Design Authority, " \
                "Stakeholder Management and Technology Strategy experience across Banking."
    weak_cv = "Experienced software developer with Python and Java skills."

    result = score_posting(JD_TITLE, JD_DESCRIPTION, {"strong": strong_cv, "weak": weak_cv})

    assert result.best_cv == "strong"
    assert result.ats_match > 0
    assert result.decision in {"Priority Apply", "Apply", "Apply after tailoring", "Stretch", "Skip"}


def test_score_posting_no_cvs_falls_back_to_profile_only():
    result = score_posting(JD_TITLE, JD_DESCRIPTION, {})
    assert result.best_cv is None
    assert result.overall_fit >= 0


def test_missing_keywords_and_rewrite_effort_scale():
    no_match_cv = "Completely unrelated career history in retail management."
    result = score_posting(JD_TITLE, JD_DESCRIPTION, {"cv": no_match_cv})
    assert len(result.missing_keywords) > 0
    assert result.rewrite_effort != "None"


def test_decision_thresholds_are_consistent_with_probability():
    strong_cv = (
        "Enterprise Architecture, Business Architecture, Solution Architecture, Architecture Governance, "
        "Design Authority, Architecture Assurance, Architecture Centre of Excellence, Technology Strategy, "
        "Technology Transformation, Technology Governance, Technical Leadership, AI Feasibility, AI Adoption, "
        "Responsible AI, Stakeholder Management, Banking, Financial Services, Consulting, Enterprise Architect"
    )
    result = score_posting(JD_TITLE, JD_DESCRIPTION, {"cv": strong_cv})
    assert result.interview_probability >= 60
    assert result.decision in {"Priority Apply", "Apply"}
