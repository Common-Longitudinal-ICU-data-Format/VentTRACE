"""Pins the ECDF extract (spec P41, 2026-08-15).

`ecdf_by_group` is defined once in each of `02_index_paralytic.py` and
`03_context.py` -- a deliberate duplicate, not a shared import (spec §4, P23):
duplicated analysis logic risks visible divergence between the two notebooks,
while a shared bug in a `utils/` helper would corrupt both identically and
invisibly. This file extracts the function from BOTH notebooks and runs the
identical suite against each, so a future edit that quietly diverges the two
copies fails here first.

The function is lifted out of the notebooks by AST rather than imported:
neither `02_index_paralytic` nor `03_context` is an importable module name, and
importing either would run the pipeline against real PHI.

Run:  uv run pytest tests/test_dose_ecdf.py -v
"""

import ast
from pathlib import Path

import polars as pl
import pytest

NOTEBOOKS = {
    "02_index_paralytic": Path(__file__).parent.parent / "code" / "02_index_paralytic.py",
    "03_context": Path(__file__).parent.parent / "code" / "03_context.py",
}

FUNC_NAME = "ecdf_by_group"

OUT_COLUMNS = [
    "med_category",
    "med_dose_unit",
    "dose",
    "n_at_dose",
    "n_cum",
    "n_total",
    "ecdf",
]


def _load_from_notebook(path, name, namespace=None):
    """Compile a single named function out of a marimo notebook, exactly as
    tests/test_dose_conversion.py and tests/test_pair_gaps.py do it."""
    tree = ast.parse(path.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, f"expected exactly one def {name} in {path.name}, found {len(found)}"
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(namespace or {})
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


ECDFS = {
    label: _load_from_notebook(path, FUNC_NAME, {"pl": pl})
    for label, path in NOTEBOOKS.items()
}

LABELS = sorted(ECDFS)


def _frame(rows):
    """Build an input frame from (med_category, med_dose_unit, med_dose) triples."""
    return pl.DataFrame(
        {
            "med_category": [r[0] for r in rows],
            "med_dose_unit": [r[1] for r in rows],
            "med_dose": [r[2] for r in rows],
        },
        schema={
            "med_category": pl.Utf8,
            "med_dose_unit": pl.Utf8,
            "med_dose": pl.Float64,
        },
    )


@pytest.mark.parametrize("label", LABELS)
def test_both_notebooks_define_the_function(label):
    """Guards the guard: if extraction silently returned nothing, every test below
    would vacuously pass against a missing function."""
    assert callable(ECDFS[label])


@pytest.mark.parametrize("label", LABELS)
def test_output_carries_exactly_the_published_columns(label):
    out = ECDFS[label](_frame([("rocuronium", "mg", 50.0)]))
    assert out.columns == OUT_COLUMNS


@pytest.mark.parametrize("label", LABELS)
def test_ecdf_reaches_one(label):
    out = ECDFS[label](
        _frame([("rocuronium", "mg", d) for d in (10.0, 20.0, 30.0, 40.0)])
    )
    last = out.row(-1, named=True)
    assert last["ecdf"] == 1.0
    assert last["n_cum"] == last["n_total"] == 4


@pytest.mark.parametrize("label", LABELS)
def test_n_cum_is_monotone(label):
    out = ECDFS[label](
        _frame([("rocuronium", "mg", d) for d in (30.0, 10.0, 20.0, 20.0, 40.0)])
    )
    cum = out.get_column("n_cum").to_list()
    assert cum == sorted(cum)
    assert all(b >= a for a, b in zip(cum, cum[1:]))


@pytest.mark.parametrize("label", LABELS)
def test_counts_sum_to_total(label):
    out = ECDFS[label](
        _frame(
            [("rocuronium", "mg", 10.0)] * 3
            + [("rocuronium", "mg", 20.0)] * 2
            + [("vecuronium", "mg", 5.0)] * 7
        )
    )
    for (cat, unit), group in out.group_by(["med_category", "med_dose_unit"]):
        assert group.get_column("n_at_dose").sum() == group.get_column("n_total")[0], (
            f"{cat}/{unit} counts do not sum to n_total"
        )


@pytest.mark.parametrize("label", LABELS)
def test_ties_collapse_to_one_row(label):
    """Ten administrations at one dose are ONE row carrying 10, not ten rows.
    A row-per-administration output would be row-level data, which publish()
    exists to keep out of final_no_phi/."""
    out = ECDFS[label](_frame([("rocuronium", "mg", 50.0)] * 10))
    assert out.height == 1
    assert out.row(0, named=True)["n_at_dose"] == 10
    assert out.row(0, named=True)["ecdf"] == 1.0


@pytest.mark.parametrize("label", LABELS)
def test_groups_do_not_bleed(label):
    """The same dose value in two units must not share a cumulative count.
    This is the ketamine mcg/mg case the raw-unit keying exists for (P41)."""
    out = ECDFS[label](
        _frame(
            [("ketamine", "mg", 10.0)] * 2
            + [("ketamine", "mcg", 10.0)] * 3
            + [("ketamine", "mcg", 20.0)] * 1
        )
    )
    mg = out.filter(pl.col("med_dose_unit") == "mg")
    mcg = out.filter(pl.col("med_dose_unit") == "mcg")
    assert mg.get_column("n_total").to_list() == [2]
    assert mcg.get_column("n_total").to_list() == [4, 4]
    assert mg.row(0, named=True)["n_cum"] == 2
    assert mcg.get_column("n_cum").to_list() == [3, 4]


@pytest.mark.parametrize("label", LABELS)
def test_sort_is_total_and_stable(label):
    """The key triple is unique, so the published sort needs no tie-break
    column to be byte-identical across runs (commit 6c70808)."""
    rows = [
        ("vecuronium", "mg", 10.0),
        ("rocuronium", "mcg", 48.0),
        ("rocuronium", "mg", 50.0),
        ("rocuronium", "mcg", 0.6),
        ("rocuronium", "mg", 10.0),
    ]
    out = ECDFS[label](_frame(rows))
    keys = out.select("med_category", "med_dose_unit", "dose").rows()
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    # Same data, different input order -> identical output.
    shuffled = ECDFS[label](_frame(list(reversed(rows))))
    assert out.equals(shuffled)


@pytest.mark.parametrize("label", LABELS)
def test_null_dose_rows_are_dropped_not_ranked(label):
    """A null dose has no position in a cumulative distribution. Sorting it to
    either end would place it at the 0th or 100th percentile of a distribution
    it is not part of, so it is excluded -- and excluded from n_total too."""
    out = ECDFS[label](
        _frame(
            [
                ("rocuronium", "mg", 10.0),
                ("rocuronium", "mg", None),
                ("rocuronium", "mg", 20.0),
                ("rocuronium", None, 30.0),
            ]
        )
    )
    assert out.height == 2
    assert out.get_column("n_total").to_list() == [2, 2]
    assert out.get_column("dose").to_list() == [10.0, 20.0]
    assert out.get_column("ecdf").to_list() == [0.5, 1.0]


@pytest.mark.parametrize("label", LABELS)
def test_empty_input_yields_empty_frame_with_schema(label):
    """A site with no qualifying administration publishes a header-only CSV,
    not a crash and not a missing file."""
    out = ECDFS[label](_frame([]))
    assert out.height == 0
    assert out.columns == OUT_COLUMNS


@pytest.mark.parametrize("label", LABELS)
def test_ecdf_is_recoverable_from_the_two_integers(label):
    """n_cum and n_total are authoritative; ecdf is a rounded convenience column.
    Tolerance rather than equality against Python's round(): polars rounds half
    away from zero and Python rounds half to even, and the contract is the
    6-dp value, not agreement between two rounding conventions."""
    out = ECDFS[label](
        _frame([("rocuronium", "mg", float(d)) for d in range(1, 8)])
    )
    for row in out.iter_rows(named=True):
        assert abs(row["ecdf"] - row["n_cum"] / row["n_total"]) <= 5e-7
