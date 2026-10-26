"""Tests for the election-night vote-counting pipeline.

Parser tests run on inline Markdown shaped like Datalab's output for the
Boulder County results page; output tests skip when the processed CSVs are
not on disk (same convention as test_processed_outputs.py).
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts import vote_counting as vc
from scripts.parsers.boco_vote_counting import (
    parse_datetime,
    parse_rcv_report,
    parse_snapshot,
    split_candidate,
    split_title,
)
from scripts.schema import VOTE_COUNTING_COLUMNS, VOTE_COUNTING_SUMMARY_COLUMNS
from scripts.vote_counting_tiles import cut_points

SAMPLE = """
# 2015 Coordinated Election November 3, 2015

**Official Results**
Last Updated:
11/3/2015 7:00 PM

View Results    Statewide Contests and Other Counties

| Election Summary                                  |                                 |
|---------------------------------------------------|---------------------------------|
| *Total Voters Registered: 247,752                 | Total Ballots Counted includes: |
| *Active Registered Voters: 192,933                | Mail Ballots                    |
| Property-owner Ballots                            | <b>121</b>                      |
| Total Ballots Counted:                            | 35,919                          |
| * Voter Registration Figures as of Nov. 3 - 8:00 p.m. |                             |

## RESULTS - ALL CONTESTS

| City of Boulder Council Candidates<br>(Vote for no more than Four) |             |       |         |
|-----------------------------------------------|-------------|-------|---------|
| CANDIDATE                                     |             | VOTES | PERCENT |
| Mark Udall - Democratic                       | <div></div> | 300   | 60.00%  |
| Cory Gardner - Republican                     | <div></div> | 199   | 39.80%  |
| Willoughby - Unaffiliated - Write-in Candidate | <div></div> | 1    | 0.20%   |
| TOTAL VOTES:                                  |             | 500   |         |

| City of Boulder Mayoral Candidates |
|---|
| Visit our [Ranked Choice Voting results page](#) |

### **City of Boulder Ballot Question 2R** **Compensation for Council Members**

|                     |             | VOTES | PERCENT |
|---------------------|-------------|-------|---------|
| For the Measure     | <div></div> | 4,187 | 42.82%  |
| Against the Measure | <div></div> | 5,591 | 57.18%  |
| TOTAL VOTES:        |             | 9,778 |         |

| Town Question 2C |             |        |         |
|------------------|-------------|--------|---------|
|                  |             | VOTES  | PERCENT |
| YES/FOR          | <div></div> | 51,35  | 6.95%   |
| <b>TOTAL VOTES:</b> |          | <b>64</b> |      |
"""


@pytest.fixture
def snap():
    return parse_snapshot(SAMPLE)


def test_header(snap):
    assert snap.results_label == "Official Results"
    assert snap.last_updated == "2015-11-03T19:00:00"


def test_summary_pairs_and_notes(snap):
    assert snap.summary["total_registration"] == 247_752
    assert snap.summary["active_registered_voters"] == 192_933
    assert snap.summary["property_owner_ballots"] == 121
    assert snap.summary["total_ballots_counted"] == 35_919
    assert snap.summary["mail_ballots"] is None  # label shown with no value
    assert snap.other_fields == {}
    assert any("Registration Figures as of Nov. 3" in n for n in snap.summary_notes)


def test_contests_and_titles(snap):
    titles = [" ".join(c.title_lines) for c in snap.contests]
    assert titles[0] == "City of Boulder Council Candidates (Vote for no more than Four)"
    # Heading lifted out of the table above a header-first table; the
    # link-only RCV card in between must not leak into it.
    assert titles[1] == "City of Boulder Ballot Question 2R Compensation for Council Members"
    assert snap.contests[0].total_votes == 500
    assert [c["votes"] for c in snap.contests[1].candidates] == [4187, 5591]


def test_malformed_row_is_reported_not_dropped(snap):
    assert ("Town Question 2C", "YES/FOR 51,35 6.95%") in snap.unparsed
    town = snap.contests[-1]
    assert town.candidates == [] and town.total_votes == 64


def test_split_title():
    assert split_title(["Council", "(Vote for no more than Four)"]) == ("Council", 4)
    assert split_title(["Council (Vote for 5)"]) == ("Council", 5)
    assert split_title(["Trustee", "Vote for not more than Nine"]) == ("Trustee", 9)
    assert split_title(["United States Senator"]) == ("United States Senator", None)


@pytest.mark.parametrize("raw,expected", [
    ("Mark Udall - Democratic", ("Mark Udall", "DEM", False)),
    ("Hillary Clinton / Tim Kaine - Democratic", ("Hillary Clinton / Tim Kaine", "DEM", False)),
    ("Willoughby - Unaffiliated - Write-in Candidate", ("Willoughby", "UAF", True)),
    ("Mike Watson - Write-In", ("Mike Watson", pd.NA, True)),
    ("Lynn Greer - Certified Write-in Candidate", ("Lynn Greer", pd.NA, True)),
    ("YES/FOR", ("Yes", None, False)),
    # Local questions' For/Against labels normalize to Yes/No, as in the SoV (#24).
    ("Against the Measure", ("No", None, False)),
    ("Nicole Speer", ("Nicole Speer", None, False)),
])
def test_split_candidate(raw, expected):
    name, party, write_in = split_candidate(raw)
    assert name == expected[0] and write_in == expected[2]
    if expected[1] is None or expected[1] is pd.NA:
        assert party is None or party is pd.NA
    else:
        assert party == expected[1]


def test_parse_datetime():
    assert parse_datetime("11/10/2022 4:41 PM") == "2022-11-10T16:41:00"
    assert parse_datetime("11/4/2014 12:05 AM") == "2014-11-04T00:05:00"
    assert parse_datetime("no date here") is None


def test_cut_points_respect_gaps_and_limit():
    gaps = [500, 1900, 3500, 3700, 6000]
    cuts = cut_points(7000, gaps, max_tile=3600)
    assert cuts[0] == 0 and cuts[-1] == 7000
    assert all(c in gaps for c in cuts[1:-1])
    assert all(b - a <= 3600 for a, b in zip(cuts, cuts[1:], strict=False))


def test_stale_correction_raises(snap, tmp_path):
    shot = vc.Screenshot("2015C", 2015, "coordinated", vc.INPUT_DIR / "2015C" / "x.jpeg")
    fixes = pd.DataFrame([{
        "source_file": shot.source_file, "contest": "City of Boulder Ballot Question 2R "
        "Compensation for Council Members", "candidate": "For the Measure", "field": "votes",
        "ocr_value": "9999", "corrected_value": "1", "note": "",
    }])
    with pytest.raises(ValueError, match="did not apply"):
        vc.apply_corrections(shot, snap, fixes)


def test_add_row_correction(snap):
    shot = vc.Screenshot("2015C", 2015, "coordinated", vc.INPUT_DIR / "2015C" / "x.jpeg")
    fixes = pd.DataFrame([{
        "source_file": shot.source_file, "contest": "Town Question 2C", "candidate": "",
        "field": "add_row", "ocr_value": "YES/FOR 51,35 6.95%",
        "corrected_value": "YES/FOR|64|100.00", "note": "",
    }])
    applied, _ = vc.apply_corrections(shot, snap, fixes)
    assert applied == 1 and snap.unparsed == []
    assert snap.contests[-1].candidates[0]["votes"] == 64
    assert vc.qa_snapshot(shot, snap) == []


RCV_PDF = vc.INPUT_DIR / "2023C" / "City of Boulder Mayor RCV Short Report (9).pdf"


@pytest.mark.skipif(not RCV_PDF.exists(), reason="RCV report not on disk")
def test_rcv_report():
    stamp, rows = parse_rcv_report(RCV_PDF)
    assert stamp == "2023-11-16T14:26:33"
    brockett = {r["round"]: r["votes"] for r in rows if r["raw"] == "Aaron Brockett"}
    assert brockett == {1: 11504, 2: 16823}
    assert {r["raw"] for r in rows} == {"Aaron Brockett", "Nicole Speer", "Bob Yates",
                                        "Paul Tweedlie"}


# ---------------------------------------------------------------------------
# Processed outputs
# ---------------------------------------------------------------------------

needs_outputs = pytest.mark.skipif(
    not (vc.CONTESTS_CSV.exists() and vc.SUMMARY_CSV.exists() and vc.QA_CSV.exists()),
    reason="vote-counting CSVs not built locally")


@needs_outputs
def test_output_columns():
    assert list(pd.read_csv(vc.CONTESTS_CSV, nrows=1).columns) == VOTE_COUNTING_COLUMNS
    assert list(pd.read_csv(vc.SUMMARY_CSV, nrows=1).columns) == VOTE_COUNTING_SUMMARY_COLUMNS


@needs_outputs
def test_no_open_qa_issues():
    qa = pd.read_csv(vc.QA_CSV)
    assert (qa["status"] == "open").sum() == 0, qa[qa["status"] == "open"].head()


@needs_outputs
def test_candidate_votes_sum_to_contest_totals():
    df = pd.read_csv(vc.CONTESTS_CSV, low_memory=False)
    web = df[df["contest_type"] != "ranked_choice"]
    g = web.groupby(["source_file", "contest"]).agg(
        votes=("votes", "sum"), total=("contest_total_votes", "first"))
    assert (g["votes"] == g["total"]).all(), g[g["votes"] != g["total"]].head()


@needs_outputs
def test_one_final_snapshot_per_election():
    s = pd.read_csv(vc.SUMMARY_CSV)
    assert (s.groupby("election_year")["is_final_snapshot"].sum() == 1).all()
    assert s.groupby("election_year")["snapshot_seq"].apply(
        lambda x: list(x) == list(range(1, len(x) + 1))).all()


@needs_outputs
def test_vote_change_rebuilds_cumulative_votes():
    """Summing vote_change over snapshots must give the final cumulative votes
    for every candidate present in every snapshot."""
    df = pd.read_csv(vc.CONTESTS_CSV, low_memory=False)
    web = df[df["contest_type"] != "ranked_choice"]
    key = ["election_year", "contest", "candidate_or_option"]
    complete = web.groupby(key)["vote_change"].transform(lambda s: s.notna().all())
    w = web[complete]
    rebuilt = w.groupby(key)["vote_change"].sum()
    final = w[w["is_final_snapshot"]].set_index(key)["votes"]
    assert (rebuilt.loc[final.index] == final).all()


@needs_outputs
def test_cache_covers_every_screenshot():
    shots = vc.discover()
    missing = [s.source_file for s in shots if not s.cache_path.exists()]
    assert missing == []
