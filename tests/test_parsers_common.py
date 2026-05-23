"""Tests for the shared parser helpers in scripts.parsers.common."""

from __future__ import annotations

import pandas as pd

from scripts.parsers.common import (
    clean_col, infer_contest_type, normalize_choice, normalize_party,
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
        assert infer_contest_type(
            "Retention of Justice Smith — Colorado Supreme Court", "Yes"
        ) == "retention"

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
