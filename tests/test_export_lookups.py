"""Lookup-export determinism + shape tests."""

from __future__ import annotations

import json

from scripts.export_lookups import (
    export_choice_map, export_election_dates, export_party_codes,
    export_schema, export_sources, LOOKUPS,
)
from scripts.schema import COLUMNS


def test_party_codes_export_roundtrip():
    export_party_codes()
    payload = json.loads((LOOKUPS / "party-codes.json").read_text())
    assert "mapping" in payload
    assert "by_canonical" in payload
    assert payload["mapping"]["Democratic Party"] == "DEM"
    assert payload["mapping"]["Republican Party"] == "REP"


def test_choice_map_export_only_yes_no():
    export_choice_map()
    payload = json.loads((LOOKUPS / "choice-map.json").read_text())
    canonicals = set(payload["mapping"].values())
    assert canonicals == {"Yes", "No"}


def test_election_dates_export_iso():
    export_election_dates()
    payload = json.loads((LOOKUPS / "election-dates.json").read_text())
    for year, date in payload["election_dates"].items():
        assert len(date) == 10 and date[4] == "-" and date[7] == "-", date


def test_sources_export_no_dups():
    export_sources()
    payload = json.loads((LOOKUPS / "sources.json").read_text())
    keys = [(s["year"], s["data_source"], s["election_type"]) for s in payload["sources"]]
    assert len(keys) == len(set(keys))


def test_schema_export_matches_python():
    export_schema()
    payload = json.loads((LOOKUPS / "schema.json").read_text())
    assert payload["columns"] == COLUMNS
