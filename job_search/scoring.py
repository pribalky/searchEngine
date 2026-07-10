"""Rule-based (non-LLM) scoring. Kept in one module so it can be swapped
for a Claude API-backed scorer later without touching pipeline.py.

Every score is a keyword-overlap heuristic, not genuine reasoning about
fit -- report output says so explicitly. See plan doc for rationale."""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config

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


def _tokenize(text: str):
    return {w.lower() for w in WORD_RE.findall(text or "")}


def _phrase_hits(text: str, phrases: List[str]) -> List[str]:
    text_lower = (text or "").lower()
    return [p for p in phrases if p.lower() in text_lower]


def _keyword_overlap_pct(jd_text: str, cv_text: str, keywords: List[str]):
    jd_hits = set(_phrase_hits(jd_text, keywords))
    if not jd_hits:
        return 0, jd_hits, set()
    cv_hits = set(_phrase_hits(cv_text, keywords))
    matched = jd_hits & cv_hits
    pct = round(100 * len(matched) / len(jd_hits))
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
    for cv_name, cv_text in cvs.items():
        ats_pct, jd_hits, matched = _keyword_overlap_pct(jd_text, cv_text, config.PROFILE_KEYWORDS)
        if ats_pct > best_ats:
            best_ats = ats_pct
            best_cv = None if cv_name == "__profile_only__" else cv_name
            best_missing = sorted(jd_hits - matched)

    cv_text_for_best = cvs.get(best_cv) if best_cv else cvs.get("__profile_only__", "")

    recruiter_pct, _, _ = _keyword_overlap_pct(title, cv_text_for_best, config.SENIOR_TITLE_SIGNALS + config.ROLE_FAMILIES)
    # Recruiter screens also reward exact role-family title matches.
    title_lower = title.lower()
    if any(rf.lower() in title_lower for rf in config.ROLE_FAMILIES):
        recruiter_pct = min(100, recruiter_pct + 20)

    requirements_text = _extract_requirements_section(description)
    hm_pct, _, _ = _keyword_overlap_pct(requirements_text, cv_text_for_best, config.PROFILE_KEYWORDS)

    overall_fit = round(best_ats * 0.4 + recruiter_pct * 0.3 + hm_pct * 0.3)
    penalty = min(40, len(best_missing) * 5)
    interview_probability = max(0, overall_fit - penalty)
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
    )
