"""Concept catalog contract tests.

A regression here usually means a parser changed how it titles a contest;
either update the concept's patterns or the parser to keep the lookup working.
"""

from __future__ import annotations

from scripts.concepts import CONCEPTS, by_name, concept_for


def test_every_concept_has_at_least_one_pattern():
    for c in CONCEPTS:
        assert c.boulder_county_patterns or c.secretary_of_state_patterns, (
            f"concept {c.name!r} has no patterns and would never match anything"
        )


def test_every_concept_has_caveats():
    """The whole point of the catalog: caveats > renames."""
    for c in CONCEPTS:
        assert c.caveats, f"concept {c.name!r} has no caveats — add one"


def test_concept_names_are_unique():
    names = [c.name for c in CONCEPTS]
    assert len(names) == len(set(names)), "duplicate concept names"


def test_by_name_roundtrip():
    for c in CONCEPTS:
        assert by_name(c.name) is c


def test_concept_for_presidential_electors_boulder():
    c = concept_for("Presidential Electors", source="boulder_county")
    assert c is not None
    assert c.name == "presidential_electors"


def test_concept_for_presidential_sos():
    c = concept_for("President of the United States/Vice President",
                    source="secretary_of_state")
    assert c is not None
    assert c.name == "presidential_electors"


def test_concept_for_returns_none_on_unknown():
    assert concept_for("Some Local Ballot Issue 4Q", source="boulder_county") is None


def test_concept_for_handles_none_and_nan():
    import math
    assert concept_for(None) is None
    assert concept_for(math.nan) is None  # type: ignore[arg-type]


def test_state_representative_vs_senator_distinct():
    """Two different concepts share words; make sure we don't conflate them."""
    rep = concept_for("State Representative District 10", source="boulder_county")
    sen = concept_for("State Senate District 17", source="boulder_county")
    assert rep is not None and sen is not None
    assert rep.name != sen.name


def test_county_commissioner_is_boulder_only():
    """SOS doesn't publish county-level offices — the SOS pattern list should
    be empty so we never falsely match an SOS row."""
    cc = by_name("county_commissioner")
    assert cc is not None
    assert cc.secretary_of_state_patterns == ()
    assert concept_for("County Commissioner District 1",
                       source="secretary_of_state") is None


def test_presidential_patterns_skip_elector_measures():
    assert concept_for("President/Vice President", source="secretary_of_state").name == \
        "presidential_electors"
    assert concept_for("PRESIDENTIAL ELECTORS/ PRESIDENTIAL ELECTORS (VICE)",
                       source="secretary_of_state").name == "presidential_electors"
    assert concept_for("Amend 36 Selection of Presidential Electors",
                       source="secretary_of_state") is None


def test_us_representative_matches_boulder_titles():
    for title in ("Representative to the 113th United States Congress - District 2",
                  "REPRESENTATIVE TO THE US CONGRESS - DISTRICT 4",
                  "Representative to the United States Congress - District 2"):
        assert concept_for(title, source="boulder_county").name == "us_representative"


def _contests_by_source():
    import pandas as pd

    from scripts.config import STATEMENTS_OF_VOTES
    files = sorted(STATEMENTS_OF_VOTES.glob("[0-9]*.csv"))
    if not files:
        return None
    out: dict[str, set[str]] = {}
    for f in files:
        d = pd.read_csv(f, usecols=["contest", "data_source"], low_memory=False).drop_duplicates()
        for r in d.itertuples(index=False):
            out.setdefault(r.data_source, set()).add(r.contest)
    return out


def test_every_concept_matches_a_contest_in_each_source_it_claims():
    """#28: presidential_electors matched no SOS contest and us_representative
    no Boulder contest. Runs against the processed CSVs; skips without them."""
    import re

    import pytest
    contests = _contests_by_source()
    if contests is None:
        pytest.skip("processed CSVs not present; run the pipeline first")
    for c in CONCEPTS:
        for source, pats in (("boulder_county", c.boulder_county_patterns),
                             ("secretary_of_state", c.secretary_of_state_patterns)):
            if not pats:
                continue
            hits = [t for t in contests.get(source, ())
                    if any(re.search(p, t, re.IGNORECASE) for p in pats)]
            assert hits, f"{c.name} matches no {source} contest"
