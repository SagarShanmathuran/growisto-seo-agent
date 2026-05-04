"""
Loads Ahrefs CSV exports (organic keywords + top pages) for a site.
Returns a normalized SiteData object with non-brand keywords, ranks, traffic.
Handles UTF-16 + tab-separated default Ahrefs export format.
"""

import pandas as pd
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SiteData:
    name:           str
    keywords:       pd.DataFrame      # all keywords
    nb_keywords:    pd.DataFrame      # non-brand only
    pages:          pd.DataFrame
    nb_traffic:     int               # sum of non-brand current organic traffic
    total_kw:       int
    nb_kw_count:    int
    top10_count:    int
    top3_count:     int
    page_count:     int
    avg_ur:         float
    traffic_change: int               # sum of organic traffic change

    def summary(self) -> dict:
        return {
            "name": self.name,
            "non_brand_traffic": self.nb_traffic,
            "total_keywords": self.total_kw,
            "non_brand_keywords": self.nb_kw_count,
            "top_10_keywords": self.top10_count,
            "top_3_keywords": self.top3_count,
            "page_count": self.page_count,
            "avg_url_rating": round(self.avg_ur, 1),
            "traffic_change": self.traffic_change,
        }


def _read_ahrefs_csv(path: str | Path) -> pd.DataFrame:
    """Ahrefs exports default to UTF-16 tab-separated; fall back to common alternatives."""
    path = Path(path)
    for enc, sep in [("utf-16", "\t"), ("utf-8", ","), ("utf-8", "\t"), ("latin-1", ",")]:
        try:
            df = pd.read_csv(path, encoding=enc, sep=sep)
            if df.shape[1] > 1:
                return df
        except (UnicodeDecodeError, UnicodeError, pd.errors.ParserError):
            continue
    raise ValueError(f"Could not parse {path} as an Ahrefs CSV export")


def _normalize_columns(df: pd.DataFrame, alias_map: dict[str, list[str]]) -> pd.DataFrame:
    """Rename any matching column to the canonical name. First match wins."""
    rename = {}
    cols_lower = {c.lower(): c for c in df.columns}
    for canonical, aliases in alias_map.items():
        if canonical in df.columns:
            continue
        for alias in aliases:
            if alias in df.columns:
                rename[alias] = canonical
                break
            if alias.lower() in cols_lower:
                rename[cols_lower[alias.lower()]] = canonical
                break
    if rename:
        df = df.rename(columns=rename)
    return df


def derive_pages_df(kw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate a keywords DataFrame into a page-level DataFrame matching the
    columns Ahrefs' top-pages CSV exposes:
        URL · Traffic · Top keyword · Top keyword: Volume · Top keyword: Position · Keywords

    Each row in the output represents one URL. Traffic is summed across all
    keywords ranking on that URL; the top keyword is the highest-volume one.
    """
    if kw_df.empty or "Current URL" not in kw_df.columns:
        return pd.DataFrame(columns=["URL", "Traffic", "Top keyword",
                                      "Top keyword: Volume", "Top keyword: Position",
                                      "Keywords", "UR"])

    df = kw_df.copy()
    df["Current URL"] = df["Current URL"].fillna("").astype(str)
    df = df[df["Current URL"] != ""]
    if df.empty:
        return pd.DataFrame(columns=["URL", "Traffic", "Top keyword",
                                      "Top keyword: Volume", "Top keyword: Position",
                                      "Keywords", "UR"])

    # Per URL: sum traffic, count keywords, find the top-volume keyword
    grouped = df.groupby("Current URL", sort=False)
    rows = []
    for url, sub in grouped:
        top = sub.loc[sub["Volume"].idxmax()]
        rows.append({
            "URL":                    url,
            "Traffic":                int(sub["Current organic traffic"].sum()),
            "Top keyword":            str(top["Keyword"]),
            "Top keyword: Volume":    int(top["Volume"]),
            "Top keyword: Position":  int(top["Current position"]) if pd.notna(top["Current position"]) else 99,
            "Keywords":               int(len(sub)),
            "UR":                     0,   # not derivable from keywords CSV
        })
    out = pd.DataFrame(rows).sort_values("Traffic", ascending=False).reset_index(drop=True)
    return out


def load(name: str, keywords_csv: str | Path, pages_csv: str | Path | None = None) -> SiteData:
    kw = _read_ahrefs_csv(keywords_csv)
    pg = _read_ahrefs_csv(pages_csv) if pages_csv else None

    # Ahrefs has multiple export formats — comparison (Current X / Previous X / X change)
    # and snapshot (just X). Normalize to the comparison-format names we use downstream.
    kw = _normalize_columns(kw, {
        "Current organic traffic":  ["Organic traffic"],
        "Current position":         ["Position"],
        "Current URL":              ["URL"],
        "Organic traffic change":   ["Traffic change"],
        "Previous organic traffic": ["Previous traffic"],
    })

    if pg is not None:
        pg = _normalize_columns(pg, {
            "Traffic":     ["Current traffic", "Estimated traffic"],
            "UR":          ["URL Rating", "Url Rating"],
            "URL":         ["Page URL", "Url"],
            "Top keyword": ["Top Keyword"],
        })

    required_kw = ["Keyword", "Branded", "Volume", "Current position", "Current organic traffic"]
    missing = [c for c in required_kw if c not in kw.columns]
    if missing:
        raise ValueError(
            f"Missing columns in keyword CSV: {missing}. Got: {list(kw.columns)}\n"
            f"Tip: re-export from Ahrefs UI keeping default columns. The loader auto-handles "
            f"both 'comparison' and 'snapshot' Ahrefs export formats."
        )

    kw["Current position"] = pd.to_numeric(kw["Current position"], errors="coerce")
    kw["Volume"] = pd.to_numeric(kw["Volume"], errors="coerce").fillna(0)
    kw["Current organic traffic"] = pd.to_numeric(kw["Current organic traffic"], errors="coerce").fillna(0)
    # Snapshot exports may not have a "change" column — treat as zero (full Series of zeros)
    if "Organic traffic change" in kw.columns:
        kw["Organic traffic change"] = pd.to_numeric(kw["Organic traffic change"], errors="coerce").fillna(0)
    else:
        kw["Organic traffic change"] = 0

    nb = kw[kw["Branded"] == False].copy()

    # If no Pages CSV provided, derive page-level data from keywords (preferred —
    # one fewer CSV per site for the analyst). Use non-brand keywords so derived
    # page traffic mirrors the analysis we run downstream.
    if pg is None:
        pg = derive_pages_df(nb)
    else:
        pg["UR"] = pd.to_numeric(pg.get("UR", 0), errors="coerce").fillna(0)
        pg["Traffic"] = pd.to_numeric(pg.get("Traffic", 0), errors="coerce").fillna(0)

    return SiteData(
        name=name,
        keywords=kw,
        nb_keywords=nb,
        pages=pg,
        nb_traffic=int(nb["Current organic traffic"].sum()),
        total_kw=len(kw),
        nb_kw_count=len(nb),
        top10_count=int((nb["Current position"] <= 10).sum()),
        top3_count=int((nb["Current position"] <= 3).sum()),
        page_count=len(pg),
        avg_ur=float(pg["UR"].mean()) if len(pg) else 0.0,
        traffic_change=int(nb["Organic traffic change"].sum()),
    )


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 4:
        print("Usage: python -m agent.modules.ahrefs_csv_loader <name> <keywords.csv> <pages.csv>")
        sys.exit(1)
    sd = load(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(sd.summary(), indent=2))
