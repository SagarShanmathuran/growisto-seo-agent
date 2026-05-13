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
Priority order:
1. high_confidence candidates (in ≥2 signals) — strongest picks
2. Single-source candidates that match positioning
3. Your manual LLM additions

Apply POSITIONING judgement. Reject informational/healthcare/general-grocery sites. Wrong sub-segment = reject even if keyword overlap is high.

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

STEP 2.1 — Run the gap script (Pass 1, candidates):
python "C:\Users\Sagar Shanmathuran\Downloads\history\seo-plugins\skills\gap-analysis\scripts\run.py" --client-name "<NAME>" --client-url "<URL>" --client-csv "<PATH>" --competitor "<C1>:<PATH>" --competitor "<C2>:<PATH>" --competitor "<C3>:<PATH>" --business-model b2c_ecommerce --niche "<STRICT NICHE — write OUT explicitly>"

Read /tmp/gap-*.json.

STEP 2.2 — Apply catalog filter:
For each candidate keyword, mark in_scope=true ONLY if it's a product the client sells AS A STANDALONE category. Reject material-only keywords, cross-category leaks. Save to /tmp/in-scope.json as ["kw1", "kw2", ...].

STEP 2.3 — Compute ROI math (this drives the verdict, not gap ratio):
- Realistic 6-12 month capture = sum of competitor traffic on top-10 in-scope kws
- Incremental revenue = capture × conv rate × AOV
- B2C ecomm: 1-2% conv. B2B: 3-5% lead conv.
- Compare against ₹3L/mo threshold (Growisto ₹1.5L retainer needs 2x ROI)

Verdict gate (ROI-driven):
- HIGH: incremental revenue ≥ ₹5L/mo AND in-scope gap > 100 kws
- MEDIUM: ₹3-5L/mo AND in-scope gap 30-100 kws
- LOW: ₹1.5-3L/mo OR gap 10-30 kws — TIGHT, retainer may not be viable
- NO POTENTIAL: < ₹1.5L/mo OR gap < 10 kws

If verdict label contradicts ROI math, RECOMPUTE. Math wins.

STEP 2.4 — Write TWO verdict files:

(a) /tmp/verdict-internal.txt — FOR CHAT ONLY (your output in Step 2.6).
This one includes the full ROI math (capture × conv × AOV vs ₹3L retainer threshold). 2-3 sentences max.

(b) /tmp/verdict-report.txt — FOR THE DOCX (client-facing).
This one MUST NOT mention AOV, conversion rate, revenue, retainer, ₹3L/₹1.5L, or any pricing math. It must read as a clean SEO opportunity summary the client can see directly. 2-3 sentences max. Focus on:
  - The size of the in-scope keyword opportunity (e.g. "22 high-intent keywords where competitors capture ~14K clicks/mo")
  - The strategic angle (existing rankings to improve vs new categories to build)
  - Tone: analyst-to-client, confident, factual. No selling, no internal math.

Examples:

GOOD (verdict-report.txt for a HIGH potential client):
"Swiss Time House holds a strong organic foundation (6,035 ranking keywords) with clear category-level upside. 22 high-intent gap keywords represent a competitor-captured opportunity of ~14,266 clicks/month, and 8 of these are existing weak rankings (positions 23-47) where targeted on-page optimisation alone should drive material gains within 90 days."

BAD (do not write this in verdict-report.txt — it's internal):
"...At Rs.10K AOV and 0.4% conversion, that is Rs.5.7L/mo — 3.8x the Growisto retainer..."

STEP 2.5 — Finalise DOCX with the CLIENT-FACING verdict:
Re-run the Step 2.1 command with these appended:
--in-scope-keywords /tmp/in-scope.json --verdict-file /tmp/verdict-report.txt --finalize

(Note: --verdict-file points to verdict-report.txt — the clean one. The internal version stays in chat only.)

STEP 2.6 — Output chat report:

## Verdict: HIGH | MEDIUM | LOW | NO POTENTIAL
[Verdict prose from /tmp/verdict.txt]

## ROI math (show your working)
- In-scope gap keywords: N
- Realistic 6-12 month capture: X clicks/mo
- × Conv rate Y% × AOV ₹Z = ₹W/mo incremental revenue
- vs ₹3L/mo threshold → VIABLE / TIGHT / NOT VIABLE

## Catalog scope
[IN / OUT bullets]

## Traffic comparison
| Site | Traffic | KWs | DR |

## Keyword opportunity
- Candidate gap: N
- In-scope after filter: N
- Out-of-scope rejected: N

## Top 5 weak rankings (client pos 11-30 — fastest wins)
| Keyword | Vol | Client pos | Action |

## Top 5 in-scope new pages
| Keyword cluster | Vol | Best comp pos | Page to build |

## Out-of-scope rejections (sanity check)
[8-10 high-vol kws rejected with one-line reason each]

## DOCX
/tmp/report-<client-slug>.docx
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
