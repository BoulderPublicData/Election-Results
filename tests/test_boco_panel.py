"""Boulder County panel-format parser (2008-2012): #20 column alignment and
#24 party splitting.

The synthetic sheet reproduces the real files' quirks: header labels sit in
different spreadsheet columns than their values, one precinct prints its
number on a row of its own with the values two rows below, a property-owner
pseudo-precinct uses a letter code, and the Totals row omits Percent Turnout.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts import reject
from scripts.parsers import boco_panel
from scripts.parsers.boco_panel import split_party
from scripts.schema import SourceMeta

WIDTH = 26
META_HEADERS = {
    0: "Precinct", 4: "Absentee\nVoting\nBallots\nCast", 6: "Early\nVoting\nBallots\nCast",
    8: "Election\nDay\nBallots\nCast", 10: "Total\nBallots Cast", 12: "Registered\nVoters",
    14: "Percent\nTurnout",
}


def _row(cells: dict[int, object]) -> list[object]:
    r = [None] * WIDTH
    for i, v in cells.items():
        r[i] = v
    return r


def _banner(title: str) -> list[list[object]]:
    return [
        _row({0: "Canvass Report  —  Total Voters  —  Official"}),
        _row({0: "Boulder County, CO  —  GENERAL ELECTION NOVEMBER 2008  —  November 04, 2008"}),
        _row({9: "Page 1 of 2", 18: "11/21/2008 02:37 PM"}),
        _row({0: "Total Number of Voters: 172,531 of 218,610 = 78.92%"}),
        _row({0: title}),
        _row({}),
    ]


def _data(precinct, values: list[object]) -> list[object]:
    """Values land in the columns the real 2008 file uses — NOT under their headers."""
    positions = [4, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 18]
    cells = {} if precinct is None else {0: precinct}
    cells.update(dict(zip(positions, values, strict=False)))
    return _row(cells)


def _sheet() -> pd.DataFrame:
    rows = _banner("UNITED STATES SENATOR")
    rows.append(_row({**META_HEADERS, 15: "\nBob Schaffer Republican", 17: "\nMark Udall Democratic",
                      19: "REP\nKen Buck", 21: "\nBruce E. Lohmiller - GRN", 25: "Continued"}))
    rows.append(_data("001", ["236", "35", 52.0, "323", 426, 75.8, 129, 191, 0, 1]))
    rows.append(_row({0: "002"}))                     # precinct printed alone…
    rows.append(_row({}))
    rows.append(_data(None, ["365", "27", 131.0, "523", 649, 80.6, 181, 331, 0, 2]))  # …values below
    rows.append(_data("FMFPD", ["29", "0", 0.0, "29", 0, 0, 10, 19, 0, 0]))
    rows.append(_row({0: "Totals:", 4: 630, 6: 62, 8: 183, 10: 875, 12: 1075,
                      14: 320, 15: 541, 16: 0, 17: 3}))
    rows += _banner("CITY OF BOULDER BALLOT QUESTION 2A")
    rows.append(_row({**META_HEADERS, 15: "\nFOR THE MEASURE", 17: "\nAGAINST THE MEASURE"}))
    rows.append(_data("001", ["236", "35", 52.0, "323", 426, 75.8, 200, 100]))
    rows.append(_data("003", ["10", "1", 2.0]))       # too short: rejected, not guessed
    rows.append(_row({0: "Totals:", 4: 236, 6: 35, 8: 52, 10: 323, 12: 426, 14: 200, 15: 100}))
    return pd.DataFrame(rows)


def _meta() -> SourceMeta:
    return SourceMeta(
        election_year=2008, election_date="2008-11-04", election_type="general",
        data_source="boulder_county", jurisdiction_level="county",
        jurisdiction_name="Boulder County", source_file="panel.xlsx", source_url="x",
        retrieved_at="2026-01-01T00:00:00+00:00", extraction_quality="machine_readable",
    )


@pytest.fixture
def panel_path(tmp_path):
    path = tmp_path / "panel.xlsx"
    _sheet().to_excel(path, index=False, header=False)
    return path


@pytest.fixture
def parsed(panel_path):
    reject.reset()
    out = boco_panel.parse(panel_path, _meta())
    rejected = reject.drain()
    return out, rejected


def _votes(df, precinct, candidate):
    r = df[(df["precinct_id"] == precinct) & (df["candidate_or_option"] == candidate)]
    assert len(r) == 1, (precinct, candidate, r)
    return r.iloc[0]


def test_values_align_with_labels_not_spreadsheet_columns(parsed):
    df, _ = parsed
    r = _votes(df, "001", "Bob Schaffer")
    assert (r["votes"], r["ballots_cast"], r["active_voters"]) == (129, 323, 426)
    assert _votes(df, "001", "Mark Udall")["votes"] == 191
    assert _votes(df, "001", "Ken Buck")["votes"] == 0
    assert _votes(df, "001", "Bruce E. Lohmiller")["votes"] == 1


def test_precinct_on_its_own_row_is_joined_to_its_values(parsed):
    df, _ = parsed
    r = _votes(df, "002", "Mark Udall")
    assert (r["votes"], r["ballots_cast"], r["active_voters"]) == (331, 523, 649)


def test_active_voters_never_below_ballots_for_real_precincts(parsed):
    df, _ = parsed
    real = df[df["precinct_id"].str.fullmatch(r"\d+")].drop_duplicates("precinct_id")
    assert (real["active_voters"] >= real["ballots_cast"]).all()


def test_pseudo_precinct_code_kept(parsed):
    df, _ = parsed
    assert _votes(df, "FMFPD", "Mark Udall")["votes"] == 19


def test_sums_match_the_files_totals_row(parsed, panel_path):
    df, _ = parsed
    totals = boco_panel.published_totals(panel_path, 2008)
    got = df.groupby(["contest", "candidate_or_option"])["votes"].sum()
    want = totals.groupby(["contest", "candidate_or_option"])["votes"].sum()
    assert got.sort_index().to_dict() == want.sort_index().to_dict()


def test_for_against_the_measure_become_yes_no(parsed):
    """#24: 'FOR THE MEASURE' used to become party FOR, candidate 'THE MEASURE'."""
    df, _ = parsed
    m = df[df["contest"] == "CITY OF BOULDER BALLOT QUESTION 2A"]
    assert set(m["candidate_or_option"]) == {"Yes", "No"}
    assert set(m["contest_type"]) == {"measure"}
    assert m["party"].isna().all()


def test_short_row_goes_to_reject_port(parsed):
    df, rejected = parsed
    assert "003" not in set(df["precinct_id"])
    assert rejected["reason"].tolist() == ["panel_row_width_mismatch"]


@pytest.mark.parametrize(("label", "year", "expected"), [
    ("\nJohn McCain /  Sarah Palin Republican", 2008, ("John McCain / Sarah Palin", "REP")),
    ("\nGene C. Amondson /  Leroy J. Pletten  Prohibition", 2008,
     ("Gene C. Amondson / Leroy J. Pletten", "PRB")),
    ("\nBrian Moore /  Stewart A. Alexander Socialist, USA", 2008,
     ("Brian Moore / Stewart A. Alexander", "SPU")),          # was party "USA"
    ("\nAlan Keyes /  Brian Rohrbough America's ", 2008, ("Alan Keyes / Brian Rohrbough", "AMI")),
    ("\nDouglas \"Dayhorse\" Campbell American Constitution", 2008,
     ("Douglas \"Dayhorse\" Campbell", "ACN")),
    ("REP\nKen Buck", 2010, ("Ken Buck", "REP")),
    ("\nMichele M. Newman - UAF", 2010, ("Michele M. Newman", "UAF")),  # was "Michele M. Newman -"
    ("\nWillie Travis Chambers / Ed E. Coron - DEM / REP", 2010,
     ("Willie Travis Chambers / Ed E. Coron", "DEM / REP")),
    ("Barack Obama /  Joe Biden    Democratic", 2012, ("Barack Obama / Joe Biden", "DEM")),
    ("Tom Hoefling /  Jonathan D. Ellis    America's", 2012,
     ("Tom Hoefling / Jonathan D. Ellis", "AMP")),
    ("\nFOR THE MEASURE", 2011, ("Yes", None)),
    ("   Against the measure", 2011, ("No", None)),
    ("\nLee Kemp", 2008, ("Lee Kemp", None)),
    ("   Mark Gelband", 2011, ("Mark Gelband", None)),
])
def test_split_party(label, year, expected):
    name, party = split_party(label, year)
    assert name == expected[0]
    if expected[1] is None:
        assert pd.isna(party)
    else:
        assert party == expected[1]
