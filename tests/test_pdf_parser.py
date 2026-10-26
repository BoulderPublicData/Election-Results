"""Boulder County PDF parser (2005/2007/2009, #23).

Unit tests use text lines copied from the PDFs. The golden tests parse a few
pages of each committed PDF (skipped when the raw file is absent) and pin
values read by eye from the source page.
"""

from __future__ import annotations

import pytest

from scripts.clean import _meta_for
from scripts.config import BOULDER_COUNTY, original_path
from scripts.parsers import boco_pdf
from scripts.parsers.boco_pdf import _drop_row_total, _parse_data_row, _split_row


class TestSplitRow:
    def test_2007_four_meta_columns(self):
        # Precinct, Election Ballots, Total Ballots, Registered, Percent, then votes.
        p, meta, values = _split_row("073 96 96 251 38.25% 41 12 5 24 38 53 44 7")
        assert p == "073"
        assert meta == ["96", "96", "251", "38.25%"]
        assert values == [41, 12, 5, 24, 38, 53, 44, 7]

    def test_2009_six_meta_columns(self):
        p, meta, values = _split_row("111 269 0 0 269 653 41.19% 158 133 101 8 112 78 28")
        assert len(meta) == 6 and values == [158, 133, 101, 8, 112, 78, 28]

    def test_pseudo_precinct_code(self):
        p, _, values = _split_row("RMFPD 44 0 0 44 0 0.00% 15 29 44")
        assert p == "RMFPD" and values == [15, 29, 44]

    def test_comma_thousands(self):
        _, meta, values = _split_row("183 530 0 0 530 1,388 38.18% 191 307 17 515")
        assert meta[-2] == "1,388" and values == [191, 307, 17, 515]

    def test_non_data_lines(self):
        assert _split_row("Totals: 17,576 17,576 48,267 6,838") is None
        assert _split_row("Page 1 of 108 11/15/2007 09:11 AM") is None


class TestRowTotal:
    def test_trailing_total_column_dropped(self):
        assert _drop_row_total([137, 26, 102, 96, 102, 13, 618], 6, has_totals=True) == [
            137,
            26,
            102,
            96,
            102,
            13,
        ]

    def test_no_total_column(self):
        assert _drop_row_total([158, 133, 101], 3, has_totals=False) == [158, 133, 101]

    def test_width_mismatch_is_none(self):
        assert _drop_row_total([305], 8, has_totals=True) is None


def test_parse_data_row_uses_meta_from_the_end():
    p, meta, votes = _parse_data_row("073 96 96 251 38.25% 41 12 5", 3)
    assert meta == {"total_ballots": 96, "registered_voters": 251}
    assert votes == [41, 12, 5]


def _source(year):
    s = next(s for s in BOULDER_COUNTY if s.year == year)
    path = original_path(s.data_source, s.local_filename)
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    return s, path


@pytest.mark.parametrize(
    ("year", "pages", "precinct", "candidate", "votes"),
    [
        # 2007 p.1: "073 96 96 251 38.25% 41 12 5 24 38 53 44 7" — Macon Cowles is the
        # 5th candidate (the old parser reported 44 / 40 / 542 for this key).
        (2007, range(1, 11), "073", "Macon Cowles", 38),
        # 2007 p.4 (second candidate group, "Continued"): Lisa Morzel is the 5th of 8.
        (2007, range(1, 11), "073", "Lisa Morzel", 43),
        # 2009 p.4 (second group on a Continued page, with a Totals column).
        (2009, range(1, 7), "073", "Barry Siff", 51),
    ],
)
def test_golden_values(year, pages, precinct, candidate, votes):
    s, path = _source(year)
    df = boco_pdf.parse(path, _meta_for(s), pages=pages)
    r = df[(df["precinct_id"] == precinct) & (df["candidate_or_option"] == candidate)]
    assert r["votes"].tolist() == [votes]


@pytest.mark.parametrize(
    ("year", "pages"),
    [
        (2005, range(53, 56)),  # Lafayette council: a two-line rotated label
        (2007, range(1, 11)),  # Boulder council: three candidate groups
        (2009, range(1, 9)),  # Boulder + Lafayette council, Totals-only last page
    ],
)
def test_pages_sum_to_printed_totals_without_duplicates(year, pages):
    s, path = _source(year)
    df = boco_pdf.parse(path, _meta_for(s), pages=pages)
    assert not df.duplicated(["precinct_id", "contest", "candidate_or_option"]).any()
    totals = boco_pdf.published_totals(path, pages=pages)
    got = df.groupby(["contest", "candidate_or_option"])["votes"].sum()
    want = totals.set_index(["contest", "candidate_or_option"])["votes"]
    want = want[want.index.isin(got.index)]
    assert len(want) > 0
    assert got.loc[want.index].tolist() == want.tolist()
