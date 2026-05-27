"""
Per-parser reject port.

The 9-step data-liberation cleaning pipeline ends with "validation + reject
port". Until now, parsers either silently `dropna()` or swallowed bad rows
into a counter in `extraction_notes`. That makes regressions invisible —
no one knows that, say, the 2008 panel parser is dropping 14 measure rows.

This module gives each parser a per-source ``Rejector`` it appends to as
malformed rows are encountered; the pipeline writes the union to
``data/audit/rejected.csv`` with columns:

    source_file        — local filename of the raw download
    election_year      — int
    data_source        — boulder_county / secretary_of_state
    row_index          — best-effort source-row pointer (sheet:row, or page:line)
    reason             — short machine-friendly tag (e.g. "missing_precinct_id")
    detail             — human-readable explanation
    raw_row            — JSON-encoded original row values, when available

Reading the rejected.csv post-run is the strongest signal that something
upstream changed and the parser needs a tweak.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class RejectedRow:
    source_file: str
    election_year: int | None
    data_source: str
    row_index: str        # "sheet:row" or "page:line" — best-effort, never None
    reason: str           # short tag, e.g. "missing_required_field"
    detail: str           # free-text explanation
    raw_row: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "election_year": self.election_year,
            "data_source": self.data_source,
            "row_index": self.row_index,
            "reason": self.reason,
            "detail": self.detail,
            "raw_row": json.dumps(self.raw_row, default=str) if self.raw_row else "",
        }


class Rejector:
    """Each parser gets one. Append to it; the pipeline drains it after."""

    def __init__(self, source_file: str, election_year: int | None, data_source: str):
        self.source_file = source_file
        self.election_year = election_year
        self.data_source = data_source
        self._rows: list[RejectedRow] = []

    def add(self, *, row_index: str, reason: str, detail: str = "",
            raw_row: dict[str, Any] | None = None) -> None:
        self._rows.append(RejectedRow(
            source_file=self.source_file,
            election_year=self.election_year,
            data_source=self.data_source,
            row_index=row_index,
            reason=reason,
            detail=detail,
            raw_row=raw_row or {},
        ))

    def drop_na_with_reject(
        self,
        df: pd.DataFrame,
        *,
        required: list[str],
        reason: str = "missing_required_field",
        row_index_col: str | None = None,
    ) -> pd.DataFrame:
        """Replace `df.dropna(subset=required)` with a rejecting version.

        Rows missing any required field are recorded in this rejector with
        `reason` and a `detail` listing the missing fields. The original row
        values (excluding null fields) are saved in `raw_row`.
        """
        mask = df[required].isna().any(axis=1)
        if mask.any():
            for idx, row in df[mask].iterrows():
                missing = [c for c in required if pd.isna(row.get(c))]
                self.add(
                    row_index=str(row.get(row_index_col, idx)) if row_index_col else str(idx),
                    reason=reason,
                    detail=f"missing: {', '.join(missing)}",
                    raw_row={k: row[k] for k in row.index if pd.notna(row[k])},
                )
        return df[~mask].copy()

    def __len__(self) -> int:
        return len(self._rows)

    def to_frame(self) -> pd.DataFrame:
        if not self._rows:
            return pd.DataFrame(columns=[
                "source_file", "election_year", "data_source", "row_index",
                "reason", "detail", "raw_row",
            ])
        return pd.DataFrame([r.to_dict() for r in self._rows])


# Module-level registry — parsers push rejector instances here; pipeline drains
# them after the full run. Using a list (not a stack) so order matches the run.
_BUFFER: list[Rejector] = []


def register(rejector: Rejector) -> None:
    _BUFFER.append(rejector)


def drain() -> pd.DataFrame:
    """Pop all registered rejectors and return their union as a single frame."""
    global _BUFFER
    if not _BUFFER:
        return pd.DataFrame(columns=[
            "source_file", "election_year", "data_source", "row_index",
            "reason", "detail", "raw_row",
        ])
    frames = [r.to_frame() for r in _BUFFER if len(r) > 0]
    _BUFFER = []
    if not frames:
        return pd.DataFrame(columns=[
            "source_file", "election_year", "data_source", "row_index",
            "reason", "detail", "raw_row",
        ])
    return pd.concat(frames, ignore_index=True)


def reset() -> None:
    """For tests."""
    global _BUFFER
    _BUFFER = []
