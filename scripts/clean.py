"""
Cleaning orchestrator. Reads one raw file and routes it to the appropriate parser.

Output: a DataFrame matching scripts.schema.COLUMNS, written to
data/processed/{data_source}-{year}-{election_type}.csv

Each row has provenance (source_url, retrieved_at, sha256 via the manifest) so
downstream analyses always know where a number came from.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .parsers import boco_panel, boco_pdf, boco_tidy, sos
from .schema import SourceMeta, validate
from .sources import (
    ALL_SOURCES, BOULDER_COUNTY, ELECTION_DATES,
    SECRETARY_OF_STATE, Source,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DATA = REPO_ROOT / "data" / "original"
PROCESSED_DATA = REPO_ROOT / "data" / "processed"
MANIFEST_PATH = ORIGINAL_DATA / "manifest.json"

# Year-by-year routing for Boulder County.
# Panel: 2008, 2010, 2011, 2012 — multi-block per-sheet format.
# Tidy:  2013-2024 — long-form (with quirks handled by boco_tidy).
# PDF:   2005, 2007, 2009 — best-effort pdfplumber extraction (no JVM required).
BOCO_PANEL_YEARS = {2008, 2010, 2011, 2012}
BOCO_PDF_YEARS = {2005, 2007, 2009}


def _retrieved_at_for(source_file: str, data_source: str) -> str:
    if MANIFEST_PATH.exists():
        m = json.loads(MANIFEST_PATH.read_text())
        rec = m.get("files", {}).get(f"{data_source}/{source_file}")
        if rec and rec.get("retrieved_at"):
            return rec["retrieved_at"]
    # Manifest absent or missing this entry — fall back to file mtime as a
    # conservative proxy. Better than NULL; flagged in the audit.
    p = ORIGINAL_DATA / data_source.replace("_", "-") / source_file
    if p.exists():
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    return "unknown"


def _meta_for(s: Source) -> SourceMeta:
    quality = "pdf_text_layer" if s.year in BOCO_PDF_YEARS else "machine_readable"
    return SourceMeta(
        election_year=s.year,
        election_date=ELECTION_DATES.get(s.year, f"{s.year}-11-XX"),
        election_type=s.election_type,
        data_source=s.data_source,
        jurisdiction_level="county" if s.data_source == "boulder_county" else "state",
        jurisdiction_name="Boulder County",
        source_file=s.local_filename,
        source_url=s.url,
        retrieved_at=_retrieved_at_for(s.local_filename, s.data_source),
        extraction_quality=quality,
    )


def clean_source(s: Source) -> pd.DataFrame:
    path = ORIGINAL_DATA / s.data_source.replace("_", "-") / s.local_filename
    if not path.exists():
        raise FileNotFoundError(f"raw file missing: {path}")
    meta = _meta_for(s)

    if s.data_source == "boulder_county":
        if s.year in BOCO_PDF_YEARS:
            return boco_pdf.parse(path, meta)
        if s.year in BOCO_PANEL_YEARS:
            return boco_panel.parse(path, meta)
        return boco_tidy.parse(path, meta)
    if s.data_source == "secretary_of_state":
        return sos.parse(path, meta)
    raise ValueError(f"unknown data_source: {s.data_source}")


def _output_path(s: Source) -> Path:
    ds = s.data_source.replace("_", "-")
    return PROCESSED_DATA / f"{s.year}-{s.election_type}-{ds}.csv"


def write_csv(df: pd.DataFrame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, help="Only this year")
    ap.add_argument("--since", type=int, help="This year and later")
    ap.add_argument("--source",
                    choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    ap.add_argument("--no-pdf", action="store_true",
                    help="Skip PDF-sourced years (2005/2007/2009). PDF parse can take minutes.")
    ap.add_argument("--validate-only", action="store_true",
                    help="Parse + validate but don't write CSVs.")
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
    if args.no_pdf:
        pool = [s for s in pool if s.year not in BOCO_PDF_YEARS]

    if not pool:
        print("No sources match filters.", file=sys.stderr)
        return 2

    errors = 0
    for s in pool:
        label = f"{s.year}-{s.election_type}-{s.data_source}"
        try:
            df = clean_source(s)
            problems = validate(df, source_label=label)
            if problems:
                print(f"  WARN {label}: {problems}", file=sys.stderr)
            if not args.validate_only:
                dest = _output_path(s)
                write_csv(df, dest)
                print(f"OK   {label}  rows={len(df):>6}  -> {dest.relative_to(REPO_ROOT)}")
            else:
                print(f"OK   {label}  rows={len(df):>6}  (validate-only)")
        except Exception as e:
            print(f"FAIL {label}: {type(e).__name__}: {e}", file=sys.stderr)
            errors += 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
