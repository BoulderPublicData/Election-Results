"""
Top-line contest reconciliation audit.

For each (year, source), open the ORIGINAL file and the processed CSV, sum
vote totals by canonical contest, and compare. The delta tells you whether the
parser preserved totals.

A non-zero delta is not always a bug — common reasons:
- The original file includes statewide rows that aren't filtered to Boulder
  (SOS only); we expect Boulder-only sums to differ from the file-level sum.
- PDF years (2005/2007/2009) have placeholder contest titles, so the
  contest-pattern matcher finds nothing in the processed data; the reconciler
  marks these rows as 'not_reconcilable'.
- Panel-format years (2008/2010) have known column-alignment issues for
  measure panels; deltas are expected to be non-zero there.

Output:
- data/audit/reconciliation.md  — full Markdown report
- data/audit/reconciliation.csv — same data in tidy form for filtering/joining
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .parsers.common import clean_cols
from .sources import ALL_SOURCES, BOULDER_COUNTY, SECRETARY_OF_STATE, Source

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DATA = REPO_ROOT / "original-data"
PROCESSED = REPO_ROOT / "data" / "processed"
AUDIT = REPO_ROOT / "data" / "audit"
LOOKUPS = REPO_ROOT / "data" / "lookups"


@dataclass(frozen=True)
class ContestPattern:
    canonical: str
    tier: str
    regexes: tuple[re.Pattern, ...]


def _load_patterns() -> list[ContestPattern]:
    raw = json.loads((LOOKUPS / "contest-aliases.json").read_text())
    return [
        ContestPattern(
            canonical=entry["canonical"],
            tier=entry["tier"],
            regexes=tuple(re.compile(p, re.IGNORECASE) for p in entry["patterns"]),
        )
        for entry in raw["contests"]
    ]


def _match_canonical(text: object, patterns: list[ContestPattern]) -> str | None:
    if pd.isna(text):
        return None
    s = str(text)
    for pat in patterns:
        if any(rx.search(s) for rx in pat.regexes):
            return pat.canonical
    return None


# ----- Original-file readers (lightweight; just enough to sum totals) -----

def _read_sos_original(path: Path) -> pd.DataFrame:
    """SOS files are already long-form; just need to load and filter Boulder."""
    df = pd.read_excel(path, engine="openpyxl", sheet_name=0)
    df = clean_cols(df)
    # Locate columns by case-insensitive aliases.
    cols = {c.lower(): c for c in df.columns}
    county_col = cols.get("county")
    contest_col = (
        cols.get("office/issue/judgeship")
        or cols.get("office/ballot issue")
        or cols.get("office/question")
    )
    party_col = cols.get("party")
    votes_col = cols.get("candidate votes") or cols.get("votes")
    yes_col = cols.get("yes votes")
    no_col = cols.get("no votes")
    if not (county_col and contest_col):
        raise ValueError(f"{path.name}: missing county/contest columns; have={list(df.columns)}")
    sub = df[df[county_col].astype("string").str.strip().str.upper() == "BOULDER"].copy()

    rows: list[dict] = []
    for _, r in sub.iterrows():
        contest = str(r[contest_col]).strip() if pd.notna(r[contest_col]) else ""
        # Candidate vote
        if votes_col and pd.notna(r[votes_col]):
            rows.append({
                "contest": contest,
                "candidate_or_option": str(r.get("candidate") or r.get("candidate/yes or no") or "").strip(),
                "party": str(r[party_col]).strip() if party_col and pd.notna(r[party_col]) else None,
                "votes": pd.to_numeric(r[votes_col], errors="coerce"),
            })
        if yes_col and pd.notna(r[yes_col]):
            rows.append({"contest": contest, "candidate_or_option": "Yes", "party": None,
                         "votes": pd.to_numeric(r[yes_col], errors="coerce")})
        if no_col and pd.notna(r[no_col]):
            rows.append({"contest": contest, "candidate_or_option": "No", "party": None,
                         "votes": pd.to_numeric(r[no_col], errors="coerce")})
    return pd.DataFrame(rows)


def _read_boco_tidy_original(path: Path) -> pd.DataFrame:
    """Boulder tidy years (2013-2024). Cheap reader that just sums Total Votes
    by Contest Title × Choice Name."""
    engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
    if path.name == "2013-coordinated-sov.xls":
        engine = "openpyxl"
    xl = pd.ExcelFile(path, engine=engine)

    frames = []
    for sheet in xl.sheet_names:
        if sheet.lower() in {"summary_of_results", "summary of results"}:
            continue
        raw = pd.read_excel(path, engine=engine, sheet_name=sheet)
        if raw.empty:
            continue
        df = clean_cols(raw)
        cols_lower = {c.lower(): c for c in df.columns}
        contest_col = cols_lower.get("contest title") or cols_lower.get("contest name")
        choice_col = cols_lower.get("choice name") or cols_lower.get("candidate name")
        votes_col = cols_lower.get("total votes")
        if not (contest_col and choice_col and votes_col):
            continue
        out = pd.DataFrame({
            "contest": df[contest_col].astype("string").str.strip(),
            "candidate_or_option": df[choice_col].astype("string").str.strip(),
            "party": df[cols_lower["party"]].astype("string").str.strip() if "party" in cols_lower else None,
            "votes": pd.to_numeric(df[votes_col], errors="coerce"),
        })
        frames.append(out.dropna(subset=["contest", "candidate_or_option"]))
    if not frames:
        return pd.DataFrame(columns=["contest", "candidate_or_option", "party", "votes"])
    return pd.concat(frames, ignore_index=True)


def _read_original(source: Source) -> pd.DataFrame | None:
    path = ORIGINAL_DATA / source.data_source.replace("_", "-") / source.local_filename
    if not path.exists():
        return None
    if source.data_source == "secretary_of_state":
        return _read_sos_original(path)
    # Boulder: tidy reader covers 2013-2024. Panel and PDF years can't be summed
    # reliably without replicating the full parser — return None so they're
    # marked 'not_reconcilable' in the report.
    if source.year < 2013:
        return None
    if source.year in {2005, 2007, 2009}:
        return None
    return _read_boco_tidy_original(path)


def _processed_path(s: Source) -> Path:
    ds = s.data_source.replace("_", "-")
    return PROCESSED / f"{s.year}-{s.election_type}-{ds}.csv"


def reconcile_source(source: Source, patterns: list[ContestPattern]) -> pd.DataFrame:
    """Return a per-canonical-contest reconciliation frame for one source."""
    proc_path = _processed_path(source)
    if not proc_path.exists():
        return pd.DataFrame()

    orig = _read_original(source)
    proc = pd.read_csv(proc_path, dtype={"precinct_id": "string"}, low_memory=False)
    proc["votes"] = pd.to_numeric(proc["votes"], errors="coerce")

    # For RCV contests, the processed CSV explodes each round into its own row.
    # The Round-N rows sum back to the original Total Votes only if we keep
    # the '| Final' rows and discard intermediates.
    rcv_mask = proc["contest_type"] == "ranked_choice"
    keep_mask = ~rcv_mask | proc["candidate_or_option"].astype("string").str.contains(
        r"\|\s*Final\s*$", na=False, regex=True
    )
    proc_for_sum = proc[keep_mask]

    proc_for_sum = proc_for_sum.assign(
        canonical=proc_for_sum["contest"].map(lambda t: _match_canonical(t, patterns))
    )
    proc_sum = (
        proc_for_sum.dropna(subset=["canonical"])
            .groupby("canonical")["votes"].sum()
            .astype("Int64")
    )

    if orig is None:
        # Mark as not reconcilable but still show what's in processed.
        out = proc_sum.rename("processed_total").to_frame()
        out["original_total"] = pd.NA
        out["delta"] = pd.NA
        out["status"] = "not_reconcilable"
    else:
        orig["canonical"] = orig["contest"].map(lambda t: _match_canonical(t, patterns))
        orig_sum = (
            orig.dropna(subset=["canonical"])
                .groupby("canonical")["votes"].sum()
                .astype("Int64")
        )
        out = pd.concat(
            [orig_sum.rename("original_total"), proc_sum.rename("processed_total")],
            axis=1,
        ).fillna(pd.NA)
        out["delta"] = out["processed_total"].sub(out["original_total"], fill_value=0)
        out["status"] = out["delta"].apply(
            lambda d: "match" if d == 0 else ("near_match" if abs(int(d)) < 50 else "mismatch")
        )
        out.loc[out["original_total"].isna() & out["processed_total"].isna(), "status"] = "not_in_file"

    out = out.reset_index().rename(columns={"index": "canonical"})
    out["year"] = source.year
    out["election_type"] = source.election_type
    out["data_source"] = source.data_source
    return out[["year", "election_type", "data_source", "canonical",
                "original_total", "processed_total", "delta", "status"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int)
    ap.add_argument("--source", choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    args = ap.parse_args()

    if args.source == "boulder_county":
        pool = BOULDER_COUNTY
    elif args.source == "secretary_of_state":
        pool = SECRETARY_OF_STATE
    else:
        pool = ALL_SOURCES
    if args.year:
        pool = [s for s in pool if s.year == args.year]

    patterns = _load_patterns()
    AUDIT.mkdir(parents=True, exist_ok=True)

    frames = []
    for s in pool:
        try:
            r = reconcile_source(s, patterns)
        except Exception as e:
            print(f"FAIL {s.year}-{s.data_source}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if r.empty:
            continue
        frames.append(r)
        n = len(r)
        bad = (r["status"] == "mismatch").sum()
        print(f"OK   {s.year}-{s.election_type}-{s.data_source}  "
              f"contests={n}  mismatches={bad}")

    if not frames:
        print("No reconciliation rows generated.", file=sys.stderr)
        return 2

    all_recon = pd.concat(frames, ignore_index=True)
    all_recon.to_csv(AUDIT / "reconciliation.csv", index=False)

    # Build the Markdown report.
    md_lines = [
        "# Reconciliation audit",
        "",
        "Compares **top-line contest vote totals** between the original published files",
        "and the harmonized CSVs in `data/processed/`. Generated by",
        "[`scripts/reconcile.py`](../scripts/reconcile.py).",
        "",
        "**Status legend:**",
        "- `match` — original total equals processed total exactly.",
        "- `near_match` — totals differ by < 50 votes (small counting reconciliation, "
        "  usually safe).",
        "- `mismatch` — totals differ by ≥ 50 votes. Investigate.",
        "- `not_reconcilable` — original file format prevents direct re-summation here "
        "  (panel years 2008/2010/2011/2012 and PDF years 2005/2007/2009).",
        "- `not_in_file` — the canonical contest pattern matched nothing in either file.",
        "",
        f"**Summary across all {len(all_recon)} contest-source rows:**",
        "",
    ]
    status_counts = all_recon["status"].value_counts().sort_index()
    md_lines.append("| status | rows |")
    md_lines.append("|---|---|")
    for status, n in status_counts.items():
        md_lines.append(f"| {status} | {n} |")
    md_lines.append("")

    # Group by (year, source) — one table per pair.
    for (year, source, etype), grp in all_recon.groupby(["year", "data_source", "election_type"]):
        md_lines.append(f"## {year} {etype} — {source}")
        md_lines.append("")
        if grp["status"].iloc[0] == "not_reconcilable":
            md_lines.append("*Not reconcilable (panel/PDF format).* Processed totals shown for reference.")
            md_lines.append("")
        md_lines.append("| canonical contest | original | processed | delta | status |")
        md_lines.append("|---|---|---|---|---|")
        for _, r in grp.sort_values("canonical").iterrows():
            orig = f"{int(r['original_total']):,}" if pd.notna(r["original_total"]) else "—"
            proc = f"{int(r['processed_total']):,}" if pd.notna(r["processed_total"]) else "—"
            delta = f"{int(r['delta']):+,}" if pd.notna(r["delta"]) else "—"
            md_lines.append(
                f"| {r['canonical']} | {orig} | {proc} | {delta} | `{r['status']}` |"
            )
        md_lines.append("")

    (AUDIT / "reconciliation.md").write_text("\n".join(md_lines))
    print(f"\nwrote data/audit/reconciliation.md and reconciliation.csv "
          f"({len(all_recon)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
