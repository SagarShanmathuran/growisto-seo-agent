---
name: gap-analysis
description: Run an SEO gap analysis on a client's Ahrefs keyword CSV vs 1-4 competitor CSVs. Use this when the analyst has the keyword dumps in hand and wants the structured gap analysis (top opportunities, intent-filtered keywords, competitor traffic comparison, big wins). Outputs both an in-chat summary and a Word report.
---

# Gap Analysis from CSV dumps

You are running the SEO potential analysis for a client given their Ahrefs keyword CSV
and the competitor CSVs the analyst pulled in the previous step.

## When to use

- Analyst has Ahrefs keyword exports for client + 1-4 competitors
- They invoke `/seo-gap-analysis` with the file paths, OR they ask "run gap analysis on these CSVs"
- Files are typically in their Downloads folder

## What you do

### Step 1 — Run the analysis script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/gap-analysis/scripts/run.py \
    --client-name <name> \
    --client-url <url> \
    --client-csv <path> \
    --competitor "<name>:<path>" \
    --competitor "<name>:<path>" \
    [--business-model b2c_ecommerce|b2b_saas|...] \
    [--niche <hint>] \
    [--output-dir <dir>]
```

The script:
1. Loads each CSV (handles UTF-16 tab-separated AND UTF-8 comma-separated Ahrefs formats)
2. Filters to non-brand commercial+transactional intent keywords
3. Drops blog/help/resources URLs
4. Computes gap keywords (competitor ranks top-10, client doesn't)
5. Sorts by competitor's actual captured traffic (not just volume)
6. Picks Big Wins (top 3 by score)
7. Computes the achievable target (sum of competitor traffic on top 10 RELEVANT gap kws)
8. Detects competitor mis-alignment (warns when relevance coverage < 10%)

It writes `gap-analysis.json` and `report.docx` to the output dir (default `/tmp/`).

### Step 2 — YOU classify keyword relevance

This is the part where Claude (you) replaces the Gemini call from the dashboard version.

The script's JSON has `candidate_keywords` (all gap kws after intent + URL filter, BEFORE
relevance filter). Read it. For each keyword:

- Decide: would a customer searching this expect to land on the **client's** website?
- The script already did intent-filtering (commercial/transactional) — your job is **scope**:
  is this keyword in the client's product/service catalog?

Apply the analyst's mental model:

- **B2C ecommerce** — keyword must be a product the client sells (e.g., a cat-litter brand
  shouldn't be compared on "cat tree" or "burmese cat" even though both contain "cat")
- **B2B services / SaaS** — keyword must be a service the client offers (e.g., social-listening
  platform shouldn't be compared on "influencer marketing agency" — different sub-category)
- **Same vertical isn't enough** — Locobuzz vs Qoruz are both "social tech" but not peers

For each candidate, output `{"keyword": "...", "in_scope": true/false, "reason": "..."}`.
Then re-run the script with `--in-scope-keywords <path>` pointing to your JSON list.

### Step 3 — Re-run with your relevance list

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/gap-analysis/scripts/run.py \
    [...same args as Step 1...] \
    --in-scope-keywords /tmp/in-scope.json \
    --finalize
```

The script regenerates the Word report with your relevance filter applied.

### Step 4 — Summarise in chat

After the final report is written, present in chat:

1. **Verdict**: HIGH / MEDIUM / LOW potential, 2-line reasoning
2. **Top 3 Big Wins**: each with keyword, volume, comp traffic, recommended action
3. **Realistic target**: sum of top-10 win traffic
4. **Catalog scope note**: 1 line on what you understood the client sells
5. **Misalignment warning** (if any from JSON's `competitor_misalignment` field)
6. **Report path**: tell analyst where the DOCX is

## What the script does NOT do

- It does not call any LLM — Claude (you) does relevance + verdict reasoning
- It does not generate the verdict prose — you write it
- The Big Win pitches in the script are templates; refine them in chat

## Required inputs

- Client CSV: Ahrefs keyword export for client domain
- ≥1 competitor CSV: same format, for each competitor finalised in `/seo-find-competitors`

## Output format expected (chat)

```markdown
## SEO Potential: HIGH | MEDIUM | LOW

[2-line summary in Growisto analyst voice]

### 🏆 Top 3 Big Wins
1. **[keyword]** — vol X/mo, [comp] wins Y clicks/mo. Build/optimise [action].
2. ...
3. ...

### 🎯 Realistic 6-12 month target
+~Z clicks/month from top 10 in-scope keywords.

### 🧠 Catalog scope
[1-line: what client sells]

### ⚠ Misalignment warning (if present)
[surface from JSON]

### 📄 Report
`/tmp/report-{client}.docx`
```
