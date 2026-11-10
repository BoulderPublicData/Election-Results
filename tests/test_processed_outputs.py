"""Smoke checks against the committed processed CSVs.

These tests skip if the per-year CSVs aren't present (e.g. on a fresh clone
that hasn't run the pipeline yet). They validate the schema contract end-to-end
against real data rather than synthetic fixtures.

The per-year CSVs hold the slim schema (no provenance columns); the provenance
sidecar lives at `data/processed/statements-of-votes/provenance.csv`.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.config import STATEMENTS_OF_VOTES as PROCESSED
from scripts.schema import CSV_COLUMNS, PROVENANCE_COLUMNS

# Every committed per-year file (#30: sampling four of them let three stale
# 20-column PDF-year files go unnoticed).
ALL_FILES = sorted(PROCESSED.glob("[0-9]*.csv"))


def _maybe_load(name: str) -> pd.DataFrame | None:
    path = PROCESSED / name
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"precinct_id": "string"}, low_memory=False)


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_file_matches_csv_schema(path):
    df = _maybe_load(path.name)
    assert list(df.columns) == CSV_COLUMNS, f"{path.name}: column order drift"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_file_has_no_provenance_cols(path):
    df = pd.read_csv(path, nrows=0)
    leaked = [c for c in PROVENANCE_COLUMNS if c in df.columns]
    assert not leaked, f"{path.name}: provenance columns leaked into slim CSV: {leaked}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_no_duplicate_keys(path):
    """#23: the PDF years printed some (precinct, contest, candidate) keys
    two or three times with different votes."""
    df = _maybe_load(path.name)
    dup = df.duplicated(["precinct_id", "contest", "candidate_or_option"])
    assert not dup.any(), f"{path.name}: {int(dup.sum())} duplicate keys"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_no_contest_mixes_yes_no_with_candidates(path):
    """#17: SOS 2012-2020 candidate contests carried phantom 0-vote Yes/No rows."""
    df = _maybe_load(path.name)
    df = df[df["contest_type"] != "ranked_choice"]
    opts = df.groupby("contest")["candidate_or_option"].agg(set)
    mixed = [c for c, v in opts.items() if (v & {"Yes", "No"}) and (v - {"Yes", "No"})]
    assert not mixed, f"{path.name}: {mixed[:3]}"


PANEL_FILES = [
    p
    for p in ALL_FILES
    if p.name[:4] in {"2008", "2010", "2011", "2012"} and "boulder-county" in p.name
]


@pytest.mark.parametrize("path", PANEL_FILES, ids=lambda p: p.name)
def test_active_voters_not_below_ballots_cast(path):
    """#20: the misaligned 2008/2010 panel columns had active_voters <
    ballots_cast in every precinct. (Panel files report one registered-voter
    count per precinct; the tidy years report it per contest, so they're not
    checked here.) Pseudo-precincts (property-owner ballots, no registered
    voters) and composite IDs are exempt."""
    df = _maybe_load(path.name).drop_duplicates("precinct_id")
    df = df[df["precinct_id"].str.fullmatch(r"\d+", na=False)]
    df = df.dropna(subset=["active_voters", "ballots_cast"])
    bad = df[df["active_voters"] < df["ballots_cast"]]
    assert bad.empty, f"{path.name}: {bad[['precinct_id', 'active_voters', 'ballots_cast']].head()}"


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
    # One row per (year, election_type, data_source), none of them null (#31).
    keys = prov[["election_year", "election_type", "data_source"]]
    assert keys.notna().all().all(), "provenance sidecar has a null key"
    assert keys.apply(tuple, axis=1).is_unique, "provenance sidecar has duplicate keys"
    from scripts.sources import ALL_SOURCES

    want = {(str(s.year), s.election_type, s.data_source) for s in ALL_SOURCES}
    assert set(keys.apply(tuple, axis=1)) == want, "provenance sidecar doesn't cover the registry"


INT_COLUMNS = [
    c for c in CSV_COLUMNS if c in {"election_year", "votes", "active_voters", "ballots_cast"}
]


@pytest.mark.parametrize("path", sorted(PROCESSED.glob("[0-9]*.csv")), ids=lambda p: p.name)
def test_integer_columns_written_as_integers(path):
    """clean_source() coerces to schema.DTYPES, so counts are written as "1291",
    never "1291.0" (which Excel and R read as a float)."""
    df = pd.read_csv(path, dtype=str, usecols=INT_COLUMNS)
    for col in INT_COLUMNS:
        floaty = df[col].dropna().str.contains(r"\.", regex=True)
        assert not floaty.any(), f"{path.name}:{col} has float-formatted values"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_composite_ids_use_one_separator_and_pseudo_flag_matches(path):
    """#27: composite IDs mixed ',', ', ', ' + ' and '+'."""
    from scripts.parsers.common import is_pseudo_precinct

    df = pd.read_csv(
        path,
        dtype={"precinct_id": "string", "is_pseudo_precinct": "boolean"},
        usecols=["precinct_id", "is_pseudo_precinct"],
    ).drop_duplicates()
    ids = df["precinct_id"].dropna()
    assert not ids.str.contains(r"\+|,(?! )|\s{2,}", regex=True).any(), path.name
    assert df["is_pseudo_precinct"].notna().all()
    assert (df["is_pseudo_precinct"] == df["precinct_id"].map(is_pseudo_precinct)).all()


def _totals(name: str, contest: str) -> dict[str, int] | None:
    df = _maybe_load(name)
    if df is None:
        return None
    sub = df[df["contest"] == contest]
    return {k: int(v) for k, v in sub.groupby("candidate_or_option")["votes"].sum().items()}


def test_2023_boulder_council_is_the_recount():
    """#42: the December 2023 recount replaces City of Boulder Council."""
    t = _totals("2023-coordinated-boulder-county.csv", "City of Boulder Council Candidates")
    if t is None:
        pytest.skip("2023 CSV not on disk")
    assert sum(t.values()) == 113_374
    assert t["Jenny Robins"] == 11_249 and t["Silas Atkins"] == 6_829


def test_2023_louisville_ward_2_is_corrected():
    """#44: the duplicated reporting unit is dropped."""
    t = _totals(
        "2023-coordinated-boulder-county.csv",
        "City of Louisville City Council Ward 2 (4-year term)",
    )
    if t is None:
        pytest.skip("2023 CSV not on disk")
    assert t == {"Deborah Fahey": 1_419, "George Colbert": 1_207}


def test_2024_boulder_is_the_full_sov_with_the_amended_contests():
    """#43: the full 2024 SoV, with the amended file's two contests over it."""
    df = _maybe_load("2024-general-boulder-county.csv")
    if df is None:
        pytest.skip("2024 CSV not on disk")
    assert len(df) == 18_438
    assert df["contest"].nunique() == 65
    assert int(df["votes"].sum()) == 6_649_407
    t = _totals("2024-general-boulder-county.csv", "Town of Superior - Trustee")
    assert t["Mike Foster"] == 3_531 and t["Sandie Hammerly"] == 3_239


def test_2011_no_numeric_contest_titles():
    """#46: Mountains Forest Improvement District 5C was titled "161"."""
    df = _maybe_load("2011-coordinated-boulder-county.csv")
    if df is None:
        pytest.skip("2011 CSV not on disk")
    assert not df["contest"].str.fullmatch(r"[\d.,\s]+").any()
    t = _totals(
        "2011-coordinated-boulder-county.csv",
        "Boulder County Mountains Forest Improvement District Question 5C:",
    )
    assert t == {"Yes": 2_347, "No": 3_331}
