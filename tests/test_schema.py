"""Schema contract tests — what every parser/audit consumer relies on."""

from __future__ import annotations

import pandas as pd

from scripts.schema import (
    COLUMNS, CSV_COLUMNS, DTYPES, PROVENANCE_COLUMNS, SCHEMA_VERSION,
    coerce, empty_frame, provenance_record, to_csv_frame, validate,
)


def test_column_count():
    assert len(COLUMNS) == 20, "Schema is 20 columns; bumping it is a major change"


def test_csv_columns_excludes_provenance():
    assert len(CSV_COLUMNS) == len(COLUMNS) - len(PROVENANCE_COLUMNS)
    assert set(CSV_COLUMNS) == set(COLUMNS) - set(PROVENANCE_COLUMNS)
    # CSV_COLUMNS must preserve the canonical order of the columns it keeps.
    assert CSV_COLUMNS == [c for c in COLUMNS if c not in PROVENANCE_COLUMNS]


def test_to_csv_frame_drops_provenance():
    df = empty_frame()
    out = to_csv_frame(df)
    assert list(out.columns) == CSV_COLUMNS
    for col in PROVENANCE_COLUMNS:
        assert col not in out.columns


def test_provenance_record_pulls_constants():
    df = empty_frame()
    df.loc[0] = [pd.NA] * len(COLUMNS)
    df.loc[1] = [pd.NA] * len(COLUMNS)
    df.loc[:, "election_year"] = 2024
    df.loc[:, "election_type"] = "general"
    df.loc[:, "data_source"] = "boulder_county"
    df.loc[:, "source_file"] = "2024-general-sov.xlsx"
    df.loc[:, "source_url"] = "https://example.test/2024.xlsx"
    df.loc[:, "extraction_quality"] = "machine_readable"
    rec = provenance_record(df)
    assert rec["source_file"] == "2024-general-sov.xlsx"
    assert rec["source_url"] == "https://example.test/2024.xlsx"
    assert rec["extraction_quality"] == "machine_readable"


def test_columns_match_dtypes():
    assert set(COLUMNS) == set(DTYPES.keys()), "Every column needs a dtype"


def test_schema_version_is_semver():
    parts = SCHEMA_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), SCHEMA_VERSION


def test_required_columns_present():
    required = {
        "election_year", "data_source", "contest", "candidate_or_option",
        "extraction_quality",
    }
    assert required.issubset(COLUMNS)


def test_empty_frame_has_schema():
    df = empty_frame()
    assert list(df.columns) == COLUMNS
    assert len(df) == 0


def test_coerce_adds_missing_columns():
    inp = pd.DataFrame({
        "election_year": [2024], "contest": ["X"], "candidate_or_option": ["A"],
        "data_source": ["boulder_county"], "extraction_quality": ["machine_readable"],
    })
    out = coerce(inp)
    assert list(out.columns) == COLUMNS
    assert out["precinct_id"].iloc[0] is pd.NA or pd.isna(out["precinct_id"].iloc[0])


def test_validate_catches_missing_required():
    df = empty_frame()
    df.loc[0] = [pd.NA] * len(COLUMNS)
    problems = validate(df, "test")
    assert any("election_year" in p for p in problems)


def test_validate_allows_negative_votes_only_for_rcv():
    base = {c: pd.NA for c in COLUMNS}
    base.update({
        "election_year": 2023, "data_source": "boulder_county",
        "contest": "X", "candidate_or_option": "A | Round 2",
        "extraction_quality": "machine_readable",
        "votes": -5, "contest_type": "ranked_choice",
    })
    df = coerce(pd.DataFrame([base]))
    assert validate(df) == []  # negative RCV votes are OK

    base["contest_type"] = "candidate"
    df = coerce(pd.DataFrame([base]))
    problems = validate(df)
    assert any("negative vote" in p for p in problems)


def test_validate_flags_unknown_contest_type():
    base = {c: pd.NA for c in COLUMNS}
    base.update({
        "election_year": 2024, "data_source": "boulder_county",
        "contest": "X", "candidate_or_option": "A",
        "extraction_quality": "machine_readable",
        "contest_type": "bogus_type",
    })
    df = coerce(pd.DataFrame([base]))
    problems = validate(df)
    assert any("contest_type" in p for p in problems)
