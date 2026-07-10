"""Cross-checks employer names against the UK Home Office's public Register
of Licensed Sponsors (Worker routes), instead of guessing sponsorship from
job description text. This is the real signal the user's goal depends on:
"known sponsors", not a keyword heuristic.

The register is published at a stable page but the underlying CSV asset
URL changes with every update, so this scrapes the publication page for
the current attachment link rather than hardcoding a CSV URL. Network
calls are isolated in fetch_sponsor_names() so the rest of this module is
unit-testable without hitting the network."""
import csv
import io
import re
from typing import Optional, Set

import requests

PUBLICATION_PAGE_URL = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"

# Legal-entity suffixes stripped before comparing job-posting company names
# against register entries, since "Barclays" (job posting) vs "Barclays
# Bank UK Plc" (register) would never match on exact string equality.
_SUFFIX_RE = re.compile(
    r"\b(plc|ltd|limited|llp|llc|inc|incorporated|corp|corporation|group|"
    r"holdings|the|uk|international|global)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]")

# Below this normalized length, substring containment produces too many
# false positives (e.g. "AI" or "IT" would match a huge share of names).
MIN_MATCH_LENGTH = 4


def normalize_name(name: str) -> str:
    text = (name or "").lower()
    text = _SUFFIX_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def find_csv_url(html: str) -> Optional[str]:
    """Extract the current register CSV attachment URL from the gov.uk
    publication page HTML. Prefers the standard assets CDN, falls back to
    any .csv link on the page."""
    match = re.search(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"', html)
    if match:
        return match.group(1)
    match = re.search(r'href="([^"]+\.csv)"', html)
    return match.group(1) if match else None


def parse_sponsor_csv(csv_text: str) -> Set[str]:
    """Returns the set of normalized organisation names in the register."""
    reader = csv.DictReader(io.StringIO(csv_text))
    name_field = next(
        (f for f in (reader.fieldnames or []) if f and "organisation" in f.lower()),
        None,
    )
    if not name_field:
        return set()
    return {normalize_name(row[name_field]) for row in reader if row.get(name_field)}


def is_registered_sponsor(company: str, sponsor_names: Set[str]) -> bool:
    if not sponsor_names:
        return False
    normalized = normalize_name(company)
    if len(normalized) < MIN_MATCH_LENGTH:
        return False
    if normalized in sponsor_names:
        return True
    return any(normalized in sponsor_name for sponsor_name in sponsor_names)


def fetch_sponsor_names(session: requests.Session = None, timeout: int = 30) -> Set[str]:
    """Live fetch: scrape the publication page for the current CSV link,
    download it, and parse it. Raises requests.RequestException or
    ValueError on failure -- callers should catch and degrade gracefully
    rather than let a scrape hiccup take down the whole pipeline run."""
    http = session or requests
    page_resp = http.get(PUBLICATION_PAGE_URL, timeout=timeout)
    page_resp.raise_for_status()

    csv_url = find_csv_url(page_resp.text)
    if not csv_url:
        raise ValueError(f"could not find a CSV link on {PUBLICATION_PAGE_URL}")

    csv_resp = http.get(csv_url, timeout=timeout)
    csv_resp.raise_for_status()
    return parse_sponsor_csv(csv_resp.text)
