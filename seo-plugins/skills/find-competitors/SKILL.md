---
name: find-competitors
description: Find the right SEO competitors for a given URL. Use this when the user wants to identify category-aligned competitor brands for an SEO potential analysis. Combines Ahrefs organic-competitors API + SerpAPI on transactional keywords + site scanning of client and candidate competitors. Returns a tiered list with positioning reasoning.
---

# Find SEO Competitors

You are helping the analyst pick the **right** competitors for an SEO potential analysis. Ahrefs alone returns noisy results (retailers, aggregators, tangential brands) — your job is to filter to actual category peers.

## When to use

- User provides a URL and asks for SEO competitors
- User says something like "find competitors for X" / "/seo-find-competitors X"
- User is starting a new SEO potential analysis

## What you do

### Step 1 — Run the data-fetch script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-competitors/scripts/find.py <CLIENT_URL> [--country IN] [--limit 15]
```

The script will:
1. Fetch Ahrefs organic-competitors (~210 units)
2. Fetch client's own metrics (~50 units)
3. Classify each candidate as Brand / Retailer / Marketplace / Reference
4. Optionally scan client + competitor homepages for category context (`--scan`)

It writes a JSON file at `/tmp/seo-competitors-{slug}.json` and prints the path.

### Step 2 — Read and reason

Open the JSON. It contains:
- `client`: `{domain, traffic, keywords_total, scope_hint}`
- `candidates`: list of `{domain, type, traffic, keywords_common, dr, scan_summary}`
- `category_seeds`: top-level URL paths from client's sitemap (auto-detected)

### Step 3 — Pick top 3 with reasoning

Apply these rules **in your own reasoning** (Claude is the LLM here — no API call needed):

1. **Category positioning fit** — same competitive segment as the client?
   - Brand-vs-brand for B2C ecomm (skip retailers/marketplaces unless no brand peers)
   - Same service category for B2B
   - Drop reference/wiki/news domains
2. **Traffic ratio sweet spot** — 4×–20× the client's traffic = strong ceiling; >100× = aspirational
3. **DR proximity** — within 20 points of client's DR is realistic
4. **Niche specificity** — Locobuzz (social listening) ≠ Qoruz (influencer marketing). Same broad vertical isn't enough.

Output 3 picks ranked by relevance, each with:
- Domain
- Why it's a good fit (1 line)
- Traffic + KW overlap stats
- Confidence: 🟢 high / 🟡 medium / 🔴 low

Plus a list of any peer brands you'd recommend the analyst ADD MANUALLY that didn't appear in Ahrefs results — based on your industry knowledge of the client's category.

### Step 4 — Hand off

Tell the analyst what to do next:
- Pull Ahrefs keyword CSV for client + each picked competitor
- Run `/seo-gap-analysis <client.csv> <comp1.csv> <comp2.csv> <comp3.csv>` once they have the dumps

## Required environment

- `AHREFS_API_TOKEN` — paid Ahrefs subscription, your existing one
- `SEARCHAPI_KEY` (optional) — for SerpAPI cross-check on transactional kws

Keys load from `.env` in the plugin folder OR Claude Code's settings.

## What this skill does NOT do

- No LLM API calls — Claude (you) does the reasoning
- No DOCX generation — that's the gap-analysis skill's job
- No persistent storage — runs are one-shot, output to /tmp

## Output format expected

After Step 3, present picks as a markdown table the analyst can copy:

| # | Domain | Type | Traffic | KW Overlap | DR | Confidence | Reason |
|---|---|---|---|---|---|---|---|
| 1 | ... | ... | ... | ... | ... | ... | ... |

Then: "**Suggested manual additions** (industry peers Ahrefs missed):" with 2-3 domains.
