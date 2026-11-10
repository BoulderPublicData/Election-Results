### 2023 coordinated — boulder_county

- **Source file:** `2023-coordinated-sov.xlsx`
- **Source URL:** https://assets.bouldercounty.gov/wp-content/uploads/2023/11/2023C-Boulder-County-Official-Statement-of-Votes.xlsx
- **Retrieved at:** 2026-05-23T18:13:44+00:00
- **Extraction quality:** machine_readable
- **Extraction notes:** includes 'Property Owner' pseudo-precinct rows (property-owner ballots in special-district contests; no precinct geography); contains composite precinct IDs (multiple precincts joined, comma-separated); votes are reported for the combined unit; RCV: candidate_or_option suffixed with '| Round N' for each tabulation round and '| Final' for the Total Votes column; 1 contest(s) taken from the recount file 2023-coordinated-sov-recount.xlsx (https://assets.bouldercounty.gov/wp-content/uploads/2023/12/2023C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx), replacing the same contests in 2023-coordinated-sov.xlsx: City of Boulder Council Candidates; 2 adjudicated correction(s) from scripts/corrections/statements-of-votes.csv: City of Louisville City Council Ward 2 (4-year term) / 2181207202, 2181207500 / Deborah Fahey: drop_row (183 published); City of Louisville City Council Ward 2 (4-year term) / 2181207202, 2181207500 / George Colbert: drop_row (234 published)

- **Rows:** 5,693
- **Distinct contests:** 38
- **Distinct precincts:** 197
- **Total votes summed:** 1,262,401
- **Rows with null votes:** 0
- **Contest type breakdown:** {'candidate': 2571, 'measure': 2402, 'ranked_choice': 720}
- **Party breakdown (top 8):** {'(none)': 5693}

**Top 10 contests by vote total** (sanity check):

| contest | total_votes |
|---|---|
| Boulder County Ballot Issue 1A | 117,806 |
| Proposition II (Statutory) | 117,453 |
| Proposition HH (Statutory) | 117,364 |
| Boulder County Ballot Issue 1B | 116,931 |
| City of Boulder Council Candidates | 113,374 |
| City of Boulder Mayoral Candidates | 64,830 |
| Boulder Valley School District RE-2 Director District A (4 Years) | 54,788 |
| Boulder Valley School District RE-2 Director District C (4 Years) | 54,364 |
| Boulder Valley School District RE-2 Director District G (4 Years) | 54,281 |
| Boulder Valley School District RE-2 Director District D (4 Years) | 53,940 |
