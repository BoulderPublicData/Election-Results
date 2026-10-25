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

from .config import (
    AUDIT, BOULDER_COUNTY, LOOKUPS,
    PROCESSED, REPO_ROOT, SECRETARY_OF_STATE, SOURCES as ALL_SOURCES, Source, original_path,
)
from .logging_setup import get_logger
from .parsers.common import clean_cols

log = get_logger(__name__)


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
    path = original_path(source.data_source, source.local_filename)
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


# ----- Election-night snapshots vs. the certified Statement of Votes -----

VOTE_COUNTING_VS_SOV_CSV = AUDIT / "vote-counting-vs-sov.csv"


def _name_key(text: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def reconcile_vote_counting() -> pd.DataFrame:
    """Compare each election's FINAL election-night snapshot
    (data/processed/vote-counting/) with the Boulder County SoV CSV, per
    contest × candidate.

    Report-only: the last web update often precedes certification (cures,
    late UOCAVA ballots, canvass adjustments), so deltas are expected and
    never counted as reconciliation mismatches. A large delta on the final
    snapshot is still worth a look — it is the only external check on the
    OCR beyond the internal sum/percent QA.
    """
    import difflib

    path = PROCESSED / "vote-counting" / "vote-counting-contests.csv"
    if not path.exists():
        return pd.DataFrame()
    web = pd.read_csv(path, low_memory=False)
    web = web[web["is_final_snapshot"].astype(bool)]
    # RCV: compare the final-round tallies (the SoV's '| Final' rows).
    web = web[(web["contest_type"] != "ranked_choice")
              | web["candidate_or_option"].str.endswith("| Final")]

    rows: list[dict] = []
    for (year, etype), w in web.groupby(["election_year", "election_type"]):
        sov_path = PROCESSED / f"{year}-{etype}-boulder-county.csv"
        if not sov_path.exists():
            continue
        sov = pd.read_csv(sov_path, low_memory=False,
                          usecols=["contest", "contest_type", "candidate_or_option", "votes"])
        sov = sov[(sov["contest_type"] != "ranked_choice")
                  | sov["candidate_or_option"].astype("string").str.endswith("| Final")]
        # SoV candidate cells sometimes carry "Name  Party" (double space).
        sov["cand_key"] = sov["candidate_or_option"].astype("string").str.split("  ").str[0] \
            .map(_name_key)
        sov["contest_key"] = sov["contest"].map(_name_key)
        sov_tot = sov.groupby(["contest_key", "cand_key"])["votes"].sum()
        sov_contests = dict(zip(sov["contest_key"], sov["contest"], strict=False))

        w = w.assign(contest_key=w["contest"].map(_name_key),
                     cand_key=w["candidate_or_option"].map(_name_key))
        snapshot = w.loc[w["contest_type"] != "ranked_choice", "last_updated"].max()
        for ckey, cw in w.groupby("contest_key", sort=False):
            match = ckey if ckey in sov_contests else next(
                iter(difflib.get_close_matches(ckey, list(sov_contests), n=1, cutoff=0.85)),
                None)
            if match is None:
                # The web card often appends the measure's subtitle to the SoV
                # title ("Ballot Issue 1A" + "Open Space Sales and Use Tax ...").
                prefixes = [k for k in sov_contests if len(k) >= 12 and ckey.startswith(k)]
                match = max(prefixes, key=len) if prefixes else None
            for r in cw.itertuples(index=False):
                sov_votes = sov_tot.get((match, r.cand_key)) if match else None
                status = ("contest_not_in_sov" if match is None else
                          "candidate_not_in_sov" if sov_votes is None else
                          "match" if sov_votes == r.votes else
                          "near_match" if abs(sov_votes - r.votes) < 50 else "differs")
                rows.append({
                    "year": year, "election_type": etype, "final_snapshot": snapshot,
                    "contest": r.contest, "sov_contest": sov_contests.get(match, pd.NA),
                    "candidate_or_option": r.candidate_or_option,
                    "snapshot_votes": r.votes,
                    "sov_votes": pd.NA if sov_votes is None else int(sov_votes),
                    "delta": pd.NA if sov_votes is None else int(r.votes - sov_votes),
                    "status": status,
                })
    return pd.DataFrame(rows)


def vote_counting_markdown(vc: pd.DataFrame) -> list[str]:
    """Report-only section for reconciliation.md."""
    if vc.empty:
        return []
    lines = [
        "## Election-night final snapshot vs. Statement of Votes (report only)",
        "",
        "Compares the last election-night web update in "
        "`data/processed/vote-counting/` with the certified SoV, candidate by candidate. "
        "The final web update usually precedes certification, so differences are "
        "**expected** and are not counted as mismatches above. Full detail: "
        "[`vote-counting-vs-sov.csv`](vote-counting-vs-sov.csv).",
        "",
        "| election | final web update | match | near_match (<50) | differs | not in SoV | "
        "web total | SoV total |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (year, etype), g in vc.groupby(["year", "election_type"]):
        n = g["status"].value_counts()
        both = g.dropna(subset=["sov_votes"])
        lines.append(
            f"| {year} {etype} | {g['final_snapshot'].iloc[0]} | {n.get('match', 0)} | "
            f"{n.get('near_match', 0)} | {n.get('differs', 0)} | "
            f"{n.get('contest_not_in_sov', 0) + n.get('candidate_not_in_sov', 0)} | "
            f"{int(both['snapshot_votes'].sum()):,} | {int(both['sov_votes'].sum()):,} |")
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int)
    ap.add_argument("--source", choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    args = ap.parse_args(argv)

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

    vc = reconcile_vote_counting()
    if not vc.empty:
        vc.to_csv(VOTE_COUNTING_VS_SOV_CSV, index=False)
        md_lines += vote_counting_markdown(vc)
        print(f"vote-counting vs SoV: {len(vc)} candidate rows "
              f"({(vc['status'] == 'match').sum()} exact matches; report only)")

    (AUDIT / "reconciliation.md").write_text("\n".join(md_lines))
    print(f"\nwrote data/audit/reconciliation.md and reconciliation.csv "
          f"({len(all_recon)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
