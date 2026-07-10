from datetime import date

from job_search import tagging


def test_tag_sector():
    assert tagging.tag_sector("Barclays UK") == "Banking"
    assert tagging.tag_sector("Deloitte LLP") == "Consulting"
    assert tagging.tag_sector("Some Random Startup") == "Other"


def test_tag_role_categories():
    cats = tagging.tag_role_categories("Architecture Governance Manager", "responsible for governance and assurance")
    assert "Governance Roles" in cats
    assert "Architecture Assurance Roles" in cats


def test_tag_work_pattern():
    assert tagging.tag_work_pattern("This role is fully remote") == "Remote"
    assert tagging.tag_work_pattern("Hybrid working, 2 days in office") == "Hybrid"
    assert tagging.tag_work_pattern("No location info") == "Unknown"


def test_tag_visa_sponsorship_uses_registry_when_available():
    sponsor_names = {"barclays bank"}
    assert tagging.tag_visa_sponsorship("Barclays", "any description", sponsor_names) == "Registered Sponsor"
    assert tagging.tag_visa_sponsorship("Totally Unknown Ltd", "any description", sponsor_names) == "Not Registered"


def test_tag_visa_sponsorship_falls_back_to_weak_guess_when_registry_unavailable():
    assert "registry unavailable" in tagging.tag_visa_sponsorship("Barclays", "Visa sponsorship available for this role", None)
    assert "registry unavailable" in tagging.tag_visa_sponsorship("Barclays", "We are unable to sponsor visas", set())
    assert tagging.tag_visa_sponsorship("Barclays", "No mention either way", None) == "Unknown (registry unavailable)"


def test_compute_days_left():
    today = date(2026, 7, 9)
    assert tagging.compute_days_left("2026-07-09", 45, today=today) == 45
    assert tagging.compute_days_left("2026-06-24", 45, today=today) == 30
    assert tagging.compute_days_left("2026-05-25", 45, today=today) == 0
    assert tagging.compute_days_left("", 45, today=today) is None
    assert tagging.compute_days_left(None, 45, today=today) is None
    assert tagging.compute_days_left("not-a-date", 45, today=today) is None
