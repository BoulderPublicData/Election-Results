"""Reject port contract tests."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts import reject
from scripts.reject import Rejector, drain, register, reset


@pytest.fixture(autouse=True)
def _clear_buffer():
    reset()
    yield
    reset()


def test_empty_drain_returns_well_typed_frame():
    out = drain()
    assert list(out.columns) == [
        "source_file", "election_year", "data_source", "row_index",
        "reason", "detail", "raw_row",
    ]
    assert len(out) == 0


def test_drop_na_with_reject_filters_and_records():
    rej = Rejector(source_file="x.xlsx", election_year=2024, data_source="boulder_county")
    register(rej)
    df = pd.DataFrame({
        "precinct_id": ["100", None, "200"],
        "contest": ["A", "A", None],
        "votes": [10, 20, 30],
    })
    out = rej.drop_na_with_reject(df, required=["precinct_id", "contest"])
    assert len(out) == 1
    assert out["precinct_id"].iloc[0] == "100"
    assert len(rej) == 2
    drained = drain()
    assert len(drained) == 2
    assert (drained["reason"] == "missing_required_field").all()
    assert "precinct_id" in drained["detail"].iloc[0]
    # raw_row should be a JSON object string
    raw = json.loads(drained["raw_row"].iloc[0])
    assert raw["votes"] == 20


def test_provenance_fields_propagate():
    rej = Rejector(source_file="x.xlsx", election_year=2024, data_source="secretary_of_state")
    rej.add(row_index="sheet:5", reason="r", detail="d")
    register(rej)
    out = drain()
    assert out["source_file"].iloc[0] == "x.xlsx"
    assert out["election_year"].iloc[0] == 2024
    assert out["data_source"].iloc[0] == "secretary_of_state"
    assert out["row_index"].iloc[0] == "sheet:5"


def test_drain_clears_buffer():
    rej = Rejector(source_file="x", election_year=2024, data_source="boulder_county")
    rej.add(row_index="1", reason="r")
    register(rej)
    assert len(drain()) == 1
    # Second drain is empty.
    assert len(drain()) == 0
