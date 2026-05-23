"""Tests for the discovery module.

Uses cached HTML fixtures captured 2026-05; re-capture by running:

    curl -sL -A "Mozilla/5.0" https://bouldercounty.gov/elections/results/ \
        > tests/fixtures/boco-results-2026-05.html
    curl -sL -A "Mozilla/5.0" \
        https://www.coloradosos.gov/pubs/elections/Results/Archives.html \
        > tests/fixtures/sos-archives-2026-05.html
"""

from __future__ import annotations

from scripts.discover import (
    _classify_boco_url, _classify_sos_url,
    discover_boulder_county, discover_secretary_of_state,
    merge_with_registry,
)
from scripts.sources import ALL_SOURCES


class TestClassifyBocoUrl:
    def test_2025_xlsx(self):
        url = "https://assets.bouldercounty.gov/wp-content/uploads/2025/11/2025C-Boulder-County-Official-Statement-of-Votes.xlsx"
        assert _classify_boco_url(url) == (2025, "coordinated")

    def test_2024_amended(self):
        url = "https://assets.bouldercounty.gov/wp-content/uploads/2024/12/2024G-Boulder-County-Amended-Statement-of-Votes.xlsx"
        assert _classify_boco_url(url) == (2024, "general")

    def test_2020_general(self):
        url = "https://assets.bouldercounty.gov/wp-content/uploads/2020/11/2020-Boulder-County-General-Election-Official-Statement-of-Votes.xlsx"
        assert _classify_boco_url(url) == (2020, "general")

    def test_rejects_summary_of_votes(self):
        url = "https://assets.bouldercounty.gov/wp-content/uploads/2025/11/2025C-Boulder-County-Official-Summary-of-Votes.xlsx"
        assert _classify_boco_url(url) is None

    def test_rejects_sample_ballot(self):
        url = "https://assets.bouldercounty.gov/wp-content/uploads/2025/09/Boulder-County-2025-Coordinated-Sample-Ballot.pdf"
        assert _classify_boco_url(url) is None

    def test_rejects_tabor(self):
        url = "https://assets.bouldercounty.gov/wp-content/uploads/2025/10/2025-Boulder-County-TABOR-Notice.pdf"
        assert _classify_boco_url(url) is None


class TestClassifySosUrl:
    def test_2020_general_precinct(self):
        url = "https://www.coloradosos.gov/pubs/elections/Results/2020/2020GEPrecinctLevelResultsPosted.xlsx"
        assert _classify_sos_url(url) == (2020, "general")

    def test_2024_turnout(self):
        url = "https://www.coloradosos.gov/pubs/elections/Results/2024/2024GeneralPrecinctVoterTurnout.xlsx"
        assert _classify_sos_url(url) == (2024, "general")

    def test_rejects_abstract_pdf(self):
        url = "https://www.coloradosos.gov/pubs/elections/Results/2024/2024BiennialAbstract.pdf"
        assert _classify_sos_url(url) is None


def test_discover_boulder_finds_recent(boco_results_html):
    # The Boulder /elections/results/ landing page rotates content; at the
    # time the fixture was captured (2026-05) it listed the 2025 coordinated
    # SoV. Discovery only needs to surface *something* — the merge step
    # filters against the static registry separately.
    found = discover_boulder_county(html=boco_results_html)
    assert found, "expected at least one discovered SoV"
    assert any(s.year == 2025 and s.election_type == "coordinated" for s in found)


def test_discover_boulder_prefers_xlsx_over_pdf(boco_results_html):
    found = discover_boulder_county(html=boco_results_html, years=[2025])
    assert len(found) == 1
    assert found[0].url.endswith(".xlsx"), found[0].url


def test_discover_sos_finds_recent(sos_archives_html):
    # SOS archive page lists items year by year; the fixture has 2024.
    found = discover_secretary_of_state(html=sos_archives_html)
    years = {s.year for s in found}
    assert 2024 in years


def test_merge_with_registry_filters_existing(boco_results_html, sos_archives_html):
    found = (
        discover_boulder_county(html=boco_results_html)
        + discover_secretary_of_state(html=sos_archives_html)
    )
    new = merge_with_registry(found, only_new=True)
    existing_keys = {(s.year, s.data_source) for s in ALL_SOURCES}
    for s in new:
        assert (s.year, s.data_source) not in existing_keys
