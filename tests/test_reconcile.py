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


def _split_layout(path, judges_yes):
    """The real 2012-2020 layout: all three vote columns filled, 0 where a
    column doesn't apply, judges named in Candidate under one office title."""
    rows = [
        {"County": "Boulder", "Precinct": 1, "Office/Issue/Judgeship": "President",
         "Candidate": "Jane Doe", "Party": "DEM", "Candidate Votes": 10,
         "Yes Votes": 0, "No Votes": 0},
    ]
    for judge, yes in judges_yes.items():
        rows.append({"County": "Boulder", "Precinct": 1,
                     "Office/Issue/Judgeship": "Court of Appeals", "Candidate": judge,
                     "Party": None, "Candidate Votes": 0, "Yes Votes": yes, "No Votes": 5})
    pd.DataFrame(rows).to_excel(path, index=False)


def test_sos_reader_keys_judges_by_name_in_split_layout(tmp_path):
    path = tmp_path / "sos.xlsx"
    _split_layout(path, {"A. Judge": 100, "B. Judge": 90})
    out = reconcile._read_sos_original(path)
    totals = out.groupby(["contest", "candidate_or_option"])["votes"].sum()
    totals = totals[totals != 0].to_dict()
    assert totals == {("President", "Jane Doe"): 10,
                      ("Court of Appeals - A. Judge", "Yes"): 100,
                      ("Court of Appeals - A. Judge", "No"): 5,
                      ("Court of Appeals - B. Judge", "Yes"): 90,
                      ("Court of Appeals - B. Judge", "No"): 5}


def _processed(rows):
    df = pd.DataFrame(rows, columns=["precinct_id", "contest", "contest_type",
                                     "candidate_or_option", "votes"])
    return df


def test_candidate_reconcile_catches_a_dropped_judge(tmp_path, monkeypatch):
    """#16 would have been caught: the second judge's votes are missing."""
    path = tmp_path / "sos.xlsx"
    _split_layout(path, {"A. Judge": 100, "B. Judge": 90})
    orig = reconcile._read_sos_original(path)
    proc = _processed([
        ("1", "President", "candidate", "Jane Doe", 10),
        ("1", "Court of Appeals", "retention", "Yes", 100),   # old parser: first judge only
        ("1", "Court of Appeals", "retention", "No", 5),
        ("1", "President", "measure", "Yes", 0),              # #17 phantom rows
        ("1", "President", "measure", "No", 0),
    ])
    monkeypatch.setattr(reconcile, "_read_processed", lambda s: proc)
    src = reconcile.SECRETARY_OF_STATE[0]
    rows, checks = reconcile.reconcile_candidates(src, orig)
    bad = rows[rows["status"] == "mismatch"]
    assert set(bad["contest"]) >= {"Court of Appeals - B. Judge", "Court of Appeals - A. Judge"}
    assert checks["mixed_contests"] == 1   # President has Yes/No *and* a candidate


def test_candidate_reconcile_all_match_and_rcv_final(monkeypatch):
    orig = pd.DataFrame({"contest": ["Mayor", "Mayor", "Issue 2A", "Issue 2A"],
                         "candidate_or_option": ["Ann", "Bob", "YES", "For the Measure"],
                         "votes": [60, 40, 30, 5]})
    proc = _processed([
        ("1", "Mayor", "ranked_choice", "Ann | Round 1", 50),
        ("1", "Mayor", "ranked_choice", "Ann | Round 2", 10),
        ("1", "Mayor", "ranked_choice", "Ann | Final", 60),
        ("1", "Mayor", "ranked_choice", "Bob | Round 1", 40),
        ("1", "Mayor", "ranked_choice", "Bob | Final", 40),
        ("1", "Issue 2A", "measure", "Yes", 35),
    ])
    monkeypatch.setattr(reconcile, "_read_processed", lambda s: proc)
    rows, checks = reconcile.reconcile_candidates(reconcile.BOULDER_COUNTY[-1], orig)
    assert set(rows["status"]) == {"match"}
    assert len(rows) == 3
    assert checks == {"duplicate_keys": 0, "mixed_contests": 0, "mixed_examples": "",
                      "status": "compared"}


def test_structural_checks_count_duplicate_keys():
    """#23: the PDF years printed one key two or three times."""
    proc = _processed([
        ("073", "Council", "candidate", "Macon Cowles", 44),
        ("073", "Council", "candidate", "Macon Cowles", 40),
        ("073", "Council", "candidate", "Macon Cowles", 542),
    ])
    assert reconcile.structural_checks(proc)["duplicate_keys"] == 2


def test_status_thresholds():
    assert reconcile._status(0) == "match"
    assert reconcile._status(-49) == "near_match"
    assert reconcile._status(50) == "mismatch"


def test_filtered_run_keeps_other_sources_rows(tmp_path, monkeypatch):
    """#18: `reconcile --year 2025` used to rewrite the report with one year."""
    top_path = tmp_path / "reconciliation.csv"
    cand_path = tmp_path / "reconciliation-candidates.csv"
    monkeypatch.setattr(reconcile, "RECONCILIATION_CSV", top_path)
    monkeypatch.setattr(reconcile, "RECONCILIATION_CANDIDATES_CSV", cand_path)
    monkeypatch.setattr(reconcile, "_read_processed", lambda s: None)
    row = {"election_type": "general", "data_source": "secretary_of_state",
           "canonical": "x", "original_total": 1, "processed_total": 1, "delta": 0,
           "status": "match"}
    pd.DataFrame([{"year": 2020, **row}, {"year": 2016, **row}]).to_csv(top_path, index=False)
    pd.DataFrame(columns=reconcile.CANDIDATE_COLUMNS).to_csv(cand_path, index=False)
    src = next(s for s in reconcile.SECRETARY_OF_STATE if s.year == 2020)
    new = pd.DataFrame([{"year": 2020, **row, "status": "mismatch"}])
    top, cand, _ = reconcile._merge_with_existing(
        [src], new, pd.DataFrame(columns=reconcile.CANDIDATE_COLUMNS), [])
    assert sorted(top["year"].tolist()) == [2016, 2020]
    assert top.loc[top["year"] == 2020, "status"].tolist() == ["mismatch"]
