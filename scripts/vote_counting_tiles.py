"""
Slice a full-page results screenshot into a multi-page PDF for OCR.

The election-night screenshots are 9,000-21,000 px tall; Datalab rejects images
taller than 15,000 px and down-samples tall pages. We cut each screenshot into
pages of at most `MAX_TILE_HEIGHT` px, always cutting through the white gap
*between* contest cards so no results table is ever split across pages.

The gap detector looks at a band through the middle of the page (always inside
the results card, whatever the page width) and finds runs of rows that are
entirely white. Table rows alternate grey / off-white and never read as pure
white, so a run of >= `MIN_GAP_ROWS` white rows is a between-card gap.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # screenshots are large but trusted, local files

MAX_TILE_HEIGHT = 3600
MIN_GAP_ROWS = 18
WHITE_THRESHOLD = 248  # min(R, G, B) at or above this counts as white
BAND = (0.33, 0.67)  # fraction of page width sampled for gap detection


def gap_midpoints(im: Image.Image) -> list[int]:
    """Return the y-coordinate of the middle of every between-card white gap."""
    arr = np.asarray(im.convert("RGB"))
    x0, x1 = int(arr.shape[1] * BAND[0]), int(arr.shape[1] * BAND[1])
    band = arr[:, x0:x1]
    is_white = (band.min(axis=2) >= WHITE_THRESHOLD).mean(axis=1) > 0.995

    mids: list[int] = []
    start: int | None = None
    for y, white in enumerate(is_white):
        if white and start is None:
            start = y
        elif not white and start is not None:
            if y - start >= MIN_GAP_ROWS:
                mids.append((start + y) // 2)
            start = None
    return mids


def cut_points(height: int, gaps: list[int], max_tile: int = MAX_TILE_HEIGHT) -> list[int]:
    """Greedy cut list [0, ..., height]: each tile is as tall as possible
    without exceeding `max_tile`, cutting only at gap midpoints. If a single
    card is taller than `max_tile` (no gap available), cut at the next gap."""
    cuts = [0]
    while height - cuts[-1] > max_tile:
        top = cuts[-1]
        candidates = [g for g in gaps if top < g <= top + max_tile]
        if candidates:
            cuts.append(candidates[-1])
            continue
        later = [g for g in gaps if g > top]
        if not later:
            break
        cuts.append(later[0])
    cuts.append(height)
    return cuts


def to_tiled_pdf(path: Path) -> tuple[bytes, list[int]]:
    """Return (pdf_bytes, cut_points) for one screenshot."""
    im = Image.open(path).convert("RGB")
    cuts = cut_points(im.height, gap_midpoints(im))
    pages = [im.crop((0, top, im.width, bottom)) for top, bottom in zip(cuts, cuts[1:], strict=False)]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
    return buf.getvalue(), cuts
