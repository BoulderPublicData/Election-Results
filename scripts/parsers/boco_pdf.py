"""
Boulder County PDF SoV parser (2005, 2007, 2009).

These are coordinated-election Canvass Reports published as 100+ page PDFs.
They have a text layer (not scans) but the layout is multi-column with
candidate names as column headers — tabula-py extracts table-shaped regions
geometrically.

Best-effort. Every row emitted carries extraction_quality='pdf_text_layer' and
an extraction_notes entry summarizing the per-page parse outcome. Tables that
fail to extract are logged but not re-tried; spot-checking against the PDF is
expected before publishing analyses derived from these years.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import SourceMeta
from .common import (
    add_provenance, clean_cols, infer_contest_type,
    normalize_choice, precinct_id_str,
)


def _extract_tables(path: Path) -> list[pd.DataFrame]:
    """tabula-py wrapper. Returns one DataFrame per detected table."""
    import tabula
    # lattice=False with stream mode handles the visually-aligned columns in
    # these reports. multiple_tables=True so each page's tables are returned
    # separately.
    tables = tabula.read_pdf(
        str(path),
        pages="all",
        multiple_tables=True,
        lattice=False,
        stream=True,
        pandas_options={"dtype": str},
        guess=True,
    )
    return [t for t in tables if isinstance(t, pd.DataFrame) and not t.empty]


def _identify_panel(table: pd.DataFrame) -> tuple[str, list[str], pd.DataFrame] | None:
    """Heuristic: the first column should look like precinct IDs (numeric or short
    codes). Surrounding columns are vote tallies. Return (contest_title_guess,
    candidate_cols, body_df) — title guess is empty (caller fills from neighbor)."""
    df = clean_cols(table)
    if df.shape[1] < 2:
        return None

    # Likely-precinct rows in column 0
    col0 = df.iloc[:, 0].astype("string").str.strip()
    p_mask = col0.str.match(r"^\d{1,10}(\s*,\s*\d+)*$", na=False)
    if p_mask.sum() < 2:
        return None

    body = df[p_mask].copy()
    body = body.rename(columns={body.columns[0]: "precinct_id"})

    # Vote columns are non-empty columns that aren't all-numeric headers.
    vote_cols = [c for c in body.columns if c != "precinct_id"]
    return ("", vote_cols, body)


def parse(path: Path, meta: SourceMeta) -> pd.DataFrame:
    notes: list[str] = []
    try:
        tables = _extract_tables(path)
    except Exception as e:
        raise RuntimeError(f"{path.name}: tabula extraction failed: {e}") from e

    if not tables:
        return add_provenance(
            pd.DataFrame(columns=["precinct_id", "contest", "candidate_or_option", "votes"]),
            meta,
            extraction_notes="tabula returned no tables; PDF requires manual extraction",
        )

    notes.append(f"tabula extracted {len(tables)} tables")

    rows: list[pd.DataFrame] = []
    success_pages = 0
    skipped_pages = 0
    for i, t in enumerate(tables):
        panel = _identify_panel(t)
        if panel is None:
            skipped_pages += 1
            continue
        _, vote_cols, body = panel
        # Best-effort: each vote column becomes a candidate (column header text);
        # numeric coercion drops blanks.
        for col in vote_cols:
            sub = pd.DataFrame()
            sub["precinct_id"] = body["precinct_id"].map(precinct_id_str)
            sub["candidate_or_option"] = str(col).strip()
            sub["votes"] = pd.to_numeric(
                body[col].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
            rows.append(sub)
        success_pages += 1

    if not rows:
        return add_provenance(
            pd.DataFrame(columns=["precinct_id", "contest", "candidate_or_option", "votes"]),
            meta,
            extraction_notes=f"tabula ran but no panels identified; review {path.name} manually",
        )

    out = pd.concat(rows, ignore_index=True)
    out = out.dropna(subset=["precinct_id", "candidate_or_option", "votes"])
    out = out[out["candidate_or_option"].astype("string").str.len() > 0]

    # PDFs lack a clean contest title per panel without page-level OCR; mark
    # contest as unknown so downstream review knows to backfill manually.
    out["contest"] = "<PDF: contest title not extracted>"
    out["candidate_or_option"] = out["candidate_or_option"].map(normalize_choice)
    out["contest_type"] = [
        infer_contest_type(c, ch) for c, ch in zip(out["contest"], out["candidate_or_option"])
    ]

    notes.append(f"panels parsed: {success_pages}; skipped: {skipped_pages}")
    notes.append(
        "contest titles NOT extracted from PDF; rows are precinct × column-header "
        "(candidate or Yes/No). Manual review required to associate columns with the "
        "correct contest title before publication."
    )

    return add_provenance(out, meta, extraction_notes="; ".join(notes))
