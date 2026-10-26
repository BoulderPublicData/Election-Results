"""
Cleaning orchestrator. Reads one raw file and routes it to the appropriate parser.

Output: a DataFrame coerced to scripts.schema.COLUMNS / DTYPES, written (as the
slim 15-column view) to
data/processed/statements-of-votes/{year}-{election_type}-{data-source}.csv.

The five provenance fields (source_url, retrieved_at, ...) travel on the
in-memory frame and are written once per source file to
data/processed/statements-of-votes/provenance.csv by pipeline.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import pandas as pd

from .config import (
    BOULDER_COUNTY,
    MANIFEST_PATH,
    ORIGINAL,
    PROVENANCE_CSV,
    REPO_ROOT,
    SECRETARY_OF_STATE,
    SOURCES,
    STATEMENTS_OF_VOTES,
    Source,
    original_path,
    sov_csv_path,
)
from .logging_setup import get_logger
from .parsers import boco_panel, boco_pdf, boco_tidy, sos
from .schema import SourceMeta, coerce, validate
from .sources import election_date_for

log = get_logger(__name__)

# Backwards-compatible aliases — keep these so any external code that imported
# from scripts.clean keeps working through a deprecation cycle.
ORIGINAL_DATA = ORIGINAL
PROCESSED_DATA = STATEMENTS_OF_VOTES
ALL_SOURCES = SOURCES

# Year-by-year routing for Boulder County.
# Panel: 2008, 2010, 2011, 2012 — multi-block per-sheet format.
# Tidy:  2013-2024 — long-form (with quirks handled by boco_tidy).
# PDF:   2005, 2007, 2009 — best-effort pdfplumber extraction (no JVM required).
BOCO_PANEL_YEARS = {2008, 2010, 2011, 2012}
BOCO_PDF_YEARS = {2005, 2007, 2009}


@cache
def _recorded_retrieved_at() -> dict[tuple[str, str], str]:
    """retrieved_at values already published in provenance.csv, keyed on
    (data_source, source_file)."""
    if not PROVENANCE_CSV.exists():
        return {}
    prov = pd.read_csv(PROVENANCE_CSV, dtype=str, keep_default_na=False)
    return {(r.data_source, r.source_file): r.retrieved_at
            for r in prov.itertuples(index=False) if r.retrieved_at}


def _retrieved_at_for(source_file: str, data_source: str) -> str:
    """When was this raw file downloaded? In order of preference:

    1. data/original/manifest.json — written by fetch.py at download time.
    2. The value already recorded in statements-of-votes/provenance.csv. Files
       added by hand have no manifest entry; reusing the published value keeps
       re-runs reproducible instead of re-dating every file whenever a fresh
       clone or a `git mv` changes its mtime.
    3. The file's mtime — a conservative proxy for brand-new hand-added files.
    """
    if MANIFEST_PATH.exists():
        m = json.loads(MANIFEST_PATH.read_text())
        rec = m.get("files", {}).get(f"{data_source}/{source_file}")
        if rec and rec.get("retrieved_at"):
            return rec["retrieved_at"]
    recorded = _recorded_retrieved_at().get((data_source, source_file))
    if recorded:
        return recorded
    p = original_path(data_source, source_file)
    if p.exists():
        return datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
    return "unknown"


def _meta_for(s: Source) -> SourceMeta:
    quality = "pdf_text_layer" if s.year in BOCO_PDF_YEARS else "machine_readable"
    return SourceMeta(
        election_year=s.year,
        election_date=election_date_for(s.year, s.election_type),
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
    path = original_path(s.data_source, s.local_filename)
    if not path.exists():
        raise FileNotFoundError(f"raw file missing: {path}")
    meta = _meta_for(s)

    if s.data_source == "boulder_county":
        if s.year in BOCO_PDF_YEARS:
            df = boco_pdf.parse(path, meta)
        elif s.year in BOCO_PANEL_YEARS:
            df = boco_panel.parse(path, meta)
        else:
            df = boco_tidy.parse(path, meta)
    elif s.data_source == "secretary_of_state":
        df = sos.parse(path, meta)
    else:
        raise ValueError(f"unknown data_source: {s.data_source}")
    # One choke point for the schema dtypes, so validate() checks real
    # problems rather than flagging int64-vs-Int16 on every parser, and
    # integer columns are written as integers ("1291", not "1291.0").
    return coerce(df)


def _output_path(s: Source) -> Path:
    return sov_csv_path(s.year, s.election_type, s.data_source)


def write_csv(df: pd.DataFrame, dest: Path) -> None:
    """Write the slim CSV view (provenance columns excluded).

    See scripts.schema.to_csv_frame — the 5 provenance columns are constant
    per source file and live in the sidecar `statements-of-votes/provenance.csv`
    instead, which the pipeline regenerates from the in-memory frames.
    """
    from .schema import to_csv_frame
    dest.parent.mkdir(parents=True, exist_ok=True)
    to_csv_frame(df).to_csv(dest, index=False)


def _election_arg(value: str) -> tuple[int, str]:
    from .sources import parse_election_key
    try:
        return parse_election_key(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, help="Only this year")
    ap.add_argument("-e", "--election", type=_election_arg, metavar="KEY",
                    help="Only this election, as an election key, e.g. 2024-general")
    ap.add_argument("--since", type=int, help="This year and later")
    ap.add_argument("--source",
                    choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    ap.add_argument("--no-pdf", action="store_true",
                    help="Skip PDF-sourced years (2005/2007/2009). PDF parse can take minutes.")
    ap.add_argument("--validate-only", action="store_true",
                    help="Parse + validate but don't write CSVs.")
    args = ap.parse_args(argv)

    if args.source == "boulder_county":
        pool = BOULDER_COUNTY
    elif args.source == "secretary_of_state":
        pool = SECRETARY_OF_STATE
    else:
        pool = ALL_SOURCES

    if args.year:
        pool = [s for s in pool if s.year == args.year]
    if args.election:
        pool = [s for s in pool if (s.year, s.election_type) == args.election]
    if args.since:
        pool = [s for s in pool if s.year >= args.since]
    if args.no_pdf:
        pool = [s for s in pool if s.year not in BOCO_PDF_YEARS]

    if not pool:
        print("No sources match filters.", file=sys.stderr)
        return 2

    from . import reject, shared_outputs
    from .schema import provenance_record

    errors = 0
    prov_rows: list[dict] = []
    parsed: list[tuple[str, str]] = []
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
                prov_rows.append(provenance_record(df, _meta_for(s)))
                parsed.append((s.data_source, s.local_filename))
                print(f"OK   {label}  rows={len(df):>6}  -> {dest.relative_to(REPO_ROOT)}")
            else:
                print(f"OK   {label}  rows={len(df):>6}  (validate-only)")
        except Exception as e:
            print(f"FAIL {label}: {type(e).__name__}: {e}", file=sys.stderr)
            errors += 1

    rejected = reject.drain()
    if not args.validate_only and parsed:
        # Keep the sidecars in step with the CSVs just written (#33); both are
        # upserts, so other files' rows are untouched. The combined CSV is
        # rebuilt by `pipeline` (or shared_outputs.rebuild_combined()).
        shared_outputs.upsert_provenance(prov_rows)
        rej = shared_outputs.upsert_rejects(rejected, parsed)
        print(f"updated {PROVENANCE_CSV.relative_to(REPO_ROOT)} ({len(prov_rows)} rows) and "
              f"data/audit/rejected.csv ({len(rej)} rows)")
    elif len(rejected):
        print(f"  {len(rejected)} row(s) would be rejected", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
