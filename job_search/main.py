"""CLI entrypoint.

Usage:
  python -m job_search.main --dry-run
  python -m job_search.main --post-issue
  python -m job_search.main --fixtures --dry-run   # no API keys needed, demo mode
"""
import argparse
import json
import os
import sys
from dataclasses import replace

import requests

from . import config, pipeline, sponsors
from .sources.adzuna import AdzunaClient
from .sources.reed import ReedClient
from .sources.workday import WorkdayClient
from .sources.base import JobPosting

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CV_DIR = os.path.join(REPO_ROOT, "cv")
STATE_PATH = os.path.join(REPO_ROOT, "data", "seen_jobs.json")
APPLICATIONS_PATH = os.path.join(REPO_ROOT, "data", "applications.json")
REPORTS_DIR = os.path.join(REPO_ROOT, "reports")
FIXTURES_DIR = os.path.join(REPO_ROOT, "tests", "fixtures")

GITHUB_ISSUE_BODY_LIMIT = 60000  # GitHub's actual cap is 65536; leave headroom


def build_live_sources():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    reed_key = os.environ.get("REED_API_KEY")
    missing = [
        name
        for name, val in [("ADZUNA_APP_ID", app_id), ("ADZUNA_APP_KEY", app_key), ("REED_API_KEY", reed_key)]
        if not val
    ]
    if missing:
        print(
            f"Missing environment variable(s): {', '.join(missing)}. "
            "Set them (see .env.example) or run with --fixtures for a demo run.",
            file=sys.stderr,
        )
        sys.exit(1)

    adzuna = AdzunaClient(app_id, app_key)
    reed = ReedClient(reed_key)

    def adzuna_search(keyword):
        return adzuna.search(keyword, max_days_old=config.MAX_POSTING_AGE_DAYS)

    def reed_search(keyword):
        return reed.search(keyword)

    workday_sources = [_make_workday_search(employer) for employer in config.WORKDAY_EMPLOYERS]

    return [adzuna_search, reed_search] + workday_sources


def _make_workday_search(employer_config):
    client = WorkdayClient(
        tenant=employer_config["tenant"],
        host=employer_config["host"],
        site=employer_config["site"],
        company_name=employer_config["name"],
    )

    def search(keyword):
        return client.search(keyword)

    return search


def build_fixture_sources():
    """Demo mode: replays saved fixture JSON regardless of keyword, so the
    pipeline can be exercised end-to-end without real API keys."""

    def load(path):
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        return [JobPosting(**item) for item in items]

    adzuna_path = os.path.join(FIXTURES_DIR, "adzuna_sample.json")
    reed_path = os.path.join(FIXTURES_DIR, "reed_sample.json")

    def adzuna_search(keyword):
        return [replace(p, role_family=keyword) for p in load(adzuna_path)]

    def reed_search(keyword):
        return [replace(p, role_family=keyword) for p in load(reed_path)]

    return [adzuna_search, reed_search]


def fetch_live_sponsor_names():
    return sponsors.fetch_sponsor_names(session=requests.Session(), timeout=30)


def post_github_issue(title: str, body: str, report_path: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN / GITHUB_REPOSITORY not set; skipping issue creation.", file=sys.stderr)
        return

    if len(body) > GITHUB_ISSUE_BODY_LIMIT:
        body = (
            body[:GITHUB_ISSUE_BODY_LIMIT]
            + f"\n\n... truncated. Full report committed at `{os.path.relpath(report_path, REPO_ROOT)}`."
        )

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"title": title, "body": body},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Created issue: {resp.json().get('html_url')}")


def print_llm_spend(spend: dict) -> None:
    """Per-run Gemini spend summary (see llm_analysis.summarize_spend),
    printed to stdout so it shows up directly in the GitHub Actions log --
    no need to dig into data/applications.json's llm_spend_log to see
    what a run cost. Cost is an estimate against placeholder pricing; see
    .env.example for the override env vars."""
    if spend is None:
        return  # applications_path wasn't set for this run
    if spend["calls"] == 0:
        print("Gemini spend this run: no new postings to analyze.")
        return
    print(
        f"Gemini spend this run: {spend['calls']} call(s), {spend['errors']} error(s), "
        f"{spend['prompt_tokens']:,} prompt + {spend['output_tokens']:,} output tokens, "
        f"~${spend['estimated_cost_usd']:.4f} estimated "
        "(placeholder pricing -- verify against your Gemini console; see .env.example)."
    )


def main():
    parser = argparse.ArgumentParser(description="UK Tech Leadership job search pipeline")
    parser.add_argument("--dry-run", action="store_true", help="run the pipeline but do not post a GitHub issue")
    parser.add_argument("--post-issue", action="store_true", help="post the report as a GitHub issue")
    parser.add_argument("--force", action="store_true", help="bypass the every-other-day gap check")
    parser.add_argument("--fixtures", action="store_true", help="use bundled fixture data instead of live APIs")
    args = parser.parse_args()

    sources = build_fixture_sources() if args.fixtures else build_live_sources()
    # Fixture/demo mode stays fully network-free; the real sponsor registry
    # lookup only runs against live data.
    sponsor_names_fetcher = None if args.fixtures else fetch_live_sponsor_names

    # Fixture/demo mode never spends real Gemini quota, same rationale as
    # the sponsor-fetcher swap above: fixture postings are canned data, so
    # an LLM call against them buys no signal.
    gemini_api_key = None if args.fixtures else os.environ.get("GEMINI_API_KEY")

    result = pipeline.run(
        cv_dir=CV_DIR,
        state_path=STATE_PATH,
        reports_dir=REPORTS_DIR,
        sources=sources,
        force=args.force,
        sponsor_names_fetcher=sponsor_names_fetcher,
        applications_path=APPLICATIONS_PATH,
        gemini_api_key=gemini_api_key,
    )

    if result["skipped"]:
        print(f"Skipped: {result['reason']}")
        return

    print(f"Verified {result['verified_count']} vacancies, excluded {result['excluded_count']}.")
    if result["fetch_errors"]:
        print(f"{len(result['fetch_errors'])} fetch error(s): {result['fetch_errors']}", file=sys.stderr)
    print(f"Report written to {result['report_path']}")
    print_llm_spend(result.get("llm_spend"))

    if args.post_issue:
        post_github_issue(
            title=f"Job Search Report -- {result['report_path'].split('/')[-1].removesuffix('.md')}",
            body=result["report_markdown"],
            report_path=result["report_path"],
        )


if __name__ == "__main__":
    main()
