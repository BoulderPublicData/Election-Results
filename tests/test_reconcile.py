"""Tests for the original-file readers in scripts/reconcile.py."""

from __future__ import annotations

import pandas as pd

from scripts import reconcile


def test_sos_reader_keeps_candidates_and_splits_measures(tmp_path):
    """2012-2020 SOS layout: candidate votes and Yes/No votes in separate
    columns, statewide rows filtered to Boulder."""
    sheet = pd.DataFrame({
        "County": ["Boulder", "Boulder", "Denver", "Boulder"],
        "Precinct": [2181007800, 2181007801, 1, 2181007800],
        "Office/Issue/Judgeship": ["President", "President", "President", "Amendment 1"],
        "Candidate": ["Jane Doe", "Jane Doe", "Jane Doe", None],
        "Party": ["DEM", "DEM", "DEM", None],
        "Candidate Votes": [10, 5, 999, None],
        "Yes Votes": [None, None, None, 7],
        "No Votes": [None, None, None, 3],
    })
    path = tmp_path / "sos.xlsx"
    sheet.to_excel(path, index=False)

    out = reconcile._read_sos_original(path)

    totals = out.groupby(["contest", "candidate_or_option"])["votes"].sum().to_dict()
    assert totals == {("President", "Jane Doe"): 15,
                      ("Amendment 1", "Yes"): 7, ("Amendment 1", "No"): 3}


def test_sos_reader_skips_turnout_only_files(tmp_path):
    path = tmp_path / "turnout.xlsx"
    pd.DataFrame({"County": ["Boulder"], "Precinct": [1], "Ballots Cast": [10]}).to_excel(
        path, index=False)
    assert reconcile._read_sos_original(path) is None
