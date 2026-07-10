"""Maps a job title to a level on the architecture seniority ladder
(config.SENIORITY_LADDER) and computes the gap against the user's current
level. Used to apply a modest scoring penalty for title-level stretch
without a hard veto -- see config.py for the rationale."""
from typing import Optional

from . import config


def infer_seniority_level(title: str) -> Optional[int]:
    text = (title or "").lower()
    for level in sorted(config.SENIORITY_LADDER.keys(), reverse=True):
        keywords = config.SENIORITY_LADDER[level]
        if any(kw.lower() in text for kw in keywords):
            return level
    return None


def compute_gap(title: str) -> Optional[int]:
    """None means the title didn't match any ladder rung -- too ambiguous
    to score a gap, so callers should treat it as no penalty rather than
    guessing."""
    level = infer_seniority_level(title)
    if level is None:
        return None
    return level - config.CURRENT_SENIORITY_LEVEL


def stretch_label(gap: Optional[int]) -> str:
    if gap is None:
        return "Unclear"
    if gap <= 0:
        return "At or below current level"
    if gap == 1:
        return "Stretch (+1 level)"
    if gap == 2:
        return "Significant stretch (+2 levels)"
    return "Major stretch (+3+ levels)"


def penalty_points(gap: Optional[int]) -> int:
    if gap is None or gap <= 0:
        return 0
    return gap * config.SENIORITY_LEVEL_PENALTY
