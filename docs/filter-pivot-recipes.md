# Filter & pivot recipes

The harmonized data is in **long form** — one row per
(year × precinct × contest × candidate-or-option). Long form is awkward to
*look at* but trivial to filter, group, and reshape. This file shows side-by-side
how to do the most common civic-data tasks in **pandas**, **tidyverse**,
**Excel pivot tables**, and **DuckDB** (SQL straight against the CSV — no load
step).

> **Just want to explore in the browser?** Open the
> [Datasette Lite link in the README](../README.md#-datasette-lite) — same data,
> same SQL editor as the DuckDB column below, zero setup.

Load the file first (DuckDB doesn't need a load — see its column):

**pandas**
```python
import pandas as pd
df = pd.read_csv("data/processed/all-elections-tidy.csv", dtype={"precinct_id": "string"})
```

**tidyverse**
```r
library(readr); library(dplyr); library(tidyr)
df <- read_csv("data/processed/all-elections-tidy.csv",
               col_types = cols(precinct_id = col_character()))
```

**DuckDB** (Python, R, CLI, or paste into Datasette's SQL editor)
```sql
-- DuckDB reads CSV directly — no load step. From the CLI:
duckdb -c "FROM 'data/processed/all-elections-tidy.csv' LIMIT 5"
-- From Python: `import duckdb; con = duckdb.connect()` then `con.sql(...)`.
-- From the Datasette web UI: paste any of the queries below into the SQL editor.
```

**Excel**
1. Open `data/processed/all-elections-tidy.csv` in Excel.
2. Click anywhere in the data → **Insert → PivotTable**. Place it in a new sheet.
3. The recipes below tell you which fields to drag into Rows / Columns / Values / Filters.

---

## Recipe 1 — Vote share for a single contest, one year

> *"What was the precinct-level split between the candidates in the 2020 Presidential race?"*

**pandas**
```python
pres20 = df[
    (df.election_year == 2020)
    & (df.data_source == "boulder_county")
    & (df.contest == "Presidential Electors")
].pivot_table(index="precinct_id", columns="candidate_or_option",
              values="votes", aggfunc="sum", fill_value=0)
```

**tidyverse**
```r
pres20 <- df |>
  filter(election_year == 2020,
         data_source == "boulder_county",
         contest == "Presidential Electors") |>
  pivot_wider(id_cols = precinct_id,
              names_from = candidate_or_option,
              values_from = votes,
              values_fn = sum, values_fill = 0)
```

**DuckDB**
```sql
PIVOT (
    FROM 'data/processed/all-elections-tidy.csv'
    WHERE election_year = 2020
      AND data_source = 'boulder_county'
      AND contest = 'Presidential Electors'
)
ON candidate_or_option
USING SUM(votes)
GROUP BY precinct_id;
```

**Excel**
- **Filters:** `election_year = 2020`, `data_source = boulder_county`, `contest = Presidential Electors`
- **Rows:** `precinct_id`
- **Columns:** `candidate_or_option`
- **Values:** Sum of `votes`

---

## Recipe 2 — Total turnout by precinct across multiple years

> *"How has total ballots-cast changed in each Boulder precinct from 2014 to 2024?"*

**pandas**
```python
# active_voters/ballots_cast are constant per (year, precinct), so dedupe before summing.
turnout = (
    df[df.data_source == "boulder_county"]
    .drop_duplicates(["election_year", "precinct_id"])
    .pivot_table(index="precinct_id", columns="election_year",
                 values="ballots_cast", aggfunc="first")
)
```

**tidyverse**
```r
turnout <- df |>
  filter(data_source == "boulder_county") |>
  distinct(election_year, precinct_id, .keep_all = TRUE) |>
  pivot_wider(id_cols = precinct_id, names_from = election_year,
              values_from = ballots_cast)
```

**DuckDB**
```sql
PIVOT (
    SELECT DISTINCT precinct_id, election_year, ballots_cast
    FROM 'data/processed/all-elections-tidy.csv'
    WHERE data_source = 'boulder_county'
)
ON election_year
USING ANY_VALUE(ballots_cast)  -- "first non-null" for the (precinct, year) cell
GROUP BY precinct_id;
```

**Excel**
- **Filters:** `data_source = boulder_county`
- **Rows:** `precinct_id`
- **Columns:** `election_year`
- **Values:** Max of `ballots_cast` (Max ≈ First when values are constant per group; use Average if you want to be sure)

---

## Recipe 3 — Citywide vote totals (just City of Boulder precincts)

City of Boulder precincts are a subset of Boulder County precincts. They're
listed in [`data/lookups/city-of-boulder-precincts-2023.json`](../data/lookups/city-of-boulder-precincts-2023.json).

**pandas**
```python
import json
cob_ids = set(json.load(open("data/lookups/city-of-boulder-precincts-2023.json")))

cob = df[df.precinct_id.isin(cob_ids)]
cob_council = (
    cob[(cob.election_year == 2023) & cob.contest.str.contains("Council", na=False)]
    .groupby(["contest", "candidate_or_option"])["votes"].sum()
    .sort_values(ascending=False)
)
```

**tidyverse**
```r
library(jsonlite)
cob_ids <- fromJSON("data/lookups/city-of-boulder-precincts-2023.json")

df |>
  filter(precinct_id %in% cob_ids,
         election_year == 2023,
         str_detect(contest, "Council")) |>
  group_by(contest, candidate_or_option) |>
  summarise(votes = sum(votes, na.rm = TRUE), .groups = "drop") |>
  arrange(desc(votes))
```

**DuckDB**
```sql
-- DuckDB reads the JSON lookup directly via read_json_auto.
WITH cob AS (
    SELECT UNNEST(*) AS precinct_id
    FROM read_json_auto('data/lookups/city-of-boulder-precincts-2023.json')
)
SELECT contest, candidate_or_option, SUM(votes) AS votes
FROM 'data/processed/all-elections-tidy.csv'
WHERE precinct_id IN (SELECT precinct_id FROM cob)
  AND election_year = 2023
  AND contest LIKE '%Council%'
GROUP BY contest, candidate_or_option
ORDER BY votes DESC;
```

**Excel**
- Open the City of Boulder precinct lookup. Paste as a list in a side sheet.
- In the pivot, use a slicer on `precinct_id` matching that list (or pre-filter via VLOOKUP/XLOOKUP).
- Rows: `contest`, then `candidate_or_option`. Values: Sum of `votes`.

---

## Recipe 4 — Compare same race across both data sources

> *"How does the Boulder County SoV compare to the Colorado SOS file for the 2020 Senator race?"*

This is the **most useful sanity check** for a civic-data piece. If the two
sources don't reconcile within a small tolerance, ask why before you publish.

**pandas**
```python
sen20 = df[
    (df.election_year == 2020)
    & (df.contest.str.contains("United States Senator", case=False, na=False))
].groupby(["data_source", "candidate_or_option"])["votes"].sum().unstack(0)
sen20["delta"] = sen20["boulder_county"] - sen20["secretary_of_state"]
```

**tidyverse**
```r
sen20 <- df |>
  filter(election_year == 2020,
         str_detect(contest, regex("United States Senator", ignore_case = TRUE))) |>
  group_by(data_source, candidate_or_option) |>
  summarise(votes = sum(votes, na.rm = TRUE), .groups = "drop") |>
  pivot_wider(names_from = data_source, values_from = votes) |>
  mutate(delta = boulder_county - secretary_of_state)
```

**DuckDB**
```sql
WITH base AS (
    SELECT data_source, candidate_or_option, SUM(votes) AS votes
    FROM 'data/processed/all-elections-tidy.csv'
    WHERE election_year = 2020
      AND LOWER(contest) LIKE '%united states senator%'
    GROUP BY data_source, candidate_or_option
)
SELECT candidate_or_option,
       SUM(CASE WHEN data_source = 'boulder_county' THEN votes END) AS boulder_county,
       SUM(CASE WHEN data_source = 'secretary_of_state' THEN votes END) AS secretary_of_state,
       SUM(CASE WHEN data_source = 'boulder_county' THEN votes END)
         - SUM(CASE WHEN data_source = 'secretary_of_state' THEN votes END) AS delta
FROM base
GROUP BY candidate_or_option
ORDER BY ABS(delta) DESC;
```

**Excel**
- **Filters:** `election_year = 2020`, `contest` contains "Senator"
- **Rows:** `candidate_or_option`
- **Columns:** `data_source`
- **Values:** Sum of `votes`
- Add a Calculated Field `delta = boulder_county - secretary_of_state`.

---

## Recipe 5 — Yes/No measure pass rate

> *"What fraction of Boulder County ballot measures since 2014 passed?"*

**pandas**
```python
measures = (
    df[(df.contest_type == "measure") & (df.election_year >= 2014)]
    .groupby(["election_year", "contest", "candidate_or_option"])["votes"].sum()
    .unstack("candidate_or_option").fillna(0)
)
measures["passed"] = measures["Yes"] > measures["No"]
pass_rate = measures.groupby(level="election_year")["passed"].mean()
```

**tidyverse**
```r
df |>
  filter(contest_type == "measure", election_year >= 2014) |>
  group_by(election_year, contest, candidate_or_option) |>
  summarise(votes = sum(votes, na.rm = TRUE), .groups = "drop") |>
  pivot_wider(names_from = candidate_or_option, values_from = votes, values_fill = 0) |>
  mutate(passed = Yes > No) |>
  group_by(election_year) |>
  summarise(pass_rate = mean(passed))
```

**DuckDB**
```sql
WITH measures AS (
    SELECT election_year, contest,
           SUM(CASE WHEN candidate_or_option = 'Yes' THEN votes END) AS yes,
           SUM(CASE WHEN candidate_or_option = 'No' THEN votes END) AS no
    FROM 'data/processed/all-elections-tidy.csv'
    WHERE contest_type = 'measure' AND election_year >= 2014
    GROUP BY election_year, contest
)
SELECT election_year,
       AVG(CASE WHEN yes > no THEN 1.0 ELSE 0.0 END) AS pass_rate
FROM measures
GROUP BY election_year
ORDER BY election_year;
```

**Excel** (two-step pivot):
1. Pivot 1: Rows = `election_year`, `contest`; Columns = `candidate_or_option`; Values = Sum of `votes`. Filter `contest_type = measure`.
2. In a side column compute `=IF(Yes>No, 1, 0)`.
3. Pivot 2: Rows = `election_year`; Values = Average of the pass column.

---

## Recipe 6 — Ranked-choice round-by-round (2023 Boulder Mayoral)

The 2023 Boulder mayoral race used RCV. Each round of tabulation is one set of rows; the candidate name is suffixed with `| Round N` or `| Final`.

**pandas**
```python
mayor = df[
    (df.election_year == 2023)
    & (df.contest_type == "ranked_choice")
    & df.contest.str.contains("Mayor", case=False, na=False)
].copy()

mayor[["candidate", "round_label"]] = mayor["candidate_or_option"].str.split(r"\s*\|\s*", expand=True)
mayor.pivot_table(index="candidate", columns="round_label",
                  values="votes", aggfunc="sum", fill_value=0)
```

**tidyverse**
```r
df |>
  filter(election_year == 2023, contest_type == "ranked_choice",
         str_detect(contest, regex("mayor", ignore_case = TRUE))) |>
  separate(candidate_or_option, into = c("candidate", "round_label"),
           sep = "\\s*\\|\\s*") |>
  group_by(candidate, round_label) |>
  summarise(votes = sum(votes), .groups = "drop") |>
  pivot_wider(names_from = round_label, values_from = votes, values_fill = 0)
```

**DuckDB**
```sql
PIVOT (
    SELECT TRIM(SPLIT_PART(candidate_or_option, '|', 1)) AS candidate,
           TRIM(SPLIT_PART(candidate_or_option, '|', 2)) AS round_label,
           votes
    FROM 'data/processed/all-elections-tidy.csv'
    WHERE election_year = 2023
      AND contest_type = 'ranked_choice'
      AND LOWER(contest) LIKE '%mayor%'
)
ON round_label
USING SUM(votes)
GROUP BY candidate;
```

**Excel**
- Filter `election_year = 2023`, `contest_type = ranked_choice`, `contest` contains "Mayor".
- Add a helper column splitting `candidate_or_option` on `|` (use `TEXTSPLIT` in modern Excel, or `LEFT`/`FIND`).
- Pivot: Rows = candidate; Columns = round_label; Values = Sum of `votes`.

---

## Joining the provenance sidecar

The per-year CSVs hold the slim schema (no `source_url`/`retrieved_at`/etc.). If you need provenance for a row, join against `data/processed/provenance.csv`:

**pandas**
```python
df = pd.read_csv("data/processed/all-elections-tidy.csv",
                 dtype={"precinct_id": "string"})
prov = pd.read_csv("data/processed/provenance.csv", dtype=str)
df = df.merge(prov, on=["election_year", "election_type", "data_source"], how="left")
```

**tidyverse**
```r
prov <- read_csv("data/processed/provenance.csv",
                 col_types = cols(election_year = col_integer()))
df <- df |> left_join(prov, by = c("election_year", "election_type", "data_source"))
```

**DuckDB**
```sql
SELECT e.*, p.source_url, p.retrieved_at, p.extraction_quality
FROM 'data/processed/all-elections-tidy.csv' e
LEFT JOIN 'data/processed/provenance.csv' p
  ON  e.election_year = CAST(p.election_year AS INTEGER)
  AND e.election_type = p.election_type
  AND e.data_source   = p.data_source;
```

**Excel** — open `provenance.csv` as a side sheet and use `XLOOKUP` against the three join columns.

## Common gotchas

- **`precinct_id` is a string** — `"01000123"` is not `1000123`. Load as text in Excel (paste-special), or use `dtype={"precinct_id": "string"}` in pandas / `col_character()` in R.
- **Active voters and ballots cast are precinct-level, not per-row** — they repeat across every contest/candidate row for the same (year, precinct). Use `drop_duplicates(["year","precinct_id"])` before summing them. Excel: use `Max` (or `First`), not `Sum`.
- **Negative votes only appear in RCV intermediate rounds** — they represent ballots transferring *away* from an eliminated candidate. Use the `Round` suffix to filter for `Final` rows when you want final totals.
- **`data_source` matters** — Boulder SoV reports all Boulder precincts; SOS reports only precincts that recorded votes. Counts differ slightly. When in doubt, prefer Boulder SoV for Boulder-specific analysis and SOS for state-level comparisons.
- **Pre-2013 panel-format quirks** — 2008 and 2010 are partial extractions; consult the `data/original/` XLS before publishing precinct-level findings for these years.
- **Composite precincts** — in 2015 and 2022, some `precinct_id` values are comma-joined (e.g. `"2181007800, 2181207403"`). These represent ballots tallied jointly across two underlying precincts. If you're joining to precinct geography, split first.
