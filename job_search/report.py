"""Builds the full markdown report, mirroring the structure of the source
prompt. All qualitative content is derived from rule-based keyword overlap
(see scoring.py) -- not LLM reasoning -- and the report says so up front."""
from collections import Counter, defaultdict
from typing import List

from . import config

TABLE_COLUMNS = [
    "Posted Date",
    "Job Title",
    "Company",
    "Location",
    "Tier",
    "Visa Sponsorship",
    "Overall Fit",
    "ATS Match",
    "Recruiter Match",
    "Hiring Manager Match",
    "Interview Probability",
    "Why It Matches",
    "Key Gaps",
    "CV Version",
    "Rewrite Effort",
    "Decision",
    "Application Link",
]


def _why_it_matches(record: dict) -> str:
    posting = record["posting"]
    score = record["score"]
    matched = sorted(set(config.PROFILE_KEYWORDS) - set(score.missing_keywords))
    matched_in_jd = [
        kw for kw in matched if kw.lower() in f"{posting.title} {posting.description}".lower()
    ]
    if not matched_in_jd:
        return f"Title matches role family '{posting.role_family}'."
    return f"Role family '{posting.role_family}'; overlaps on: {', '.join(matched_in_jd[:4])}"


def _key_gaps(record: dict) -> str:
    gaps = record["score"].missing_keywords
    return ", ".join(gaps[:5]) if gaps else "None identified"


def _row(record: dict) -> List[str]:
    posting = record["posting"]
    score = record["score"]
    return [
        posting.posted_date,
        posting.title,
        posting.company,
        posting.location,
        record["sector"],
        record["visa"],
        str(score.overall_fit),
        str(score.ats_match),
        str(score.recruiter_match),
        str(score.hiring_manager_match),
        str(score.interview_probability),
        _why_it_matches(record),
        _key_gaps(record),
        score.best_cv or "New tailored version required",
        score.rewrite_effort,
        score.decision,
        posting.url,
    ]


def render_table(records: List[dict]) -> str:
    if not records:
        return "_No verified vacancies in this section._\n"
    lines = ["| " + " | ".join(TABLE_COLUMNS) + " |", "|" + "|".join(["---"] * len(TABLE_COLUMNS)) + "|"]
    for record in records:
        cells = [c.replace("|", "/").replace("\n", " ")[:200] for c in _row(record)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _sorted_master(records):
    return sorted(records, key=lambda r: (r["posting"].posted_date, r["score"].interview_probability), reverse=True)


def _section(title: str, records: List[dict]) -> str:
    return f"\n## {title}\n\n{render_table(records)}\n"


def _market_patterns(records: List[dict]) -> str:
    if not records:
        return "No verified vacancies this run -- no patterns to report."
    keyword_counter = Counter()
    missing_counter = Counter()
    role_family_scores = defaultdict(list)
    company_scores = defaultdict(list)
    cv_recommendation_counter = Counter()
    priority_48h = []

    for r in records:
        posting, score = r["posting"], r["score"]
        text = f"{posting.title} {posting.description}".lower()
        for kw in config.PROFILE_KEYWORDS:
            if kw.lower() in text:
                keyword_counter[kw] += 1
        for kw in score.missing_keywords:
            missing_counter[kw] += 1
        if posting.role_family:
            role_family_scores[posting.role_family].append(score.interview_probability)
        company_scores[posting.company].append(score.overall_fit)
        cv_recommendation_counter[score.best_cv or "New tailored version required"] += 1
        if score.decision == "Priority Apply":
            priority_48h.append(f"{posting.title} @ {posting.company} ({posting.url})")

    top_keywords = ", ".join(k for k, _ in keyword_counter.most_common(10)) or "none detected"
    top_missing = ", ".join(k for k, _ in missing_counter.most_common(10)) or "none detected"
    best_cv = cv_recommendation_counter.most_common(1)[0][0] if cv_recommendation_counter else "N/A"
    new_master_cv = (
        "Yes -- several recurring missing keywords suggest a gap no existing CV version covers well."
        if missing_counter and missing_counter.most_common(1)[0][1] >= max(3, len(records) // 4)
        else "Not yet clearly indicated by this run's data."
    )
    role_family_avg = {
        rf: sum(v) / len(v) for rf, v in role_family_scores.items() if v
    }
    best_role_family = max(role_family_avg, key=role_family_avg.get) if role_family_avg else "N/A"
    company_avg = {c: sum(v) / len(v) for c, v in company_scores.items() if v}
    top_companies = ", ".join(
        c for c, _ in sorted(company_avg.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ) or "N/A"

    lines = [
        f"1. **Patterns across the market**: {len(records)} verified vacancies this run across "
        f"{len(role_family_scores)} role families and {len(company_scores)} employers.",
        f"2. **Common keywords employers are requesting**: {top_keywords}",
        f"3. **Skills appearing most frequently** (present in your best-matching CV): "
        f"{', '.join(k for k, _ in keyword_counter.most_common(5)) or 'none'}",
        f"4. **Skills missing from your CV**: {top_missing}",
        f"5. **Which CV to use most often**: {best_cv}",
        f"6. **Whether to create a new master CV**: {new_master_cv}",
        f"7. **Role family with highest interview probability**: {best_role_family}",
        f"8. **Companies appearing most aligned**: {top_companies}",
        "9. **Vacancies to apply to within the next 48 hours**: "
        + ("; ".join(priority_48h) if priority_48h else "None this run."),
    ]
    return "\n".join(lines)


def _step8(records: List[dict]) -> str:
    high_prob = [r for r in records if r["score"].interview_probability > 70]
    if not high_prob:
        return "No vacancies exceeded 70% Interview Probability this run."

    ranked = sorted(
        high_prob,
        key=lambda r: r["score"].interview_probability / (len(r["score"].missing_keywords) + 1),
        reverse=True,
    )
    lines = []
    for r in ranked:
        posting, score = r["posting"], r["score"]
        uplift = min(25, 5 * len(score.missing_keywords))
        ats_risk = (
            f" ATS/recruiter screening risk: **HIGH** (ATS Match {score.ats_match}/100) -- "
            f"add the missing keywords before applying."
            if score.ats_match < 50
            else ""
        )
        lines.append(
            f"- **{posting.title} @ {posting.company}** (Interview Probability {score.interview_probability}/100)\n"
            f"  - Top keywords to add: {', '.join(score.missing_keywords[:10]) or 'none identified'}\n"
            f"  - Achievements to emphasise / bullets to rewrite: review manually against this JD -- "
            f"rule-based scoring cannot reliably extract CV bullet content.\n"
            f"  - Estimated tailoring uplift: +{uplift}%\n"
            f"  - Recommended CV: {score.best_cv or 'New tailored version required'} "
            f"(rewrite effort: {score.rewrite_effort}).{ats_risk}"
        )
    return "\n".join(lines)


def build_report(
    execution_date: str,
    verified_records: List[dict],
    excluded_count: int,
    cvs_loaded: int,
) -> str:
    master = _sorted_master(verified_records)
    by_fit = sorted(verified_records, key=lambda r: r["score"].overall_fit, reverse=True)[:10]
    by_interview = sorted(verified_records, key=lambda r: r["score"].interview_probability, reverse=True)[:10]
    by_newest = sorted(verified_records, key=lambda r: r["posting"].posted_date, reverse=True)[:10]

    banking = [r for r in verified_records if r["sector"] == "Banking"]
    consulting = [r for r in verified_records if r["sector"] == "Consulting"]
    visa_friendly = [r for r in verified_records if r["visa"] == "Likely"]
    remote_hybrid = [r for r in verified_records if r["work_pattern"] in ("Remote", "Hybrid")]
    stretch = [r for r in verified_records if r["stretch"] == "Stretch"]

    parts = [
        "# UK Technology Leadership Job Search Report",
        f"\n**Execution date:** {execution_date}",
        f"\n**Method:** Adzuna + Reed job-board APIs (UK-scoped), each vacancy verified by "
        f"posted-date window and a live HTTP check on the application link. Scoring is "
        f"rule-based keyword overlap against your CV(s), not LLM reasoning -- treat scores "
        f"as directional, not authoritative.",
        f"\n**Verified vacancies:** {len(verified_records)} | **Excluded (failed verification):** "
        f"{excluded_count} | **CVs loaded:** {cvs_loaded}",
        "\n## Master Table (sorted by newest, then Interview Probability)",
        render_table(master),
        _section("Top 10 Highest Fit", by_fit),
        _section("Top 10 Highest Interview Probability", by_interview),
        _section("Top 10 Newest", by_newest),
        _section("Banking Opportunities", banking),
        _section("Consulting Opportunities", consulting),
    ]

    for category in config.ROLE_CATEGORY_RULES:
        matching = [r for r in verified_records if category in r["role_categories"]]
        parts.append(_section(category, matching))

    parts.append(_section("Visa Sponsorship Friendly Roles", visa_friendly))
    parts.append(_section("Remote / Hybrid Roles", remote_hybrid))
    parts.append(_section("Strategic Stretch Roles", stretch))

    parts.append("\n## Market Analysis\n")
    parts.append(_market_patterns(verified_records))

    parts.append("\n\n## Step 8 -- Application Strategy (Interview Probability > 70%)\n")
    parts.append(_step8(verified_records))

    return "\n".join(parts) + "\n"
