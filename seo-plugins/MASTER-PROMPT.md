# Master prompt — full SEO potential analysis

ONE prompt. Pause in the middle for you to drop CSVs. Same rigour as the Orra analysis.

Paste this in a fresh chat. Replace `<PASTE URL HERE>` at the top. Hit enter.

```
SEO POTENTIAL ANALYSIS — full workflow with pause for CSVs

CLIENT URL: <PASTE URL HERE>

You will run this in TWO phases. After Phase 1, STOP and wait for me to drop the Ahrefs CSVs.

================ PHASE 1 — Find competitors + catalog scope ================

STEP 1.1 — WebFetch the client homepage FIRST to identify their niche.
This gives the SerpAPI seed-keyword builder a useful hint. Note the niche in one short line (e.g. "premium dry fruits and nuts D2C", "diamond and platinum jewellery").

STEP 1.2 — Run the competitor finder with niche hint + SerpAPI cross-check:
python "C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins\skills\find-competitors\scripts\find.py" <CLIENT URL> --country IN --scan --niche "<NICHE>"

The script now runs THREE signals:
  - Ahrefs organic-competitors (keyword overlap)
  - SearchAPI live Google SERPs on client's top 5 commercial keywords (live co-occurrence)
  - Domains appearing in BOTH get `high_confidence: true`

Read /tmp/seo-competitors-*.json.

STEP 1.3 — Add LLM peer-brand discovery (free, you are the LLM).
Independent of the script, generate 5-8 brands you know compete with this client in India based on positioning and industry knowledge. Compare to the candidates list:
- If a brand is in your list AND in the candidates → already counted as high-confidence
- If a brand is in your list but NOT in candidates → Ahrefs+SERP missed it, flag as MANUAL ADDITION

STEP 1.4 — Build strict catalog scope.
List:
- IN: <products client actually sells, sub-categories>
- OUT: <products competitors sell but client doesn't, especially metals/materials/adjacent>

STEP 1.5 — Pick top 3 competitors.

PRIMARY CATEGORY RULE (critical for multi-category brands):
For brands spanning multiple product categories (Black+Decker, Bosch, Stanley, Samsung, GE — anyone selling power tools + appliances + outdoor, or tech + accessories + services), identify the PRIMARY category first:
- Look at homepage hero + sitemap path frequency + SKU count
- PRIMARY = the category driving most organic traffic and search demand
- For Black+Decker: PRIMARY = power tools (not appliances, not outdoor)
- ALL 3 competitors must come from the PRIMARY category
- Secondary categories get their own separate analysis later

30% OVERLAP MINIMUM:
Reject any candidate that shares <30% of the brand's primary catalog. Hamilton Beach has 0% overlap with Black+Decker's power tools — REJECT regardless of keyword overlap score.

Priority order for picking:
1. high_confidence candidates (in ≥2 signals) — strongest picks
2. Single-source candidates that match positioning AND primary category
3. Your manual LLM additions

Apply POSITIONING judgement. Reject informational/healthcare/general-grocery sites. Wrong sub-segment = reject even if keyword overlap is high.

HARD RULE — REJECT competitors smaller than the client.
Look at each candidate's traffic from the JSON. If a candidate has LESS than 50% of the client's non-brand traffic, REJECT it. There is no meaningful traffic gap to capture from competitors smaller than the client.

If you cannot find 3 competitors that are at least the size of the client AND in the primary category, say so explicitly. Do NOT downgrade. Instead, output:
"⚠ Cannot find 3 size-appropriate primary-category competitors. Best matches are <X>, <Y>, <Z> but they are <smaller than client / wrong sub-segment>. Consider this client a HIGH-AUTHORITY OUTLIER — gap analysis may not be the right framing. Recommend a defensive SEO audit instead."

STEP 1.6 — Present Phase 1 output and STOP:

## Client: <name>
## URL: <url>
## Niche: <one-line>

## Catalog scope
- IN: ...
- OUT: ...

## Competitor signals summary
- Ahrefs candidates: N
- SerpAPI cross-confirmed: N
- High-confidence (≥2 signals): N
- LLM additions (Ahrefs+SERP missed these): N

## Top 3 picks (pull CSVs for these)
| # | Competitor | Domain | Sources | Why it fits | Traffic | KWs | DR |
| 1 | ... | ... | ahrefs+serp | ... | ... | ... | ... |

## NEXT STEP — your turn
Pull Ahrefs Organic Keywords CSVs (Site Explorer → Organic keywords → country=IN → Export) for:
1. <CLIENT>
2. <COMP 1>
3. <COMP 2>
4. <COMP 3>

Drop the 4 file paths in chat. I'll continue from there.

THEN STOP. Do not proceed to Phase 2 until I paste the CSV paths.

================ PHASE 2 — Gap analysis + verdict + DOCX ================
(Run this only AFTER I drop the CSV paths)

🚫 CRITICAL RULE — DO NOT WRITE A CUSTOM PYTHON SCRIPT.
You MUST use the plugin's run.py. If you find yourself about to write a `gap_analysis.py` or any custom CSV-parsing code, STOP. Use run.py instead. The plugin has:
  - Non-branded traffic filtering (required for accurate Site comparison)
  - Top Pages CSV auto-detection
  - SERP-guard against gold/silver keyword leaks
  - Catalog scope filter enforcement (--in-scope-keywords)
  - Verdict prose sanitiser (strips internal ROI math from the DOCX)
  - Client-vs-competitor page-level aggregation
Writing your own script bypasses ALL of these and produces wrong reports.

STEP 2.1 — Run the gap script (Pass 1, candidates):
python "C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins\skills\gap-analysis\scripts\run.py" --client-name "<NAME>" --client-url "<URL>" --client-csv "<PATH>" --competitor "<C1>:<PATH>" --competitor "<C2>:<PATH>" --competitor "<C3>:<PATH>" --business-model b2c_ecommerce --niche "<STRICT NICHE — write OUT explicitly>"

Read /tmp/gap-*.json. Sanity check the brand_audit field:
- Are non-brand traffic numbers materially smaller than total? (If brand_rows=0 across all CSVs, the Branded flag wasn't exported — STOP and ask user to re-export from Ahrefs with brand filters enabled.)
- Are the competitors larger than the client? (If client_traffic > all comp traffic, the script will warn — surface this to the user, do NOT proceed to a HIGH verdict.)

STEP 2.2 — Apply catalog filter in ONE pass (no review pause).
Quickly scan candidate_keywords. Keep only those that are products/services the client sells AS A STANDALONE category. Reject:
- Material-only keywords when client doesn't sell that material standalone (gold X, silver X, plain Y)
- Cross-category leaks (cookware brand → cutlery; tea → coffee; etc.)
- Branded competitor terms
- Pure informational queries (how to / what is / guide / tutorial)

Write the in-scope list directly to /tmp/in-scope.json as ["kw1", "kw2", ...]. Do NOT ask for review or pause. Just write the file and move on.

STEP 2.3 — Decide the verdict using these gates (no ROI math, no AOV):

Look at:
- In-scope gap kw count
- Sum of competitor traffic on top-10 in-scope kws (= achievable_top10_traffic in JSON)
- Client's existing non-brand traffic
- Whether competitors are larger or smaller than the client

Gates:
- HIGH potential: in-scope gap > 100 AND achievable > 30K clicks/mo AND competitors are 2-15x larger than client
- MEDIUM potential: in-scope gap 30-100 AND achievable 10K-30K clicks/mo
- LOW potential: in-scope gap 10-30 OR achievable 3K-10K
- No meaningful potential: in-scope gap < 10 OR achievable < 3K OR client traffic already exceeds best competitor

Special cases:
- If client_traffic > max(competitor_traffic) → cap verdict at LOW. Surface in chat that competitor picks may be wrong.
- If brand_audit shows zero branded keywords across all CSVs → STOP. The Branded flag wasn't exported. Tell user to re-export with brand filter enabled.

STEP 2.4 — Write the verdict (2 sentences MAX):

Start with one of: "HIGH potential." / "MEDIUM potential." / "LOW potential." / "No meaningful potential."
Then 1-2 sentences with the reasoning. Anchor on the in-scope keyword count + capturable competitor traffic. No AOV, no conversion rate, no ₹/Rs. amounts.

Save to /tmp/verdict-report.txt. Keep it short.

Example (HIGH): "HIGH potential. Swiss Time House has 6,035 existing rankings and 22 in-scope gap keywords where competitors capture 14,266 clicks/mo — 8 of these are weak rankings (pos 23-47) where on-page optimisation alone should drive material gains in 90 days."

Example (MEDIUM): "MEDIUM potential. Plated has a defensible exosome moat, but its 850 non-brand clicks vs competitors' 37K-54K means the 11,816 in-scope gap is realistic to chase only via deepening existing categories — not catching the leaders."

Example (LOW): "LOW potential. Only 17 in-scope keywords with 8,119 competitor capture. At Nu Republic's near-zero existing SEO base (372 clicks/mo) and narrow audio catalog, organic gains will not move the business meaningfully."

STEP 2.5 — Finalise DOCX:
Re-run the Step 2.1 command with these appended:
--in-scope-keywords /tmp/in-scope.json --verdict-file /tmp/verdict-report.txt --finalize

The --in-scope-keywords flag is MANDATORY. If you skip it, the script will REFUSE to write the DOCX (error code 2) — this prevents out-of-scope keywords leaking into the report.

STEP 2.6 — One-line chat output:

Just confirm in chat:
"✓ Done. Verdict: <HIGH/MEDIUM/LOW>. DOCX: /tmp/report-<slug>.docx"

Optional one-line summary of the in-scope count + capturable traffic if you want, but don't write paragraphs. The DOCX has everything the user needs.
```

---

## How to use it

1. New chat
2. Paste this whole block
3. Replace `<PASTE URL HERE>` at the top with the client's URL
4. Hit enter
5. Phase 1 runs — Claude finds competitors with 3-signal merge + asks for CSVs
6. Pull 4 Ahrefs CSVs (client + 3 picks), paste paths in same chat
7. Phase 2 runs — full gap analysis + verdict + DOCX

## What's new (vs the previous version)

- **3-signal competitor merge:** Ahrefs + SerpAPI + LLM peer brands. Cross-confirmed picks marked `high_confidence`. Catches premium/new brands Ahrefs misses (Farmley, Zoya, Forevermark types).
- **Niche-aware SerpAPI seeds:** Step 1.1 fetches homepage first, builds niche string, passes to script for better SERP seed keywords.
- **ROI-driven verdict (not gap ratio):** Verdict gate is grounded in incremental revenue vs ₹3L/mo threshold. No more "small gap = HIGH" bug from Happilo.
- **DOCX gets real verdict prose:** Script now accepts `--verdict-file`, no more placeholder text in the report.
- **Top Pages CSV support (NEW):** The gap script now auto-detects either Ahrefs export format:
  - **Organic Keywords export** (default) — top 1,000 kws per site, 4,000 export rows per analysis
  - **Top Pages export** — top 100 pages (one row per page, top keyword shown), **400 export rows per analysis (10x cheaper)**
  - Either works in the same `python ... run.py` command — no flag change needed. The script prints which format it detected for each CSV.
  - **Use Top Pages export when your Ahrefs row budget is tight.** Get ~30 analyses on 12K rows instead of 3.
