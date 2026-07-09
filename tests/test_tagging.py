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


def test_tag_visa_sponsorship():
    assert tagging.tag_visa_sponsorship("Visa sponsorship available for this role") == "Likely"
    assert tagging.tag_visa_sponsorship("We are unable to sponsor visas") == "Unlikely"
    assert tagging.tag_visa_sponsorship("No mention either way") == "Unclear"


def test_tag_career_stretch():
    assert tagging.tag_career_stretch("Director of Architecture") == "Stretch"
    assert tagging.tag_career_stretch("Enterprise Architect") == "Core"
