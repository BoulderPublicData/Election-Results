"""
Merge a supplement — a recount or amended Statement of Votes — over a parsed
source file, by contest (#42, #43).

The county sometimes re-posts part of an election's results after the canvass:
a recount SoV (2023) or an amended SoV (2024) that lists **only** the contests
that changed. Neither file is complete on its own, and both stay in
``data/original/`` unchanged (AGENTS.md §2.5). The registry
(``scripts/sources.py``) lists the full file as the ``Source`` and the later
file as one of its ``supplements``; ``clean.clean_source`` parses both with the
same parser and calls :func:`overlay_by_contest`:

- every contest the supplement reports replaces that contest's rows in the
  base, whole (all precincts and choices), so no row of the superseded count
  survives;
- every other contest keeps the base file's rows;
- a supplement contest the base doesn't have is an error, not a new contest:
  a renamed or mistyped title would otherwise count the contest twice.

Supplement rows take the place of the base row with the same (precinct,
contest, choice) key, so the merged frame keeps the base file's row order.
``scripts/reconcile.py`` applies the same rule, independently, to the raw
workbooks' totals.
"""

from __future__ import annotations

import pandas as pd

KEY = ["precinct_id", "contest", "candidate_or_option"]


def _titles(df: pd.DataFrame) -> pd.Series:
    return df["contest"].astype("string").str.strip()


def overlay_by_contest(
    base: pd.DataFrame, supplement: pd.DataFrame, *, label: str = "supplement"
) -> tuple[pd.DataFrame, list[str]]:
    """Return (merged frame, contests replaced, in the supplement's order).

    ``base`` and ``supplement`` are parser outputs with the same columns.
    Raises ``ValueError`` if the supplement is empty or names a contest that
    isn't in the base.
    """
    if supplement.empty:
        raise ValueError(f"{label}: no rows to merge")
    base_titles = _titles(base)
    sup_titles = _titles(supplement)
    replaced = list(dict.fromkeys(sup_titles.dropna()))
    missing = sorted(set(replaced) - set(base_titles.dropna()))
    if missing:
        raise ValueError(
            f"{label}: contest(s) not in the base file, so they can't replace anything: {missing}"
        )

    drop = base_titles.isin(replaced).fillna(False).to_numpy()
    kept = base[~drop]
    # Order: each supplement row takes the position of the base row it
    # replaces; rows with no counterpart go after the base rows.
    position = {k: i for i, k in enumerate(base[KEY].itertuples(index=False, name=None))}
    n = len(base)
    sup_pos = [
        position.get(k, n + i)
        for i, k in enumerate(supplement[KEY].itertuples(index=False, name=None))
    ]
    merged = pd.concat(
        [
            kept.assign(_pos=[i for i, d in enumerate(drop) if not d]),
            supplement.assign(_pos=sup_pos),
        ],
        ignore_index=True,
    )
    merged = merged.sort_values("_pos", kind="stable").drop(columns="_pos")
    merged = merged.reset_index(drop=True)
    merged.attrs.update(base.attrs)
    return merged, replaced


def overlay_totals(base: pd.DataFrame, supplement: pd.DataFrame) -> pd.DataFrame:
    """The same rule on contest-level totals (any frame with a ``contest``
    column): drop the base rows of every contest the supplement reports and
    append the supplement's rows. Used by reconcile, which needs no row order."""
    replaced = set(_titles(supplement).dropna())
    missing = sorted(replaced - set(_titles(base).dropna()))
    if missing:
        raise ValueError(f"supplement contest(s) not in the base file: {missing}")
    keep = ~_titles(base).isin(replaced).fillna(False)
    return pd.concat([base[keep], supplement], ignore_index=True)
