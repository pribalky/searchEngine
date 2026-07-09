from job_search.dedupe import dedupe
from job_search.sources.base import JobPosting


def make_posting(**overrides):
    base = dict(
        source="adzuna",
        source_id="1",
        title="Enterprise Architect",
        company="Barclays",
        location="London",
        description="short",
        url="https://example.com/1",
        posted_date="2026-07-05",
    )
    base.update(overrides)
    return JobPosting(**base)


def test_dedupe_merges_same_role_across_sources():
    a = make_posting(source="adzuna", source_id="1", description="short", posted_date="2026-07-05")
    b = make_posting(
        source="reed",
        source_id="99",
        description="a much longer and more complete description of the same role",
        posted_date="2026-07-01",
    )
    result = dedupe([a, b])
    assert len(result) == 1
    merged = result[0]
    assert merged.posted_date == "2026-07-01"  # earliest kept
    assert "longer" in merged.description  # fuller description kept


def test_dedupe_keeps_distinct_roles():
    a = make_posting(company="Barclays", title="Enterprise Architect")
    b = make_posting(company="Deloitte", title="Business Architect", source_id="2")
    result = dedupe([a, b])
    assert len(result) == 2
