---
description: Generate a 6-slide SEO proposal PPTX from Ahrefs keyword + top-page CSV exports (client + 2-3 competitors).
argument-hint: --client-name X --client-csv ./client-kw.csv --competitor "Comp1:./comp1-kw.csv" --competitor "Comp2:./comp2-kw.csv" [--top-pages-csv ./client-pages.csv]
---

Run the **proposal-slides** skill with these args: $ARGUMENTS

Follow the three-pass workflow in `${CLAUDE_PLUGIN_ROOT}/skills/proposal-slides/SKILL.md`.

### Pass 1 — Generate base data

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/proposal-slides/scripts/run.py $ARGUMENTS
```

Read the `proposals-{slug}.json` written to the output directory.

### Pass 2 — YOU enrich for slides 3–6

Open the JSON. Read `for_claude.client_top_keywords`, `for_claude.competitor_keywords`,
and `for_claude.top_pages`.

Produce `clusters-{slug}.json` with keys:
- `slide3_clusters` — 4–6 topical clusters with kw_count, total_sv, sample_keywords
- `slide4_categories` — 5–8 category rows: client KWs/top10/traffic vs main competitor
- `slide5_pages` — 4–6 missing sub-category page opportunities
- `slide6_inpage` — 2–4 in-page deep-dives (mis-targeted pages)

See SKILL.md for the exact JSON schema each key must follow.

### Pass 3 — Generate the PPTX

Re-run with `--clusters-json <path> --finalize`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/proposal-slides/scripts/run.py $ARGUMENTS \
    --clusters-json <path/to/clusters-{slug}.json> \
    --finalize
```

Tell the analyst the full path to the saved `proposal-slides-{slug}.pptx`.
