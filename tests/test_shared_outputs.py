"""#18: a filtered run must leave the other sources' rows in every
whole-dataset output."""

from __future__ import annotations

import pandas as pd

from scripts import shared_outputs as so
from scripts.schema import CSV_COLUMNS


def _prov(year, etype, source, note):
    return {
        "election_year": year,
        "election_type": etype,
        "data_source": source,
        "source_file": f"{year}.xlsx",
        "source_url": "https://x",
        "retrieved_at": "t",
        "extraction_quality": "machine_readable",
        "extraction_notes": note,
    }


def test_upsert_provenance_keeps_other_sources(tmp_path):
    path = tmp_path / "provenance.csv"
    so.upsert_provenance(
        [
            _prov(2024, "general", "boulder_county", "old 2024"),
            _prov(2025, "coordinated", "boulder_county", "old 2025"),
            _prov(2020, "general", "secretary_of_state", "sos"),
        ],
        path,
    )
    out = so.upsert_provenance([_prov(2025, "coordinated", "boulder_county", "new 2025")], path)
    assert len(out) == 3
    notes = dict(zip(out["election_year"].astype(int), out["extraction_notes"], strict=True))
    assert notes == {2024: "old 2024", 2025: "new 2025", 2020: "sos"}
    # Registry order: Boulder (by year), then SOS.
    assert out["election_year"].astype(int).tolist() == [2024, 2025, 2020]


def test_upsert_rejects_replaces_only_the_files_parsed(tmp_path):
    path = tmp_path / "rejected.csv"
    old = pd.DataFrame(
        {
            "source_file": ["2008.xls", "2008.xls", "2025.xlsx"],
            "election_year": [2008, 2008, 2025],
            "data_source": ["boulder_county"] * 3,
            "row_index": ["1", "2", "3"],
            "reason": ["r"] * 3,
            "detail": [""] * 3,
            "raw_row": [""] * 3,
        }
    )
    old.to_csv(path, index=False)
    # Re-parsing 2025 with no rejects drops its old row; 2008's rows stay.
    out = so.upsert_rejects(pd.DataFrame(), [("boulder_county", "2025.xlsx")], path)
    assert out["source_file"].tolist() == ["2008.xls", "2008.xls"]


def _write_year(directory, name, years):
    df = pd.DataFrame({c: [None] * len(years) for c in CSV_COLUMNS})
    df["election_year"] = years
    df["votes"] = 1
    df.to_csv(directory / name, index=False)


def test_rebuild_combined_uses_every_file_on_disk(tmp_path):
    _write_year(tmp_path, "2024-general-boulder-county.csv", [2024, 2024])
    _write_year(tmp_path, "2025-coordinated-boulder-county.csv", [2025])
    _write_year(tmp_path, "2020-general-secretary-of-state.csv", [2020])
    out = tmp_path / "all-elections-tidy.csv"
    combined = so.rebuild_combined(tmp_path, out)
    assert len(combined) == 4
    assert pd.read_csv(out)["election_year"].tolist() == [2024, 2024, 2025, 2020]


def test_rebuild_audit_summary_keeps_every_fragment(tmp_path):
    (tmp_path / "2025-coordinated-boulder-county.md").write_text("### 2025")
    (tmp_path / "2004-general-secretary-of-state.md").write_text("### 2004 SOS")
    (tmp_path / "2005-coordinated-boulder-county.md").write_text("### 2005")
    out = tmp_path / "summary.md"
    assert so.rebuild_audit_summary(tmp_path, out) == 3
    assert out.read_text() == "### 2005\n### 2025\n### 2004 SOS"
