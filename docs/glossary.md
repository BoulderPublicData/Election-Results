# Glossary

Shared vocabulary for the BoulderPublicData election repositories — this one
(precinct-level Statements of Votes and election-night snapshots) and
[Cast-Vote-Records](https://github.com/BoulderPublicData/Cast-Vote-Records)
(ballot-level records). The data dictionary keeps a short version in
[§0](data-dictionary.md#0-glossary).

## Elections

| Term | Meaning |
|---|---|
| **Election key** | The identifier both repositories use for one election: lowercase `{year}-{type}`, e.g. `2016-general`, `2023-coordinated`, `2024-presidential-primary` (the type `presidential_primary` is written with a hyphen in the key). File stems (`2016-general-boulder-county.csv`), cache folders and every `--election` option use it. Raw folders keep the names they were published or collected under (`2016G`); code maps them (`scripts.sources.parse_election_key`). |
| **General election** | `general`: the even-year November election for federal, state and county offices. |
| **Primary election** | `primary`: the even-year June election in which each party picks its nominees. Not yet ingested here. |
| **Presidential primary** | `presidential_primary`: the March election, in a presidential year, in which each party's voters choose among its presidential candidates (2024-03-05). Cast-Vote-Records holds the 2024 presidential primary; this repository ingests none. |
| **Coordinated election** | `coordinated`: the odd-year November election the county runs on behalf of cities, school districts and special districts (and statewide ballot measures). |
| **Canvass / certification** | The post-election review in which the county reconciles every ballot and certifies the official results, usually 2-3 weeks after election day. |
| **Recount / amended SoV** | A Statement of Votes reissued after a recount or amendment (2023 and 2024 here). It lists only the contests that changed, so it supersedes the original for those contests only: it is merged over the full SoV by contest. |
| **UOCAVA** | Uniformed and Overseas Citizens Absentee Voting Act: ballots from military and overseas voters, which can arrive after election night. |

## Results files

| Term | Meaning |
|---|---|
| **SoV (Statement of Votes)** | The county's official, certified results: votes for every candidate and ballot question in every precinct. |
| **SOS** | The Colorado Secretary of State, which publishes its own precinct-level results for general elections. |
| **CVR (cast vote record)** | One record per ballot with the voter's marks in each contest, anonymized; the subject of the Cast-Vote-Records repository. Summing CVRs per contest should reproduce the SoV totals. |
| **Election-night snapshot** | One published update of the county's results website ("Last Updated" time); cumulative, county-wide, not by precinct. |

## Places

| Term | Meaning |
|---|---|
| **Precinct** | The smallest geographic voting unit; each voter belongs to one. IDs are 10 digits (`2181007800`) except in Boulder's 2007-2012 files, which use 3-digit codes (`073`). |
| **Composite precinct** | Several precincts reported together as one unit (often so a very small group of voters can't be identified); `precinct_id = "2181007800, 2181207403"`. |
| **Pseudo-precinct** | A results row that isn't a place: property-owner / landowner ballots in special-district contests (`Property Owner`, `Landowner`, `RMFPD`, …) or an SOS summary row (`SUM`, `Provisional`). `is_pseudo_precinct = True`. |

## Contests

| Term | Meaning |
|---|---|
| **Candidate contest** | A race between named candidates (`contest_type = candidate`). |
| **Ballot measure** | A yes/no question — amendment, proposition, referendum or local ballot issue (`measure`). "For/Against the Measure" is recorded as Yes/No. |
| **Retention** | A yes/no vote on whether a judge keeps their seat (`retention`). |
| **Recall** | A vote on removing an official before the end of their term (`recall`). |
| **RCV (ranked-choice voting)** | Voters rank candidates; the last-place candidate is eliminated round by round and their ballots move to each voter's next choice until one candidate has a majority (`ranked_choice`). Boulder first used it for mayor in 2023. |
| **Write-in** | A candidate not printed on the ballot whose name voters write in; results files usually lump write-ins together. |
