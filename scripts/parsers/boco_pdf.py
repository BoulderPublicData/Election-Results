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

Every page is read on its own (#23). A contest with more candidates than fit
across a page prints its whole precinct run once per group of candidates, so
the candidate labels change from one "Continued" page to the next and must be
re-read from each page's rotated header; the last group usually adds a per-row
``Totals`` column, and the last page of a long contest can carry *only* that
column. The vote-method block before the candidates is four columns in 2007
and six in 2005/2009, so a row is split at its Percent Turnout token (the one
ending in ``%``) rather than at a fixed offset. A row whose width doesn't fit
its page's labels, and any (precinct, contest, candidate) key printed twice,
goes to the reject port (data/audit/rejected.csv) instead of the output.

:func:`published_totals` reads the ``Totals:`` line printed under each
candidate group, which ``scripts/reconcile.py`` uses as the original side for
these years; with the per-page reading every candidate's precinct rows sum to
it exactly.

Tabula-py was the previous extractor; pdfplumber is pure-Python (no JVM) and
recovers contest titles (which tabula lost in the surrounding narrative).
Rows are still flagged ``extraction_quality = "pdf_text_layer"``: the text
layer is reliable, but labels come from rotated text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import pdfplumber

from ..reject import Rejector
from ..reject import register as register_rejector
from ..schema import SourceMeta
from .common import (
    add_provenance,
    infer_contest_type,
    normalize_choice,
    precinct_id_str,
)

# Header/boilerplate lines we always skip when looking for the contest title.
# 2005/2007/2009 each prefix their pages with a slightly different banner, plus
# a "Boulder County, …" line and a "Page X of Y" line.
_BOILERPLATE_PREFIXES = (
    # The banner is "Boulder County, CO — …" / "Boulder County, Colorado — …";
    # the comma keeps contest titles such as "Boulder County Nederland
    # Community Library District Ballot Issue 5A" (2009) from matching.
    "Boulder County,",
    "Page ",
    "Total Number of Voters",
    "Precincts Reporting",
    "Canvass Report",                 # 2007 banner
    "Colorado Canvass Report",        # 2005 banner
    "Precinct ",                      # column-header line (page with no title)
)

# Match a data row: precinct followed by whitespace-separated tokens.
# 2007 and 2009 use 3-digit precinct codes (e.g., 073); 2005 uses the full
# 10-digit identifier (e.g., 2181007037).
# Property-owner ballots in special-district contests are printed under a
# pseudo-precinct code instead ("Landowner" in 2007, "RMFPD" / "NCLD" in 2009).
_DATA_ROW_RE = re.compile(r"^\s*(\d{3,10}|Landowner|[A-Z]{3,6})\s+(.+?)\s*$")

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


# Rotated label lines closer than this (in PDF points) belong to one column.
_WRAP_GAP_PT = 15


def _extract_header(page) -> tuple[list[str], bool]:
    """Pull the candidate (and Yes/No) column labels from the page header by
    clustering pdfplumber's rotated words. Returns ``(labels, has_totals)``,
    where ``has_totals`` says the page also prints a per-row ``Totals``
    column after the candidates.

    The PDF renders candidate names rotated 90° from the horizontal text flow.
    pdfplumber exposes that via ``upright=False`` on each word; the words for
    one candidate sit at the same x-coordinate, stacked top-to-bottom, each
    char-reversed (because the PDF reading order goes the opposite way along
    the rotated baseline). Cluster by x, sort by y, char-reverse, join in
    reverse line order, and we get the candidate name in its original
    ``First [Middle] Last`` form. A parenthetical cluster such as
    ``(withdrawn)`` (2007) belongs to the label before it.
    """
    try:
        words = page.extract_words(use_text_flow=False, extra_attrs=["upright"])
    except Exception:
        return [], False

    rotated = [w for w in words if not w.get("upright", True)]
    if not rotated:
        return [], False

    # Bucket by x0 with a small tolerance so jittered words land in the same column.
    bucket_size = 5  # ~5pt buckets
    buckets: dict[int, list[dict]] = {}
    for w in rotated:
        key = int(round(w["x0"] / bucket_size) * bucket_size)
        buckets.setdefault(key, []).append(w)

    clusters: list[tuple[int, str]] = []
    for x in sorted(buckets):
        cluster = sorted(buckets[x], key=lambda w: w["top"])
        # Within a rotated cell the visual top-to-bottom order is the reverse
        # of normal reading order, so reverse the line list.
        unrot_words = [w["text"][::-1] for w in reversed(cluster)]
        label = " ".join(unrot_words).strip()
        if label:
            clusters.append((x, label))

    # A long label wraps onto a second rotated line about 10pt to the right
    # ("Francisca N." + "Araiza-Kasama", 2005; "Doug Brown" + "(withdrawn)",
    # 2007); candidate columns are ~46pt apart. Join clusters that close.
    merged: list[tuple[int, str]] = []
    for x, label in clusters:
        special = label.lower() in {"totals", "total", "continued"}
        if (merged and x - merged[-1][0] < _WRAP_GAP_PT and not special
                and merged[-1][1].lower() not in {"totals", "total", "continued"}):
            merged[-1] = (x, f"{merged[-1][1]} {label}")
        else:
            merged.append((x, label))

    labels: list[str] = []
    has_totals = False
    for _x, label in merged:
        lo = label.lower()
        if lo in {"totals", "total"}:
            has_totals = True
            continue
        if lo == "continued":
            continue
        if _is_known_meta_header(label):
            continue
        labels.append(_classify_choice_label(label))
    return labels, has_totals


def _extract_candidate_columns(page) -> list[str]:
    """Candidate / Yes-No labels of a page (see :func:`_extract_header`)."""
    return _extract_header(page)[0]


def _to_int(tok: str) -> int | None:
    cleaned = tok.replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned))
        except ValueError:
            return None


def _split_row(line: str) -> tuple[str, list[str], list[int | None]] | None:
    """Split a precinct row into (precinct, meta tokens, value tokens).

    Layout: ``precinct  meta…  NN.NN%  value…``. The number of vote-method /
    turnout columns differs by year (2007 prints four, 2005 and 2009 six), so
    the meta block is "everything up to and including the Percent Turnout
    token" rather than a fixed count; the values after it are the candidate
    columns, plus a row total on pages that print one."""
    m = _DATA_ROW_RE.match(line)
    if not m:
        return None
    precinct = m.group(1)
    if precinct in _BAD_PRECINCT_VALUES:
        return None
    tokens = m.group(2).split()
    pct = next((i for i, t in enumerate(tokens) if t.endswith("%")), None)
    if pct is None or pct < 2:
        return None
    meta = tokens[: pct + 1]
    values = [_to_int(t) for t in tokens[pct + 1:]]
    if any(v is None for v in values):
        return None
    return precinct, meta, values


def _parse_data_row(line: str, n_candidates: int, has_totals: bool = False
                    ) -> tuple[str, dict[str, int | None], list[int | None]] | None:
    """Decode one precinct row into (precinct_id, meta_values, candidate_votes),
    or None if it isn't a data row or its width doesn't fit ``n_candidates``."""
    split = _split_row(line)
    if split is None:
        return None
    precinct, meta_tokens, values = split
    values = _drop_row_total(values, n_candidates, has_totals)
    if values is None:
        return None
    meta = {
        "total_ballots": _to_int(meta_tokens[-3]),
        "registered_voters": _to_int(meta_tokens[-2]),
    }
    return precinct, meta, values


def _drop_row_total(values: list[int | None], n: int, has_totals: bool) -> list[int | None] | None:
    """Strip the trailing per-row Totals column if present; None if the
    remaining width doesn't match the n candidate labels."""
    if len(values) == n + 1 and (has_totals or values[-1] == sum(v or 0 for v in values[:-1])):
        return values[:-1]
    if len(values) == n:
        return values
    return None


_TOTALS_LINE_RE = re.compile(r"^\s*Totals:\s*(.+?)\s*$")


def _pages(pdf, pages: Iterable[int] | None):
    """(1-based page number, page) for every page, or only for `pages`."""
    wanted = set(pages) if pages is not None else None
    for page_no, page in enumerate(pdf.pages, start=1):
        if wanted is None or page_no in wanted:
            yield page_no, page


def parse(path: Path, meta: SourceMeta, pages: Iterable[int] | None = None) -> pd.DataFrame:
    """Parse the whole PDF, or only the 1-based `pages` (used by the golden
    tests; a contest's first page must be included for its title to carry)."""
    rejector = Rejector(
        source_file=path.name,
        election_year=meta.election_year,
        data_source=meta.data_source,
    )
    register_rejector(rejector)
    rows: list[dict] = []
    pages_parsed = 0
    pages_skipped = 0
    pages_no_candidates = 0
    last_title: str | None = None
    last_labels: tuple[list[str], bool] = ([], False)

    with pdfplumber.open(path) as pdf:
        for page_no, page in _pages(pdf, pages):
            text = page.extract_text() or ""
            lines = text.split("\n")
            title, is_continuation = _find_contest_title(lines, last_title)
            if not title:
                pages_skipped += 1
                continue
            last_title = title

            # Candidate columns change from page to page within one contest
            # (a contest with more candidates than fit across a page repeats
            # its precinct run for each group of candidates), so the header is
            # read on every page (#23). Only a continuation page with no
            # readable header falls back to the previous page's labels.
            labels, has_totals = _extract_header(page)
            if not labels and has_totals:
                # The last page of a long contest can carry only the per-row
                # Totals column (2007 Park R-3, 2009 Lafayette): no candidate
                # votes on it.
                pages_parsed += 1
                continue
            if not labels and is_continuation:
                labels, has_totals = last_labels
            last_labels = (labels, has_totals)
            if not labels:
                pages_no_candidates += 1
                continue

            for line_no, line in enumerate(lines, start=1):
                split = _split_row(line)
                if split is None:
                    continue
                precinct, meta_tokens, values = split
                votes = _drop_row_total(values, len(labels), has_totals)
                if votes is None:
                    rejector.add(
                        row_index=f"page {page_no}:line {line_no}",
                        reason="pdf_row_width_mismatch",
                        detail=(f"{title}: {len(values)} values for {len(labels)} "
                                f"candidate labels {labels}"),
                        raw_row={"line": line},
                    )
                    continue
                for cand_label, v in zip(labels, votes, strict=True):
                    rows.append({
                        "precinct_id": precinct_id_str(precinct),
                        "precinct_name": pd.NA,
                        "contest": title,
                        "candidate_or_option": cand_label,
                        "party": pd.NA,
                        "votes": v,
                        "active_voters": _to_int(meta_tokens[-2]),
                        "ballots_cast": _to_int(meta_tokens[-3]),
                        "_where": f"page {page_no}:line {line_no}",
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
    # A (precinct, contest, candidate) key printed twice means the page's
    # labels were attached to the wrong columns; route every copy to the
    # reject port rather than publish one of several conflicting counts.
    key = ["precinct_id", "contest", "candidate_or_option"]
    dup = df.duplicated(key, keep=False)
    n_dup = int(dup.sum())
    for rec in df[dup].to_dict("records"):
        rejector.add(row_index=rec["_where"], reason="duplicate_key",
                     detail=f"{rec['contest']} / {rec['candidate_or_option']} printed twice "
                            f"for precinct {rec['precinct_id']}",
                     raw_row={k: v for k, v in rec.items() if pd.notna(v)})
    df = df[~dup].drop(columns=["_where"])
    df["contest_type"] = [
        infer_contest_type(c, ch) for c, ch in zip(df["contest"], df["candidate_or_option"], strict=True)
    ]

    notes = [
        f"pdfplumber: parsed {pages_parsed} pages, "
        f"skipped {pages_skipped}, "
        f"{pages_no_candidates} pages had no recognizable candidate header (skipped)",
        "Candidate names recovered from rotated PDF text via _unrotate(); "
        "spot-check a sample of precincts against the source PDF before publishing",
    ]
    if len(rejector):
        notes.append(f"{len(rejector)} row(s) sent to data/audit/rejected.csv"
                     + (f" ({n_dup} with duplicate keys)" if n_dup else ""))
    return add_provenance(df, meta, extraction_notes="; ".join(notes))


def published_totals(path: Path, pages: Iterable[int] | None = None) -> pd.DataFrame:
    """The ``Totals:`` line printed at the end of each candidate group, keyed
    to that page's labels: contest / candidate_or_option / votes. Used by
    reconcile.py as the "original" side for the PDF years."""
    recs: list[dict] = []
    last_title: str | None = None
    last_labels: tuple[list[str], bool] = ([], False)
    with pdfplumber.open(path) as pdf:
        for _page_no, page in _pages(pdf, pages):
            lines = (page.extract_text() or "").split("\n")
            title, is_continuation = _find_contest_title(lines, last_title)
            if not title:
                continue
            last_title = title
            labels, has_totals = _extract_header(page)
            if not labels and has_totals:
                continue
            if not labels and is_continuation:
                labels, has_totals = last_labels
            last_labels = (labels, has_totals)
            if not labels:
                continue
            n_meta = next((len(s[1]) for s in map(_split_row, lines) if s), None)
            for line in lines:
                m = _TOTALS_LINE_RE.match(line)
                if not m or n_meta is None:
                    continue
                toks = m.group(1).split()
                # The Totals line omits the Percent Turnout cell.
                values = [_to_int(t) for t in toks[n_meta - 1:]]
                values = _drop_row_total(values, len(labels), has_totals)
                if values is None:
                    continue
                recs.extend({"contest": title, "candidate_or_option": lab, "votes": v}
                            for lab, v in zip(labels, values, strict=True))
    return pd.DataFrame(recs, columns=["contest", "candidate_or_option", "votes"])
