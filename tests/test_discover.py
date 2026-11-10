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
    _classify_boco_url,
    _classify_sos_url,
    discover_boulder_county,
    discover_secretary_of_state,
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
    found = discover_boulder_county(html=boco_results_html) + discover_secretary_of_state(
        html=sos_archives_html
    )
    new = merge_with_registry(found, only_new=True)
    existing_keys = {(s.year, s.election_type, s.data_source) for s in ALL_SOURCES}
    for s in new:
        assert (s.year, s.election_type, s.data_source) not in existing_keys


class TestPrimariesAndRecounts:
    """#29."""

    def test_boulder_primary_by_prefix(self):
        url = (
            "https://assets.bouldercounty.gov/wp-content/uploads/2026/07/"
            "2026P-Boulder-County-Primary-Official-Statement-of-Votes.xlsx"
        )
        assert _classify_boco_url(url) == (2026, "primary")

    def test_sos_primary(self):
        url = (
            "https://www.coloradosos.gov/pubs/elections/Results/2026/"
            "2026PrimaryPrecinctLevelResults.xlsx"
        )
        assert _classify_sos_url(url) == (2026, "primary")

    def test_recount_sov_is_not_rejected(self):
        url = (
            "https://assets.bouldercounty.gov/wp-content/uploads/2023/12/"
            "2023C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx"
        )
        assert _classify_boco_url(url) == (2023, "coordinated")

    def test_recount_is_a_supplement_of_the_full_sov(self):
        """#42: the recount SoV re-reports only the recounted contest, so the
        full SoV stays the source and the recount is merged over it."""
        base = "https://assets.bouldercounty.gov/wp-content/uploads/2023/"
        html = (
            f"<a href='{base}12/2023C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx'>b</a>"
            f"<a href='{base}11/2023C-Boulder-County-Official-Statement-of-Votes.xlsx'>a</a>"
            f"<a href='{base}11/2023C-Boulder-County-Official-Statement-of-Votes.pdf'>c</a>"
        )
        found = discover_boulder_county(html=html)
        assert len(found) == 1
        s = found[0]
        assert s.url == f"{base}11/2023C-Boulder-County-Official-Statement-of-Votes.xlsx"
        assert s.local_filename == "2023-coordinated-sov.xlsx"
        assert [(x.kind, x.local_filename) for x in s.supplements] == [
            ("recount", "2023-coordinated-sov-recount.xlsx")
        ]

    def test_amended_is_a_supplement_and_presidential_primary_is_its_own_election(self):
        """#43, and the 2024 by-year page's three elections."""
        base = "https://assets.bouldercounty.gov/wp-content/uploads/2024/"
        html = "".join(
            f"<a href='{base}{p}'>x</a>"
            for p in (
                "03/2024PP-Boulder-County-Official-Statement-of-Votes.xlsx",
                "07/2024P-boulder-county-official-statement-of-votes.xlsx",
                "11/2024G-Boulder-County-Official-Statement-of-Votes.xlsx",
                "12/2024G-Boulder-County-Amended-Statement-of-Votes.xlsx",
                "12/2024G-Boulder-County-Amended-Summary-of-Votes.pdf",
            )
        )
        found = {s.election_type: s for s in discover_boulder_county(html=html)}
        assert set(found) == {"general", "primary", "presidential_primary"}
        g = found["general"]
        assert g.url.endswith("11/2024G-Boulder-County-Official-Statement-of-Votes.xlsx")
        assert [(x.kind, x.local_filename) for x in g.supplements] == [
            ("amended", "2024-general-sov-amended.xlsx")
        ]
        pp = found["presidential_primary"]
        assert pp.local_filename == "2024-presidential-primary-sov.xlsx"
        assert not found["primary"].supplements

    def test_partial_file_alone_is_used_whole(self):
        url = (
            "https://assets.bouldercounty.gov/wp-content/uploads/2031/12/"
            "2031C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx"
        )
        (s,) = discover_boulder_county(html=f"<a href='{url}'>r</a>")
        assert s.url == url and s.supplements == ()

    def test_sos_presidential_primary(self):
        url = (
            "https://www.coloradosos.gov/pubs/elections/Results/2024/"
            "2024PresidentialPrimaryPrecinctLevelResults.xlsx"
        )
        assert _classify_sos_url(url) == (2024, "presidential_primary")

    def test_primary_is_new_even_when_the_general_is_registered(self):
        from scripts.sources import Source

        primary = Source(
            2024, "primary", "boulder_county", "https://x/2024P.xlsx", "2024-primary-sov.xlsx"
        )
        assert merge_with_registry([primary], only_new=True) == [primary]

    def test_primary_election_date(self):
        from scripts.sources import election_date_for

        assert election_date_for(2026, "primary") == "2026-06-30"
        assert election_date_for(2026, "general") == "2026-11-03"
