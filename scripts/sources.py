"""
Source URL registry.

The single source of truth for where each year's raw file came from.
Adding a new election year? Add an entry here and the rest of the pipeline picks it up.

The URLs are mirror-stable upstream paths (assets.bouldercounty.gov, coloradosos.gov).
If they ever 404, the README tracks the historical canonical URL and these can be
patched without touching parser code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Source:
    year: int
    election_type: Literal["general", "primary", "coordinated"]
    data_source: Literal["boulder_county", "secretary_of_state"]
    url: str
    local_filename: str  # path under original-data/{data_source-kebab}/


# Boulder County Statement of Votes.
# Note: 2005, 2007, 2009 are coordinated elections published only as PDFs.
# 2024 is the AMENDED SoV (post-recount); supersedes the original.
BOULDER_COUNTY: list[Source] = [
    Source(2005, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2005-election-sov.pdf",
           "2005-coordinated-sov.pdf"),
    Source(2007, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2007-election-sov.pdf",
           "2007-coordinated-sov.pdf"),
    Source(2008, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/12/2008-general-election-sov.xls",
           "2008-general-sov.xls"),
    Source(2009, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2009-election-sov.pdf",
           "2009-coordinated-sov.pdf"),
    Source(2010, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/09/2010-general-sov.xls",
           "2010-general-sov.xls"),
    Source(2011, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2011-election-sov.xls",
           "2011-coordinated-sov.xls"),
    Source(2012, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2012-general-election-sov.xls",
           "2012-general-sov.xls"),
    Source(2013, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2013-election-sov.xls",
           "2013-coordinated-sov.xls"),
    Source(2014, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2014-general-election-sov.xls",
           "2014-general-sov.xls"),
    Source(2015, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2015-election-sov.xls",
           "2015-coordinated-sov.xls"),
    Source(2016, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2016-general-election-results-final-sov.xls",
           "2016-general-sov.xls"),
    Source(2017, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2017/11/Results_SOV_Final.xlsx",
           "2017-coordinated-sov.xlsx"),
    Source(2018, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2018/11/2018-General-Election-Official-Statement-Of-Votes.xlsx",
           "2018-general-sov.xlsx"),
    Source(2019, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2019/11/2019C-Official-Statement-Of-Votes-SOV.xls",
           "2019-coordinated-sov.xls"),
    Source(2020, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2020/11/2020-Boulder-County-General-Election-Official-Statement-of-Votes.xlsx",
           "2020-general-sov.xlsx"),
    Source(2021, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2021/11/2021-Boulder-County-Coordinated-Election-Official-Statement-of-Votes-1.xlsx",
           "2021-coordinated-sov.xlsx"),
    Source(2022, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2022/12/2022G-Boulder-County-Official-Statement-of-Votes.xlsx",
           "2022-general-sov.xlsx"),
    Source(2023, "coordinated", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2023/12/2023C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx",
           "2023-coordinated-sov.xlsx"),
    Source(2024, "general", "boulder_county",
           "https://assets.bouldercounty.gov/wp-content/uploads/2024/12/2024G-Boulder-County-Amended-Statement-of-Votes.xlsx",
           "2024-general-sov.xlsx"),
]

# Colorado Secretary of State precinct-level results.
# Even years only — SOS publishes precinct files only for general elections.
SECRETARY_OF_STATE: list[Source] = [
    Source(2004, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2004/2004GeneralPrecinctBallotsCast.xlsx",
           "2004-general-precinct-results.xlsx"),
    Source(2006, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2006/2006GeneralPrecinctBallotsCast.xlsx",
           "2006-general-precinct-results.xlsx"),
    Source(2008, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2008/2008GeneralPrecinctTurnout.xlsx",
           "2008-general-precinct-results.xlsx"),
    Source(2010, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2010/general/2010GeneralPrecinctTurnout.xlsx",
           "2010-general-precinct-results.xlsx"),
    Source(2012, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2012/2012GeneralPrecinctLevelTurnout.xlsx",
           "2012-general-precinct-results.xlsx"),
    Source(2014, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2014/2014GeneralPrecinctTurnout.xlsx",
           "2014-general-precinct-results.xlsx"),
    Source(2016, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2016/General/2016GeneralTurnoutPrecinctLevel.xlsx",
           "2016-general-precinct-results.xlsx"),
    Source(2018, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2018/2018GEPrecinctLevelResults.xlsx",
           "2018-general-precinct-results.xlsx"),
    Source(2020, "general", "secretary_of_state",
           "https://www.coloradosos.gov/pubs/elections/Results/2020/2020GEPrecinctLevelResultsPosted.xlsx",
           "2020-general-precinct-results.xlsx"),
]

ALL_SOURCES: list[Source] = BOULDER_COUNTY + SECRETARY_OF_STATE


# Best-known certification dates per year (used for election_date metadata).
# Boulder County typically certifies ~3 weeks after the election day in November.
# These are approximate election days (first Tuesday after first Monday in November).
ELECTION_DATES: dict[int, str] = {
    2004: "2004-11-02", 2005: "2005-11-01", 2006: "2006-11-07",
    2007: "2007-11-06", 2008: "2008-11-04", 2009: "2009-11-03",
    2010: "2010-11-02", 2011: "2011-11-01", 2012: "2012-11-06",
    2013: "2013-11-05", 2014: "2014-11-04", 2015: "2015-11-03",
    2016: "2016-11-08", 2017: "2017-11-07", 2018: "2018-11-06",
    2019: "2019-11-05", 2020: "2020-11-03", 2021: "2021-11-02",
    2022: "2022-11-08", 2023: "2023-11-07", 2024: "2024-11-05",
}


def sources_for_year(year: int) -> list[Source]:
    return [s for s in ALL_SOURCES if s.year == year]


def find(year: int, data_source: str) -> Source | None:
    for s in ALL_SOURCES:
        if s.year == year and s.data_source == data_source:
            return s
    return None
