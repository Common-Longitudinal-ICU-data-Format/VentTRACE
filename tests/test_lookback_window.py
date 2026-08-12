"""Pins the look-back window of `04_covariates.py` (spec P33).

Twelve interval tests live in that notebook -- four exposure sources times three
windows -- and they all call one helper for the reason P15 gives about D and E:
two implementations of an interval test drift at the boundary, and a one-row
disagreement between "on pressors" and "on CRRT" is invisible in aggregate.

The window is closed at BOTH ends: t0 - Xh <= dttm <= t0. A row exactly on the
far edge is in; a row one microsecond earlier is out; a row after t0 is out --
an exposure "before the index" may not include the index minute's own charting
sweeping forward.

Run:  uv run pytest tests/test_lookback_window.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl

NOTEBOOK = Path(__file__).parent.parent / "code" / "04_covariates.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())


def _load_from_notebook(name, namespace=None):
    found = [
        node
        for node in ast.walk(NOTEBOOK_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one def {name} in {NOTEBOOK.name}, found {len(found)}"
    )
    ns = {"pl": pl}
    ns.update(namespace or {})
    exec(compile(ast.Module(body=[found[0]], type_ignores=[]), NOTEBOOK.name, "exec"), ns)
    return ns[name]


in_lookback = _load_from_notebook("in_lookback")

T0 = datetime.datetime(2024, 3, 1, 12, 0, 0)


def _frame(offsets_minutes):
    return pl.DataFrame(
        {
            "t0": [T0] * len(offsets_minutes),
            "dttm": [T0 + datetime.timedelta(minutes=m) for m in offsets_minutes],
        }
    )


def test_far_edge_is_inclusive():
    """A row exactly on t0 - 24h is inside the 24h window."""
    got = _frame([-1440]).select(in_lookback("t0", "dttm", 24)).to_series().to_list()
    assert got == [True]


def test_one_microsecond_before_far_edge_is_out():
    df = pl.DataFrame(
        {
            "t0": [T0],
            "dttm": [T0 - datetime.timedelta(hours=24, microseconds=1)],
        }
    )
    assert df.select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [False]


def test_t0_itself_is_inclusive():
    """The window closes ON t0, so charting at the index minute counts."""
    assert _frame([0]).select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [True]


def test_after_t0_is_out():
    """One second after the index is not 'before the index'."""
    df = pl.DataFrame({"t0": [T0], "dttm": [T0 + datetime.timedelta(seconds=1)]})
    assert df.select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [False]


def test_windows_nest():
    """1h subset of 6h subset of 24h -- a row in a tighter window is in every wider one."""
    offsets = [-30, -180, -1000, -2000]
    df = _frame(offsets)
    got = df.select(
        in_lookback("t0", "dttm", 1).alias("h1"),
        in_lookback("t0", "dttm", 6).alias("h6"),
        in_lookback("t0", "dttm", 24).alias("h24"),
    )
    for row in got.iter_rows(named=True):
        assert not (row["h1"] and not row["h6"]), "in 1h but not 6h"
        assert not (row["h6"] and not row["h24"]), "in 6h but not 24h"
    assert got.to_dicts() == [
        {"h1": True, "h6": True, "h24": True},
        {"h1": False, "h6": True, "h24": True},
        {"h1": False, "h6": False, "h24": True},
        {"h1": False, "h6": False, "h24": False},
    ]


def test_null_dttm_is_not_in_window():
    """A missing timestamp is not an exposure. Null must not propagate as true."""
    df = pl.DataFrame({"t0": [T0], "dttm": [None]}, schema={"t0": pl.Datetime, "dttm": pl.Datetime})
    assert df.select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [False]
