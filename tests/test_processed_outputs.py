"""Smoke checks against the committed processed CSVs.

These tests skip if the per-year CSVs aren't present (e.g. on a fresh clone
that hasn't run the pipeline yet). They validate the schema contract end-to-end
against real data rather than synthetic fixtures.

The per-year CSVs hold the slim schema (no provenance columns); the provenance
sidecar lives at `data/processed/provenance.csv`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.schema import CSV_COLUMNS, PROVENANCE_COLUMNS

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
def test_file_matches_csv_schema(filename):
    df = _maybe_load(filename)
    if df is None:
        pytest.skip(f"{filename} not present; run `python -m scripts.pipeline` first")
    assert list(df.columns) == CSV_COLUMNS, f"{filename}: column order drift"


@pytest.mark.parametrize("filename", SAMPLE_FILES)
def test_file_has_no_provenance_cols(filename):
    df = _maybe_load(filename)
    if df is None:
        pytest.skip(f"{filename} not present")
    leaked = [c for c in PROVENANCE_COLUMNS if c in df.columns]
    assert not leaked, f"{filename}: provenance columns leaked into slim CSV: {leaked}"


def test_combined_tidy_csv_uses_slim_schema():
    path = PROCESSED / "all-elections-tidy.csv"
    if not path.exists():
        pytest.skip("combined CSV not built locally")
    df = pd.read_csv(path, dtype={"precinct_id": "string"}, low_memory=False)
    assert list(df.columns) == CSV_COLUMNS
    expected_years = {2020, 2022, 2023, 2024}
    have = set(df["election_year"].dropna().astype(int).unique())
    assert expected_years.issubset(have), f"missing years: {expected_years - have}"


def test_provenance_sidecar_present_and_complete():
    path = PROCESSED / "provenance.csv"
    if not path.exists():
        pytest.skip("provenance.csv not built yet")
    prov = pd.read_csv(path, dtype=str)
    assert "source_file" in prov.columns
    assert "source_url" in prov.columns
    assert "retrieved_at" in prov.columns
    assert "extraction_quality" in prov.columns
    assert "extraction_notes" in prov.columns
    # One row per (year, election_type, data_source)
    keys = prov[["election_year", "election_type", "data_source"]].apply(tuple, axis=1)
    assert keys.is_unique, "provenance sidecar has duplicate keys"
