# Architecture review against the data-liberation skill

Date: 2026-05-26
Reviewer: Brian Keegan + Claude

The [data-liberation skill](https://github.com/brianckeegan/claude-skills) crystallizes the
patterns from PUDL, the IPEDS pipeline, and the rest of the Boulder Public Data family
into a single template. This document audits the **current Election-Results repo**
against that template and proposes a tiered set of changes, ranked by value-to-effort.

Use this as the working agenda for what to land next. Each tier lands as its own PR.

---

## TL;DR

The repo **already implements 4 of the skill's 6 phases cleanly**: Survey (README + Cleaning.ipynb), Scaffold (matching layout), Extract (per-vintage parsers + idempotent fetch), Tidy (15-column slim CSVs + provenance sidecar), Audit (audit + reconcile). The two gaps are:

1. **Publish** is entirely missing — no Datasette, no Quarto site, no Git LFS, no DocumentCloud.
2. **A handful of skill conventions** (concept catalog, reject port, pandera at the boundary, central `config.py`, AGENTS.md naming, DuckDB recipes) are below-the-bar.

Tier 1 closes the easy gaps in a single afternoon. Tier 2 is a week's work and yields a much more robust pipeline. Tier 3 is the Publish phase — the largest scope but also where the project goes from "an internal harmonized dataset" to "a public civic asset with a queryable API and a docs site."

---

## What's already aligned with the skill

| Skill convention | Current state |
|---|---|
| Six-phase workflow (Survey → … → Publish) | 4 of 6 phases implemented end-to-end |
| Immutable originals under `data/original/` | ✅ Codified with `manifest.json` + sha256 |
| Tidy long format as primary storage | ✅ 15-column slim CSV; combined `all-elections-tidy.csv` |
| Per-extract (not per-row) provenance | ✅ `data/processed/provenance.csv` sidecar |
| Per-vintage parsers under `scripts/parsers/` | ✅ `boco_tidy.py`, `boco_panel.py`, `boco_pdf.py`, `sos.py` |
| `Source` dataclass + registry | ✅ `scripts/sources.py:Source` + `ALL_SOURCES` |
| Discovery scraper | ✅ `scripts/discover.py` for new vintages on upstream pages |
| Reconciliation against authoritative totals | ✅ `scripts/reconcile.py` — 153 cross-checks, 0 mismatches |
| Audit module producing diff-able Markdown | ✅ `scripts/audit.py` → `data/audit/summary.md` |
| Single end-to-end driver | ✅ `scripts/pipeline.py` |
| JSON lookups exported from Python source-of-truth | ✅ `scripts/export_lookups.py` → 5 JSON files |
| pytest suite + CI workflow | ✅ 74 tests + `.github/workflows/tests.yml` |
| Cron-driven refresh PR | ✅ `.github/workflows/annual-sov-refresh.yml` (every Jan 6) |
| Data dictionary + filter-pivot recipes | ✅ `docs/data-dictionary.md` + `docs/filter-pivot-recipes.md` |
| Movement-context note | ✅ README mentions BoulderPublicData |
| Two-home rule (only `data/original/` + `data/processed/` are written) | ✅ Codified in AGENTS.md guardrails |

---

## What's missing or below-the-bar

### Tier 1 — high value, low effort (≤ 1 day)

These are small, mostly cosmetic, but the skill calls them out as defended conventions.

**T1.1 — Rename `AGENT.md` → `AGENTS.md` (plural).** The skill's template uses `AGENTS.md` (the convention that's emerging across Anthropic / OpenAI agent tooling). One file rename + ~6 references to update (README, docstrings, the rename note itself).

**T1.2 — Add a reject port.** The 9-step parser-time pipeline ends with "validation + reject port", but 4 of 5 parsers currently `dropna()` silently:

- `boco_panel.py` — drops on `[precinct_id, contest, candidate_or_option]`
- `boco_pdf.py` — page-level skip counter only in extraction_notes
- `boco_tidy.py` — silent `dropna()`
- `sos.py` — silent `dropna()` on 4 columns

Land: each parser routes rejected rows to a shared in-memory buffer; the pipeline writes the union to `data/audit/rejected.csv` with columns `(source_file, row_index, reason, raw_row_json)`. The audit report counts rejections per source. Already there is a column for it conceptually — `extraction_notes` carries page-level skip counts; this just makes row-level rejection durable and joinable.

**T1.3 — Add DuckDB column to `docs/filter-pivot-recipes.md`.** The skill specifically defends DuckDB as the third column because it "queries the CSV directly with no load step, runs SQL the consumer can paste straight into Datasette's SQL editor." Currently the file has pandas + tidyverse + Excel. Add a 4th column or replace Excel with DuckDB. Recommend: keep Excel (still the dominant tool for non-technical readers), add DuckDB as a 4th column.

**T1.4 — Make movement-context lineage explicit in README.** The skill emphasizes naming Sunlight Foundation → PDF Liberation → MuckRock → PUDL → BoulderPublicData as the inheritance line. Currently the README mentions BoulderPublicData but doesn't trace the lineage. Add a 4-line "Lineage" paragraph at the top.

**Cost:** ~2-4 hours total. Mostly text + one parser refactor.

---

### Tier 2 — medium value, medium effort (3-5 days)

These improve robustness and reduce coupling — worth doing before adding more sources.

**T2.1 — Add `scripts/config.py`.** Currently `REPO_ROOT` is duplicated across 6 modules and HTTP defaults (User-Agent, timeout) live in `fetch.py` only. The skill prescribes:

```python
# scripts/config.py
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"
ORIGINAL = DATA / "original"
PROCESSED = DATA / "processed"
AUDIT = DATA / "audit"
LOOKUPS = DATA / "lookups"

HTTP_TIMEOUT = 60
HTTP_USER_AGENT = "Election-Results-Pipeline/0.1 (+https://github.com/BoulderPublicData/Election-Results) research/civic-data"

# Re-export SOURCES from sources.py for the canonical "where do I look up …" path
from .sources import ALL_SOURCES as SOURCES  # noqa: F401
```

Then 6 modules collapse to `from .config import ORIGINAL, PROCESSED, AUDIT, LOOKUPS`.

**T2.2 — Add `requests-cache` + `tenacity`.** Currently `fetch.py` and `discover.py` use plain `requests.get(..., timeout=60)` with no retry and no caching:

- A flaky upstream returns 502 → fetch fails and the cron-PR is empty.
- A re-run of the pipeline during development re-downloads files we just downloaded.

`requests-cache` gives us a SQLite-backed HTTP cache (huge dev-time win); `tenacity` gives us exponential backoff retries (production robustness). The skill prescribes both. Add `requests-cache>=1.2` and `tenacity>=9.0` to `pyproject.toml`.

**T2.3 — Migrate validation to `pandera` at the pipeline boundary.** The current `schema.validate()` is hand-rolled Python that returns problem strings. The skill prescribes pandera schemas at the boundary because:

1. Pandera schemas double as machine-readable documentation (export to JSON, render to Markdown).
2. They catch dtype drift the hand-rolled validator misses.
3. They integrate with pytest cleanly.

Migration: `scripts/schema.py:validate()` returns a `pa.errors.SchemaError` instead of a list; existing callers wrap with `try / except` and accumulate; tests use `pa.testing.check_schema_equality` to detect drift.

**T2.4 — Add a concept catalog (`scripts/concepts.py`).** The skill's most-defended convention for multi-source projects. The repo currently harmonizes Boulder County + Colorado SOS but the cross-source contest mapping is implicit (it lives in regex patterns in `data/lookups/contest-aliases.json`). A concept catalog makes it explicit and adds the **caveats** field that's the whole point:

```python
# scripts/concepts.py
@dataclass
class Concept:
    name: str           # "presidential_electors"
    description: str
    boulder_county: list[str]   # contest titles as they appear in BoCo files
    secretary_of_state: list[str]
    caveats: str        # what's NOT comparable: e.g. "Boulder lists the
                        # full elector slate ('Biden/Harris'); SOS lists
                        # the candidate alone ('Joseph R. Biden'). Vote
                        # totals are equivalent but the candidate string
                        # cannot be joined directly."

CONCEPTS = [
    Concept(
        name="presidential_electors",
        description="Electors for President and Vice President of the United States.",
        boulder_county=["Presidential Electors"],
        secretary_of_state=["President of the United States/Vice President"],
        caveats="Boulder presents the elector slate as a single candidate "
                "('Joseph R. Biden / Kamala D. Harris'); SOS lists the "
                "presidential candidate alone. Vote totals match exactly when "
                "aggregated; the candidate strings cannot be joined directly.",
    ),
    # ~20 more
]
```

Bonus: `scripts/export_lookups.py` exports `concepts.json` automatically.

**T2.5 — Consolidate CLI to `python -m scripts.pipeline <subcommand>`.** Currently 7 console scripts are exposed (`elections-fetch`, `elections-clean`, `elections-audit`, `elections-pipeline`, `elections-discover`, `elections-reconcile`, `elections-export-lookups`). The skill prescribes a single CLI with subcommands:

```bash
elections-pipeline discover
elections-pipeline fetch --year 2026
elections-pipeline clean --since 2020
elections-pipeline audit
elections-pipeline reconcile
elections-pipeline export-lookups
elections-pipeline run    # the default end-to-end driver
```

Keep the individual `python -m scripts.fetch` etc. as backwards-compat shims for one version; deprecate the standalone `elections-*` entries in v0.2.0.

**T2.6 — `structlog` for the pipeline's print/stderr.** Currently the pipeline writes mixed `print()` and `print(..., file=sys.stderr)` output that is hard to parse from CI. `structlog` gives JSON output in CI and pretty output in interactive runs, key-value lookups (e.g. filter for `event="reconcile_mismatch"`), and bound contexts so every line from a parser carries `source` + `vintage`.

**Cost:** ~3-5 days total. Each item is its own PR.

---

### Tier 3 — large effort, large value (2-4 weeks)

The Publish phase — what turns the repo from "a harmonized dataset I can clone and grep" into "a public civic resource."

**T3.1 — Datasette + SQLite (`scripts/publish.py build` + `deploy`).** The headline addition. `sqlite-utils` builds a single SQLite from `data/processed/`; `datasette publish vercel|fly|cloudrun` ships it as a public read-only query interface with:

- SQL editor (readers can write their own queries)
- Faceting on `election_year`, `data_source`, `contest_type`, `party`, `precinct_id`
- Optional full-text search on `contest` + `candidate_or_option`
- JSON API at `/elections-results.json` for journalism + civic dev
- Foreign-key link from the data table to `provenance.csv` so readers can trace any row back to its source URL
- Per-column documentation rendered from `docs/data-dictionary.md` (via auto-generated `metadata.yaml`)
- (Optional) Datasette Agent — conversational LLM interface released alpha May 2026

The "Baked Data" architecture (rebuild SQLite on every deploy; no app-layer writes) is well-suited here because the data only changes on the annual refresh PR. Hosting: Vercel or Cloud Run both have free tiers that fit a ~50MB SQLite.

**T3.2 — Quarto docs site on GitHub Pages.** Move `docs/*.md` to `docs/*.qmd` and add a `_quarto.yml`. Quarto adds executable code blocks (so the filter-pivot recipes actually RUN against `all-elections-tidy.csv` and verify), proper navigation, and TOCs. Render via `quarto-dev/quarto-actions/publish@v2` on every push to main. URL: `boulderpublicdata.github.io/election-results/`.

Notable: the existing Cleaning.ipynb (the rewritten public-data-oped notebook) becomes a Quarto page directly. No content rewrite needed.

**T3.3 — Git LFS for source PDFs + the combined CSV.** The 3 source PDFs (2005, 2007, 2009) are ~10MB each; the combined `all-elections-tidy.csv` is 49MB. Currently committed (PDFs) or gitignored (combined). LFS lets us commit both without bloating the git history. `.gitattributes`:

```
*.pdf filter=lfs diff=lfs merge=lfs -text
data/processed/all-elections-tidy.csv filter=lfs diff=lfs merge=lfs -text
```

**Architectural constraint** (the skill flags this): LFS does NOT work with GitHub Pages. So the Quarto site links out to Datasette + to GitHub Releases for full-file downloads; it does not directly embed LFS-tracked files. This is fine — readers query via Datasette, download via Releases.

**T3.4 — DocumentCloud for the source PDFs.** Uploads the 3 Boulder coordinated-election PDFs (2005, 2007, 2009) to DocumentCloud, which gives:

- Reader-facing OCR (currently we rely on the embedded text layer; DocumentCloud re-OCRs and indexes)
- Per-page permalinks readers can cite
- Annotations on specific pages (e.g. "this is where the contest title goes" for future agents)
- Embeddable iframes for the Quarto site
- A chain-of-custody from every `provenance.csv` row to a specific DocumentCloud document URL

This is the lowest-priority item — only 3 PDFs and they're already text-extractable.

**Cost:** 2-4 weeks total. T3.1 alone is ~1 week (SQLite build + Datasette deploy + canned queries + metadata wiring). T3.2 is ~2 days. T3.3 is ~half a day. T3.4 is ~1 day.

---

## Out of scope (and why)

| Item | Reason |
|---|---|
| **Refactor `Source` to ABC with `discover()` + `ingest()` methods** | Skill prescribes this for multi-source bootstrapping. Current `Source = @dataclass(frozen=True)` + `discover.py` doing the discovery + `parsers/` doing the ingestion is a clean separation already. Refactoring would touch every parser for no behavioral change. |
| **Per-cell provenance** | Skill flags it as "opt-in for audit-grade work." Per-extract provenance (the current sidecar) is sufficient for election results. |
| **Tidy-long-on-top-of-wide-storage (the Cast Vote Record exception)** | The repo doesn't deal with ballot-level CVR data. |
| **PII redaction** | Election results are aggregated to precinct level; no PII present. |
| **Renaming `Cleaning.ipynb` → `docs/methodology.qmd`** | The notebook is the methodology document; renaming it to .qmd is part of T3.2 (Quarto site) — already covered. |
| **Tier 3 reordering** | T3.1 (Datasette) is the clear headline; T3.2-T3.4 can land in any order after. |

---

## Recommended path

If we're allocating budget, I'd land:

- **Week 1**: Tier 1 (one PR per item, or one combined PR — these are all ≤ 50 lines each)
- **Week 2-3**: Tier 2.1, 2.2, 2.4, 2.5 (config consolidation, retries, concept catalog, CLI subcommands)
- **Week 4-5**: Tier 2.3, 2.6 (pandera migration + structlog) — riskier, do after config consolidation lands
- **Month 2**: Tier 3.1 + 3.2 (Datasette + Quarto) — the public-facing additions
- **Month 3** (only if there's appetite): Tier 3.3 + 3.4 (LFS + DocumentCloud)

The natural breakpoints are Tier 1 (cosmetic + one structural — safe to land in a single PR), then everything in Tier 2 as separate PRs gated on the previous, then Tier 3 as a "new chapter" once the analytical foundation is locked.

---

## Tracking

This review is durable — when a tier ships, mark its row in the tables above with a date and the merged PR number. When the skill itself updates (`brianckeegan/claude-skills`), re-run this audit and bump the date at the top.
