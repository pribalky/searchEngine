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
]

# Excluded from ROLE_FAMILIES: "Product Owner", "Program Manager", "Process
# Analyst" were in the original prompt's list but are generic job titles
# used across the entire UK market, not specific to an architecture/
# governance background. Searching them broadened results ~10x while
# adding almost no relevant matches (a live run scored 86% of the results
# they contributed as "Skip") -- directly against the "optimise for
# interview probability, not job count" objective.

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
    # Added from real usage patterns in the user's own CVs, rather than
    # guessed generically -- these are phrases that actually recur across
    # their CV variants (architecture governance, product ownership).
    "Feasibility Assessment",
    "Impact Assessment",
    "Governance Controls",
    "Solution Design",
    "Architecture Review",
    "Product Ownership",
    "Definition of Ready",
    "Delivery Governance",
    "Technology Risk",
    "Architecture Standards",
]

# Partial credit given when a JD keyword only appears in a CV's job-title
# text (e.g. a title mentioning "Design Authority") but not backed by any
# responsibility/achievement bullet. Full credit (1.0) requires the
# keyword to show up in demonstrated responsibility text instead --
# titles alone are a weaker, less trustworthy signal of real experience.
CV_TITLE_MATCH_WEIGHT = 0.25

# Overall Fit blend weights. ATS Match and Hiring Manager Match are both
# responsibility-weighted (see CV_TITLE_MATCH_WEIGHT and score_posting);
# Recruiter Match is a pure title-to-title comparison, kept small so a
# title mismatch alone (common when a formal job title undersells actual
# scope) can't dominate the score. Semantic Match (see semantic.py) is a
# TF-IDF/cosine-similarity signal that catches paraphrased overlap the
# literal fixed-keyword matching above misses entirely (e.g. "established
# governance controls" vs "define delivery gate criteria" share no exact
# phrase but do share weighted vocabulary) -- weighted equally alongside
# ats/hiring_manager since it's the closest thing to real JD matching
# this rule-based pipeline does.
OVERALL_FIT_WEIGHTS = {
    "ats": 0.30,
    "recruiter": 0.10,
    "hiring_manager": 0.30,
    "semantic": 0.30,
}

# Only postings that are either fully remote, or based in/near one of
# these locations, are worth surfacing -- a "Hybrid" role still requires
# an office presence, so it only counts if that office is here too.
ACCEPTABLE_LOCATIONS = ["Edinburgh", "Glasgow", "Scotland"]

# Postings requiring a bigger seniority jump than this are excluded from
# the report entirely (still scored/tracked in state, just not shown --
# same treatment as a "Skip" decision). None/unclear gap is still allowed
# through, since that just means the title couldn't be confidently
# classified, not that it's necessarily a big stretch.
MAX_ACCEPTABLE_SENIORITY_GAP = 2

# Title-keyword exclusion list: security/infrastructure roles (the
# original ask) plus pure IC software-engineering roles that pass the
# architecture-anchor gate on incidental keyword overlap but aren't
# genuinely architecture/governance/leadership positions. Matched with
# word boundaries (see tagging.is_excluded_title) so e.g. "Software
# Engineer" doesn't false-positive on "Software Engineering" as a
# department/discipline name in a legitimate leadership title.
EXCLUDED_TITLE_KEYWORDS = [
    "Security Architect",
    "Security Engineer",
    "Security Analyst",
    "Cyber Security",
    "Infrastructure Engineer",
    "Infrastructure Architect",
    "Infrastructure Lead",
    "Network Engineer",
    "Network Architect",
    "DevOps",
    "Site Reliability",
    "SRE",
    "Software Engineer",
    "Software Developer",
    "Full Stack Developer",
    "Full-Stack Developer",
    "Backend Developer",
    "Frontend Developer",
    "Python Developer",
    "Java Developer",
    "DBA",
    "Database Administrator",
    "Data Modeller",
    "QA Engineer",
    "Test Engineer",
    "Salesforce Developer",
    "Salesforce Engineer",
]

# Vacancies older than this are excluded regardless of source.
MAX_POSTING_AGE_DAYS = 45

# A posting with fewer days left than this before it ages out of the
# verification window is flagged as urgent -- the closest proxy available
# to "apply before this goes stale" since job boards don't expose real
# application deadlines.
URGENT_DAYS_THRESHOLD = 10

# Seniority ladder for architecture-track titles, ordered low to high.
# Matched against job titles only (descriptions are too noisy -- "reports
# to the Head of Engineering" would falsely inflate level). Checked from
# the highest level down so a compound title like "Head of Enterprise
# Architecture" resolves to the more senior descriptor ("Head of") rather
# than the lower one ("Enterprise Architecture") it also contains.
#
# Calibrated against the user's actual current role (Associate Architect)
# rather than a generic ladder: their title reads junior but the
# responsibilities already sit at Architect/Solution Architect/Business
# Architect level, so those are grouped as the same (current) level.
SENIORITY_LADDER = {
    0: ["Associate Architect", "Solution Architect", "Business Architect", "Architect"],
    1: ["Senior Architect", "Lead Architect", "Principal Architect"],
    2: ["Enterprise Architect", "Domain Architect"],
    3: ["Head of Architecture", "Director of Architecture", "Head of", "Director"],
    4: ["VP", "Vice President"],
}
CURRENT_SENIORITY_LEVEL = 0

# Points shaved off Interview Probability per seniority level above the
# user's current one. Deliberately modest (not a hard veto): a bigger
# title doesn't always mean bigger real responsibilities, so a 2-level
# jump should score lower, not vanish from Priority Apply/Apply entirely.
SENIORITY_LEVEL_PENALTY = 9

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
    "Senior Manager",
    "VP",
    "Vice President",
]
# "Lead" was deliberately dropped: as a single generic word it appears in
# almost any CV ("led a team", "technical leadership") and any job title
# ("Technical Lead", "Lead Data Engineer"), so it inflated recruiter-match
# scores for roles with nothing to do with architecture/governance.

# A vacancy can't be a genuine architecture/governance match without at
# least one of these appearing -- used as a hard gate on Priority
# Apply/Apply decisions so generic engineering-leadership titles (e.g.
# "Technical Motor Claims Lead") can't outscore real architecture roles
# just from incidental keyword overlap elsewhere in the JD.
CORE_ANCHOR_KEYWORDS = [
    "Architect",
    "Architecture",
    "Design Authority",
    "Technology Strategy",
    "Technology Governance",
    "AI Governance",
    "Business Architecture",
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
