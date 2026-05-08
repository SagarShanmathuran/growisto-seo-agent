---
description: Find SEO competitors for a URL via Ahrefs + SerpAPI + site scan. Returns ranked list with positioning reasoning.
argument-hint: <client-url> [--country IN] [--scan]
---

Run the **find-competitors** skill on the URL: $ARGUMENTS

Steps:
1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/find-competitors/scripts/find.py $ARGUMENTS`
2. Read the JSON output.
3. Apply your own positioning judgement (no LLM API call needed — you ARE the LLM).
4. Present the top 3 picks as a markdown table, plus 2-3 manual additions you'd recommend from industry knowledge.
5. Tell the analyst to run `/seo-gap-analysis` once they've pulled the keyword CSVs.

Follow the SKILL.md at `${CLAUDE_PLUGIN_ROOT}/skills/find-competitors/SKILL.md`.
