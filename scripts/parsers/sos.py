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

from ..schema import SourceMeta
from .common import (
    add_provenance, clean_cols, infer_contest_type,
    normalize_choice, normalize_party, precinct_id_str,
)


def _normalize_county(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.upper()


def _parse_unified(df: pd.DataFrame, target_county: str) -> pd.DataFrame:
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
        infer_contest_type(c, ch) for c, ch in zip(out["contest"], out["candidate_or_option"])
    ]
    return out


def _parse_split(df: pd.DataFrame, target_county: str) -> pd.DataFrame:
    """2012-2020 schema: candidate votes vs. yes/no votes in separate columns."""
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

    rows: list[pd.DataFrame] = []

    # Candidate rows: where _cand_votes is non-null.
    if "_cand_votes" in sub.columns:
        cand_mask = sub["_cand_votes"].notna()
        cand = pd.DataFrame()
        cand["precinct_id"] = sub.loc[cand_mask, "_precinct"].map(precinct_id_str)
        cand["precinct_name"] = pd.NA
        cand["contest"] = sub.loc[cand_mask, "_contest"].astype("string").str.strip()
        cand["candidate_or_option"] = (
            sub.loc[cand_mask, "_candidate"].astype("string").str.strip().map(normalize_choice)
        )
        cand["party"] = (
            sub.loc[cand_mask, "_party"].map(normalize_party)
            if "_party" in sub.columns else pd.NA
        )
        cand["votes"] = pd.to_numeric(sub.loc[cand_mask, "_cand_votes"], errors="coerce")
        cand["active_voters"] = pd.NA
        cand["ballots_cast"] = pd.NA
        cand["contest_type"] = [
            infer_contest_type(c, ch) for c, ch in zip(cand["contest"], cand["candidate_or_option"])
        ]
        rows.append(cand)

    # Yes/No rows: split into two long records each.
    if "_yes_votes" in sub.columns:
        measure_mask = sub["_yes_votes"].notna() | sub.get("_no_votes", pd.Series(dtype="float64")).notna()
        measure_base = sub[measure_mask]
        # Deduplicate at (precinct, contest) — many rows repeat the same Yes/No.
        keys = ["_precinct", "_contest"]
        measure_dedup = measure_base.drop_duplicates(subset=keys)
        for vote_col, choice_label in [("_yes_votes", "Yes"), ("_no_votes", "No")]:
            if vote_col not in measure_dedup.columns:
                continue
            block = pd.DataFrame()
            block["precinct_id"] = measure_dedup["_precinct"].map(precinct_id_str)
            block["precinct_name"] = pd.NA
            block["contest"] = measure_dedup["_contest"].astype("string").str.strip()
            block["candidate_or_option"] = choice_label
            block["party"] = pd.NA
            block["votes"] = pd.to_numeric(measure_dedup[vote_col], errors="coerce")
            block["active_voters"] = pd.NA
            block["ballots_cast"] = pd.NA
            block["contest_type"] = [
                infer_contest_type(c, choice_label) for c in block["contest"]
            ]
            rows.append(block)

    if not rows:
        return pd.DataFrame()

    out = pd.concat(rows, ignore_index=True)
    out = out.dropna(subset=["precinct_id", "contest", "candidate_or_option", "votes"])
    return out


def parse(path: Path, meta: SourceMeta, target_county: str = "Boulder") -> pd.DataFrame:
    df = pd.read_excel(path, engine="openpyxl", sheet_name=0)
    df = clean_cols(df)
    cols = {c.lower().strip() for c in df.columns}

    if "candidate votes" in cols:
        out = _parse_split(df, target_county)
    else:
        out = _parse_unified(df, target_county)

    if out.empty:
        raise ValueError(f"{path.name}: no rows matched county={target_county!r}")

    return add_provenance(out, meta)
