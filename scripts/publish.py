"""
Build a SQLite database from the processed CSVs for Datasette publishing.

This implements the **Publish** phase of the data-liberation workflow. Two
artifacts are produced under ``data/processed/``:

- ``elections.db`` — single SQLite file with three tables:
  - ``elections`` — the long-form tidy data (one row per precinct × contest × candidate).
  - ``provenance`` — one row per source file, keyed on (election_year, election_type, data_source).
  - ``concepts`` — the cross-source concept catalog from scripts/concepts.py.
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
from .config import LOOKUPS, PROCESSED, REPO_ROOT
from .logging_setup import get_logger

log = get_logger(__name__)

DB_PATH = PROCESSED / "elections.db"
METADATA_PATH = PROCESSED / "metadata.yaml"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _load_combined() -> pd.DataFrame:
    combined = PROCESSED / "all-elections-tidy.csv"
    if not combined.exists():
        raise FileNotFoundError(
            f"{combined} missing — run `python -m scripts.pipeline run` first"
        )
    return pd.read_csv(combined, dtype={"precinct_id": "string"}, low_memory=False)


def _load_provenance() -> pd.DataFrame:
    prov = PROCESSED / "provenance.csv"
    if not prov.exists():
        raise FileNotFoundError(
            f"{prov} missing — run `python -m scripts.pipeline run` first"
        )
    return pd.read_csv(prov, dtype=str)


def _concepts_frame() -> pd.DataFrame:
    return pd.DataFrame([{
        "name": c.name,
        "description": c.description,
        "tier": c.tier,
        "boulder_county_patterns": "|".join(c.boulder_county_patterns),
        "secretary_of_state_patterns": "|".join(c.secretary_of_state_patterns),
        "caveats": c.caveats,
    } for c in CONCEPTS])


def build(db_path: Path = DB_PATH) -> Path:
    """Build elections.db from the per-year CSVs + sidecar + concepts."""
    import sqlite_utils

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = sqlite_utils.Database(db_path)

    elections = _load_combined()
    provenance = _load_provenance()
    concepts = _concepts_frame()

    # `elections` table — facetable columns indexed for query speed.
    db["elections"].insert_all(
        elections.to_dict(orient="records"),
        batch_size=10_000,
    )
    for col in ("election_year", "data_source", "election_type", "contest_type",
                "precinct_id", "party"):
        if col in elections.columns:
            db["elections"].create_index([col])

    # `provenance` — small enough that no index is needed, but a composite
    # primary key makes the join from `elections` deterministic.
    db["provenance"].insert_all(
        provenance.to_dict(orient="records"),
        pk=("election_year", "election_type", "data_source"),
    )

    # `concepts` — even smaller.
    db["concepts"].insert_all(
        concepts.to_dict(orient="records"),
        pk="name",
    )

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

    log.info("publish.build_done",
             db=str(db_path.relative_to(REPO_ROOT)),
             elections_rows=len(elections),
             provenance_rows=len(provenance),
             concepts_rows=len(concepts))
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
    "precinct_id": "10-digit Boulder/Colorado precinct identifier (string, preserves leading zeros). Composite IDs (2015, 2022) appear comma-joined.",
    "precinct_name": "Short-form (3-digit) precinct code. Null for SOS rows.",
    "contest": "Contest title as published.",
    "contest_type": "candidate / measure / retention / recall / ranked_choice.",
    "candidate_or_option": "Candidate name OR Yes/No OR (RCV) 'Candidate | Round N'.",
    "party": "Normalized 3-letter party code. Null for measures.",
    "votes": "Vote tally. May be negative for RCV intermediate rounds.",
    "active_voters": "Active registered voters in the precinct. Null on SOS rows.",
    "ballots_cast": "Ballots cast in the precinct. Null on SOS rows.",
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
        "license": "Public domain (election results) — see repo LICENSE.",
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
                            "contest_type", "party",
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
    log.info("publish.metadata_done", path=str(out.relative_to(REPO_ROOT)))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build", help="Build elections.db + metadata.yaml.")
    sub.add_parser("metadata-only", help="Re-emit metadata.yaml without rebuilding the DB.")
    args = ap.parse_args(argv)

    cmd = args.cmd or "build"
    if cmd == "metadata-only":
        build_metadata()
        print(f"wrote {METADATA_PATH.relative_to(REPO_ROOT)}")
        return 0

    db = build()
    md = build_metadata()
    size_mb = db.stat().st_size / (1024 * 1024)
    print(f"wrote {db.relative_to(REPO_ROOT)}  ({size_mb:.1f} MB)")
    print(f"wrote {md.relative_to(REPO_ROOT)}")
    print(
        f"\nPreview locally:\n"
        f"  uv run datasette serve {db.relative_to(REPO_ROOT)} "
        f"-m {md.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
