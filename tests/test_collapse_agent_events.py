"""Pins the index-paralytic fold in `code/02_index_paralytic.py` (spec P6, P19).

`collapse_agent_events` is what turns paralytic administrations into index
paralytics, and the index paralytic's first administration is `t` -- the clock
that sub-analyses C, D and E all measure against. A fold bug therefore does not
produce a slightly wrong count; it moves the study's origin.

The one property worth a test of its own is that the window is **anchored on the
event's first row, not chained off the previous one**. Chained, an agent redosed
every ten minutes would grow into one event spanning the whole stay, and its `t`
would sit hours from most of its own doses. Anchored, every event is bounded by
the gap end to end. Case (d) below is the case that tells the two apart, and it
is the only one a chained implementation fails.

This file previously pinned the same function in the deleted `05_method_pair.py`,
where it folded sedatives and paralytics separately before a pairing scan. The
function moved without changing; only its consumer did.

The function is lifted out of the notebook by AST rather than imported:
`02_index_paralytic` is a marimo notebook whose module name is not a Python
identifier, and importing it would run the whole pipeline against real PHI.

Run:  uv run pytest tests/test_collapse_agent_events.py -v
"""

import ast
import datetime
import os
import time
from pathlib import Path

import polars as pl
import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "02_index_paralytic.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())

# P19 ("the timezone always comes from config['timezone']; no code path consults the
# OS zone") binds in every notebook, not just this one -- test_notebook_calls_no_naive_
# timestamp below walks all three.
ALL_NOTEBOOKS = [
    Path(__file__).parent.parent / "code" / name
    for name in ("01_cohort.py", "02_index_paralytic.py", "03_context.py")
]


def _load_from_notebook(name, namespace=None):
    """Compile a single named function out of the marimo notebook."""
    found = [
        node
        for node in ast.walk(NOTEBOOK_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one def {name} in {NOTEBOOK.name}, found {len(found)}"
    )
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(namespace or {})
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[name]


collapse_agent_events = _load_from_notebook("collapse_agent_events")
epoch_minutes = _load_from_notebook("epoch_minutes", {"pl": pl})

GAP = 15.0

# (label, times, expected grouping) — the D43 worked examples, verbatim.
WORKED_EXAMPLES = [
    ("a same-instant co-administration merges", [0, 0], [[0, 1]]),
    ("b exactly at the limit still merges", [0, 15], [[0, 1]]),
    ("c one minute past the limit splits", [0, 16], [[0], [1]]),
    ("d anchored, not chained", [0, 10, 20], [[0, 1], [2]]),
    ("e a run inside one window stays one event", [0, 5, 10, 15], [[0, 1, 2, 3]]),
    ("f singleton", [0], [[0]]),
]


def _call(times, gap=GAP, categories=None):
    if categories is None:
        categories = ["x"] * len(times)
    return collapse_agent_events([float(t) for t in times], categories, gap)


@pytest.mark.parametrize(
    ("label", "times", "expected"),
    WORKED_EXAMPLES,
    ids=[case[0][0] for case in WORKED_EXAMPLES],
)
def test_worked_example(label, times, expected):
    assert _call(times) == expected, label


def test_boundary_is_strictly_greater():
    """15 min merges, 15.001 min does not — the parameter reads inclusively."""
    assert _call([0, GAP]) == [[0, 1]]
    assert _call([0, GAP + 0.001]) == [[0], [1]]


def test_anchor_does_not_walk_forward():
    """A dose every 10 min for two hours must not become one two-hour event.

    This is the failure the anchor exists to prevent: chained off the previous row every
    one of these joins, and the whole stay collapses to a single event.
    """
    times = list(range(0, 121, 10))
    events = _call(times)
    assert len(events) > 1, "the event walked forward off its predecessor"
    for event in events:
        assert times[event[-1]] - times[event[0]] <= GAP


@pytest.mark.parametrize(
    "times",
    [
        [],
        [0],
        [0, 0, 0, 0],
        [0, 15, 30, 45, 60],
        [0, 1, 2, 3, 4, 5, 60, 61, 200],
        [0, 16, 32, 33, 34, 100, 100, 100, 116],
        list(range(0, 200, 7)),
        list(range(0, 60)),
    ],
)
def test_partition_property(times):
    """Concatenating the returned index-lists reproduces range(n) exactly.

    Nothing lost, nothing duplicated, nothing reordered — the property `02` asserts on
    real data as `sum(n_admins) == scan_rows.height`.
    """
    events = _call(times)
    flat = [i for event in events for i in event]
    assert flat == list(range(len(times)))
    assert all(event for event in events), "an empty event was emitted"


@pytest.mark.parametrize(
    "times", [[0], [0, 10, 20], [0, 15, 16, 31], list(range(0, 200, 7))]
)
def test_every_event_is_within_the_gap(times):
    """The invariant the function's docstring names, checked end to end per event."""
    for event in _call(times):
        assert times[event[-1]] - times[event[0]] <= GAP


def test_grouping_ignores_categories():
    """A repeat of one agent and a co-administration of two fold identically.

    Which agents were involved is recorded by the caller in `agent_label`; it must play no
    part in the fold, or a co-administration would become two index paralytics and the
    study would count one intubation twice.
    """
    times = [0, 2, 40]
    same = _call(times, categories=["rocuronium", "rocuronium", "rocuronium"])
    mixed = _call(times, categories=["rocuronium", "vecuronium", "succinylcholine"])
    assert same == mixed == [[0, 1], [2]]


def test_length_mismatch_is_caught():
    with pytest.raises(AssertionError):
        collapse_agent_events([0.0, 1.0], ["x"], GAP)


# --------------------------------------------------------------------------------------
# The timezone trap: `datetime.timestamp()` on a NAIVE datetime reads the OS zone
# --------------------------------------------------------------------------------------
#
# `admin_dttm` is site-naive — US/Eastern wall clock with the tzinfo stripped, produced by
# `to_site_naive`. Calling `.timestamp()` on such a value does not treat it as the wall
# clock it is: Python interprets it in the *operating system's* zone and converts. Run on a
# US/Central machine against US/Eastern data, the fall-back hour is applied a second time
# and a ten-minute gap measures seventy.
#
# Seventy against a fifteen-minute collapse window is not a rounding error, it is a
# different answer: two doses that are one push of drug split into two agent events, one of
# which can then pair with a paralytic on its own. And because it depends on the machine's
# TZ, the same code on two laptops produces two different parquets — the exact failure the
# §6.2 sort is so careful to prevent.

FALL_BACK = [
    datetime.datetime(2023, 11, 5, 1, 55),  # US/Eastern wall clock, 5 min before the repeat
    datetime.datetime(2023, 11, 5, 2, 5),  # ten minutes later on the wall
]


@pytest.fixture
def central_os_timezone():
    """Force the OS zone to US/Central — a zone the data is NOT in."""
    if not hasattr(time, "tzset"):
        pytest.skip("no time.tzset on this platform")
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/Chicago"
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = before
        time.tzset()


def test_the_trap_is_real(central_os_timezone):
    """Guards the guard: if this ever stops failing, the tests below prove nothing."""
    naive = (FALL_BACK[1].timestamp() - FALL_BACK[0].timestamp()) / 60.0
    assert naive == pytest.approx(70.0), (
        "naive .timestamp() no longer re-applies the OS fall-back hour, so the regression "
        "tests below no longer discriminate — re-derive them before trusting them."
    )


def test_epoch_minutes_ignores_the_os_timezone(central_os_timezone):
    """Ten minutes of wall clock must measure ten minutes, on any machine."""
    minutes = (
        pl.DataFrame({"admin_dttm": FALL_BACK})
        .with_columns(m=epoch_minutes())
        .get_column("m")
        .to_list()
    )
    assert minutes[1] - minutes[0] == pytest.approx(10.0)


def test_collapse_merges_across_a_dst_fall_back(central_os_timezone):
    """The end-to-end consequence: these two doses are one agent event, not two.

    Fails if `epoch_minutes` is "simplified" back to `x.timestamp() / 60.0` — 70 minutes is
    past the 15-minute window and the fold splits them.
    """
    minutes = (
        pl.DataFrame({"admin_dttm": FALL_BACK})
        .with_columns(m=epoch_minutes())
        .get_column("m")
        .to_list()
    )
    assert collapse_agent_events(minutes, ["rocuronium", "vecuronium"], GAP) == [[0, 1]]

    # ... and the discarded idiom would have split them, which is the whole point.
    naive = [t.timestamp() / 60.0 for t in FALL_BACK]
    assert collapse_agent_events(naive, ["rocuronium", "vecuronium"], GAP) == [[0], [1]]


@pytest.mark.parametrize("notebook_path", ALL_NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_calls_no_naive_timestamp(notebook_path):
    """No stage of `01`, `02` or `03` may convert a timestamp by asking the OS what
    zone it is in.

    Walks each notebook's AST rather than grepping, so the trap named in
    `epoch_minutes`' docstring does not itself trip the check. P19 binds everywhere in
    this pipeline, not only in the notebook the rest of this file otherwise pins.
    """
    tree = ast.parse(notebook_path.read_text())
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "timestamp"
    ]
    assert not offenders, (
        f"{notebook_path.name} calls .timestamp() at line(s) {offenders}. On a "
        "site-naive column that reads the OS timezone, not config['timezone'] -- use "
        "epoch_minutes()."
    )
