# How to use the SEO plugins (without slash commands)

Until the plugin is added to the Growisto org marketplace, just copy-paste these
prompts into a fresh Claude Code chat. Replace the placeholders. Claude will
run the script and present the analysis.

---

## 1. Find competitors for a URL

Copy this whole block, replace `<CLIENT_URL>`, paste into Claude Code chat:

```
Run the SEO competitor finder for this URL: <CLIENT_URL>

Steps:
1. Run this exact command:
   python "C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins\skills\find-competitors\scripts\find.py" <CLIENT_URL> --country IN --scan

2. Read the JSON file the script writes to /tmp/seo-competitors-*.json

3. Apply positioning judgement (you are the LLM — no API call needed):
   - Pick the 3 most category-aligned competitors from the candidates
   - Suggest 2-3 manual additions from industry knowledge

4. Present the top 3 picks as a markdown table with columns:
   Competitor | Domain | Why it's a fit | Traffic | Keywords

5. Below the table, list 2-3 brands you'd recommend adding manually with one-line reasoning.

6. Tell me to pull Ahrefs keyword CSVs for the picks before running gap analysis.
```

**Example fill-in:**
```
Run the SEO competitor finder for this URL: https://www.orra.co.in/
...
   python "C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins\skills\find-competitors\scripts\find.py" https://www.orra.co.in/ --country IN --scan
...
```

---

## 2. Run gap analysis on Ahrefs CSVs

After you've exported keyword CSVs from Ahrefs for the client + each competitor:

```
Run the SEO gap analysis with these inputs:
- Client name: <CLIENT_NAME>
- Client URL: <CLIENT_URL>
- Client CSV: <PATH_TO_CLIENT_CSV>
- Competitor 1: <NAME>:<PATH>
- Competitor 2: <NAME>:<PATH>
- Competitor 3: <NAME>:<PATH>
- Business model: <b2c_ecommerce|b2b_saas|b2b_services>
- Niche: <ONE-LINE_DESCRIPTION>

Workflow (4 passes):

Pass 1 — Generate candidate keywords:
Run this command (substitute the values above):
   python "C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins\skills\gap-analysis\scripts\run.py" --client-name "<CLIENT_NAME>" --client-url "<CLIENT_URL>" --client-csv "<PATH_TO_CLIENT_CSV>" --competitor "<NAME>:<PATH>" --competitor "<NAME>:<PATH>" --business-model <MODEL> --niche "<NICHE>"

Pass 2 — Classify scope:
Read /tmp/gap-*.json. For each candidate keyword, decide if it's in the client's catalog scope.
Apply analyst rules:
- B2C ecommerce: must be a product the client actually sells
- B2B services/SaaS: must be a service the client offers
- Same vertical isn't enough — sub-category must match
Write your in-scope keywords as a JSON list to /tmp/in-scope.json:
   ["keyword 1", "keyword 2", ...]

Pass 3 — Finalise:
Re-run the script with --in-scope-keywords /tmp/in-scope.json --finalize appended.

Pass 4 — Summarise in chat:
Open the JSON one more time. Present:
- Verdict: HIGH / MEDIUM / LOW with 2-line reasoning
- Top 3 Big Wins (refined from script's templated pitches)
- Realistic 6-12 month traffic target
- Catalog scope (1 line)
- Misalignment warning if present
- Path to the DOCX report
```

---

## Tips

- The first prompt costs ~260 Ahrefs units per run. The second is free (no API).
- Both scripts write to `/tmp/` (which on Windows resolves to `C:\Users\Sagar Shanmathuran\AppData\Local\Temp\` or similar — Claude will tell you the exact path).
- If you want shorter prompts, save these as text snippets in your notes app and paste when needed.
- Once you've validated the analysis on 2-3 real clients, ask Nishant for write access to `GrowistoInc/claude-plugins` to upgrade to the slash-command experience.
