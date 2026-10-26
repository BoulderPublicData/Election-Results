"""
Upstream source discovery.

The static registry in ``scripts.sources`` stops at whatever year was hand-
recorded the last time someone touched the file. For automated annual runs we
also want to *discover* SoV/precinct files for years the registry hasn't
caught up to yet. This module scrapes the two upstream landing pages and
yields :class:`scripts.sources.Source` records.

Upstream pages:
- Boulder County:  https://bouldercounty.gov/elections/results/
                   (and, as fallback, /elections/by-year/{year}-election/)
- Colorado SOS:    https://www.coloradosos.gov/pubs/elections/Results/Archives.html

The discovery is best-effort and intentionally conservative — it only flags
files whose filenames look like Statement-of-Votes or precinct-level results
documents. Anything else (sample ballots, TABOR notices, summary PDFs)
is rejected by the filename filter.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from collections.abc import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import http
from .config import SOURCES, Source
from .logging_setup import get_logger

log = get_logger(__name__)

# Where to look for Boulder County's published Statements of Votes.
BOCO_RESULTS_PAGE = "https://bouldercounty.gov/elections/results/"
BOCO_BY_YEAR_PAGE = "https://bouldercounty.gov/elections/by-year/{year}-election/"

# Colorado SOS Archives landing page.
SOS_ARCHIVES_PAGE = "https://www.coloradosos.gov/pubs/elections/Results/Archives.html"

# Filename patterns that identify a real Statement of Votes file. We accept
# .xlsx, .xls, and .pdf so historical years still work. We *reject* summary,
# canvass, sample-ballot, TABOR, and similar publications.
_BOCO_FILENAME_RE = re.compile(r"(?i)/(\d{4})[^/]*statement.of.vote[^/]*\.(xls|xlsx|pdf)$")
# "recount" is NOT rejected: the registered 2023 file is a Recount SoV, and a
# recount (or amended) SoV supersedes the original when both are published —
# see discover_boulder_county's ranking.
_BOCO_REJECT_RE = re.compile(r"(?i)(summary|sample|tabor|canvass|notice|cvr|cure)")
_SUPERSEDING_RE = re.compile(r"(?i)(recount|amended)")

_SOS_FILENAME_RE = re.compile(
    r"(?i)/(\d{4})/?\d*(General|Coordinated|Primary)?[A-Za-z]*"
    r"(Precinct|Turnout|BallotsCast)[A-Za-z]*\.xlsx?$"
)


def _fetch_html(url: str) -> str:
    """Fetch a page via the shared cached+retrying HTTP session."""
    return http.get_text(url)


def _classify_boco_url(url: str) -> tuple[int, str] | None:
    """Return (year, election_type) if `url` looks like a Boulder SoV file."""
    if _BOCO_REJECT_RE.search(url):
        return None
    m = _BOCO_FILENAME_RE.search(url)
    if not m:
        return None
    year = int(m.group(1))
    # Boulder uses "2024G" / "2025C" / "2026P" prefixes embedded in the filename.
    # Primary first: a primary file must never be keyed as that year's general.
    if re.search(r"(?i)\d{4}P[A-Z-]", url) or re.search(r"(?i)primary", url):
        etype = "primary"
    elif re.search(r"(?i)\d{4}G[A-Z-]", url):
        etype = "general"
    elif re.search(r"(?i)\d{4}C[A-Z-]", url):
        etype = "coordinated"
    elif re.search(r"(?i)general", url):
        etype = "general"
    elif re.search(r"(?i)coordinated", url):
        etype = "coordinated"
    else:
        # Fall back on the year — Boulder runs coordinated in odd years,
        # general in even years.
        etype = "coordinated" if year % 2 else "general"
    return year, etype


def _classify_sos_url(url: str) -> tuple[int, str] | None:
    m = _SOS_FILENAME_RE.search(url)
    if not m:
        return None
    year = int(m.group(1))
    # The URL usually names the election ("General", "Primary"); check
    # primary first so a June primary file isn't keyed as the general.
    if re.search(r"(?i)primary", url):
        etype = "primary"
    elif re.search(r"(?i)general", url):
        etype = "general"
    elif re.search(r"(?i)coordinated", url):
        etype = "coordinated"
    else:
        etype = "general" if year % 2 == 0 else "coordinated"
    return year, etype


def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls = set()
    for a in soup.find_all("a", href=True):
        urls.add(urljoin(base_url, a["href"]))
    return sorted(urls)


def discover_boulder_county(
    *,
    html: str | None = None,
    years: Iterable[int] | None = None,
) -> list[Source]:
    """Find Boulder County SoV files on the official results landing page.

    Pass ``html`` to parse pre-fetched markup (used by tests). Otherwise fetches
    ``BOCO_RESULTS_PAGE`` over the network. The optional ``years`` filter
    restricts the result list to those years.
    """
    if html is None:
        html = _fetch_html(BOCO_RESULTS_PAGE)
    yset = set(years) if years else None
    # Prefer machine-readable formats over PDFs when the same year/election
    # publishes both, and within a format a recount/amended SoV over the
    # original. Lower rank wins.
    fmt_rank = {"xlsx": 0, "xls": 1, "pdf": 2}
    candidates: dict[tuple[int, str], tuple[tuple, Source]] = {}
    for url in _extract_links(html, BOCO_RESULTS_PAGE):
        cls = _classify_boco_url(url)
        if not cls:
            continue
        year, etype = cls
        if yset and year not in yset:
            continue
        ext = url.rsplit(".", 1)[1].lower()
        rank = (ext == "pdf", not _SUPERSEDING_RE.search(url), fmt_rank.get(ext, 99))
        key = (year, etype)
        src = Source(
            year=year,
            election_type=etype,
            data_source="boulder_county",
            url=url,
            local_filename=f"{year}-{etype}-sov.{ext}",
        )
        if key not in candidates or rank < candidates[key][0]:
            candidates[key] = (rank, src)
    return [
        src for _, src in sorted(candidates.values(), key=lambda x: (x[1].year, x[1].election_type))
    ]


def discover_secretary_of_state(
    *,
    html: str | None = None,
    years: Iterable[int] | None = None,
) -> list[Source]:
    """Find Colorado SOS precinct-level result files on the Archives page."""
    if html is None:
        html = _fetch_html(SOS_ARCHIVES_PAGE)
    yset = set(years) if years else None
    out: list[Source] = []
    seen: set[tuple[int, str]] = set()
    for url in _extract_links(html, SOS_ARCHIVES_PAGE):
        cls = _classify_sos_url(url)
        if not cls:
            continue
        year, etype = cls
        if yset and year not in yset:
            continue
        # We're only interested in precinct-level results; the filter regex
        # already requires "Precinct" / "Turnout" / "BallotsCast" in the path.
        key = (year, etype)
        if key in seen:
            continue
        seen.add(key)
        filename = f"{year}-{etype}-precinct-results.xlsx"
        out.append(
            Source(
                year=year,
                election_type=etype,
                data_source="secretary_of_state",
                url=url,
                local_filename=filename,
            )
        )
    return out


def discover(
    *,
    boco_html: str | None = None,
    sos_html: str | None = None,
    years: Iterable[int] | None = None,
) -> list[Source]:
    return discover_boulder_county(html=boco_html, years=years) + discover_secretary_of_state(
        html=sos_html, years=years
    )


def merge_with_registry(
    discovered: list[Source],
    *,
    only_new: bool = True,
) -> list[Source]:
    """Combine the static registry with newly discovered sources.

    Sources are keyed on (year, election_type, data_source), so a primary and
    a general in the same year are different sources. When ``only_new`` is
    True (default), entries that duplicate an existing registry key are
    dropped — the static registry wins. This is deliberate: the static URLs
    have been verified, and discovery URLs can change as the upstream sites
    are reorganized.
    """

    def key(s: Source) -> tuple[int, str, str]:
        return (s.year, s.election_type, s.data_source)

    if only_new:
        existing = {key(s) for s in SOURCES}
        return [s for s in discovered if key(s) not in existing]
    by_key: dict[tuple[int, str, str], Source] = {key(s): s for s in SOURCES}
    for s in discovered:
        by_key[key(s)] = s
    return list(by_key.values())


def _election_arg(value: str) -> tuple[int, str]:
    from .sources import parse_election_key

    try:
        return parse_election_key(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, help="Only consider this year")
    ap.add_argument(
        "-e",
        "--election",
        type=_election_arg,
        metavar="KEY",
        help="Only this election, as an election key, e.g. 2024-general",
    )
    ap.add_argument("--since", type=int, help="This year and later")
    ap.add_argument(
        "--source", choices=["boulder_county", "secretary_of_state", "all"], default="all"
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Include sources already in the static registry "
        "(default: only show newly discovered entries)",
    )
    ap.add_argument(
        "--json", action="store_true", help="Emit JSON instead of the human-readable summary"
    )
    args = ap.parse_args(argv)

    try:
        if args.source == "boulder_county":
            found = discover_boulder_county()
        elif args.source == "secretary_of_state":
            found = discover_secretary_of_state()
        else:
            found = discover()
    except requests.RequestException as e:
        print(f"FAIL fetching upstream pages: {e}", file=sys.stderr)
        return 2

    if args.year:
        found = [s for s in found if s.year == args.year]
    if args.election:
        found = [s for s in found if (s.year, s.election_type) == args.election]
    if args.since:
        found = [s for s in found if s.year >= args.since]

    new_sources = merge_with_registry(found, only_new=not args.all)

    if args.json:
        import json

        payload = [dataclasses.asdict(s) for s in new_sources]
        print(json.dumps(payload, indent=2))
    else:
        if not new_sources:
            print("No new sources discovered.")
            return 0
        print(f"Discovered {len(new_sources)} source(s) not in the static registry:")
        for s in new_sources:
            print(f"  {s.year}  {s.election_type:<12}  {s.data_source:<20}  {s.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
