# Data dictionary

This file is the authoritative description of every column in `data/processed/`.
It also documents the cross-walks between Boulder County SoV files, Colorado
Secretary of State precinct-results files, and the harmonized long-form schema
used throughout `data/processed/`.

Schema version: **1.0.0** (see [`scripts/schema.py`](../scripts/schema.py))

---

## 1. Schema (canonical columns)

Every CSV under `data/processed/` carries the same 20 columns in this order. One
row represents one **(election_year × jurisdiction × precinct × contest ×
candidate-or-option)** tally.

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
| 16 | `source_file` | string | yes | The local filename of the raw download (e.g., `2020-general-sov.xlsx`). |
| 17 | `source_url` | string | yes | The canonical upstream URL. |
| 18 | `retrieved_at` | string (ISO UTC) | yes | Timestamp when the raw file was downloaded by `scripts/fetch.py` (or the file's mtime if downloaded by hand). |
| 19 | `extraction_quality` | string | yes | `machine_readable` (XLS/XLSX), `pdf_text_layer` (tabula-extracted from text-layer PDF), `pdf_ocr` (reserved), `manual` (reserved). |
| 20 | `extraction_notes` | string | no | Free-text caveats from the parser — composite-ID flags, RCV mechanics, skipped panels, etc. |

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

Columns not used: `ContestSeqNbr`, `CandSeqNbr`, `PctSeqNbr`, `Sequence`, `ContestID`, `IsCurrent`, `Total Under Votes`, `Total Over Votes`, `Total Undervotes`, `Total Overvotes`. (Under/over votes are intentionally dropped; if you need them, reach into the original-data file.)

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

### 4.4 PDF years (2005, 2007, 2009)

These are 100+-page coordinated-election Canvass Reports published only as PDFs. They have a text layer (tabula-py can extract tables) but the layout is irregular page-to-page, and **contest titles do not extract cleanly** because they sit in narrative cells outside the table region.

Rows from PDF years carry:
- `extraction_quality = "pdf_text_layer"`
- `contest = "<PDF: contest title not extracted>"` — flagged for manual association
- `extraction_notes` listing the page-parse outcome

These years should be treated as **provisional**: useful for spot-checks against the PDF, but not for unattended analyses until contest titles are backfilled.

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

**Notes on row counts:**

- 2008/2010 Boulder: only major statewide and Boulder-specific contests captured cleanly — see [§4.2](#42-boulder-county-panel-years-2008-2010-2011-2012).
- 2024 Boulder: the upstream "Amended Statement of Votes" file contains only 66 rows of local races (Town of Superior, etc.). Federal/state races may be reported only via the SOS file (forthcoming). Verify before publishing.
- 2008-2014 SOS: ~3-5 fewer precincts than Boulder — SOS reports precinct subset that voted; Boulder reports every registered precinct.

---

## 6. How to filter, pivot, and join

See [`docs/filter-pivot-recipes.md`](filter-pivot-recipes.md) for parallel examples in pandas, tidyverse (R), and Excel pivot tables.

---

## 7. Changelog

- **2026-05-23** — Schema 1.0.0 released alongside the new pipeline. Initial dictionary published.
