"""Adjudicated corrections to published Statements of Votes (#44)."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts import reconcile, sov_corrections
from scripts.sources import find

COLS = sov_corrections.CORRECTION_COLUMNS


def _fixes(rows):
    return pd.DataFrame(rows, columns=COLS, dtype="string")


def _fix(action, published, corrected="", candidate="Fahey", precinct="202, 500"):
    return [
        "2023-coordinated",
        "boulder_county",
        "Ward 2",
        precinct,
        candidate,
        action,
        str(published),
        corrected,
        "county summary of votes",
        "",
    ]


DF = pd.DataFrame(
    {
        "precinct_id": ["201, 202", "201, 202", "202, 500", "202, 500", "203"],
        "contest": ["Ward 2"] * 5,
        "candidate_or_option": ["Fahey", "Colbert"] * 2 + ["Fahey"],
        "votes": [184, 234, 183, 234, 158],
    }
)


def test_drop_row_removes_exactly_the_named_rows():
    fixes = _fixes([_fix("drop_row", 183), _fix("drop_row", 234, candidate="Colbert")])
    out, notes = sov_corrections.apply(DF, fixes)
    assert out["precinct_id"].tolist() == ["201, 202", "201, 202", "203"]
    assert len(notes) == 2 and "drop_row (183 published)" in notes[0]


def test_set_votes():
    out, notes = sov_corrections.apply(DF, _fixes([_fix("set_votes", 158, "160", precinct="203")]))
    assert out["votes"].tolist() == [184, 234, 183, 234, 160]
    assert notes[0].endswith("(158 published → 160)")


def test_stale_correction_fails_the_build():
    with pytest.raises(ValueError, match="did not apply"):
        sov_corrections.apply(DF, _fixes([_fix("drop_row", 999)]))
    with pytest.raises(ValueError, match="did not apply"):
        sov_corrections.apply(DF, _fixes([_fix("drop_row", 183, precinct="202,500")]))


def test_vote_delta():
    f = _fixes([_fix("drop_row", 183), _fix("set_votes", 158, "160")])
    assert [sov_corrections.vote_delta(r) for r in f.itertuples(index=False)] == [-183, 2]


def test_load_rejects_missing_evidence_and_bad_actions(tmp_path):
    path = tmp_path / "c.csv"
    row = _fix("drop_row", 183)
    row[COLS.index("evidence")] = ""
    _fixes([row]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="without evidence"):
        sov_corrections.load(path)
    _fixes([_fix("zero_out", 183)]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="unknown action"):
        sov_corrections.load(path)
    _fixes([_fix("drop_row", 183, corrected="0")]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="corrected_votes"):
        sov_corrections.load(path)


def test_committed_corrections_louisville_ward_2():
    fixes = sov_corrections.for_source(2023, "coordinated", "boulder_county")
    assert len(fixes) == 2
    assert set(fixes["precinct_id"]) == {"2181207202, 2181207500"}
    assert {int(v) for v in fixes["published_votes"]} == {183, 234}
    assert all("Summary of Votes" in e and "vote-counting" in e for e in fixes["evidence"])


def test_reconcile_marks_a_documented_correction_as_corrected(monkeypatch):
    src = find(2023, "boulder_county")
    contest = "City of Louisville City Council Ward 2 (4-year term)"
    orig = pd.DataFrame(
        {
            "contest": [contest] * 2 + ["Other"],
            "candidate_or_option": ["Deborah Fahey", "George Colbert", "Yes"],
            "votes": [1602, 1441, 10],
        }
    )
    proc = pd.DataFrame(
        {
            "precinct_id": ["1", "1", "1"],
            "contest": [contest, contest, "Other"],
            "contest_type": ["candidate", "candidate", "measure"],
            "candidate_or_option": ["Deborah Fahey", "George Colbert", "Yes"],
            "votes": [1419, 1207, 10],
        }
    )
    monkeypatch.setattr(reconcile, "_read_processed", lambda s: proc)
    rows, _ = reconcile.reconcile_candidates(src, orig)
    st = dict(zip(rows["candidate_or_option"], rows["status"], strict=True))
    assert st == {"Deborah Fahey": "corrected", "George Colbert": "corrected", "Yes": "match"}
    top = reconcile.reconcile_source(src, reconcile._load_patterns(), orig)
    assert top.set_index("canonical").at["City of Louisville Council", "status"] == "corrected"

    # Any other difference is still a mismatch.
    proc.loc[0, "votes"] = 1500
    rows, _ = reconcile.reconcile_candidates(src, orig)
    assert rows.set_index("candidate_or_option").at["Deborah Fahey", "status"] == "mismatch"
