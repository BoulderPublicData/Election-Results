"""
End-to-end driver: fetch (if needed) → clean → vote counting → reconcile →
audit, plus one entry point for every per-stage command.

Typical use:
  uv run python -m scripts.pipeline                 # full refresh
  uv run python -m scripts.pipeline --no-pdf        # skip the slow PDF years
  uv run python -m scripts.pipeline --year 2024     # one year only
  uv run python -m scripts.pipeline reconcile       # one stage (see below)

A filtered run (--year / --since / --source / --no-pdf) re-parses only the
matching source files. The whole-dataset outputs — all-elections-tidy.csv,
provenance.csv, rejected.csv, summary.md and the reconciliation report — are
rebuilt from every file on disk or upserted by key (scripts/shared_outputs.py),
so they never shrink to the subset (#18).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import shared_outputs
from .clean import BOCO_PDF_YEARS, _meta_for, _output_path, clean_source, write_csv
from .config import (
    AUDIT,
    AUDIT_SUMMARY_MD,
    BOULDER_COUNTY,
    COMBINED_CSV,
    PROVENANCE_CSV,
    REJECTED_CSV,
    REPO_ROOT,
    SECRETARY_OF_STATE,
    STATEMENTS_OF_VOTES,
    sov_csv_path,
)
from .config import (
    SOURCES as ALL_SOURCES,
)
from .schema import provenance_record, validate

# Subcommand → module whose main(argv) implements it.
SUBCOMMANDS: dict[str, tuple[str | None, str]] = {
    "run": (None, "the full pipeline (the default when no subcommand is given)"),
    "discover": ("scripts.discover", "list SoV files upstream that the registry doesn't have"),
    "fetch": ("scripts.fetch", "download raw files into data/original/ (+ manifest)"),
    "clean": ("scripts.clean", "parse raw files into the per-year CSVs"),
    "audit": ("scripts.audit", "per-file summary statistics → data/audit/"),
    "reconcile": ("scripts.reconcile", "compare processed totals with the originals"),
    "export-lookups": ("scripts.export_lookups", "regenerate data/lookups/*.json"),
    "publish": ("scripts.publish", "build elections.db + metadata.yaml for Datasette"),
    "vote-counting": ("scripts.vote_counting", "rebuild the election-night dataset"),
}


def _epilog() -> str:
    width = max(len(k) for k in SUBCOMMANDS)
    lines = ["subcommands (`python -m scripts.pipeline <subcommand> --help` for each):"]
    lines += [f"  {name:<{width}}  {desc}" for name, (_, desc) in SUBCOMMANDS.items()]
    return "\n".join(lines)


def _election_arg(value: str) -> tuple[int, str]:
    from .sources import parse_election_key
    try:
        return parse_election_key(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _run_end_to_end(argv: list[str] | None = None) -> int:
    """The full discover → fetch → clean → reconcile → audit driver.

    This used to be `main()`; it's now the implementation of the `run`
    subcommand. The new `main()` below is an argparse-with-subcommands router.
    """
    ap = argparse.ArgumentParser(
        prog="python -m scripts.pipeline [run]", description=__doc__, epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int)
    ap.add_argument("-e", "--election", type=_election_arg, metavar="KEY",
                    help="Only this election, as an election key, e.g. 2024-general")
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
                    default=COMBINED_CSV)
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
    if args.election:
        pool = [s for s in pool if (s.year, s.election_type) == args.election]
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

    STATEMENTS_OF_VOTES.mkdir(parents=True, exist_ok=True)
    per_year: list[pd.DataFrame] = []
    prov_rows: list[dict] = []
    parsed: list[tuple[str, str]] = []
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
        prov_rows.append(provenance_record(df, _meta_for(s)))
        parsed.append((s.data_source, s.local_filename))

    # Whole-dataset outputs: rebuilt from every per-year CSV on disk or
    # upserted by key, never replaced by just this run's subset (#18).
    combined = shared_outputs.rebuild_combined(STATEMENTS_OF_VOTES, args.combined_out)
    print(f"\nwrote {args.combined_out.relative_to(REPO_ROOT)} "
          f"({len(combined):,} rows, "
          f"{combined['election_year'].nunique()} years, "
          f"{combined['data_source'].nunique()} sources)")

    # Provenance sidecar — one row per source file. The per-year CSVs drop
    # these 5 columns to keep file sizes down (they're constant for every row
    # from a given file); the sidecar preserves the info so nothing's lost.
    prov_df = shared_outputs.upsert_provenance(prov_rows, PROVENANCE_CSV)
    print(f"wrote {PROVENANCE_CSV.relative_to(REPO_ROOT)} "
          f"({len(prov_df)} source files; {len(prov_rows)} updated this run)")

    # Reject port — drain the per-parser rejection buffers and upsert them by
    # source file. Any non-zero count is a signal that a parser dropped rows;
    # the row_index column points back into the source file.
    from .reject import drain as _drain_rejects
    rejected = shared_outputs.upsert_rejects(_drain_rejects(), parsed, REJECTED_CSV)
    print(f"wrote {REJECTED_CSV.relative_to(REPO_ROOT)} ({len(rejected)} rejected rows"
          + (" — investigate before publishing)" if len(rejected) else ")"))

    # Election-night vote counting — rebuilt from the committed Datalab cache
    # only (never calls the API; run `pipeline vote-counting --ocr` for new
    # screenshots). Runs before reconcile so the SoV comparison sees it.
    if args.source in ("all", "boulder_county"):
        print("\n--- vote counting ---")
        try:
            from . import vote_counting
            vc_contests, vc_summary, vc_qa = vote_counting.build(vote_counting.discover())
            vote_counting.write_outputs(vc_contests, vc_summary, vc_qa)
            if (vc_qa["status"] == "open").any():
                print("  WARN: open vote-counting QA issues — see data/audit/vote-counting.md",
                      file=sys.stderr)
        except Exception as e:
            print(f"  vote-counting FAIL: {type(e).__name__}: {e}", file=sys.stderr)
            errors += 1

    # Reconciliation audit — top-line and contest × candidate totals between
    # the raw source files and the processed CSVs. Always run over every
    # source on disk (not just this run's subset) so the shared report covers
    # the whole dataset.
    print("\n--- reconcile ---")
    from . import reconcile
    if reconcile.main([]) != 0:
        errors += 1

    # Audit — per-file fragments for this run's IN-MEMORY frames (which still
    # carry provenance), then summary.md rebuilt from every fragment on disk.
    print("\n--- audit ---")
    from .audit import audit_frame
    AUDIT.mkdir(parents=True, exist_ok=True)
    for df, prov in zip(per_year, prov_rows, strict=True):
        stem = sov_csv_path(int(prov["election_year"]), str(prov["election_type"]),
                            str(prov["data_source"])).stem
        try:
            (AUDIT / f"{stem}.md").write_text(audit_frame(df, stem, provenance=prov))
        except Exception as e:
            print(f"  audit FAIL {stem}: {e}", file=sys.stderr)
    n = shared_outputs.rebuild_audit_summary(AUDIT, AUDIT_SUMMARY_MD)
    print(f"wrote {AUDIT_SUMMARY_MD.relative_to(REPO_ROOT)} ({n} sections)")

    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Subcommand CLI — one entry point that dispatches to per-module mains.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Dispatch to a subcommand. Backwards-compat: `python -m scripts.pipeline`
    with no subcommand runs the full end-to-end driver (the prior behavior)."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] not in SUBCOMMANDS:
        # No subcommand given — treat as `run` for backwards compatibility.
        return _run_end_to_end(argv)

    sub, *rest = argv
    if sub == "run":
        return _run_end_to_end(rest)

    import importlib
    module_name = SUBCOMMANDS[sub][0]
    module = importlib.import_module(module_name)
    if not hasattr(module, "main"):
        print(f"{module_name} has no main() — can't run subcommand `{sub}`",
              file=sys.stderr)
        return 2
    # All module main()s accept argv as their first positional arg.
    return int(module.main(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
