"""
Source URL registry.

The single source of truth for where each year's raw file came from.
Adding a new election year? Add an entry here and the rest of the pipeline picks it up.

The URLs are mirror-stable upstream paths (assets.bouldercounty.gov, coloradosos.gov).
If they ever 404, the README tracks the historical canonical URL and these can be
patched without touching parser code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Supplement:
    """A later file that re-reports some of a source's contests: a recount or
    an amended Statement of Votes. It covers only the contests it re-reports,
    so it is merged over the source **by contest** (scripts/overlay.py): every
    contest it names replaces that contest in the source file, and every other
    contest keeps the source file's rows. Both files stay in data/original/."""

    kind: Literal["recount", "amended"]
    url: str
    local_filename: str  # file under config.ORIGINAL_SUBDIRS[data_source]


@dataclass(frozen=True)
class Source:
    year: int
    election_type: Literal["general", "primary", "coordinated", "presidential_primary"]
    data_source: Literal["boulder_county", "secretary_of_state"]
    url: str
    local_filename: str  # file under config.ORIGINAL_SUBDIRS[data_source]
    # Applied in order, each over the result of the previous one.
    supplements: tuple[Supplement, ...] = ()

    def file_records(self) -> list[Source]:
        """This source and each supplement as a single-file Source (same year,
        type and data source; the supplement's URL and filename), for code
        that handles raw files one at a time: fetch, the manifest, rejects."""
        return [self] + [
            Source(self.year, self.election_type, self.data_source, sup.url, sup.local_filename)
            for sup in self.supplements
        ]


# Boulder County Statement of Votes.
# Note: 2005, 2007, 2009 are coordinated elections published only as PDFs.
# 2023 and 2024: the county posted the full SoV in November, then a recount
# (2023) or amended (2024) SoV in December that re-reports only the recounted
# or amended contests. The full file is the source; the December file is a
# Supplement merged over it by contest (#42, #43).
BOULDER_COUNTY: list[Source] = [
    Source(
        2005,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2005-election-sov.pdf",
        "2005-coordinated-sov.pdf",
    ),
    Source(
        2007,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2007-election-sov.pdf",
        "2007-coordinated-sov.pdf",
    ),
    Source(
        2008,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/12/2008-general-election-sov.xls",
        "2008-general-sov.xls",
    ),
    Source(
        2009,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2009-election-sov.pdf",
        "2009-coordinated-sov.pdf",
    ),
    Source(
        2010,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/09/2010-general-sov.xls",
        "2010-general-sov.xls",
    ),
    Source(
        2011,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2011-election-sov.xls",
        "2011-coordinated-sov.xls",
    ),
    Source(
        2012,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2012-general-election-sov.xls",
        "2012-general-sov.xls",
    ),
    Source(
        2013,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2013-election-sov.xls",
        "2013-coordinated-sov.xls",
    ),
    Source(
        2014,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2014-general-election-sov.xls",
        "2014-general-sov.xls",
    ),
    Source(
        2015,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2015-election-sov.xls",
        "2015-coordinated-sov.xls",
    ),
    Source(
        2016,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/03/2016-general-election-results-final-sov.xls",
        "2016-general-sov.xls",
    ),
    Source(
        2017,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2017/11/Results_SOV_Final.xlsx",
        "2017-coordinated-sov.xlsx",
    ),
    Source(
        2018,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2018/11/2018-General-Election-Official-Statement-Of-Votes.xlsx",
        "2018-general-sov.xlsx",
    ),
    Source(
        2019,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2019/11/2019C-Official-Statement-Of-Votes-SOV.xls",
        "2019-coordinated-sov.xls",
    ),
    Source(
        2020,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2020/11/2020-Boulder-County-General-Election-Official-Statement-of-Votes.xlsx",
        "2020-general-sov.xlsx",
    ),
    Source(
        2021,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2021/11/2021-Boulder-County-Coordinated-Election-Official-Statement-of-Votes-1.xlsx",
        "2021-coordinated-sov.xlsx",
    ),
    Source(
        2022,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2022/12/2022G-Boulder-County-Official-Statement-of-Votes.xlsx",
        "2022-general-sov.xlsx",
    ),
    Source(
        2023,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2023/11/2023C-Boulder-County-Official-Statement-of-Votes.xlsx",
        "2023-coordinated-sov.xlsx",
        supplements=(
            # City of Boulder Council Candidates only (December 2023 recount).
            Supplement(
                "recount",
                "https://assets.bouldercounty.gov/wp-content/uploads/2023/12/2023C-Boulder-County-Official-Statement-of-Votes-Recount.xlsx",
                "2023-coordinated-sov-recount.xlsx",
            ),
        ),
    ),
    Source(
        2024,
        "general",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2024/11/2024G-Boulder-County-Official-Statement-of-Votes.xlsx",
        "2024-general-sov.xlsx",
        supplements=(
            # Town of Superior - Trustee and Town of Erie - Council Member
            # District 1 only (amended December 2024).
            Supplement(
                "amended",
                "https://assets.bouldercounty.gov/wp-content/uploads/2024/12/2024G-Boulder-County-Amended-Statement-of-Votes.xlsx",
                "2024-general-sov-amended.xlsx",
            ),
        ),
    ),
    Source(
        2025,
        "coordinated",
        "boulder_county",
        "https://assets.bouldercounty.gov/wp-content/uploads/2025/11/2025C-Boulder-County-Official-Statement-of-Votes.xlsx",
        "2025-coordinated-sov.xlsx",
    ),
]

# Colorado Secretary of State precinct-level results.
# Even years only — SOS publishes precinct files only for general elections.
SECRETARY_OF_STATE: list[Source] = [
    Source(
        2004,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2004/2004GeneralPrecinctBallotsCast.xlsx",
        "2004-general-precinct-results.xlsx",
    ),
    Source(
        2006,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2006/2006GeneralPrecinctBallotsCast.xlsx",
        "2006-general-precinct-results.xlsx",
    ),
    Source(
        2008,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2008/2008GeneralPrecinctTurnout.xlsx",
        "2008-general-precinct-results.xlsx",
    ),
    Source(
        2010,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2010/general/2010GeneralPrecinctTurnout.xlsx",
        "2010-general-precinct-results.xlsx",
    ),
    Source(
        2012,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2012/2012GeneralPrecinctLevelTurnout.xlsx",
        "2012-general-precinct-results.xlsx",
    ),
    Source(
        2014,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2014/2014GeneralPrecinctTurnout.xlsx",
        "2014-general-precinct-results.xlsx",
    ),
    Source(
        2016,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2016/General/2016GeneralTurnoutPrecinctLevel.xlsx",
        "2016-general-precinct-results.xlsx",
    ),
    Source(
        2018,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2018/2018GEPrecinctLevelResults.xlsx",
        "2018-general-precinct-results.xlsx",
    ),
    Source(
        2020,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2020/2020GEPrecinctLevelResultsPosted.xlsx",
        "2020-general-precinct-results.xlsx",
    ),
    Source(
        2024,
        "general",
        "secretary_of_state",
        "https://www.coloradosos.gov/pubs/elections/Results/2024/2024GeneralPrecinctVoterTurnout.xlsx",
        "2024-general-precinct-results.xlsx",
    ),
]

ALL_SOURCES: list[Source] = BOULDER_COUNTY + SECRETARY_OF_STATE


# Best-known certification dates per year (used for election_date metadata).
# Boulder County typically certifies ~3 weeks after the election day in November.
# These are approximate election days (first Tuesday after first Monday in November).
ELECTION_DATES: dict[int, str] = {
    2004: "2004-11-02",
    2005: "2005-11-01",
    2006: "2006-11-07",
    2007: "2007-11-06",
    2008: "2008-11-04",
    2009: "2009-11-03",
    2010: "2010-11-02",
    2011: "2011-11-01",
    2012: "2012-11-06",
    2013: "2013-11-05",
    2014: "2014-11-04",
    2015: "2015-11-03",
    2016: "2016-11-08",
    2017: "2017-11-07",
    2018: "2018-11-06",
    2019: "2019-11-05",
    2020: "2020-11-03",
    2021: "2021-11-02",
    2022: "2022-11-08",
    2023: "2023-11-07",
    2024: "2024-11-05",
    2025: "2025-11-04",
    2026: "2026-11-03",
}


# Colorado's June primaries (last Tuesday in June). Not ingested yet (AGENTS
# §5 item 3), but discovery can now classify a primary file (#29), so keep its
# date separate from the November general's.
PRIMARY_ELECTION_DATES: dict[int, str] = {
    2026: "2026-06-30",
}

# Colorado's March presidential primaries (Super Tuesday). No data is ingested
# here; the type exists so this repo and Cast-Vote-Records (which holds the
# 2024 presidential primary CVR) share one election-key vocabulary.
PRESIDENTIAL_PRIMARY_ELECTION_DATES: dict[int, str] = {
    2024: "2024-03-05",
}


def election_date_for(year: int, election_type: str) -> str:
    """Election day for (year, election_type); a placeholder when unknown."""
    if election_type == "primary":
        return PRIMARY_ELECTION_DATES.get(year, f"{year}-06-XX")
    if election_type == "presidential_primary":
        return PRESIDENTIAL_PRIMARY_ELECTION_DATES.get(year, f"{year}-03-XX")
    return ELECTION_DATES.get(year, f"{year}-11-XX")


# The election key shared with BoulderPublicData/Cast-Vote-Records (#34):
# lowercase "{year}-{type}", type one of ELECTION_TYPES, with "_" written "-"
# ("2024-presidential-primary"). File stems, cache folders and CLI --election
# arguments all use it.
ELECTION_TYPES: tuple[str, ...] = ("general", "primary", "coordinated", "presidential_primary")
_KEY_RE = re.compile(
    r"^(?P<year>\d{4})-(?P<type>general|primary|coordinated|presidential[-_]primary)$"
)
# Raw election-night folders under data/original/ (immutable) are named
# "2016G" / "2015C"; this maps their letter to the type. The county writes the
# presidential primary "2024PP".
_LEGACY_CODE_RE = re.compile(r"^(?P<year>\d{4})(?P<kind>PP|[GCP])$")
_LEGACY_KIND = {
    "G": "general",
    "C": "coordinated",
    "P": "primary",
    "PP": "presidential_primary",
}


def election_key(year: int, election_type: str) -> str:
    """(2016, "general") → "2016-general";
    (2024, "presidential_primary") → "2024-presidential-primary"."""
    if election_type not in ELECTION_TYPES:
        raise ValueError(
            f"unknown election type {election_type!r}; expected one of {ELECTION_TYPES}"
        )
    return f"{int(year)}-{election_type.replace('_', '-')}"


def parse_election_key(key: str) -> tuple[int, str]:
    """ "2016-general" → (2016, "general"); "2024-presidential-primary" →
    (2024, "presidential_primary"). Also accepts the legacy folder code
    "2016G" / "2024PP" so old commands keep working."""
    s = key.strip()
    m = _KEY_RE.match(s.lower())
    if m:
        return int(m["year"]), m["type"].replace("-", "_")
    m = _LEGACY_CODE_RE.match(s.upper())
    if m:
        return int(m["year"]), _LEGACY_KIND[m["kind"]]
    raise ValueError(f"not an election key: {key!r} (expected e.g. '2016-general')")


def sources_for_year(year: int) -> list[Source]:
    return [s for s in ALL_SOURCES if s.year == year]


def find(year: int, data_source: str) -> Source | None:
    for s in ALL_SOURCES:
        if s.year == year and s.data_source == data_source:
            return s
    return None
