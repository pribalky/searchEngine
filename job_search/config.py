"""Static configuration: role families, target employers, keyword taxonomy, thresholds."""

# Role families to search for, taken directly from the source prompt.
ROLE_FAMILIES = [
    "Enterprise Architect",
    "Business Architect",
    "Principal Architect",
    "Lead Architect",
    "Solution Architect",
    "Domain Architect",
    "Architecture Governance",
    "Architecture Assurance",
    "Architecture Manager",
    "Architecture Review Lead",
    "Architecture Design Authority",
    "Enterprise Design Authority",
    "Technology Governance Manager",
    "Technology Governance Lead",
    "Technology Strategy Lead",
    "Technology Transformation Lead",
    "Technology Advisory",
    "Senior Manager Technology Advisory",
    "Architecture Centre of Excellence",
    "CoE Lead",
    "Technical Programme Manager",
    "Technical Program Manager",
    "Technology Delivery Lead",
    "Platform Governance",
    "Engineering Governance",
    "AI Governance",
    "Responsible AI",
    "AI Adoption",
    "Digital Architecture",
    "Business Architecture",
    "Director of Architecture",
    "Head of Architecture",
    "Product Owner",
    "Program Manager",
    "Process Analyst",
]

# Named priority employers, tagged by sector tier. Used to flag (not filter)
# results, since MVP discovery is via job-board APIs rather than scraping
# each employer's own careers site directly.
BANKING_EMPLOYERS = [
    "Barclays",
    "Lloyds Banking Group",
    "Lloyds",
    "NatWest",
    "Nationwide",
    "HSBC",
    "Standard Chartered",
    "JPMorgan",
    "JP Morgan",
    "Citi",
    "Goldman Sachs",
    "Morgan Stanley",
]

CONSULTING_EMPLOYERS = [
    "Deloitte",
    "PwC",
    "KPMG",
    "Accenture",
    "Capgemini",
    "Cognizant",
    "Infosys",
    "Synechron",
    "Coforge",
]

NAMED_EMPLOYERS = BANKING_EMPLOYERS + CONSULTING_EMPLOYERS

# Candidate background keywords, used both as the "hard skill" taxonomy for
# ATS-style scoring and to build the base profile-match vocabulary.
PROFILE_KEYWORDS = [
    "Enterprise Architecture",
    "Business Architecture",
    "Solution Architecture",
    "Architecture Governance",
    "Design Authority",
    "Architecture Assurance",
    "Architecture Centre of Excellence",
    "Technology Strategy",
    "Technology Transformation",
    "Technology Governance",
    "Technical Leadership",
    "AI Feasibility",
    "AI Adoption",
    "Responsible AI",
    "Stakeholder Management",
    "Banking",
    "Financial Services",
    "Consulting",
]

# Vacancies older than this are excluded regardless of source.
MAX_POSTING_AGE_DAYS = 45

# Minimum gap (in days) between scheduled runs, enforced by main.py rather
# than relying purely on cron scheduling semantics.
MIN_DAYS_BETWEEN_RUNS = 2

# HTTP timeout (seconds) for link-verification requests.
VERIFY_TIMEOUT_SECONDS = 10

# Decision thresholds, applied to Interview Probability (/100) and gap count.
DECISION_THRESHOLDS = {
    "priority_apply": 75,
    "apply": 60,
    "apply_after_tailoring": 45,
    "stretch": 30,
    # below stretch threshold -> "Skip"
}

# CV rewrite effort buckets by missing-keyword count.
REWRITE_EFFORT_BUCKETS = [
    (0, "None"),
    (2, "Minor (30 mins)"),
    (5, "Moderate (1-2 hrs)"),
    (float("inf"), "Major rewrite"),
]

# Keywords used to flag visa sponsorship signal in a job description.
# Best-effort only: absence of a negative phrase is NOT proof of sponsorship.
VISA_POSITIVE_PHRASES = [
    "visa sponsorship available",
    "we sponsor visas",
    "sponsorship available",
    "can sponsor",
    "skilled worker visa",
]
VISA_NEGATIVE_PHRASES = [
    "unable to sponsor",
    "cannot sponsor",
    "no sponsorship",
    "not able to offer sponsorship",
    "does not offer visa sponsorship",
]

REMOTE_PHRASES = ["remote", "work from home", "wfh"]
HYBRID_PHRASES = ["hybrid"]

SENIOR_TITLE_SIGNALS = [
    "Director",
    "Head of",
    "Principal",
    "Lead",
    "Senior Manager",
    "VP",
    "Vice President",
]

# Role-category tagging rules: report section name -> keywords matched
# against job title + description (case-insensitive).
ROLE_CATEGORY_RULES = {
    "Governance Roles": ["governance"],
    "Design Authority Roles": ["design authority"],
    "Architecture Assurance Roles": ["assurance"],
    "Enterprise Architecture Roles": ["enterprise architect", "enterprise architecture"],
    "Business Architecture Roles": ["business architect", "business architecture"],
    "AI Governance Roles": ["ai governance", "responsible ai", "ai adoption", "ai feasibility"],
    "Technology Strategy Roles": ["technology strategy", "tech strategy"],
    "Transformation Leadership Roles": ["transformation"],
    "Director / Head of Architecture Roles": ["director of architecture", "head of architecture"],
}
