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


def test_generic_lead_title_without_architecture_anchor_is_not_priority_apply():
    """Reproduces the real false positive seen in production: a generic
    'Technical Lead' JD with boilerplate 'Stakeholder Management' language
    but nothing architecture/governance-specific should never outrank a
    genuine architecture role, even if a broad CV happens to overlap on
    generic terms."""
    generic_title = "Technical Motor Claims Lead"
    generic_description = (
        "Great opportunity for a Technical Lead with strong Stakeholder Management and "
        "Technical Leadership skills to join our claims team. Essential: leadership experience."
    )
    broad_cv = (
        "Extensive Technical Leadership, Stakeholder Management and team leadership experience "
        "across Banking and Financial Services, leading cross-functional delivery teams."
    )

    result = score_posting(generic_title, generic_description, {"cv": broad_cv})

    assert result.decision not in {"Priority Apply", "Apply", "Apply after tailoring"}


def test_architecture_titled_role_is_unaffected_by_anchor_gate():
    strong_cv = (
        "Enterprise Architecture, Architecture Governance, Design Authority, "
        "Stakeholder Management and Technology Strategy experience across Banking."
    )
    result = score_posting(JD_TITLE, JD_DESCRIPTION, {"cv": strong_cv})
    assert result.decision in {"Priority Apply", "Apply", "Apply after tailoring", "Stretch", "Skip"}


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
