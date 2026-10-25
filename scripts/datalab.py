"""
Thin client for the Datalab document-conversion API (https://www.datalab.to).

Used by scripts/vote_counting.py to OCR the election-night results screenshots
under data/original/boulder-county/vote-counting/. Only the one endpoint we
need is wrapped: submit a file to `/api/v1/convert`, poll the
`request_check_url` until the job completes, and return the JSON payload.

Responses are cached on disk by the caller (keyed on the input file's sha256)
so the pipeline never re-bills the API for an image it has already converted.
The API key comes from the `DATALAB_API_KEY` environment variable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from . import config
from .logging_setup import get_logger

log = get_logger(__name__)

DATALAB_HOST = os.environ.get("DATALAB_HOST", "https://www.datalab.to")
CONVERT_ENDPOINT = f"{DATALAB_HOST}/api/v1/convert"

POLL_INTERVAL = 3.0  # seconds between status checks
POLL_TIMEOUT = 600.0  # give up on a single job after 10 minutes
SUBMIT_ATTEMPTS = 4


class DatalabError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("DATALAB_API_KEY")
    if not key:
        raise DatalabError(
            "DATALAB_API_KEY is not set — export it, or run with the cached "
            "responses already committed under data/processed/vote-counting/datalab/"
        )
    return key


def convert(path: Path, *, mode: str = "accurate", output_format: str = "json",
            mime: str = "application/pdf") -> dict[str, Any]:
    """Convert one file and return the completed job payload.

    Raises DatalabError if the job fails or never completes.
    """
    headers = {"X-Api-Key": _api_key(), "User-Agent": config.HTTP_USER_AGENT}
    data = {
        "output_format": output_format,
        "mode": mode,
        "disable_image_extraction": "true",
        "disable_image_captions": "true",
    }

    resp = None
    for attempt in range(1, SUBMIT_ATTEMPTS + 1):
        try:
            with path.open("rb") as fh:
                resp = requests.post(
                    CONVERT_ENDPOINT, headers=headers, data=data,
                    files={"file": (path.name, fh, mime)},
                    timeout=config.HTTP_TIMEOUT,
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            break
        except requests.RequestException as e:
            if attempt == SUBMIT_ATTEMPTS:
                raise DatalabError(f"submit {path.name}: {e}") from e
            wait = 2 ** attempt
            log.warning("datalab.submit_retry", file=path.name, attempt=attempt,
                        wait=wait, error=str(e))
            time.sleep(wait)
    assert resp is not None
    if resp.status_code != 200:
        raise DatalabError(f"submit {path.name}: HTTP {resp.status_code} {resp.text[:300]}")
    check_url = resp.json()["request_check_url"]

    start = time.monotonic()
    while time.monotonic() - start < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            r = requests.get(check_url, headers=headers, timeout=config.HTTP_TIMEOUT)
        except requests.RequestException as e:
            log.warning("datalab.poll_retry", file=path.name, error=str(e))
            continue
        if r.status_code != 200:
            log.warning("datalab.poll_status", file=path.name, status=r.status_code)
            continue
        payload = r.json()
        if payload.get("status") != "complete":
            continue
        if not payload.get("success"):
            raise DatalabError(f"convert {path.name}: {payload.get('error')}")
        return payload
    raise DatalabError(f"convert {path.name}: timed out after {POLL_TIMEOUT:.0f}s")
