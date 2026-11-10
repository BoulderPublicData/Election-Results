"""
Adjudicated corrections to the published Statements of Votes (#44).

The harmonized data reproduces each SoV as published, except where a row of
``scripts/corrections/statements-of-votes.csv`` documents a defect in the
published file and the evidence for the fix. This is the SoV counterpart of
``scripts/corrections/vote-counting.csv``, and follows the same rules:

- a correction names the row as the parser produces it (election key, data
  source, contest, ``precinct_id``, ``candidate_or_option``) and the vote count
  the file published; if that row or count is no longer there, the build
  fails, so a stale correction can never apply silently;
- every correction carries its evidence and a note;
- ``scripts/reconcile.py`` compares the processed data with the raw file and
  marks a key whose difference equals its documented corrections as
  ``corrected`` rather than ``mismatch``.

Actions (``action`` column):

==========  ==============================  ===============================
action      published_votes                 corrected_votes
==========  ==============================  ===============================
drop_row    votes in the published row      (blank) — the row is removed
set_votes   votes in the published row      the adjudicated vote count
==========  ==============================  ===============================
"""

from __future__ import annotations

import pandas as pd

from .config import SOV_CORRECTIONS_CSV
from .sources import election_key

CORRECTION_COLUMNS = [
    "election",
    "data_source",
    "contest",
    "precinct_id",
    "candidate_or_option",
    "action",
    "published_votes",
    "corrected_votes",
    "evidence",
    "note",
]
ACTIONS = {"drop_row", "set_votes"}


def load(path=None) -> pd.DataFrame:
    """Every correction, as strings. Raises on a malformed file."""
    path = SOV_CORRECTIONS_CSV if path is None else path
    if not path.exists():
        return pd.DataFrame(columns=CORRECTION_COLUMNS)
    df = pd.read_csv(path, dtype="string", keep_default_na=False)
    missing = set(CORRECTION_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    bad = sorted(set(df["action"]) - ACTIONS)
    if bad:
        raise ValueError(f"{path.name}: unknown action(s) {bad}; expected one of {sorted(ACTIONS)}")
    for r in df.itertuples(index=False):
        if not r.evidence.strip():
            raise ValueError(f"{path.name}: correction without evidence: {r}")
        if (r.action == "set_votes") != bool(r.corrected_votes.strip()):
            raise ValueError(
                f"{path.name}: corrected_votes must be set for set_votes and blank for "
                f"drop_row: {r}"
            )
    return df


def for_source(
    year: int, election_type: str, data_source: str, fixes: pd.DataFrame | None = None
) -> pd.DataFrame:
    fixes = load() if fixes is None else fixes
    key = election_key(year, election_type)
    return fixes[(fixes["election"] == key) & (fixes["data_source"] == data_source)]


def vote_delta(fix) -> int:
    """How much the correction changes the published count."""
    published = int(fix.published_votes)
    if fix.action == "drop_row":
        return -published
    return int(fix.corrected_votes) - published


def apply(df: pd.DataFrame, fixes: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Apply `fixes` (already filtered to this file) to a parser-output frame.
    Returns (corrected frame, one note per applied correction). Raises if a
    correction doesn't match exactly one row with the published vote count."""
    if fixes.empty:
        return df, []
    df = df.copy()
    keep = pd.Series(True, index=df.index)
    notes: list[str] = []
    for fix in fixes.itertuples(index=False):
        hit = (
            (df["contest"] == fix.contest)
            & (df["precinct_id"] == fix.precinct_id)
            & (df["candidate_or_option"] == fix.candidate_or_option)
        ).fillna(False)
        rows = df.index[hit]
        if len(rows) != 1 or int(df.at[rows[0], "votes"]) != int(fix.published_votes):
            found = [int(v) for v in df.loc[rows, "votes"]]
            raise ValueError(
                "SoV correction did not apply (row missing, repeated, or its published "
                f"votes changed; found {found}): {fix.election} / {fix.contest} / "
                f"{fix.precinct_id} / {fix.candidate_or_option}"
            )
        if fix.action == "drop_row":
            keep[rows[0]] = False
        else:
            df.at[rows[0], "votes"] = int(fix.corrected_votes)
        notes.append(
            f"{fix.contest} / {fix.precinct_id} / {fix.candidate_or_option}: {fix.action} "
            f"({fix.published_votes} published"
            + (f" → {fix.corrected_votes})" if fix.action == "set_votes" else ")")
        )
    return df[keep].reset_index(drop=True), notes
