"""
Download raw SoV/precinct files into data/original/{data-source}/.

The files under data/original/ are immutable (AGENTS §2.5), so fetching is
conservative (#21):

- a file that exists and matches its manifest sha256 is skipped;
- a file that exists with **no** manifest entry (added by hand, or committed
  before the manifest existed) is recorded — sha256, size, and the
  retrieved_at already published for it — and skipped, never re-downloaded;
- a file whose sha256 no longer matches the manifest is reported as a FAIL
  and left alone; only ``--force`` re-downloads (and re-records) it.

``--verify`` checks every manifest entry against the file on disk without
touching the network; ``--backfill-manifest`` records every registry file on
disk that has no entry.

HTTP layer (caching, retries, User-Agent) is in scripts/http.py.
Path + config constants are in scripts/config.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import http
from .config import (
    BOULDER_COUNTY,
    MANIFEST_PATH,
    REPO_ROOT,
    SECRETARY_OF_STATE,
    SOURCES,
    Source,
    original_path,
)
from .logging_setup import get_logger

log = get_logger(__name__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"schema_version": 1, "files": {}}


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def local_path(s: Source) -> Path:
    return original_path(s.data_source, s.local_filename)


def _manifest_key(s: Source) -> str:
    return f"{s.data_source}/{s.local_filename}"


def _published_retrieved_at(s: Source) -> str | None:
    """retrieved_at already published for this file in provenance.csv, if any."""
    import pandas as pd

    from .config import PROVENANCE_CSV
    if not PROVENANCE_CSV.exists():
        return None
    prov = pd.read_csv(PROVENANCE_CSV, dtype=str, keep_default_na=False)
    hit = prov[(prov["data_source"] == s.data_source) & (prov["source_file"] == s.local_filename)]
    vals = [v for v in hit["retrieved_at"] if v]
    return vals[0] if vals else None


def _record(s: Source, dest: Path, retrieved_at: str, **extra: object) -> dict:
    return {
        "year": s.year,
        "election_type": s.election_type,
        "data_source": s.data_source,
        "url": s.url,
        "filename": s.local_filename,
        "sha256": _sha256(dest),
        "bytes": dest.stat().st_size,
        "retrieved_at": retrieved_at,
        **extra,
    }


def record_existing(s: Source, manifest: dict) -> dict:
    """Manifest record for a file already on disk with no entry. Its
    acquisition time is unknown, so use the value already published for it
    (provenance.csv), else the file's mtime — flagged as such."""
    dest = local_path(s)
    published = _published_retrieved_at(s)
    if published:
        rec = _record(s, dest, published)
    else:
        mtime = datetime.fromtimestamp(dest.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
        rec = _record(s, dest, mtime, retrieved_at_source="file_mtime")
    manifest["files"][_manifest_key(s)] = rec
    return rec


def backfill_manifest(sources: list[Source]) -> int:
    """Record every source file on disk that has no manifest entry. Returns
    the number of entries added."""
    manifest = _load_manifest()
    added = 0
    for s in sources:
        if local_path(s).exists() and _manifest_key(s) not in manifest["files"]:
            record_existing(s, manifest)
            added += 1
    if added:
        manifest["files"] = dict(sorted(manifest["files"].items()))
        _save_manifest(manifest)
    return added


def verify_manifest() -> list[str]:
    """Problems found comparing the manifest with data/original/ (no network):
    files missing on disk, and sha256 or size mismatches."""
    problems = []
    for s in SOURCES:
        rec = _load_manifest()["files"].get(_manifest_key(s))
        dest = local_path(s)
        if rec is None:
            if dest.exists():
                problems.append(f"{_manifest_key(s)}: on disk but not in the manifest")
            continue
        if not dest.exists():
            problems.append(f"{_manifest_key(s)}: in the manifest but missing on disk")
        elif _sha256(dest) != rec.get("sha256"):
            problems.append(f"{_manifest_key(s)}: sha256 differs from the manifest")
    return problems


def fetch_one(s: Source, *, force: bool = False, dry_run: bool = False) -> tuple[bool, str]:
    """Download a single source. Returns (changed, message).

    Cache + retries are handled by `http.get_bytes`. We pass `expire_after=0`
    via the requests-cache control header so this call ALWAYS hits the upstream
    (no cached stale binary), but tenacity still retries transient errors.
    """
    dest = local_path(s)
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    key = _manifest_key(s)
    record = manifest["files"].get(key)

    if not force and dest.exists():
        if record is None:
            if dry_run:
                return False, f"would-record  {key}  (on disk, no manifest entry)"
            record_existing(s, manifest)
            _save_manifest(manifest)
            return False, f"skip  {key}  (on disk; recorded in manifest)"
        if _sha256(dest) == record.get("sha256"):
            log.debug("fetch.skip", key=key, reason="sha256 matches manifest")
            return False, f"skip  {key}  (sha256 matches manifest)"
        return False, (f"FAIL  {key}  sha256 differs from the manifest; not overwriting "
                       "an original — inspect it, then re-run with --force to re-download")

    if dry_run:
        return False, f"would-fetch  {key}  <- {s.url}"

    try:
        # Force a fresh download for binary artifacts — caching would mask
        # upstream amendments.
        body = http.get_bytes(s.url, headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return False, f"FAIL  {key}  {type(e).__name__}: {e}  {s.url}"

    dest.write_bytes(body)
    manifest["files"][key] = _record(s, dest, datetime.now(UTC).isoformat(timespec="seconds"))
    manifest["files"] = dict(sorted(manifest["files"].items()))
    _save_manifest(manifest)
    log.debug("fetch.ok", key=key, bytes=dest.stat().st_size)
    return True, f"OK    {key}  ({dest.stat().st_size:,} bytes)"


def fetch_many(sources: list[Source], *, force: bool = False, dry_run: bool = False) -> int:
    errors = 0
    for s in sources:
        changed, msg = fetch_one(s, force=force, dry_run=dry_run)
        print(msg)
        if msg.startswith("FAIL"):
            errors += 1
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, help="Only this year")
    ap.add_argument("--since", type=int, help="This year and later")
    ap.add_argument("--source",
                    choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if the file is on disk (re-records the manifest)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="Check every manifest entry against data/original/ (no network)")
    ap.add_argument("--backfill-manifest", action="store_true",
                    help="Record every registry file on disk that has no manifest entry")
    ap.add_argument("--discover", action="store_true",
                    help="Also scrape upstream landing pages for sources not in "
                         "the static registry (e.g. years more recent than the "
                         "last hand-recorded entry)")
    args = ap.parse_args(argv)

    if args.verify:
        problems = verify_manifest()
        for p in problems:
            print(f"FAIL  {p}", file=sys.stderr)
        print(f"verified {MANIFEST_PATH.relative_to(REPO_ROOT)}: "
              f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if args.backfill_manifest:
        n = backfill_manifest(list(SOURCES))
        print(f"recorded {n} file(s) in {MANIFEST_PATH.name}")
        return 0

    if args.source == "boulder_county":
        pool = list(BOULDER_COUNTY)
    elif args.source == "secretary_of_state":
        pool = list(SECRETARY_OF_STATE)
    else:
        pool = list(SOURCES)

    if args.discover:
        try:
            from .discover import discover, merge_with_registry
            discovered = discover()
            new = merge_with_registry(discovered, only_new=True)
            if args.source != "all":
                new = [s for s in new if s.data_source == args.source]
            for s in new:
                print(f"discover  +{s.year}-{s.election_type}-{s.data_source}  {s.url}",
                      file=sys.stderr)
            pool.extend(new)
        except Exception as e:
            print(f"WARN discovery failed: {e}", file=sys.stderr)

    if args.year:
        pool = [s for s in pool if s.year == args.year]
    if args.since:
        pool = [s for s in pool if s.year >= args.since]

    if not pool:
        print("No sources match filters.", file=sys.stderr)
        return 2

    errors = fetch_many(pool, force=args.force, dry_run=args.dry_run)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
