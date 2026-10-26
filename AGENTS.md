# Agent handbook

Read this first if you're an LLM agent (Claude Code, Cursor, etc.) being asked to extend or maintain this repo. It's a single-page brief: architecture, design choices, known limitations, where to be careful, and what counts as "done."

This file is also a useful overview for human collaborators.

---

## 0. One-paragraph summary

This repo harmonizes precinct-level election results from Boulder County (2005-2025) and the Colorado Secretary of State (2004-2024) into a single long-form CSV under `data/processed/statements-of-votes/`. Raw files in `data/original/` are immutable; everything else under `data/` is regenerable from them via `scripts/pipeline.py`. The schema is defined once in [`scripts/schema.py`](scripts/schema.py); every parser produces the same 20 columns. A reconciliation audit ([`scripts/reconcile.py`](scripts/reconcile.py)) compares top-line contest totals between the originals and the processed CSVs and would catch a regression. [`scripts/discover.py`](scripts/discover.py) scrapes the upstream Boulder County and SOS landing pages so the pipeline picks up newly-published years even before they're hand-added to the static registry. A GitHub Action runs every January 6 to refresh the prior calendar year; another runs pytest on every push and PR.

---

## 1. Architecture

```
       ┌─────────────────────────┐     ┌──────────────────────┐
       │  scripts/discover.py    │ ──▶ │  scripts/sources.py  │
       │  (BoCo + SOS scrapers)  │     │  URL registry + dates│
       └─────────────────────────┘     └──────────┬───────────┘
                                                  │ Source records
                                                  ▼
                                       ┌──────────────────────┐
                                       │   scripts/fetch.py   │  idempotent downloader
                                       └──────────┬───────────┘
                               │ data/original/{source}/*.xls(x|pdf)
                               ▼
        ┌─────────────────────────────────────────────────┐
        │            scripts/clean.py (router)            │
        │  routes by (year, data_source) to one parser:   │
        │   ├─ parsers/boco_tidy.py   (Boulder 2013-2025) │
        │   ├─ parsers/boco_panel.py  (Boulder 2008-2012) │
        │   ├─ parsers/boco_pdf.py    (Boulder 2005-2009) │
        │   └─ parsers/sos.py         (SOS 2004-2020)     │
        └─────────────────┬───────────────────────────────┘
                          │ DataFrame matching scripts.schema.COLUMNS
                          ▼
          data/processed/statements-of-votes/{year}-{type}-{source}.csv
                          │
                ┌─────────┼──────────────┐
                ▼         ▼              ▼
       scripts/audit.py  scripts/reconcile.py
       per-file stats    top-line totals vs originals
                │              │
                ▼              ▼
       data/audit/*.md    data/audit/reconciliation.{md,csv}
```

All modules above sit under `scripts/` and are wired up so `uv run python -m scripts.pipeline` runs end-to-end. The dataset is `data/processed/statements-of-votes/`; provenance (`source_url`, `retrieved_at`, `extraction_quality`, …) is carried on the in-memory frames and written once per source file to `data/processed/statements-of-votes/provenance.csv` (§2.1a).

A second, separate dataset rides alongside: **election-night snapshots** (`scripts/vote_counting.py` → `data/processed/vote-counting/`), OCR'd from results-site screenshots through Datalab with a committed response cache, its own schema (`schema.py:VOTE_COUNTING_*`), QA (`data/audit/vote-counting.md`), and a report-only comparison against the SoV in `reconcile.py`. The pipeline rebuilds it from the cache and never calls the API.

All Excel reads go through `parsers/common.py:read_excel` / `excel_file` (the calamine engine — 4-6× faster than openpyxl on the statewide SOS files). `clean.py:clean_source` coerces every parser's output to `schema.DTYPES` before it is validated or written.

---

## 2. Design choices and why

### 2.1 Long-form schema with one row per (year × precinct × contest × candidate)

**Why:** Long form pivots to anything (candidate-wide, contest-wide, precinct-wide, year-wide). The cost is that `active_voters` and `ballots_cast` repeat across every row in the same precinct/year — analysts must `drop_duplicates(["year","precinct_id"])` before summing them. Documented in `docs/filter-pivot-recipes.md` § "Common gotchas".

**Don't change to wide form.** The reshape recipes already handle the common views; widening the storage would break the SOS schema (which lacks ballots_cast) and the RCV round-level rows.

### 2.1a Provenance lives in a sidecar, not on every row

**Why:** `source_file`, `source_url`, `retrieved_at`, `extraction_quality`, `extraction_notes` are constant per source file — repeating them on every row would inflate per-year CSVs by ~3×. They live in `data/processed/statements-of-votes/provenance.csv` (one row per source file) and the in-memory schema. `scripts.schema.to_csv_frame()` drops them before write; `pipeline.py` regenerates the sidecar from the in-memory frames so the two views stay synchronized.

To recover row-level provenance, join on `(election_year, election_type, data_source)` — see `docs/filter-pivot-recipes.md` § "Joining the provenance sidecar". `scripts.audit.audit_file` and `scripts.audit.audit_frame` both reconstruct provenance: the file-based variant reads the sidecar, the frame-based variant reads the in-memory columns directly.

### 2.2 Separate per-year parsers (not one mega-parser)

**Why:** Each year/source generation has its own quirks (column rename, header layout, party-name conventions, RCV-vs-plurality sheets, panel vs. tidy format). Forcing them through one branching function hid bugs in the original `Cleaning.ipynb`. Splitting into `parsers/boco_tidy.py`, `parsers/boco_panel.py`, etc. makes each generation testable in isolation and adds a clear extension point for new years.

### 2.3 Schema as code (`scripts/schema.py`), exported as JSON

**Why:** Python `dataclass` + `dict[str, str]` definitions are easy to validate against. The JSON exports under `data/lookups/` (regenerated by `scripts/export_lookups.py`) let R / Excel / JS consumers read the same canonical definitions without parsing Python.

### 2.4 Three audit layers, not one

- **`scripts/audit.py`** — per-file summary stats (row counts, contests, parties, top-N).
- **`scripts/reconcile.py`** — reconciliation between original files and processed CSVs, at two levels: top-line contests, and every contest × candidate key (the strongest correctness check), plus structural checks for duplicate keys and contests that mix Yes/No with candidates.
- **`Cleaning.ipynb` § 5** — narrative reconciliation in the methodology notebook.

**Why three:** The audit catches null-rate regressions and shape changes. The reconciliation catches vote-count regressions (the thing that would actually mislead an analyst). The notebook is the human-readable doc that explains both.

### 2.5 `data/original/` is immutable

Raw downloads are committed alongside the manifest (sha256 + retrieved_at for every file). Anything else under `data/` is regenerable. **Never edit `data/original/` files in place** — if you find an issue, change the parser, not the raw file. `scripts.fetch` never overwrites an original: an existing file is skipped (or recorded, if it has no manifest entry), a sha256 mismatch is a `FAIL`, and only `--force` re-downloads. `uv run python -m scripts.fetch --verify` checks every hash without the network.

**One documented exception:** the Datalab OCR cache under `data/processed/vote-counting/datalab/` is derived from `data/original/` but costs money to rebuild, so it is committed and the pipeline only ever reads it. Treat it as append-only: re-OCR (`vote_counting --ocr`) only images whose cache entry is missing or stale.

### 2.6 uv + pyproject.toml (not pip + requirements.txt)

**Why:** uv resolves deterministically (lock file), runs fast in CI, and the GitHub Action uses `astral-sh/setup-uv`. If you must use pip, run `uv pip compile pyproject.toml -o requirements.txt` and use that — but commit it.

### 2.7 Kebab-case file/dir names; snake_case Python module names

**Why:** The user asked for kebab-case (correcting an earlier choice of snake_case). It applies to directories, JSON files, and CSV filenames. Python modules continue to use snake_case because that's the language requirement.

### 2.8 Discovery layered on top of a static registry

**Why:** Pure scraping is fragile — Boulder's `elections/results/` page rotates content and SOS reorganizes URL paths. A hand-maintained registry in `sources.py` keeps the canonical URLs stable; discovery only fills in gaps for years more recent than the last hand-recorded entry. `merge_with_registry(only_new=True)` is the default contract: the static registry wins for any (year, data_source) it already covers. Update the registry whenever a newly-discovered year lands in a PR.

### 2.9 Hermetic tests (offline by default)

**Why:** The discovery tests use HTML fixtures captured under `tests/fixtures/` so CI doesn't break if a vendor's CDN flakes. Re-capture them when the upstream pages change shape (instructions in `tests/test_discover.py`'s module docstring). Tests against `data/processed/` skip gracefully when the CSVs aren't present on disk, so the suite passes on a fresh clone without running the full pipeline first.

---

## 3. Where to be careful

| Area | Hazard | What to do |
|---|---|---|
| **Schema changes** | Adding/removing a column without updating `scripts/schema.py` breaks coercion and validation downstream. | Edit `COLUMNS` + `DTYPES` in one place; every parser will fail-fast until it returns the new shape. |
| **Composite precinct IDs (2015, 2022)** | Joining to precinct geography on `precinct_id` silently drops these rows. | Split on `,` before joins; `extraction_notes` flags these years. |
| **Property-owner pseudo-precincts (2015, 2023, 2025)** | Rows with `precinct_id` `Property Owner` / `Landowner` have no geography; dropping them undercounts special-district contests. | Keep them for totals, exclude them before spatial joins. See `docs/data-dictionary.md` §4.3a. |
| **RCV expansion (2023)** | Summing `votes` for RCV contests double-counts (Round 1 + Round 2 + Final). | Filter to `candidate_or_option.str.endswith("| Final")` before summing totals. Reconcile already handles this — see `reconcile.py:reconcile_source`. |
| **2008-2012 Boulder panel format** | Header labels don't sit over their values (merged cells), so `boco_panel` maps each row's non-empty cells to the header's non-empty labels by position — never by spreadsheet column. Rows that don't fit go to the reject port. | Keep `reconcile.py`'s contest × candidate check at 0 mismatches: it compares against the file's own `Totals` row. |
| **2005/2007/2009 PDF years** | Candidate columns change page to page within one contest, and the vote-method block is 4 columns (2007) or 6 (2005/2009). | `boco_pdf` re-reads the header on every page and splits rows at the `%` token. Rows still carry `extraction_quality = pdf_text_layer`; spot-check names against the source PDF. |
| **2024 Boulder file** | The upstream "Amended SoV" file contains only 66 rows of local races (Town of Superior, etc.). Federal/state-level Boulder results may have a separate file or appear via SOS once published. | Verify the file's scope before drawing conclusions. |
| **negative `votes` values** | Legitimately appear in RCV intermediate rounds (ballots transferring away from eliminated candidates). | `validate()` skips this check for `contest_type == "ranked_choice"` rows. Don't "fix" it by taking absolute values — you lose information. |
| **Election-night snapshots** (`data/processed/vote-counting/`) | Rows are cumulative county-wide totals per snapshot; summing `votes` across snapshots multiplies them, and concatenating with precinct data double-counts. | Use `vote_change` or filter `is_final_snapshot`. Keep the dataset separate (own schema in `schema.py:VOTE_COUNTING_*`). |
| **Vote-counting OCR fixes** | Editing a cached Datalab JSON hides the fix and is overwritten on re-OCR. | Add a row to `scripts/corrections/vote-counting.csv` (the build fails if its `ocr_value` stops matching). `data/audit/vote-counting.md` must show 0 open issues. |
| **Combined CSV size** | `all-elections-tidy.csv` is 152 MB. Gitignored. | The pipeline regenerates it from per-year files in ~30s; never check it in. |

---

## 4. Limitations and uncertainties

### Hard limitations (documented in `docs/data-dictionary.md`)

- **No precinct geographies** are bundled. `data/lookups/*-precincts.json` are precinct-ID *lists*, not shapes. If you want choropleth maps, source the precinct GeoJSON separately and join on `precinct_id`.
- **`ballots_cast` and `active_voters` are null on SOS rows.** The SOS publishes only candidate vote totals.
- **No primary-election data.** Boulder publishes primary results but we haven't ingested them.
- **No write-in candidate detail.** Files lump all write-ins into a single "Write-In" row.

### Open uncertainties (do not "fix" without evidence)

- **PDF candidate labels.** Vote counts reconcile exactly to each PDF's printed totals, but candidate names are rebuilt from rotated text (clustered by x-coordinate, char-reversed). A misspelled or truncated label would still reconcile — spot-check names against the source PDF before publishing.
- **Party-name normalization is best-effort.** The `PARTY_MAP` in `parsers/common.py` is exhaustive for the parties I've seen, but new parties (especially small / single-cycle ones) pass through verbatim. Check `data/lookups/party-codes.json:by_canonical` to see the current coverage.
- **`election_date` is election day, not certification day.** The SoV file is usually published 2-4 weeks later. We don't track certification date as a separate field.

---

## 5. Future work (good first tasks)

> **See also: [`docs/architecture-review.md`](docs/architecture-review.md)** — a
> tiered audit of this repo against the `data-liberation` skill template
> (concept catalog, reject port, pandera at the boundary, Datasette / Quarto
> / LFS / DocumentCloud publishing surfaces). The items below are the legacy
> backlog; the architecture review is the **organizing document** for the
> next several PRs.

In rough order of value:

1. ~~Fix the 2008/2010 panel-header alignment~~ — done (2026-10): `boco_panel` aligns by position and every candidate reconciles to the file's `Totals` row.
2. **Spot-check 2005/2007/2009 PDF candidate names** against the source PDFs. Vote counts now reconcile to the printed totals and `tests/test_pdf_parser.py` pins golden values per year; names from rotated text still deserve a sampled read.
3. **Add Colorado primary elections** to the source registry. Boulder publishes primary SoVs in even-year June; the SOS publishes statewide primary precinct files too.
4. **Add precinct geographies** as a separate `data/geography/` directory (GeoJSON or shapefile) with a year column so changing precinct boundaries can be joined to historical results.
5. **Golden-output tests per parser.** The `tests/` suite (~115 tests) covers helpers, schema, discovery, and the election-night pipeline; small checked-in fixture workbooks per parser generation would catch silent regressions in the parsers themselves.
6. **Add primary-vs-general party-affiliation tracking** for partisan primaries (the schema already has `party`; needs the primary data to populate it).
7. **Fail the annual-refresh PR on new reconcile mismatches.** The Action now runs `reconcile.py` and puts the mismatch count in the PR body; it doesn't yet fail the job when that count is above 0.
8. **Repo / org setting prerequisite for the Action:** The Action opens a PR via `peter-evans/create-pull-request`. For that to work, the repo (and the org, if it enforces) must have **Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests"** enabled. Without it, the scheduled run fails at the `Open PR` step with `"GitHub Actions is not permitted to create or approve pull requests"`. The workflow has a fallback step that opens an issue containing the same body in that case, but enabling the toggle is the proper fix.
9. **Per-year contest-name canonicalization.** Right now `contest` carries the as-published title; `data/lookups/contest-aliases.json` has patterns but only for top-line offices. A full crosswalk would let analyses group, e.g., "Representative to the 113th Congress" and "Representative to the 114th Congress" without manual regex.

---

## 6. How to add a new election year

1. Add the entry to `BOULDER_COUNTY` or `SECRETARY_OF_STATE` in [`scripts/sources.py`](scripts/sources.py).
2. Add the election day to `ELECTION_DATES` in the same file (use the absolute date — `2026-11-03`, not "next November").
3. Pick a parser route in [`scripts/clean.py`](scripts/clean.py). If the new year is a Boulder XLS/XLSX, it should "just work" via `boco_tidy`. If it's a new file format, add a parser under `scripts/parsers/`.
4. Run `uv run python -m scripts.pipeline --skip-fetch --year <year>`.
5. Check `data/audit/reconciliation.md` — every top-line contest and every contest × candidate key should be `match` or `near_match`, and the structural checks 0. If anything is `mismatch`, find why before publishing.
6. Run `uv run python -m scripts.export_lookups` to refresh the JSON lookups.
7. Update the year row in `docs/data-dictionary.md` § 5 and the README availability table.

---

## 7. How to add a new column to the schema

1. Add it to `COLUMNS` and `DTYPES` in [`scripts/schema.py`](scripts/schema.py).
2. Document it in [`docs/data-dictionary.md`](docs/data-dictionary.md) § 1.
3. Update every parser under `scripts/parsers/` to populate the new column (start with `pd.NA` if the source doesn't provide it).
4. Re-run `scripts.export_lookups`; verify `data/lookups/schema.json` updated.
5. Re-run the pipeline; check `validate()` doesn't surface unexpected nulls.
6. Bump `SCHEMA_VERSION` in `schema.py`.

---

## 8. Where to find things (file index)

| Thing | File |
|---|---|
| Schema definition | [`scripts/schema.py`](scripts/schema.py) |
| URL registry | [`scripts/sources.py`](scripts/sources.py) |
| Upstream discovery | [`scripts/discover.py`](scripts/discover.py) |
| Downloader | [`scripts/fetch.py`](scripts/fetch.py) |
| Cleaning orchestrator | [`scripts/clean.py`](scripts/clean.py) |
| Parsers (per generation) | [`scripts/parsers/`](scripts/parsers/) |
| Audit module | [`scripts/audit.py`](scripts/audit.py) |
| Reconciliation module | [`scripts/reconcile.py`](scripts/reconcile.py) |
| End-to-end driver | [`scripts/pipeline.py`](scripts/pipeline.py) |
| JSON lookup exporter | [`scripts/export_lookups.py`](scripts/export_lookups.py) |
| Test suite | [`tests/`](tests/) (pytest, ~115 tests, runs in ~3s; hermetic — never writes into `data/`) |
| Shared Excel reader | [`scripts/parsers/common.py`](scripts/parsers/common.py) (`read_excel`, `excel_file`) |
| Data dictionary | [`docs/data-dictionary.md`](docs/data-dictionary.md) |
| Filter/pivot recipes | [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md) |
| Methodology notebook | [`Cleaning.ipynb`](Cleaning.ipynb) |
| Annual refresh workflow | [`.github/workflows/annual-sov-refresh.yml`](.github/workflows/annual-sov-refresh.yml) |
| Party-code mapping | [`data/lookups/party-codes.json`](data/lookups/party-codes.json) |
| Yes/No normalization | [`data/lookups/choice-map.json`](data/lookups/choice-map.json) |
| Election dates | [`data/lookups/election-dates.json`](data/lookups/election-dates.json) |
| Source URL registry (JSON) | [`data/lookups/sources.json`](data/lookups/sources.json) |
| Schema (JSON) | [`data/lookups/schema.json`](data/lookups/schema.json) |
| Top-line contest patterns | [`data/lookups/contest-aliases.json`](data/lookups/contest-aliases.json) |
| Reconciliation report | [`data/audit/reconciliation.md`](data/audit/reconciliation.md) (top-line rows in `reconciliation.csv`, contest × candidate rows in `reconciliation-candidates.csv`) |
| Election-night vote counting | [`scripts/vote_counting.py`](scripts/vote_counting.py), parser [`scripts/parsers/boco_vote_counting.py`](scripts/parsers/boco_vote_counting.py), OCR client [`scripts/datalab.py`](scripts/datalab.py) |
| Vote-counting OCR corrections | [`scripts/corrections/vote-counting.csv`](scripts/corrections/vote-counting.csv) |
| Vote-counting QA | [`data/audit/vote-counting.md`](data/audit/vote-counting.md) |
| Per-file audits | [`data/audit/*.md`](data/audit/) |
| Annual refresh workflow | [`.github/workflows/annual-sov-refresh.yml`](.github/workflows/annual-sov-refresh.yml) |
| CI tests workflow | [`.github/workflows/tests.yml`](.github/workflows/tests.yml) |

---

## 9. Common agent failure modes (avoid these)

- **Building a path to a raw SoV by hand.** Boulder SoVs live in `data/original/boulder-county/statement-of-votes/`; always go through `config.original_path(data_source, local_filename)`. The same goes for outputs: harmonized SoV CSVs live in `data/processed/statements-of-votes/` — use `config.sov_csv_path(year, election_type, data_source)`, and `config.STATEMENTS_OF_VOTES` / `config.VOTE_COUNTING` for the dataset folders.
- **Editing `data/original/` instead of the parser.** The raw files are reference. Fix the parser.
- **Adding a parser without updating `scripts/clean.py`'s router.** The orchestrator picks the parser by year; a new parser orphaned outside the router won't run.
- **Hardcoding a path.** Everything should resolve from `REPO_ROOT = Path(__file__).resolve().parents[1]`.
- **Inferring schema from `data/processed/` instead of `scripts/schema.py`.** The schema file is authoritative.
- **Bypassing `add_provenance()`.** Parsers must still attach the provenance columns — they're in the in-memory schema even though the CSV writer strips them. The audit module and the `provenance.csv` sidecar both depend on them.
- **Inferring schema from the CSV files.** Per-year CSVs use `CSV_COLUMNS` (15 cols, no provenance); the canonical `COLUMNS` constant in `schema.py` has all 20. Use `CSV_COLUMNS` when validating a CSV; use `COLUMNS` when validating a parser-output frame.
- **Pretending PDF years are machine-readable.** Their `extraction_quality` is intentionally `pdf_text_layer` so downstream filters can skip them.
- **"Fixing" composite precinct IDs by splitting on comma.** Their vote tallies are reported jointly — splitting would multiply totals.
- **Recreating a `data/cleaned/` or `data/original/output/` directory for "intermediate" outputs.** There are only two homes for data on disk: `data/original/` for immutable raw downloads and `data/processed/` for everything the pipeline produces — one subfolder per dataset (`statements-of-votes/`, `vote-counting/`), with cross-dataset publishing artifacts (`elections.db`, `metadata.yaml`) at its top. The `data/audit/` and `data/lookups/` siblings are read-only artifacts derived from `data/processed/`; do not invent new write targets.

---

## 10. Sanity-check before declaring done

After any non-trivial change, run all six:

```bash
uv sync                                                  # installs pytest + ruff (dev group)
uv run ruff check .                                      # lint (CI enforces it)
uv run pytest                                            # all unit tests
uv run python -m scripts.pipeline --skip-fetch           # rebuilds processed CSVs, PDFs included
uv run python -m scripts.reconcile                       # top-line + contest × candidate totals
uv run python -m scripts.export_lookups                  # refreshes JSON lookups
uv run jupyter nbconvert --to notebook --execute \
    Cleaning.ipynb --output Cleaning.ipynb               # validates notebook
```

If `ruff` or `pytest` fails, or `reconcile` reports any new `mismatch` rows, **stop and investigate** before committing. CI runs ruff and pytest on every push and PR; the annual-refresh workflow also runs reconcile and surfaces the mismatch counts in the PR body.

Filtered runs (`--year`, `--since`, `--source`, `--no-pdf`, `clean`, `reconcile --year`, `vote_counting --election`) only re-parse their subset; the whole-dataset outputs (combined CSV, `provenance.csv`, `rejected.csv`, `summary.md`, the reconciliation report, the election-night CSVs) are rebuilt from every file on disk or upserted by key, so they never shrink to the subset. A full run before committing is still the safest check.

**Output convention:** user-facing progress and results are `print()` to stdout, problems (`WARN …`, `FAIL …`) `print()` to stderr; structlog is for diagnostics only (stderr, key=value text; `ELECTIONS_LOG_FORMAT=json` for JSON). Paths always come from `scripts/config.py`.
