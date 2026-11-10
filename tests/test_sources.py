"""Source registry shape tests."""

from __future__ import annotations

from scripts.sources import (
    ALL_SOURCES,
    BOULDER_COUNTY,
    ELECTION_DATES,
    ELECTION_TYPES,
    SECRETARY_OF_STATE,
    find,
    sources_for_year,
)


def test_no_duplicate_year_source():
    keys = [(s.year, s.data_source, s.election_type) for s in ALL_SOURCES]
    assert len(keys) == len(set(keys)), f"duplicate keys present: {keys}"


def test_all_sources_have_urls_and_filenames():
    for s in ALL_SOURCES:
        assert s.url.startswith("http"), s
        assert s.local_filename, s
        assert s.data_source in {"boulder_county", "secretary_of_state"}
        assert s.election_type in ELECTION_TYPES


def test_election_dates_cover_all_source_years():
    for s in ALL_SOURCES:
        assert s.year in ELECTION_DATES, f"{s.year} missing from ELECTION_DATES"


def test_boulder_covers_both_parities():
    even = {s.year for s in BOULDER_COUNTY if s.year % 2 == 0}
    odd = {s.year for s in BOULDER_COUNTY if s.year % 2 == 1}
    assert even and odd, "Boulder registry should have both general and coordinated years"


def test_sos_is_general_only():
    assert all(s.election_type == "general" for s in SECRETARY_OF_STATE)


def test_find_returns_match():
    s = find(2020, "boulder_county")
    assert s is not None
    assert s.year == 2020
    assert s.election_type == "general"


def test_sources_for_year_returns_per_year_pair():
    pairs = sources_for_year(2020)
    sources = {p.data_source for p in pairs}
    assert "boulder_county" in sources
    assert "secretary_of_state" in sources


def test_presidential_primary_key_shared_with_cast_vote_records():
    from scripts.sources import election_date_for, election_key, parse_election_key

    assert "presidential_primary" in ELECTION_TYPES
    assert election_key(2024, "presidential_primary") == "2024-presidential-primary"
    assert parse_election_key("2024-presidential-primary") == (2024, "presidential_primary")
    assert parse_election_key("2024PP") == (2024, "presidential_primary")  # county prefix
    assert parse_election_key("2024P") == (2024, "primary")
    assert election_date_for(2024, "presidential_primary") == "2024-03-05"


def test_presidential_primary_csv_stem():
    from scripts.config import sov_csv_path

    assert sov_csv_path(2024, "presidential_primary", "boulder_county").name == (
        "2024-presidential-primary-boulder-county.csv"
    )


def test_file_records_list_the_source_then_its_supplements():
    s = find(2024, "boulder_county")
    recs = s.file_records()
    assert [r.local_filename for r in recs] == [
        "2024-general-sov.xlsx",
        "2024-general-sov-amended.xlsx",
    ]
    assert all(
        (r.year, r.election_type, r.data_source) == (2024, "general", "boulder_county")
        for r in recs
    )
    assert recs[1].url == s.supplements[0].url and not recs[1].supplements
