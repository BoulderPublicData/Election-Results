"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def boco_results_html() -> str:
    return (FIXTURES / "boco-results-2026-05.html").read_text(encoding="utf-8")


@pytest.fixture
def sos_archives_html() -> str:
    return (FIXTURES / "sos-archives-2026-05.html").read_text(encoding="utf-8")


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
