# SEO Potential Analyzer (Growisto)

CSV-driven SEO potential analysis. No Ahrefs API or Claude API needed —
analyst exports CSVs from Ahrefs, drops them in, gets a Growisto-branded Word report.

## Quick Start

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Or use the CLI:
```bash
python analyze.py \
  --client-url vinodcookware.com --client-name "Vinod Cookware" \
  --client-keywords client_kw.csv --client-pages client_pages.csv \
  --competitor "Milton:milton_kw.csv:milton_pages.csv" \
  --competitor "Borosil:borosil_kw.csv:borosil_pages.csv" \
  --niche Cookware --aov 1800
```

## Architecture

```
agent/
├── modules/
│   ├── business_model_detector.py   # B2C / B2B / SaaS / Financial classification
│   ├── ahrefs_csv_loader.py         # Parse Ahrefs CSV exports → SiteData
│   ├── gap_analyzer.py              # Client vs competitors stats + notes
│   └── report_data_builder.py       # Bridge to word_report's expected shape
├── services/
│   ├── roi_calculator.py            # ₹1.5L/mo retainer, 10% achievable, ROI math
│   ├── strategic_advisor.py         # Templated recommendations
│   ├── word_report.py               # Growisto-branded DOCX generator
│   ├── serp_client.py               # SearchAPI.io competitor discovery
│   └── gemini_client.py             # Gemini Flash REST verdict (with template fallback)
└── seo_core/
    ├── crawler.py + metrics.py      # On-page health crawl
    └── analyzer.py + recommendations.py

analyze.py            CLI orchestrator
streamlit_app.py      Web UI
.env                  GEMINI_API_KEY, SEARCHAPI_KEY
```

## Configuration

Edit `.env`:
```
GEMINI_API_KEY=...
SEARCHAPI_KEY=...
```

If Gemini is unavailable / rate-limited, the synthesizer falls back to a deterministic
template that produces verdicts in the same Growisto house style.
