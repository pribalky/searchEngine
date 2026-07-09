from . import config


def tag_sector(company: str) -> str:
    company_lower = (company or "").lower()
    for name in config.BANKING_EMPLOYERS:
        if name.lower() in company_lower:
            return "Banking"
    for name in config.CONSULTING_EMPLOYERS:
        if name.lower() in company_lower:
            return "Consulting"
    return "Other"


def is_named_employer(company: str) -> bool:
    return tag_sector(company) in ("Banking", "Consulting")


def tag_role_categories(title: str, description: str):
    text = f"{title} {description}".lower()
    return [
        category
        for category, keywords in config.ROLE_CATEGORY_RULES.items()
        if any(kw in text for kw in keywords)
    ]


def tag_work_pattern(description: str) -> str:
    text = (description or "").lower()
    if any(p in text for p in config.HYBRID_PHRASES):
        return "Hybrid"
    if any(p in text for p in config.REMOTE_PHRASES):
        return "Remote"
    return "Unknown"


def tag_visa_sponsorship(description: str) -> str:
    text = (description or "").lower()
    if any(p in text for p in config.VISA_NEGATIVE_PHRASES):
        return "Unlikely"
    if any(p in text for p in config.VISA_POSITIVE_PHRASES):
        return "Likely"
    return "Unclear"


def tag_career_stretch(title: str) -> str:
    title_lower = (title or "").lower()
    stretch_signals = ["director", "head of", "vp", "vice president"]
    if any(s in title_lower for s in stretch_signals):
        return "Stretch"
    return "Core"
