# Filter & pivot recipes

The harmonized data is in **long form** — one row per
(year × precinct × contest × candidate-or-option). Long form is awkward to
*look at* but trivial to filter, group, and reshape. This file shows side-by-side
how to do the most common civic-data tasks in **pandas**, **tidyverse**, and
**Excel pivot tables**.

Load the file first:

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

**Excel** — open `provenance.csv` as a side sheet and use `XLOOKUP` against the three join columns.

## Common gotchas

- **`precinct_id` is a string** — `"01000123"` is not `1000123`. Load as text in Excel (paste-special), or use `dtype={"precinct_id": "string"}` in pandas / `col_character()` in R.
- **Active voters and ballots cast are precinct-level, not per-row** — they repeat across every contest/candidate row for the same (year, precinct). Use `drop_duplicates(["year","precinct_id"])` before summing them. Excel: use `Max` (or `First`), not `Sum`.
- **Negative votes only appear in RCV intermediate rounds** — they represent ballots transferring *away* from an eliminated candidate. Use the `Round` suffix to filter for `Final` rows when you want final totals.
- **`data_source` matters** — Boulder SoV reports all Boulder precincts; SOS reports only precincts that recorded votes. Counts differ slightly. When in doubt, prefer Boulder SoV for Boulder-specific analysis and SOS for state-level comparisons.
- **Pre-2013 panel-format quirks** — 2008 and 2010 are partial extractions; consult the `data/original/` XLS before publishing precinct-level findings for these years.
- **Composite precincts** — in 2015 and 2022, some `precinct_id` values are comma-joined (e.g. `"2181007800, 2181207403"`). These represent ballots tallied jointly across two underlying precincts. If you're joining to precinct geography, split first.
