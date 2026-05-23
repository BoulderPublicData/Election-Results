"""
Boulder County PDF SoV parser (2005, 2007, 2009).

These are coordinated-election Canvass Reports published as 100+ page PDFs with
a text layer (not scans). The page layout is:

    Boulder County, CO  —  2009 COORDINATED ELECTION  —  November 03, 2009
    Page 4 of 105   11/17/2009 11:48 AM
    Total Number of Voters: ...  Precincts Reporting ...
    {CONTEST TITLE}
    [Continued]                     <- on continuation pages only
    {column headers — meta + candidate names rendered vertically}
    {data rows: precinct, vote-method totals, candidate votes, row total}

pdfplumber gives us:
- `extract_text()` — clean line-by-line text. Contest title sits on line 4
  (zero-indexed); "Continued" marker, if present, sits on the line below.
- `extract_tables()` — recovers the column header row. Candidate names are
  rendered vertically in the PDF, so pdfplumber returns them as
  `"lastNameReversed\nfirstNameReversed"`; `_unrotate()` reverses each line
  and re-orders into `First Last`.

Tabula-py was the previous extractor; pdfplumber is pure-Python (no JVM) and
recovers contest titles (which tabula lost in the surrounding narrative).
Coverage is still best-effort and rows are flagged
`extraction_quality = "pdf_text_layer"`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pdfplumber

from ..schema import SourceMeta
from .common import (
    add_provenance, infer_contest_type, normalize_choice, precinct_id_str,
)

# Header/boilerplate lines we always skip when looking for the contest title.
# 2005/2007/2009 each prefix their pages with a slightly different banner, plus
# a "Boulder County, …" line and a "Page X of Y" line.
_BOILERPLATE_PREFIXES = (
    "Boulder County",
    "Page ",
    "Total Number of Voters",
    "Precincts Reporting",
    "Canvass Report",                 # 2007 banner
    "Colorado Canvass Report",        # 2005 banner
)

# Vote-method / turnout column headers that appear before the candidate columns.
# Order matters — the parser assumes data rows present these in this order.
_META_COLUMNS = (
    "absentee_ballots",
    "early_ballots",
    "election_day_ballots",
    "total_ballots",
    "registered_voters",
    "percent_turnout",
)

# Match a data row: 3-10 digit precinct followed by whitespace-separated tokens.
# 2007 and 2009 use 3-digit precinct codes (e.g., 073); 2005 uses the full
# 10-digit identifier (e.g., 2181007037).
_DATA_ROW_RE = re.compile(r"^\s*(\d{3,10})\s+(.+?)\s*$")

# Tokens that should NOT count as a vote value (page summary rows, etc.).
_BAD_PRECINCT_VALUES = {"000", "999"}


_REVERSED_WORD_RE = re.compile(r"[A-Za-z]+")


def _looks_char_reversed(text: str) -> bool:
    """Heuristic for "this cell came from rotated text and pdfplumber emitted
    it char-by-char-reversed".

    Normal English proper-case words start uppercase and end lowercase
    ("George"). When pdfplumber reads a 90°-rotated word, the characters come
    out in reverse: "egroeG" — starts lowercase, ends uppercase. We flag a
    cell as rotated when a majority of its alpha words show that pattern.
    """
    words = _REVERSED_WORD_RE.findall(text)
    if not words:
        return False
    reversed_looking = sum(
        1 for w in words
        if len(w) > 1 and w[0].islower() and w[-1].isupper()
    )
    return reversed_looking * 2 > len(words)


def _unrotate(cell: str) -> str:
    """Return cell text in human-readable order.

    Two cases:
    - Meta column headers (Absentee Voting Ballots Cast, Registered Voters,
      Totals, …) are rendered horizontally in the PDF. pdfplumber emits them
      with their natural casing, often with embedded newlines from the wrap.
      We just collapse the newlines to spaces.
    - Candidate names (George Karakehian, Valerie Mitchell, …) are rendered
      vertically. pdfplumber emits each visual row of the rotated text on its
      own line, character-reversed (``"naihekaraK\\negroeG"``). We reverse
      each line's characters, then reverse the line order, then join with
      spaces ("George Karakehian").
    """
    if not cell:
        return ""
    parts = [p for p in str(cell).split("\n") if p]
    if not parts:
        return ""
    if any(_looks_char_reversed(p) for p in parts):
        return " ".join(reversed([p[::-1] for p in parts])).strip()
    return " ".join(parts).strip()


def _is_known_meta_header(unrotated: str) -> bool:
    """Detect header cells that describe vote-method/turnout columns
    (Absentee Voting Ballots Cast, Election Day Ballots Cast, etc.).

    These are NOT candidates and shouldn't generate result rows."""
    s = unrotated.lower().replace("\n", " ")
    return any(kw in s for kw in (
        "ballots cast", "ballotscast", "registered voters",
        "percent turnout", "absentee voting", "early voting",
        "election day", "mail ballots", "provisional",
    ))


def _classify_choice_label(label: str) -> str:
    """Recognize Yes/No measure-style labels even when they arrive char-reversed."""
    candidates = {label, _unrotate(label)}
    for c in candidates:
        norm = normalize_choice(c.strip())
        if isinstance(norm, str) and norm in {"Yes", "No"}:
            return norm
    return label.strip()


def _find_contest_title(lines: list[str], last_title: str | None) -> tuple[str | None, bool]:
    """Return (contest_title, is_continuation).

    The title is the first non-boilerplate line on the page. If the next
    non-empty line says "Continued", we're on a continuation page and the
    title carries forward from the previous panel."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in _BOILERPLATE_PREFIXES):
            continue
        # First non-boilerplate line — does the next non-empty line say "Continued"?
        is_continuation = False
        for j in range(i + 1, min(i + 4, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                continue
            if nxt.lower() == "continued":
                is_continuation = True
            break
        if is_continuation and last_title:
            return last_title, True
        return stripped, False
    return None, False


def _extract_candidate_columns(page) -> list[str]:
    """Pull the candidate (and Yes/No) column labels from the page header by
    clustering pdfplumber's rotated words.

    The PDF renders candidate names rotated 90° from the horizontal text flow.
    pdfplumber exposes that via ``upright=False`` on each word; the words for
    one candidate sit at the same x-coordinate, stacked top-to-bottom, each
    char-reversed (because the PDF reading order goes the opposite way along
    the rotated baseline). Cluster by x, sort by y, char-reverse, join in
    reverse line order, and we get the candidate name in its original
    ``First [Middle] Last`` form.
    """
    try:
        words = page.extract_words(use_text_flow=False, extra_attrs=["upright"])
    except Exception:
        return []

    rotated = [w for w in words if not w.get("upright", True)]
    if not rotated:
        return []

    # Bucket by x0 with a small tolerance so jittered words land in the same column.
    bucket_size = 5  # ~5pt buckets
    buckets: dict[int, list[dict]] = {}
    for w in rotated:
        key = int(round(w["x0"] / bucket_size) * bucket_size)
        buckets.setdefault(key, []).append(w)

    labels: list[str] = []
    for x in sorted(buckets):
        cluster = sorted(buckets[x], key=lambda w: w["top"])
        # Within a rotated cell the visual top-to-bottom order is the reverse
        # of normal reading order, so reverse the line list.
        unrot_words = [w["text"][::-1] for w in reversed(cluster)]
        label = " ".join(unrot_words).strip()
        if not label:
            continue
        # Skip non-candidate labels that occasionally land in the rotated set.
        lo = label.lower()
        if lo in {"totals", "total", "continued"}:
            continue
        if _is_known_meta_header(label):
            continue
        labels.append(_classify_choice_label(label))
    return labels


def _infer_n_candidates(lines: list[str]) -> int:
    """First data row tells us how many candidate columns the page has:
    tokens = 1 (precinct) + 6 (meta) + N (candidates) + 1 (Totals).
    Used to trim an over-clustered candidate list to the right width."""
    for line in lines:
        m = _DATA_ROW_RE.match(line.strip())
        if not m:
            continue
        n_tokens = 1 + len(m.group(2).split())
        n = n_tokens - 1 - len(_META_COLUMNS) - 1
        if n > 0:
            return n
    return 0


def _parse_data_row(line: str, n_candidates: int) -> tuple[str, dict[str, int | None], list[int | None]] | None:
    """Decode a single precinct row into (precinct_id, meta_values, candidate_votes).

    Layout: ``precinct  6×meta  N×candidate  total``. We slice positionally;
    if the token count doesn't match the expected length we return None and let
    the caller drop the row."""
    m = _DATA_ROW_RE.match(line)
    if not m:
        return None
    precinct = m.group(1)
    if precinct in _BAD_PRECINCT_VALUES:
        return None
    tokens = m.group(2).split()
    expected = len(_META_COLUMNS) + n_candidates + 1  # +1 for the "Totals" column
    if len(tokens) < len(_META_COLUMNS) + 1:
        # too short — almost certainly not a data row
        return None

    def _to_int(tok: str) -> int | None:
        if tok.endswith("%"):
            return None  # turnout percentage; we don't store it
        cleaned = tok.replace(",", "")
        try:
            return int(cleaned)
        except ValueError:
            try:
                return int(float(cleaned))
            except ValueError:
                return None

    # If the row has more tokens than we expect, trust the meta block at the
    # start and the trailing totals; everything in between is candidate votes.
    meta_tokens = tokens[: len(_META_COLUMNS)]
    meta = dict(zip(_META_COLUMNS, [_to_int(t) for t in meta_tokens]))

    candidate_slice = tokens[len(_META_COLUMNS) : len(_META_COLUMNS) + n_candidates]
    candidate_votes = [_to_int(t) for t in candidate_slice]
    # Pad with None if the row is short on candidate columns.
    while len(candidate_votes) < n_candidates:
        candidate_votes.append(None)
    return precinct, meta, candidate_votes


def parse(path: Path, meta: SourceMeta) -> pd.DataFrame:
    rows: list[dict] = []
    pages_parsed = 0
    pages_skipped = 0
    pages_no_candidates = 0
    last_title: str | None = None
    last_candidates: list[str] = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.split("\n")
            if not lines:
                pages_skipped += 1
                continue

            title, is_continuation = _find_contest_title(lines, last_title)
            if not title:
                pages_skipped += 1
                continue

            if is_continuation:
                candidates = last_candidates
            else:
                candidates = _extract_candidate_columns(page)
                expected_n = _infer_n_candidates(lines)
                # If the rotated-word cluster came up short, trim/extend so
                # zip() lines up with the data row's actual candidate count.
                if expected_n and len(candidates) > expected_n:
                    candidates = candidates[:expected_n]
                last_title = title
                last_candidates = candidates

            if not candidates:
                pages_no_candidates += 1
                continue

            for line in lines:
                parsed = _parse_data_row(line, n_candidates=len(candidates))
                if parsed is None:
                    continue
                precinct, meta_values, candidate_votes = parsed
                for cand_label, votes in zip(candidates, candidate_votes):
                    if votes is None:
                        continue
                    rows.append({
                        "precinct_id": precinct_id_str(precinct),
                        "precinct_name": pd.NA,
                        "contest": title,
                        "candidate_or_option": cand_label,
                        "party": pd.NA,
                        "votes": votes,
                        "active_voters": meta_values.get("registered_voters"),
                        "ballots_cast": meta_values.get("total_ballots"),
                    })
            pages_parsed += 1

    if not rows:
        return add_provenance(
            pd.DataFrame(columns=[
                "precinct_id", "precinct_name", "contest", "candidate_or_option",
                "party", "votes", "active_voters", "ballots_cast",
            ]),
            meta,
            extraction_notes=(
                f"pdfplumber found no parseable panels in {path.name}; "
                "manual extraction required"
            ),
        )

    df = pd.DataFrame(rows)
    df["contest_type"] = [
        infer_contest_type(c, ch) for c, ch in zip(df["contest"], df["candidate_or_option"])
    ]

    notes = [
        f"pdfplumber: parsed {pages_parsed} pages, "
        f"skipped {pages_skipped}, "
        f"{pages_no_candidates} pages had no recognizable candidate header (skipped)",
        "Candidate names recovered from rotated PDF text via _unrotate(); "
        "spot-check a sample of precincts against the source PDF before publishing",
    ]
    return add_provenance(df, meta, extraction_notes="; ".join(notes))
