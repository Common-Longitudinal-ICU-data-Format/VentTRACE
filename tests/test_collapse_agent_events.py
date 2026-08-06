"""Pins the agent-event collapse in `code/05_method_pair.py` (D40).

The PAIR scan counts *pairings*, so what it is handed decides what a pair means. Before
the collapse existed the scan was handed raw administration rows, and a single rapid
sequence induction charted as fentanyl / propofol / rocuronium plus a repeat push came
back as several "intubations". `collapse_agent_events` folds administrations within
`collapse_gap_minutes` of each other into one clinical agent event, separately within
each drug class of each encounter, before the scan ever runs.

The one property worth a test of its own is that the window is **anchored on the event's
first row, not chained off the previous one**. Chained, a maintenance infusion charted
every ten minutes would grow into one event spanning the whole stay, and the second
intubation of a re-intubated patient would vanish into it. Anchored, every event is
bounded by the gap end to end. Case (d) below is the case that tells the two apart, and
it is the only one a chained implementation fails.

The function is lifted out of the notebook by AST rather than imported: `05_method_pair`
is a marimo notebook whose module name is not a Python identifier, and importing it
would run the whole pipeline against real PHI.

Run:  uv run pytest tests/test_collapse_agent_events.py -v
"""

import ast
from pathlib import Path

import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "05_method_pair.py"
FUNC_NAME = "collapse_agent_events"


def _load_from_notebook():
    """Compile just `collapse_agent_events` out of the marimo notebook."""
    tree = ast.parse(NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME
    ]
    assert len(found) == 1, (
        f"expected exactly one def {FUNC_NAME} in {NOTEBOOK.name}, found {len(found)}"
    )
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[FUNC_NAME]


collapse_agent_events = _load_from_notebook()

GAP = 15.0

# (label, times, expected grouping) — the D40 worked examples, verbatim.
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

    Nothing lost, nothing duplicated, nothing reordered — the property `05` asserts on
    real data as `sum(n_admin) == scan_rows.height`.
    """
    events = _call(times)
    flat = [i for event in events for i in event]
    assert flat == list(range(len(times)))
    assert all(event for event in events), "an empty event was emitted"


@pytest.mark.parametrize("times", [[], [0], [0, 10, 20], list(range(0, 200, 7))])
def test_every_event_is_within_the_gap(times):
    """The invariant the function's docstring names, checked end to end per event."""
    for event in _call(times):
        assert times[event[-1]] - times[event[0]] <= GAP


def test_grouping_ignores_categories():
    """A repeat of one agent and a co-administration of two fold identically.

    Which agents were involved is recorded by the caller in the D40.5 label; it must play
    no part in the fold, or a co-administration would be scanned as two events and pair
    twice.
    """
    times = [0, 2, 40]
    same = _call(times, categories=["fentanyl", "fentanyl", "fentanyl"])
    mixed = _call(times, categories=["fentanyl", "propofol", "midazolam"])
    assert same == mixed == [[0, 1], [2]]


def test_length_mismatch_is_caught():
    with pytest.raises(AssertionError):
        collapse_agent_events([0.0, 1.0], ["x"], GAP)
