"""Pins the n >= 10 suppression rule (spec P21, §8).

This is the only shared module in the project and the reason it is shared is
recorded in P23: duplicating *analysis* logic risks correlated errors that look
like agreement, which no longer matters here; duplicating *suppression* logic
risks one notebook publishing a cell the other would have withheld, which is a
disclosure failure and has to be impossible rather than merely unlikely.

The rule, stated once: a published count of 1..9 is suppressed, suppression
drops the WHOLE ROW rather than blanking a cell, and a count of exactly zero is
published -- "this never happened" and "this is missing" are different
statements and a multi-site table may not confuse them.

Run:  uv run pytest tests/test_min_cell_suppression.py -v
"""

import polars as pl
import pytest

from utils.suppress import MIN_CELL, apply_min_cell, publish, small_cell_mask


def _frame(counts):
    return pl.DataFrame({"bin": [f"b{i}" for i in range(len(counts))], "n": counts})


def test_min_cell_is_ten():
    assert MIN_CELL == 10


@pytest.mark.parametrize(
    ("n", "dropped"),
    [(0, False), (1, True), (9, True), (10, False), (11, False), (1000, False)],
)
def test_boundary(n, dropped):
    """Zero is published; 1..9 are not; 10 is the first publishable positive count."""
    kept, gone = apply_min_cell(_frame([n]), ["n"], "t")
    assert (gone.height == 1) is dropped
    assert (kept.height == 1) is not dropped


def test_any_count_column_triggers():
    """A row is dropped if ANY of its published counts is disclosive."""
    df = pl.DataFrame({"bin": ["a", "b"], "n_x": [50, 50], "n_y": [50, 3]})
    kept, gone = apply_min_cell(df, ["n_x", "n_y"], "t")
    assert kept.get_column("bin").to_list() == ["a"]
    assert gone.get_column("bin").to_list() == ["b"]


def test_whole_row_is_dropped_not_blanked():
    """A blanked cell in a table whose margins are published is recoverable by
    subtraction, so the row goes entirely."""
    df = pl.DataFrame({"bin": ["a"], "n_x": [500], "n_y": [4]})
    kept, _ = apply_min_cell(df, ["n_x", "n_y"], "t")
    assert kept.height == 0


def test_fully_suppressed_frame_is_empty_not_an_error():
    """Every cell disclosive must yield an empty frame with the schema intact --
    downstream figure code reads this frame and must degrade, not raise."""
    kept, gone = apply_min_cell(_frame([1, 2, 3]), ["n"], "t")
    assert kept.height == 0
    assert kept.columns == ["bin", "n"]
    assert gone.height == 3


def test_mask_is_a_plain_boolean_series():
    mask = small_cell_mask(_frame([0, 5, 10]), ["n"])
    assert mask.to_list() == [False, True, False]


def test_publish_writes_only_the_kept_rows(tmp_path):
    path = tmp_path / "out.csv"
    kept = publish(_frame([50, 3, 12]), path, ["n"], "t")
    written = pl.read_csv(path)
    assert kept.height == 2
    assert written.get_column("n").to_list() == [50, 12]


def test_publish_reports_what_it_dropped(tmp_path, capsys):
    """Never silent: a suppressed row must be visible in the run log."""
    publish(_frame([50, 3]), tmp_path / "out.csv", ["n"], "gap_distribution")
    out = capsys.readouterr().out
    assert "gap_distribution" in out
    assert "1 row" in out
