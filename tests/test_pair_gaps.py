"""Pins the all-pairs enumeration and the gap bin grid of `02_index_paralytic.py`.

Sub-analysis A is the evidence for the 15-minute boundary (spec P7), so it is
published BEFORE the fold applies that boundary and depends on nothing the fold
computes. Two things can go wrong and neither announces itself:

  * the enumeration silently crossing an encounter_block boundary, which would
    manufacture gaps between different patients' drugs;
  * a bin edge landing on the wrong side, which moves mass across the very line
    the threshold is drawn at.

Both are checked below. The functions are lifted out of the marimo notebook by
AST, the way `tests/test_collapse_agent_events.py` does it: `02_index_paralytic`
is not an importable module name and importing it would run the pipeline against
real PHI.

Run:  uv run pytest tests/test_pair_gaps.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl
import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "02_index_paralytic.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())

GAP_CUT_BREAKS = [1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 4320, 10080]
GAP_CUT_LABELS = [
    "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]", "(15,30]", "(30,60]",
    "(1,2]h", "(2,6]h", "(6,12]h", "(12,24]h", "(1,3]d", "(3,7]d", ">7d",
]


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


_NS = {
    "pl": pl,
    "GAP_CUT_BREAKS": GAP_CUT_BREAKS,
    "GAP_CUT_LABELS": GAP_CUT_LABELS,
}
gap_bin_expr = _load_from_notebook("gap_bin_expr", _NS)
epoch_minutes = _load_from_notebook("epoch_minutes", {"pl": pl})
all_pair_gaps = _load_from_notebook("all_pair_gaps", {"pl": pl, "epoch_minutes": epoch_minutes})

BASE = datetime.datetime(2024, 3, 1, 12, 0)


def _admins(spec):
    """spec: list of (encounter_block, minutes_after_BASE, med_category)."""
    return pl.DataFrame(
        {
            "encounter_block": [b for b, _, _ in spec],
            "admin_dttm": [BASE + datetime.timedelta(minutes=m) for _, m, _ in spec],
            "med_category": [c for _, _, c in spec],
        }
    )


def _bins(values):
    return (
        pl.DataFrame({"gap_minutes": [float(v) for v in values]})
        .with_columns(gap_bin_expr())
        .get_column("gap_bin")
        .to_list()
    )


# ------------------------------------------------------------------ the bin grid


def test_exact_zero_gets_its_own_bin():
    """Two agents charted on the same minute is the most informative value in the
    distribution and must not be pooled with 'under a minute'."""
    assert _bins([0]) == ["0"]
    assert _bins([0.0001]) == ["(0,1]"]


@pytest.mark.parametrize(
    ("gap", "label"),
    [
        (1, "(0,1]"),
        (1.0001, "(1,2]"),
        (15, "(10,15]"),
        (15.0001, "(15,30]"),
        (60, "(30,60]"),
        (60.0001, "(1,2]h"),
        (1440, "(12,24]h"),
        (4320, "(1,3]d"),
        (10080, "(3,7]d"),
        (10080.0001, ">7d"),
        (100000, ">7d"),
    ],
)
def test_bin_edges_are_left_open_right_closed(gap, label):
    """Every interval is (a, b]. The 15-minute edge matters most: it is the line the
    fold is drawn at, and a value landing on the wrong side of it would make Figure A.1
    disagree with the boundary it is evidence for."""
    assert _bins([gap]) == [label]


def test_the_seven_day_cap_is_a_bin_not_a_filter():
    """A filter would make the histogram's own denominator depend on the cap, so two
    sites with different long-stay mixes would not be comparable even on the short bins
    (P10)."""
    labels = _bins([5, 20000, 30000])
    assert labels.count(">7d") == 2
    assert None not in labels


def test_every_gap_lands_in_exactly_one_named_bin():
    values = [0, 0.5, 1, 3, 7, 12, 15, 22, 45, 90, 200, 500, 1000, 2000, 5000, 10080, 99999]
    labels = _bins(values)
    assert None not in labels
    assert set(labels) <= set(["0"] + GAP_CUT_LABELS)


# --------------------------------------------------------- the pair enumeration


def test_n_administrations_yield_n_choose_2_pairs():
    pairs = all_pair_gaps(_admins([(1, 0, "rocuronium")] + [(1, m, "vecuronium") for m in (2, 40, 100)]))
    assert pairs.height == 6  # 4 choose 2


def test_pairs_never_cross_an_encounter_block():
    """The bridge drops hospitalization_id precisely so gaps are computed per block; a
    leak across blocks would manufacture a gap between two different patients' drugs."""
    pairs = all_pair_gaps(
        _admins([(1, 0, "rocuronium"), (1, 5, "rocuronium"), (2, 7, "rocuronium")])
    )
    assert pairs.height == 1
    assert pairs.get_column("encounter_block").to_list() == [1]


def test_same_agent_pairs_are_included_and_flagged():
    """roc->roc at 3 min is a redose and roc->sux at 3 min is a co-administration. Both
    are counted (P9) and the split is what tells them apart."""
    pairs = all_pair_gaps(
        _admins([(1, 0, "rocuronium"), (1, 3, "rocuronium"), (1, 6, "succinylcholine")])
    ).sort("gap_minutes")
    assert pairs.get_column("is_same_agent").to_list() == [True, False, False]


def test_agent_pair_label_is_alphabetical():
    """One pair is one row, never two orderings of itself."""
    pairs = all_pair_gaps(_admins([(1, 0, "vecuronium"), (1, 4, "rocuronium")]))
    assert pairs.get_column("agent_pair").to_list() == ["rocuronium+vecuronium"]


def test_same_agent_pair_label_repeats_the_agent():
    pairs = all_pair_gaps(_admins([(1, 0, "rocuronium"), (1, 4, "rocuronium")]))
    assert pairs.get_column("agent_pair").to_list() == ["rocuronium+rocuronium"]


def test_gap_is_absolute_and_order_independent():
    pairs = all_pair_gaps(_admins([(1, 40, "rocuronium"), (1, 0, "vecuronium")]))
    assert pairs.get_column("gap_minutes").to_list() == [40.0]


def test_a_single_administration_yields_no_pairs():
    assert all_pair_gaps(_admins([(1, 0, "rocuronium")])).height == 0


def test_empty_input_yields_an_empty_frame_not_an_error():
    empty = _admins([]).cast({"encounter_block": pl.Int64})
    assert all_pair_gaps(empty).height == 0
