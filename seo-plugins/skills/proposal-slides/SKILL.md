---
name: proposal-slides
description: >
  Generate a 6-slide Ahrefs-powered SEO proposal PPTX from organic keyword
  and top-page CSV exports. Use when the analyst has keyword dumps for a client
  + 2-3 competitors and wants a ready-to-paste proposal slide deck.
  Trigger on: "make proposal slides", "build the 6 slides", "create proposal deck",
  "generate ranking slides", or any mention of the 6 slide types listed below.
---

# SEO Proposal Slides — 6-Slide PPTX from Ahrefs CSVs

You generate a 6-slide PPTX using Ahrefs keyword exports. The output slides are:

1. **Keyword Ranking** — client vs competitors on key gap keywords
2. **Ranking Bucketing** — client's position-distribution with search volume share
3. **On-Page: Topical Clusters** — content universe grouped into interlinked clusters
4. **On-Page: Category Level Scope** — category-by-category traffic gap vs main competitor
5. **On-Page Opportunity** — missing sub-category pages (competitor traffic benchmarks)
6. **In-Page Opportunity** — page-level deep-dives (mis-targeted pages, wrong keyword)

---

## Required Inputs

| Input | File | Notes |
|-------|------|-------|
| Client keywords | Ahrefs → Site Explorer → Organic Keywords → Export CSV | One file |
| Competitor keywords | Same export, one file per competitor | 2–3 competitors |
| Client top pages | Ahrefs → Site Explorer → Top Pages → Export CSV | Optional but needed for slides 5–6 |
| Competitor top pages | Same export per competitor | Optional but recommended |

---

## Workflow

### Pass 1 — Run the data script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/proposal-slides/scripts/run.py \
    --client-name <ClientName> \
    --client-csv <path/to/client-keywords.csv> \
    --competitor "<CompName1>:<path/to/comp1.csv>" \
    --competitor "<CompName2>:<path/to/comp2.csv>" \
    [--top-pages-csv <path/to/client-pages.csv>] \
    [--comp-pages "<CompName1>:<path/to/comp1-pages.csv>"] \
    [--output-dir <output-folder>]
```

The script:
- Loads and normalises all CSVs (handles UTF-16 tab-separated AND UTF-8 comma-separated)
- Computes **Slide 1** data: top-15 keywords where a competitor outranks the client
- Computes **Slide 2** data: position-bucket distribution (1, 2, 3, 4-6, 7-10, 11-20, 21-30, 31-50, NR)
- Extracts top-300 client keywords and top-200 per competitor for your analysis
- Writes `proposals-{slug}.json` and prints the path

### Pass 2 — YOU analyse for slides 3–6

Open the JSON. Read `for_claude.client_top_keywords` (top 300 by SV) and
`for_claude.competitor_keywords` (top 200 per competitor) and `for_claude.top_pages`.

#### slide3_clusters — Topical clustering

Group the client's top keywords into **4–6 meaningful topical clusters**.
Rules:
- Each cluster should be a coherent topic area (e.g., "Diamond Rings", "Men's Jewellery")
- Keywords in a cluster share the same buyer intent and landing-page destination
- Derive `kw_count` and `total_sv` by summing the matching keywords from the JSON

#### slide4_categories — Category-level gap

Identify **5–8 main product/service categories** from the keyword data.
For each category:
- Count client keywords that contain category-relevant terms → `client_kws`
- Count those with Position ≤ 10 → `client_top10`
- Sum their traffic → `client_traffic`
- Do the same for the primary competitor → `comp_kws`, `comp_top10`, `comp_traffic`
- Compute `gap_multiple`: `(comp_traffic / client_traffic)` rounded to 1 decimal + "x"
- List 3–4 high-volume keywords the client is missing or ranking poorly on → `missing_keywords`

#### slide5_pages — Missing sub-category pages

Look at `for_claude.top_pages` for each competitor. Find pages that:
- Drive significant competitor traffic (≥ 1,000 visits/mo)
- Target a keyword the client doesn't rank for or has no matching page
- Are in a category the client actually sells/serves

For each gap, identify:
- What the client's current status is ("0 traffic — no page exists")
- What pages to create (2–4 concrete page names)
- Competitor traffic benchmarks (1–2 examples)
- Top target keywords for those pages

#### slide6_inpage — In-page deep-dives

Find **2–4 existing client pages** where the problem is targeting, not absence:
- Page exists but targets a low-SV keyword when a higher-SV variant is available
- URL slug is misspelled or non-descriptive
- Client traffic is ≪ competitor traffic on the same category

For each, note:
- Current client URL, traffic, top keyword and its SV
- The issue (e.g., "Wrong keyword targeted — ranking for 1.3K SV term, should target 267K")
- Best competitor benchmark (name, traffic, top keyword + SV)
- A concrete action sentence

### Write the enrichment JSON

Write a file `clusters-{slug}.json` with this exact schema:

```json
{
  "slide3_clusters": [
    {
      "num": 1,
      "name": "Cluster Name",
      "kw_count": 45,
      "total_sv": 250000,
      "sample_keywords": ["keyword 1", "keyword 2", "keyword 3"],
      "description": "Optional one-line description"
    }
  ],
  "slide4_categories": [
    {
      "category": "Category Name",
      "client_kws": 2761,
      "client_top10": 1854,
      "client_traffic": 21883,
      "comp_name": "Competitor Name",
      "comp_kws": 7567,
      "comp_top10": 5782,
      "comp_traffic": 72560,
      "gap_multiple": "3.3x",
      "missing_keywords": "keyword A (54K, pos 22), keyword B (123K, pos 22), keyword C (46K, NR)"
    }
  ],
  "slide5_pages": [
    {
      "category": "Category Name (max 30 chars)",
      "client_status": "0 traffic — no style-specific page",
      "pages_to_create": ["Page Name 1", "Page Name 2", "Page Name 3"],
      "comp_traffic_examples": [
        {"comp": "Competitor Name", "page": "Page label", "traffic": 20522}
      ],
      "top_keywords": "keyword A (23K, NR), keyword B (17K, NR), keyword C (15K, NR)"
    }
  ],
  "slide6_inpage": [
    {
      "category": "Category Name",
      "client_url": "/collections/example-slug",
      "client_traffic": 152,
      "client_top_kw": "low sv keyword",
      "client_kw_sv": 1300,
      "issue": "Wrong keyword targeted",
      "comp_name": "Competitor Name",
      "comp_url": "/collections/correct-slug",
      "comp_traffic": 69192,
      "comp_top_kw": "high sv keyword",
      "comp_kw_sv": 267000,
      "action": "Retarget slug and H1/meta for 'high sv keyword' (267K SV). Create colour-variant sub-pages."
    }
  ]
}
```

### Pass 3 — Generate the PPTX

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/proposal-slides/scripts/run.py \
    --client-name <ClientName> \
    --client-csv <path/to/client-keywords.csv> \
    --competitor "<CompName1>:<path/to/comp1.csv>" \
    --competitor "<CompName2>:<path/to/comp2.csv>" \
    [--top-pages-csv <path>] [--comp-pages "<Name>:<path>"] \
    --clusters-json <path/to/clusters-{slug}.json> \
    --finalize \
    [--output-dir <output-folder>]
```

The PPTX is saved as `proposal-slides-{slug}.pptx` in the output directory
(default: same folder as the client CSV).

Tell the analyst the full path to the PPTX.

---

## Dependencies

```bash
pip install pandas python-pptx
```

---

## Tips for better slides

- **slide4_categories**: Use the primary competitor only (first in `--competitor` list). Other
  competitors can be mentioned in `missing_keywords`.
- **slide5_pages**: Prefer gaps where the client has the underlying product/service inventory —
  the point is "the page doesn't exist yet", not "the product doesn't exist".
- **slide6_inpage**: Focus on pages with the most traffic-upside (high comp_traffic, low client_traffic).
  The action sentence should be concrete and implementable in one sprint.
- Keep `category` and card `name` strings short (≤ 30 characters) — they appear in card headers.
