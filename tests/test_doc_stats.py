"""#33: counts quoted in the docs are generated, so they can't silently go stale."""

from __future__ import annotations

import pytest

from scripts import doc_stats
from scripts.config import REPO_ROOT


def test_rewrite_replaces_only_marked_spans():
    text = "a <!-- generated:row-count -->1<!-- /generated:row-count --> b 1"
    out = doc_stats.rewrite(text, {"row-count": "409,496"})
    assert out == "a <!-- generated:row-count -->409,496<!-- /generated:row-count --> b 1"


def test_unavailable_value_leaves_span_alone():
    text = "<!-- generated:db-size -->105 MB<!-- /generated:db-size -->"
    assert doc_stats.rewrite(text, {"db-size": None}) == text


def test_data_dictionary_table_matches_the_csvs():
    """The §5 table must be the one doc_stats would write from the committed CSVs."""
    table = doc_stats.sov_table()
    if table is None:
        pytest.skip("processed CSVs not present")
    text = (REPO_ROOT / "docs" / "data-dictionary.md").read_text()
    assert (
        doc_stats.rewrite(text, {"sov-table": table, "row-count": doc_stats.row_count()}) == text
    ), "run `uv run python -m scripts.doc_stats`"
