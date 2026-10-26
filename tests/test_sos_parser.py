"""SOS precinct-file parser (#16, #17, #25).

The fixtures reproduce the 2012-2020 "split" layout as the real files have it:
every row carries all three vote columns, with 0 where a column doesn't apply,
and several judges share one office title with the judge named in Candidate.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.parsers import sos
from scripts.schema import SourceMeta


def _meta(year: int) -> SourceMeta:
    return SourceMeta(
        election_year=year,
        election_date=f"{year}-11-08",
        election_type="general",
        data_source="secretary_of_state",
        jurisdiction_level="state",
        jurisdiction_name="Boulder County",
        source_file="sos.xlsx",
        source_url="x",
        retrieved_at="2026-01-01T00:00:00+00:00",
        extraction_quality="machine_readable",
    )


def _split_rows() -> pd.DataFrame:
    rows = []
    for precinct in (2161307900, 2161307901):
        base = {
            "State": "Colorado",
            "Year": 2016,
            "Election Type": "G",
            "County": "Boulder",
            "Precinct": precinct,
        }
        rows += [
            {
                **base,
                "Office/Issue/Judgeship": "President/Vice President",
                "Candidate": "Hillary Clinton / Tim Kaine",
                "Party": "Democratic Party",
                "Candidate Votes": 353,
                "Yes Votes": 0,
                "No Votes": 0,
            },
            {
                **base,
                "Office/Issue/Judgeship": "President/Vice President",
                "Candidate": "Darrell L. Castle / Scott N. Bradley",
                "Party": "American Constitution Party",
                "Candidate Votes": 0,
                "Yes Votes": 0,
                "No Votes": 0,
            },
            {
                **base,
                "Office/Issue/Judgeship": "Court of Appeals",
                "Candidate": "Karen M. Ashby",
                "Party": None,
                "Candidate Votes": 0,
                "Yes Votes": 235,
                "No Votes": 36,
            },
            {
                **base,
                "Office/Issue/Judgeship": "Court of Appeals",
                "Candidate": "Anthony J. Navarro",
                "Party": None,
                "Candidate Votes": 0,
                "Yes Votes": 195,
                "No Votes": 62,
            },
            {
                **base,
                "Office/Issue/Judgeship": "County Court, Boulder",
                "Candidate": "John F. Stavely",
                "Party": None,
                "Candidate Votes": 0,
                "Yes Votes": 223,
                "No Votes": 71,
            },
            {
                **base,
                "Office/Issue/Judgeship": "Amendment T (CONSTITUTIONAL)",
                "Candidate": None,
                "Party": None,
                "Candidate Votes": 0,
                "Yes Votes": 321,
                "No Votes": 86,
            },
        ]
    # A judge with zero votes in one precinct is still a retention row.
    rows.append(
        {
            **rows[0],
            "Precinct": 2161307902,
            "Office/Issue/Judgeship": "Court of Appeals",
            "Candidate": "Karen M. Ashby",
            "Party": None,
            "Candidate Votes": 0,
            "Yes Votes": 0,
            "No Votes": 0,
        }
    )
    # Another county's rows are ignored.
    rows.append({**rows[0], "County": "Denver", "Candidate Votes": 9999})
    return pd.DataFrame(rows)


@pytest.fixture
def split_out(tmp_path):
    path = tmp_path / "2016.xlsx"
    _split_rows().to_excel(path, index=False)
    return sos.parse(path, _meta(2016))


def test_every_judge_keeps_its_retention_votes(split_out):
    """#16: the old dedupe on (precinct, office) kept only the first judge."""
    ret = split_out[split_out["contest_type"] == "retention"]
    totals = ret.groupby(["contest", "candidate_or_option"])["votes"].sum().to_dict()
    assert totals == {
        ("Court of Appeals - Karen M. Ashby", "Yes"): 470,
        ("Court of Appeals - Karen M. Ashby", "No"): 72,
        ("Court of Appeals - Anthony J. Navarro", "Yes"): 390,
        ("Court of Appeals - Anthony J. Navarro", "No"): 124,
        ("County Court, Boulder - John F. Stavely", "Yes"): 446,
        ("County Court, Boulder - John F. Stavely", "No"): 142,
    }


def test_no_phantom_yes_no_rows_on_candidate_contests(split_out):
    """#17: every candidate contest used to gain 0-vote Yes/No rows."""
    pres = split_out[split_out["contest"] == "President/Vice President"]
    assert set(pres["candidate_or_option"]) == {
        "Hillary Clinton / Tim Kaine",
        "Darrell L. Castle / Scott N. Bradley",
    }
    assert set(pres["contest_type"]) == {"candidate"}


def test_no_zero_vote_candidate_rows_for_judges(split_out):
    """#17: every judge used to also appear as a 0-vote 'candidate'."""
    assert (
        not split_out["candidate_or_option"]
        .isin(["Karen M. Ashby", "Anthony J. Navarro", "John F. Stavely"])
        .any()
    )


def test_zero_vote_precinct_is_still_retention(split_out):
    z = split_out[split_out["precinct_id"] == "2161307902"]
    assert set(z["candidate_or_option"]) == {"Yes", "No"}
    assert set(z["contest_type"]) == {"retention"}


def test_measures_and_totals_preserved(split_out):
    m = split_out[split_out["contest"] == "Amendment T (CONSTITUTIONAL)"]
    assert m.groupby("candidate_or_option")["votes"].sum().to_dict() == {"Yes": 642, "No": 172}
    assert set(m["contest_type"]) == {"measure"}
    raw = _split_rows()
    raw = raw[raw["County"] == "Boulder"]
    expected = raw[["Candidate Votes", "Yes Votes", "No Votes"]].sum().sum()
    assert split_out["votes"].sum() == expected


def test_no_duplicate_keys(split_out):
    assert not split_out.duplicated(["precinct_id", "contest", "candidate_or_option"]).any()


def test_unified_layout_county_court_is_retention(tmp_path):
    """#25: 2004's 'Reed of the Boulder County Court' was typed 'measure'."""
    path = tmp_path / "2004.xlsx"
    pd.DataFrame(
        {
            "County": ["BOULDER   ", "BOULDER   "],
            "Precinct": [2181007001, 2181007001],
            "Office/Ballot Issue": ["Reed of the Boulder County Court"] * 2,
            "Candidate/Yes or No": ["YES", "NO"],
            "Party": [None, None],
            "Votes": [300, 80],
        }
    ).to_excel(path, index=False)
    out = sos.parse(path, _meta(2004))
    assert set(out["contest_type"]) == {"retention"}
    assert set(out["candidate_or_option"]) == {"Yes", "No"}
