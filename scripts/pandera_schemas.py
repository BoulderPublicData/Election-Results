"""
Pandera schemas — the boundary contract for parser-output frames and slim
CSV frames. Both are derived from the single source-of-truth in scripts/schema.py.

These schemas double as documentation: rendering them via
``pandera.io.serialize_schema(SCHEMA)`` gives a JSON description usable by
non-Python consumers; the column docstrings here flow into that JSON.

Usage:

    from .pandera_schemas import IN_MEMORY_SCHEMA, CSV_SCHEMA
    IN_MEMORY_SCHEMA.validate(parser_output_df, lazy=True)  # raises SchemaErrors
    CSV_SCHEMA.validate(csv_loaded_df, lazy=True)

The hand-rolled :func:`scripts.schema.validate` wraps these schemas and returns
a list of problem strings (for callers that don't want to raise) — keeping the
existing API stable while gaining pandera's richer dtype + range checks.
"""

from __future__ import annotations

import pandera.pandas as pa
from pandera.typing import Series  # noqa: F401  -- re-exported for users

from .schema import COLUMNS, CSV_COLUMNS

# ----------------------------------------------------------------------------
# Reusable column specs. Each entry pairs a pandera Column with a description
# that travels into the serialized schema.
# ----------------------------------------------------------------------------

# Required string columns (never null).
_REQ_STR = lambda desc: pa.Column(
    "string", nullable=False, required=True, description=desc,
)
# Optional string columns (null allowed).
_OPT_STR = lambda desc: pa.Column(
    "string", nullable=True, required=True, description=desc,
)
# Nullable integer columns.
_OPT_INT64 = lambda desc: pa.Column(
    "Int64", nullable=True, required=True, description=desc,
)


_BASE_COLUMNS = {
    "election_year": pa.Column(
        "Int16", nullable=False, required=True,
        checks=pa.Check.in_range(min_value=2000, max_value=2100),
        description="Calendar year the election was held.",
    ),
    "election_date": _REQ_STR("Election day, ISO YYYY-MM-DD."),
    "election_type": pa.Column(
        "string", nullable=False, required=True,
        checks=pa.Check.isin(["general", "primary", "coordinated"]),
        description="general (even-year November), primary (even-year June), "
                    "coordinated (odd-year November).",
    ),
    "data_source": pa.Column(
        "string", nullable=False, required=True,
        checks=pa.Check.isin(["boulder_county", "secretary_of_state"]),
        description="Which agency published the file.",
    ),
    "jurisdiction_level": _REQ_STR(
        "county / state / city / school_district / special_district."
    ),
    "jurisdiction_name": _REQ_STR("Always 'Boulder County' in this project."),
    "precinct_id": _REQ_STR(
        "10-digit Boulder/Colorado precinct identifier, string-typed to preserve "
        "leading zeros. Composite IDs (2015, 2022) are joined with commas."
    ),
    "precinct_name": _OPT_STR(
        "Short-form precinct code (3 digits). Null for SOS rows + older Boulder "
        "files without a separate short code."
    ),
    "contest": _REQ_STR("Contest title as published."),
    "contest_type": pa.Column(
        "string", nullable=True, required=True,
        checks=pa.Check.isin([
            "candidate", "measure", "retention", "recall", "ranked_choice",
        ]),
        description="Inferred from contest title + candidate_or_option.",
    ),
    "candidate_or_option": _REQ_STR(
        "Candidate name OR Yes/No OR (RCV) 'Candidate | Round N'."
    ),
    "party": _OPT_STR("Normalized 3-letter party code; null for measures."),
    "votes": _OPT_INT64(
        "Vote tally. May be negative for RCV intermediate rounds."
    ),
    "active_voters": _OPT_INT64("Active registered voters in the precinct."),
    "ballots_cast": _OPT_INT64("Ballots cast in the precinct. Null on SOS rows."),
}


_PROVENANCE_COLUMNS = {
    "source_file": _REQ_STR("Local filename of the raw download."),
    "source_url": _REQ_STR("Canonical upstream URL."),
    "retrieved_at": _REQ_STR("ISO 8601 UTC timestamp of the download."),
    "extraction_quality": pa.Column(
        "string", nullable=False, required=True,
        checks=pa.Check.isin([
            "machine_readable", "pdf_text_layer", "pdf_ocr", "manual",
        ]),
        description="Where the data came from and how reliable extraction was.",
    ),
    "extraction_notes": _OPT_STR("Free-text caveats from the parser."),
}


def _build_inmemory_schema() -> pa.DataFrameSchema:
    cols = dict(_BASE_COLUMNS)
    cols.update(_PROVENANCE_COLUMNS)
    assert set(cols.keys()) == set(COLUMNS), (
        f"in-memory schema columns differ from schema.COLUMNS: "
        f"missing={set(COLUMNS)-set(cols)} extra={set(cols)-set(COLUMNS)}"
    )
    return pa.DataFrameSchema(
        cols, strict=False, ordered=False, name="ElectionResults_InMemory",
        description="Full 20-column parser-output frame.",
    )


def _build_csv_schema() -> pa.DataFrameSchema:
    cols = {c: spec for c, spec in _BASE_COLUMNS.items() if c in CSV_COLUMNS}
    assert set(cols.keys()) == set(CSV_COLUMNS), (
        f"CSV schema columns differ from schema.CSV_COLUMNS: "
        f"missing={set(CSV_COLUMNS)-set(cols)} extra={set(cols)-set(CSV_COLUMNS)}"
    )
    return pa.DataFrameSchema(
        cols, strict=False, ordered=False, name="ElectionResults_CSV",
        description="Slim 15-column view written to data/processed/*.csv.",
    )


IN_MEMORY_SCHEMA = _build_inmemory_schema()
CSV_SCHEMA = _build_csv_schema()
