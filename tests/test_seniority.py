from job_search.seniority import compute_gap, infer_seniority_level, penalty_points, stretch_label


def test_infer_seniority_level_current_tier():
    assert infer_seniority_level("Associate Architect") == 0
    assert infer_seniority_level("Solution Architect") == 0
    assert infer_seniority_level("Business Architect") == 0
    assert infer_seniority_level("Data Architect") == 0  # generic "Architect" catch-all


def test_infer_seniority_level_higher_tiers():
    assert infer_seniority_level("Principal Architect") == 1
    assert infer_seniority_level("Lead Architect") == 1
    assert infer_seniority_level("Enterprise Architect") == 2
    assert infer_seniority_level("Domain Architect") == 2
    assert infer_seniority_level("Head of Architecture") == 3
    assert infer_seniority_level("Director of Architecture") == 3
    assert infer_seniority_level("VP of Architecture") == 4


def test_infer_seniority_level_prefers_more_senior_compound_title():
    # Contains both a level-3 signal ("Head of") and a level-2 phrase
    # ("Enterprise Architecture") -- the more senior one should win.
    assert infer_seniority_level("Head of Enterprise Architecture") == 3


def test_infer_seniority_level_unmatched_title_returns_none():
    assert infer_seniority_level("Technical Motor Claims Lead") is None
    assert infer_seniority_level("") is None
    assert infer_seniority_level(None) is None


def test_compute_gap_relative_to_current_level():
    assert compute_gap("Associate Architect") == 0
    assert compute_gap("Enterprise Architect") == 2
    assert compute_gap("Head of Architecture") == 3
    assert compute_gap("Technical Lead") is None


def test_stretch_label():
    assert stretch_label(None) == "Unclear"
    assert stretch_label(0) == "At or below current level"
    assert stretch_label(-1) == "At or below current level"
    assert stretch_label(1) == "Stretch (+1 level)"
    assert stretch_label(2) == "Significant stretch (+2 levels)"
    assert stretch_label(3) == "Major stretch (+3+ levels)"
    assert stretch_label(5) == "Major stretch (+3+ levels)"


def test_penalty_points_scales_with_gap_and_never_negative():
    assert penalty_points(None) == 0
    assert penalty_points(0) == 0
    assert penalty_points(-2) == 0
    assert penalty_points(1) == 9
    assert penalty_points(2) == 18
    assert penalty_points(3) == 27
