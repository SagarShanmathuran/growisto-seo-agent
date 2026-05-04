# Deploying the Growisto SEO Agent

Goal: a private, password-gated dashboard analysts can reach from any browser.

Recommended path: **Streamlit Community Cloud + private GitHub repo + password gate.**

---

## 1. Pre-flight checklist (do once)

✅ All sensitive files are gitignored (`.env`, `.streamlit/secrets.toml`, `agent/data/*.json`, `*.docx`).
✅ Code reads secrets via `agent.services.config.get_secret()` (works locally and in production).
✅ A password gate (`_gate()` in `streamlit_app.py`) blocks the app until `APP_PASSWORD` is supplied.

Verify nothing leaks before pushing:

```bash
git status                    # should NOT list .env or secrets.toml
grep -r "AIza" --include='*.py' .   # zero results expected
grep -r "ahrefs.*=" --include='*.py' . | grep -v config | head    # no hardcoded tokens
```

---

## 2. Create the GitHub repo

1. Go to https://github.com/new
2. Name: `growisto-seo-agent` (or whatever)
3. **Private** (do not make public — exposes the app structure)
4. Don't initialize with README — we have one
5. Copy the SSH or HTTPS URL it gives you

In the project folder:

```bash
cd "C:/Users/Sagar Shanmathuran/Downloads/history"
git init
git add .
git status      # double-check no secrets are staged
git commit -m "Initial commit — Growisto SEO Agent"
git branch -M main
git remote add origin <YOUR_REPO_URL>
git push -u origin main
```

---

## 3. Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io
2. Sign in with GitHub
3. Click **New app**
4. Pick the repo, branch (`main`), main file (`streamlit_app.py`)
5. Click **Deploy**

The first deploy will fail because secrets aren't set yet. That's expected.

---

## 4. Add secrets

1. In the Streamlit Cloud dashboard, click your app → **Settings** → **Secrets**
2. Paste contents like:

```toml
APP_PASSWORD = "pick-a-long-random-string"
AHREFS_API_TOKEN = "your-ahrefs-token"
GEMINI_API_KEY = "AIza..."
SEARCHAPI_KEY = "your-searchapi-key"
```

3. Save → app auto-redeploys with secrets loaded
4. Visit the URL (something like `https://growisto-seo-agent.streamlit.app`)
5. Sign in with the password you set

---

## 5. Share with the team

- Give analysts the URL + password
- Use a password manager (1Password, Bitwarden) to share — not Slack/email
- Rotate `APP_PASSWORD` if anyone leaves the team

---

## 6. Updating the app

```bash
git add -A && git commit -m "describe change" && git push
```

Streamlit Cloud auto-redeploys on every push to `main`. ~2 min turnaround.

---

## Notes on persistent data

The local JSON logs (`agent/data/ahrefs_usage.json`, `analyst_feedback.json`) live on Streamlit Cloud's filesystem. They **persist between session refreshes** but **reset on every redeploy** (every `git push`). For long-term tracking, plug in a real DB later.

If that becomes a problem, swap these JSON files for a free Supabase / Neon Postgres table — ~30 min of code change.

---

## Alternative: Render.com

If you want full control (custom domain, persistent disk, no redeploy data loss):

1. Push to GitHub the same way
2. Sign up at https://render.com → connect GitHub
3. New Web Service → pick the repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true`
6. Add env vars (the same ones from `.streamlit/secrets.toml.example`)
7. Cost: $7/mo for the smallest paid web service

Persistent disk: add a 1GB volume mounted at `/app/agent/data` — survives redeploys.

---

## Cost summary

| Service | Cost | Notes |
|---|---|---|
| Streamlit Community Cloud | Free | 1 GB RAM, public URL, redeploys on push |
| GitHub private repo | Free | Up to 3 collaborators on free tier |
| Ahrefs (your existing plan) | ~₹40,000/mo | 400K units/month, ~20% used by this dashboard |
| Gemini API | Free | 1,500 reqs/day on free tier — enough for 60 sites/week |
| SearchAPI.io | Existing plan | Only used when Ahrefs is unconfigured |
