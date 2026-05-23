"""
Boulder County tidy-format SoV parser (2013-2024).

These files are already long-form: one row per (precinct, contest, choice).
The only work is column normalization to the harmonized schema and contest-type
classification. Composite precinct IDs (2015, 2022) are preserved as-is and flagged
in extraction_notes.

2023 has two sheets: 'Plurality' (standard) and 'RCV' (ranked choice). The RCV sheet
gets contest_type='ranked_choice'; each row corresponds to one round's tally for one
candidate.

2013 is an XLSX file with a .xls extension — read with openpyxl, not xlrd.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import SourceMeta
from .common import (
    add_provenance, clean_cols, infer_contest_type,
    normalize_choice, normalize_party, precinct_id_str,
)


# Per-year column name → canonical name aliases.
# After clean_cols() collapses whitespace/newlines, we map known variants here.
_PRECINCT_LONG_ALIASES = {
    "Precinct Name", "Precinct Name (Long)", "Precinct Number",
}
_PRECINCT_SHORT_ALIASES = {
    "Precinct Name (Short)", "Precinct Name Short", "Precinct Name(Short)",
    "Precinct Code",
}
_CONTEST_ALIASES = {"Contest Title", "Contest Name"}
_CHOICE_ALIASES = {"Choice Name", "Candidate Name"}
_PARTY_ALIASES = {"Party"}
_ACTIVE_VOTERS_ALIASES = {"Active Voters"}
_TOTAL_BALLOTS_ALIASES = {"Total Ballots"}
_TOTAL_VOTES_ALIASES = {"Total Votes"}


def _pick(df: pd.DataFrame, aliases: set[str]) -> str | None:
    for c in df.columns:
        if c in aliases:
            return c
    return None


def _read_excel(path: Path, sheet: int | str = 0) -> pd.DataFrame:
    engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
    if path.name == "2013-coordinated-sov.xls":
        engine = "openpyxl"  # mislabeled extension
    return pd.read_excel(path, engine=engine, sheet_name=sheet)


def parse(path: Path, meta: SourceMeta) -> pd.DataFrame:
    """Return harmonized long-form DataFrame for a Boulder tidy-format SoV."""
    notes: list[str] = []

    # Read all sheets, then concatenate (handles 2023's Plurality+RCV split).
    engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
    if path.name == "2013-coordinated-sov.xls":
        engine = "openpyxl"
    xl = pd.ExcelFile(path, engine=engine)

    frames: list[pd.DataFrame] = []
    for sheet in xl.sheet_names:
        if sheet.lower() in {"summary_of_results", "summary of results"}:
            continue
        raw = pd.read_excel(path, engine=engine, sheet_name=sheet)
        if raw.empty:
            continue
        df = clean_cols(raw)
        is_rcv = sheet.upper() == "RCV"

        p_long = _pick(df, _PRECINCT_LONG_ALIASES)
        p_short = _pick(df, _PRECINCT_SHORT_ALIASES)
        contest = _pick(df, _CONTEST_ALIASES)
        choice = _pick(df, _CHOICE_ALIASES)
        party = _pick(df, _PARTY_ALIASES)
        active = _pick(df, _ACTIVE_VOTERS_ALIASES)
        ballots = _pick(df, _TOTAL_BALLOTS_ALIASES)
        votes = _pick(df, _TOTAL_VOTES_ALIASES)

        if not (p_long or p_short) or not contest or not choice or not votes:
            raise ValueError(
                f"{path.name} sheet={sheet!r}: missing required columns "
                f"(p_long={p_long}, p_short={p_short}, contest={contest}, "
                f"choice={choice}, votes={votes}); have={list(df.columns)}"
            )

        out = pd.DataFrame()
        out["precinct_id"] = (df[p_long] if p_long else df[p_short]).map(precinct_id_str)
        out["precinct_name"] = (
            df[p_short].map(precinct_id_str) if p_short else pd.NA
        )
        out["contest"] = df[contest].astype("string").str.strip()
        out["candidate_or_option"] = df[choice].map(normalize_choice).astype("string").str.strip()
        out["party"] = df[party].map(normalize_party) if party else pd.NA
        out["votes"] = pd.to_numeric(df[votes], errors="coerce")
        out["active_voters"] = pd.to_numeric(df[active], errors="coerce") if active else pd.NA
        out["ballots_cast"] = pd.to_numeric(df[ballots], errors="coerce") if ballots else pd.NA

        if is_rcv:
            # Melt per-round columns into rows so each round becomes its own
            # (precinct, contest, candidate, round) tally. Encode round in
            # candidate_or_option as 'Candidate Name | Round N' to keep one
            # canonical schema.
            round_cols = [c for c in df.columns if c.lower().startswith("round ") and c.lower().endswith(" votes")]
            if round_cols:
                rounds = []
                for rc in round_cols:
                    n = rc.split()[1]
                    chunk = out.copy()
                    chunk["candidate_or_option"] = (
                        out["candidate_or_option"].astype("string") + f" | Round {n}"
                    )
                    chunk["votes"] = pd.to_numeric(df[rc], errors="coerce")
                    rounds.append(chunk)
                # Append a "Final" row using Total Votes (so analyses that
                # don't care about rounds can filter on '| Final').
                final_chunk = out.copy()
                final_chunk["candidate_or_option"] = (
                    out["candidate_or_option"].astype("string") + " | Final"
                )
                rounds.append(final_chunk)
                out = pd.concat(rounds, ignore_index=True)
            out["contest_type"] = "ranked_choice"
            notes.append(
                "RCV: candidate_or_option suffixed with '| Round N' for each tabulation round "
                "and '| Final' for the Total Votes column"
            )
        else:
            out["contest_type"] = [
                infer_contest_type(c, ch) for c, ch in zip(out["contest"], out["candidate_or_option"])
            ]

        # Drop rows where precinct_id is missing or where the row is a totals row.
        out = out.dropna(subset=["precinct_id", "contest", "candidate_or_option"])
        out = out[~out["precinct_id"].astype("string").str.lower().isin(
            {"total", "totals", "grand total", "summary", "nan", ""}
        )]

        # Composite precinct flag (2015, 2022)
        if out["precinct_id"].astype("string").str.contains(",", na=False).any():
            notes.append("contains composite precinct IDs (multiple precincts joined, "
                         "comma-separated); votes are reported for the combined unit")

        frames.append(out)

    if not frames:
        raise ValueError(f"{path.name}: no data rows extracted")
    final = pd.concat(frames, ignore_index=True)

    extraction_notes = "; ".join(notes) if notes else None
    return add_provenance(final, meta, extraction_notes=extraction_notes)
