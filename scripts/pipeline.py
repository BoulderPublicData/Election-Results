"""
End-to-end driver: fetch (if needed) → clean → audit → emit all-elections-tidy.csv.

Typical use:
  uv run python -m scripts.pipeline                 # full refresh
  uv run python -m scripts.pipeline --no-pdf        # skip the slow PDF years
  uv run python -m scripts.pipeline --year 2024     # one year only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .clean import BOCO_PDF_YEARS, clean_source, _output_path, write_csv
from .config import (
    BOULDER_COUNTY, PROCESSED as PROCESSED_DATA, REPO_ROOT,
    SECRETARY_OF_STATE, SOURCES as ALL_SOURCES,
)
from .logging_setup import get_logger
from .schema import PROVENANCE_COLUMNS, provenance_record, validate

log = get_logger(__name__)


def _run_end_to_end(argv: list[str] | None = None) -> int:
    """The full discover → fetch → clean → reconcile → audit driver.

    This used to be `main()`; it's now the implementation of the `run`
    subcommand. The new `main()` below is an argparse-with-subcommands router.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int)
    ap.add_argument("--since", type=int)
    ap.add_argument("--source", choices=["boulder_county", "secretary_of_state", "all"],
                    default="all")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Don't try to download; assume files already present.")
    ap.add_argument("--discover", action="store_true",
                    help="Also scrape upstream landing pages for sources not in "
                         "the static registry (e.g. a newly published year)")
    ap.add_argument("--combined-out", type=Path,
                    default=PROCESSED_DATA / "all-elections-tidy.csv")
    args = ap.parse_args(argv)

    if args.source == "boulder_county":
        pool = list(BOULDER_COUNTY)
    elif args.source == "secretary_of_state":
        pool = list(SECRETARY_OF_STATE)
    else:
        pool = list(ALL_SOURCES)

    if args.discover:
        try:
            from .discover import discover, merge_with_registry
            discovered = discover()
            new = merge_with_registry(discovered, only_new=True)
            if args.source != "all":
                new = [s for s in new if s.data_source == args.source]
            for s in new:
                print(f"discover  +{s.year}-{s.election_type}-{s.data_source}  {s.url}",
                      file=sys.stderr)
            pool.extend(new)
        except Exception as e:
            print(f"WARN discovery failed: {e}", file=sys.stderr)

    if args.year:
        pool = [s for s in pool if s.year == args.year]
    if args.since:
        pool = [s for s in pool if s.year >= args.since]
    if args.no_pdf:
        pool = [s for s in pool if s.year not in BOCO_PDF_YEARS]

    if not args.skip_fetch:
        from .fetch import fetch_many
        fetch_errors = fetch_many(pool)
        if fetch_errors:
            print(f"WARN: {fetch_errors} fetch error(s); continuing with files on disk",
                  file=sys.stderr)

    PROCESSED_DATA.mkdir(parents=True, exist_ok=True)
    per_year: list[pd.DataFrame] = []
    errors = 0
    for s in pool:
        label = f"{s.year}-{s.election_type}-{s.data_source}"
        try:
            df = clean_source(s)
        except Exception as e:
            print(f"FAIL {label}: {type(e).__name__}: {e}", file=sys.stderr)
            errors += 1
            continue
        probs = validate(df, source_label=label)
        for p in probs:
            print(f"  WARN {p}", file=sys.stderr)
        write_csv(df, _output_path(s))
        print(f"OK   {label}  rows={len(df):>6}")
        per_year.append(df)

    if per_year:
        combined = pd.concat(per_year, ignore_index=True)
        write_csv(combined, args.combined_out)
        print(f"\nwrote {args.combined_out.relative_to(REPO_ROOT)} "
              f"({len(combined):,} rows, "
              f"{combined['election_year'].nunique()} years, "
              f"{combined['data_source'].nunique()} sources)")

        # Provenance sidecar — one row per source file. The per-year CSVs
        # drop these 5 columns to keep file sizes down (they're constant for
        # every row from a given file); the sidecar preserves the info so
        # nothing's lost.
        prov_rows = [provenance_record(df) for df in per_year]
        prov_df = pd.DataFrame(prov_rows)
        prov_path = PROCESSED_DATA / "provenance.csv"
        prov_df.to_csv(prov_path, index=False)
        print(f"wrote {prov_path.relative_to(REPO_ROOT)} "
              f"({len(prov_df)} source files; provenance for the slim per-year CSVs)")

    # Reject port — drain the per-parser rejection buffers and emit a single
    # CSV. Any non-zero count here is a signal that the parser dropped rows;
    # the row_index column points back into the source file.
    from .reject import drain as _drain_rejects
    from .config import REJECTED_CSV
    rejected = _drain_rejects()
    REJECTED_CSV.parent.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(REJECTED_CSV, index=False)
    if len(rejected):
        log.warning("pipeline.rejected_rows",
                    count=len(rejected), path=str(REJECTED_CSV.relative_to(REPO_ROOT)))
        print(f"wrote {REJECTED_CSV.relative_to(REPO_ROOT)} "
              f"({len(rejected)} rejected rows — investigate before publishing)")
    else:
        print(f"wrote {REJECTED_CSV.relative_to(REPO_ROOT)} (0 rejected rows)")

    # Reconciliation audit — compares top-line contest totals between the raw
    # source files and the processed CSVs. Caught regressions in earlier passes.
    print("\n--- reconcile ---")
    try:
        from .reconcile import reconcile_source, _load_patterns
        patterns = _load_patterns()
        recon_frames = []
        for s in pool:
            try:
                r = reconcile_source(s, patterns)
            except Exception as e:
                print(f"  reconcile FAIL {s.year}-{s.data_source}: {e}", file=sys.stderr)
                continue
            if not r.empty:
                recon_frames.append(r)
        if recon_frames:
            all_recon = pd.concat(recon_frames, ignore_index=True)
            from .reconcile import AUDIT as _AUDIT_DIR
            _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            all_recon.to_csv(_AUDIT_DIR / "reconciliation.csv", index=False)
            mismatches = (all_recon["status"] == "mismatch").sum()
            print(f"reconciled {len(all_recon)} contest-source rows; mismatches={mismatches}")
            if mismatches:
                print(
                    "  WARN: top-line totals diverged from the source — "
                    "run `uv run python -m scripts.reconcile` for the Markdown report",
                    file=sys.stderr,
                )
    except ImportError as e:
        print(f"  reconcile skipped: {e}", file=sys.stderr)

    # Audit — runs on the IN-MEMORY frames (which still carry provenance)
    # so we don't have to re-read the slim CSVs + join the sidecar.
    print("\n--- audit ---")
    from .audit import AUDIT_DIR, audit_frame
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    fragments: list[str] = []
    for df in per_year:
        if df.empty:
            continue
        # Recover the per-file stem from the per-row schema columns.
        year = df["election_year"].iloc[0]
        etype = df["election_type"].iloc[0]
        ds = df["data_source"].iloc[0].replace("_", "-")
        stem = f"{year}-{etype}-{ds}"
        try:
            frag = audit_frame(df, stem)
            (AUDIT_DIR / f"{stem}.md").write_text(frag)
            fragments.append(frag)
        except Exception as e:
            print(f"  audit FAIL {stem}: {e}", file=sys.stderr)
    (AUDIT_DIR / "summary.md").write_text("\n".join(fragments))
    print(f"wrote data/audit/summary.md ({len(fragments)} sections)")

    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Subcommand CLI — one entry point that dispatches to per-module mains.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Dispatch to a subcommand. Backwards-compat: `python -m scripts.pipeline`
    with no subcommand runs the full end-to-end driver (the prior behavior)."""
    if argv is None:
        argv = sys.argv[1:]

    # Backwards compat: no subcommand → run the full pipeline as before.
    subcommands = {
        "discover": "scripts.discover",
        "fetch": "scripts.fetch",
        "clean": "scripts.clean",
        "audit": "scripts.audit",
        "reconcile": "scripts.reconcile",
        "export-lookups": "scripts.export_lookups",
        "publish": "scripts.publish",
        "run": None,  # handled inline
    }

    if not argv or argv[0] not in subcommands:
        # No subcommand given — treat as `run` for backwards compatibility.
        return _run_end_to_end(argv)

    sub, *rest = argv
    if sub == "run":
        return _run_end_to_end(rest)

    import importlib
    module_name = subcommands[sub]
    module = importlib.import_module(module_name)
    if not hasattr(module, "main"):
        print(f"{module_name} has no main() — can't run subcommand `{sub}`",
              file=sys.stderr)
        return 2
    # All module main()s accept argv as their first positional arg.
    return int(module.main(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
