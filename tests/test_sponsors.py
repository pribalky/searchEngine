from job_search.sponsors import (
    find_csv_url,
    fetch_sponsor_names,
    is_registered_sponsor,
    normalize_name,
    parse_sponsor_csv,
)

SAMPLE_CSV = (
    "Organisation Name,Town/City,County,Type & Rating,Route\n"
    "Barclays Bank UK Plc,London,Greater London,Worker (A rating),Skilled Worker\n"
    "Deloitte LLP,London,Greater London,Worker (A rating),Skilled Worker\n"
    "HSBC UK Bank Plc,Birmingham,West Midlands,Worker (A rating),Skilled Worker\n"
    "Acme Bespoke Widgets Limited,Leeds,West Yorkshire,Worker (A rating),Skilled Worker\n"
)

SAMPLE_PUBLICATION_HTML = """
<html><body>
<a class="gem-c-attachment__link" href="https://assets.publishing.service.gov.uk/media/abc123/2026-07-01_-_Worker_and_Temporary_Worker.csv">Register of licensed sponsors (CSV, 4.1MB)</a>
</body></html>
"""


def test_normalize_name_strips_suffixes_and_punctuation():
    assert normalize_name("Barclays Bank UK Plc") == "barclays bank"
    assert normalize_name("Deloitte LLP") == "deloitte"
    assert normalize_name("Acme, Inc.") == "acme"


def test_find_csv_url_prefers_assets_cdn():
    url = find_csv_url(SAMPLE_PUBLICATION_HTML)
    assert url == "https://assets.publishing.service.gov.uk/media/abc123/2026-07-01_-_Worker_and_Temporary_Worker.csv"


def test_find_csv_url_falls_back_to_any_csv_link():
    html = '<a href="https://example.com/register/downloads/sponsors.csv">Download</a>'
    assert find_csv_url(html) == "https://example.com/register/downloads/sponsors.csv"


def test_find_csv_url_returns_none_when_absent():
    assert find_csv_url("<html><body>no csv here</body></html>") is None


def test_parse_sponsor_csv_returns_normalized_names():
    names = parse_sponsor_csv(SAMPLE_CSV)
    assert "barclays bank" in names
    assert "deloitte" in names
    assert "hsbc bank" in names
    assert len(names) == 4


def test_is_registered_sponsor_matches_brand_name_against_legal_name():
    names = parse_sponsor_csv(SAMPLE_CSV)
    assert is_registered_sponsor("Barclays", names) is True
    assert is_registered_sponsor("HSBC", names) is True
    assert is_registered_sponsor("Deloitte", names) is True


def test_is_registered_sponsor_false_for_unlisted_company():
    names = parse_sponsor_csv(SAMPLE_CSV)
    assert is_registered_sponsor("Totally Unknown Startup Ltd", names) is False


def test_is_registered_sponsor_avoids_false_positives_from_short_names():
    names = parse_sponsor_csv(SAMPLE_CSV)
    assert is_registered_sponsor("AI", names) is False
    assert is_registered_sponsor("UK", names) is False  # strips to empty after suffix removal


def test_is_registered_sponsor_handles_empty_registry():
    assert is_registered_sponsor("Barclays", set()) is False


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"status {self.status_code}")


class _FakeSession:
    def __init__(self, page_html, csv_text):
        self.page_html = page_html
        self.csv_text = csv_text
        self.requested_urls = []

    def get(self, url, timeout=None):
        self.requested_urls.append(url)
        if url.endswith(".csv"):
            return _FakeResponse(self.csv_text)
        return _FakeResponse(self.page_html)


def test_fetch_sponsor_names_orchestrates_page_then_csv():
    session = _FakeSession(SAMPLE_PUBLICATION_HTML, SAMPLE_CSV)
    names = fetch_sponsor_names(session=session, timeout=5)

    assert "barclays bank" in names
    assert len(session.requested_urls) == 2
    assert session.requested_urls[1].endswith(".csv")


def test_fetch_sponsor_names_raises_when_no_csv_link_found():
    session = _FakeSession("<html>no link</html>", SAMPLE_CSV)
    try:
        fetch_sponsor_names(session=session, timeout=5)
        assert False, "expected ValueError"
    except ValueError:
        pass
