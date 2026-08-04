# Application Tracker

Streamlit UI over `data/applications.json`, which the job_search pipeline
auto-populates on every run: every non-"Skip" posting gets a row with its
score fields, Gemini-generated CV match/gap analysis, recruiter/hiring-
manager pass %, worth-applying verdict, recommended CV, and section-level
edit notes, ranked by priority.

You can edit **Stage** and **Notes** directly in the table -- everything
else there is pipeline-owned and gets overwritten on the next run. Moving
a row's Stage to Applied/Shortlisted/Interview/Followup/Offer/Rejected/
Withdrawn stamps that stage's date column with today's date, the first
time only -- re-selecting a stage won't overwrite when you first reached
it.

You can also add a posting the pipeline missed: the **"+ Add a posting
manually"** section at the top takes either a URL (fetched and cleaned
automatically) or pasted job description text -- fill in one, not both.
It goes through the same rule-based scoring as everything else plus one
Gemini call, and gets added regardless of how it scores (a deliberate add
isn't filtered the way auto-discovered postings are). Needs
`GEMINI_API_KEY` configured the same as the pipeline -- see below.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app/tracker.py
```

With no `GITHUB_TOKEN`/`GITHUB_REPOSITORY` set, edits save straight to the
local `data/applications.json` -- commit that file yourself like any other
change. For the manual-add feature to work locally, `GEMINI_API_KEY` needs
to be in your environment (e.g. `export $(cat .env | xargs)` after filling
in `.env` from `.env.example`).

---

## Deploy on Streamlit Community Cloud

This is the free, official way to get a persistent URL you can open from
your phone. Streamlit Cloud's filesystem is ephemeral (wiped on every
redeploy), so the app is written to detect that and commit edits back to
the repo via the GitHub Contents API instead of writing local files --
that's what the `GITHUB_TOKEN`/`GITHUB_REPOSITORY` secrets below are for.

### Step 1 — Confirm the repo is on GitHub

Already true if you're reading this from a clone -- `pribalky/searchEngine`
(or wherever you forked it), with this code on the `main` branch.

### Step 2 — Create a fine-grained GitHub token, scoped to just this repo

This is the credential the deployed app uses to save your edits back to
GitHub, since it can't write to its own (ephemeral) disk.

1. Go to **github.com** → click your avatar (top right) → **Settings**
2. Left sidebar, scroll down → **Developer settings**
3. **Personal access tokens** → **Fine-grained tokens**
4. **Generate new token**
5. Fill in:
   - **Token name**: something like `searchengine-tracker`
   - **Expiration**: your choice (90 days is the default; you'll need to
     regenerate and update the Streamlit secret when it expires)
   - **Repository access**: select **"Only select repositories"**, then
     choose `searchEngine` from the dropdown -- **not** "All repositories"
6. Scroll to **Permissions** → **Repository permissions** → find
   **Contents** → set it to **Read and write**. Leave everything else as
   "No access."
7. **Generate token** at the bottom
8. **Copy the token now** -- it's shown once (`github_pat_...`). If you
   navigate away before copying it, you'll have to generate a new one.

This token can only read/write files in this one repo. It can't touch
your other repos, your issues, or your account settings -- worth doing
this way rather than a classic all-repos token, since it's going to live
inside a third-party hosting platform's secrets store.

### Step 3 — Create the Streamlit Cloud app

1. Go to **[share.streamlit.io](https://share.streamlit.io)**
2. Sign in with GitHub (first time: authorize the "Streamlit" GitHub App
   — you can scope this to just the `searchEngine` repo when prompted,
   same minimal-access principle as the token above)
3. Click **"Create app"** (or **"New app"**)
4. Choose **"Deploy a public app from GitHub"**
5. Fill in the deploy form:
   - **Repository**: `<your-username>/searchEngine`
   - **Branch**: `main`
   - **Main file path**: `app/tracker.py`
   - App URL: Streamlit assigns one automatically (you can customize the
     subdomain here if you want something memorable)
6. **Don't click Deploy yet** -- click **"Advanced settings"** first to
   set secrets before the first boot (you can also add them after and
   just reboot the app, but doing it now saves a step)

### Step 4 — Add secrets

In Advanced settings, there's a **Secrets** text box that takes TOML.
Paste in:

```toml
GITHUB_TOKEN = "github_pat_...your token from Step 2..."
GITHUB_REPOSITORY = "your-username/searchEngine"
GEMINI_API_KEY = "AIza...your Gemini key..."
```

`GEMINI_API_KEY` is only needed if you want the manual-add feature to
work from the deployed app (recommended -- that's the point of hosting
it). Optionally add `GEMINI_MODEL = "gemini-2.5-flash"` too if you've
pinned a specific model.

**Python version**: also in Advanced settings, set it to match the
pipeline (3.12) to avoid dependency surprises.

### Step 5 — Deploy

Click **Deploy**. Streamlit Cloud clones the repo, installs
`requirements.txt`, and starts the app -- first boot typically takes a
minute or two. You'll land on a build-log screen; once it says the app is
running, you'll get a URL like `https://searchengine-tracker.streamlit.app`.

Bookmark that URL / add it to your phone's home screen -- that's your
tracker, from anywhere.

### What happens after that

- **Auto-redeploy on push.** Streamlit Cloud watches the `main` branch;
  every push (e.g. the pipeline's own scheduled commits, or you merging
  future changes) triggers a redeploy automatically. No manual step
  needed to pick up code changes.
- **The app sleeps after inactivity** (free tier). If nobody's opened it
  for a while, the next visit shows a "waking up" screen for ~30-60
  seconds before it's responsive again -- normal, not a bug.
- **Secrets survive redeploys** -- they're stored by Streamlit Cloud, not
  in the repo, so you only set them once (until the GitHub token expires
  and needs regenerating).
- **Managing the app**: from the Streamlit Cloud dashboard, the "⋮" menu
  on your app gives you Reboot, View logs, Settings (to edit secrets),
  Delete. **Logs** are the first place to look if something breaks --
  e.g. a missing/typo'd secret shows up there as a `KeyError` or similar
  on app start.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Saved" appears to work but changes vanish on next visit | `GITHUB_TOKEN`/`GITHUB_REPOSITORY` secret missing or wrong -- check it's writing to GitHub, not falling back to the (ephemeral) local file |
| `403` error on save | Token's Contents permission isn't set to "Read and write", or it's scoped to the wrong repo |
| Manual-add always fails with "GEMINI_API_KEY not set" | Secret name typo, or it wasn't added to *this* app's secrets (each Streamlit Cloud app has its own secrets store) |
| App shows old data after a pipeline run | The GitHub Actions run may not have finished/pushed yet -- the tracker reads the live file from GitHub on every page load, so a refresh after the run completes should pick it up |
