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
    BOULDER_COUNTY,
    SECRETARY_OF_STATE,
    ELECTION_DATES,
    Source,
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

# Specific files used in several places.
MANIFEST_PATH = ORIGINAL / "manifest.json"
PROVENANCE_CSV = PROCESSED / "provenance.csv"
COMBINED_CSV = PROCESSED / "all-elections-tidy.csv"
RECONCILIATION_CSV = AUDIT / "reconciliation.csv"
RECONCILIATION_MD = AUDIT / "reconciliation.md"
REJECTED_CSV = AUDIT / "rejected.csv"
AUDIT_SUMMARY_MD = AUDIT / "summary.md"

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
# - In CI: short cache or no cache (overridden by ELECTIONS_HTTP_CACHE_HOURS=0).
HTTP_CACHE_HOURS = int(os.environ.get("ELECTIONS_HTTP_CACHE_HOURS", "24"))
HTTP_CACHE_PATH = REPO_ROOT / ".cache" / "requests-cache.sqlite"

# tenacity retry posture: 3 attempts, exponential backoff 1s → 2s → 4s.
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_MIN_WAIT = 1.0
HTTP_RETRY_MAX_WAIT = 8.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Set to "json" in CI for parseable logs; "pretty" in interactive runs.
# scripts/logging.py picks the renderer based on this + tty detection.
LOG_FORMAT = os.environ.get("ELECTIONS_LOG_FORMAT", "auto")


# Convenience: any code that wants a path can do `config.ORIGINAL / ...` rather
# than recomputing REPO_ROOT.  When you find a module computing its own
# REPO_ROOT, swap it out for an import from here.
__all__ = [
    "REPO_ROOT", "DATA", "ORIGINAL", "PROCESSED", "AUDIT", "LOOKUPS",
    "MANIFEST_PATH", "PROVENANCE_CSV", "COMBINED_CSV",
    "RECONCILIATION_CSV", "RECONCILIATION_MD", "REJECTED_CSV", "AUDIT_SUMMARY_MD",
    "HTTP_TIMEOUT", "HTTP_USER_AGENT",
    "HTTP_CACHE_HOURS", "HTTP_CACHE_PATH",
    "HTTP_RETRY_ATTEMPTS", "HTTP_RETRY_MIN_WAIT", "HTTP_RETRY_MAX_WAIT",
    "LOG_FORMAT",
    "SOURCES", "BOULDER_COUNTY", "SECRETARY_OF_STATE", "ELECTION_DATES", "Source",
]
