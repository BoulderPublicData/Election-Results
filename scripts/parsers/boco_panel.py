"""
Boulder County panel-format SoV parser (2008, 2010, 2011, 2012).

These XLS files predate the modern tidy export and report results as repeating
"panels" — header block, then a contest title, then a row of column headers
(Precinct, candidate names, etc.), then per-precinct rows, then a totals row,
then the next panel.

The parser walks the sheet and:
  1. Detects panel start by finding a row whose first cell == "Precinct".
  2. Reads back upward to grab the contest title from the cell at column 6
     (or column 0 if column 6 is empty) on the previous row.
  3. Reads downward until the next "Precinct" row, a "Continued" marker, or
     a trailing summary block.
  4. Melts the candidate columns into long form.

For 2011 and 2012 some multi-panel contests (e.g., Presidential Electors with
many candidates) span several blocks; we leave each panel as a separate set of
rows — the same (precinct, contest) keys naturally merge them when filtering.

This is a port of the manual logic in the original Cleaning.ipynb but normalized
to the harmonized schema. The original notebook is preserved in the rewrite as
historical reference.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..reject import Rejector, register as register_rejector
from ..schema import SourceMeta
from .common import (
    add_provenance, clean_col, infer_contest_type, normalize_choice,
    normalize_party, precinct_id_str,
)


def _read_raw(path: Path) -> pd.DataFrame:
    engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
    return pd.read_excel(path, engine=engine, sheet_name=0, header=None)


def _find_panel_starts(raw: pd.DataFrame) -> list[int]:
    """Row indices where column-0 == 'Precinct' (case-insensitive)."""
    col0 = raw.iloc[:, 0].astype("string").str.strip().str.lower()
    return col0.index[col0 == "precinct"].tolist()


_BOILERPLATE_PREFIXES = (
    "precinct", "early voting", "election day", "absentee",
    "total number of voters", "precincts reporting",
    "boulder county", "canvass report", "general election",
    "coordinated election", "primary election", "page ",
)


def _contest_title(raw: pd.DataFrame, start: int) -> str:
    """The contest title sits 1-10 rows above the 'Precinct' header row, typically
    in column 0 or column 6. Walk upward and pick the first non-null, non-boilerplate
    cell. The window is wide because page-break headers can push the title up."""
    for offset in range(1, 11):
        idx = start - offset
        if idx < 0:
            break
        row = raw.iloc[idx]
        for col in (6, 0, 1, 2, 3, 4, 5, 7):
            if col >= raw.shape[1]:
                continue
            val = row.iloc[col]
            if pd.isna(val):
                continue
            text = str(val).strip()
            if not text:
                continue
            lower = text.lower()
            if any(lower.startswith(p) for p in _BOILERPLATE_PREFIXES):
                continue
            if lower in {"continued", "totals", "total", "yes", "no"}:
                continue
            # Date or time stamp strings — skip.
            if "/" in text and len(text) < 25 and any(ch.isdigit() for ch in text):
                continue
            return text
    return f"<unknown contest at row {start}>"


def _panel_rows(raw: pd.DataFrame, start: int, next_start: int | None) -> tuple[pd.DataFrame, list[str]]:
    """Extract the rectangular block under a single panel header.
    Returns (data_df_with_header_row_as_columns, candidate_columns_list)."""
    stop = next_start if next_start else raw.shape[0]
    header = raw.iloc[start]
    block = raw.iloc[start + 1 : stop].copy()
    # Normalize embedded newlines/whitespace in header cells. Original XLS files
    # used multi-line headers ("Absentee\nVoting\nBallots\nCast", "REP\nKen Buck")
    # that must collapse to single-line strings before we can match boilerplate
    # or split party prefixes.
    block.columns = [
        clean_col(c) if pd.notna(c) else f"col_{i}"
        for i, c in enumerate(header)
    ]

    # Drop fully-empty rows
    block = block.dropna(how="all")
    # Drop trailing 'Continued' / 'Totals' rows
    if not block.empty:
        first_col = block.iloc[:, 0].astype("string").str.strip().str.lower().fillna("")
        block = block[~first_col.isin({"continued", "totals", "total", ""})]
    # Drop rows whose precinct isn't numeric-ish
    if not block.empty:
        pmask = block.iloc[:, 0].astype("string").str.match(r"^\d+", na=False)
        block = block[pmask]

    _NON_CANDIDATE_EXACT = {
        "precinct", "totals", "total", "continued",
        "registered voters", "percent turnout",
        "percentturnout",  # legacy when whitespace collapse stripped the space
    }

    def _is_meta_header(c: str) -> bool:
        lo = c.strip().lower()
        if lo in _NON_CANDIDATE_EXACT:
            return True
        # Any "*Ballots Cast" header, regardless of voting-method prefix
        if lo.endswith("ballots cast") or lo.endswith("ballotscast"):
            return True
        if lo.endswith("ballots") or lo.endswith("ballotscast"):
            return True
        return False

    candidate_cols = [
        c for c in block.columns
        if not _is_meta_header(c) and not c.startswith("col_")
    ]
    return block, candidate_cols


def _meta_cols(block: pd.DataFrame) -> dict[str, str]:
    """Identify which column in `block` holds Total Ballots, Active/Registered Voters."""
    lookup = {c.strip().lower(): c for c in block.columns}
    return {
        "ballots_cast": (
            lookup.get("total ballots cast") or lookup.get("totalballots cast")
            or lookup.get("totalballotscast")
        ),
        "active_voters": (
            lookup.get("registered voters") or lookup.get("registeredvoters")
        ),
    }


def parse(path: Path, meta: SourceMeta) -> pd.DataFrame:
    rejector = Rejector(
        source_file=path.name,
        election_year=meta.election_year,
        data_source=meta.data_source,
    )
    register_rejector(rejector)

    raw = _read_raw(path)
    starts = _find_panel_starts(raw)
    if not starts:
        raise ValueError(f"{path.name}: no 'Precinct' header rows found")

    starts_with_sentinel = starts + [raw.shape[0]]
    rows: list[pd.DataFrame] = []
    notes: list[str] = []
    skipped_panels: list[str] = []
    last_known_title: str | None = None

    for i, start in enumerate(starts):
        next_start = starts_with_sentinel[i + 1] if i + 1 < len(starts_with_sentinel) else None
        try:
            block, cand_cols = _panel_rows(raw, start, next_start)
        except Exception as e:
            skipped_panels.append(f"row {start}: {e}")
            continue
        if block.empty or not cand_cols:
            continue
        contest_title = _contest_title(raw, start)
        if contest_title.startswith("<unknown") and last_known_title:
            # Page-break continuation of the prior panel's contest.
            contest_title = last_known_title
        else:
            last_known_title = contest_title

        mcols = _meta_cols(block)
        precinct_col = block.columns[0]

        # Wide → long across candidate columns.
        melt = block.melt(
            id_vars=[precinct_col]
            + [c for c in (mcols["ballots_cast"], mcols["active_voters"]) if c],
            value_vars=cand_cols,
            var_name="candidate_or_option",
            value_name="votes",
        )
        melt = melt.rename(columns={
            precinct_col: "precinct_id",
            mcols["ballots_cast"] or "": "ballots_cast",
            mcols["active_voters"] or "": "active_voters",
        })
        melt["precinct_id"] = melt["precinct_id"].map(precinct_id_str)
        melt["votes"] = pd.to_numeric(
            melt["votes"].astype("string").str.replace(",", "", regex=False),
            errors="coerce",
        )
        if "ballots_cast" in melt.columns:
            melt["ballots_cast"] = pd.to_numeric(
                melt["ballots_cast"].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
        if "active_voters" in melt.columns:
            melt["active_voters"] = pd.to_numeric(
                melt["active_voters"].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
        melt["contest"] = contest_title
        melt["candidate_or_option"] = (
            melt["candidate_or_option"].astype("string").str.strip().map(normalize_choice)
        )

        # Party can sit either before or after the candidate name in panel headers:
        #   "REP Ken Buck" / "REP\nKen Buck"  → name="Ken Buck", party=REP
        #   "Smith REP"                       → name="Smith",    party=REP
        # Try leading first (more common in 2008/2010); fall back to trailing.
        names = melt["candidate_or_option"].astype("string")
        leading = names.str.extract(r"^([A-Z]{2,4})\s+(.+)$")
        trailing = names.str.extract(r"^(.+?)\s+([A-Z]{2,4})\s*$")
        # Choose the party from whichever pattern matched (leading wins ties).
        party_lead = leading[0]
        party_trail = trailing[1]
        melt["party"] = party_lead.where(party_lead.notna(), party_trail).map(normalize_party)
        name_clean = leading[1].where(leading[1].notna(), trailing[0])
        melt["candidate_or_option"] = (
            name_clean.where(name_clean.notna(), names).astype("string").str.strip()
        )
        melt["contest_type"] = [
            infer_contest_type(contest_title, ch) for ch in melt["candidate_or_option"]
        ]
        rows.append(melt)

    if not rows:
        raise ValueError(f"{path.name}: no panels yielded data; skipped={skipped_panels}")

    final = pd.concat(rows, ignore_index=True)
    final = rejector.drop_na_with_reject(
        final,
        required=["precinct_id", "candidate_or_option", "votes"],
        reason="missing_required_field",
    )
    final = final[final["candidate_or_option"].astype("string").str.len() > 0]

    # Skipped panels are a per-PANEL rejection (not per-row); record them too
    # so a reviewer browsing rejected.csv sees the loss.
    for panel_label in skipped_panels:
        rejector.add(
            row_index=panel_label,
            reason="panel_skipped",
            detail="boco_panel parser could not align headers with data block",
        )
    if skipped_panels:
        notes.append(f"skipped {len(skipped_panels)} panel(s) during extraction")
    if "<unknown contest" in " ".join(final["contest"].unique().tolist()):
        n = (final["contest"].astype("string").str.startswith("<unknown contest")).sum()
        notes.append(f"{n} rows have unknown contest title — review needed")

    return add_provenance(final, meta, extraction_notes="; ".join(notes) if notes else None)
