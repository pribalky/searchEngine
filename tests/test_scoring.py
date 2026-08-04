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


def test_seniority_gap_applies_modest_penalty_not_hard_veto():
    """A title several levels above the user's current one (Associate
    Architect) should score lower than an equivalent-content role at
    their level, but should NOT be automatically excluded from Apply/
    Priority Apply -- title seniority doesn't always track real
    responsibilities."""
    strong_cv = (
        "Enterprise Architecture, Architecture Governance, Design Authority, "
        "Stakeholder Management and Technology Strategy experience across Banking."
    )
    description = (
        "Architecture Governance, Design Authority and Technology Strategy role. "
        "Essential: Stakeholder Management."
    )

    same_level = score_posting("Solution Architect", description, {"cv": strong_cv})
    big_stretch = score_posting("Head of Architecture", description, {"cv": strong_cv})

    assert same_level.seniority_gap == 0
    assert same_level.career_stretch_level == "At or below current level"
    assert big_stretch.seniority_gap == 3
    assert big_stretch.career_stretch_level == "Major stretch (+3+ levels)"

    # Modest penalty: lower score, but not necessarily knocked out of contention.
    assert big_stretch.interview_probability < same_level.interview_probability
    assert same_level.interview_probability - big_stretch.interview_probability == 27  # 3 levels * 9 points


def test_unmatched_title_gets_no_seniority_penalty():
    result = score_posting("AI Governance Lead", JD_DESCRIPTION, {"cv": "AI Governance experience."})
    assert result.seniority_gap is None
    assert result.career_stretch_level == "Unclear"


def test_ats_match_weights_responsibility_evidence_over_title_mention():
    """The core ask: a keyword mentioned only in a CV job-title header
    should score (and count as a gap) worse than the same keyword backed
    by an actual demonstrated-responsibility bullet."""
    jd_title = "Enterprise Architect"
    jd_description = "We need Design Authority and Technology Strategy experience. Essential: Architecture Governance."

    title_only_cv = (
        "PROFESSIONAL EXPERIENCE\n"
        "Design Authority & Technology Strategy Lead | SomeCo, UK 2020 - 2022\n"
        "Delivered unrelated day-to-day support tickets and general admin tasks.\n"
    )
    responsibility_backed_cv = (
        "PROFESSIONAL EXPERIENCE\n"
        "Consultant | SomeCo, UK 2020 - 2022\n"
        "Delivered Design Authority governance and shaped Technology Strategy roadmaps, "
        "embedding Architecture Governance controls across delivery teams.\n"
    )

    title_only_result = score_posting(jd_title, jd_description, {"cv": title_only_cv})
    responsibility_result = score_posting(jd_title, jd_description, {"cv": responsibility_backed_cv})

    assert responsibility_result.ats_match > title_only_result.ats_match
    assert "Design Authority" in title_only_result.missing_keywords
    assert "Design Authority" not in responsibility_result.missing_keywords
    assert responsibility_result.ats_match == 100
    assert title_only_result.ats_match == 17  # 2 of 3 keywords at 0.25 partial credit


def test_single_incidental_keyword_cannot_reach_full_ats_match():
    """Reproduces a real false positive: a JD for a completely unrelated
    role (an IT support job) that happens to mention the employer's own
    sector once ("financial services") should not score a perfect ATS
    Match just because that one generic word also recurs in the CV --
    that's a single incidental hit, not real evidence of fit."""
    unrelated_title = "Application Support Engineer"
    unrelated_description = "Join our financial services company, providing 2nd/3rd line application support."
    broad_cv = (
        "Architecture professional delivering enterprise technology solutions across banking, "
        "financial services, fintech, logistics, and software product environments."
    )

    result = score_posting(unrelated_title, unrelated_description, {"cv": broad_cv})

    assert result.ats_match < 100
    assert result.decision in {"Stretch", "Skip"}


def test_recruiter_match_only_considers_cv_title_lines():
    cv_with_matching_title_but_no_responsibility_overlap = (
        "PROFESSIONAL EXPERIENCE\n"
        "Enterprise Architect | SomeCo, UK 2020 - 2022\n"
        "Unrelated day-to-day admin work.\n"
    )
    result = score_posting(
        "Enterprise Architect", "Looking for an Enterprise Architect.", {"cv": cv_with_matching_title_but_no_responsibility_overlap}
    )
    # Title-line match plus exact role-family bonus should still register.
    assert result.recruiter_match > 0


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
