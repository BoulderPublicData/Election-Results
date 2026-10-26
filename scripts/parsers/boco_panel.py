"""
Boulder County panel-format SoV parser (2008, 2010, 2011, 2012).

These XLS files predate the modern tidy export and report results as repeating
"panels" — page banner, contest title, a row of column headers (Precinct, the
vote-method / turnout columns, then one column per candidate or Yes/No), the
per-precinct rows, and on the last page of each contest a ``Totals`` row.
2008 and 2010 print one page per panel (about 34 precincts each, so a contest
spans seven or more panels, and contests with many candidates repeat the whole
run of pages for the next group of candidates); 2011 and 2012 print one panel
per contest group.

**Column alignment (#20).** The header labels and the data values do *not* sit
in the same spreadsheet columns: the export merged header cells, so the 2008
"Total Ballots Cast" header is in column 10 while its values are in column 8,
and some value columns have no header above them at all. Reading a value by
the label above it (what the previous parser did) shifted every column after
the first gap. The original ``Cleaning.ipynb`` solved this per contest with
hand-picked ``iloc`` positions; this parser does the same mapping generically:

- the header's non-empty cells, in order, are the panel's labels;
- each data row's non-empty cells, in order, are its values;
- the i-th value belongs to the i-th label.

Every data row in the four files has exactly one value per label (the
``Percent Turnout`` cell is omitted on ``Totals`` rows and the 2012 file writes
the ``%`` sign in a cell of its own; both are handled). A row whose width
doesn't match its header is sent to the reject port rather than guessed at.
Some 2008 rows print the precinct number alone, with its values on a row below;
those are joined back together.

The ``Totals`` rows are not emitted as data, but :func:`published_totals`
exposes them so ``scripts/reconcile.py`` can check that the per-precinct rows
add up to the county's own published totals for every candidate.

**Candidate labels (#24).** Party sits in the label in several ways —
``"REP\\nKen Buck"`` (2010), ``"Bruce E. Lohmiller - GRN"`` (2010),
``"Mark Udall Democratic"`` (2008), ``"Jared Polis    Democratic"`` (2012).
Only *known* party codes and names are split off (see :func:`split_party`);
anything else stays in the name, so ``FOR THE MEASURE`` is a Yes/No option
rather than party ``FOR``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..reject import Rejector
from ..reject import register as register_rejector
from ..schema import SourceMeta
from .common import (
    PARTY_MAP,
    add_provenance,
    clean_col,
    infer_contest_type,
    normalize_choice,
    normalize_party,
    read_excel,
)


def _read_raw(path: Path) -> pd.DataFrame:
    return read_excel(path, sheet_name=0, header=None)


def _find_panel_starts(raw: pd.DataFrame) -> list[int]:
    """Row indices where column-0 == 'Precinct' (case-insensitive)."""
    col0 = raw.iloc[:, 0].astype("string").str.strip().str.lower()
    return col0.index[col0 == "precinct"].tolist()


_BOILERPLATE_PREFIXES = (
    "precinct", "early voting", "election day", "absentee",
    "total number of voters", "precincts reporting",
    "boulder county", "canvass report", "general election",
    "coordinated election", "primary election", "page ",
)


def _contest_title(raw: pd.DataFrame, start: int) -> str:
    """The contest title sits 1-10 rows above the 'Precinct' header row, typically
    in column 0 or column 6. Walk upward and pick the first non-null, non-boilerplate
    cell. The window is wide because page-break headers can push the title up."""
    for offset in range(1, 11):
        idx = start - offset
        if idx < 0:
            break
        row = raw.iloc[idx]
        for col in (6, 0, 1, 2, 3, 4, 5, 7):
            if col >= raw.shape[1]:
                continue
            val = row.iloc[col]
            if pd.isna(val):
                continue
            text = str(val).strip()
            if not text:
                continue
            lower = text.lower()
            if any(lower.startswith(p) for p in _BOILERPLATE_PREFIXES):
                continue
            if lower in {"continued", "totals", "totals:", "total", "yes", "no"}:
                continue
            # Date or time stamp strings — skip.
            if "/" in text and len(text) < 25 and any(ch.isdigit() for ch in text):
                continue
            return clean_col(text)
    return f"<unknown contest at row {start}>"


# ---------------------------------------------------------------------------
# Header labels
# ---------------------------------------------------------------------------

def _label_kind(label: str) -> str:
    """Classify a cleaned header label: precinct / ballots_cast / active_voters /
    meta (other turnout columns) / row_total / candidate."""
    lo = label.strip().lower()
    if lo == "precinct":
        return "precinct"
    if lo in {"totals", "total"}:
        return "row_total"
    if lo.replace(" ", "") in {"registeredvoters"}:
        return "active_voters"
    if lo.replace(" ", "") == "percentturnout":
        return "percent"
    if lo.endswith("ballots cast") or lo.endswith("ballotscast") or lo.endswith("ballots"):
        return "ballots_cast" if lo.startswith("total") else "meta"
    return "candidate"


def _header_labels(raw: pd.DataFrame, start: int) -> list[str]:
    """The header row's non-empty cells in order, minus the 'Continued' marker.
    Raw text (with its embedded newlines) is kept for party splitting."""
    out: list[str] = []
    for v in raw.iloc[start].tolist():
        if pd.isna(v):
            continue
        text = str(v)
        if not text.strip() or text.strip().lower() == "continued":
            continue
        out.append(text)
    return out


# ---------------------------------------------------------------------------
# Party splitting (#24)
# ---------------------------------------------------------------------------

# Codes that may lead a label ("REP\nKen Buck") or trail it ("Robert Rank - REP").
_PARTY_CODES = {k for k in PARTY_MAP if re.fullmatch(r"[A-Z]{2,4}", k)} | {"NR"}

# Full party names that trail a label, as printed (some are truncated by the
# export). Longest first so "American Constitution" wins over "Constitution".
_TRAILING_PARTY_NAMES = sorted({
    "Democratic", "Republican", "Libertarian", "Green", "Unaffiliated", "Unity",
    "Constitution", "American Constitution", "American", "Prohibition",
    "Socialist Workers", "Boston Tea", "America's", "Socialism and",
    "U.S. Pacifist", "Socialist, USA", "Objectivist", "HeartQuake '08",
    "Justice", "Peace and Freedom", "American Third", "We the People",
    "Socialist Equality", "Independent /",
}, key=len, reverse=True)

# Labels the export truncated, resolved per year against the SOS file for the
# same election (which prints the party in full).
_TRUNCATED_PARTY: dict[int, dict[str, str]] = {
    2008: {"America's": "America's Independent",           # Alan Keyes
           "Socialism and": "Socialism and Liberation"},
    2010: {"Not": "NR"},                                     # Peter J. Carr (SOS: NR)
    2012: {"America's": "America's Party",                   # Tom Hoefling
           "Socialism and": "Socialism and Liberation",
           "American Third": "American Third Position",
           "American": "American Constitution",              # Virgil H. Goode Jr.
           "Independent /": "Independent / Republican"},     # Randall Terry
}

_LEADING_CODE_RE = re.compile(r"^\s*([A-Z]{2,4})\s*[\r\n]+\s*(.+?)\s*$", re.DOTALL)
_TRAILING_CODE_RE = re.compile(
    r"^(.+?)\s+-\s+([A-Za-z]{2,4}(?:\s*/\s*[A-Z]{2,4})*)\s*$", re.DOTALL)


def split_party(label: str, year: int | None = None) -> tuple[str, object]:
    """Split a panel header label into (candidate name, canonical party).

    Only known party codes / names are split off; a label with no recognizable
    party is returned whole with party NA. Yes/No style labels ("FOR THE
    MEASURE") are normalized to ``Yes`` / ``No``.
    """
    overrides = _TRUNCATED_PARTY.get(year or 0, {})
    text = str(label)
    choice = normalize_choice(clean_col(text))
    if choice in {"Yes", "No"}:
        return choice, pd.NA

    m = _LEADING_CODE_RE.match(text)
    if m and m.group(1) in _PARTY_CODES:
        return clean_col(m.group(2)), normalize_party(m.group(1))

    flat = clean_col(text)
    m = _TRAILING_CODE_RE.match(flat)
    if m:
        codes = [c.strip() for c in m.group(2).split("/")]
        if all(c in _PARTY_CODES or c in overrides for c in codes):
            party = " / ".join(overrides.get(c, c) for c in codes)
            return clean_col(m.group(1)), normalize_party(party)

    for name in _TRAILING_PARTY_NAMES:
        if flat == name or not flat.endswith(" " + name):
            continue
        party = overrides.get(name, name)
        return flat[: -len(name)].strip(), normalize_party(party)
    return flat, pd.NA


# ---------------------------------------------------------------------------
# Panel walking
# ---------------------------------------------------------------------------

_PRECINCT_RE = re.compile(r"^\d")
_LANDOWNER_RE = re.compile(r"^landowner\b", re.IGNORECASE)


def _row_cells(row: list[object]) -> list[object]:
    """Non-empty cells in order, without the stand-alone '%' cells of 2012."""
    out = []
    for v in row:
        if pd.isna(v):
            continue
        if isinstance(v, str):
            t = v.strip()
            if not t or t == "%":
                continue
        out.append(v)
    return out


def _to_number(v: object) -> float | None:
    if isinstance(v, int | float):
        return float(v)
    t = str(v).strip().replace(",", "").rstrip("%")
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class Panel:
    start: int
    contest: str
    labels: list[str]
    rows: list[tuple[int, list[object]]] = field(default_factory=list)   # (raw row, cells)
    totals: list[object] | None = None
    bad_rows: list[tuple[int, list[object]]] = field(default_factory=list)


def _is_row_start(first: str) -> bool:
    return bool(_PRECINCT_RE.match(first) or _LANDOWNER_RE.match(first))


def _is_totals(first: str) -> bool:
    return first.lower().rstrip(":") in {"totals", "total"}


def _align(labels: list[str], cells: list[object], *, totals: bool) -> list[object] | None:
    """Return `cells` padded to one value per label, or None if they don't fit.
    Totals rows omit the Percent Turnout cell."""
    if len(cells) == len(labels):
        return cells
    if totals and len(cells) == len(labels) - 1:
        kinds = [_label_kind(clean_col(lab)) for lab in labels]
        if "percent" in kinds:
            i = kinds.index("percent")
            return cells[:i] + [None] + cells[i:]
    return None


def walk_panels(raw: pd.DataFrame) -> list[Panel]:
    """Split the sheet into panels, each with its aligned data rows."""
    starts = _find_panel_starts(raw)
    bounds = starts[1:] + [raw.shape[0]]
    panels: list[Panel] = []
    last_title: str | None = None
    values = raw.to_numpy(dtype=object)
    for start, stop in zip(starts, bounds, strict=True):
        title = _contest_title(raw, start)
        if title.startswith("<unknown") and last_title:
            title = last_title  # page-break continuation of the prior contest
        else:
            last_title = title
        panel = Panel(start=start, contest=title, labels=_header_labels(raw, start))
        pending: tuple[int, object] | None = None   # precinct printed alone
        for i in range(start + 1, stop):
            row_i = i
            cells = _row_cells(list(values[i]))
            if not cells:
                continue
            col0 = values[i][0]
            first = "" if pd.isna(col0) else str(col0).strip()
            if first:
                pending = None
                if _is_totals(first):
                    aligned = _align(panel.labels, cells, totals=True)
                    if aligned is None:
                        panel.bad_rows.append((i, cells))
                    else:
                        panel.totals = aligned
                    continue
                if not _is_row_start(first):
                    # Banner / title / footer text — unless it is a full-width
                    # row of numbers under a non-numeric code: the property-
                    # owner pseudo-precincts ("FMFPD", 2010) of special districts.
                    if not (len(cells) == len(panel.labels)
                            and all(_to_number(c) is not None for c in cells[1:])):
                        continue
                if len(cells) == 1:
                    pending = (i, cells[0])
                    continue
            elif pending is not None and all(_to_number(c) is not None for c in cells):
                cells = [pending[1]] + cells
                row_i, pending = pending[0], None
            else:
                continue
            aligned = _align(panel.labels, cells, totals=False)
            if aligned is None:
                panel.bad_rows.append((row_i, cells))
            else:
                panel.rows.append((row_i, aligned))
        panels.append(panel)
    return panels


def _panel_frame(panel: Panel, year: int | None) -> pd.DataFrame:
    kinds = [_label_kind(clean_col(lab)) for lab in panel.labels]
    if "precinct" not in kinds:
        return pd.DataFrame()
    p_i = kinds.index("precinct")
    b_i = kinds.index("ballots_cast") if "ballots_cast" in kinds else None
    a_i = kinds.index("active_voters") if "active_voters" in kinds else None
    cand = [(j, *split_party(panel.labels[j], year)) for j, k in enumerate(kinds) if k == "candidate"]
    recs = []
    for row_i, cells in panel.rows:
        precinct = str(cells[p_i]).strip()
        if isinstance(cells[p_i], float) and cells[p_i].is_integer():
            precinct = str(int(cells[p_i]))
        ballots = _to_number(cells[b_i]) if b_i is not None else None
        active = _to_number(cells[a_i]) if a_i is not None else None
        for j, name, party in cand:
            recs.append({
                "_row": row_i,
                "precinct_id": precinct,
                "precinct_name": pd.NA,
                "contest": panel.contest,
                "candidate_or_option": name,
                "party": party,
                "votes": _to_number(cells[j]),
                "active_voters": active,
                "ballots_cast": ballots,
            })
    return pd.DataFrame(recs)


def published_totals(path: Path, year: int | None = None) -> pd.DataFrame:
    """The county's own ``Totals`` row for every (contest, candidate) in the
    file, as a frame of contest / candidate_or_option / party / votes. Used by
    reconcile.py as the "original" side for the panel years."""
    recs = []
    for panel in walk_panels(_read_raw(path)):
        if panel.totals is None:
            continue
        kinds = [_label_kind(clean_col(lab)) for lab in panel.labels]
        for j, k in enumerate(kinds):
            if k != "candidate":
                continue
            name, party = split_party(panel.labels[j], year)
            recs.append({"contest": panel.contest, "candidate_or_option": name,
                         "party": party, "votes": _to_number(panel.totals[j])})
    if not recs:
        return pd.DataFrame(columns=["contest", "candidate_or_option", "party", "votes"])
    return pd.DataFrame(recs)


def parse(path: Path, meta: SourceMeta) -> pd.DataFrame:
    rejector = Rejector(
        source_file=path.name,
        election_year=meta.election_year,
        data_source=meta.data_source,
    )
    register_rejector(rejector)

    raw = _read_raw(path)
    panels = walk_panels(raw)
    if not panels:
        raise ValueError(f"{path.name}: no 'Precinct' header rows found")

    notes: list[str] = []
    frames: list[pd.DataFrame] = []
    n_bad = 0
    for panel in panels:
        for row_i, cells in panel.bad_rows:
            n_bad += 1
            rejector.add(
                row_index=f"row {row_i + 1}",
                reason="panel_row_width_mismatch",
                detail=(f"{panel.contest}: {len(cells)} values for {len(panel.labels)} "
                        "header labels; not aligned"),
                raw_row={"cells": [str(c) for c in cells]},
            )
        f = _panel_frame(panel, meta.election_year)
        if not f.empty:
            frames.append(f)

    if not frames:
        raise ValueError(f"{path.name}: no panels yielded data")

    final = pd.concat(frames, ignore_index=True)
    final["contest_type"] = [
        infer_contest_type(c, ch)
        for c, ch in zip(final["contest"], final["candidate_or_option"], strict=True)
    ]
    final["_row_index"] = "row " + (final["_row"] + 1).astype(str)
    final = rejector.drop_na_with_reject(
        final,
        required=["precinct_id", "candidate_or_option", "votes"],
        reason="missing_required_field",
        row_index_col="_row_index",
    )
    final = final.drop(columns=["_row", "_row_index"])

    # A contest whose candidates span several panels must not repeat a
    # (precinct, contest, candidate) key; if it does, the panels were stitched
    # wrong and the duplicates are rejected rather than double-counted.
    key = ["precinct_id", "contest", "candidate_or_option"]
    dup = final.duplicated(key, keep=False)
    if dup.any():
        for rec in final[dup].to_dict("records"):
            rejector.add(row_index=f"{rec['precinct_id']}|{rec['contest']}",
                         reason="duplicate_key",
                         detail="same precinct/contest/candidate in two panels",
                         raw_row={k: v for k, v in rec.items() if pd.notna(v)})
        final = final[~dup]
        notes.append(f"{int(dup.sum())} rows with duplicate keys rejected")

    if n_bad:
        notes.append(f"{n_bad} panel row(s) whose width didn't match the header were rejected")
    if final["precinct_id"].astype("string").str.match(_LANDOWNER_RE).any():
        notes.append("includes 'Landowner' pseudo-precinct rows (property-owner ballots in "
                     "special-district contests; no precinct geography)")
    if (final["contest"].astype("string").str.startswith("<unknown contest")).any():
        n = (final["contest"].astype("string").str.startswith("<unknown contest")).sum()
        notes.append(f"{n} rows have unknown contest title — review needed")

    return add_provenance(final, meta, extraction_notes="; ".join(notes) if notes else None)
