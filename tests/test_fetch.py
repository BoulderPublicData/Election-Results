"""#21: files already in data/original/ are recorded and kept, never
silently re-downloaded or overwritten."""

from __future__ import annotations

import json

import pytest

from scripts import fetch
from scripts.sources import Source

SRC = Source(2025, "coordinated", "boulder_county", "https://example.invalid/sov.xlsx",
             "2025-coordinated-sov.xlsx")


@pytest.fixture
def env(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    raw = tmp_path / SRC.local_filename
    monkeypatch.setattr(fetch, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(fetch, "local_path", lambda s: tmp_path / s.local_filename)
    monkeypatch.setattr(fetch, "_published_retrieved_at", lambda s: "2026-05-23T18:30:06+00:00")
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return b"downloaded"
    monkeypatch.setattr(fetch.http, "get_bytes", fake_get)
    return manifest, raw, calls


def test_existing_file_without_entry_is_recorded_not_downloaded(env):
    manifest, raw, calls = env
    raw.write_bytes(b"original")
    changed, msg = fetch.fetch_one(SRC)
    assert not changed and msg.startswith("skip") and calls == []
    rec = json.loads(manifest.read_text())["files"]["boulder_county/2025-coordinated-sov.xlsx"]
    assert rec["sha256"] == fetch._sha256(raw)
    assert rec["retrieved_at"] == "2026-05-23T18:30:06+00:00"
    assert raw.read_bytes() == b"original"


def test_matching_hash_is_skipped(env):
    manifest, raw, calls = env
    raw.write_bytes(b"original")
    fetch.fetch_one(SRC)
    changed, msg = fetch.fetch_one(SRC)
    assert msg.startswith("skip") and calls == []


def test_hash_mismatch_fails_and_keeps_the_file(env):
    manifest, raw, calls = env
    raw.write_bytes(b"original")
    fetch.fetch_one(SRC)
    raw.write_bytes(b"edited in place")
    changed, msg = fetch.fetch_one(SRC)
    assert msg.startswith("FAIL") and calls == []
    assert raw.read_bytes() == b"edited in place"


def test_force_redownloads_and_rerecords(env):
    manifest, raw, calls = env
    raw.write_bytes(b"original")
    changed, msg = fetch.fetch_one(SRC, force=True)
    assert changed and calls == [SRC.url] and raw.read_bytes() == b"downloaded"
    rec = json.loads(manifest.read_text())["files"]["boulder_county/2025-coordinated-sov.xlsx"]
    assert rec["sha256"] == fetch._sha256(raw)


def test_committed_manifest_covers_and_matches_every_original():
    """Every registry file on disk has an entry whose sha256 matches."""
    assert fetch.verify_manifest() == []
