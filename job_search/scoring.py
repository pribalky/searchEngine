"""Rule-based (non-LLM) scoring. Kept in one module so it can be swapped
for a Claude API-backed scorer later without touching pipeline.py.

Every score is a keyword-overlap heuristic, not genuine reasoning about
fit -- report output says so explicitly. See plan doc for rationale."""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config, cv_parser, semantic, seniority

WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]+")


@dataclass
class ScoreResult:
    overall_fit: int
    ats_match: int
    recruiter_match: int
    hiring_manager_match: int
    interview_probability: int
    best_cv: Optional[str]
    missing_keywords: List[str]
    rewrite_effort: str
    decision: str
    seniority_gap: Optional[int]
    career_stretch_level: str
    semantic_match: int


def _tokenize(text: str):
    return {w.lower() for w in WORD_RE.findall(text or "")}


def _phrase_hits(text: str, phrases: List[str]) -> List[str]:
    text_lower = (text or "").lower()
    return [p for p in phrases if p.lower() in text_lower]


def _keyword_overlap_pct(jd_text: str, cv_text: str, keywords: List[str], min_hits_for_full_confidence: int = 1):
    jd_hits = set(_phrase_hits(jd_text, keywords))
    if not jd_hits:
        return 0, jd_hits, set()
    cv_hits = set(_phrase_hits(cv_text, keywords))
    matched = jd_hits & cv_hits
    denominator = max(len(jd_hits), min_hits_for_full_confidence)
    pct = round(100 * len(matched) / denominator)
    return pct, jd_hits, matched


def _extract_requirements_section(description: str) -> str:
    """Best-effort extraction of the 'essential/required' portion of a JD,
    used as a proxy for what a hiring manager screens hardest against."""
    text = description or ""
    match = re.search(
        r"(essential|required|must have|mandatory)(.{0,800})",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(0) if match else text[:800]


def _extract_responsibilities_section(description: str) -> str:
    """Best-effort extraction of the 'what you'll do' portion of a JD, to
    pair against the CV's demonstrated-responsibility text specifically
    (as opposed to matching against the whole posting, which mixes in
    boilerplate/company-intro/benefits text)."""
    text = description or ""
    match = re.search(
        r"(responsibilities|what you.?ll do|what you will do|key responsibilities|"
        r"role overview|about the role|duties)(.{0,800})",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(0) if match else text[:800]


def _weighted_keyword_match(jd_text: str, titles_text: str, responsibilities_text: str, keywords: List[str]):
    """Like _keyword_overlap_pct, but a JD keyword only counts as fully
    matched when it's backed by CV responsibility/achievement text.
    A title-only mention still counts as "missing" (so gap/rewrite-effort
    reporting nudges toward adding a demonstrated bullet, not just relying
    on the title) but earns partial credit toward the score itself, since
    it's still a weak positive signal."""
    jd_hits = set(_phrase_hits(jd_text, keywords))
    if not jd_hits:
        return 0, jd_hits, []

    resp_hits = set(_phrase_hits(responsibilities_text, keywords))
    title_hits = set(_phrase_hits(titles_text, keywords))

    weighted_sum = 0.0
    for kw in jd_hits:
        if kw in resp_hits:
            weighted_sum += 1.0
        elif kw in title_hits:
            weighted_sum += config.CV_TITLE_MATCH_WEIGHT

    denominator = max(len(jd_hits), config.MIN_KEYWORD_HITS_FOR_FULL_CONFIDENCE)
    pct = round(100 * weighted_sum / denominator)
    missing = sorted(jd_hits - resp_hits)
    return pct, jd_hits, missing


def _rewrite_effort(missing_count: int) -> str:
    for threshold, label in config.REWRITE_EFFORT_BUCKETS:
        if missing_count <= threshold:
            return label
    return config.REWRITE_EFFORT_BUCKETS[-1][1]


def _decision(interview_probability: int, has_anchor: bool) -> str:
    t = config.DECISION_THRESHOLDS
    if interview_probability >= t["priority_apply"]:
        decision = "Priority Apply"
    elif interview_probability >= t["apply"]:
        decision = "Apply"
    elif interview_probability >= t["apply_after_tailoring"]:
        decision = "Apply after tailoring"
    elif interview_probability >= t["stretch"]:
        decision = "Stretch"
    else:
        return "Skip"

    if not has_anchor and decision in ("Priority Apply", "Apply", "Apply after tailoring"):
        # High numeric score but no architecture/governance-specific term
        # anywhere in the JD -- almost certainly a false positive from
        # incidental keyword overlap, not a genuine match.
        return "Stretch"
    return decision


def _has_anchor_keyword(jd_text: str) -> bool:
    text = jd_text.lower()
    return any(kw.lower() in text for kw in config.CORE_ANCHOR_KEYWORDS)


def score_posting(title: str, description: str, cvs: Dict[str, str]) -> ScoreResult:
    jd_text = f"{title}\n{description}"

    if not cvs:
        # No CVs on file yet: still tag against the base profile keyword
        # list so the pipeline is useful before the user's CVs are added.
        cvs = {"__profile_only__": " ".join(config.PROFILE_KEYWORDS)}

    best_cv = None
    best_ats = -1
    best_missing: List[str] = []
    best_sections = {"titles_text": "", "responsibilities_text": ""}
    for cv_name, cv_text in cvs.items():
        sections = cv_parser.split_cv_sections(cv_text)
        ats_pct, _, missing = _weighted_keyword_match(
            jd_text, sections["titles_text"], sections["responsibilities_text"], config.PROFILE_KEYWORDS
        )
        if ats_pct > best_ats:
            best_ats = ats_pct
            best_cv = None if cv_name == "__profile_only__" else cv_name
            best_missing = missing
            best_sections = sections

    # Recruiter screens compare job titles to job titles -- match against
    # the CV's title-lines only, not demonstrated-responsibility text.
    recruiter_pct, _, _ = _keyword_overlap_pct(
        title, best_sections["titles_text"], config.SENIOR_TITLE_SIGNALS + config.ROLE_FAMILIES
    )
    title_lower = title.lower()
    if any(rf.lower() in title_lower for rf in config.ROLE_FAMILIES):
        recruiter_pct = min(100, recruiter_pct + 20)

    # Hiring managers screen demonstrated experience against both the
    # JD's stated requirements and its stated day-to-day duties -- match
    # both against the CV's responsibility text only (no title credit).
    requirements_text = _extract_requirements_section(description)
    responsibilities_section = _extract_responsibilities_section(description)
    hm_jd_text = f"{requirements_text}\n{responsibilities_section}"
    hm_pct, _, _ = _keyword_overlap_pct(
        hm_jd_text,
        best_sections["responsibilities_text"],
        config.PROFILE_KEYWORDS,
        min_hits_for_full_confidence=config.MIN_KEYWORD_HITS_FOR_FULL_CONFIDENCE,
    )

    # TF-IDF/cosine similarity between demonstrated-responsibility text and
    # the JD description -- catches paraphrased overlap the fixed
    # PROFILE_KEYWORDS list above can't (see semantic.py). Deliberately
    # excludes the title text: this component exists to measure
    # responsibility overlap, and mixing title text back in would
    # reintroduce exactly the title-driven noise the rest of this
    # rebalance is trying to reduce.
    semantic_pct = semantic.tfidf_similarity_pct(best_sections["responsibilities_text"], description)

    w = config.OVERALL_FIT_WEIGHTS
    overall_fit = round(
        best_ats * w["ats"]
        + recruiter_pct * w["recruiter"]
        + hm_pct * w["hiring_manager"]
        + semantic_pct * w["semantic"]
    )
    keyword_penalty = min(40, len(best_missing) * 5)
    seniority_gap = seniority.compute_gap(title)
    seniority_penalty = seniority.penalty_points(seniority_gap)
    interview_probability = max(0, overall_fit - keyword_penalty - seniority_penalty)
    has_anchor = _has_anchor_keyword(jd_text)

    return ScoreResult(
        overall_fit=overall_fit,
        ats_match=best_ats,
        recruiter_match=recruiter_pct,
        hiring_manager_match=hm_pct,
        interview_probability=interview_probability,
        best_cv=best_cv,
        missing_keywords=best_missing,
        rewrite_effort=_rewrite_effort(len(best_missing)),
        decision=_decision(interview_probability, has_anchor),
        seniority_gap=seniority_gap,
        career_stretch_level=seniority.stretch_label(seniority_gap),
        semantic_match=semantic_pct,
    )
