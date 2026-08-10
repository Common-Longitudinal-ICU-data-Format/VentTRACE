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

from utils.suppress import MIN_CELL, small_cell_mask

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
withhold_second_row = _load_from_notebook(
    "withhold_second_row",
    {"pl": pl, "small_cell_mask": small_cell_mask, "MIN_CELL": MIN_CELL},
)

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


# ------------------------------------- the partition guard, withhold_second_row
#
# Every table in 03 partitions a total the reader can already obtain, so a reader who
# sums the published rows and subtracts learns the RESIDUAL for free. The n>=10 rule
# alone does not close that: with exactly one row withheld, the residual IS that row.
#
# The guard withholds a second row, and WHICH second row is decided by arithmetic, not
# taste:
#
#     withheld cell  v,  1 <= v <= 9    (it was suppressed)
#     second row     w,  w >= 10        (it survived suppression)
#     reader sees    r = total - published = v + w
#     reader solves  v = r - w  s.t.  w >= 10   =>   v <= r - 10
#
# so v is ambiguous across the full 1..9 only when r >= 19, and since v can be 1 that
# needs w >= 18 == 2 * MIN_CELL - 2. Withholding the SMALLEST surviving row does the
# opposite: at w = 10, v = 1 the residual is 11, which pins v = 1 exactly and protects
# nothing at all. test_victim_makes_the_residual_fully_ambiguous is that regression.

MIN_SECOND = 2 * MIN_CELL - 2  # 18


def _counts(values):
    return pl.DataFrame({"label": [f"r{i}" for i in range(len(values))], "n": values})


def _residual(before, after):
    """What a reader computes: the public total minus what actually gets published.

    `before` is the unsuppressed table, whose total is public by assumption. `after` is
    what the guard hands to publish(), which then drops the small cells itself.
    """
    published = after.filter(~small_cell_mask(after, ["n"]))
    return before.get_column("n").sum() - published.get_column("n").sum()


def test_victim_makes_the_residual_fully_ambiguous():
    """THE regression. Several rows could be withheld second; the one chosen must leave a
    residual of at least 19, so the suppressed cell could be any value in 1..9."""
    before = _counts([5, 12, 20, 30])
    after = withhold_second_row(before, ["n"], "t")

    assert _residual(before, after) >= 2 * MIN_CELL - 1  # >= 19
    # 12 survives suppression but is below 18: withholding it would leave residual 17,
    # bounding v <= 7 rather than 9.
    assert after.get_column("n").to_list() == [5, 12, 30], "the victim must be 20, not 12"


def test_victim_is_the_smallest_row_that_clears_the_threshold():
    """Smallest-above-18, not simply largest: the threshold buys the guarantee, and among
    the rows clearing it the smallest is the one whose loss costs the reader least."""
    after = withhold_second_row(_counts([4, 18, 25, 90]), ["n"], "t")
    assert after.get_column("n").to_list() == [4, 25, 90]


def test_the_threshold_is_inclusive_at_18():
    """w = 18 with v = 1 gives r = 19, which is exactly enough. Off by one here silently
    reintroduces the leak for the tightest case."""
    assert withhold_second_row(_counts([1, 18, 40]), ["n"], "t").get_column("n").to_list() == [
        1,
        40,
    ]
    # 17 is one short -- choosing it would give r = 18, bounding v <= 8 -- so it is
    # skipped and the next row up is taken instead.
    assert withhold_second_row(_counts([1, 17, 40]), ["n"], "t").get_column("n").to_list() == [
        1,
        17,
    ]


def test_no_surviving_row_reaches_the_threshold_withholds_the_whole_table():
    """The degenerate case. No second row can make the residual ambiguous across 1..9, so
    publishing anything at all narrows the withheld cell. An empty table is the rule
    working -- and the schema survives so publish() still writes a header."""
    before = _counts([6, 11, 15])
    after = withhold_second_row(before, ["n"], "t")
    assert after.height == 0
    assert after.columns == before.columns
    assert after.schema == before.schema


def test_no_row_withheld_is_a_no_op():
    """Nothing was suppressed, so there is no residual to attribute and nothing to do."""
    before = _counts([10, 20, 30])
    assert withhold_second_row(before, ["n"], "t").equals(before)


def test_a_published_zero_does_not_count_as_a_withheld_row():
    """Zero is published, not suppressed, so a table of zeros and large cells is a no-op."""
    before = _counts([0, 0, 25])
    assert withhold_second_row(before, ["n"], "t").equals(before)


def test_two_rows_already_withheld_is_a_no_op():
    """The residual is already spread over two unknown cells and cannot be attributed to
    either one. Withholding a third would destroy a row for nothing."""
    before = _counts([3, 5, 20, 30])
    assert withhold_second_row(before, ["n"], "t").equals(before)


def test_a_published_zero_is_never_the_victim():
    """Withholding a zero leaves the residual unchanged: it would look like protection
    while leaving the withheld cell recoverable exactly as before."""
    before = _counts([4, 0, 0, 22])
    after = withhold_second_row(before, ["n"], "t")
    assert after.get_column("n").to_list() == [4, 0, 0]
    assert _residual(before, after) >= 2 * MIN_CELL - 1


def test_the_first_count_column_is_the_partitioning_one():
    """Every count column drives suppression, but only the first sums to the public total,
    so only the first can be recovered by subtraction and only it may choose the victim.
    Here row 0 is suppressed on its SECOND column while its first is large."""
    before = pl.DataFrame({"n": [50, 60, 40], "n_blocks": [5, 60, 40]})
    after = withhold_second_row(before, ["n", "n_blocks"], "t")
    assert after.get_column("n").to_list() == [50, 60], "the victim is chosen on n, not n_blocks"
