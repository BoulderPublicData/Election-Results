"""Tests for scripts/clean.py helpers."""

from __future__ import annotations

from scripts import clean


def test_retrieved_at_prefers_manifest_then_recorded_provenance(tmp_path, monkeypatch):
    """Hand-added files have no manifest entry; their retrieved_at must come
    from the published provenance.csv, not the file's mtime (which changes on
    every fresh clone or `git mv`)."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"files": {"boulder_county/a.xlsx": {"retrieved_at": "2020-01-01T00:00:00+00:00"}}}')
    prov = tmp_path / "provenance.csv"
    prov.write_text("data_source,source_file,retrieved_at\n"
                    "boulder_county,a.xlsx,2021-01-01T00:00:00+00:00\n"
                    "boulder_county,b.xlsx,2022-02-02T00:00:00+00:00\n")
    monkeypatch.setattr(clean, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(clean, "PROVENANCE_CSV", prov)
    clean._recorded_retrieved_at.cache_clear()
    try:
        assert clean._retrieved_at_for("a.xlsx", "boulder_county") == "2020-01-01T00:00:00+00:00"
        assert clean._retrieved_at_for("b.xlsx", "boulder_county") == "2022-02-02T00:00:00+00:00"
        assert clean._retrieved_at_for("missing.xlsx", "boulder_county") == "unknown"
    finally:
        clean._recorded_retrieved_at.cache_clear()
