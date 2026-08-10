"""Pins the non-IMV -> IMV transition rule of `code/03_context.py` (spec P12, P13).

Sub-analysis D asks whether the DEVICE CHANGED around the index paralytic, not
whether IMV was charted. The distinction is the whole design: a patient who has
been ventilated for a week satisfies "IMV was charted in +/-60 min" without
anything having happened, so a state test cannot answer the question a transition
test answers.

Four cases define the rule and all four are checked below:

    nasal  -> imv     TRANSITION      an observed device change
    null   -> imv     TRANSITION      null is not imv; this is the first thing
                                      we ever learned about the airway
    [first row] imv   TRANSITION      the block opens on a ventilator -- the
                                      airway was secured before the extract's
                                      first row, which is a property of the
                                      extract, not evidence nothing occurred
    imv    -> imv     not a transition

The null case is the one that bites: `shift(1) != 'imv'` evaluates to NULL, not
TRUE, when the previous device is null, so a naive predicate silently drops every
one of them. `test_null_predecessor_is_a_transition` is that regression.

Run:  uv run pytest tests/test_imv_transition.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl
import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "03_context.py"
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
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(namespace or {})
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[name]


is_transition_expr = _load_from_notebook("is_transition_expr", {"pl": pl})
mark_transitions = _load_from_notebook(
    "mark_transitions", {"pl": pl, "is_transition_expr": is_transition_expr}
)
in_window_expr = _load_from_notebook("in_window_expr", {"pl": pl})

BASE = datetime.datetime(2024, 3, 1, 12, 0)


def _waterfall(spec):
    """spec: list of (encounter_block, hours_after_BASE, device_category | None)."""
    return pl.DataFrame(
        {
            "encounter_block": [b for b, _, _ in spec],
            "recorded_dttm": [BASE + datetime.timedelta(hours=h) for _, h, _ in spec],
            "device_category": [d for _, _, d in spec],
        },
        schema_overrides={"device_category": pl.String},
    )


def _flags(spec):
    return mark_transitions(_waterfall(spec)).get_column("is_transition").to_list()


# ------------------------------------------------------------- the four cases


def test_observed_non_imv_to_imv_is_a_transition():
    assert _flags([(1, 0, "nasal cannula"), (1, 1, "imv")]) == [False, True]


def test_null_predecessor_is_a_transition():
    """THE regression. `shift(1) != 'imv'` is NULL when the previous device is null,
    and a filter on NULL keeps nothing -- so a naive predicate silently drops every
    patient whose record begins before anyone charted a device."""
    assert _flags([(1, 0, None), (1, 1, "imv")]) == [False, True]


def test_a_block_opening_on_imv_is_a_transition():
    """There is no preceding row at all. The airway was secured before the extract's
    first row, which is a property of the extract and not evidence that nothing
    happened (P12)."""
    assert _flags([(1, 0, "imv"), (1, 1, "imv")]) == [True, False]


def test_imv_to_imv_is_not_a_transition():
    assert _flags([(1, 0, "imv"), (1, 1, "imv"), (1, 2, "imv")]) == [True, False, False]


# --------------------------------------------------------------- around them


def test_extubation_and_reintubation_give_two_transitions():
    """A patient taken off the vent and put back on has had two airway events."""
    assert _flags(
        [(1, 0, "imv"), (1, 1, "face mask"), (1, 2, "imv")]
    ) == [True, False, True]


def test_transitions_do_not_cross_an_encounter_block():
    """Block 2's first row must be judged against nothing, not against block 1's last."""
    assert _flags([(1, 0, "imv"), (2, 1, "imv")]) == [True, True]


def test_opens_block_is_recorded_separately_from_a_null_predecessor():
    """Both give prior_device_category = null, so the two cases are otherwise
    indistinguishable in the published table."""
    marked = mark_transitions(_waterfall([(1, 0, "imv"), (2, 0, None), (2, 1, "imv")]))
    assert marked.get_column("opens_block").to_list() == [True, True, False]
    assert marked.get_column("_prev_device").to_list() == [None, None, None]


def test_rows_are_ordered_within_the_block_before_shifting():
    """An unsorted input must not change the answer -- the shift is meaningless unless
    the frame is in time order within each block."""
    shuffled = _waterfall([(1, 2, "imv"), (1, 0, "nasal cannula"), (1, 1, "nasal cannula")])
    marked = mark_transitions(shuffled).sort(["encounter_block", "recorded_dttm"])
    assert marked.get_column("is_transition").to_list() == [False, False, True]


# ------------------------------------------------------- the shared +/- window


@pytest.mark.parametrize(
    ("offset", "inside"),
    [(-61, False), (-60, True), (-0.5, True), (0, True), (59.9, True), (60, True), (60.1, False)],
)
def test_window_is_inclusive_at_both_ends(offset, inside):
    """Sub-analyses D and E share this one predicate (P15). Two implementations of an
    interval test drift at the boundary, and a one-row disagreement between 'IMV was
    near' and 'sedation was near' is invisible in aggregate and fatal to the joint
    reading."""
    got = (
        pl.DataFrame({"offset_minutes": [float(offset)]})
        .select(in_window_expr("offset_minutes", 60.0).alias("x"))
        .get_column("x")
        .to_list()
    )
    assert got == [inside]


def test_window_rejects_a_null_offset():
    """A null offset means no candidate row was found at all and must not pass."""
    got = (
        pl.DataFrame({"offset_minutes": [None]}, schema={"offset_minutes": pl.Float64})
        .select(in_window_expr("offset_minutes", 60.0).alias("x"))
        .get_column("x")
        .to_list()
    )
    assert got == [False]
