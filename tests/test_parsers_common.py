"""Tests for the shared parser helpers in scripts.parsers.common."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.parsers.common import (
    clean_col,
    infer_contest_type,
    normalize_choice,
    normalize_party,
    precinct_id_str,
)


class TestNormalizeChoice:
    def test_yes_variants(self):
        for v in ["Yes", "yes", "YES", "Yes/For", "For", "Yes/Sí", "Y"]:
            assert normalize_choice(v) == "Yes", v

    def test_no_variants(self):
        for v in ["No", "no", "NO", "No/Against", "Against", "N"]:
            assert normalize_choice(v) == "No", v

    def test_unknown_value_passes_through(self):
        assert normalize_choice("John Smith") == "John Smith"

    def test_na_passes_through(self):
        assert pd.isna(normalize_choice(pd.NA))


class TestNormalizeParty:
    def test_long_form_mapped(self):
        assert normalize_party("Democratic Party") == "DEM"
        assert normalize_party("Republican Party") == "REP"
        assert normalize_party("Libertarian") == "LBR"

    def test_short_codes_passed_through(self):
        assert normalize_party("DEM") == "DEM"
        assert normalize_party("REP") == "REP"

    def test_blank_returns_na(self):
        assert pd.isna(normalize_party(""))
        assert pd.isna(normalize_party(pd.NA))


class TestInferContestType:
    def test_yes_no_is_measure(self):
        assert infer_contest_type("Proposition CC (Statutory)", "Yes") == "measure"
        assert infer_contest_type("Proposition CC", "No") == "measure"

    def test_retention_detected(self):
        assert (
            infer_contest_type("Retention of Justice Smith — Colorado Supreme Court", "Yes")
            == "retention"
        )

    def test_recall_detected(self):
        assert infer_contest_type("Recall of County Commissioner X", "Yes") == "recall"

    def test_candidate_is_default(self):
        assert infer_contest_type("United States Senator", "John Doe") == "candidate"

    def test_handles_na_inputs(self):
        # Must not raise even when columns are pd.NA (2025 fix).
        assert infer_contest_type(pd.NA, "Yes") == "measure"
        assert infer_contest_type("X", pd.NA) == "candidate"


class TestPrecinctIdStr:
    def test_preserves_leading_zeros(self):
        assert precinct_id_str("0085") == "0085"

    def test_int_input(self):
        assert precinct_id_str(2181007800) == "2181007800"

    def test_float_input_drops_decimal(self):
        assert precinct_id_str(2181007800.0) == "2181007800"

    def test_composite_preserved(self):
        assert precinct_id_str("800, 403") == "800, 403"

    def test_na_passes_through(self):
        assert pd.isna(precinct_id_str(pd.NA))


def test_clean_col_collapses_whitespace():
    assert clean_col("Active \nVoters") == "Active Voters"
    assert clean_col("Total\nBallots Cast") == "Total Ballots Cast"
    assert clean_col("  Contest\rTitle  ") == "Contest Title"


class TestRetentionPhrasings:
    """#25: county and district court judges were typed 'measure'."""

    @pytest.mark.parametrize(
        "title",
        [
            "County Court, Boulder",  # SOS 2012+
            "District Court, 20th Judicial District",  # SOS 2012+
            "COUNTY JUDGE, BOULDER - Thomas J.B. Reed",  # 2008
            "Boulder County Court: David A. Archuleta",  # 2010
            "Reed of the Boulder County Court",  # 2004
            "District Court Judge - 20th Judicial District - Hartman",
            "Court of Appeals - Anthony J. Navarro",
        ],
    )
    def test_retention(self, title):
        assert infer_contest_type(title, "Yes") == "retention"
        assert infer_contest_type(title, "No") == "retention"

    @pytest.mark.parametrize(
        "title",
        [
            "City of Boulder Ballot Issue 2D - Authorize Retention of All Sugar-Sweetened "
            "Beverages Tax Revenue",
            "Proposition BB (STATUTORY) Retain Revenue in Excess of Blue Book Estimate",
        ],
    )
    def test_revenue_retention_is_a_measure(self, title):
        assert infer_contest_type(title, "Yes") == "measure"


class TestChoiceVariants:
    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("FOR THE MEASURE", "Yes"),
            ("For the measure", "Yes"),
            ("For The Measure", "Yes"),
            ("AGAINST THE MEASURE", "No"),
            ("Against the Measure", "No"),
            ("FOR THE ISSUE", "Yes"),
            ("AGAINST THE ISSUE", "No"),
            ("FOR", "Yes"),
            ("AGAINST", "No"),
            ("AGAINST THE", "No"),
            ("  YES ", "Yes"),
            ("Yes/Sí", "Yes"),
        ],
    )
    def test_maps_to_yes_no(self, raw, want):
        assert normalize_choice(raw) == want


class TestPartyDrift:
    """#33: one code per party across sources and years."""

    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("UNI", "UTY"),
            ("Unity", "UTY"),
            ("Unity Party of Colorado", "UTY"),
            ("LIB", "LBR"),
            ("UNA", "UAF"),
            ("APV", "AVP"),
            ("Approval Voting Party", "AVP"),
            ("AMS", "ASP"),
            ("ALL", "ALP"),
            ("Socialist Workers Party", "SWP"),
            ("Socialism and Liberation", "SLB"),
            ("Prohibition Party", "PRB"),
            ("DEM/REP", "DEM / REP"),
            ("Unaffiliated / Republican", "UAF / REP"),
            ("Democratic   Party", "DEM"),
        ],
    )
    def test_canonical(self, raw, want):
        assert normalize_party(raw) == want

    def test_zero_is_no_party(self):
        assert pd.isna(normalize_party("0"))


class TestPrecinctIds:
    """#27: composite separators and pseudo-precincts."""

    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("2181207201,2181207202", "2181207201, 2181207202"),  # 2023
            ("073 + 74", "073, 74"),  # 2011
            ("128+132+133+  232+233", "128, 132, 133, 232, 233"),  # 2011
            ("2181007800, 2181207403", "2181007800, 2181207403"),
            ("002-004", "002-004"),  # 2010: may be a range
            ("Landowner-FMLV, Landowner-LV", "Landowner-FMLV, Landowner-LV"),
        ],
    )
    def test_normalize(self, raw, want):
        from scripts.parsers.common import normalize_precinct_id

        assert normalize_precinct_id(raw) == want

    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("2181007800", False),
            ("073", False),
            ("002-004", False),
            ("2181007800, 2181207403", False),
            ("Property Owner", True),
            ("Landowner", True),
            ("LANDOWNER", True),
            ("Landowner CCCPR", True),
            ("RMFPD", True),
            ("004, 005, LFPD", True),
            ("2181307910, Landowner", True),
            ("Property Owner, 627", True),
            ("SUM", True),
            ("Provisional", True),
        ],
    )
    def test_is_pseudo(self, raw, want):
        from scripts.parsers.common import is_pseudo_precinct

        assert is_pseudo_precinct(raw) is want
