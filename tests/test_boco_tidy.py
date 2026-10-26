"""Regression tests for the Boulder tidy-format SoV parser."""

from __future__ import annotations

import pandas as pd

from scripts.parsers import boco_tidy
from scripts.schema import SourceMeta


def _meta(name: str) -> SourceMeta:
    return SourceMeta(
        election_year=2023,
        election_date="2023-11-07",
        election_type="coordinated",
        data_source="boulder_county",
        jurisdiction_level="county",
        jurisdiction_name="Boulder County",
        source_file=name,
        source_url="",
        retrieved_at="",
        extraction_quality="machine_readable",
    )


def test_property_owner_rows_are_kept(tmp_path):
    """2023/2025 SoVs report property-owner ballots on rows with a Precinct
    Code of 'Property Owner' and no Precinct Number. They count toward the
    certified totals, so they must not be rejected (Nederland 6A came up
    101 Yes / 43 No short before this fix)."""
    contest = "Nederland Eco Pass Public Improvement District Ballot Issue 6A"
    sheet = pd.DataFrame(
        {
            "Precinct\nCode": ["904", "904", "Property Owner", "Property Owner"],
            "Precinct\nNumber": [2154907904, 2154907904, None, None],
            "Active\nVoters": [1213, 1213, None, None],
            "Contest Title": [contest] * 4,
            "Choice Name": ["Yes/For", "No/Against", "Yes/For", "No/Against"],
            "Total\nBallots": [605, 605, 145, 145],
            "Total\nVotes": [498, 97, 101, 43],
        }
    )
    path = tmp_path / "2023-coordinated-sov.xlsx"
    sheet.to_excel(path, sheet_name="Plurality", index=False)

    out = boco_tidy.parse(path, _meta(path.name))

    assert len(out) == 4
    assert out.groupby("candidate_or_option")["votes"].sum().to_dict() == {"Yes": 599, "No": 140}
    po = out[out["precinct_name"] == "Property Owner"]
    assert (po["precinct_id"] == "Property Owner").all()
    assert "Property Owner" in out["extraction_notes"].iloc[0]
