"""Pins `close_per_agent_dose_leak` in `code/03_context.py` (spec P24, fourth instance).

THE DEFECT THIS EXISTS TO PREVENT. `sedation_offset_distribution.csv` and
`sedation_dose.csv` are partitions of one another PER AGENT -- both count the same
(index paralytic, administration) pairs, one split by offset bin, the other by
charted unit. The grand total is published nowhere, which is what made the first
implementation believe neither was recoverable. But the *per-agent* total is
published, by the offset file itself, whenever that agent has zero withheld bins:
its 24 published bins then sum to its true total. Measured at the first site:

    propofol   0 of 24 bins withheld  ->  bin sum 1,433 = its true total
               sedation_dose.csv publishes  propofol / mg / 1,427
               1,433 - 1,427 = 6   <-- the withheld propofol/mcg cell, exactly

Midazolam and ketamine escaped only because they happened to have withheld bins.
Accident is not a control, hence a rule and hence these tests.

THE RULE. An agent is exposed when it has at least one dose row the n>=10 rule
will withhold AND zero offset bins that rule will withhold. For an exposed agent,
one further offset bin is withheld -- the smallest whose count is at least
2*MIN_CELL-2 = 18 -- so the reader's residual no longer pins the withheld dose
cell. If no bin reaches 18, that agent's ENTIRE offset distribution is withheld,
which is how `withhold_second_row` resolves its own degenerate case.

WHY THE THRESHOLD IS 18 AND NOT 10, restated so a future edit cannot "simplify"
it away: the reader solves v = c + w with c known and w the count of the one
missing bin. Candidates are w in [1-c, 9-c]; every value of v in 1..9 stays
feasible only if no candidate w can be ruled out, and a candidate below MIN_CELL
could have been ruled out ("that bin would have been suppressed anyway"). So the
whole candidate range must sit at or above MIN_CELL, giving w >= v + 9 and, worst
case v = 9, w >= 18. Picking the smallest surviving bin instead would pick w = 10,
which pins v uniquely and destroys a bar for nothing.

Run:  uv run pytest tests/test_per_agent_dose_leak.py -v
"""

import ast
from pathlib import Path

import polars as pl
import pytest

from utils.suppress import MIN_CELL, publish, small_cell_mask

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


close_per_agent_dose_leak = _load_from_notebook(
    "close_per_agent_dose_leak",
    {"pl": pl, "MIN_CELL": MIN_CELL, "small_cell_mask": small_cell_mask},
)

COUNT = "n_admin_windows"
AGENT = "med_category"
MIN_BIN = 2 * MIN_CELL - 2  # 18


def _offsets(**per_agent):
    """`agent=[counts...]` -> a bin frame, one row per (agent, bin)."""
    rows = []
    for agent, counts in per_agent.items():
        for order, n in enumerate(counts):
            rows.append({"bin_order": order, AGENT: agent, COUNT: n})
    return pl.DataFrame(
        rows, schema={"bin_order": pl.Int32, AGENT: pl.String, COUNT: pl.Int64}
    )


def _dose(*rows):
    """`(agent, unit, n)` triples -> a dose frame."""
    return pl.DataFrame(
        [{AGENT: a, "med_dose_unit": u, COUNT: n} for a, u, n in rows],
        schema={AGENT: pl.String, "med_dose_unit": pl.String, COUNT: pl.Int64},
    )


def _run(offsets, dose):
    return close_per_agent_dose_leak(offsets, dose, AGENT, COUNT, "t")


def _released(frame):
    """What a reader actually receives: the rule's output, then the n>=10 rule."""
    return frame.filter(~small_cell_mask(frame, [COUNT]))


# --------------------------------------------------------------------------
# The four cases the rule is specified over
# --------------------------------------------------------------------------


def test_fires_when_dose_row_withheld_and_no_bin_withheld():
    """The propofol case: exposed, so one bin goes."""
    offsets = _offsets(propofol=[40, 21, 100, 0, 19])
    dose = _dose(("propofol", "mg", 174), ("propofol", "mcg", 6))

    out = _run(offsets, dose)

    assert out.height == offsets.height - 1, "exactly one bin should have been withheld"
    gone = set(offsets.rows()) - set(out.rows())
    assert len(gone) == 1
    (_, _, withheld_count), = gone
    assert withheld_count >= MIN_BIN, "the victim must clear the 18 threshold"


def test_victim_is_the_smallest_bin_clearing_the_threshold():
    """Not the largest, and emphatically not the smallest overall.

    The smallest overall would be a bin at 10, which pins v uniquely. The largest
    would cost the reader more than necessary. Smallest-above-18 is the rule.
    """
    offsets = _offsets(propofol=[10, 40, 19, 500, 18, 12])
    dose = _dose(("propofol", "mg", 594), ("propofol", "mcg", 5))

    out = _run(offsets, dose)
    gone = set(offsets.rows()) - set(out.rows())
    (_, _, withheld_count), = gone
    assert withheld_count == 18, (
        "expected the smallest bin at or above 18, not the smallest bin overall "
        "and not the largest"
    )


def test_no_op_when_the_agent_already_has_a_withheld_bin():
    """A withheld bin means the published bin sum is NOT the agent's total.

    Nothing is recoverable, so nothing further may be taken -- withholding here
    would cost a reader a bar to protect a total that is already unknown.
    """
    offsets = _offsets(midazolam=[40, 7, 100, 30])  # the 7 is withheld by the n>=10 rule
    dose = _dose(("midazolam", "mg", 172), ("midazolam", "mcg", 5))

    out = _run(offsets, dose)
    assert out.equals(offsets), "no agent was exposed; the frame must come back untouched"


def test_no_op_when_no_dose_row_is_withheld():
    """The fentanyl case: every bin published, but nothing to recover.

    The bin sum IS the agent's true total here, and that is fine -- publishing a
    total is only a leak when something is being reconstructed from it.
    """
    offsets = _offsets(fentanyl=[40, 21, 100, 30])
    dose = _dose(("fentanyl", "mcg", 191))

    out = _run(offsets, dose)
    assert out.equals(offsets)


def test_degenerate_case_withholds_that_agents_whole_distribution():
    """No bin reaches 18, so no single withholding keeps 1..9 feasible.

    Resolved as `withhold_second_row` resolves its own degenerate case -- withhold
    the whole unit. The unit here is the AGENT, because the leak is computed per
    agent, so the other agents' histograms survive.
    """
    offsets = _offsets(ketamine=[10, 12, 0, 17], propofol=[40, 21, 100])
    dose = _dose(("ketamine", "mg", 34), ("ketamine", "mcg", 5))

    out = _run(offsets, dose)

    assert out.filter(pl.col(AGENT) == "ketamine").height == 0, (
        "the exposed agent's entire distribution must be withheld when no bin "
        "reaches the threshold"
    )
    assert out.filter(pl.col(AGENT) == "propofol").height == 3, (
        "the blast radius is one agent, not the table"
    )


# --------------------------------------------------------------------------
# The properties the rule must have, not just the branches it must take
# --------------------------------------------------------------------------


def test_a_published_zero_is_never_the_victim():
    """Withholding a zero leaves the bin sum unchanged -- protection in appearance only."""
    offsets = _offsets(propofol=[0, 0, 40, 0, 25])
    dose = _dose(("propofol", "mg", 60), ("propofol", "mcg", 5))

    out = _run(offsets, dose)
    gone = set(offsets.rows()) - set(out.rows())
    (_, _, withheld_count), = gone
    assert withheld_count != 0
    assert out.filter(pl.col(COUNT) == 0).height == 3, "every zero must survive"


def test_only_the_exposed_agent_loses_a_bin():
    offsets = _offsets(
        propofol=[40, 21, 100],
        fentanyl=[40, 21, 100],
        midazolam=[40, 7, 100],
    )
    dose = _dose(
        ("propofol", "mg", 156), ("propofol", "mcg", 5),
        ("fentanyl", "mcg", 161),
        ("midazolam", "mg", 142), ("midazolam", "mcg", 5),
    )

    out = _run(offsets, dose)
    per_agent = dict(
        out.group_by(AGENT).agg(k=pl.len()).sort(AGENT).iter_rows()
    )
    assert per_agent == {"fentanyl": 3, "midazolam": 3, "propofol": 2}


@pytest.mark.parametrize("v", range(1, MIN_CELL))
def test_residual_leaves_every_withheld_value_feasible(v):
    """The property the whole rule exists for, checked as a reader would check it.

    True total T; a dose cell of `v` is withheld; the offsets lose one bin `w`.
    The reader computes c = published_bin_sum - published_dose_total and knows
    exactly one bin is missing, so v = c + w with w in [1-c, 9-c]. The rule holds
    when every candidate w is at or above MIN_CELL -- otherwise the reader
    eliminates the low candidates ("that bin would have been suppressed") and
    narrows v.
    """
    bins = [40, 21, 100, 0, 19]
    total = sum(bins)
    offsets = _offsets(propofol=bins)
    dose = _dose(("propofol", "mg", total - v), ("propofol", "mcg", v))

    released = _released(_run(offsets, dose))
    assert released.height == len(bins) - 1, "exactly one bin missing to the reader"

    c = released.get_column(COUNT).sum() - (total - v)
    lo, hi = 1 - c, (MIN_CELL - 1) - c
    assert lo <= hi
    assert lo >= MIN_CELL, (
        f"the reader can eliminate candidate bin counts below {MIN_CELL}, which "
        f"narrows the withheld cell: candidates were [{lo}, {hi}]"
    )
    assert lo <= total - (total - v) - c <= hi  # the true w is in the candidate set


def test_the_first_sites_actual_leak_is_closed_end_to_end():
    """The exact numbers from the run that found this, differenced as an attacker would."""
    bins = [
        23, 21, 25, 25, 34, 29, 36, 27, 45, 68, 85, 176,
        394, 92, 72, 64, 33, 33, 33, 26, 22, 23, 17, 30,
    ]
    assert sum(bins) == 1433
    offsets = _offsets(propofol=bins)
    dose = _dose(("propofol", "mg", 1427), ("propofol", "mcg", 6))

    before = _released(offsets)
    assert before.get_column(COUNT).sum() - 1427 == 6, (
        "the regression itself: without the rule the withheld cell differences out exactly"
    )

    after = _released(_run(offsets, dose))
    residual = after.get_column(COUNT).sum() - 1427
    assert not (1 <= residual <= MIN_CELL - 1), (
        f"the residual {residual} still lands in 1..{MIN_CELL - 1}"
    )
    assert after.height == 23, "one bin withheld, the other 23 published"


def test_publish_still_applies_the_row_level_rule_on_top(tmp_path):
    """The rule runs BEFORE `publish`; it never replaces the n>=10 rule."""
    offsets = _offsets(propofol=[40, 21, 100], midazolam=[40, 7, 100])
    dose = _dose(("propofol", "mg", 156), ("propofol", "mcg", 5))

    kept = publish(_run(offsets, dose), tmp_path / "o.csv", [COUNT], "t")
    assert kept.filter(pl.col(COUNT) == 7).height == 0, "the small cell must still go"
    assert kept.height == 4
