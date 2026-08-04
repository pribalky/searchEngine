# UK Technology Leadership Job Search Pipeline

Finds, verifies, scores, and reports on live UK technology-leadership
vacancies, tailored to an Enterprise/Solution/Business Architecture,
Architecture Governance, and Technology Strategy background.

## How it works

1. **Discovery** -- searches the [Adzuna](https://developer.adzuna.com/) and
   [Reed](https://www.reed.co.uk/developers/jobseeker) UK job-board APIs
   across ~30 role families (Enterprise Architect, Architecture Governance,
   Technology Strategy Lead, AI Governance, etc).
2. **Dedupe** -- merges the same role when it appears via both sources.
3. **Verify** -- drops anything whose posted date is older than 45 days, or
   whose application link doesn't resolve over HTTP. This is a real check,
   not an LLM guess, so vacancies in the report are genuinely live.
4. **Score** -- rule-based keyword-overlap scoring against your CV(s): ATS
   Match, Recruiter Match, Hiring Manager Match, Overall Fit, Interview
   Probability, missing keywords, recommended CV version, and a
   Priority Apply/Apply/Skip decision. This is heuristic, not true
   reasoning -- treat scores as directional.
5. **Report** -- a full markdown report (master table, top-10 breakdowns,
   14 category sections, market analysis, and an application-strategy
   section) is written to `reports/YYYY-MM-DD.md` and posted as a GitHub
   Issue.
6. **State** -- `data/seen_jobs.json` tracks previously seen jobs so they're
   re-validated (not just re-announced) on later runs, and so the pipeline
   can enforce an "every other day" minimum gap between runs regardless of
   how often the workflow itself is triggered.

### Known MVP scope (see `/root/.claude/plans/tingly-leaping-puzzle.md` for full rationale)

- Discovery is via job-board APIs, not scraping each named employer's own
  careers site -- broader coverage of UK tech-leadership roles generally,
  tagged (not filtered) by whether the employer is on your named
  Banking/Consulting priority list (`job_search/config.py`).
- Scoring is rule-based keyword overlap, not an LLM. Qualitative fields like
  "why it matches" and CV bullet rewrites are keyword-derived, not reasoned.
  `job_search/scoring.py` is isolated so it can be swapped for Claude-API
  scoring later.

## Setup

### 1. Get free API keys

- **Adzuna**: sign up at https://developer.adzuna.com/ -- gives you an
  `app_id` and `app_key`.
- **Reed**: sign up at https://www.reed.co.uk/developers/jobseeker -- gives
  you an API key (used as the HTTP Basic Auth username).

### 2. Add them as GitHub Actions secrets

In the repo: **Settings -> Secrets and variables -> Actions -> New repository secret**

- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `REED_API_KEY`

(`GITHUB_TOKEN` is provided automatically by Actions -- no setup needed.)

### 3. Add your CVs

Drop your CV versions as plain text or Markdown files into `cv/` (see
`cv/README.md`). The pipeline runs without them, but scoring and CV
recommendations are only meaningful once they're present.

### 4. Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys, then `export $(cat .env | xargs)`
python -m job_search.main --dry-run
```

Or, with no keys at all, run the bundled fixture demo:

```bash
python -m job_search.main --fixtures --dry-run --force
```

### 5. Run in GitHub Actions

Once secrets and CVs are in place, trigger the workflow manually from the
**Actions** tab (`Job Search Pipeline` -> **Run workflow**) to confirm it
works end-to-end and posts a report issue.

### 6. Enable the every-other-day schedule

Edit `.github/workflows/job_search.yml` and uncomment the `schedule:`
block. The pipeline self-checks elapsed time since the last successful run
(via `data/seen_jobs.json`), so the cron cadence just needs to be at least
as frequent as your desired gap -- it won't spam more often than that.

### 7. (Optional) LLM analysis + application tracker

Add a `GEMINI_API_KEY` (Actions secret, or your local `.env`) and every run
also enriches new postings with Gemini-generated CV match/gap analysis,
recruiter/hiring-manager pass %, a worth-applying verdict, recommended CV,
and section-level edit notes, upserted into `data/applications.json` (only
for postings not already tracked, so repeat runs don't re-spend on the
same backlog). Without the key the pipeline runs exactly as before --
tracker rows just get no LLM fields.

View and update it (stage, notes) with the Streamlit app:

```bash
streamlit run app/tracker.py
```

See `app/README.md` for deploying it (e.g. Streamlit Community Cloud) so
you can update application status from your phone.

## Tests

```bash
pip install pytest
pytest tests/ -v
```

Tests use mocked HTTP responses and bundled fixture data, so they run
without any API keys or network access.
