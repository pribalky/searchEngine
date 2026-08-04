"""Splits a CV into job-title text vs. demonstrated-responsibility text, so
scoring.py can weight the latter more heavily than the former.

The 4 real CVs in cv/ share a recognisable structure per job entry:
    <Title> (Official title: X) | <Company>, <Location> <Year> - <Year or Present>
    <responsibility/achievement bullets...>
possibly with markdown emphasis (**bold**, _italic_) around parts of the
line. A header line is identified by containing both a "|" and a 4-digit
year -- no bullet/narrative line in these CVs contains a literal "|", so
this is a reliable, low-false-positive signal without needing a rigid
format match (handles the markdown-emphasis and no-space-before-year
variants seen across the 4 files).

If no header line is found at all (e.g. a plain-text CV, or the small
synthetic CV strings used in tests), the whole text is returned as both
"titles_text" and "responsibilities_text" -- degrading to the old
undifferentiated behavior rather than penalizing an unrecognised format."""
import re
from typing import Dict

_YEAR_RE = re.compile(r"(19|20)\d{2}")
_MARKDOWN_RE = re.compile(r"[*_`]+")


def _is_header_line(line: str) -> bool:
    return "|" in line and bool(_YEAR_RE.search(line))


def _clean_markdown(text: str) -> str:
    return _MARKDOWN_RE.sub("", text).strip()


def split_cv_sections(text: str) -> Dict[str, str]:
    title_lines = []
    body_lines = []
    for raw_line in (text or "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if _is_header_line(line):
            title_part = line.split("|", 1)[0]
            title_lines.append(_clean_markdown(title_part))
        else:
            body_lines.append(line)

    if not title_lines:
        whole = text or ""
        return {"titles_text": whole, "responsibilities_text": whole}

    return {
        "titles_text": " ".join(title_lines),
        "responsibilities_text": " ".join(body_lines),
    }
