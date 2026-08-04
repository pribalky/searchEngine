# Application Tracker

Streamlit UI over `data/applications.json`, which the job_search pipeline
auto-populates on every run: every non-"Skip" posting gets a row with its
score fields, Gemini-generated CV match/gap analysis, recruiter/hiring-
manager pass %, worth-applying verdict, recommended CV, and section-level
edit notes, ranked by priority. This app only edits **Stage** and
**Notes** -- everything else is pipeline-owned and gets overwritten on the
next run.

Moving a row's Stage to Applied/Shortlisted/Interview/Followup/Offer/
Rejected/Withdrawn stamps that stage's date column with today's date, the
first time only -- re-selecting a stage won't overwrite when you first
reached it.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app/tracker.py
```

With no `GITHUB_TOKEN`/`GITHUB_REPOSITORY` set, edits save straight to the
local `data/applications.json` -- commit that file yourself like any other
change.

## Deploy on Streamlit Community Cloud

Streamlit Cloud's filesystem is ephemeral (wiped on every redeploy), so
local-file writes wouldn't persist. Instead, set two **app secrets**
(Streamlit Cloud dashboard -> your app -> Settings -> Secrets) and the app
commits edits back to the repo via the GitHub Contents API:

```toml
GITHUB_TOKEN = "github_pat_..."
GITHUB_REPOSITORY = "your-username/searchEngine"
```

**Token scope -- keep it minimal.** Create a **fine-grained** personal
access token (GitHub -> Settings -> Developer settings -> Fine-grained
tokens), scoped to:
- **Only this repository** (not "All repositories")
- **Contents: Read and write** permission, nothing else

This token can only read/write files in this one repo -- it can't touch
your other repos, issues, or account settings. Treat it as a secret same
as the Adzuna/Reed/Gemini keys; don't commit it, don't paste it anywhere
but the Streamlit secrets panel.

1. Push this repo to GitHub (already done if you're reading this from a
   clone).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app
   pointed at this repo, branch, and `app/tracker.py` as the entrypoint.
3. Add the two secrets above.
4. Deploy. The tracker reads/writes `data/applications.json` in this repo
   on every save, so it stays in sync with what the pipeline populates on
   its scheduled runs.
