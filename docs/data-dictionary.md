# Data dictionary

This file is the authoritative description of every column in `data/processed/`
(the harmonized SoV dataset in `statements-of-votes/` and the election-night
dataset in `vote-counting/`, §8).
It also documents the cross-walks between Boulder County SoV files, Colorado
Secretary of State precinct-results files, and the harmonized long-form schema
used throughout `data/processed/statements-of-votes/`.

Schema version: **1.1.0** (see [`scripts/schema.py`](../scripts/schema.py))

---

## 1. Schema (canonical columns)

The harmonized in-memory schema is **20 columns**. The **per-year CSV files** under
`data/processed/statements-of-votes/` hold a slim 15-column view — the 5 provenance columns (#16-20
in the table below) are redundant per-row (every row from a single source file
has the same value) so they live in a sidecar:

```
data/processed/
├── statements-of-votes/
│   ├── 2020-general-boulder-county.csv     ← 15-column slim view
│   ├── …                                    ← one slim CSV per source file
│   ├── all-elections-tidy.csv              ← combined slim CSV
│   └── provenance.csv                      ← one row per source file; carries
│                                             the 5 provenance columns
└── vote-counting/                          ← election-night snapshots (§8)
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

Columns marked **sidecar** live in `data/processed/statements-of-votes/provenance.csv` rather than in every row of every per-year CSV. They're constant per source file, so duplicating them on every row would inflate file sizes ~3× for no information gain. The pipeline writes both files together so they stay in sync.

---

## 2. Value normalization

### 2.1 Precinct IDs

Boulder uses 10-digit precinct numbers like `2181007800` (county-state-precinct format) and a "short" form like `800` (last three digits). We treat the 10-digit form as the canonical `precinct_id`. The short form is `precinct_name` when published, otherwise null.

`precinct_id` is always a **string** so leading zeros are preserved.

### 2.2 Choice normalization

The published files use several Yes/No variants. We canonicalize:

| Source value | Canonical |
|---|---|
| `Yes`, `Y`, `Yes/Sí`, `Yes/For`, `For`, `For the Measure`, `For the Issue` | `Yes` |
| `No`, `N`, `No/Against`, `Against`, `Against the Measure`, `Against the Issue` | `No` |

Matching ignores case and extra spaces (`YES`, `FOR THE MEASURE`, `For The Measure` all match). Rows with these options get `contest_type = measure` (or `retention` / `recall`).

Candidate names are stripped of whitespace but otherwise left as-published. Future cleanups (e.g., `John McCain / Sarah Palin` ↔ `McCain/Palin`) are out of scope.

### 2.3 Party normalization

The SOS uses full names in 2012+ (`Democratic Party`, `Republican Party`) and 3-letter codes in 2004-2010 (`DEM`, `REP`, with `LIB`/`UNA` in 2010). Boulder mixes full names with its own codes (`UNI`, `APV`, `AMS`, …). We canonicalize to one code per party — the SOS code where there is one, otherwise Boulder's — so a party has the same `party` value in every year and source:

| Canonical | Common source variants |
|---|---|
| `DEM` | `Democratic`, `Democrat`, `Democratic Party`, `Dem` |
| `REP` | `Republican`, `Republican Party`, `Rep` |
| `LBR` | `Libertarian`, `Libertarian Party`, `Lib`, `LIB` |
| `GRN` | `Green`, `Green Party` |
| `UAF` | `Unaffiliated`, `UNA` |
| `UTY` | `Unity`, `UNI`, `Unity Party of Colorado` |
| `ACN` | `American Constitution`, `American Constitution Party` |
| `AVP` | `Approval Voting Party`, `Approval Voting`, `APV` |
| `ASP` | `American Solidarity Party`, `AMS` |
| `ALP` | `Alliance Party`, `ALL` |
| `AIP` | `American Independent`, `American Independent Party` |
| `IAM` | `Independent American Party` |
| `CON` | `Constitution`, `Constitution Party` |
| `BTP` | `Boston Tea`, `Boston Tea Party` |
| `PRB` / `PRO` / `SLB` / `SOE` / `SWP` / `SPU` | Prohibition / Progressive / Socialism and Liberation / Socialist Equality / Socialist Workers / Socialist Party USA |
| `WI`  | `Write-In`, `Write In`, `Write-in` |
| `IND` | `Independent` |
| `NP`  | `Non Partisan`, `Non-Partisan`, `Nonpartisan` |
| `UAF / REP`, `DEM / REP`, `IND / REP`, … | two-party labels keep both codes |

`0` (one 2022 write-in row) means no party and becomes null. The full list, including the rarer one-cycle parties, is in [`data/lookups/party-codes.json`](../data/lookups/party-codes.json).

Parties not in the map pass through verbatim — never silently dropped. Add new mappings in [`scripts/parsers/common.py`](../scripts/parsers/common.py) (`PARTY_MAP`).

---

## 3. Contest types

`contest_type` is inferred from the `contest` title and `candidate_or_option` value:

| Rule | contest_type |
|---|---|
| Title contains `Recall` | `recall` |
| Choice ∈ {`Yes`, `No`} AND title matches a judicial cue (`Justice of the`, `Supreme Court`, `Court of Appeals`, `District Judge`, `District Court`, `County Judge`, `County Court`, `Municipal Judge`, `retained in office`, …) | `retention` |
| Choice ∈ {`Yes`, `No`} | `measure` |
| Otherwise | `candidate` |

A bare "retention" / "retain" is not a judicial cue: TABOR questions such as `Authorize Retention of All Sugar-Sweetened Beverages Tax Revenue` are measures.

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

These XLS files predate the modern tidy export. Results are reported as repeating "panels": a contest title row, a header row whose first cell is `Precinct`, then per-precinct rows with vote counts spread across candidate columns, and on a contest's last page a `Totals` row. 2008 and 2010 print one page per panel (a contest spans seven or more), 2011 and 2012 one panel per contest. The parser walks the sheet, finds each panel, and melts wide → long. See [`scripts/parsers/boco_panel.py`](../scripts/parsers/boco_panel.py).

**Column alignment.** The header labels don't sit over their values: in 2008 the `Total Ballots Cast` header is in spreadsheet column 10 and its values in column 8, and several value columns have no header above them. The parser therefore maps each data row's non-empty cells, in order, to the header's non-empty labels, in order (the original `Cleaning.ipynb` did the same per contest with hand-picked `iloc` positions). A row whose width doesn't fit its header goes to `data/audit/rejected.csv`; a precinct printed alone with its values on the row below is joined back up. Before 2026-10 the parser read values by spreadsheet column, which left 2008/2010 misaligned (e.g. 2008 Presidential Electors summed to 1,005 votes; `active_voters < ballots_cast` in every precinct).

**Checks.** Every (contest, candidate) total matches the file's own `Totals` row in all four years, and every contest titled the same way in the SOS file for 2008/2010/2012 matches it exactly (see `data/audit/reconciliation.md`).

**Candidate labels.** Party is printed in the label — `REP\nKen Buck` (2010), `Bruce E. Lohmiller - GRN` (2010), `Mark Udall Democratic` (2008), `Jared Polis    Democratic` (2012). Only known party codes and names are split into `party`; labels the export truncated (`America's`, `Socialism and`, …) are resolved per year against the SOS file. `FOR THE MEASURE` / `AGAINST THE MEASURE` are Yes/No options. Precinct IDs are the 3-digit codes of those years (`073`), not the 10-digit IDs used from 2013.

### 4.3 Composite precinct IDs

In **2015** and **2022**, Boulder County reported some precincts jointly because turnout in individual sub-precincts was small enough to risk voter privacy. These rows have comma-joined IDs:

```
precinct_id = "2181007800, 2181207403"
precinct_name = "800, 403"
```

Vote tallies are for the **combined** unit. To match these against single-precinct geography, split the comma-separated IDs into a one-to-many lookup. The parser flags these in `extraction_notes`.

**Source anomaly — 2023 City of Louisville City Council Ward 2.** The 2023 SoV reports this contest under two *overlapping* composite units, `2181207201,2181207202` and `2181207202,2181207500`, with near-identical tallies (Fahey 184 / 183, Colbert 234 / 234, 458 ballots each). Summed as published, the SoV gives 1,602 / 1,441; without the `202,500` row it gives 1,419 / 1,207 — exactly the county's final election-night web totals (§8). It looks like a double-listed tally in the published file, but the data is left as published (never split or drop composite rows on a guess). It is the only contest in the 2015, 2022 or 2023 files where one precinct appears in two reporting units.

### 4.3a Property-owner / landowner pseudo-precincts

Special-district contests can include ballots from non-resident property owners. The SoV reports them on a row whose precinct code is `Property Owner` (2023, 2025), `Landowner` (2007, 2008, 2012, 2015; `Landowner CCCPR` etc. in 2011) or a district code such as `FMFPD` / `SLFPD` (2010) or `RMFPD` / `NCLD` (2009) instead of a real precinct. They count toward the certified totals, so they are kept with `precinct_id = "Property Owner"` (or `Landowner`) and flagged in `extraction_notes`. They have no precinct geography — exclude them before a spatial join, but keep them when summing contest totals. (Before 2026-10 the 2023/2025 rows were rejected for a missing `precinct_id`, which undercounted e.g. 2023 Nederland Eco Pass 6A by 101 Yes / 43 No.)

### 4.4 PDF years (2005, 2007, 2009)

These are 100+-page coordinated-election Canvass Reports published only as PDFs. They have a text layer, so `scripts/parsers/boco_pdf.py` reads them with **pdfplumber** (pure Python, no JVM). Contest titles come straight from the page text; candidate names are reconstructed by clustering rotated `upright=False` words by x-coordinate and reversing their characters.

Rows from PDF years carry:
- `extraction_quality = "pdf_text_layer"`
- `contest = "<actual title from page>"` (e.g., `City of Boulder Council Candidates`, `Referendum C`)
- `extraction_notes` summarizing pages parsed/skipped and reminding analysts to spot-check against the source PDF.

A contest with more candidates than fit across a page prints its precinct run once per group of candidates, so the parser reads the candidate header on every page; the vote-method block before the candidates is 4 columns in 2007 and 6 in 2005/2009, so rows are split at the Percent Turnout (`%`) token. Every candidate's precinct rows now sum exactly to the `Totals:` line the PDF prints for it, and no (precinct, contest, candidate) key appears twice. (Before 2026-10 continuation pages reused the first page's candidate names and 2007 rows were split at the wrong column, which produced 1,448 / 1,365 / 1,154 duplicate keys with conflicting votes in 2005 / 2007 / 2009.)

These years remain **provisional** (`pdf_text_layer`): the vote counts reconcile, but candidate names are rebuilt from rotated text — verify names against the source before publishing precinct-level claims.

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
| `contest` (retention row) | `{Office/Issue/Judgeship} - {Candidate}`, e.g. `Court of Appeals - Anthony J. Navarro` |
| `candidate_or_option` (candidate row) | `Candidate` |
| `candidate_or_option` (measure / retention row) | `Yes` or `No` (synthesized from column name) |
| `party` | `Party` |
| `votes` (candidate row) | `Candidate Votes` |
| `votes` (measure Yes row) | `Yes Votes` |
| `votes` (measure No row) | `No Votes` |
| (filter) | `County == "BOULDER"` (after strip+upper) |

Every 2012-2020 row carries all three vote columns, with `0` where a column doesn't apply, so the parser classifies rows instead of testing for nulls: `Candidate` empty → a ballot measure (Yes/No rows); otherwise a judge up for retention if that (office, name) has Yes/No votes anywhere in the county, else a candidate. Several judges share one office title (`Court of Appeals`) with the judge named in `Candidate`, so retention rows put the judge in `contest` — the same shape the Boulder files and the 2004-2010 SOS files use. (Before 2026-10 only the first judge per office survived in each precinct — e.g. 2016 Court of Appeals summed to 134,320 votes instead of 1,306,890 — and every candidate contest carried 0-vote `Yes`/`No` rows, which made recipe 5 count offices such as Governor as failed measures.)

The SOS publishes **only candidate vote totals**, never ballots-cast or active-voter counts. `active_voters` and `ballots_cast` are null on every SOS row.

### 4.6 Election certification dates

`election_date` is set from a small table in [`scripts/sources.py`](../scripts/sources.py) (`ELECTION_DATES`). It records election day, not the certification date. Boulder County typically certifies its SoV ~3 weeks after election day; the file `retrieved_at` timestamp captures when we pulled the latest copy.

---

## 5. Per-year audits

The audit is generated by [`scripts/audit.py`](../scripts/audit.py) and refreshed on every pipeline run. The full per-year summary lives at [`data/audit/summary.md`](../data/audit/summary.md) and per-file fragments at `data/audit/{stem}.md`.

Quick reference (post-pipeline run, 2026-10-26). Contests count distinct titles; SOS 2012-2020 retention contests are one per judge (§4.5):

| Year | Source | Election | Rows | Contests | Precincts | Quality |
|---|---|---|---|---|---|---|
| 2005 | Boulder | coordinated | 7,307 | 43 | 228 | `pdf_text_layer` |
| 2007 | Boulder | coordinated | 6,866 | 45 | 235 | `pdf_text_layer` |
| 2008 | Boulder | general | 27,934 | 71 | 237 | `machine_readable` |
| 2008 | SOS | general | 24,856 | 43 | 239 | `machine_readable` |
| 2009 | Boulder | coordinated | 6,654 | 41 | 236 | `pdf_text_layer` |
| 2010 | Boulder | general | 23,078 | 57 | 247 | `machine_readable` |
| 2010 | SOS | general | 18,196 | 37 | 236 | `machine_readable` |
| 2011 | Boulder | coordinated | 6,291 | 49 | 246 | `machine_readable` |
| 2012 | Boulder | general | 16,775 | 46 | 243 | `machine_readable` |
| 2012 | SOS | general | 14,290 | 28 | 234 | `machine_readable` |
| 2013 | Boulder | coordinated | 4,783 | 103 | 246 | `machine_readable` |
| 2014 | Boulder | general | 20,307 | 58 | 234 | `machine_readable` |
| 2014 | SOS | general | 15,617 | 32 | 233 | `machine_readable` |
| 2015 | Boulder | coordinated | 5,235 | 39 | 237 | `machine_readable` (composite precincts) |
| 2016 | Boulder | general | 26,051 | 62 | 235 | `machine_readable` |
| 2016 | SOS | general | 21,623 | 38 | 233 | `machine_readable` |
| 2017 | Boulder | coordinated | 6,047 | 38 | 237 | `machine_readable` |
| 2018 | Boulder | general | 22,025 | 70 | 240 | `machine_readable` |
| 2018 | SOS | general | 17,085 | 39 | 235 | `machine_readable` |
| 2019 | Boulder | coordinated | 5,529 | 32 | 246 | `machine_readable` |
| 2020 | Boulder | general | 22,990 | 50 | 245 | `machine_readable` |
| 2020 | SOS | general | 20,584 | 34 | 240 | `machine_readable` |
| 2021 | Boulder | coordinated | 6,241 | 40 | 243 | `machine_readable` |
| 2022 | Boulder | general | 22,144 | 76 | 201 | `machine_readable` (composite precincts) |
| 2023 | Boulder | coordinated | 5,695 | 38 | 198 | `machine_readable` (Plurality + RCV sheets) |
| 2024 | Boulder | general | 66 | 2 | 13 | `machine_readable` ⚠ check upstream |
| 2024 | SOS | general | 0 | 0 | 0 | upstream file is turnout-only — no candidate/contest detail; harmonized rows skipped, raw file kept in `data/original/` |
| 2025 | Boulder | coordinated | 4,342 | 32 | 196 | `machine_readable` (Propositions LL/MM, Boulder County ballot issues) |

**Notes on row counts:**

- 2008-2012 Boulder: panel files; every candidate reconciles to the file's printed `Totals` — see [§4.2](#42-boulder-county-panel-years-2008-2010-2011-2012).
- 2024 Boulder: the upstream "Amended Statement of Votes" file contains only 66 rows of local races (Town of Superior, etc.), and the 2024 SOS file is turnout-only. County-wide totals for all 65 contests are in the election-night dataset's final 2024 snapshot (§8).
- 2023 / 2025 Boulder: precinct counts include the `Property Owner` pseudo-precinct (§4.3a).
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
| `candidate_or_option` | string | Candidate name with party and write-in suffix removed; Yes/No choices canonicalized (§2.2), including `For/Against the Measure`. |
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
- **2026-05** — Schema bumped to **1.1.0**. Per-row CSVs now hold a slim 15-column view; the 5 provenance columns (`source_file`, `source_url`, `retrieved_at`, `extraction_quality`, `extraction_notes`) moved to `data/processed/statements-of-votes/provenance.csv`. Combined-CSV size dropped from 152 MB to 49 MB; per-year files shrank by ~60%.
- **2026-10** — Added the election-night incremental results dataset (§8, vote-counting schema 1.0.0), OCR'd from results-site screenshots via Datalab. Boulder SoV raw files moved to `data/original/boulder-county/statement-of-votes/`; paths now resolve through `config.original_path()`.
- **2026-10** — Boulder tidy parser keeps `Property Owner` pseudo-precinct rows (2023, 2025) instead of rejecting them (§4.3a).
- **2026-10** — Accuracy fixes (data changes; schema unchanged):
  - SOS 2012-2020: every judge's retention votes kept, one contest per judge (`Court of Appeals - {judge}`); no more 0-vote `Yes`/`No` rows on candidate contests or 0-vote judge "candidate" rows (§4.5). Boulder retention votes per year now equal the raw file's (e.g. 2016: 400,831 → 1,701,522).
  - Boulder 2008/2010 panel files re-parsed with positional alignment; 2008 grows from 2,528 to 27,934 rows and every candidate reconciles to the file's `Totals` row (§4.2). 2011/2012 gain their `Landowner` rows.
  - PDF years: candidate headers read per page; no duplicate keys; every candidate reconciles to the PDF's printed totals (§4.4).
  - `For/Against the Measure`, `FOR THE ISSUE`, `FOR`/`AGAINST` → `Yes`/`No` (contest type `measure`); county/district court judges typed `retention`, TABOR revenue-retention questions typed `measure`.
  - Party codes unified across sources (`UNI`/`Unity Party of Colorado` → `UTY`, `LIB` → `LBR`, `UNA` → `UAF`, `APV` → `AVP`, full names → codes; see `data/lookups/party-codes.json`).
  - `provenance.csv` has a row for every source file, including the PDF years and the turnout-only 2024 SOS file; `reconcile.py` adds a contest × candidate check.
