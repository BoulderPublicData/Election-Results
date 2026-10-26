"""
Regenerate the counts and sizes quoted in the docs (#33).

Hand-typed numbers went stale ("~115 tests", "152 MB", "27 contests for 2010
SOS"). Each one now sits between markers and is rewritten from the data:

    <!-- generated:NAME -->…<!-- /generated:NAME -->

Names:

- ``test-count``     — number of pytest tests (``pytest --collect-only``)
- ``combined-size``  — size of all-elections-tidy.csv (after a pipeline run)
- ``db-size``        — size of the Datasette database (after ``publish``)
- ``row-count``      — rows in the combined dataset (sum of the per-year CSVs)
- ``sov-table``      — the per-file rows / contests / precincts table
                       (docs/data-dictionary.md §5)

Run after the pipeline (and ``publish`` if you want ``db-size``):

    uv run python -m scripts.doc_stats            # rewrite the docs in place
    uv run python -m scripts.doc_stats --check    # exit 1 if any are stale

A value that can't be computed (e.g. no elections.db locally) is left as is.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

from .config import (
    COMBINED_CSV,
    DATASETTE_DB,
    PROVENANCE_CSV,
    REPO_ROOT,
    SOURCES,
    sov_csv_path,
)

DOCS = [REPO_ROOT / "README.md", REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "data-dictionary.md", REPO_ROOT / "docs" / "architecture-review.md"]

_MARKER = re.compile(r"(<!-- generated:(?P<name>[a-z-]+) -->)(?P<body>.*?)(<!-- /generated:(?P=name) -->)",
                     re.DOTALL)


def _mb(path: Path) -> str | None:
    return f"{path.stat().st_size / 1e6:.0f} MB" if path.exists() else None


def count_tests() -> str | None:
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                             cwd=REPO_ROOT, capture_output=True, text=True, check=False).stdout
    except OSError:
        return None
    m = re.search(r"(\d+) tests? collected", out)
    return f"{int(m.group(1)):,} tests" if m else None


def _label(source: str) -> str:
    return "Boulder" if source == "boulder_county" else "SOS"


def sov_table() -> str | None:
    quality = {}
    if PROVENANCE_CSV.exists():
        prov = pd.read_csv(PROVENANCE_CSV, dtype=str)
        quality = {(r.election_year, r.election_type, r.data_source): r.extraction_quality
                   for r in prov.itertuples(index=False)}
    rows = ["| Year | Source | Election | Rows | Contests | Precincts | Pseudo-precinct rows | Quality |",
            "|---|---|---|---|---|---|---|---|"]
    found = False
    for s in sorted(SOURCES, key=lambda s: (s.year, s.data_source)):
        p = sov_csv_path(s.year, s.election_type, s.data_source)
        if not p.exists():
            continue
        found = True
        df = pd.read_csv(p, dtype={"precinct_id": "string", "is_pseudo_precinct": "boolean"},
                         usecols=["contest", "precinct_id", "is_pseudo_precinct"])
        q = quality.get((str(s.year), s.election_type, s.data_source), "—")
        rows.append(f"| {s.year} | {_label(s.data_source)} | {s.election_type} | {len(df):,} | "
                    f"{df['contest'].nunique()} | {df['precinct_id'].nunique()} | "
                    f"{int(df['is_pseudo_precinct'].sum()):,} | `{q}` |")
    return "\n" + "\n".join(rows) + "\n" if found else None


def row_count() -> str | None:
    total = 0
    found = False
    for s in SOURCES:
        p = sov_csv_path(s.year, s.election_type, s.data_source)
        if p.exists():
            found = True
            total += sum(1 for _ in p.open(encoding="utf-8")) - 1
    return f"{total:,}" if found else None


def values() -> dict[str, str | None]:
    return {
        "test-count": count_tests(),
        "combined-size": _mb(COMBINED_CSV),
        "db-size": _mb(DATASETTE_DB),
        "row-count": row_count(),
        "sov-table": sov_table(),
    }


def rewrite(text: str, vals: dict[str, str | None]) -> str:
    def repl(m: re.Match) -> str:
        v = vals.get(m.group("name"))
        return m.group(0) if v is None else f"{m.group(1)}{v}{m.group(4)}"
    return _MARKER.sub(repl, text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="Report stale values; don't write")
    args = ap.parse_args(argv)
    vals = values()
    stale = []
    for path in DOCS:
        text = path.read_text()
        new = rewrite(text, vals)
        if new != text:
            stale.append(path.relative_to(REPO_ROOT))
            if not args.check:
                path.write_text(new)
    for name, v in vals.items():
        print(f"{name}: {'(unavailable — left as is)' if v is None else v.strip()[:60]}")
    if args.check:
        for p in stale:
            print(f"stale: {p}", file=sys.stderr)
        return 1 if stale else 0
    print(f"updated {len(stale)} file(s)" if stale else "docs already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
