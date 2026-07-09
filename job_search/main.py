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

from . import config, pipeline
from .sources.adzuna import AdzunaClient
from .sources.reed import ReedClient
from .sources.base import JobPosting

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CV_DIR = os.path.join(REPO_ROOT, "cv")
STATE_PATH = os.path.join(REPO_ROOT, "data", "seen_jobs.json")
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

    return [adzuna_search, reed_search]


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


def main():
    parser = argparse.ArgumentParser(description="UK Tech Leadership job search pipeline")
    parser.add_argument("--dry-run", action="store_true", help="run the pipeline but do not post a GitHub issue")
    parser.add_argument("--post-issue", action="store_true", help="post the report as a GitHub issue")
    parser.add_argument("--force", action="store_true", help="bypass the every-other-day gap check")
    parser.add_argument("--fixtures", action="store_true", help="use bundled fixture data instead of live APIs")
    args = parser.parse_args()

    sources = build_fixture_sources() if args.fixtures else build_live_sources()

    result = pipeline.run(
        cv_dir=CV_DIR,
        state_path=STATE_PATH,
        reports_dir=REPORTS_DIR,
        sources=sources,
        force=args.force,
    )

    if result["skipped"]:
        print(f"Skipped: {result['reason']}")
        return

    print(f"Verified {result['verified_count']} vacancies, excluded {result['excluded_count']}.")
    if result["fetch_errors"]:
        print(f"{len(result['fetch_errors'])} fetch error(s): {result['fetch_errors']}", file=sys.stderr)
    print(f"Report written to {result['report_path']}")

    if args.post_issue:
        post_github_issue(
            title=f"Job Search Report -- {result['report_path'].split('/')[-1].removesuffix('.md')}",
            body=result["report_markdown"],
            report_path=result["report_path"],
        )


if __name__ == "__main__":
    main()
