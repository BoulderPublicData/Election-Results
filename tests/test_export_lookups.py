"""Lookup-export determinism + shape tests.

The exporters write into a temp directory (see the autouse fixture) so running
the suite never rewrites the committed files under data/lookups/.
"""

from __future__ import annotations

import json

import pytest

from scripts import export_lookups
from scripts.export_lookups import (
    export_choice_map,
    export_election_dates,
    export_party_codes,
    export_schema,
    export_sources,
)
from scripts.schema import COLUMNS


@pytest.fixture(autouse=True)
def LOOKUPS(tmp_path, monkeypatch):
    monkeypatch.setattr(export_lookups, "LOOKUPS", tmp_path)
    return tmp_path


def test_party_codes_export_roundtrip(LOOKUPS):
    export_party_codes()
    payload = json.loads((LOOKUPS / "party-codes.json").read_text())
    assert "mapping" in payload
    assert "by_canonical" in payload
    assert payload["mapping"]["Democratic Party"] == "DEM"
    assert payload["mapping"]["Republican Party"] == "REP"


def test_choice_map_export_only_yes_no(LOOKUPS):
    export_choice_map()
    payload = json.loads((LOOKUPS / "choice-map.json").read_text())
    canonicals = set(payload["mapping"].values())
    assert canonicals == {"Yes", "No"}


def test_election_dates_export_iso(LOOKUPS):
    export_election_dates()
    payload = json.loads((LOOKUPS / "election-dates.json").read_text())
    for date in payload["election_dates"].values():
        assert len(date) == 10 and date[4] == "-" and date[7] == "-", date


def test_sources_export_no_dups(LOOKUPS):
    export_sources()
    payload = json.loads((LOOKUPS / "sources.json").read_text())
    keys = [(s["year"], s["data_source"], s["election_type"]) for s in payload["sources"]]
    assert len(keys) == len(set(keys))


def test_schema_export_matches_python(LOOKUPS):
    export_schema()
    payload = json.loads((LOOKUPS / "schema.json").read_text())
    assert payload["columns"] == COLUMNS
