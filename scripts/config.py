"""
Central configuration: path constants, HTTP defaults, and a SOURCES re-export.

Every module that needs a path or an HTTP knob imports it from here so the
"where do I look up X" question always has one answer. Previously REPO_ROOT
was duplicated across 6 modules and HTTP_TIMEOUT lived only in fetch.py.

Read this file first when adding a new module: chances are the constant you're
about to define already exists here.
"""

from __future__ import annotations

import os
from pathlib import Path

# Re-exported for downstream convenience — `from .config import SOURCES` is the
# canonical access path. `sources.py` continues to hold the actual registry +
# the Source dataclass; we just give it a friendlier name here.
from .sources import (  # noqa: F401
    ALL_SOURCES as SOURCES,
)
from .sources import (
    BOULDER_COUNTY,
    ELECTION_DATES,
    ELECTION_TYPES,
    SECRETARY_OF_STATE,
    Source,
    election_key,
    parse_election_key,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"

# The two-home rule (see AGENTS.md): only these two directories receive writes
# from parsers / fetchers / cleaners. `audit/` and `lookups/` are read-only
# artifacts derived from them.
ORIGINAL = DATA / "original"
PROCESSED = DATA / "processed"

# Read-only artifact dirs.
AUDIT = DATA / "audit"
LOOKUPS = DATA / "lookups"

# Where each data source's raw downloads live under ORIGINAL. Boulder County's
# Statement of Votes files sit in a subfolder next to the election-night
# screenshots (vote-counting/); SOS files sit at the top of their folder.
ORIGINAL_SUBDIRS: dict[str, str] = {
    "boulder_county": "boulder-county/statement-of-votes",
    "secretary_of_state": "secretary-of-state",
}


def original_path(data_source: str, local_filename: str) -> Path:
    """Absolute path of a registry file under data/original/."""
    return ORIGINAL / ORIGINAL_SUBDIRS[data_source] / local_filename


# Each dataset under PROCESSED gets its own subfolder, mirroring data/original/:
# the harmonized Statement of Votes CSVs (with their provenance sidecar and the
# combined CSV) and the election-night snapshots. Cross-dataset publishing
# artifacts (elections.db, metadata.yaml) stay at the top of PROCESSED.
STATEMENTS_OF_VOTES = PROCESSED / "statements-of-votes"
VOTE_COUNTING = PROCESSED / "vote-counting"


# Cross-dataset publishing artifacts (gitignored; built by scripts/publish.py).
DATASETTE_DB = PROCESSED / "elections.db"
DATASETTE_RECENT_DB = PROCESSED / "elections-recent.db"
DATASETTE_METADATA = PROCESSED / "metadata.yaml"
EXCEL_ZIP = PROCESSED / "statements-of-votes-excel.zip"

# Election-night snapshots: screenshots in, tidy CSVs + QA out. The Datalab
# response cache lives under the processed folder by design (see AGENTS §2.5):
# it is derived from data/original/, but rebuilding it costs money, so it is
# committed and the pipeline never re-OCRs.
VOTE_COUNTING_ORIGINAL = ORIGINAL / "boulder-county" / "vote-counting"
VOTE_COUNTING_CACHE = VOTE_COUNTING / "datalab"
VOTE_COUNTING_CONTESTS_CSV = VOTE_COUNTING / "vote-counting-contests.csv"
VOTE_COUNTING_SUMMARY_CSV = VOTE_COUNTING / "vote-counting-summary.csv"
VOTE_COUNTING_CORRECTIONS_CSV = REPO_ROOT / "scripts" / "corrections" / "vote-counting.csv"


def sov_csv_path(year: int, election_type: str, data_source: str) -> Path:
    """Harmonized per-year CSV: statements-of-votes/{election key}-{source}.csv,
    e.g. 2016-general-boulder-county.csv."""
    ds = data_source.replace("_", "-")
    return STATEMENTS_OF_VOTES / f"{election_key(year, election_type)}-{ds}.csv"


# Specific files used in several places.
MANIFEST_PATH = ORIGINAL / "manifest.json"
PROVENANCE_CSV = STATEMENTS_OF_VOTES / "provenance.csv"
COMBINED_CSV = STATEMENTS_OF_VOTES / "all-elections-tidy.csv"
RECONCILIATION_CSV = AUDIT / "reconciliation.csv"
RECONCILIATION_MD = AUDIT / "reconciliation.md"
RECONCILIATION_CANDIDATES_CSV = AUDIT / "reconciliation-candidates.csv"
VOTE_COUNTING_VS_SOV_CSV = AUDIT / "vote-counting-vs-sov.csv"
REJECTED_CSV = AUDIT / "rejected.csv"
AUDIT_SUMMARY_MD = AUDIT / "summary.md"
VOTE_COUNTING_QA_CSV = AUDIT / "vote-counting-qa.csv"
VOTE_COUNTING_QA_MD = AUDIT / "vote-counting.md"

# ---------------------------------------------------------------------------
# HTTP defaults
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = 60  # seconds — every requests.get() in the codebase

HTTP_USER_AGENT = (
    "Election-Results-Pipeline/0.1 "
    "(+https://github.com/BoulderPublicData/Election-Results) "
    "research/civic-data"
)

# requests-cache config (see scripts/http.py).
# - In dev: cache for 1 day so re-running pipeline.py doesn't re-download
#   files we just downloaded. Saves minutes per iteration.
# - In CI: the annual-refresh workflow sets ELECTIONS_HTTP_CACHE_HOURS=0.
HTTP_CACHE_HOURS = int(os.environ.get("ELECTIONS_HTTP_CACHE_HOURS", "24"))
HTTP_CACHE_PATH = REPO_ROOT / ".cache" / "requests-cache.sqlite"

# tenacity retry posture: 3 attempts, exponential backoff 1s → 2s → 4s.
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_MIN_WAIT = 1.0
HTTP_RETRY_MAX_WAIT = 8.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Diagnostics renderer: "json" for one JSON object per line; anything else
# (default "auto") renders key=value text. See scripts/logging_setup.py for
# the print-vs-log convention.
LOG_FORMAT = os.environ.get("ELECTIONS_LOG_FORMAT", "auto")
LOG_LEVEL = os.environ.get("ELECTIONS_LOG_LEVEL", "INFO")


# Convenience: any code that wants a path can do `config.ORIGINAL / ...` rather
# than recomputing REPO_ROOT.  When you find a module computing its own
# REPO_ROOT, swap it out for an import from here.
__all__ = [
    "REPO_ROOT", "DATA", "ORIGINAL", "PROCESSED", "AUDIT", "LOOKUPS",
    "ORIGINAL_SUBDIRS", "original_path",
    "MANIFEST_PATH", "PROVENANCE_CSV", "COMBINED_CSV",
    "RECONCILIATION_CSV", "RECONCILIATION_MD", "RECONCILIATION_CANDIDATES_CSV",
    "VOTE_COUNTING_VS_SOV_CSV", "REJECTED_CSV", "AUDIT_SUMMARY_MD",
    "STATEMENTS_OF_VOTES", "VOTE_COUNTING", "sov_csv_path",
    "DATASETTE_DB", "DATASETTE_RECENT_DB", "DATASETTE_METADATA", "EXCEL_ZIP",
    "VOTE_COUNTING_ORIGINAL", "VOTE_COUNTING_CACHE", "VOTE_COUNTING_CONTESTS_CSV",
    "VOTE_COUNTING_SUMMARY_CSV", "VOTE_COUNTING_CORRECTIONS_CSV",
    "VOTE_COUNTING_QA_CSV", "VOTE_COUNTING_QA_MD",
    "HTTP_TIMEOUT", "HTTP_USER_AGENT",
    "HTTP_CACHE_HOURS", "HTTP_CACHE_PATH",
    "HTTP_RETRY_ATTEMPTS", "HTTP_RETRY_MIN_WAIT", "HTTP_RETRY_MAX_WAIT",
    "LOG_FORMAT", "LOG_LEVEL",
    "SOURCES", "BOULDER_COUNTY", "SECRETARY_OF_STATE", "ELECTION_DATES", "Source",
    "ELECTION_TYPES", "election_key", "parse_election_key",
]
