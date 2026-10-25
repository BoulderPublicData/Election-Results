"""
Parse one election-night results snapshot (Datalab Markdown of a screenshot of
the Boulder County results site) into a header, an election-summary record,
and contest × candidate rows.

The page layout has been stable from 2014 through 2025:

  {Official|Unofficial} Results / Last Updated: M/D/YYYY H:MM AM|PM
  Election Summary table   (label/value pairs, sometimes two pairs per row)
  RESULTS - ALL CONTESTS
  one card per contest:
      title row(s)            "United States Senator" [+ "Vote for no more than Four"]
      header row              "CANDIDATE | | VOTES | PERCENT"  (blank first cell for measures)
      candidate rows          "Name - Party | <bar> | 42,394 | 64.89%"
      total row               "TOTAL VOTES: | | 65,335"

Datalab usually emits one Markdown table per card, but sometimes lifts the
title out as a `##` heading or merges two cards into one table. The parser
therefore treats the Markdown as a *stream of rows* (table rows and loose text
lines alike) and runs a small state machine over it rather than trusting
table boundaries.

Also parses the 2023 City of Boulder mayoral RCV "Short Report" PDFs, which
have a real text layer (no OCR needed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .common import normalize_choice, normalize_party

# ---------------------------------------------------------------------------
# Low-level cell helpers
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_INT = re.compile(r"^-?\d{1,3}(,\d{3})*$|^-?\d+$")
_PCT = re.compile(r"^-?\d+(\.\d+)?\s*%$")
_DATETIME = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?"
)


def clean_cell(text: str) -> str:
    text = text.replace("<br>", " ").replace("<br/>", " ")
    text = _TAG.sub("", text).replace("**", "").replace("\\", "")
    return _WS.sub(" ", text).strip()


def parse_int(text: str) -> int | None:
    t = clean_cell(text).replace(" ", "")
    return int(t.replace(",", "")) if _INT.match(t) else None


def parse_pct(text: str) -> float | None:
    t = clean_cell(text).replace(" ", "")
    return float(t.rstrip("%")) if _PCT.match(t) else None


def parse_datetime(text: str) -> str | None:
    """'11/8/2016 7:00 PM' → '2016-11-08T19:00:00' (local, America/Denver)."""
    m = _DATETIME.search(text)
    if not m:
        return None
    mon, day, year, hh, mm, ss, ampm = m.groups()
    hour = int(hh)
    if ampm:
        hour = hour % 12 + (12 if ampm.upper() == "PM" else 0)
    dt = datetime(int(year), int(mon), int(day), hour, int(mm), int(ss or 0))
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Row stream
# ---------------------------------------------------------------------------

@dataclass
class Row:
    cells: list[str]          # cleaned, non-empty cells (bar-chart cells drop out)
    is_table: bool
    table_start: bool         # first row of a Markdown table

    @property
    def text(self) -> str:
        return " ".join(self.cells)


_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}")


def iter_rows(markdown: str):
    prev_table = False
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            prev_table = False
            continue
        if line.startswith("|"):
            if _SEPARATOR.match(line):
                continue
            cells = [clean_cell(c) for c in line.strip("|").split("|")]
            cells = [c for c in cells if c]
            yield Row(cells, True, not prev_table)
            prev_table = True
        else:
            prev_table = False
            text = clean_cell(line.lstrip("#").strip())
            if text:
                yield Row([text], False, False)


# ---------------------------------------------------------------------------
# Snapshot parse
# ---------------------------------------------------------------------------

SUMMARY_FIELDS: list[tuple[str, re.Pattern]] = [
    ("total_registration", re.compile(r"total (voters )?registered|total registration", re.I)),
    ("active_registered_voters", re.compile(r"active registered", re.I)),
    ("mail_ballots_distributed", re.compile(r"mail ballots distributed", re.I)),
    ("property_owner_only_ballots_distributed",
     re.compile(r"property owner only ballots", re.I)),
    ("expected_turnout", re.compile(r"expected turnout", re.I)),
    ("total_ballots_counted", re.compile(r"total ballots counted", re.I)),
    ("in_person_ballots", re.compile(r"in.?person ballots", re.I)),
    ("property_owner_ballots", re.compile(r"^property.?owner ballots", re.I)),
    ("mail_ballots", re.compile(r"^mail ballots$", re.I)),
]
SUMMARY_COLUMNS = [name for name, _ in SUMMARY_FIELDS]

_LABEL_VALUE = re.compile(r"^(?P<label>.*[A-Za-z].*?):?\s+(?P<value>\d{1,3}(?:,\d{3})*|\d+)$")
_NOTE = re.compile(r"\bas of\b|\bestimate\b|figures|posting|\bupdate\b|\bthrough\b", re.I)
_RESULTS_LABEL = re.compile(r"\b(un)?official results\b", re.I)
_LAST_UPDATED = re.compile(r"last updated", re.I)
_ALL_CONTESTS = re.compile(r"results\s*-\s*all contests", re.I)
_TOTAL_VOTES = re.compile(r"^total votes:?$", re.I)
_VOTE_FOR = re.compile(r"\(?\s*vote for (?:not |no )?(?:more than )?(\w+)\s*\)?", re.I)
# "- Write-in Candidate" (2014-2022), "- Write-In" (2024), "- Certified Write-in Candidate"
_WRITE_IN = re.compile(r"\s*-\s*(certified\s+)?write-?\s?in(\s+candidate)?\s*$", re.I)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_LINK_CARD = re.compile(r"visit our .*results page", re.I)
# Page chrome that can appear between contests; never part of a contest title.
_BOILERPLATE = re.compile(
    r"^(view results|voter turnout by precinct|statewide contests|results preview|"
    r"boulder county elections?|page \d+)", re.I)


@dataclass
class Contest:
    title_lines: list[str]
    candidates: list[dict] = field(default_factory=list)
    total_votes: int | None = None


@dataclass
class Snapshot:
    results_label: str | None
    last_updated: str | None
    summary: dict[str, int | None]
    summary_notes: list[str]
    other_fields: dict[str, int]
    contests: list[Contest]
    unparsed: list[tuple[str, str]]  # (contest title, row text) the state machine couldn't place


def _summary_field(label: str) -> str | None:
    label = label.strip(" *:").strip()
    for name, rx in SUMMARY_FIELDS:
        if rx.search(label):
            return name
    return None


def _parse_summary(rows: list[Row], snap: Snapshot) -> None:
    """Label/value pairs in reading order; non-numeric rows become notes."""
    for row in rows:
        cells: list[str] = []
        for c in row.cells:
            if c.lower() == "election summary":
                continue
            # "Total Voters Registered: 247,752" → label, value. Footnotes
            # ("* Voter Registration Figures as of ... November 7") also end in
            # a number; keep those whole so they land in summary_notes.
            m = None if _NOTE.search(c) else _LABEL_VALUE.match(c)
            cells.extend([m["label"], m["value"]] if m else [c])
        if not cells:
            continue
        values = [None if _NOTE.search(c) else parse_int(c) for c in cells]
        if all(v is None for v in values):
            note = " ".join(cells).strip()
            if note and not re.fullmatch(r"total ballots counted includes:?", note, re.I):
                snap.summary_notes.append(note)
            continue
        label: str | None = None
        for cell, value in zip(cells, values, strict=True):
            if value is None:
                label = cell if label is None else f"{label} {cell}"
                continue
            if label is None:
                continue
            name = _summary_field(label)
            if name:
                snap.summary[name] = value
            else:
                snap.other_fields[label.strip(" *:")] = value
            label = None


def _is_header(row: Row) -> bool:
    upper = [c.upper() for c in row.cells]
    return "VOTES" in upper and "PERCENT" in upper


def _candidate_row(row: Row) -> dict | None:
    """'Name | 42,394 | 64.89%' → dict, else None."""
    if len(row.cells) < 3:
        return None
    pct = parse_pct(row.cells[-1])
    votes = parse_int(row.cells[-2])
    if pct is None or votes is None:
        return None
    name = " ".join(row.cells[:-2]).strip()
    if not name:
        return None
    return {"raw": name, "votes": votes, "percent": pct}


def _total_row(row: Row) -> int | None:
    if row.cells and _TOTAL_VOTES.match(row.cells[0]):
        for c in row.cells[1:]:
            v = parse_int(c)
            if v is not None:
                return v
    return None


def parse_snapshot(markdown: str) -> Snapshot:
    rows = list(iter_rows(markdown))
    snap = Snapshot(None, None, {k: None for k in SUMMARY_COLUMNS}, [], {}, [], [])

    # --- header: results label + Last Updated (first occurrence wins) ---
    for i, row in enumerate(rows):
        if snap.results_label is None:
            m = _RESULTS_LABEL.search(row.text)
            if m:
                snap.results_label = m.group(0).title()
        if snap.last_updated is None and _LAST_UPDATED.search(row.text):
            for nxt in rows[i:i + 3]:
                ts = parse_datetime(nxt.text)
                if ts:
                    snap.last_updated = ts
                    break
        if snap.results_label and snap.last_updated:
            break

    # --- split at "RESULTS - ALL CONTESTS" ---
    split = next((i for i, r in enumerate(rows) if _ALL_CONTESTS.search(r.text)), None)
    if split is None:
        # Fall back to the first contest header row.
        split = next((max(i - 1, 0) for i, r in enumerate(rows) if _is_header(r)), len(rows))
    summary_start = next((i for i, r in enumerate(rows[:split])
                          if "election summary" in r.text.lower()), None)
    if summary_start is not None:
        _parse_summary(rows[summary_start:split], snap)

    # --- contests: state machine over the row stream ---
    pending: list[str] = []
    current: Contest | None = None
    for row in rows[split + 1:]:
        if row.table_start and current is None and not _is_header(row):
            # A new table that opens with a title row starts a fresh title.
            # (A table that opens with the VOTES/PERCENT header keeps the
            # pending title: Datalab lifted it out as a heading above.)
            pending = []
        if _is_header(row):
            # Header cells besides CANDIDATE/VOTES/PERCENT carry the title when
            # Datalab folds the title into the header row.
            extra = [c for c in row.cells if c.upper() not in {"CANDIDATE", "VOTES", "PERCENT"}]
            current = Contest(title_lines=pending + extra)
            pending = []
            continue
        total = _total_row(row)
        if total is not None:
            if current is not None:
                current.total_votes = total
                snap.contests.append(current)
            else:
                snap.unparsed.append(("", row.text))
            current = None
            continue
        cand = _candidate_row(row)
        if cand is not None:
            if current is None:  # header row missing: start from pending title
                current = Contest(title_lines=pending)
                pending = []
            current.candidates.append(cand)
            continue
        if current is None:
            if _LINK_CARD.search(row.text):
                # A card with no results of its own (2023's "Visit our Ranked
                # Choice Voting results page") — drop its title with it.
                pending = []
            elif not _BOILERPLATE.match(row.text):
                pending.append(row.text)
        elif row.is_table and any(parse_int(c) is not None or "%" in c for c in row.cells):
            # Looks like a candidate row but a number didn't parse ("51,35").
            # Never drop silently: QA reports it and a correction fixes it.
            snap.unparsed.append((" ".join(current.title_lines), row.text))
    if current is not None and current.candidates:
        snap.contests.append(current)  # trailing contest without a TOTAL row
    return snap


# ---------------------------------------------------------------------------
# Contest / candidate normalization
# ---------------------------------------------------------------------------

def split_title(lines: list[str]) -> tuple[str, int | None]:
    """Join title lines; pull 'Vote for no more than Four' out as an int."""
    title = " ".join(lines)
    vote_for: int | None = None
    m = _VOTE_FOR.search(title)
    if m:
        word = m.group(1).lower()
        vote_for = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
        title = (title[:m.start()] + title[m.end():])
    title = _WS.sub(" ", title).strip(" :-")
    return title, vote_for


def split_candidate(raw: str) -> tuple[str, str | None, bool]:
    """'Mark Udall - Democratic' → ('Mark Udall', 'DEM', False).

    Write-in suffixes are stripped into the boolean. The party is whatever
    follows the last ' - ' (normalized via PARTY_MAP when known)."""
    text = raw.strip()
    write_in = bool(_WRITE_IN.search(text))
    text = _WRITE_IN.sub("", text).strip()
    choice = normalize_choice(text)
    if choice in {"Yes", "No"}:
        return choice, None, write_in
    if " - " in text:
        name, party = text.rsplit(" - ", 1)
        return name.strip(), normalize_party(party.strip()), write_in
    return text, None, write_in


# ---------------------------------------------------------------------------
# RCV short reports (2023 City of Boulder mayor)
# ---------------------------------------------------------------------------

_RCV_STAMP = re.compile(r"(\d{2}/\d{2}/\d{4}) (\d{2}):(\d{2}):(\d{2})")
_RCV_SKIP = re.compile(r"^(continuing|blanks|exhausted|overvotes|non transferable|threshold|"
                       r"round|candidate|votes|\(elimination\)|page|\*)", re.I)


def parse_rcv_report(path: Path) -> tuple[str, list[dict]]:
    """Return (last_updated_iso, rows) for one RCV Short Report PDF.

    Each candidate line reads
        Name  R1votes R1pct  transfer  R2votes R2pct  transfer
    i.e. a (votes, pct) pair per round separated by transfer columns.
    """
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = _RCV_STAMP.search(text)
    if not m:
        raise ValueError(f"{path.name}: no report timestamp")
    mon, day, year = m.group(1).split("/")
    stamp = datetime(int(year), int(mon), int(day),
                     int(m.group(2)), int(m.group(3)), int(m.group(4))).isoformat()

    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or _RCV_SKIP.match(line):
            continue
        tokens = line.split()
        nums = [t for t in tokens if re.fullmatch(r"-?[\d,]+|-?[\d.]+%", t)]
        name = " ".join(t for t in tokens if t not in nums).strip()
        if not name or not nums:
            continue
        # (votes, pct) pairs: every token followed by a percentage.
        rounds = [(int(nums[i].replace(",", "")), float(nums[i + 1].rstrip("%")))
                  for i in range(len(nums) - 1)
                  if not nums[i].endswith("%") and nums[i + 1].endswith("%")]
        for n, (votes, pct) in enumerate(rounds, start=1):
            rows.append({"raw": name, "round": n, "votes": votes, "percent": pct,
                         "final": n == len(rounds)})
    return stamp, rows
