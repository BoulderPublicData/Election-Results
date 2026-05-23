"""
Harmonized long-format schema for Boulder County and Colorado SOS election results.

One row per: (election_year, jurisdiction, precinct_id, contest, candidate_or_option).
Long format pivots cleanly to candidate-wide, contest-wide, or precinct-wide views.

The contract here is consumed by every parser in scripts/parsers/ and by audit.py.
Add a new column in exactly one place — here — then update parsers and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

SCHEMA_VERSION = "1.1.0"

# Canonical column order. Parsers MUST return these columns in this order.
COLUMNS: list[str] = [
    "election_year",
    "election_date",
    "election_type",
    "data_source",
    "jurisdiction_level",
    "jurisdiction_name",
    "precinct_id",
    "precinct_name",
    "contest",
    "contest_type",
    "candidate_or_option",
    "party",
    "votes",
    "active_voters",
    "ballots_cast",
    "source_file",
    "source_url",
    "retrieved_at",
    "extraction_quality",
    "extraction_notes",
]

# Pandas dtypes for the canonical schema. Strings use the nullable "string"
# dtype so missing values stay distinguishable from empty strings.
DTYPES: dict[str, str] = {
    "election_year": "Int16",
    "election_date": "string",  # ISO date; left as string for CSV roundtrip
    "election_type": "string",
    "data_source": "string",
    "jurisdiction_level": "string",
    "jurisdiction_name": "string",
    "precinct_id": "string",  # may have leading zeros — never cast to int
    "precinct_name": "string",
    "contest": "string",
    "contest_type": "string",
    "candidate_or_option": "string",
    "party": "string",
    "votes": "Int64",
    "active_voters": "Int64",
    "ballots_cast": "Int64",
    "source_file": "string",
    "source_url": "string",
    "retrieved_at": "string",  # ISO 8601 UTC
    "extraction_quality": "string",
    "extraction_notes": "string",
}

# Provenance columns that are constant per (year × source × election_type) — i.e.
# they repeat the same value on every row from one source file. We drop them
# from the per-row CSVs to keep file sizes manageable and write a sidecar
# `data/processed/provenance.csv` with one row per source file instead.
# The columns still live in the in-memory schema; coerce() / validate() / the
# audit module all use them upstream of CSV writes.
PROVENANCE_COLUMNS: list[str] = [
    "source_file",
    "source_url",
    "retrieved_at",
    "extraction_quality",
    "extraction_notes",
]

# Columns actually written to per-year CSV files (the slimmed view).
CSV_COLUMNS: list[str] = [c for c in COLUMNS if c not in PROVENANCE_COLUMNS]


def to_csv_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with provenance columns removed, in CSV column order."""
    keep = [c for c in CSV_COLUMNS if c in df.columns]
    return df[keep].copy()


def provenance_record(df: pd.DataFrame) -> dict[str, object]:
    """Distil the constant provenance fields from a parser-output frame into a
    single dict. All non-grouping columns are expected to hold one value across
    every row from this source — the first non-null wins."""
    out: dict[str, object] = {}
    for col in ["election_year", "election_type", "data_source"] + PROVENANCE_COLUMNS:
        if col not in df.columns:
            out[col] = pd.NA
            continue
        s = df[col].dropna()
        out[col] = s.iloc[0] if len(s) else pd.NA
    return out

ElectionType = Literal["general", "primary", "coordinated"]
ContestType = Literal[
    "candidate",       # partisan or non-partisan candidate race
    "measure",         # yes/no ballot measure, referendum, amendment
    "retention",       # judicial retention (yes/no)
    "recall",          # recall question (yes/no)
    "ranked_choice",   # RCV contest — round-level detail in candidate_or_option
]
JurisdictionLevel = Literal["county", "state", "city", "school_district", "special_district"]
DataSource = Literal["boulder_county", "secretary_of_state"]
ExtractionQuality = Literal["machine_readable", "pdf_text_layer", "pdf_ocr", "manual"]


@dataclass(frozen=True)
class SourceMeta:
    """Provenance metadata threaded through every row a parser emits."""
    election_year: int
    election_date: str  # ISO YYYY-MM-DD
    election_type: ElectionType
    data_source: DataSource
    jurisdiction_level: JurisdictionLevel
    jurisdiction_name: str
    source_file: str
    source_url: str
    retrieved_at: str
    extraction_quality: ExtractionQuality


def empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical schema applied."""
    return pd.DataFrame({c: pd.Series(dtype=DTYPES[c]) for c in COLUMNS})


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a DataFrame to the canonical schema. Missing columns are added as null;
    extra columns are dropped with a warning printed to stderr."""
    import sys

    extra = sorted(set(df.columns) - set(COLUMNS))
    if extra:
        print(f"  WARN coerce() dropping unknown columns: {extra}", file=sys.stderr)

    out = pd.DataFrame()
    for col in COLUMNS:
        if col in df.columns:
            series = df[col]
        else:
            series = pd.Series([pd.NA] * len(df), dtype=DTYPES[col])
        try:
            if DTYPES[col].startswith("Int"):
                series = pd.to_numeric(series, errors="coerce").astype(DTYPES[col])
            else:
                series = series.astype(DTYPES[col])
        except (ValueError, TypeError) as e:
            raise ValueError(f"coerce({col!r}): {e}") from e
        out[col] = series
    return out[COLUMNS]


def validate(df: pd.DataFrame, source_label: str = "") -> list[str]:
    """Return a list of validation problems. Empty list = clean.
    Not raised — callers decide how to handle (warn vs. fail)."""
    problems: list[str] = []
    prefix = f"[{source_label}] " if source_label else ""

    missing = sorted(set(COLUMNS) - set(df.columns))
    if missing:
        problems.append(f"{prefix}missing columns: {missing}")
        return problems

    for col in ["election_year", "data_source", "contest", "candidate_or_option"]:
        nulls = df[col].isna().sum()
        if nulls:
            problems.append(f"{prefix}{col}: {nulls} nulls (must be non-null)")

    # Negative votes are illegal except for RCV intermediate rounds, where they
    # represent ballots transferring AWAY from an eliminated candidate.
    non_rcv = df.loc[df["contest_type"] != "ranked_choice", "votes"].dropna()
    if (non_rcv < 0).any():
        problems.append(f"{prefix}negative vote counts in non-RCV rows")

    bad_type = df.loc[~df["contest_type"].isin(
        ["candidate", "measure", "retention", "recall", "ranked_choice"]
    ) & df["contest_type"].notna(), "contest_type"].unique()
    if len(bad_type):
        problems.append(f"{prefix}unknown contest_type values: {list(bad_type)}")

    bad_q = df.loc[~df["extraction_quality"].isin(
        ["machine_readable", "pdf_text_layer", "pdf_ocr", "manual"]
    ) & df["extraction_quality"].notna(), "extraction_quality"].unique()
    if len(bad_q):
        problems.append(f"{prefix}unknown extraction_quality values: {list(bad_q)}")

    return problems
