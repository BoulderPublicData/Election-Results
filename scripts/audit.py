"""
Audit module — generates per-source summary statistics and Markdown fragments
that feed docs/data-dictionary.md.

For each (year, source) source file produces:
- row counts, distinct contests, distinct precincts
- contest_type breakdown
- vote-count summary (min, max, sum, % null)
- top 10 contests by vote totals (sanity check)
- extraction_quality + extraction_notes summary

The provenance columns (source_file, source_url, retrieved_at,
extraction_quality, extraction_notes) live in `data/processed/provenance.csv`
rather than in the per-row CSVs. ``audit_file`` joins them back in by
(election_year, election_type, data_source) before formatting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"
AUDIT_DIR = REPO_ROOT / "data" / "audit"
PROVENANCE_CSV = PROCESSED / "provenance.csv"


def _md_table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def _provenance_lookup() -> dict[tuple[str, str, str], dict]:
    """Index provenance.csv by (year, election_type, data_source).

    Returns an empty dict if the sidecar isn't present — audits fall back to
    "(unknown)" for those fields, which is the right behavior on a fresh
    clone before the pipeline has run.
    """
    if not PROVENANCE_CSV.exists():
        return {}
    prov = pd.read_csv(PROVENANCE_CSV, dtype=str)
    out: dict[tuple[str, str, str], dict] = {}
    for _, row in prov.iterrows():
        key = (str(row["election_year"]), str(row["election_type"]), str(row["data_source"]))
        out[key] = row.to_dict()
    return out


def audit_frame(df: pd.DataFrame, stem: str, *, provenance: dict | None = None) -> str:
    """Format a Markdown audit fragment for one (year, source) DataFrame.

    `provenance` is the matching row from `provenance.csv` as a dict; if None,
    the function looks for provenance columns directly on `df` (the in-memory
    frame still carries them when called from `pipeline.py`).
    """
    df = df.copy()
    df["_votes"] = pd.to_numeric(df.get("votes"), errors="coerce")

    year = df["election_year"].iloc[0] if not df.empty else "?"
    etype = df["election_type"].iloc[0] if not df.empty else "?"
    src = df["data_source"].iloc[0] if not df.empty else "?"

    def _pick(col: str, default: str = "?") -> str:
        if provenance and col in provenance and pd.notna(provenance.get(col)):
            return str(provenance[col])
        if col in df.columns and df[col].notna().any():
            return str(df[col].dropna().iloc[0])
        return default

    source_file = _pick("source_file")
    source_url = _pick("source_url")
    retrieved = _pick("retrieved_at")
    quality = _pick("extraction_quality")
    notes = _pick("extraction_notes", default="—")

    n_rows = len(df)
    n_contests = df["contest"].nunique()
    n_precincts = df["precinct_id"].nunique()
    contest_types = df["contest_type"].value_counts().to_dict()
    null_votes = df["_votes"].isna().sum()
    total_votes = int(df["_votes"].fillna(0).sum())

    top = (
        df.groupby("contest", dropna=False)["_votes"]
        .sum().sort_values(ascending=False).head(10).reset_index()
    )
    top_rows = [{"contest": r["contest"], "total_votes": f"{int(r['_votes']):,}"} for _, r in top.iterrows()]
    party_counts = df["party"].fillna("(none)").value_counts().head(8).to_dict()

    parts = [
        f"### {year} {etype} — {src}",
        "",
        f"- **Source file:** `{source_file}`",
        f"- **Source URL:** {source_url}",
        f"- **Retrieved at:** {retrieved}",
        f"- **Extraction quality:** {quality}",
        f"- **Extraction notes:** {notes}",
        "",
        f"- **Rows:** {n_rows:,}",
        f"- **Distinct contests:** {n_contests}",
        f"- **Distinct precincts:** {n_precincts}",
        f"- **Total votes summed:** {total_votes:,}",
        f"- **Rows with null votes:** {null_votes:,}",
        f"- **Contest type breakdown:** {contest_types}",
        f"- **Party breakdown (top 8):** {party_counts}",
        "",
        "**Top 10 contests by vote total** (sanity check):",
        "",
        _md_table(top_rows, ["contest", "total_votes"]),
        "",
    ]
    return "\n".join(parts)


def audit_file(csv_path: Path, *, provenance_lookup: dict | None = None) -> str:
    """Standalone-CLI entry point: reads a slim CSV from disk and joins
    provenance from the sidecar before formatting."""
    df = pd.read_csv(csv_path, dtype=str)
    lookup = provenance_lookup if provenance_lookup is not None else _provenance_lookup()
    prov = None
    if not df.empty:
        key = (str(df["election_year"].iloc[0]),
               str(df["election_type"].iloc[0]),
               str(df["data_source"].iloc[0]))
        prov = lookup.get(key)
    return audit_frame(df, csv_path.stem, provenance=prov)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=AUDIT_DIR / "summary.md",
                    help="Concatenated audit output (default: data/audit/summary.md)")
    ap.add_argument("csv", nargs="*", type=Path,
                    help="Specific CSVs (default: every CSV in data/processed/ "
                         "except provenance.csv and all-elections-tidy.csv)")
    args = ap.parse_args()

    if args.csv:
        csvs = args.csv
    else:
        csvs = [p for p in sorted(PROCESSED.glob("[0-9]*.csv"))
                if p.name != "provenance.csv"]
    if not csvs:
        print(f"No CSVs found under {PROCESSED}", file=sys.stderr)
        return 2

    lookup = _provenance_lookup()
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    fragments: list[str] = []
    for p in csvs:
        if not p.exists():
            print(f"  skip {p.name} (missing)", file=sys.stderr)
            continue
        frag = audit_file(p, provenance_lookup=lookup)
        (AUDIT_DIR / f"{p.stem}.md").write_text(frag)
        fragments.append(frag)
        print(f"audited {p.name}")

    args.out.write_text("\n".join(fragments))
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)} ({len(fragments)} sections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
