"""
Colorado Secretary of State precinct-results parser (2004-2020).

Two file generations:

- 2004-2010: 9-13 columns. Single 'Votes' column. Year column may be 4-digit or
  string. County names are uppercase with trailing whitespace ('BOULDER    ').
  Candidate column is 'Candidate' or 'Candidate/Yes or No'.

- 2012-2020: 11 columns. Separate 'Candidate Votes', 'Yes Votes', 'No Votes'.
  County names are title-case ('Boulder'). Office column is 'Office/Issue/Judgeship'.

Both generations have NO precinct_name (only the numeric 10-digit precinct_id)
and NO ballots_cast (only candidate votes). Those fields stay null on SOS rows.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..reject import Rejector
from ..reject import register as register_rejector
from ..schema import SourceMeta
from .common import (
    RETENTION_RE,
    add_provenance,
    clean_cols,
    infer_contest_type,
    normalize_choice,
    normalize_party,
    precinct_id_str,
    read_excel,
)


def _normalize_county(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.upper()


def _parse_unified(df: pd.DataFrame, target_county: str, rejector: Rejector | None = None) -> pd.DataFrame:
    """2004-2010 schema: one Votes column, candidates and Yes/No mixed."""
    # Standardize column names.
    rename = {}
    for c in df.columns:
        lo = c.lower().strip()
        if lo == "county":
            rename[c] = "_county"
        elif lo == "precinct":
            rename[c] = "_precinct"
        elif lo in {"office/ballot issue", "office/issue/judgeship", "office/question"}:
            rename[c] = "_contest"
        elif lo in {"candidate/yes or no", "candidate"}:
            rename[c] = "_choice"
        elif lo == "party":
            rename[c] = "_party"
        elif lo == "votes":
            rename[c] = "_votes"
    df = df.rename(columns=rename)

    mask = _normalize_county(df["_county"]) == target_county.upper()
    sub = df[mask].copy()

    out = pd.DataFrame()
    out["precinct_id"] = sub["_precinct"].map(precinct_id_str)
    out["precinct_name"] = pd.NA
    out["contest"] = sub["_contest"].astype("string").str.strip()
    out["candidate_or_option"] = sub["_choice"].map(normalize_choice).astype("string").str.strip()
    out["party"] = sub["_party"].map(normalize_party) if "_party" in sub.columns else pd.NA
    out["votes"] = pd.to_numeric(sub["_votes"], errors="coerce")
    out["active_voters"] = pd.NA
    out["ballots_cast"] = pd.NA
    out["contest_type"] = [
        infer_contest_type(c, ch) for c, ch in zip(out["contest"], out["candidate_or_option"], strict=True)
    ]
    return out


def _parse_split(df: pd.DataFrame, target_county: str, rejector: Rejector | None = None) -> pd.DataFrame:
    """2012-2020 schema: candidate votes vs. yes/no votes in separate columns.

    Every row in these files has all three vote columns filled, with ``0``
    where a column doesn't apply, so "not null" can't tell a candidate row
    from a Yes/No row (#17). Instead each row is classified by what it is:

    - ``Candidate`` null → a ballot measure: emit ``Yes`` / ``No`` rows.
    - ``Candidate`` set → classify the (contest, candidate) pair across the
      whole county: Yes/No votes anywhere → a judge up for retention;
      candidate votes anywhere → a candidate race. A pair with zero votes in
      every column falls back to the party (candidates have one, judges
      don't) and then to the retention regex.

    Several judges share one contest title ("Court of Appeals") and the
    judge's name sits in ``Candidate`` (#16), so retention rows are written as
    ``contest = "{office} - {judge}"`` with ``Yes`` / ``No`` options — the same
    shape the Boulder County files and the 2004-2010 SOS files use — and every
    judge's votes survive.
    """
    rename = {}
    for c in df.columns:
        lo = c.lower().strip()
        if lo == "county":
            rename[c] = "_county"
        elif lo == "precinct":
            rename[c] = "_precinct"
        elif lo in {"office/issue/judgeship", "office/ballot issue"}:
            rename[c] = "_contest"
        elif lo == "candidate":
            rename[c] = "_candidate"
        elif lo == "party":
            rename[c] = "_party"
        elif lo == "candidate votes":
            rename[c] = "_cand_votes"
        elif lo == "yes votes":
            rename[c] = "_yes_votes"
        elif lo == "no votes":
            rename[c] = "_no_votes"
    df = df.rename(columns=rename)

    mask = _normalize_county(df["_county"]) == target_county.upper()
    sub = df[mask].copy()
    for col in ("_candidate", "_party"):
        if col not in sub.columns:
            sub[col] = pd.NA
    for col in ("_cand_votes", "_yes_votes", "_no_votes"):
        sub[col] = pd.to_numeric(sub[col], errors="coerce") if col in sub.columns else pd.NA
    sub["_contest"] = sub["_contest"].astype("string").str.strip()
    sub["_candidate"] = sub["_candidate"].astype("string").str.strip().replace("", pd.NA)

    yesno_total = sub["_yes_votes"].fillna(0) + sub["_no_votes"].fillna(0)
    sub["_yn_total"] = yesno_total
    sub["_cv_total"] = sub["_cand_votes"].fillna(0)
    named = sub["_candidate"].notna()

    # Per-(contest, candidate) classification over the whole county, so a
    # judge's 0-vote precinct is still a retention row and a candidate's
    # 0-vote precinct is still a candidate row.
    pair = (
        sub[named]
        .groupby(["_contest", "_candidate"], dropna=False)
        .agg(yn=("_yn_total", "sum"), cv=("_cv_total", "sum"),
             has_party=("_party", lambda s: s.notna().any()))
    )

    def _is_yesno(r) -> bool:
        if r.yn > 0:
            return True
        if r.cv > 0 or r.has_party:
            return False
        return bool(RETENTION_RE.search(str(r.name[0])))

    yesno_pairs = {k for k, r in pair.iterrows() if _is_yesno(r)}
    pair_key = pd.Series(list(zip(sub["_contest"], sub["_candidate"], strict=True)), index=sub.index)
    is_yesno_row = ~named | pair_key.map(lambda k: k in yesno_pairs)

    rows: list[pd.DataFrame] = []

    cand_rows = sub[~is_yesno_row]
    if not cand_rows.empty:
        cand = pd.DataFrame(index=cand_rows.index)
        cand["precinct_id"] = cand_rows["_precinct"].map(precinct_id_str)
        cand["precinct_name"] = pd.NA
        cand["contest"] = cand_rows["_contest"]
        cand["candidate_or_option"] = cand_rows["_candidate"].map(normalize_choice)
        cand["party"] = cand_rows["_party"].map(normalize_party)
        cand["votes"] = cand_rows["_cand_votes"]
        rows.append(cand)

    yn_rows = sub[is_yesno_row]
    if not yn_rows.empty:
        contest = yn_rows["_contest"].where(
            yn_rows["_candidate"].isna(),
            yn_rows["_contest"] + " - " + yn_rows["_candidate"],
        )
        for vote_col, choice_label in [("_yes_votes", "Yes"), ("_no_votes", "No")]:
            block = pd.DataFrame(index=yn_rows.index)
            block["precinct_id"] = yn_rows["_precinct"].map(precinct_id_str)
            block["precinct_name"] = pd.NA
            block["contest"] = contest
            block["candidate_or_option"] = choice_label
            block["party"] = pd.NA
            block["votes"] = yn_rows[vote_col]
            rows.append(block)

    if not rows:
        return pd.DataFrame()

    out = pd.concat(rows, ignore_index=True)
    out["active_voters"] = pd.NA
    out["ballots_cast"] = pd.NA
    out["contest_type"] = [
        infer_contest_type(c, ch)
        for c, ch in zip(out["contest"], out["candidate_or_option"], strict=True)
    ]
    if rejector is not None:
        out = rejector.drop_na_with_reject(
            out,
            required=["precinct_id", "contest", "candidate_or_option", "votes"],
            reason="missing_required_field",
        )
    else:
        out = out.dropna(subset=["precinct_id", "contest", "candidate_or_option", "votes"])
    return out


def parse(path: Path, meta: SourceMeta, target_county: str = "Boulder") -> pd.DataFrame:
    rejector = Rejector(
        source_file=path.name,
        election_year=meta.election_year,
        data_source=meta.data_source,
    )
    register_rejector(rejector)

    df = read_excel(path, sheet_name=0)
    df = clean_cols(df)
    cols = {c.lower().strip() for c in df.columns}

    # Turnout-only files (e.g. 2024 SOS PrecinctVoterTurnout.xlsx) report
    # ballots-cast and active-voter totals without any candidate or contest
    # detail. They don't fit the harmonized schema, so we emit an empty frame
    # with a provenance note so downstream tools know we saw the file but
    # couldn't extract candidate rows.
    candidate_cols = {"candidate", "candidate/yes or no", "office/issue/judgeship",
                      "office/ballot issue", "office/question"}
    if not (cols & candidate_cols):
        empty = pd.DataFrame()
        return add_provenance(
            empty, meta,
            extraction_notes=(
                f"{path.name} is a turnout-only file (no candidate or contest "
                "columns); harmonized schema requires candidate-level detail. "
                "Use the raw file in data/original/ if you need turnout figures."
            ),
        )

    if "candidate votes" in cols:
        out = _parse_split(df, target_county, rejector=rejector)
    else:
        out = _parse_unified(df, target_county, rejector=rejector)

    if out.empty:
        raise ValueError(f"{path.name}: no rows matched county={target_county!r}")

    return add_provenance(out, meta)
