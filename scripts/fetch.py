"""
Download raw SoV/precinct files into original-data/{data-source}/.

Idempotent: skips files that exist and match the recorded SHA-256
in original-data/manifest.json. Use --force to refetch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from .sources import ALL_SOURCES, BOULDER_COUNTY, SECRETARY_OF_STATE, Source

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DATA = REPO_ROOT / "original-data"
MANIFEST_PATH = ORIGINAL_DATA / "manifest.json"

USER_AGENT = (
    "Election-Results-Pipeline/0.1 (+https://github.com/brianckeegan/Election-Results) "
    "research/civic-data"
)


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


def _data_dir(s: Source) -> Path:
    return ORIGINAL_DATA / s.data_source.replace("_", "-")


def local_path(s: Source) -> Path:
    return _data_dir(s) / s.local_filename


def fetch_one(s: Source, *, force: bool = False, dry_run: bool = False) -> tuple[bool, str]:
    """Download a single source. Returns (changed, message)."""
    dest = local_path(s)
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    key = f"{s.data_source}/{s.local_filename}"
    record = manifest["files"].get(key)

    if not force and dest.exists() and record:
        digest = _sha256(dest)
        if digest == record.get("sha256"):
            return False, f"skip  {key}  (sha256 matches manifest)"

    if dry_run:
        return False, f"would-fetch  {key}  <- {s.url}"

    resp = requests.get(s.url, headers={"User-Agent": USER_AGENT}, timeout=60)
    if resp.status_code != 200:
        return False, f"FAIL  {key}  HTTP {resp.status_code}  {s.url}"

    dest.write_bytes(resp.content)
    digest = _sha256(dest)
    manifest["files"][key] = {
        "year": s.year,
        "election_type": s.election_type,
        "data_source": s.data_source,
        "url": s.url,
        "filename": s.local_filename,
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save_manifest(manifest)
    return True, f"OK    {key}  ({dest.stat().st_size:,} bytes)"


def fetch_many(sources: list[Source], *, force: bool = False, dry_run: bool = False) -> int:
    errors = 0
    for s in sources:
        changed, msg = fetch_one(s, force=force, dry_run=dry_run)
        print(msg)
        if msg.startswith("FAIL"):
            errors += 1
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, help="Only this year")
    ap.add_argument("--since", type=int, help="This year and later")
    ap.add_argument("--source",
                    choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    ap.add_argument("--force", action="store_true", help="Refetch even if manifest matches")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.source == "boulder_county":
        pool = BOULDER_COUNTY
    elif args.source == "secretary_of_state":
        pool = SECRETARY_OF_STATE
    else:
        pool = ALL_SOURCES

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
