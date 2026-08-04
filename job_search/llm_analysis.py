"""Gemini-backed qualitative JD analysis: a CV match/gap narrative, the
model's own recruiter/hiring-manager pass-percentage estimate, a
worth-applying verdict, which CV to use, and section-level CV edit notes.

Kept isolated from scoring.py -- that module's docstring already
anticipated "a Claude/Gemini API-backed scorer later"; this is that
scorer, feeding the application tracker (see applications.py) rather than
replacing scoring.py's rule-based report columns.

Gated by the caller to run only on postings that already cleared the
rule-based Skip/Stretch bar (same set the report shows) and only on
postings the tracker hasn't already analyzed (see analyze_many), so API
spend scales with new postings per run, not with the accumulated backlog.

The model name is intentionally read from GEMINI_MODEL at import time
(override via env var) rather than hardcoded to one string -- confirm the
current model name in your Gemini console before relying on the default.
"""
import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Placeholder pricing (USD per 1M tokens) -- these are NOT verified against
# current Gemini billing and exist only so per-run spend logging has a
# number to show from the first live run. Check your Gemini console/
# billing page for the actual rate for GEMINI_MODEL and override via env
# vars if it differs; the estimate is only as good as these two values.
INPUT_PRICE_PER_MTOK = float(os.environ.get("GEMINI_INPUT_PRICE_PER_MTOK", "0.30"))
OUTPUT_PRICE_PER_MTOK = float(os.environ.get("GEMINI_OUTPUT_PRICE_PER_MTOK", "2.50"))

SYSTEM_INSTRUCTION = (
    "You are assisting a UK technology-leadership job seeker (Enterprise/"
    "Solution/Business Architecture, Architecture Governance, Technology "
    "Strategy background). Given a job description and their CV variants, "
    "give a grounded, honest assessment -- real overlap and real gaps, not "
    "generic encouragement. Base every judgement on the actual text "
    "provided, not assumptions about the role or company."
)


def _response_schema(cv_names: List[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "cv_match_gap": {
                "type": "string",
                "description": "2-3 sentences on genuine overlap and genuine gaps between the CV and this JD.",
            },
            "recruiter_pass_pct": {
                "type": "integer",
                "description": "0-100 estimate of the odds a recruiter keyword/title screen passes this CV through.",
            },
            "hiring_manager_pass_pct": {
                "type": "integer",
                "description": "0-100 estimate of the odds a hiring manager reading the full CV would shortlist for interview.",
            },
            "worth_applying": {"type": "string", "enum": ["Yes", "Maybe", "No"]},
            "worth_applying_reason": {"type": "string", "description": "One sentence justifying the verdict."},
            "cv_to_use": {
                "type": "string",
                "enum": list(cv_names),
                "description": "Which of the provided CV variants is the best starting point for this application.",
            },
            "recommendation": {
                "type": "string",
                "description": "Concise, section-by-section edit notes for tailoring the chosen CV to this JD.",
            },
        },
        "required": [
            "cv_match_gap",
            "recruiter_pass_pct",
            "hiring_manager_pass_pct",
            "worth_applying",
            "worth_applying_reason",
            "cv_to_use",
            "recommendation",
        ],
    }


@dataclass
class LLMAnalysis:
    cv_match_gap: str
    recruiter_pass_pct: Optional[int]
    hiring_manager_pass_pct: Optional[int]
    worth_applying: str
    worth_applying_reason: str
    cv_to_use: str
    recommendation: str
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


def _build_prompt(title: str, company: str, description: str, cvs: Dict[str, str]) -> str:
    cv_block = "\n\n".join(f"--- CV: {name} ---\n{text}" for name, text in cvs.items())
    return (
        f"Job title: {title}\nCompany: {company}\n\nJob description:\n{description}\n\n"
        f"Candidate's CV variants:\n{cv_block}\n\n"
        "Assess this specific candidate against this specific job."
    )


def analyze(
    title: str,
    company: str,
    description: str,
    cvs: Dict[str, str],
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    client_factory=None,
) -> LLMAnalysis:
    """Returns a best-effort LLMAnalysis. Never raises -- a Gemini failure
    (missing key, rate limit, network error, malformed response) degrades
    to an error-flagged result rather than breaking the pipeline run, the
    same resilience pattern as the sponsor-registry fetch in pipeline.py."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return LLMAnalysis("", None, None, "", "", "", "", error="GEMINI_API_KEY not set")
    if not cvs:
        return LLMAnalysis("", None, None, "", "", "", "", error="no CVs loaded")

    try:
        from google import genai  # deferred: optional dependency, only needed on this path
        from google.genai import types

        client = client_factory() if client_factory else genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=_response_schema(list(cvs.keys())),
        )
        response = client.models.generate_content(
            model=model,
            contents=_build_prompt(title, company, description, cvs),
            config=config,
        )
        payload = json.loads(response.text)
        usage = getattr(response, "usage_metadata", None)
        return LLMAnalysis(
            cv_match_gap=payload["cv_match_gap"],
            recruiter_pass_pct=int(payload["recruiter_pass_pct"]),
            hiring_manager_pass_pct=int(payload["hiring_manager_pass_pct"]),
            worth_applying=payload["worth_applying"],
            worth_applying_reason=payload["worth_applying_reason"],
            cv_to_use=payload["cv_to_use"],
            recommendation=payload["recommendation"],
            prompt_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
            total_tokens=getattr(usage, "total_token_count", None) if usage else None,
        )
    except Exception as exc:  # noqa: BLE001 -- LLM issues must never crash the pipeline run
        return LLMAnalysis("", None, None, "", "", "", "", error=str(exc))


MANUAL_SYSTEM_INSTRUCTION = (
    "You are assisting a UK technology-leadership job seeker (Enterprise/"
    "Solution/Business Architecture, Architecture Governance, Technology "
    "Strategy background). You will be given raw text -- either a fetched "
    "job-posting web page (which may include navigation, footer, cookie-"
    "banner, and other boilerplate you should ignore) or a job description "
    "pasted directly by the candidate. First decide whether it actually "
    "contains a real job posting to assess; if not, set extraction_ok to "
    "false and give a one-sentence reason why in extraction_note. If it "
    "does, extract the job title, employer name, and a concise summary of "
    "the role, then give a grounded, honest assessment of fit against the "
    "candidate's CV variants -- real overlap and real gaps, not generic "
    "encouragement. Base every judgement on the actual text provided."
)


def _extraction_response_schema(cv_names: List[str]) -> dict:
    schema = _response_schema(cv_names)
    schema["properties"] = {
        "extraction_ok": {
            "type": "boolean",
            "description": "True only if the provided text clearly contains a real job posting (a title, an employer, and role content) to assess.",
        },
        "extraction_note": {
            "type": "string",
            "description": "If extraction_ok is false, a one-sentence reason why (e.g. 'no job description found in this text', 'page appears to require login'). Empty string if extraction_ok is true.",
        },
        "title": {"type": "string", "description": "The job title, or empty string if extraction_ok is false."},
        "company": {"type": "string", "description": "The employer name, or empty string if extraction_ok is false."},
        "description_summary": {
            "type": "string",
            "description": "A concise plain-text summary of the role's responsibilities and requirements (150-300 words), or empty string if extraction_ok is false.",
        },
        **schema["properties"],
    }
    schema["required"] = [
        "extraction_ok",
        "extraction_note",
        "title",
        "company",
        "description_summary",
    ] + schema["required"]
    return schema


@dataclass
class ManualPostingResult:
    extraction_ok: bool
    extraction_note: str
    title: str
    company: str
    description_summary: str
    cv_match_gap: str
    recruiter_pass_pct: Optional[int]
    hiring_manager_pass_pct: Optional[int]
    worth_applying: str
    worth_applying_reason: str
    cv_to_use: str
    recommendation: str
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


def _failed_manual_result(error: str) -> ManualPostingResult:
    return ManualPostingResult(
        extraction_ok=False,
        extraction_note="",
        title="",
        company="",
        description_summary="",
        cv_match_gap="",
        recruiter_pass_pct=None,
        hiring_manager_pass_pct=None,
        worth_applying="",
        worth_applying_reason="",
        cv_to_use="",
        recommendation="",
        error=error,
    )


def extract_and_analyze(
    source_text: str,
    cvs: Dict[str, str],
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    client_factory=None,
) -> ManualPostingResult:
    """Like analyze(), but for text of unknown shape (a fetched web page or
    a pasted JD) rather than a job-board API's already-structured title/
    company/description -- one Gemini call both extracts those fields and
    runs the same fit assessment. Never raises; extraction failure (no
    real posting found in the text) is a first-class, user-visible outcome
    via extraction_ok/extraction_note, not an exception -- arbitrary URLs
    and pasted text are far more likely to fail cleanly here than a
    job-board API ever is."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return _failed_manual_result("GEMINI_API_KEY not set")
    if not cvs:
        return _failed_manual_result("no CVs loaded")
    if not source_text or not source_text.strip():
        return _failed_manual_result("no source text provided")

    try:
        from google import genai  # deferred: optional dependency, only needed on this path
        from google.genai import types

        client = client_factory() if client_factory else genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=MANUAL_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=_extraction_response_schema(list(cvs.keys())),
        )
        cv_block = "\n\n".join(f"--- CV: {name} ---\n{text}" for name, text in cvs.items())
        prompt = f"Source text:\n{source_text}\n\nCandidate's CV variants:\n{cv_block}"
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        payload = json.loads(response.text)
        usage = getattr(response, "usage_metadata", None)
        return ManualPostingResult(
            extraction_ok=bool(payload["extraction_ok"]),
            extraction_note=payload.get("extraction_note", ""),
            title=payload.get("title", ""),
            company=payload.get("company", ""),
            description_summary=payload.get("description_summary", ""),
            cv_match_gap=payload.get("cv_match_gap", ""),
            recruiter_pass_pct=payload.get("recruiter_pass_pct"),
            hiring_manager_pass_pct=payload.get("hiring_manager_pass_pct"),
            worth_applying=payload.get("worth_applying", ""),
            worth_applying_reason=payload.get("worth_applying_reason", ""),
            cv_to_use=payload.get("cv_to_use", ""),
            recommendation=payload.get("recommendation", ""),
            prompt_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
            total_tokens=getattr(usage, "total_token_count", None) if usage else None,
        )
    except Exception as exc:  # noqa: BLE001 -- must never crash the caller over LLM/parsing issues
        return _failed_manual_result(str(exc))


def analyze_many(
    eligible: List[dict],
    cvs: Dict[str, str],
    already_analyzed_keys,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    client_factory=None,
) -> Dict[str, dict]:
    """Runs analyze() only for postings not already present in the
    tracker -- see module docstring for why. Returns {job_key: asdict(LLMAnalysis)}."""
    results = {}
    for record in eligible:
        posting = record["posting"]
        if posting.key in already_analyzed_keys:
            continue
        result = analyze(
            posting.title,
            posting.company,
            posting.description,
            cvs,
            api_key=api_key,
            model=model,
            client_factory=client_factory,
        )
        results[posting.key] = asdict(result)
    return results


def estimate_cost_usd(prompt_tokens: int, output_tokens: int) -> float:
    return prompt_tokens / 1_000_000 * INPUT_PRICE_PER_MTOK + output_tokens / 1_000_000 * OUTPUT_PRICE_PER_MTOK


def summarize_spend(results: Dict[str, dict]) -> dict:
    """Aggregates one run's analyze_many() output into a spend summary --
    every analyzed posting counts toward `calls` (so a spike in `errors`
    is visible even when token/cost totals look low), but only successful
    calls contribute tokens since a result that errored before a response
    came back has none to sum."""
    prompt_tokens = sum(r.get("prompt_tokens") or 0 for r in results.values())
    output_tokens = sum(r.get("output_tokens") or 0 for r in results.values())
    total_tokens = sum(r.get("total_tokens") or 0 for r in results.values())
    return {
        "calls": len(results),
        "errors": sum(1 for r in results.values() if r.get("error")),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(estimate_cost_usd(prompt_tokens, output_tokens), 6),
    }
