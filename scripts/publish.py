"""
Build a SQLite database from the processed CSVs for Datasette publishing.

This implements the **Publish** phase of the data-liberation workflow. It reads
``data/processed/statements-of-votes/`` and ``data/processed/vote-counting/``,
and writes two cross-dataset artifacts to the top of ``data/processed/``:

- ``elections.db`` — single SQLite file with these tables:
  - ``elections`` — the long-form tidy data (one row per precinct × contest × candidate).
  - ``provenance`` — one row per source file, keyed on (election_year, election_type, data_source).
  - ``concepts`` — the cross-source concept catalog from scripts/concepts.py.
  - ``vote_counting_contests`` / ``vote_counting_summary`` — the separate
    election-night dataset (county-wide totals per results-site update), when
    data/processed/vote-counting/ is present.
- ``metadata.yaml`` — Datasette metadata: title, license, source links,
  per-column descriptions (pulled from docs/data-dictionary.md), suggested
  facets, and 2-3 canned queries.

Use ``datasette serve data/processed/elections.db -m data/processed/metadata.yaml``
for local preview. For a no-server option, the README links to Datasette Lite
pointing at the file in a GitHub Release.

The Action under .github/workflows/publish.yml runs this on every push to main
and attaches the SQLite to a GitHub Release.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

from .concepts import CONCEPTS
from .config import (
    DATASETTE_DB,
    DATASETTE_METADATA,
    DATASETTE_RECENT_DB,
    EXCEL_ZIP,
    PROVENANCE_CSV,
    REPO_ROOT,
    STATEMENTS_OF_VOTES,
    VOTE_COUNTING_CONTESTS_CSV,
    VOTE_COUNTING_SUMMARY_CSV,
)
from .logging_setup import get_logger
from .schema import (
    CSV_COLUMNS,
    DTYPES,
    PROVENANCE_DTYPES,
    VOTE_COUNTING_DTYPES,
    VOTE_COUNTING_SUMMARY_DTYPES,
)
from .shared_outputs import per_year_csvs

log = get_logger(__name__)

DB_PATH = DATASETTE_DB
METADATA_PATH = DATASETTE_METADATA
# A lighter database for Datasette Lite, which downloads the whole file into
# the browser (#33): the last four general elections and everything since.
RECENT_SINCE = 2018
RECENT_DB_PATH = DATASETTE_RECENT_DB


def export_excel_csvs(out: Path = EXCEL_ZIP) -> Path:
    """Zip of the per-year CSVs re-encoded as UTF-8 *with* a byte-order mark,
    so double-clicking one opens it in Excel with accented names intact
    (plain UTF-8 CSVs are read as Windows-1252 and garble "Mónica Olguín")."""
    import zipfile

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in per_year_csvs(STATEMENTS_OF_VOTES) + [PROVENANCE_CSV]:
            zf.writestr(p.name, "\ufeff" + p.read_text(encoding="utf-8"))
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _load_combined() -> pd.DataFrame:
    """Every committed per-year CSV, concatenated (#19).

    Built from the per-year files rather than the gitignored
    all-elections-tidy.csv, so the database always holds every year on disk —
    the PDF years included — without re-running the parsers (or needing
    pdfplumber) in CI."""
    paths = per_year_csvs(STATEMENTS_OF_VOTES)
    if not paths:
        raise FileNotFoundError(
            f"no per-year CSVs under {STATEMENTS_OF_VOTES} — run `python -m scripts.pipeline` first"
        )
    frames = [pd.read_csv(p, dtype={c: DTYPES[c] for c in CSV_COLUMNS}, low_memory=False)
              for p in paths]
    return pd.concat([f for f in frames if not f.empty], ignore_index=True)


def _load_provenance() -> pd.DataFrame:
    prov = PROVENANCE_CSV
    if not prov.exists():
        raise FileNotFoundError(
            f"{prov} missing — run `python -m scripts.pipeline run` first"
        )
    return pd.read_csv(prov, dtype=PROVENANCE_DTYPES)


VOTE_COUNTING_TABLES = {
    "vote_counting_contests": VOTE_COUNTING_CONTESTS_CSV,
    "vote_counting_summary": VOTE_COUNTING_SUMMARY_CSV,
}


def _records(frame: pd.DataFrame) -> list[dict]:
    """Rows as dicts with nulls as None, so nullable-integer columns stay
    INTEGER in SQLite instead of collapsing to REAL ("92408.0")."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def _concepts_frame() -> pd.DataFrame:
    return pd.DataFrame([{
        "name": c.name,
        "description": c.description,
        "tier": c.tier,
        "boulder_county_patterns": "|".join(c.boulder_county_patterns),
        "secretary_of_state_patterns": "|".join(c.secretary_of_state_patterns),
        "caveats": c.caveats,
    } for c in CONCEPTS])


def build(db_path: Path = DB_PATH, since: int | None = None) -> Path:
    """Build elections.db from the per-year CSVs + sidecar + concepts.
    `since` keeps only elections from that year on (the slim "recent" DB)."""
    import sqlite_utils

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = sqlite_utils.Database(db_path)

    elections = _load_combined()
    provenance = _load_provenance()
    concepts = _concepts_frame()
    if since is not None:
        elections = elections[elections["election_year"] >= since]
        provenance = provenance[provenance["election_year"] >= since]

    # `elections` table — facetable columns indexed for query speed.
    db["elections"].insert_all(
        _records(elections),
        batch_size=10_000,
    )
    for col in ("election_year", "data_source", "election_type", "contest_type",
                "precinct_id", "party"):
        if col in elections.columns:
            db["elections"].create_index([col])

    # `provenance` — small enough that no index is needed, but a composite
    # primary key makes the join from `elections` deterministic.
    db["provenance"].insert_all(
        _records(provenance),
        pk=("election_year", "election_type", "data_source"),
    )

    # `concepts` — even smaller.
    db["concepts"].insert_all(
        concepts.to_dict(orient="records"),
        pk="name",
    )

    # Election-night snapshots — a separate dataset with its own grain; never
    # union it with `elections`.
    for table, path in VOTE_COUNTING_TABLES.items():
        if not path.exists():
            log.warning("publish.vote_counting_missing", path=str(path.relative_to(REPO_ROOT)))
            continue
        dtypes = VOTE_COUNTING_DTYPES if table == "vote_counting_contests" \
            else VOTE_COUNTING_SUMMARY_DTYPES
        frame = pd.read_csv(path, dtype=dtypes, low_memory=False)
        if since is not None:
            frame = frame[frame["election_year"] >= since]
        db[table].insert_all(_records(frame), batch_size=10_000)
        index_cols = ("election_year", "contest") if table == "vote_counting_contests" \
            else ("election_year",)
        for col in index_cols:
            db[table].create_index([col])

    # Convenience view: elections + provenance joined on the file key.
    db.create_view(
        "elections_with_provenance",
        """
        SELECT e.*, p.source_file, p.source_url, p.retrieved_at,
               p.extraction_quality, p.extraction_notes
        FROM elections e
        LEFT JOIN provenance p
          ON e.election_year = p.election_year
         AND e.election_type = p.election_type
         AND e.data_source   = p.data_source
        """,
        replace=True,
    )

    print(f"wrote {db_path.relative_to(REPO_ROOT)}: elections={len(elections):,} rows "
          f"({elections['election_year'].nunique()} years), provenance={len(provenance)}, "
          f"concepts={len(concepts)}")
    return db_path


# ---------------------------------------------------------------------------
# Metadata.yaml — Datasette's per-database/table/column annotations
# ---------------------------------------------------------------------------

# Pulled from docs/data-dictionary.md § 1. Keep in sync if a column is added.
_COLUMN_DESCRIPTIONS: dict[str, str] = {
    "election_year": "Calendar year the election was held.",
    "election_date": "Election day, ISO YYYY-MM-DD.",
    "election_type": "general / primary / coordinated.",
    "data_source": "Which agency published the file (boulder_county or secretary_of_state).",
    "jurisdiction_level": "county / state / city / school_district / special_district.",
    "jurisdiction_name": "Always 'Boulder County' in this project.",
    "precinct_id": "Precinct identifier (string, preserves leading zeros): 10 digits for SOS and Boulder 2005/2013+, 3 digits for Boulder 2007-2012. Composite reporting units (2010-2025) join their IDs with ', '. Pseudo-precincts ('Property Owner', 'Landowner', 'RMFPD', …) are flagged by is_pseudo_precinct.",
    "precinct_name": "Short-form (3-digit) precinct code. Null for SOS rows.",
    "contest": "Contest title as published.",
    "contest_type": "candidate / measure / retention / recall / ranked_choice.",
    "candidate_or_option": "Candidate name OR Yes/No OR (RCV) 'Candidate | Round N'.",
    "party": "Normalized 3-letter party code. Null for measures.",
    "votes": "Vote tally. May be negative for RCV intermediate rounds.",
    "active_voters": "Active registered voters in the precinct. Null on SOS rows.",
    "ballots_cast": "Ballots cast in the precinct. Null on SOS rows.",
    "is_pseudo_precinct": "1 when precinct_id is, or includes, a unit with no precinct geography "
                          "(property-owner / landowner ballots, SOS SUM / Provisional rows). "
                          "Keep these rows for contest totals; drop them before spatial joins.",
}


# Pulled from docs/data-dictionary.md § 8. Keep in sync if a column is added.
_VOTE_COUNTING_DESCRIPTIONS: dict[str, str] = {
    "election_year": "Calendar year the election was held.",
    "election_date": "Election day, ISO YYYY-MM-DD.",
    "election_type": "general / coordinated.",
    "snapshot_seq": "1..n in last_updated order within the election (null for RCV report rows).",
    "last_updated": "Local time (America/Denver) from the results page's 'Last Updated' box.",
    "results_label": "As published ('Official Results' / 'Unofficial Results'). Not a certification flag.",
    "is_final_snapshot": "1 for the latest update of the election.",
    "contest": "Contest title as published.",
    "vote_for": "N from 'Vote for no more than N', when shown.",
    "contest_type": "candidate / measure / retention / recall / ranked_choice.",
    "candidate_or_option": "Candidate name (party and write-in suffix removed) or Yes/No.",
    "party": "Party code (normalized where known).",
    "is_write_in": "1 if the candidate was listed as a write-in.",
    "votes": "Cumulative votes as of last_updated. Never sum across snapshots.",
    "percent": "Percent as published.",
    "contest_total_votes": "The contest card's TOTAL VOTES row.",
    "vote_change": "Votes gained since the previous snapshot (negative after canvass adjustments).",
    "source_file": "Screenshot or PDF under data/original/boulder-county/.",
}


def build_metadata(out: Path = METADATA_PATH) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "title": "Boulder County + Colorado SOS — Harmonized Precinct Results",
        "description_html": (
            "Precinct-level election results from Boulder County (2005-2025) "
            "and the Colorado Secretary of State (2004-2024), harmonized into "
            "a single long-form schema. "
            "Source: <a href='https://github.com/BoulderPublicData/Election-Results'>"
            "BoulderPublicData/Election-Results</a>. "
            "Methodology: <a href='https://github.com/BoulderPublicData/Election-Results/blob/main/docs/data-dictionary.md'>"
            "data-dictionary.md</a>."
        ),
        "license": "MIT (code and harmonized data) — see repo LICENSE. The underlying "
                   "election results are public records.",
        "license_url": "https://github.com/BoulderPublicData/Election-Results/blob/main/LICENSE",
        "source": "Boulder County Elections + Colorado Secretary of State",
        "source_url": "https://bouldercounty.gov/elections/results/",
        "databases": {
            "elections": {
                "description": (
                    "Harmonized precinct-level election results. "
                    "Each row is one (year × precinct × contest × candidate-or-option) tally."
                ),
                "tables": {
                    "elections": {
                        "title": "Election results (long-form)",
                        "description": (
                            "Slim 15-column schema. For provenance fields "
                            "(source_url, retrieved_at, extraction_quality, "
                            "extraction_notes), join on the `provenance` table "
                            "or query the `elections_with_provenance` view."
                        ),
                        "columns": _COLUMN_DESCRIPTIONS,
                        "facets": [
                            "election_year", "data_source", "election_type",
                            "contest_type", "party", "is_pseudo_precinct",
                        ],
                        "size": 100,
                    },
                    "provenance": {
                        "title": "Per-file provenance sidecar",
                        "description": (
                            "One row per source file. Join `elections` on "
                            "(election_year, election_type, data_source) to "
                            "recover the source URL and download timestamp."
                        ),
                    },
                    "vote_counting_contests": {
                        "title": "Election-night results by update (2014-2025)",
                        "description": (
                            "County-wide totals for every contest and candidate at each "
                            "'Last Updated' time on the Boulder County results site, OCR'd "
                            "from screenshots and checked against each contest's total. "
                            "Votes are cumulative: filter is_final_snapshot = 1 for final "
                            "counts, or use vote_change for per-update increments."
                        ),
                        "columns": _VOTE_COUNTING_DESCRIPTIONS,
                        "facets": ["election_year", "contest_type", "is_final_snapshot"],
                        "size": 100,
                    },
                    "vote_counting_summary": {
                        "title": "Election-night summary by update",
                        "description": (
                            "One row per results-site update: registration, ballots counted, "
                            "and the page's footnotes."
                        ),
                        "facets": ["election_year"],
                    },
                    "concepts": {
                        "title": "Cross-source concept catalog",
                        "description": (
                            "Source-neutral names for contests that appear in "
                            "both Boulder County and SOS files. The `caveats` "
                            "column documents what is NOT comparable across "
                            "sources for each concept."
                        ),
                    },
                },
                "queries": {
                    "presidential_totals_by_year": {
                        "title": "Presidential totals by year + candidate",
                        "description": "Total presidential votes (Boulder County rows only) by year + candidate.",
                        "sql": (
                            "SELECT election_year, candidate_or_option, party, "
                            "SUM(votes) AS total_votes "
                            "FROM elections "
                            "WHERE contest LIKE '%Presidential Electors%' "
                            "  AND data_source = 'boulder_county' "
                            "GROUP BY election_year, candidate_or_option, party "
                            "ORDER BY election_year DESC, total_votes DESC"
                        ),
                    },
                    "rcv_final_rounds": {
                        "title": "RCV races — Final-round results",
                        "description": "All ranked-choice contests, with only the Final round (sums comparable to plurality races).",
                        "sql": (
                            "SELECT election_year, contest, "
                            "REPLACE(candidate_or_option, ' | Final', '') AS candidate, "
                            "SUM(votes) AS final_votes "
                            "FROM elections "
                            "WHERE contest_type = 'ranked_choice' "
                            "  AND candidate_or_option LIKE '% | Final' "
                            "GROUP BY election_year, contest, candidate "
                            "ORDER BY election_year DESC, contest, final_votes DESC"
                        ),
                    },
                    "election_night_progress": {
                        "title": "How a contest's count grew on election night",
                        "description": "Each update's cumulative votes and the change since the previous update, for one contest.",
                        "sql": (
                            "SELECT last_updated, candidate_or_option, votes, vote_change, percent "
                            "FROM vote_counting_contests "
                            "WHERE election_year = :year AND contest = :contest "
                            "  AND snapshot_seq IS NOT NULL "
                            "ORDER BY snapshot_seq, votes DESC"
                        ),
                    },
                    "concept_caveats": {
                        "title": "Cross-source concept caveats",
                        "description": "The 'what's not comparable' notes for every harmonized concept.",
                        "sql": (
                            "SELECT name, tier, description, caveats "
                            "FROM concepts ORDER BY tier, name"
                        ),
                    },
                },
            }
        },
    }
    out.write_text(yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True))
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build", help="Build elections.db, elections-recent.db, metadata.yaml "
                                 "and the Excel-friendly CSV zip.")
    sub.add_parser("metadata-only", help="Re-emit metadata.yaml without rebuilding the DB.")
    sub.add_parser("excel", help="Only write the Excel-friendly (UTF-8 with BOM) CSV zip.")
    args = ap.parse_args(argv)

    cmd = args.cmd or "build"
    if cmd == "metadata-only":
        build_metadata()
        return 0
    if cmd == "excel":
        export_excel_csvs()
        return 0

    db = build()
    recent = build(RECENT_DB_PATH, since=RECENT_SINCE)
    md = build_metadata()
    export_excel_csvs()
    for path in (db, recent):
        print(f"  {path.relative_to(REPO_ROOT)}: {path.stat().st_size / 1e6:.0f} MB")
    print(
        f"\nPreview locally:\n"
        f"  uv run datasette serve {db.relative_to(REPO_ROOT)} "
        f"-m {md.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
