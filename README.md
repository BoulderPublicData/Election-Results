# Election Results

Boulder County and Colorado Secretary of State precinct-level election results,
harmonized into a single tidy long-form dataset spanning **2004-2024**.

Boulder County Elections [publishes](https://bouldercounty.gov/elections/by-year/)
Statements of Votes (SoVs) for primary and general elections in even years and
coordinated elections in odd years. The Colorado Secretary of State
[publishes](https://www.coloradosos.gov/pubs/elections/Results/Archives.html)
precinct-level results for general elections in even years.

This repo:
- pulls those files from upstream,
- harmonizes them into one schema (one row per precinct × contest × candidate),
- audits each year for shape and totals,
- reconciles top-line vote totals against the originals,
- documents every column, every cross-walk, and every known caveat.

> **Maintaining this repo?** Read [`AGENT.md`](AGENT.md) first — it's the architecture brief, gotcha list, and "how to add a new year" guide in one page.

## Quickstart

```bash
# 1. Install (uv handles Python and dependencies)
uv sync

# 2. Run the full pipeline — fetch, clean, audit, reconcile
uv run python -m scripts.pipeline

# 3. Discover newly published years from the upstream pages,
#    then fetch + clean them (handles years missing from sources.py)
uv run python -m scripts.pipeline --discover

# 4. Just clean what's already on disk (faster, no network)
uv run python -m scripts.pipeline --skip-fetch --no-pdf

# 5. Run the test suite
uv run pytest
```

Output lands in [`data/processed/`](data/processed/):
- `{year}-{election_type}-{source}.csv` — per source file (slim 15-column schema)
- `all-elections-tidy.csv` — everything concatenated
- `provenance.csv` — one row per source file with `source_url`, `retrieved_at`,
  `extraction_quality`, `extraction_notes`. Join on `(election_year,
  election_type, data_source)` if you need row-level provenance — see
  [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md).

## Layout

```
.
├── data/                      # everything reproducible from raw + scripts
│   ├── original/              # immutable raw downloads — the ONLY input dir
│   │   ├── boulder-county/    #   one file per published SoV (xls/xlsx/pdf)
│   │   ├── secretary-of-state/
│   │   └── manifest.json      # sha256 + retrieved_at per file
│   ├── processed/             # tidy CSVs (pipeline output) — the ONLY output dir
│   │                          #   per-year .csv + all-elections-tidy.csv
│   │                          #   + provenance.csv sidecar
│   ├── audit/                 # auto-generated audits + reconciliation report
│   └── lookups/               # JSON lookups — party codes, election dates,
│                              #   source registry, schema, contest aliases,
│                              #   precinct-ID lists
├── scripts/                   # pipeline modules — see `scripts/__init__.py`
│   ├── schema.py              # canonical column definitions
│   ├── sources.py             # URL registry, election dates
│   ├── discover.py            # scrapes BoCo + SOS pages for new years
│   ├── fetch.py               # idempotent downloader
│   ├── clean.py               # orchestrator (routes per year/source)
│   ├── audit.py               # summary stats → Markdown
│   ├── reconcile.py           # top-line contest totals vs originals
│   ├── export_lookups.py      # regenerates data/lookups/*.json
│   ├── pipeline.py            # end-to-end driver
│   └── parsers/               # year/source-specific parsers
├── tests/                     # pytest suite (schema, parsers, discovery, …)
├── docs/
│   ├── data-dictionary.md     # what every column means + cross-walks
│   └── filter-pivot-recipes.md  # pandas / tidyverse / Excel recipes
├── Cleaning.ipynb             # rewritten notebook — methodology + worked examples
├── AGENT.md                   # architecture, gotchas, future-agent handbook
├── .github/workflows/
│   ├── annual-sov-refresh.yml  # cron: every Jan 6 14:00 UTC, runs discovery
│   └── tests.yml               # pytest on every push + PR
└── pyproject.toml             # uv-managed env
```

## Data summary

Are the results of individual contests available at the level of precincts in an accessible format?

| Year | Boulder | State | Notes |
|---|---|---|---|
| 2024 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2024/12/2024G-Boulder-County-Amended-Statement-of-Votes.xlsx) | (not yet) | Amended SoV — verify scope before publishing |
| 2023 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2023/12/2023C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx) | ❌ | First Boulder mayoral RCV |
| 2022 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2022/12/2022G-Boulder-County-Official-Statement-of-Votes.xlsx) | ❌ | Composite precincts in places |
| 2021 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2021/11/2021-Boulder-County-Coordinated-Election-Official-Statement-of-Votes-1.xlsx) | ❌ | |
| 2020 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2020/11/2020-Boulder-County-General-Election-Official-Statement-of-Votes.xlsx) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2020/2020GEPrecinctLevelResultsPosted.xlsx) | |
| 2019 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2019/11/2019C-Official-Statement-Of-Votes-SOV.xls) | ❌ | |
| 2018 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2018/11/2018-General-Election-Official-Statement-Of-Votes.xlsx) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2018/2018GEPrecinctLevelResults.xlsx) | |
| 2017 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/11/Results_SOV_Final.xlsx) | ❌ | |
| 2016 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2016-general-election-results-final-sov.xls) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2016/General/2016GeneralTurnoutPrecinctLevel.xlsx) | |
| 2015 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2015-election-sov.xls) | ❌ | Composite precincts in places |
| 2014 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2014-general-election-sov.xls) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2014/2014GeneralPrecinctTurnout.xlsx) | |
| 2013 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2013-election-sov.xls) | ❌ | XLSX mislabeled as `.xls` |
| 2012 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2012-general-election-sov.xls) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2012/2012GeneralPrecinctLevelTurnout.xlsx) | Panel format |
| 2011 | [✅](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2011-election-sov.xls) | ❌ | Panel format |
| 2010 | ⚠️ [partial](https://assets.bouldercounty.gov/wp-content/uploads/2017/09/2010-general-sov.xls) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2010/general/2010GeneralPrecinctTurnout.xlsx) | Merged-cell panels limit extraction |
| 2009 | ⚠️ [PDF](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2009-election-sov.pdf) | ❌ | pdfplumber extract |
| 2008 | ⚠️ [partial](https://assets.bouldercounty.gov/wp-content/uploads/2017/12/2008-general-election-sov.xls) | [✅](https://www.coloradosos.gov/pubs/elections/Results/2008/2008GeneralPrecinctTurnout.xlsx) | Merged-cell panels limit extraction |
| 2007 | ⚠️ [PDF](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2007-election-sov.pdf) | ❌ | pdfplumber extract |
| 2006 | ❌ | [✅](https://www.coloradosos.gov/pubs/elections/Results/2006/2006GeneralPrecinctBallotsCast.xlsx) | |
| 2005 | ⚠️ [PDF](https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2005-election-sov.pdf) | ❌ | pdfplumber extract |
| 2004 | ❌ | [✅](https://www.coloradosos.gov/pubs/elections/Results/2004/2004GeneralPrecinctBallotsCast.xlsx) | |

✅ machine-readable extraction · ⚠️ partial / PDF-extracted (verify before publishing) · ❌ not available upstream

## How to use the data

Start with [`docs/filter-pivot-recipes.md`](docs/filter-pivot-recipes.md) — side-by-side examples for pandas, tidyverse, and Excel. Full schema in [`docs/data-dictionary.md`](docs/data-dictionary.md).

Machine-readable lookups (regenerated by [`scripts/export_lookups.py`](scripts/export_lookups.py)):

- [`data/lookups/party-codes.json`](data/lookups/party-codes.json) — party name normalization
- [`data/lookups/choice-map.json`](data/lookups/choice-map.json) — Yes/No variant normalization
- [`data/lookups/election-dates.json`](data/lookups/election-dates.json) — election days per year
- [`data/lookups/sources.json`](data/lookups/sources.json) — source URL registry
- [`data/lookups/schema.json`](data/lookups/schema.json) — column/dtype reference
- [`data/lookups/contest-aliases.json`](data/lookups/contest-aliases.json) — top-line contest pattern matchers

## How we know the data is right

[`scripts/reconcile.py`](scripts/reconcile.py) re-opens each original file, sums top-line contest totals, and compares them to the processed CSVs. The report lands at [`data/audit/reconciliation.md`](data/audit/reconciliation.md); 149 of the 150 cross-checks currently `match` exactly, the remaining row is a `not_reconcilable` panel/PDF year. Any new `mismatch` is a regression — investigate before merging.

## Annual refresh

A [GitHub Action](.github/workflows/annual-sov-refresh.yml) runs every **January 6** (federal Electoral College certification day). The job:

1. **Discovers** newly published SoV files by scraping [bouldercounty.gov/elections/results/](https://bouldercounty.gov/elections/results/) and [coloradosos.gov/pubs/elections/Results/Archives.html](https://www.coloradosos.gov/pubs/elections/Results/Archives.html). Anything not already in [`scripts/sources.py`](scripts/sources.py) gets added at runtime.
2. **Fetches** the files into `data/original/{source}/` (and records sha256 + retrieved_at in `data/original/manifest.json`).
3. **Cleans, audits, and reconciles** against the originals.
4. **Opens a PR** with the new files. If the repo doesn't allow Actions to open PRs, falls back to opening an issue with the same body.

You can run it manually any time via the **Actions** tab → **Annual SOV refresh** → *Run workflow*. The `--discover` flag also works from the CLI:

```bash
uv run python -m scripts.discover                       # show what's new upstream
uv run python -m scripts.fetch --discover --year 2025   # fetch a newly-discovered year
uv run python -m scripts.pipeline --discover            # full end-to-end with discovery
```

## Testing

The pytest suite runs on every push and PR via [`.github/workflows/tests.yml`](.github/workflows/tests.yml). It covers schema contracts, per-parser helpers, the discovery classifier (with cached HTML fixtures so it works offline), source-registry shape, and a sample of committed processed CSVs.

```bash
uv run pytest                  # run everything (~2 seconds)
uv run pytest tests/test_discover.py -v
```

## Known limitations

- **2008 / 2010 Boulder SoV panel format** — these XLS files use merged header cells so candidate-column ↔ data-column alignment is irregular. The pipeline captures the major statewide and county contests cleanly; precinct-level detail for some down-ballot contests is reduced. Tracked in [`docs/data-dictionary.md §4.2`](docs/data-dictionary.md).
- **2005 / 2007 / 2009 PDF extraction** — `extraction_quality = pdf_text_layer` but contest titles are not reliably extracted from the surrounding narrative text. Treat as provisional until manually backfilled.
- **2024 Boulder SoV** — only 66 rows of local races (Town of Superior, etc.). Federal/state-level Boulder results may not be in the published file; the SOS 2024 file will fill the gap when published.
- **`Cleaning.ipynb` rewrite** preserves the methodology of the original notebook but no longer re-implements every per-year transform — those live in `scripts/parsers/` now.

## License

[`LICENSE`](LICENSE) — MIT.
