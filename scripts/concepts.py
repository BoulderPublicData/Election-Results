"""
Concept catalog — source-neutral names for contests that appear in BOTH the
Boulder County SoVs and the Colorado SOS precinct files.

The skill convention:

    "A concept catalog that just renames variables across sources is a foot-gun.
     Every concept entry should document what is and is not comparable —
     ... 'IPEDS Non-Resident Alien ≠ CDHE Non-Resident.'"

So each Concept entry below carries:
- A short, source-neutral `name` (snake_case).
- A 1-line `description`.
- The literal contest titles that appear in Boulder County / SOS files
  (regex-friendly patterns; case-insensitive substring matching).
- A `caveats` paragraph spelling out what's NOT comparable across sources.

To use:

    from scripts.concepts import CONCEPTS, concept_for
    c = concept_for("Presidential Electors", source="boulder_county")
    if c:
        print(c.name, c.caveats)

Or filter your tidy CSV by canonical concept name:

    df["concept"] = df.apply(
        lambda r: (concept_for(r["contest"], r["data_source"]) or _).name,
        axis=1,
    )

The catalog is exported to `data/lookups/concepts.json` by
`scripts/export_lookups.py` so non-Python consumers can use it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Concept:
    name: str                          # snake_case canonical id
    description: str                   # one line
    boulder_county_patterns: tuple[str, ...] = field(default_factory=tuple)
    secretary_of_state_patterns: tuple[str, ...] = field(default_factory=tuple)
    caveats: str = ""                  # what's NOT comparable across sources
    tier: str = "federal"              # federal / state / county / city / district

    def to_dict(self) -> dict:
        return asdict(self)


# Order is informational only — the lookup is by-name.
CONCEPTS: tuple[Concept, ...] = (
    Concept(
        name="presidential_electors",
        description="Electors for President and Vice President of the United States.",
        boulder_county_patterns=("Presidential Electors", "President.*Vice President"),
        secretary_of_state_patterns=(
            "President.*United States.*Vice President",
            "President of the United States",
        ),
        caveats=(
            "Boulder presents the elector slate as a single candidate "
            "(`Joseph R. Biden / Kamala D. Harris`); SOS lists the "
            "presidential candidate alone (`Joseph R. Biden`). Vote totals "
            "match exactly when aggregated to the candidate level, but the "
            "candidate strings cannot be joined directly — strip the running-"
            "mate suffix from Boulder rows before joining."
        ),
        tier="federal",
    ),
    Concept(
        name="us_senator",
        description="United States Senator for Colorado.",
        boulder_county_patterns=("United States Senator", "U[.]?S[.]? Senator"),
        secretary_of_state_patterns=("United States Senator", "U[.]?S[.]? Senator"),
        caveats="Cleanly comparable across sources.",
        tier="federal",
    ),
    Concept(
        name="us_representative",
        description="United States Representative — Boulder is mostly in CO-2, "
                    "with a small piece historically in CO-4.",
        boulder_county_patterns=(
            r"Representative to the \d+th Congress",
            "United States Representative",
        ),
        secretary_of_state_patterns=(
            r"Representative to the \d+th Congress",
            "United States Representative",
        ),
        caveats=(
            "District numbers (`113th Congress`, `114th Congress`, etc.) change "
            "by election; group on this concept to avoid having to enumerate "
            "every Congress. District boundaries also shift after each census "
            "(2010, 2020) so historical comparisons across boundary years are "
            "geographic-area comparisons, not constituency comparisons."
        ),
        tier="federal",
    ),
    Concept(
        name="governor",
        description="Governor / Lieutenant Governor of Colorado.",
        boulder_county_patterns=("Governor", "Governor/Lieutenant Governor"),
        secretary_of_state_patterns=("Governor", "Governor/Lieutenant Governor"),
        caveats=(
            "Like president, Boulder presents the ticket as one candidate "
            "(`Polis/Primavera`); SOS varies. Aggregate to candidate level "
            "after splitting the slash."
        ),
        tier="state",
    ),
    Concept(
        name="attorney_general",
        description="Colorado Attorney General.",
        boulder_county_patterns=("Attorney General",),
        secretary_of_state_patterns=("Attorney General",),
        caveats="Cleanly comparable.",
        tier="state",
    ),
    Concept(
        name="secretary_of_state",
        description="Colorado Secretary of State.",
        boulder_county_patterns=("Secretary of State",),
        secretary_of_state_patterns=("Secretary of State",),
        caveats="Cleanly comparable.",
        tier="state",
    ),
    Concept(
        name="state_treasurer",
        description="Colorado State Treasurer.",
        boulder_county_patterns=("State Treasurer", "Treasurer of the State"),
        secretary_of_state_patterns=("State Treasurer", "Treasurer of the State"),
        caveats="Cleanly comparable.",
        tier="state",
    ),
    Concept(
        name="state_senator",
        description="Colorado State Senator.",
        boulder_county_patterns=("State Senate",),
        secretary_of_state_patterns=("State Senator", "State Senate"),
        caveats=(
            "District boundaries are redrawn after each census. Cross-decennial "
            "comparisons need a precinct-to-district crosswalk for each year."
        ),
        tier="state",
    ),
    Concept(
        name="state_representative",
        description="Colorado State Representative.",
        boulder_county_patterns=("State Representative",),
        secretary_of_state_patterns=("State Representative",),
        caveats="Same caveat as state senator on redistricting.",
        tier="state",
    ),
    Concept(
        name="regent_university_of_colorado",
        description="Regent of the University of Colorado.",
        boulder_county_patterns=("Regent.*University of Colorado",),
        secretary_of_state_patterns=("Regent.*University of Colorado",),
        caveats="Cleanly comparable.",
        tier="state",
    ),
    Concept(
        name="district_attorney",
        description="Boulder County District Attorney (20th Judicial District).",
        boulder_county_patterns=("District Attorney",),
        secretary_of_state_patterns=("District Attorney",),
        caveats="Cleanly comparable.",
        tier="county",
    ),
    Concept(
        name="county_commissioner",
        description="Boulder County Commissioner (district seats).",
        boulder_county_patterns=("County Commissioner",),
        secretary_of_state_patterns=(),  # SOS doesn't publish county-level offices
        caveats=(
            "SOS does NOT publish precinct-level county-commissioner results — "
            "the Boulder County file is the only source. Reconciliation cross-"
            "checks therefore only work BoCo→BoCo for this concept."
        ),
        tier="county",
    ),
    Concept(
        name="city_of_boulder_council",
        description="City of Boulder Council members (at-large).",
        boulder_county_patterns=("City of Boulder Council",),
        secretary_of_state_patterns=(),
        caveats=(
            "City-level office; only published in Boulder County files. "
            "Starting in 2023, the Boulder Mayor race became RCV — see "
            "`city_of_boulder_mayor` for that. Council remains plurality."
        ),
        tier="city",
    ),
    Concept(
        name="city_of_boulder_mayor",
        description="City of Boulder Mayor (RCV since 2023).",
        boulder_county_patterns=("City of Boulder Mayor",),
        secretary_of_state_patterns=(),
        caveats=(
            "First-ever RCV election in 2023. RCV rows in the harmonized "
            "schema use `contest_type = 'ranked_choice'` and suffix "
            "`candidate_or_option` with `| Round N` (intermediate rounds, "
            "may have NEGATIVE votes for ballots transferring away) or "
            "`| Final` (the candidate's final round total). Sum only `| Final` "
            "rows to get totals comparable to a plurality race."
        ),
        tier="city",
    ),
    Concept(
        name="city_of_longmont_council",
        description="City of Longmont Council.",
        boulder_county_patterns=("City of Longmont Council",),
        secretary_of_state_patterns=(),
        caveats="City-level office; only Boulder County files.",
        tier="city",
    ),
    Concept(
        name="city_of_louisville_council",
        description="City of Louisville City Council.",
        boulder_county_patterns=("City of Louisville.*Council",),
        secretary_of_state_patterns=(),
        caveats="City-level office; only Boulder County files.",
        tier="city",
    ),
    Concept(
        name="city_of_lafayette_council",
        description="City of Lafayette City Council.",
        boulder_county_patterns=("City of Lafayette Council",),
        secretary_of_state_patterns=(),
        caveats="City-level office; only Boulder County files.",
        tier="city",
    ),
)


# Compiled patterns for cheap lookup. We compile per-source so the lookup
# returns the right concept even when the same contest name happens to match
# multiple concepts (rare, but defensive).
_BOCO_PATTERNS: list[tuple[re.Pattern, Concept]] = [
    (re.compile(pat, re.IGNORECASE), c)
    for c in CONCEPTS for pat in c.boulder_county_patterns
]
_SOS_PATTERNS: list[tuple[re.Pattern, Concept]] = [
    (re.compile(pat, re.IGNORECASE), c)
    for c in CONCEPTS for pat in c.secretary_of_state_patterns
]


def concept_for(contest: str, source: str = "boulder_county") -> Concept | None:
    """Return the matching Concept for a contest title (or None).

    `source` selects which pattern table to scan — the same contest text might
    parse differently in BoCo vs. SOS files. Pass the row's `data_source` value.
    """
    if contest is None or not isinstance(contest, str):
        return None
    table = _BOCO_PATTERNS if source == "boulder_county" else _SOS_PATTERNS
    for rx, c in table:
        if rx.search(contest):
            return c
    return None


def by_name(name: str) -> Concept | None:
    """Look up a concept by its snake_case canonical name."""
    for c in CONCEPTS:
        if c.name == name:
            return c
    return None
