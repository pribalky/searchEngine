from job_search.cv_parser import split_cv_sections

PLAIN_STYLE_CV = """Priya Balakrishnan
Business Architect | Enterprise Architecture | Business Transformation | Technology Strategy

PROFESSIONAL PROFILE
Architecture professional with 13+ years experience across banking and financial services.

PROFESSIONAL EXPERIENCE
Architecture Governance Architect (Official title: Associate Architect, WNS-Vuram) |  Barclays, UK 2026 – Present
Provide architecture governance and enterprise decision support across a large-scale banking transformation programme.
Establish governance controls, including Definition of Ready and architecture entry/exit criteria.
Architecture Consultant (Official title: Associate Architect, WNS-Vuram) | Global Bank, UK 2025 – 2026
Conducted architecture feasibility assessments and structured risk analysis to support enterprise change initiatives.
"""

MARKDOWN_STYLE_CV = """**PROFESSIONAL EXPERIENCE**

**Associate Architect**  |  Global Bank, UK _Feb 2026 – Present_

Providing architecture leadership across enterprise banking delivery teams.

*   Lead cross-team initiatives establishing reusable design patterns.
*   Conduct feasibility assessments evaluating business alignment.

**Pod Lead / Senior Developer**  |  Global Bank, UK_2022 – 2024_

Led delivery of enterprise risk and access-management capabilities.

*   Architected reporting and data-processing capabilities.

**TECHNOLOGIES & PLATFORMS:** Appian (19.4-26.3) | Appian AI Skills | AWS | REST APIs
**CERTIFICATIONS:** Appian AI Practitioner | AWS Cloud Practitioner
"""

PLAIN_TEXT_NO_HEADERS = (
    "Extensive Enterprise Architecture, Architecture Governance, Design Authority, "
    "Stakeholder Management and Technology Strategy experience across Banking."
)


def test_split_detects_pipe_and_year_header_lines():
    sections = split_cv_sections(PLAIN_STYLE_CV)
    assert "Architecture Governance Architect" in sections["titles_text"]
    assert "Architecture Consultant" in sections["titles_text"]
    assert "(Official title: Associate Architect, WNS-Vuram)" in sections["titles_text"]


def test_split_puts_bullets_and_summary_in_responsibilities():
    sections = split_cv_sections(PLAIN_STYLE_CV)
    assert "architecture governance and enterprise decision support" in sections["responsibilities_text"]
    assert "Definition of Ready" in sections["responsibilities_text"]
    assert "architecture feasibility assessments" in sections["responsibilities_text"]
    # Title text shouldn't leak into responsibilities text
    assert "Architecture Governance Architect" not in sections["responsibilities_text"]


def test_split_handles_markdown_emphasis_and_no_space_before_year():
    sections = split_cv_sections(MARKDOWN_STYLE_CV)
    assert "Associate Architect" in sections["titles_text"]
    assert "Pod Lead / Senior Developer" in sections["titles_text"]
    assert "Lead cross-team initiatives" in sections["responsibilities_text"]


def test_split_excludes_tech_and_cert_lists_from_titles_despite_pipes():
    """These lines contain many '|' characters but no 4-digit year, so
    they should NOT be misclassified as job-title headers -- they're
    matchable skill/cert content and shouldn't be down-weighted."""
    sections = split_cv_sections(MARKDOWN_STYLE_CV)
    assert "Appian AI Skills" in sections["responsibilities_text"]
    assert "AWS Cloud Practitioner" in sections["responsibilities_text"]
    assert "Appian AI Skills" not in sections["titles_text"]


def test_split_falls_back_to_whole_text_when_no_headers_found():
    sections = split_cv_sections(PLAIN_TEXT_NO_HEADERS)
    assert sections["titles_text"] == PLAIN_TEXT_NO_HEADERS
    assert sections["responsibilities_text"] == PLAIN_TEXT_NO_HEADERS


def test_split_handles_empty_and_none_text():
    assert split_cv_sections("") == {"titles_text": "", "responsibilities_text": ""}
    assert split_cv_sections(None) == {"titles_text": "", "responsibilities_text": ""}
