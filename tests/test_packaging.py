"""Tooling contract: `uv sync` alone installs what AGENTS §10 runs (#32), the
entry points resolve, and the workflows keep their fixes (#19, #22)."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_dev_group_has_pytest_and_ruff():
    dev = " ".join(PYPROJECT["dependency-groups"]["dev"])
    assert "pytest" in dev and "ruff" in dev
    assert "dev" not in PYPROJECT["project"].get("optional-dependencies", {})


def test_python_version_pinned_to_the_floor():
    assert (ROOT / ".python-version").read_text().strip() == "3.11"
    assert PYPROJECT["project"]["requires-python"] == ">=3.11"


def test_every_entry_point_resolves():
    scripts = PYPROJECT["project"]["scripts"]
    assert {"elections-publish", "elections-vote-counting"} <= set(scripts)
    for target in scripts.values():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func)), target


def test_pipeline_help_lists_every_subcommand():
    from scripts.pipeline import SUBCOMMANDS, _epilog

    for name in SUBCOMMANDS:
        assert f"  {name}" in _epilog()


def test_annual_refresh_targets_previous_year():
    wf = (ROOT / ".github/workflows/annual-sov-refresh.yml").read_text()
    assert "yesterday" not in wf and "-v-1d" not in wf
    assert "$(( $(date -u +%Y) - 1 ))" in wf


def test_publish_workflow_does_not_reparse_without_pdfs():
    wf = (ROOT / ".github/workflows/publish.yml").read_text()
    assert "--no-pdf" not in wf


def test_every_cli_takes_an_election_key():
    """#34: one --election {year}-{type} option across the CLIs (and CVR)."""
    import argparse

    import pytest

    for name in ("clean", "fetch", "pipeline", "reconcile", "discover"):
        mod = importlib.import_module(f"scripts.{name}")
        assert mod._election_arg("2024-general") == (2024, "general")
        assert mod._election_arg("2023C") == (2023, "coordinated")
        with pytest.raises(argparse.ArgumentTypeError):
            mod._election_arg("2024-General-Election")


def test_changelog_and_glossary_are_shared_pages():
    assert (ROOT / "docs" / "changelog.md").exists()
    assert (ROOT / "docs" / "glossary.md").exists()
    assert (
        "docs/changelog.md" in (ROOT / "docs" / "data-dictionary.md").read_text()
        or "(changelog.md)" in (ROOT / "docs" / "data-dictionary.md").read_text()
    )
