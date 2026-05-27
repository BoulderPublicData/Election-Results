"""
structlog configuration. Replaces ad-hoc print() across the pipeline.

- **Interactive runs (TTY):** pretty key=value output with timestamps,
  level coloring, and grouped event names. Good for "what's happening".
- **CI / piped output:** JSON lines (one event per line) so GitHub Actions
  log filtering, `jq`, and downstream observability stacks can parse them.

Toggle explicitly with `ELECTIONS_LOG_FORMAT=json` or `=pretty`. Defaults to
`auto` (TTY → pretty, otherwise → json).

Every module that wants to log should do:

    from .logging_setup import get_logger
    log = get_logger(__name__)
    log.info("did_thing", count=42, source="boulder_county")

The keyword args become structured fields. `log.bind(source=...)` returns a
child logger with that field always attached — useful inside parsers so every
line carries `(source, vintage)`.
"""

from __future__ import annotations

import logging
import sys

import structlog

from . import config

_CONFIGURED = False


def _pretty_or_json() -> str:
    fmt = config.LOG_FORMAT.lower()
    if fmt in {"json", "pretty"}:
        return fmt
    # Auto: pretty if stderr is a TTY, JSON otherwise.
    return "pretty" if sys.stderr.isatty() else "json"


def configure_logging(level: str = "INFO") -> None:
    """Set up structlog. Idempotent — safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

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
