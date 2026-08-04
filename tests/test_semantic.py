from job_search.semantic import tfidf_similarity_pct


def test_identical_text_scores_high():
    text = "Established architecture governance controls and delivery frameworks."
    assert tfidf_similarity_pct(text, text) == 100


def test_completely_unrelated_text_scores_low():
    a = "Established architecture governance controls and delivery frameworks."
    b = "Baked bread and watered the garden every morning before breakfast."
    assert tfidf_similarity_pct(a, b) < 20


def test_catches_partial_overlap_literal_keyword_matching_misses():
    """The real point of this module: two sentences sharing zero
    PROFILE_KEYWORDS exact phrases, but real overlapping vocabulary,
    should score meaningfully above zero -- unlike fixed-keyword overlap,
    which would score this as a complete miss."""
    cv_text = "Established governance controls, including Definition of Ready and architecture entry criteria."
    jd_text = "Define delivery gate criteria and embed governance controls across engineering teams."
    score = tfidf_similarity_pct(cv_text, jd_text)
    assert score > 0


def test_empty_inputs_score_zero():
    assert tfidf_similarity_pct("", "something") == 0
    assert tfidf_similarity_pct("something", "") == 0
    assert tfidf_similarity_pct(None, None) == 0


def test_stopwords_only_text_does_not_crash():
    assert tfidf_similarity_pct("the a an of", "and or but") == 0
