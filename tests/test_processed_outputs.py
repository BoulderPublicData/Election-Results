"""Smoke checks against the committed processed CSVs.

These tests skip if the per-year CSVs aren't present (e.g. on a fresh clone
that hasn't run the pipeline yet). They validate the schema contract end-to-end
against real data rather than synthetic fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from scripts.schema import COLUMNS, validate

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"

# A handful of representative years that cover every parser branch.
SAMPLE_FILES = [
    "2020-general-boulder-county.csv",     # boco_tidy + Party column
    "2023-coordinated-boulder-county.csv", # boco_tidy + RCV sheet
    "2025-coordinated-boulder-county.csv", # boco_tidy + 2025 schema variant
    "2020-general-secretary-of-state.csv", # sos split format
]


def _maybe_load(name: str) -> pd.DataFrame | None:
    path = PROCESSED / name
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"precinct_id": "string"}, low_memory=False)


@pytest.mark.parametrize("filename", SAMPLE_FILES)
def test_file_matches_schema(filename):
    df = _maybe_load(filename)
    if df is None:
        pytest.skip(f"{filename} not present; run `python -m scripts.pipeline` first")
    assert list(df.columns) == COLUMNS, f"{filename}: column order drift"


@pytest.mark.parametrize("filename", SAMPLE_FILES)
def test_file_validates(filename):
    df = _maybe_load(filename)
    if df is None:
        pytest.skip(f"{filename} not present")
    problems = validate(df, filename)
    assert problems == [], problems


def test_combined_tidy_csv_optional_but_consistent():
    path = PROCESSED / "all-elections-tidy.csv"
    if not path.exists():
        pytest.skip("combined CSV is gitignored; only checked if locally built")
    df = pd.read_csv(path, dtype={"precinct_id": "string"}, low_memory=False)
    assert list(df.columns) == COLUMNS
    # At least the years that ship CSVs should be represented.
    expected_years = {2020, 2022, 2023, 2024}
    have = set(df["election_year"].dropna().astype(int).unique())
    assert expected_years.issubset(have), f"missing years: {expected_years - have}"
