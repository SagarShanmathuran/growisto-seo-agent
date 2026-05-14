# Setup — SEO Potential Analysis plugin

10-minute setup for first-time users. Skip if you already have it running.

---

## Prerequisites

You need three things on your machine:

1. **Python 3.10 or newer** — check with `python --version`. If you don't have it: https://www.python.org/downloads/
2. **Claude Code** — installed and signed in (https://claude.com/code)
3. **An Ahrefs account with API access** — you'll get the token + SearchAPI key from the person who sent you this folder

---

## Step 1 — Unzip somewhere clean

Pick a permanent location, e.g.:
- Windows: `C:\Tools\seo-plugins\`
- Mac/Linux: `~/Tools/seo-plugins/`

You should now have a folder containing:
```
seo-plugins/
├── .claude-plugin/
├── commands/
├── skills/
├── HOW-TO-USE.md
├── MASTER-PROMPT.md
├── SETUP.md  (this file)
├── requirements.txt
└── .env.example
```

---

## Step 2 — Install Python dependencies

Open a terminal in the folder above and run:

```
pip install -r requirements.txt
```

This installs pandas, requests, python-docx, beautifulsoup4, and lxml. Takes 1-2 minutes.

If you hit `ModuleNotFoundError` later, re-run this command.

---

## Step 3 — API keys (already done for you)

A `.env` file is bundled inside the ZIP with the team's shared Ahrefs + SearchAPI keys already filled in. Nothing to set up.

**But — do NOT share this `.env` outside the team.** If the Ahrefs token leaks publicly, the whole team gets locked out of the API. Treat the unzipped folder as confidential. Don't:
- Re-zip and forward to anyone outside Growisto
- Commit it to a public git repo
- Upload it to Drive folders shared with clients

If you ever lose the file or accidentally overwrite it, copy `.env.example` to `.env` and ask Sagar for the values.

---

## Step 4 — Update the path in `MASTER-PROMPT.md`

Open `MASTER-PROMPT.md` in any text editor. Use Find-and-Replace to change:

- **Find:** `C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins`
- **Replace with:** the absolute path where you unzipped this folder (e.g. `C:\Tools\seo-plugins`)

Save the file. You only do this once.

---

## Step 5 — Test it

1. Open Claude Code
2. Start a new chat
3. Copy everything between the triple-backticks in `MASTER-PROMPT.md`
4. At the top, replace `<PASTE URL HERE>` with any test URL (e.g. `https://orra.co.in`)
5. Paste into Claude Code, hit enter

Claude should:
- WebFetch the homepage
- Run the competitor finder script
- Show you 3 picks + ask for CSV file paths

If you see this, you're set up correctly.

---

## What to do next

For every website you want to analyse:

1. Open a fresh Claude Code chat
2. Paste the master prompt (with the URL filled in at the top)
3. When Claude asks, pull Ahrefs CSVs (Top Pages export — 100 rows each — is cheapest)
4. Drop the 4 file paths in chat
5. Get verdict + DOCX report

Full workflow details in `HOW-TO-USE.md`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `AHREFS_API_TOKEN not set` | You forgot Step 3 — create `.env` with the token |
| `ModuleNotFoundError: pandas` | Re-run `pip install -r requirements.txt` |
| `Could not parse <csv>` | The Ahrefs CSV might be a different format — pull a fresh one |
| Claude writes its own Python script instead of using `run.py` | The path in MASTER-PROMPT.md is wrong — re-do Step 4 |
| Insufficient export rows in Ahrefs | Use Top Pages export with 100 rows instead of Organic Keywords with 30K |

---

If something's broken and you can't figure it out, ping Sagar with the error message.
