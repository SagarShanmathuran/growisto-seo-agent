---
description: Run an SEO gap analysis on Ahrefs CSV dumps for a client + 1-4 competitors. Outputs a Word report and an in-chat verdict.
argument-hint: --client-name X --client-url Y --client-csv ./client.csv --competitor "A:./a.csv" --competitor "B:./b.csv"
---

Run the **gap-analysis** skill with these args: $ARGUMENTS

Two-pass workflow:

### Pass 1 — Generate candidate keywords
Run the script (without `--finalize`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/gap-analysis/scripts/run.py $ARGUMENTS
```

Read the JSON written to `/tmp/gap-{slug}.json`. Look at `candidate_keywords`.

### Pass 2 — YOU classify scope
For EACH candidate keyword, decide whether it's in the client's catalog scope.
Apply the analyst's mental model from `${CLAUDE_PLUGIN_ROOT}/skills/gap-analysis/SKILL.md`.

Write your decision to `/tmp/in-scope.json` as a JSON list of in-scope keywords:
```json
["best cat litter", "kitty litter", ...]
```

### Pass 3 — Finalise
Re-run the script with `--in-scope-keywords /tmp/in-scope.json --finalize`. This writes the DOCX report.

### Pass 4 — Summarise in chat
Open the JSON one more time (it now has the misalignment warning if any). Present:
- Verdict (HIGH / MEDIUM / LOW with 2-line reasoning)
- Top 3 Big Wins (refined from the script's templated pitches)
- Realistic 6-12 month target
- Catalog scope (1 line)
- Misalignment warning (if present)
- Path to the DOCX

Follow `${CLAUDE_PLUGIN_ROOT}/skills/gap-analysis/SKILL.md` for the exact output format.
