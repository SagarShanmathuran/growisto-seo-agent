# Growisto SEO Potential — Claude Code Plugin

Two skills for SEO outreach potential analysis. Built so any analyst with Claude
Code + an Ahrefs subscription can run the same analysis Growisto SEO consultants
do manually — without needing the standalone Streamlit dashboard.

**Why a plugin instead of a dashboard?**
- No LLM API costs — Claude (in your Claude Code chat) does the reasoning
- Portable — clone, install, ready to go
- Composable — chain with other Claude Code skills

---

## What's inside

```
seo-plugins/
├── .claude-plugin/plugin.json
├── commands/
│   ├── seo-find-competitors.md     →  /seo-find-competitors <url>
│   └── seo-gap-analysis.md         →  /seo-gap-analysis --client-name X --client-csv ...
└── skills/
    ├── find-competitors/           →  Skill 1: URL → ranked competitor list
    └── gap-analysis/               →  Skill 2: Keyword CSVs → SEO potential report
```

### Skill 1 — find-competitors
Input a client URL. The script fetches:
1. Ahrefs `organic-competitors` (top 15 by keyword overlap)
2. Ahrefs `site-metrics` for the client (traffic + KW count)
3. Optional: scans homepages of client + each candidate for category context
4. Sitemap-based category seeds (e.g. `/diamond/`, `/rings/` for ORRA)

It writes JSON. Then **Claude reads it and applies positioning judgement** — picking the
3 most category-aligned competitors and suggesting brands the analyst should add manually.

**Cost:** ~260 Ahrefs units per run.

### Skill 2 — gap-analysis
Input client + competitor Ahrefs keyword CSVs. The script:
1. Filters non-brand commercial+transactional intent keywords
2. Drops blog/help/resources URLs
3. Computes gap keywords (where competitors rank top 10, client doesn't)
4. Sorts by competitor's actual captured traffic
5. Computes "Big Wins" (top 3 by score) + achievable target
6. Detects competitor mis-alignment

It writes JSON. **Claude reads it, decides which keywords are in client's catalog scope**, then
the script regenerates a Word report (`report-{client}.docx`) using only the in-scope set.

**Cost:** $0 — all reasoning happens in Claude chat, no API calls.

---

## Installation

### Option A — point Claude Code at this folder directly

```bash
# Clone the parent repo (this plugin lives inside it)
git clone https://github.com/SagarShanmathuran/growisto-seo-agent.git
cd growisto-seo-agent

# Tell Claude Code to load the plugin
mkdir -p ~/.claude/plugins
ln -s "$(pwd)/seo-plugins" ~/.claude/plugins/growisto-seo
```

Then in Claude Code:
- `/plugin reload`
- The `/seo-find-competitors` and `/seo-gap-analysis` commands appear

### Option B — copy the folder into your existing `~/.claude/plugins/` directory

```bash
cp -r seo-plugins ~/.claude/plugins/growisto-seo
```

---

## Configuration

Create `seo-plugins/.env` (gitignored — never commit):

```
AHREFS_API_TOKEN=your-ahrefs-api-token-from-https://ahrefs.com/api/profile
SEARCHAPI_KEY=your-searchapi-key-optional
```

Only `AHREFS_API_TOKEN` is required. Get it from your Ahrefs subscription's API tab.

The script also reads from a `.env` in the parent repo root if present — so if you've
already configured the dashboard version, this just works.

---

## Usage

### 1. Find competitors

```
/seo-find-competitors https://locobuzz.com/ --country IN --scan
```

Claude will:
- Run the script (~260 Ahrefs units)
- Read the JSON
- Apply positioning reasoning
- Present a markdown table with top 3 picks + suggested manual additions

### 2. Pull Ahrefs CSVs

For the picks Claude recommended, manually export from your Ahrefs UI:
- Site Explorer → Organic keywords → Export CSV
- Repeat for client + each competitor

### 3. Run the gap analysis

```
/seo-gap-analysis \
    --client-name Locobuzz \
    --client-url https://locobuzz.com/ \
    --client-csv ~/Downloads/locobuzz-keywords.csv \
    --competitor "Sproutsocial:~/Downloads/sproutsocial-keywords.csv" \
    --competitor "Hootsuite:~/Downloads/hootsuite-keywords.csv" \
    --competitor "Brand24:~/Downloads/brand24-keywords.csv" \
    --business-model b2b_saas \
    --niche "social listening platform"
```

Claude will:
- Run the script (no API cost)
- Read the candidate keywords
- Decide which are in scope (their actual analyst-style call)
- Re-run with `--finalize` to generate the DOCX
- Summarise in chat with verdict + Big Wins + warnings

The DOCX lands at `/tmp/report-{slug}.docx`.

---

## How this differs from the dashboard

| Aspect | Streamlit dashboard | Plugin |
|---|---|---|
| Where it runs | A web app on Streamlit Cloud | Inside your Claude Code chat |
| Who's the LLM | Gemini API + Claude API as fallback | Claude (your chat session) |
| LLM cost | Free tier 429s common, paid Claude as fallback | $0 — your existing Claude subscription |
| Multi-user | Yes (URL + password) | One analyst at a time |
| Deployment | git push → auto-deploy | git pull → manual reload |
| Best for | Multi-analyst team workflow | Solo analyst, ad-hoc analyses |

You can use both. The dashboard for batch screening; the plugin when you want
Claude's reasoning involved interactively.

---

## Troubleshooting

**"AHREFS_API_TOKEN not set"** — create `seo-plugins/.env` (or the repo-root `.env`)
with the token.

**Script can't find pandas / requests / python-docx** — run
`pip install pandas requests python-docx beautifulsoup4 lxml` (matches the dashboard's
requirements.txt).

**CSV format errors** — Ahrefs exports two formats: comparison (UTF-16 tab-separated, has
"Previous/Current" columns) and snapshot (UTF-8 comma-separated). The loader handles both.
If your CSV has different column names, paste a header sample and we'll add the alias.

**Claude doesn't see the commands** — `/plugin list` should show `growisto-seo`. If not,
re-check the symlink/copy path and run `/plugin reload`.
