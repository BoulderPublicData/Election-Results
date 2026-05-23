"""
Audit module — generates per-source summary statistics and Markdown fragments
that feed docs/data-dictionary.md.

For each (year, source) processed CSV produces:
- row counts, distinct contests, distinct precincts
- contest_type breakdown
- vote-count summary (min, max, sum, % null)
- top 10 contests by vote totals (sanity check)
- extraction_quality + extraction_notes summary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"
AUDIT_DIR = REPO_ROOT / "data" / "audit"


def _md_table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def audit_file(csv_path: Path) -> str:
    df = pd.read_csv(csv_path, dtype=str)
    # cast votes for stats
    df["_votes"] = pd.to_numeric(df.get("votes"), errors="coerce")

    stem = csv_path.stem  # e.g. 2020-general-boulder-county
    year = df["election_year"].iloc[0] if not df.empty else "?"
    etype = df["election_type"].iloc[0] if not df.empty else "?"
    src = df["data_source"].iloc[0] if not df.empty else "?"
    quality = df["extraction_quality"].iloc[0] if not df.empty else "?"
    notes = df["extraction_notes"].dropna().iloc[0] if df["extraction_notes"].notna().any() else "—"
    source_url = df["source_url"].iloc[0] if not df.empty else "?"
    source_file = df["source_file"].iloc[0] if not df.empty else "?"
    retrieved = df["retrieved_at"].iloc[0] if not df.empty else "?"

    n_rows = len(df)
    n_contests = df["contest"].nunique()
    n_precincts = df["precinct_id"].nunique()
    contest_types = df["contest_type"].value_counts().to_dict()
    null_votes = df["_votes"].isna().sum()
    total_votes = int(df["_votes"].fillna(0).sum())

    # Top 10 contests by vote total
    top = (
        df.groupby("contest", dropna=False)["_votes"]
        .sum().sort_values(ascending=False).head(10).reset_index()
    )
    top_rows = [{"contest": r["contest"], "total_votes": f"{int(r['_votes']):,}"} for _, r in top.iterrows()]

    # Party breakdown (top 8)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=AUDIT_DIR / "summary.md",
                    help="Concatenated audit output (default: data/audit/summary.md)")
    ap.add_argument("csv", nargs="*", type=Path,
                    help="Specific CSVs (default: every CSV in data/processed/)")
    args = ap.parse_args()

    csvs = args.csv if args.csv else sorted(PROCESSED.glob("*.csv"))
    if not csvs:
        print(f"No CSVs found under {PROCESSED}", file=sys.stderr)
        return 2

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    fragments: list[str] = []
    for p in csvs:
        if not p.exists():
            print(f"  skip {p.name} (missing)", file=sys.stderr)
            continue
        frag = audit_file(p)
        # Write per-file fragment for incremental updates
        (AUDIT_DIR / f"{p.stem}.md").write_text(frag)
        fragments.append(frag)
        print(f"audited {p.name}")

    args.out.write_text("\n".join(fragments))
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)} ({len(fragments)} sections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
