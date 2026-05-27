"""
HTTP helpers: a single session with caching, retries, and the canonical
User-Agent baked in. Every module that does GET requests should go through
`get()` here rather than calling `requests.get(...)` directly.

- **Caching** via requests-cache (SQLite-backed). Cache lifetime is
  `config.HTTP_CACHE_HOURS` (24h by default). Set
  `ELECTIONS_HTTP_CACHE_HOURS=0` to disable entirely (CI does this).
- **Retries** via tenacity. 3 attempts, exponential 1s → 2s → 4s, on
  RequestException + 5xx + 429. Network blips no longer kill a refresh PR.
- **User-Agent** comes from config.HTTP_USER_AGENT — one place to update.
"""

from __future__ import annotations

import time
from typing import Any

import requests
import requests_cache
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt,
    wait_exponential, before_sleep_log,
)

from . import config
from .logging_setup import get_logger

log = get_logger(__name__)


def _build_session() -> requests.Session:
    """Module-level singleton — share connection pools + cache across calls."""
    if config.HTTP_CACHE_HOURS > 0:
        config.HTTP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        session = requests_cache.CachedSession(
            cache_name=str(config.HTTP_CACHE_PATH.with_suffix("")),
            backend="sqlite",
            expire_after=config.HTTP_CACHE_HOURS * 3600,
            allowable_methods=("GET",),
            stale_if_error=True,  # if the next refresh fails, serve the stale entry
        )
    else:
        session = requests.Session()
    session.headers["User-Agent"] = config.HTTP_USER_AGENT
    return session


_session: requests.Session | None = None


def session() -> requests.Session:
    """Return the shared session (lazy-built)."""
    global _session
    if _session is None:
        _session = _build_session()
    return _session


class _Transient(Exception):
    """5xx / 429 — worth retrying. 4xx (other) we surface immediately."""


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_RETRY_ATTEMPTS),
    wait=wait_exponential(
        multiplier=config.HTTP_RETRY_MIN_WAIT,
        max=config.HTTP_RETRY_MAX_WAIT,
    ),
    retry=retry_if_exception_type((_Transient, requests.exceptions.RequestException)),
)
def get(url: str, **kwargs: Any) -> requests.Response:
    """Cached + retried GET. Timeout defaults to config.HTTP_TIMEOUT.

    Returns the Response. Raises after exhausting retries for transient errors,
    or immediately for 4xx (except 429)."""
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT)
    resp = session().get(url, **kwargs)
    # 429 + 5xx are worth retrying.
    if resp.status_code == 429 or 500 <= resp.status_code < 600:
        log.warning(
            "http.transient_status", url=url, status=resp.status_code,
            from_cache=getattr(resp, "from_cache", False),
        )
        raise _Transient(f"HTTP {resp.status_code} from {url}")
    return resp


def get_bytes(url: str, **kwargs: Any) -> bytes:
    """Cached + retried download. Returns the response body as bytes.
    Raises HTTPError for non-2xx after retry exhaustion."""
    resp = get(url, **kwargs)
    resp.raise_for_status()
    return resp.content


def get_text(url: str, **kwargs: Any) -> str:
    """Cached + retried text fetch (for HTML pages discover.py scrapes)."""
    resp = get(url, **kwargs)
    resp.raise_for_status()
    return resp.text


def clear_cache() -> None:
    """Drop the on-disk cache. Useful in tests."""
    s = session()
    if isinstance(s, requests_cache.CachedSession):
        s.cache.clear()
