"""
Whole-dataset artifacts, rebuilt or upserted so a filtered run never shrinks them.

`pipeline --year 2025` (or `--source`, `--since`, `--no-pdf`, or `clean`)
re-parses only some source files, but several outputs describe the whole
dataset (#18):

- ``statements-of-votes/all-elections-tidy.csv`` — rebuilt from every per-year
  CSV on disk, not from this run's frames;
- ``statements-of-votes/provenance.csv`` — upserted on
  (election_year, election_type, data_source);
- ``data/audit/rejected.csv`` — upserted on (data_source, source_file);
- ``data/audit/summary.md`` — rebuilt from every per-file audit fragment
  (``data/audit/{stem}.md``) on disk.

Rows are ordered like the source registry (Boulder County, then SOS, by
year), with any discovered sources not in the registry after them.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import (
    AUDIT,
    AUDIT_SUMMARY_MD,
    COMBINED_CSV,
    PROVENANCE_CSV,
    REJECTED_CSV,
    SOURCES,
    STATEMENTS_OF_VOTES,
    sov_csv_path,
)
from .schema import CSV_COLUMNS, DTYPES, PROVENANCE_COLUMNS, PROVENANCE_DTYPES, to_csv_frame

PROVENANCE_KEY = ["election_year", "election_type", "data_source"]
REJECT_COLUMNS = ["source_file", "election_year", "data_source", "row_index",
                  "reason", "detail", "raw_row"]


def _registry_order() -> dict[tuple[int, str, str], int]:
    return {(s.year, s.election_type, s.data_source): i for i, s in enumerate(SOURCES)}


def _sort_by_registry(df: pd.DataFrame, year: str = "election_year",
                      etype: str = "election_type", source: str = "data_source") -> pd.DataFrame:
    if df.empty:
        return df
    order = _registry_order()
    rank = [order.get((int(y), t, s), len(order) + i) if pd.notna(y) else len(order) * 2 + i
            for i, (y, t, s) in enumerate(zip(df[year], df[etype], df[source], strict=True))]
    return df.assign(_rank=rank).sort_values("_rank", kind="stable").drop(columns="_rank")


def per_year_csvs(directory: Path = STATEMENTS_OF_VOTES) -> list[Path]:
    """Every per-year CSV on disk, registry sources first (in registry order)."""
    on_disk = {p.name: p for p in directory.glob("[0-9]*.csv")}
    ordered = []
    for s in SOURCES:
        p = sov_csv_path(s.year, s.election_type, s.data_source)
        if p.name in on_disk:
            ordered.append(on_disk.pop(p.name))
    return ordered + sorted(on_disk.values())


def rebuild_combined(directory: Path = STATEMENTS_OF_VOTES,
                     out: Path = COMBINED_CSV) -> pd.DataFrame:
    """Concatenate every per-year CSV under `directory` into `out`."""
    frames = [pd.read_csv(p, dtype={c: DTYPES[c] for c in CSV_COLUMNS}, low_memory=False)
              for p in per_year_csvs(directory)]
    frames = [f for f in frames if not f.empty]
    combined = (pd.concat(frames, ignore_index=True) if frames
                else pd.DataFrame(columns=CSV_COLUMNS))
    out.parent.mkdir(parents=True, exist_ok=True)
    to_csv_frame(combined).to_csv(out, index=False)
    return combined


def _read_provenance(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PROVENANCE_KEY + PROVENANCE_COLUMNS)
    prov = pd.read_csv(path, dtype=PROVENANCE_DTYPES)
    return prov.dropna(subset=PROVENANCE_KEY)


def upsert_provenance(rows: list[dict], path: Path = PROVENANCE_CSV) -> pd.DataFrame:
    """Replace the sidecar rows for the sources in `rows`; keep every other row."""
    new = pd.DataFrame(rows, columns=PROVENANCE_KEY + PROVENANCE_COLUMNS)
    old = _read_provenance(path)
    if not new.empty:
        keys = set(zip(new["election_year"].astype(int), new["election_type"],
                       new["data_source"], strict=True))
        keep = [(int(y), t, s) not in keys for y, t, s in
                zip(old["election_year"], old["election_type"], old["data_source"], strict=True)]
        old = old[keep]
    merged = pd.concat([old, new], ignore_index=True) if len(old) else new
    merged = _sort_by_registry(merged)[PROVENANCE_KEY + PROVENANCE_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged


def upsert_rejects(rejected: pd.DataFrame, sources: list[tuple[str, str]],
                   path: Path = REJECTED_CSV) -> pd.DataFrame:
    """Replace the reject rows of every (data_source, source_file) in `sources`
    — the files this run parsed, whether or not they rejected anything — and
    keep the rows for every other file."""
    old = (pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists()
           else pd.DataFrame(columns=REJECT_COLUMNS))
    done = set(sources)
    old = old[[(d, f) not in done for d, f in
               zip(old["data_source"], old["source_file"], strict=True)]]
    new = rejected.astype(str).reindex(columns=REJECT_COLUMNS) if len(rejected) else None
    merged = pd.concat([old, new], ignore_index=True) if new is not None else old
    merged = merged.reindex(columns=REJECT_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged


def rebuild_audit_summary(audit_dir: Path = AUDIT, out: Path = AUDIT_SUMMARY_MD) -> int:
    """Concatenate every per-file audit fragment in registry order. Returns
    the number of sections."""
    stems = [sov_csv_path(s.year, s.election_type, s.data_source).stem for s in SOURCES]
    seen = set(stems)
    extra = sorted(p.stem for p in audit_dir.glob("[0-9]*.md") if p.stem not in seen)
    fragments = [(audit_dir / f"{stem}.md").read_text()
                 for stem in stems + extra if (audit_dir / f"{stem}.md").exists()]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(fragments))
    return len(fragments)
