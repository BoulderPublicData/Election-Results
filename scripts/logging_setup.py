"""
structlog configuration, and the project's output convention.

**Convention (#33).** Two channels, never mixed:

- **User-facing output** — progress and results (`OK …`, `wrote …`, `skip …`)
  — is plain ``print()`` to **stdout**; problems the user must act on
  (`WARN …`, `FAIL …`) are ``print(..., file=sys.stderr)``. This is what the
  CLIs, the pipeline and the GitHub Actions logs show.
- **Diagnostics** — retries, stale caches, debug detail — go through
  structlog to **stderr**. They never repeat a line already printed.

Rendering: key=value lines by default (colored on a TTY). Set
``ELECTIONS_LOG_FORMAT=json`` for one JSON object per line (log shippers,
``jq``). ``ELECTIONS_LOG_LEVEL`` (default ``INFO``) sets the threshold.

Every module that wants to log should do:

    from .logging_setup import get_logger
    log = get_logger(__name__)
    log.warning("thing_retried", attempt=2, source="boulder_county")

The keyword args become structured fields. `log.bind(source=...)` returns a
child logger with that field always attached.
"""

from __future__ import annotations

import logging
import sys

import structlog

from . import config

_CONFIGURED = False


def _pretty_or_json() -> str:
    # "auto" (the default) and "pretty" both render key=value text; JSON is
    # opt-in, so diagnostics read like the rest of the CLI output in a
    # terminal and in CI logs alike.
    return "json" if config.LOG_FORMAT.lower() == "json" else "pretty"


def configure_logging(level: str | None = None) -> None:
    """Set up structlog. Idempotent — safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True
    level = level or config.LOG_LEVEL

    # Bridge stdlib logging through structlog so requests/urllib3 logs pick up
    # the same format.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if _pretty_or_json() == "pretty":
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger bound to a dotted module name."""
    configure_logging()
    return structlog.get_logger(name)
