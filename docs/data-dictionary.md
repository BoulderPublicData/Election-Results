# Data dictionary

This file is the authoritative description of every column in `data/processed/`.
It also documents the cross-walks between Boulder County SoV files, Colorado
Secretary of State precinct-results files, and the harmonized long-form schema
used throughout `data/processed/`.

Schema version: **1.1.0** (see [`scripts/schema.py`](../scripts/schema.py))

---

## 1. Schema (canonical columns)

The harmonized in-memory schema is **20 columns**. The **per-year CSV files** under
`data/processed/` hold a slim 15-column view — the 5 provenance columns (#16-20
in the table below) are redundant per-row (every row from a single source file
has the same value) so they live in a sidecar:

```
data/processed/
├── 2020-general-boulder-county.csv     ← 15-column slim view
├── …                                    ← one slim CSV per source file
├── all-elections-tidy.csv              ← combined slim CSV
└── provenance.csv                      ← one row per source file; carries
                                          the 5 provenance columns
```

One row in a per-year CSV represents one
**(election_year × jurisdiction × precinct × contest × candidate-or-option)** tally.
Join `provenance.csv` on `(election_year, election_type, data_source)` if you
need the source URL or retrieved-at timestamp for a row.

| # | Column | Type | Required | Description |
|---|---|---|---|---|
| 1 | `election_year` | int (Int16) | yes | Calendar year the election was held. |
| 2 | `election_date` | string (ISO date) | yes | Election day (`YYYY-MM-DD`). |
| 3 | `election_type` | string | yes | One of `general` (even-year November), `primary` (even-year June), `coordinated` (odd-year November). |
| 4 | `data_source` | string | yes | `boulder_county` or `secretary_of_state` — which agency published the file. |
| 5 | `jurisdiction_level` | string | yes | `county` (Boulder County SoV) or `state` (SOS file, Boulder rows only). |
| 6 | `jurisdiction_name` | string | yes | Always `Boulder County` in this project. |
| 7 | `precinct_id` | string | yes | The 10-digit Boulder/Colorado precinct identifier as a **string** (preserves leading zeros). Composite IDs (2015, 2022) appear as `"2181007800, 2181207403"` — see [§4.3](#43-composite-precinct-ids). |
| 8 | `precinct_name` | string | no | Short form (typically 3-digit) precinct code. Null for SOS rows and for older Boulder files that didn't ship a separate short code. |
| 9 | `contest` | string | yes | Contest title as published. May contain trailing classifiers like `(CONSTITUTIONAL)`, `(STATUTORY)`. |
| 10 | `contest_type` | string | yes | One of `candidate`, `measure`, `retention`, `recall`, `ranked_choice`. See [§3](#3-contest-types). |
| 11 | `candidate_or_option` | string | yes | Candidate name OR `Yes`/`No` OR (for RCV) `Candidate Name \| Round N`. Choice labels are canonicalized — see [§2.2](#22-choice-normalization). |
| 12 | `party` | string | no | Party affiliation, normalized to 3-letter codes where possible (`DEM`, `REP`, `LBR`, `GRN`, `UAF`, …). Null for measures, retentions, and Boulder files that don't ship a Party column. See [§2.3](#23-party-normalization). |
| 13 | `votes` | int (Int64) | usually | Vote tally for this row. **May be negative for RCV intermediate rounds** (votes transferring away from an eliminated candidate). |
| 14 | `active_voters` | int (Int64) | no | Active registered voters in the precinct at the time of the election. Boulder SoVs only. Null on SOS rows. |
| 15 | `ballots_cast` | int (Int64) | no | Ballots cast in the precinct. Boulder SoVs only. Null on SOS rows (SOS files don't report ballot totals). |
| 16 | `source_file` | string | sidecar | **Provenance — sidecar only.** The local filename of the raw download (e.g., `2020-general-sov.xlsx`). |
| 17 | `source_url` | string | sidecar | **Provenance — sidecar only.** The canonical upstream URL. |
| 18 | `retrieved_at` | string (ISO UTC) | sidecar | **Provenance — sidecar only.** Timestamp when the raw file was downloaded by `scripts/fetch.py` (or the file's mtime if downloaded by hand). |
| 19 | `extraction_quality` | string | sidecar | **Provenance — sidecar only.** `machine_readable` (XLS/XLSX), `pdf_text_layer` (pdfplumber-extracted from text-layer PDF), `pdf_ocr` (reserved), `manual` (reserved). |
| 20 | `extraction_notes` | string | sidecar | **Provenance — sidecar only.** Free-text caveats from the parser — composite-ID flags, RCV mechanics, skipped panels, etc. |

Columns marked **sidecar** live in `data/processed/provenance.csv` rather than in every row of every per-year CSV. They're constant per source file, so duplicating them on every row would inflate file sizes ~3× for no information gain. The pipeline writes both files together so they stay in sync.

---

## 2. Value normalization

### 2.1 Precinct IDs

Boulder uses 10-digit precinct numbers like `2181007800` (county-state-precinct format) and a "short" form like `800` (last three digits). We treat the 10-digit form as the canonical `precinct_id`. The short form is `precinct_name` when published, otherwise null.

`precinct_id` is always a **string** so leading zeros are preserved.

### 2.2 Choice normalization

The published files use several Yes/No variants. We canonicalize:

| Source value | Canonical |
|---|---|
| `Yes`, `yes`, `YES`, `Y`, `Yes/Sí`, `Yes/For`, `For` | `Yes` |
| `No`, `no`, `NO`, `N`, `No/Against`, `Against` | `No` |

Candidate names are stripped of whitespace but otherwise left as-published. Future cleanups (e.g., `John McCain / Sarah Palin` ↔ `McCain/Palin`) are out of scope.

### 2.3 Party normalization

The SOS uses full names in 2012+ (`Democratic Party`, `Republican Party`) and 3-letter codes in 2004-2010 (`DEM`, `REP`). Boulder mixes both. We canonicalize to the SOS codes where the mapping is unambiguous:

| Canonical | Common source variants |
|---|---|
| `DEM` | `Democratic`, `Democrat`, `Democratic Party`, `Dem` |
| `REP` | `Republican`, `Republican Party`, `Rep` |
| `LBR` | `Libertarian`, `Libertarian Party`, `Lib` |
| `GRN` | `Green`, `Green Party` |
| `UAF` | `Unaffiliated` |
| `ACN` | `American Constitution`, `American Constitution Party` |
| `AVP` | `Approval Voting Party` |
| `AIP` | `American Independent`, `American Independent Party` |
| `CON` | `Constitution`, `Constitution Party` |
| `BTP` | `Boston Tea`, `Boston Tea Party` |
| `WI`  | `Write-In`, `Write In`, `Write-in` |
| `IND` | `Independent`, `Independent / Republican` |
| `NP`  | `Non Partisan`, `Non-Partisan`, `Nonpartisan` |

Parties not in the map pass through verbatim — never silently dropped. Add new mappings in [`scripts/parsers/common.py`](../scripts/parsers/common.py) (`PARTY_MAP`).

---

## 3. Contest types

`contest_type` is inferred from the `contest` title and `candidate_or_option` value:

| Rule | contest_type |
|---|---|
| Title contains `Recall` | `recall` |
| Choice ∈ {`Yes`, `No`} AND title matches a retention/judicial cue (`Retention`, `Justice of the`, `District Judge`, `Supreme Court`, etc.) | `retention` |
| Choice ∈ {`Yes`, `No`} | `measure` |
| Otherwise | `candidate` |

The 2023 Boulder coordinated election has a dedicated RCV sheet for Boulder Mayor (the first instant-runoff election in city history). RCV rows are flagged `ranked_choice` and the candidate is suffixed with the round number — e.g. `Aaron Brockett | Round 1`, `Aaron Brockett | Round 2`, `Aaron Brockett | Final` — so each round is its own row but groups cleanly when filtering on the candidate prefix.

---

## 4. Cross-walks (source columns → schema)

### 4.1 Boulder County tidy years (2013-2024)

These files are already long-form. Column names vary by year — the parser
canonicalizes them after collapsing embedded whitespace/newlines.

| Schema column | 2013-2014 | 2015 | 2016 | 2017 | 2018-2019 | 2020 | 2021 | 2022 | 2023-2024 |
|---|---|---|---|---|---|---|---|---|---|
| `precinct_id` | `Precinct Name` | `Precinct Name` (long) | `Precinct Name` (long) | `Precinct Name` (long) | `Precinct Name` (long) | `Precinct Name` (long) | `Precinct Name` (long) | `Precinct Name (Long)` | `Precinct Number` |
| `precinct_name` | — | `Precinct Name (Short)` | `Precinct Name (Short)` | `Precinct Name (Short)` | `Precinct Name Short` | `Precinct Name (Short)` | `Precinct Name (Short)` | `Precinct Name (Short)` | `Precinct Code` |
| `contest` | `Contest Title` | `Contest Title` | `Contest Title` | `Contest Title` | `Contest Title` | `Contest Name` | `Contest Title` | `Contest Title` | `Contest Title` |
| `candidate_or_option` | `Choice Name` | `Choice Name` | `Choice Name` | `Choice Name` | `Choice Name` | `Choice Name` | `Choice Name` | `Choice Name` | `Choice Name` (or `Candidate Name` in 2023 RCV) |
| `party` | `Party` | `Party` | — | — | `Party` (2018) / — (2019) | `Party` | — | `Party` | — |
| `active_voters` | `Active Voters` | `Active Voters` | `Active Voters` | `Active Voters` | `Active Voters` | `Active Voters` | `Active Voters` | `Active Voters` | `Active Voters` |
| `ballots_cast` | `Total Ballots` | `Total Ballots` | `Total Ballots` | `Total Ballots` | `Total Ballots` | `Total Ballots` | `Total Ballots` | `Total Ballots` | `Total Ballots` |
| `votes` | `Total Votes` | `Total Votes` | `Total Votes` | `Total Votes` | `Total Votes` | `Total Votes` | `Total Votes` | `Total Votes` | `Total Votes` |

Columns not used: `ContestSeqNbr`, `CandSeqNbr`, `PctSeqNbr`, `Sequence`, `ContestID`, `IsCurrent`, `Total Under Votes`, `Total Over Votes`, `Total Undervotes`, `Total Overvotes`. (Under/over votes are intentionally dropped; if you need them, reach into the `data/original/` file.)

### 4.2 Boulder County panel years (2008, 2010, 2011, 2012)

These XLS files predate the modern tidy export. Results are reported as repeating "panels": a contest title row, a header row whose first cell is `Precinct`, then per-precinct rows with vote counts spread across candidate columns. The parser walks the sheet, finds each panel, and melts wide → long. See [`scripts/parsers/boco_panel.py`](../scripts/parsers/boco_panel.py).

**Known limitation:** 2008 and 2010 use merged header cells where each candidate's column header spans multiple data columns. The resulting alignment between header positions (15, 17, 19, …) and data positions (12, 13, 14, …) is irregular and not reliably extractable with a generic walker. The pipeline emits the major contests with reduced row counts (~2,500-3,000 rows vs ~75,000 expected); analyses needing precinct × candidate detail for 2008/2010 should consult the original XLS until this is improved. Tracked as a follow-up.

### 4.3 Composite precinct IDs

In **2015** and **2022**, Boulder County reported some precincts jointly because turnout in individual sub-precincts was small enough to risk voter privacy. These rows have comma-joined IDs:

```
precinct_id = "2181007800, 2181207403"
precinct_name = "800, 403"
```

Vote tallies are for the **combined** unit. To match these against single-precinct geography, split the comma-separated IDs into a one-to-many lookup. The parser flags these in `extraction_notes`.

**Source anomaly — 2023 City of Louisville City Council Ward 2.** The 2023 SoV reports this contest under two *overlapping* composite units, `2181207201,2181207202` and `2181207202,2181207500`, with near-identical tallies (Fahey 184 / 183, Colbert 234 / 234, 458 ballots each). Summed as published, the SoV gives 1,602 / 1,441; without the `202,500` row it gives 1,419 / 1,207 — exactly the county's final election-night web totals (§8). It looks like a double-listed tally in the published file, but the data is left as published (never split or drop composite rows on a guess). It is the only contest in the 2015, 2022 or 2023 files where one precinct appears in two reporting units.

### 4.3a Property-owner / landowner pseudo-precincts

Special-district contests can include ballots from non-resident property owners. The SoV reports them on a row whose precinct code is `Property Owner` (2023, 2025) or `Landowner` (2015) instead of a real precinct. They count toward the certified totals, so they are kept with `precinct_id = "Property Owner"` (or `Landowner`) and flagged in `extraction_notes`. They have no precinct geography — exclude them before a spatial join, but keep them when summing contest totals. (Before 2026-10 the 2023/2025 rows were rejected for a missing `precinct_id`, which undercounted e.g. 2023 Nederland Eco Pass 6A by 101 Yes / 43 No.)

### 4.4 PDF years (2005, 2007, 2009)

These are 100+-page coordinated-election Canvass Reports published only as PDFs. They have a text layer, so `scripts/parsers/boco_pdf.py` reads them with **pdfplumber** (pure Python, no JVM). Contest titles come straight from the page text; candidate names are reconstructed by clustering rotated `upright=False` words by x-coordinate and reversing their characters.

Rows from PDF years carry:
- `extraction_quality = "pdf_text_layer"`
- `contest = "<actual title from page>"` (e.g., `City of Boulder Council Candidates`, `Referendum C`)
- `extraction_notes` summarizing pages parsed/skipped and reminding analysts to spot-check against the source PDF.

These years remain **provisional**: while contest names, candidate names, and per-precinct vote counts now extract reliably, the PDF layout is irregular page-to-page, so verify any precinct-level claim against the source before publishing.

### 4.5 Colorado SOS files (2004-2020)

Two generations of file:

**2004-2008:** 9 columns. Single `Votes` column. County names uppercase with trailing whitespace.

| Schema column | SOS column |
|---|---|
| `precinct_id` | `Precinct` |
| `contest` | `Office/Ballot Issue` |
| `candidate_or_option` | `Candidate/Yes or No` |
| `party` | `Party` |
| `votes` | `Votes` |
| (filter) | `County == "BOULDER"` (after strip+upper) |

**2010:** Same as 2004-2008 but with `Office/Question` instead, plus per-vote-method columns (`PollVotes`, `MailVotes`, `EarlyVotes`, `ProvVotes`).

**2012-2020:** 11 columns. Candidate votes vs. Yes/No votes in separate columns.

| Schema column | SOS column |
|---|---|
| `precinct_id` | `Precinct` |
| `contest` | `Office/Issue/Judgeship` |
| `candidate_or_option` (candidate row) | `Candidate` |
| `candidate_or_option` (measure row) | `Yes` or `No` (synthesized from column name) |
| `party` | `Party` |
| `votes` (candidate row) | `Candidate Votes` |
| `votes` (measure Yes row) | `Yes Votes` |
| `votes` (measure No row) | `No Votes` |
| (filter) | `County == "BOULDER"` (after strip+upper) |

The SOS publishes **only candidate vote totals**, never ballots-cast or active-voter counts. `active_voters` and `ballots_cast` are null on every SOS row.

### 4.6 Election certification dates

`election_date` is set from a small table in [`scripts/sources.py`](../scripts/sources.py) (`ELECTION_DATES`). It records election day, not the certification date. Boulder County typically certifies its SoV ~3 weeks after election day; the file `retrieved_at` timestamp captures when we pulled the latest copy.

---

## 5. Per-year audits

The audit is generated by [`scripts/audit.py`](../scripts/audit.py) and refreshed on every pipeline run. The full per-year summary lives at [`data/audit/summary.md`](../data/audit/summary.md) and per-file fragments at `data/audit/{stem}.md`.

Quick reference (post-pipeline run, 2026-05-23):

| Year | Source | Election | Rows | Contests | Precincts | Quality |
|---|---|---|---|---|---|---|
| 2005 | Boulder | coordinated | _PDF — see audit_ | _PDF_ | _PDF_ | `pdf_text_layer` |
| 2007 | Boulder | coordinated | _PDF — see audit_ | _PDF_ | _PDF_ | `pdf_text_layer` |
| 2008 | Boulder | general | 2,528 | 6 | 236 | `machine_readable` ⚠ partial |
| 2008 | SOS | general | 24,856 | 43 | 239 | `machine_readable` |
| 2009 | Boulder | coordinated | _PDF — see audit_ | _PDF_ | _PDF_ | `pdf_text_layer` |
| 2010 | Boulder | general | 2,868 | 8 | 236 | `machine_readable` ⚠ partial |
| 2010 | SOS | general | 18,196 | 27 | 240 | `machine_readable` |
| 2011 | Boulder | coordinated | 6,279 | 49 | 241 | `machine_readable` |
| 2012 | Boulder | general | 16,771 | 46 | 242 | `machine_readable` |
| 2012 | SOS | general | 17,252 | 22 | 234 | `machine_readable` |
| 2013 | Boulder | coordinated | 4,783 | 103 | 246 | `machine_readable` |
| 2014 | Boulder | general | 20,307 | 58 | 234 | `machine_readable` |
| 2014 | SOS | general | 18,404 | 23 | 233 | `machine_readable` |
| 2015 | Boulder | coordinated | 5,235 | 39 | 237 | `machine_readable` (composite precincts) |
| 2016 | Boulder | general | 26,051 | 62 | 235 | `machine_readable` |
| 2016 | SOS | general | 23,496 | 28 | 233 | `machine_readable` |
| 2017 | Boulder | coordinated | 6,047 | 38 | 237 | `machine_readable` |
| 2018 | Boulder | general | 22,025 | 70 | 240 | `machine_readable` |
| 2018 | SOS | general | 21,422 | 34 | 235 | `machine_readable` |
| 2019 | Boulder | coordinated | 5,529 | 32 | 246 | `machine_readable` |
| 2020 | Boulder | general | 22,990 | 50 | 245 | `machine_readable` |
| 2020 | SOS | general | 23,320 | 28 | 240 | `machine_readable` |
| 2021 | Boulder | coordinated | 6,241 | 40 | 243 | `machine_readable` |
| 2022 | Boulder | general | 22,144 | 76 | 201 | `machine_readable` (composite precincts) |
| 2023 | Boulder | coordinated | 5,691 | 38 | 197 | `machine_readable` (Plurality + RCV sheets) |
| 2024 | Boulder | general | 66 | 2 | 13 | `machine_readable` ⚠ check upstream |
| 2024 | SOS | general | 0 | 0 | 0 | upstream file is turnout-only — no candidate/contest detail; harmonized rows skipped, raw file kept in `data/original/` |
| 2025 | Boulder | coordinated | 4,340 | 32 | 195 | `machine_readable` (Propositions LL/MM, Boulder County ballot issues) |

**Notes on row counts:**

- 2008/2010 Boulder: only major statewide and Boulder-specific contests captured cleanly — see [§4.2](#42-boulder-county-panel-years-2008-2010-2011-2012).
- 2024 Boulder: the upstream "Amended Statement of Votes" file contains only 66 rows of local races (Town of Superior, etc.). Federal/state races may be reported only via the SOS file (forthcoming). Verify before publishing.
- 2008-2014 SOS: ~3-5 fewer precincts than Boulder — SOS reports precinct subset that voted; Boulder reports every registered precinct.

---

## 6. How to filter, pivot, and join

See [`docs/filter-pivot-recipes.md`](filter-pivot-recipes.md) for parallel examples in pandas, tidyverse (R), and Excel pivot tables.

---

## 7. Upstream discovery

The pipeline pulls source URLs from two layers:

1. **Static registry** in [`scripts/sources.py`](../scripts/sources.py) — the verified canonical URL for every year that's been hand-recorded.
2. **Discovery** in [`scripts/discover.py`](../scripts/discover.py) — scrapes the upstream landing pages so newly-published files are picked up automatically, even before they're hand-added to the registry:
   - Boulder County: [bouldercounty.gov/elections/results/](https://bouldercounty.gov/elections/results/)
   - Colorado SOS: [coloradosos.gov/pubs/elections/Results/Archives.html](https://www.coloradosos.gov/pubs/elections/Results/Archives.html)

Discovery prefers `.xlsx` over `.xls` over `.pdf` when the same year publishes multiple formats. The filename filter rejects sample ballots, TABOR notices, summary files, abstracts, and other non-SoV publications.

```bash
# See what discovery would find that's NOT already in sources.py
uv run python -m scripts.discover

# Run the full pipeline including discovery
uv run python -m scripts.pipeline --discover
```

When a discovery finds something new, **add it to `sources.py`** in the same PR that introduces the year's data. Discovery's role is to keep the pipeline working between hand-curated updates; it's not a substitute for the registry.

## 8. Election-night incremental results (`data/processed/vote-counting/`)

A **separate dataset** (vote-counting schema **1.0.0**, defined in
[`scripts/schema.py`](../scripts/schema.py) under `VOTE_COUNTING_*`) built by
[`scripts/vote_counting.py`](../scripts/vote_counting.py) from 122 full-page screenshots of the
Boulder County election-night results site (2014–2025, one per published update) in
`data/original/boulder-county/vote-counting/{YYYY}{G|C}/`, plus the nine 2023 City of Boulder
mayoral RCV "Short Report" PDFs.

> **Grain:** county-wide totals *at a point in time* — not precincts. Never concatenate with
> `all-elections-tidy.csv`, and never sum `votes` across snapshots (they are cumulative). Use
> `vote_change` for per-update increments, or filter `is_final_snapshot`.

```
data/processed/vote-counting/
├── vote-counting-contests.csv   ← one row per election × snapshot × contest × candidate
├── vote-counting-summary.csv    ← one row per snapshot ("Election Summary" box + provenance)
└── datalab/{YYYY}{G|C}/*.json   ← cached Datalab OCR responses (keyed on image sha256)
```

### 8.1 `vote-counting-contests.csv`

| Column | Type | Description |
|---|---|---|
| `election_year`, `election_date`, `election_type` | Int16, ISO date, string | As in §1. |
| `snapshot_seq` | Int16 | 1…n in `last_updated` order within the election. Null for RCV report rows. |
| `last_updated` | string | ISO local time (America/Denver, no offset) from the page's **Last Updated** box. For RCV rows, the report's own timestamp. |
| `results_label` | string | As published: `Official Results` / `Unofficial Results`; `RCV Short Report` for RCV rows. **Not a certification flag** — 2014–2024 pages say "Official Results" from 7 p.m. on election night. |
| `is_final_snapshot` | boolean | The latest update for the election (web pages and RCV reports are separate series). |
| `contest` | string | Card title as published, with any "Vote for no more than N" line removed. |
| `vote_for` | Int16 | N from "Vote for (no/not more than) N", when shown. |
| `contest_type` | string | As in §3 (inferred the same way). RCV report rows are `ranked_choice` with `\| Round N` / `\| Final` suffixes, matching the 2023 SoV convention. |
| `candidate_or_option` | string | Candidate name with party and write-in suffix removed; Yes/No choices canonicalized (§2.2). Other measure labels (e.g. `For the Measure`) pass through. |
| `party` | string | Text after the last ` - ` in the published name, normalized via `PARTY_MAP` (§2.3); unknown parties verbatim. |
| `is_write_in` | boolean | Name carried `- Write-in Candidate`, `- Write-In`, or `- Certified Write-in Candidate`. |
| `votes` | Int64 | Cumulative votes as of `last_updated`. Null only where the source image is illegible. |
| `percent` | Float64 | Percent as published (null where illegible). |
| `contest_total_votes` | Int64 | The card's **TOTAL VOTES** row. |
| `vote_change` | Int64 | `votes` minus the same candidate's votes in the previous snapshot. Equals `votes` in the first snapshot (nothing is reported before polls close); null if the candidate is missing from the previous snapshot. Can be negative after canvass adjustments and recounts. |
| `source_file` | string | Screenshot/PDF path under `data/original/boulder-county/`. |

### 8.2 `vote-counting-summary.csv`

One row per snapshot: the identifying columns above, then every figure the page's
**Election Summary** box published (`total_registration`, `active_registered_voters`,
`mail_ballots_distributed`, `property_owner_only_ballots_distributed`, `expected_turnout`,
`mail_ballots`, `in_person_ballots`, `property_owner_ballots`, `total_ballots_counted`; null when
that year's page didn't show it), `ballots_counted_change`, `n_contests`, `summary_notes` (the
box's footnotes and update notices, verbatim), and provenance (`source_file`, `source_sha256`,
`ocr_retrieved_at`, `extraction_quality = "datalab_ocr"`).

### 8.3 How it is built and checked

1. **OCR.** Screenshots are 9,000–21,000 px tall, over Datalab's 15,000 px limit, so each is
   sliced into ≤3,600 px pages *at the white gaps between contest cards* (no table is ever split)
   and sent as one PDF to Datalab's `/api/v1/convert` (`mode=accurate`, Markdown output). Responses
   are committed, so rebuilding never calls the API. `uv run python -m scripts.vote_counting --ocr`
   converts only new or changed screenshots (needs `DATALAB_API_KEY`).
2. **QA.** Every card must satisfy *sum of candidate votes = TOTAL VOTES*, and every published
   percent must equal votes / total (±0.011). Rows that look like data but don't parse are
   reported, never dropped. Results: [`data/audit/vote-counting.md`](../data/audit/vote-counting.md).
3. **Corrections.** Every fix is a row in
   [`scripts/corrections/vote-counting.csv`](../scripts/corrections/vote-counting.csv) with the
   OCR'd value, the verified value, and a note. A correction whose OCR'd value no longer matches
   fails the build. Current corrections: 2017C City of Boulder Council (one row hidden by a
   screenshot stitching seam in all 8 snapshots — votes derived as TOTAL minus the 13 legible
   rows; the final value matches the SoV exactly) and three 2023C pages where OCR left two cards'
   vote cells blank (read from the image).
4. **External check.** `scripts/reconcile.py` compares each election's final snapshot with the
   SoV, candidate by candidate (report only — see the last section of
   [`data/audit/reconciliation.md`](../data/audit/reconciliation.md)). For 2014–2022 every
   matchable candidate agrees **exactly**.

**Known gaps:** write-in candidates can't be matched to the SoV (it lumps them); the 2024 SoV in
this repo has only local races, so for 2024 this dataset is the fullest county-level record we
hold; 2025's final snapshot is pre-certification ("Unofficial Results").

---

## 9. Changelog

- **2026-05-23** — Schema 1.0.0 released alongside the new pipeline. Initial dictionary published.
- **2026-05** — Added `discover.py` (BoCo + SOS upstream scraping), pytest suite under `tests/`, CI workflow at `.github/workflows/tests.yml`, plus 2025 Boulder coordinated + 2024 SOS general entries. `infer_contest_type` now handles `pd.NA` inputs.
- **2026-05** — Schema bumped to **1.1.0**. Per-row CSVs now hold a slim 15-column view; the 5 provenance columns (`source_file`, `source_url`, `retrieved_at`, `extraction_quality`, `extraction_notes`) moved to `data/processed/provenance.csv`. Combined-CSV size dropped from 152 MB to 49 MB; per-year files shrank by ~60%.
- **2026-10** — Added the election-night incremental results dataset (§8, vote-counting schema 1.0.0), OCR'd from results-site screenshots via Datalab. Boulder SoV raw files moved to `data/original/boulder-county/statement-of-votes/`; paths now resolve through `config.original_path()`.
- **2026-10** — Boulder tidy parser keeps `Property Owner` pseudo-precinct rows (2023, 2025) instead of rejecting them (§4.3a).
