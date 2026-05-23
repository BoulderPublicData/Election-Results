"""
Regenerate the JSON lookup files under data/lookups/ from the Python
source-of-truth tables in scripts/parsers/common.py and scripts/sources.py.

Run this whenever PARTY_MAP, CHOICE_MAP, ELECTION_DATES, or the source registry
changes. The JSON files are checked in so non-Python consumers (R, Excel,
JavaScript) can read them directly.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .parsers.common import CHOICE_MAP, PARTY_MAP
from .schema import COLUMNS, CSV_COLUMNS, DTYPES, PROVENANCE_COLUMNS, SCHEMA_VERSION
from .sources import ALL_SOURCES, ELECTION_DATES

REPO_ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = REPO_ROOT / "data" / "lookups"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def export_party_codes() -> None:
    """Export the party-name → 3-letter-code mapping plus the inverse for lookup."""
    by_canonical: dict[str, list[str]] = {}
    for source, canonical in PARTY_MAP.items():
        by_canonical.setdefault(canonical, []).append(source)
    payload = {
        "$schema_version": SCHEMA_VERSION,
        "$description": (
            "Party-name normalization. `mapping` is source-string → canonical 3-letter code. "
            "`by_canonical` groups every known source-string variant under its canonical code "
            "so you can render party labels consistently. Unknown source strings pass through "
            "verbatim — they are never silently dropped."
        ),
        "$generated_by": "scripts/export_lookups.py from scripts/parsers/common.py:PARTY_MAP",
        "$generated_at": _now(),
        "mapping": dict(sorted(PARTY_MAP.items())),
        "by_canonical": {k: sorted(v) for k, v in sorted(by_canonical.items())},
    }
    (LOOKUPS / "party-codes.json").write_text(json.dumps(payload, indent=2) + "\n")


def export_choice_map() -> None:
    """Yes/No variant normalization."""
    by_canonical: dict[str, list[str]] = {}
    for source, canonical in CHOICE_MAP.items():
        by_canonical.setdefault(canonical, []).append(source)
    payload = {
        "$schema_version": SCHEMA_VERSION,
        "$description": (
            "Yes/No variant normalization. Published files use many spellings "
            "(`Yes/For`, `No/Against`, `Yes/Sí`, ...). `mapping` is source → canonical. "
            "All canonical values are either `Yes` or `No`."
        ),
        "$generated_by": "scripts/export_lookups.py from scripts/parsers/common.py:CHOICE_MAP",
        "$generated_at": _now(),
        "mapping": dict(sorted(CHOICE_MAP.items())),
        "by_canonical": {k: sorted(v) for k, v in sorted(by_canonical.items())},
    }
    (LOOKUPS / "choice-map.json").write_text(json.dumps(payload, indent=2) + "\n")


def export_election_dates() -> None:
    payload = {
        "$schema_version": SCHEMA_VERSION,
        "$description": (
            "Election day for each year in the registry. Format: ISO YYYY-MM-DD. "
            "Note that Boulder County typically certifies its Statement of Votes "
            "~3 weeks after election day; the `retrieved_at` field on processed "
            "rows captures when the pipeline downloaded the certified file."
        ),
        "$generated_by": "scripts/export_lookups.py from scripts/sources.py:ELECTION_DATES",
        "$generated_at": _now(),
        "election_dates": {str(y): d for y, d in sorted(ELECTION_DATES.items())},
    }
    (LOOKUPS / "election-dates.json").write_text(json.dumps(payload, indent=2) + "\n")


def export_sources() -> None:
    payload = {
        "$schema_version": SCHEMA_VERSION,
        "$description": (
            "Source URL registry. One entry per (year, data_source). "
            "`local_filename` is the path under data/original/{data_source-kebab}/."
        ),
        "$generated_by": "scripts/export_lookups.py from scripts/sources.py:ALL_SOURCES",
        "$generated_at": _now(),
        "sources": [
            {
                "year": s.year,
                "election_type": s.election_type,
                "data_source": s.data_source,
                "url": s.url,
                "local_filename": s.local_filename,
            }
            for s in sorted(ALL_SOURCES, key=lambda s: (s.year, s.data_source))
        ],
    }
    (LOOKUPS / "sources.json").write_text(json.dumps(payload, indent=2) + "\n")


def export_schema() -> None:
    """Machine-readable schema description for non-Python consumers."""
    payload = {
        "$schema_version": SCHEMA_VERSION,
        "$description": (
            "Harmonized schema for data/processed/. `columns` is the full "
            "in-memory schema (20 cols). `csv_columns` is the slim view written "
            "to per-year CSV files (15 cols). `provenance_columns` are the "
            "5 fields stored in data/processed/provenance.csv instead of "
            "duplicating them on every row."
        ),
        "$generated_by": "scripts/export_lookups.py from scripts/schema.py",
        "$generated_at": _now(),
        "columns": COLUMNS,
        "csv_columns": CSV_COLUMNS,
        "provenance_columns": PROVENANCE_COLUMNS,
        "dtypes": DTYPES,
        "contest_types": [
            {"value": "candidate", "description": "Partisan or non-partisan candidate race."},
            {"value": "measure", "description": "Yes/No ballot measure, referendum, or amendment."},
            {"value": "retention", "description": "Judicial retention (Yes/No to retain a judge)."},
            {"value": "recall", "description": "Recall question (Yes/No)."},
            {"value": "ranked_choice", "description": "RCV contest — candidate_or_option suffixed with `| Round N` or `| Final`."},
        ],
        "extraction_quality_values": [
            {"value": "machine_readable", "description": "Parsed from XLS/XLSX with structured columns."},
            {"value": "pdf_text_layer", "description": "Parsed from a PDF text layer via pdfplumber; contest titles + candidate names extracted, but spot-check against source PDF before publishing."},
            {"value": "pdf_ocr", "description": "Reserved — not currently produced."},
            {"value": "manual", "description": "Reserved — for hand-entered records."},
        ],
    }
    (LOOKUPS / "schema.json").write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    LOOKUPS.mkdir(parents=True, exist_ok=True)
    export_party_codes()
    export_choice_map()
    export_election_dates()
    export_sources()
    export_schema()
    print(f"wrote 5 lookup files under {LOOKUPS.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
