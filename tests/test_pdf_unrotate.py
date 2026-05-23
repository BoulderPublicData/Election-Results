"""Unit tests for the PDF parser's _unrotate / _looks_char_reversed helpers."""

from __future__ import annotations

from scripts.parsers.boco_pdf import _looks_char_reversed, _unrotate


class TestLooksCharReversed:
    def test_reversed_proper_case(self):
        # "Karakehian" reversed → "naihekaraK"; first lower, last upper
        assert _looks_char_reversed("naihekaraK")

    def test_normal_proper_case(self):
        assert not _looks_char_reversed("Karakehian")

    def test_empty(self):
        assert not _looks_char_reversed("")

    def test_pure_punct(self):
        assert not _looks_char_reversed("123.45")


class TestUnrotate:
    def test_passthrough_normal_text(self):
        assert _unrotate("Absentee\nVoting\nBallots\nCast") == "Absentee Voting Ballots Cast"

    def test_reverses_rotated_pair(self):
        # "George Karakehian" rotated 90° comes out as last\nfirst, each reversed.
        assert _unrotate("naihekaraK\negroeG") == "George Karakehian"

    def test_reverses_three_part(self):
        # "Susan M. Osborne" → 3 vertical rows in the PDF.
        assert _unrotate("enrobsO\n.M\nnasuS") == "Susan M. Osborne"

    def test_single_token_reverses(self):
        assert _unrotate("slatoT") == "Totals"

    def test_empty(self):
        assert _unrotate("") == ""
        assert _unrotate(None) == ""
