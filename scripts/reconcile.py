"""
Reconciliation audit: processed CSVs vs. the original published files.

Two levels, both written to data/audit/:

1. **Top-line contests** (``reconciliation.csv``). For each (year, source),
   sum vote totals by canonical contest (``data/lookups/contest-aliases.json``)
   in the ORIGINAL file and in the processed CSV, and compare.
2. **Contest × candidate** (``reconciliation-candidates.csv``). The same
   comparison for every (contest, candidate_or_option) key in the file, so a
   parser that drops one judge's retention votes (#16), adds phantom 0-vote
   rows (#17), misaligns panel columns (#20) or attaches votes to the wrong
   PDF labels (#23) shows up even when the contest isn't a top-line office.
   Two structural checks ride along per file: duplicate
   (precinct, contest, candidate) keys, and contests that mix Yes/No options
   with named candidates.

The "original" side for each generation:

- SOS 2004-2020 and Boulder 2013-2025: the vote columns of the raw workbook.
- Boulder 2008-2012 (panel XLS): the county's own ``Totals`` row for each
  candidate (``parsers/boco_panel.py:published_totals``).
- Boulder 2005/2007/2009 (PDF): the ``Totals:`` line printed at the end of
  each candidate group (``parsers/boco_pdf.py:published_totals``).

Status per row: ``match`` (delta 0), ``near_match`` (|delta| < 50) or
``mismatch`` (|delta| >= 50). A non-zero delta is not always a bug — e.g. the
SOS files can differ slightly from the county's certified totals — but every
``mismatch`` should be explained before publishing.

Output:
- data/audit/reconciliation.md            — full Markdown report
- data/audit/reconciliation.csv           — top-line rows
- data/audit/reconciliation-candidates.csv — contest × candidate rows
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
    AUDIT,
    BOULDER_COUNTY,
    LOOKUPS,
    RECONCILIATION_CANDIDATES_CSV,
    RECONCILIATION_CSV,
    RECONCILIATION_MD,
    SECRETARY_OF_STATE,
    VOTE_COUNTING_CONTESTS_CSV,
    VOTE_COUNTING_VS_SOV_CSV,
    Source,
    original_path,
    sov_csv_path,
)
from .config import (
    SOURCES as ALL_SOURCES,
)
from .logging_setup import get_logger
from .parsers import boco_panel, boco_pdf
from .parsers.common import clean_cols, excel_file, normalize_choice, read_excel

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

def _read_sos_original(path: Path) -> pd.DataFrame | None:
    """SOS files are already long-form; just need to load and filter Boulder.
    Returns None for turnout-only files (no contest column), which have no
    vote totals to reconcile."""
    df = read_excel(path, sheet_name=0)
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
    if county_col and not contest_col:
        log.debug("reconcile.turnout_only", file=path.name)
        return None
    if not (county_col and contest_col):
        raise ValueError(f"{path.name}: missing county/contest columns; have={list(df.columns)}")
    sub = df[df[county_col].astype("string").str.strip().str.upper() == "BOULDER"]
    contest = sub[contest_col].astype("string").str.strip().fillna("")
    cand_col = cols.get("candidate") or cols.get("candidate/yes or no")

    cand = (sub[cand_col].astype("string").str.strip().replace("", pd.NA)
            if cand_col else pd.Series(pd.NA, index=sub.index, dtype="string"))

    # One frame per vote column, keyed the way the harmonized data keys them.
    # Candidate votes keep the candidate's name. Yes/No columns become
    # "Yes"/"No" rows; in the 2012-2020 split layout a judge up for retention
    # is named in the Candidate column under a shared office title ("Court of
    # Appeals"), so those rows key on "{office} - {judge}". Every vote column
    # is read (including the 0s the split layout writes where a column
    # doesn't apply); zero-total keys are ignored by the comparison.
    frames: list[pd.DataFrame] = []
    if votes_col:
        m = sub[votes_col].notna()
        frames.append(pd.DataFrame({
            "contest": contest[m],
            "candidate_or_option": cand[m].fillna("") if cand_col else "",
            "party": sub.loc[m, party_col].astype("string").str.strip() if party_col else None,
            "votes": pd.to_numeric(sub.loc[m, votes_col], errors="coerce"),
        }))
    yn_contest = contest.where(cand.isna(), contest + " - " + cand.fillna(""))
    for col, label in ((yes_col, "Yes"), (no_col, "No")):
        if col:
            m = sub[col].notna()
            frames.append(pd.DataFrame({
                "contest": yn_contest[m], "candidate_or_option": label, "party": None,
                "votes": pd.to_numeric(sub.loc[m, col], errors="coerce"),
            }))
    if not frames:
        return pd.DataFrame(columns=["contest", "candidate_or_option", "party", "votes"])
    return pd.concat(frames, ignore_index=True)


def _read_boco_tidy_original(path: Path) -> pd.DataFrame:
    """Boulder tidy years (2013-2025). Cheap reader that just sums Total Votes
    by Contest Title × Choice Name."""
    xl = excel_file(path)

    frames = []
    for sheet in xl.sheet_names:
        if sheet.lower() in {"summary_of_results", "summary of results"}:
            continue
        raw = xl.parse(sheet)
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
    """Original-side frame (contest / candidate_or_option / party / votes) for
    one source, or None if the raw file is missing or has no vote totals."""
    from .clean import BOCO_PANEL_YEARS, BOCO_PDF_YEARS

    path = original_path(source.data_source, source.local_filename)
    if not path.exists():
        return None
    if source.data_source == "secretary_of_state":
        return _read_sos_original(path)
    if source.year in BOCO_PDF_YEARS:
        return boco_pdf.published_totals(path)
    if source.year in BOCO_PANEL_YEARS:
        return boco_panel.published_totals(path, source.year)
    return _read_boco_tidy_original(path)


def _processed_path(s: Source) -> Path:
    return sov_csv_path(s.year, s.election_type, s.data_source)


def _read_processed(source: Source) -> pd.DataFrame | None:
    proc_path = _processed_path(source)
    if not proc_path.exists():
        return None
    proc = pd.read_csv(proc_path, dtype={"precinct_id": "string"}, low_memory=False)
    proc["votes"] = pd.to_numeric(proc["votes"], errors="coerce")
    return proc


_MISSING = object()


def reconcile_source(source: Source, patterns: list[ContestPattern],
                     orig: object = _MISSING) -> pd.DataFrame:
    """Return a per-canonical-contest reconciliation frame for one source.
    Pass `orig` (from _read_original) to avoid re-reading the raw file."""
    proc = _read_processed(source)
    if proc is None:
        return pd.DataFrame()
    if orig is _MISSING:
        orig = _read_original(source)

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
        orig = orig.assign(canonical=orig["contest"].map(lambda t: _match_canonical(t, patterns)))
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


# ----- Contest × candidate reconciliation -----

def _status(delta: int) -> str:
    return "match" if delta == 0 else ("near_match" if abs(int(delta)) < 50 else "mismatch")


def _option_key(text: object) -> str:
    return _name_key(normalize_choice(text))


def _final_rcv_only(proc: pd.DataFrame) -> pd.DataFrame:
    """Keep each RCV candidate's '| Final' row (the original's Total Votes),
    with the suffix stripped; drop the per-round rows."""
    rcv = proc["contest_type"] == "ranked_choice"
    opt = proc["candidate_or_option"].astype("string")
    final = opt.str.contains(r"\|\s*Final\s*$", na=False, regex=True)
    out = proc[~rcv | final].copy()
    out.loc[rcv & final, "candidate_or_option"] = opt[rcv & final].str.replace(
        r"\s*\|\s*Final\s*$", "", regex=True)
    return out


def structural_checks(proc: pd.DataFrame) -> dict[str, object]:
    """Per-file checks that a vote-total comparison can't see: duplicate
    (precinct, contest, candidate) keys (#23) and contests that mix Yes/No
    options with named candidates (#17's phantom rows have 0 votes, so they
    never move a total)."""
    key = ["precinct_id", "contest", "candidate_or_option"]
    dup = int(proc.duplicated(key).sum())
    plain = proc[proc["contest_type"] != "ranked_choice"]
    opts = plain.groupby("contest")["candidate_or_option"].agg(lambda s: set(s.dropna()))
    mixed = sorted(c for c, v in opts.items() if (v & {"Yes", "No"}) and (v - {"Yes", "No"}))
    return {"duplicate_keys": dup, "mixed_contests": len(mixed),
            "mixed_examples": "; ".join(mixed[:3])}


CANDIDATE_COLUMNS = ["year", "election_type", "data_source", "contest", "candidate_or_option",
                     "original_votes", "processed_votes", "delta", "status", "note"]


def reconcile_candidates(source: Source, orig: object = _MISSING
                         ) -> tuple[pd.DataFrame, dict[str, object]]:
    """Contest × candidate comparison for one source.

    Returns (rows, checks): one row per (contest, candidate_or_option) key with
    a non-zero total on either side, and the structural checks for the
    processed file. Keys are compared case-, space- and punctuation-
    insensitively, with Yes/No spellings normalized; RCV contests are compared
    on their '| Final' rows.
    """
    proc = _read_processed(source)
    if proc is None:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS), {}
    checks = structural_checks(proc)
    if orig is _MISSING:
        orig = _read_original(source)
    if orig is None:
        checks["status"] = "no_original"
        return pd.DataFrame(columns=CANDIDATE_COLUMNS), checks

    def _keyed(df: pd.DataFrame) -> pd.DataFrame:
        df = df.dropna(subset=["contest", "candidate_or_option"])
        df = df.assign(ck=df["contest"].map(_name_key),
                       kk=df["candidate_or_option"].map(_option_key))
        return df.groupby(["ck", "kk"]).agg(
            contest=("contest", "first"), candidate_or_option=("candidate_or_option", "first"),
            votes=("votes", "sum"))

    o = _keyed(orig)
    p = _keyed(_final_rcv_only(proc))
    j = o.join(p, how="outer", lsuffix="_o", rsuffix="_p")
    j["original_votes"] = j["votes_o"].fillna(0).astype("int64")
    j["processed_votes"] = j["votes_p"].fillna(0).astype("int64")
    j = j[(j["original_votes"] != 0) | (j["processed_votes"] != 0)].copy()
    j["contest"] = j["contest_p"].fillna(j["contest_o"])
    j["candidate_or_option"] = j["candidate_or_option_p"].fillna(j["candidate_or_option_o"])
    j["delta"] = j["processed_votes"] - j["original_votes"]
    j["status"] = j["delta"].map(_status)
    j["note"] = ""
    j.loc[j["votes_p"].isna(), "note"] = "only in original"
    j.loc[j["votes_o"].isna(), "note"] = "only in processed"
    j["year"] = source.year
    j["election_type"] = source.election_type
    j["data_source"] = source.data_source
    out = j.reset_index(drop=True)[CANDIDATE_COLUMNS]
    checks["status"] = "compared"
    return out.sort_values(["contest", "candidate_or_option"], kind="stable"), checks


def candidate_markdown(cand: pd.DataFrame, checks: list[dict]) -> list[str]:
    """Report section for reconciliation.md."""
    lines = [
        "## Contest × candidate reconciliation",
        "",
        "Every (contest, candidate_or_option) key in each file, original vs. processed "
        "(RCV contests on their `| Final` rows). Full detail: "
        "[`reconciliation-candidates.csv`](reconciliation-candidates.csv). The structural "
        "columns count duplicate (precinct, contest, candidate) keys and contests that mix "
        "Yes/No options with named candidates; both should be 0.",
        "",
        "| file | keys | match | near_match | mismatch | duplicate keys | mixed contests |",
        "|---|---|---|---|---|---|---|",
    ]
    by_file = {(c["year"], c["election_type"], c["data_source"]): c for c in checks}
    for k in sorted(by_file):
        c = by_file[k]
        g = cand[(cand["year"] == k[0]) & (cand["election_type"] == k[1])
                 & (cand["data_source"] == k[2])]
        n = g["status"].value_counts()
        if c.get("status") == "no_original":
            counts = "— | — | — | —"
        else:
            counts = (f"{len(g):,} | {n.get('match', 0):,} | {n.get('near_match', 0):,} | "
                      f"{n.get('mismatch', 0):,}")
        lines.append(f"| {k[0]} {k[1]} {k[2]} | {counts} | {c['duplicate_keys']:,} | "
                     f"{c['mixed_contests']:,} |")
    lines.append("")
    bad = cand[cand["status"] != "match"]
    if not bad.empty:
        lines += [f"### Keys that differ ({len(bad):,})", "",
                  "| file | contest | candidate / option | original | processed | delta | status |",
                  "|---|---|---|---|---|---|---|"]
        for r in bad.head(200).itertuples(index=False):
            lines.append(
                f"| {r.year} {r.election_type} {r.data_source} | {r.contest} | "
                f"{r.candidate_or_option} | {r.original_votes:,} | {r.processed_votes:,} | "
                f"{r.delta:+,} | `{r.status}`{' (' + r.note + ')' if r.note else ''} |")
        if len(bad) > 200:
            lines.append(f"| … {len(bad) - 200:,} more in the CSV | | | | | | |")
        lines.append("")
    return lines


# ----- Cross-source: Boulder County SoV vs. the SOS file for the same election -----

def reconcile_cross_source() -> pd.DataFrame:
    """For each general election both sources publish, compare Boulder's and the
    SOS's precinct-summed totals for every (contest, candidate) key whose
    names agree in both files (case/punctuation-insensitive). Report-only: the
    two files title most contests differently, so only the name-matched keys
    are compared — but those should agree exactly, which makes this an
    independent check on the Boulder parsers (notably the 2008/2010 panel
    files, #20)."""
    by_key = {(s.year, s.election_type): s for s in SECRETARY_OF_STATE}
    rows = []
    for b in BOULDER_COUNTY:
        sos = by_key.get((b.year, b.election_type))
        if sos is None:
            continue
        pb, ps = _read_processed(b), _read_processed(sos)
        if pb is None or ps is None or pb.empty or ps.empty:
            continue
        totals = []
        for df in (pb, ps):
            df = _final_rcv_only(df)
            totals.append(df.assign(ck=df["contest"].map(_name_key),
                                    kk=df["candidate_or_option"].map(_option_key))
                          .groupby(["ck", "kk"])["votes"].sum())
        j = pd.concat(totals, axis=1, keys=["boulder", "sos"]).dropna()
        j = j[(j["boulder"] != 0) | (j["sos"] != 0)]
        d = (j["boulder"] - j["sos"]).abs()
        rows.append({"year": b.year, "election_type": b.election_type,
                     "keys_matched_by_name": len(j),
                     "contests_matched_by_name": j.index.get_level_values(0).nunique(),
                     "exact": int((d == 0).sum()), "near_match": int(((d > 0) & (d < 50)).sum()),
                     "differ": int((d >= 50).sum()),
                     "boulder_votes": int(j["boulder"].sum()), "sos_votes": int(j["sos"].sum())})
    return pd.DataFrame(rows)


def cross_source_markdown(xs: pd.DataFrame) -> list[str]:
    if xs.empty:
        return []
    lines = [
        "## Boulder County SoV vs. SOS file, same election (report only)",
        "",
        "Precinct-summed totals for every (contest, candidate) key whose names agree in "
        "both sources. The two publishers title most contests differently, so only "
        "name-matched keys are compared; those should agree exactly.",
        "",
        "| election | contests matched | keys matched | exact | near_match (<50) | differ | "
        "Boulder total | SOS total |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in xs.itertuples(index=False):
        lines.append(f"| {r.year} {r.election_type} | {r.contests_matched_by_name} | "
                     f"{r.keys_matched_by_name} | {r.exact} | {r.near_match} | {r.differ} | "
                     f"{r.boulder_votes:,} | {r.sos_votes:,} |")
    lines.append("")
    return lines


# ----- Election-night snapshots vs. the certified Statement of Votes -----

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

    path = VOTE_COUNTING_CONTESTS_CSV
    if not path.exists():
        return pd.DataFrame()
    web = pd.read_csv(path, low_memory=False)
    web = web[web["is_final_snapshot"].astype(bool)]
    # RCV: compare the final-round tallies (the SoV's '| Final' rows).
    web = web[(web["contest_type"] != "ranked_choice")
              | web["candidate_or_option"].str.endswith("| Final")]

    rows: list[dict] = []
    for (year, etype), w in web.groupby(["election_year", "election_type"]):
        sov_path = sov_csv_path(year, etype, "boulder_county")
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


def run(pool: list[Source]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Reconcile every source in `pool`. Returns (top-line rows, contest ×
    candidate rows, per-file structural checks). Each raw file is read once."""
    patterns = _load_patterns()
    top: list[pd.DataFrame] = []
    cand: list[pd.DataFrame] = []
    checks: list[dict] = []
    for s in pool:
        label = f"{s.year}-{s.election_type}-{s.data_source}"
        try:
            orig = _read_original(s)
            r = reconcile_source(s, patterns, orig)
            c, chk = reconcile_candidates(s, orig)
        except Exception as e:
            print(f"FAIL {label}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if r.empty and not chk:
            continue
        if not r.empty:
            top.append(r)
        if chk:
            checks.append({"year": s.year, "election_type": s.election_type,
                           "data_source": s.data_source, **chk})
        if not c.empty:
            cand.append(c)
        print(f"OK   {label}  contests={len(r)}  mismatches={(r['status'] == 'mismatch').sum() if not r.empty else 0}"
              f"  candidate-keys={len(c)}  candidate-mismatches={(c['status'] == 'mismatch').sum()}"
              f"  dup-keys={chk.get('duplicate_keys', 0)}  mixed={chk.get('mixed_contests', 0)}")
    top_df = pd.concat(top, ignore_index=True) if top else pd.DataFrame()
    cand_df = pd.concat(cand, ignore_index=True) if cand else pd.DataFrame(columns=CANDIDATE_COLUMNS)
    return top_df, cand_df, checks


def _key_set(df: pd.DataFrame) -> pd.Series:
    return pd.Series(list(zip(df["year"].astype(int), df["election_type"], df["data_source"],
                              strict=True)), index=df.index, dtype=object)


def _merge_with_existing(pool: list[Source], top: pd.DataFrame, cand: pd.DataFrame,
                         checks: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    done = {(s.year, s.election_type, s.data_source) for s in pool}
    order = {(s.year, s.election_type, s.data_source): i for i, s in enumerate(ALL_SOURCES)}

    def merge(path: Path, new: pd.DataFrame) -> pd.DataFrame:
        if not path.exists():
            return new
        old = pd.read_csv(path, keep_default_na=False, na_values=[""])
        if old.empty:
            return new
        old = old[~_key_set(old).isin(done)]
        out = pd.concat([old, new], ignore_index=True) if len(new) else old
        rank = _key_set(out).map(lambda k: order.get(k, len(order)))
        return out.assign(_r=rank).sort_values("_r", kind="stable").drop(columns="_r")

    top = merge(RECONCILIATION_CSV, top)
    cand = merge(RECONCILIATION_CANDIDATES_CSV, cand)
    if "note" in cand.columns:
        cand["note"] = cand["note"].fillna("")
    compared = set(_key_set(cand)) if len(cand) else set()
    for s in ALL_SOURCES:
        key = (s.year, s.election_type, s.data_source)
        if key in done:
            continue
        proc = _read_processed(s)
        if proc is None:
            continue
        checks.append({"year": s.year, "election_type": s.election_type,
                       "data_source": s.data_source, **structural_checks(proc),
                       "status": "compared" if key in compared else "no_original"})
    return top, cand, checks


def report_markdown(all_recon: pd.DataFrame, cand: pd.DataFrame, checks: list[dict],
                    vc: pd.DataFrame, xs: pd.DataFrame | None = None) -> str:
    n_cand_bad = int((cand["status"] == "mismatch").sum())
    n_struct = sum(int(c["duplicate_keys"]) + int(c["mixed_contests"]) for c in checks)
    md_lines = [
        "# Reconciliation audit",
        "",
        "Compares vote totals between the original published files and the harmonized",
        "CSVs in `data/processed/statements-of-votes/`, first for **top-line contests**",
        "and then for **every contest × candidate** key. Generated by",
        "[`scripts/reconcile.py`](../../scripts/reconcile.py).",
        "",
        "The original side is the raw workbook's vote columns (SOS; Boulder 2013+), the",
        "county's own `Totals` row per candidate (Boulder panel XLS, 2008-2012), or the",
        "`Totals:` line printed per candidate group (Boulder PDFs, 2005/2007/2009).",
        "",
        "**Status legend:**",
        "- `match` — original total equals processed total exactly.",
        "- `near_match` — totals differ by < 50 votes (small counting reconciliation, "
        "usually safe).",
        "- `mismatch` — totals differ by ≥ 50 votes. Investigate.",
        "- `not_in_file` — the canonical contest pattern matched nothing in either file.",
        "",
        f"**Contest × candidate:** {len(cand):,} keys compared, "
        f"{int((cand['status'] == 'match').sum()):,} match, "
        f"{int((cand['status'] == 'near_match').sum()):,} near_match, "
        f"**{n_cand_bad:,} mismatch**; structural issues (duplicate keys + mixed "
        f"contests): **{n_struct:,}**.",
        "",
        f"**Top-line summary across all {len(all_recon)} contest-source rows:**",
        "",
    ]
    status_counts = all_recon["status"].value_counts().sort_index()
    md_lines.append("| status | rows |")
    md_lines.append("|---|---|")
    for status, n in status_counts.items():
        md_lines.append(f"| {status} | {n} |")
    md_lines.append("")

    md_lines += candidate_markdown(cand, checks)

    md_lines += ["## Top-line contests", ""]
    # Group by (year, source) — one table per pair.
    for (year, source, etype), grp in all_recon.groupby(["year", "data_source", "election_type"]):
        md_lines.append(f"### {year} {etype} — {source}")
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

    if xs is not None:
        md_lines += cross_source_markdown(xs)
    md_lines += vote_counting_markdown(vc)
    return "\n".join(md_lines)


def _election_arg(value: str) -> tuple[int, str]:
    from .sources import parse_election_key
    try:
        return parse_election_key(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int)
    ap.add_argument("-e", "--election", type=_election_arg, metavar="KEY",
                    help="Only this election, as an election key, e.g. 2024-general")
    ap.add_argument("--source", choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    ap.add_argument("--check", action="store_true",
                    help="Write nothing; exit 1 if any top-line or contest × candidate "
                         "`mismatch`, duplicate key or mixed contest is found (CI uses this)")
    args = ap.parse_args(argv)

    if args.source == "boulder_county":
        pool = BOULDER_COUNTY
    elif args.source == "secretary_of_state":
        pool = SECRETARY_OF_STATE
    else:
        pool = ALL_SOURCES
    if args.year:
        pool = [s for s in pool if s.year == args.year]
    if args.election:
        pool = [s for s in pool if (s.year, s.election_type) == args.election]

    AUDIT.mkdir(parents=True, exist_ok=True)
    all_recon, cand, checks = run(pool)
    if all_recon.empty and cand.empty:
        print("No reconciliation rows generated.", file=sys.stderr)
        return 2
    if args.check:
        n_bad = int((all_recon["status"] == "mismatch").sum()) if len(all_recon) else 0
        n_cand_bad = int((cand["status"] == "mismatch").sum())
        n_struct = sum(int(c["duplicate_keys"]) + int(c["mixed_contests"]) for c in checks)
        print(f"mismatches: top-line={n_bad} candidate={n_cand_bad} structural={n_struct}")
        for r in cand[cand["status"] == "mismatch"].head(20).itertuples(index=False):
            print(f"FAIL  {r.year} {r.election_type} {r.data_source}: {r.contest} / "
                  f"{r.candidate_or_option}: {r.original_votes} → {r.processed_votes}",
                  file=sys.stderr)
        return 1 if (n_bad or n_cand_bad or n_struct) else 0
    if len(pool) < len(ALL_SOURCES):
        # A filtered run updates its own sources' rows and keeps everyone
        # else's, so the shared report always covers the whole dataset (#18).
        all_recon, cand, checks = _merge_with_existing(pool, all_recon, cand, checks)

    all_recon.to_csv(RECONCILIATION_CSV, index=False)
    cand.to_csv(RECONCILIATION_CANDIDATES_CSV, index=False)

    vc = reconcile_vote_counting()
    if not vc.empty:
        vc.to_csv(VOTE_COUNTING_VS_SOV_CSV, index=False)
        print(f"vote-counting vs SoV: {len(vc)} candidate rows "
              f"({(vc['status'] == 'match').sum()} exact matches; report only)")

    xs = reconcile_cross_source()
    RECONCILIATION_MD.write_text(report_markdown(all_recon, cand, checks, vc, xs))
    n_bad = int((all_recon["status"] == "mismatch").sum())
    n_cand_bad = int((cand["status"] == "mismatch").sum())
    n_struct = sum(int(c["duplicate_keys"]) + int(c["mixed_contests"]) for c in checks)
    print(f"\nwrote data/audit/reconciliation.md, reconciliation.csv ({len(all_recon)} rows) "
          f"and reconciliation-candidates.csv ({len(cand)} rows)")
    print(f"mismatches: top-line={n_bad} candidate={n_cand_bad} structural={n_struct}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
