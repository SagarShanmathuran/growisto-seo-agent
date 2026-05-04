"""Claude AI synthesis — final SEO potential verdict and narrative."""

import anthropic


_SYSTEM = """You are a senior SEO strategist at a digital marketing agency.
Your job is to assess whether a client website has HIGH, MEDIUM, or LOW SEO potential
based on competitor benchmarks, keyword gaps, on-page audit findings, and ROI data.
Be direct, specific, and actionable. Write like an expert briefing a sales team."""


def _build_prompt(
    client_url: str,
    niche: str,
    competitors: list[dict],
    keyword_gaps: list[dict],
    on_page_audit: dict,
    roi_data: dict,
) -> str:
    comp_lines = "\n".join(
        f"  • {c['domain']}: ~{c.get('estimated_traffic', 0):,} organic visits/month"
        for c in competitors[:6]
    ) or "  No competitor data uploaded."

    gap_lines = "\n".join(
        f"  • \"{g['keyword']}\" — Vol: {g.get('search_volume', '?'):,}  "
        f"Competitor rank: #{g.get('competitor_position', '?')}  "
        f"Client rank: {g.get('client_position', 'Not ranking')}"
        for g in keyword_gaps[:10]
    ) or "  No keyword data uploaded."

    audit_lines = "\n".join(
        f"  • {k.replace('_', ' ').title()}: {v}"
        for k, v in on_page_audit.items()
        if v is not None
    ) if on_page_audit else "  Audit not available."

    roi = roi_data or {}
    roi_lines = (
        f"  • Competitor total traffic: {roi.get('competitor_traffic', 0):,}/mo\n"
        f"  • Achievable traffic (10%): {roi.get('achievable_traffic', 0):,}/mo\n"
        f"  • Est. monthly revenue: ${roi.get('monthly_revenue', 0):,.0f}\n"
        f"  • Annual ROI: {roi.get('roi_pct', 0)}%  (ratio: {roi.get('roi_ratio', 0)}×)\n"
        f"  • ROI viable (≥3× return): {'YES' if roi.get('is_viable') else 'NO'}"
    )

    return f"""Assess the SEO outreach potential for this website.

CLIENT: {client_url}
NICHE: {niche}

COMPETITOR TRAFFIC BENCHMARK:
{comp_lines}

TOP KEYWORD GAPS (competitors rank, client doesn't):
{gap_lines}

ON-PAGE SEO AUDIT (client site):
{audit_lines}

SEO ROI ESTIMATE:
{roi_lines}

---
Respond using EXACTLY this format (no extra text before or after):

POTENTIAL: [HIGH | MEDIUM | LOW]

SUMMARY:
[3–4 sentences. State the verdict, why, key evidence from the data above, and the business case.]

ACTIONS:
- [Specific action 1]
- [Specific action 2]
- [Specific action 3]

SCORING GUIDE:
- HIGH: Competitor traffic >10K/mo, clear keyword gaps, ROI viable, on-page issues present → worth outreach
- MEDIUM: Moderate traffic (3K–10K), some gaps, borderline ROI → conditional outreach
- LOW: <3K competitor traffic, few gaps, poor ROI → skip or 2-line explanation only
"""


def synthesize(
    client_url: str,
    niche: str,
    competitors: list[dict],
    keyword_gaps: list[dict],
    on_page_audit: dict,
    roi_data: dict,
    api_key: str,
) -> dict:
    """
    Call Claude and return:
      { potential: "HIGH"|"MEDIUM"|"LOW", summary: str, actions: list[str] }
    """
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        client_url, niche, competitors, keyword_gaps, on_page_audit, roi_data
    )

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=1200,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()

    text = next(
        (b.text for b in msg.content if hasattr(b, "text") and b.type == "text"),
        "",
    )
    return _parse(text)


def _parse(text: str) -> dict:
    potential = "MEDIUM"
    summary   = ""
    actions   = []
    mode      = None

    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if line.upper().startswith("POTENTIAL:"):
            val = line.split(":", 1)[1].strip().upper()
            if val in ("HIGH", "MEDIUM", "LOW"):
                potential = val
        elif line.upper() == "SUMMARY:":
            mode = "summary"
        elif line.upper() == "ACTIONS:":
            mode = "actions"
        elif mode == "summary" and line:
            summary += (" " if summary else "") + line
        elif mode == "actions" and line.startswith("-"):
            actions.append(line[1:].strip())

    return {"potential": potential, "summary": summary.strip(), "actions": actions}
