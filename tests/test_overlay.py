"""Supplements (recount / amended SoVs) merged over a source by contest (#42, #43)."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts import clean, reconcile
from scripts.overlay import overlay_by_contest, overlay_totals
from scripts.sources import BOULDER_COUNTY, Source, Supplement, find


def _frame(rows):
    return pd.DataFrame(rows, columns=["precinct_id", "contest", "candidate_or_option", "votes"])


BASE = _frame(
    [
        ("1", "Mayor", "Ann", 10),
        ("1", "Council", "Cy", 5),
        ("1", "Council", "Di", 6),
        ("2", "Mayor", "Ann", 20),
        ("2", "Council", "Cy", 7),
        ("2", "Council", "Di", 8),
    ]
)


def test_supplement_replaces_its_contests_whole_and_keeps_row_order():
    sup = _frame([("2", "Council", "Di", 9), ("1", "Council", "Cy", 4), ("1", "Council", "Di", 6)])
    merged, replaced = overlay_by_contest(BASE, sup)
    assert replaced == ["Council"]
    # Precinct 2 / Cy is not in the supplement: the recount's contest wins
    # whole, so the base row is gone rather than kept alongside.
    assert merged.values.tolist() == [
        ["1", "Mayor", "Ann", 10],
        ["1", "Council", "Cy", 4],
        ["1", "Council", "Di", 6],
        ["2", "Mayor", "Ann", 20],
        ["2", "Council", "Di", 9],
    ]


def test_other_contests_are_untouched():
    sup = _frame([("1", "Mayor", "Ann", 11), ("2", "Mayor", "Ann", 19)])
    merged, _ = overlay_by_contest(BASE, sup)
    assert merged[merged["contest"] == "Council"].equals(BASE[BASE["contest"] == "Council"])
    assert merged.loc[merged["contest"] == "Mayor", "votes"].tolist() == [11, 19]


def test_rows_with_no_base_counterpart_go_last():
    sup = _frame([("3", "Mayor", "Ann", 1), ("1", "Mayor", "Ann", 10)])
    merged, _ = overlay_by_contest(BASE, sup)
    assert merged.iloc[-1].tolist() == ["3", "Mayor", "Ann", 1]
    assert len(merged) == len(BASE)  # 2 Mayor rows out, 2 in


def test_unknown_contest_is_an_error_not_a_new_contest():
    with pytest.raises(ValueError, match="not in the base file"):
        overlay_by_contest(BASE, _frame([("1", "Mayor (Recount)", "Ann", 10)]))
    with pytest.raises(ValueError, match="not in the base file"):
        overlay_totals(BASE, _frame([("1", "Treasurer", "Ann", 10)]))


def test_empty_supplement_is_an_error():
    with pytest.raises(ValueError, match="no rows"):
        overlay_by_contest(BASE, BASE.iloc[0:0])


def test_overlay_totals_is_the_same_rule():
    sup = _frame([("1", "Council", "Cy", 4)])
    merged, _ = overlay_by_contest(BASE, sup)
    totals = overlay_totals(BASE, sup)
    by = ["contest", "candidate_or_option"]
    assert (
        merged.groupby(by)["votes"].sum().to_dict() == totals.groupby(by)["votes"].sum().to_dict()
    )


# ---------------------------------------------------------------------------
# Through clean_source and reconcile, with two tidy workbooks on disk.
# ---------------------------------------------------------------------------


def _tidy(path, rows):
    pd.DataFrame(
        rows,
        columns=[
            "Precinct \nCode",
            "Precinct \nNumber",
            "Contest \nTitle",
            "Choice \nName",
            "Active \nVoters",
            "Total \nBallots",
            "Total \nVotes",
        ],
    ).to_excel(path, index=False)


@pytest.fixture
def tidy_source(tmp_path, monkeypatch):
    _tidy(
        tmp_path / "base.xlsx",
        [
            ("100", "2181207100", "Mayor", "Ann", 900, 500, 300),
            ("100", "2181207100", "Mayor", "Bob", 900, 500, 190),
            ("100", "2181207100", "Town Trustee", "Cy", 900, 500, 200),
            ("101", "2181207101", "Mayor", "Ann", 800, 400, 250),
            ("101", "2181207101", "Mayor", "Bob", 800, 400, 140),
            ("101", "2181207101", "Town Trustee", "Cy", 800, 400, 150),
        ],
    )
    _tidy(
        tmp_path / "base-recount.xlsx",
        [
            ("100", "2181207100", "Town Trustee", "Cy", 900, 500, 199),
            ("101", "2181207101", "Town Trustee", "Cy", 800, 400, 151),
        ],
    )
    monkeypatch.setattr(clean, "original_path", lambda ds, f: tmp_path / f)
    monkeypatch.setattr(reconcile, "original_path", lambda ds, f: tmp_path / f)
    return Source(
        2030,
        "general",
        "boulder_county",
        "https://example.invalid/base.xlsx",
        "base.xlsx",
        supplements=(Supplement("recount", "https://example.invalid/r.xlsx", "base-recount.xlsx"),),
    )


def test_clean_source_merges_the_supplement(tidy_source):
    df = clean.clean_source(tidy_source)
    got = df.groupby(["contest", "candidate_or_option"])["votes"].sum().to_dict()
    assert got == {("Mayor", "Ann"): 550, ("Mayor", "Bob"): 330, ("Town Trustee", "Cy"): 350}
    assert df["precinct_id"].tolist()[:3] == ["2181207100"] * 3  # base order kept
    note = df["extraction_notes"].iloc[0]
    assert "1 contest(s) taken from the recount file base-recount.xlsx" in note
    assert df.attrs["extraction_notes"] == note
    assert clean.parsed_files(tidy_source) == [
        ("boulder_county", "base.xlsx"),
        ("boulder_county", "base-recount.xlsx"),
    ]


def test_reconcile_original_side_applies_the_supplement(tidy_source):
    orig = reconcile._read_original(tidy_source)
    got = orig.groupby(["contest", "candidate_or_option"])["votes"].sum().to_dict()
    assert got[("Town Trustee", "Cy")] == 350
    assert got[("Mayor", "Ann")] == 550


def test_registry_supplements_2023_recount_and_2024_amended():
    s23, s24 = find(2023, "boulder_county"), find(2024, "boulder_county")
    assert s23.url.endswith("/2023/11/2023C-Boulder-County-Official-Statement-of-Votes.xlsx")
    assert [(x.kind, x.local_filename) for x in s23.supplements] == [
        ("recount", "2023-coordinated-sov-recount.xlsx")
    ]
    assert s24.url.endswith("/2024/11/2024G-Boulder-County-Official-Statement-of-Votes.xlsx")
    assert [(x.kind, x.local_filename) for x in s24.supplements] == [
        ("amended", "2024-general-sov-amended.xlsx")
    ]
    # Each raw file appears once across the registry.
    files = [r.local_filename for s in BOULDER_COUNTY for r in s.file_records()]
    assert len(files) == len(set(files))
