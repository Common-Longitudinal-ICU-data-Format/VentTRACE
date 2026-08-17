"""Pins the polars -> pandas -> polars dose-unit-conversion boundary (spec P18,
amended 2026-08-10).

`convert_doses_to_preferred_units` is defined once in each of `02_index_paralytic.py`
and `03_context.py` -- a deliberate duplicate, not a shared import (spec §4, P23):
duplicated analysis logic risks visible divergence between the two notebooks, while a
shared bug in a `utils/` helper would corrupt both identically and invisibly. This
file extracts the function from BOTH notebooks and runs the identical test suite
against each, so a future edit that quietly diverges the two copies fails here first.

`clifpy.utils.unit_converter.convert_dose_units_by_med_category` takes pandas; this
pipeline is polars everywhere else. The function under test is the whole boundary
crossing, including P42's calculation-only unit overrides and the exclusion of rows
without a usable dose. An integer row key plus the four columns the converter needs
(`med_category`, `med_dose`, calculation `med_dose_unit`, an all-null `weight_kg`)
go through pandas, and the result is joined back on the key -- never a datetime column.

The function is lifted out of the notebooks by AST rather than imported: neither
`02_index_paralytic` nor `03_context` is an importable module name, and importing
either would run the pipeline against real PHI.

Run:  uv run pytest tests/test_dose_conversion.py -v
"""

import ast
from functools import partial
from pathlib import Path

import polars as pl
import pytest

from clifpy.utils.unit_converter import convert_dose_units_by_med_category

NOTEBOOKS = {
    "02_index_paralytic": Path(__file__).parent.parent / "code" / "02_index_paralytic.py",
    "03_context": Path(__file__).parent.parent / "code" / "03_context.py",
}

FUNC_NAME = "convert_doses_to_preferred_units"
RATE_FUNC_NAME = "rate_unit_expr"


def _load_from_notebook(path, name, namespace=None):
    """Compile a single named function out of a marimo notebook, exactly as
    tests/test_collapse_agent_events.py and tests/test_pair_gaps.py do it."""
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


def _load_literal_assignment(path, name):
    tree = ast.parse(path.read_text())
    found = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]
    assert len(found) == 1, f"expected exactly one assignment to {name} in {path.name}"
    return ast.literal_eval(found[0])


_NAMESPACE = {
    "pl": pl,
    "convert_dose_units_by_med_category": convert_dose_units_by_med_category,
}

_RAW_CONVERTERS = {
    label: _load_from_notebook(path, FUNC_NAME, _NAMESPACE) for label, path in NOTEBOOKS.items()
}
RATE_EXPRESSIONS = {
    label: _load_from_notebook(path, RATE_FUNC_NAME, {"pl": pl})
    for label, path in NOTEBOOKS.items()
}

# The spec's exact constant (brief, P18): mg for everything except fentanyl.
PREFERRED_UNITS = {
    "rocuronium": "mg",
    "succinylcholine": "mg",
    "vecuronium": "mg",
    "midazolam": "mg",
    "etomidate": "mg",
    "ketamine": "mg",
    "propofol": "mg",
    "fentanyl": "mcg",
}

UNIT_OVERRIDES = {
    ("rocuronium", "mg/kg"): "mg",
    ("succinylcholine", "mg/kg"): "mg",
}

CONVERTERS = {
    label: partial(convert, unit_overrides=UNIT_OVERRIDES)
    for label, convert in _RAW_CONVERTERS.items()
}

LABELS = sorted(CONVERTERS)


@pytest.mark.parametrize("label", LABELS)
def test_both_notebooks_define_the_function(label):
    """Guards the guard: if extraction silently returned nothing, every test below
    would vacuously pass against a missing function."""
    assert callable(CONVERTERS[label])


@pytest.mark.parametrize("label", LABELS)
def test_both_notebooks_define_the_same_global_unit_overrides(label):
    assert _load_literal_assignment(NOTEBOOKS[label], "DOSE_UNIT_OVERRIDES") == UNIT_OVERRIDES


@pytest.mark.parametrize("label", LABELS)
def test_rate_units_are_identified_before_medication_analysis(label):
    df = pl.DataFrame(
        {
            "med_dose_unit": [
                "mcg/hr",
                "mg/kg/min",
                "ml/hour",
                "mcg per minute",
                "mg/day",
                "mg",
                "mcg",
                None,
            ]
        }
    ).with_columns(is_rate=RATE_EXPRESSIONS[label]("med_dose_unit"))

    assert df.get_column("is_rate").to_list() == [
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
    ]


@pytest.mark.parametrize("label", LABELS)
def test_mixed_units_convert_to_the_preferred_unit_with_correct_arithmetic(label):
    """A frame mixing mg and mcg for one category converts to the preferred unit;
    1 mg = 1,000 mcg is the arithmetic this pins."""
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["ketamine", "ketamine"],
            "med_dose": [50.0, 30_000.0],  # 50 mg, and 30,000 mcg == 30 mg
            "med_dose_unit": ["mg", "mcg"],
        }
    )
    out = convert(df, PREFERRED_UNITS)

    assert out.height == 2
    assert set(out.get_column("med_dose_unit_converted").to_list()) == {"mg"}
    assert set(out.get_column("_unit_class").to_list()) == {"amount"}
    assert set(out.get_column("_convert_status").to_list()) == {"success"}
    assert sorted(out.get_column("med_dose_converted").to_list()) == pytest.approx(
        [30.0, 50.0]
    )


@pytest.mark.parametrize("label", LABELS)
def test_an_unapproved_kg_unit_raises_before_the_converter_ever_runs(label):
    """P42 is an exact two-category exception, not permission to discard /kg
    from genuinely weight-based dosing."""
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["propofol"],
            "med_dose": [50.0],
            "med_dose_unit": ["mcg/kg/min"],
        }
    )
    with pytest.raises(AssertionError, match="weight-based dosing"):
        convert(df, PREFERRED_UNITS)


@pytest.mark.parametrize("label", LABELS)
def test_a_kg_unit_is_detected_case_insensitively(label):
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["propofol"],
            "med_dose": [50.0],
            "med_dose_unit": ["MCG/KG/MIN"],
        }
    )
    with pytest.raises(AssertionError, match="weight-based dosing"):
        convert(df, PREFERRED_UNITS)


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("med_category", ["rocuronium", "succinylcholine"])
def test_approved_mg_per_kg_is_assumed_to_be_absolute_mg(label, med_category):
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": [med_category],
            "med_dose": [50.0],
            "med_dose_unit": ["mg/kg"],
        }
    )
    out = convert(df, PREFERRED_UNITS)

    assert out.get_column("med_dose").to_list() == [50.0]
    assert out.get_column("med_dose_unit").to_list() == ["mg/kg"]
    assert out.get_column("med_dose_converted").to_list() == [50.0]
    assert out.get_column("med_dose_unit_converted").to_list() == ["mg"]
    assert out.get_column("_convert_status").to_list() == ["success"]


@pytest.mark.parametrize("label", LABELS)
def test_override_matching_is_case_insensitive(label):
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["ROCURONIUM"],
            "med_dose": [50.0],
            "med_dose_unit": ["MG/KG"],
        }
    )
    out = convert(df, {**PREFERRED_UNITS, "ROCURONIUM": "mg"})

    assert out.get_column("med_dose_unit").to_list() == ["MG/KG"]
    assert out.get_column("med_dose_converted").to_list() == [50.0]
    assert out.get_column("med_dose_unit_converted").to_list() == ["mg"]


@pytest.mark.parametrize("label", LABELS)
def test_rows_without_a_usable_dose_are_excluded(label):
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["rocuronium"] * 4,
            "med_dose": [50.0, None, float("nan"), 40.0],
            "med_dose_unit": ["mg", None, "mg", None],
        }
    )
    out = convert(df, PREFERRED_UNITS)

    assert out.height == 1
    assert out.get_column("med_dose").to_list() == [50.0]


@pytest.mark.parametrize("label", LABELS)
def test_an_unrecognized_unit_raises_rather_than_being_silently_dropped(label):
    """A converter that dropped an unrecognised unit would shrink the denominator
    without anything raising. This must never be filtered out."""
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["propofol"],
            "med_dose": [1.0],
            "med_dose_unit": ["puffs"],
        }
    )
    with pytest.raises(AssertionError, match="failed unit conversion"):
        convert(df, PREFERRED_UNITS)


@pytest.mark.parametrize("label", LABELS)
def test_row_count_is_preserved(label):
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["fentanyl", "fentanyl", "midazolam"],
            "med_dose": [50.0, 100.0, 2.0],
            "med_dose_unit": ["mcg", "mcg", "mg"],
        }
    )
    out = convert(df, PREFERRED_UNITS)
    assert out.height == df.height


@pytest.mark.parametrize("label", LABELS)
def test_the_row_key_round_trips_so_duplicate_rows_cannot_fan_out(label):
    """Three rows sharing an identical (med_category, med_dose, med_dose_unit) triple
    must come back as three rows, unchanged and unshuffled. A join performed on those
    natural columns instead of the row key would either fan the duplicates out
    (a join on non-unique columns multiplies) or silently collapse them -- either is a
    denominator bug this test is built to catch."""
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["rocuronium", "rocuronium", "rocuronium"],
            "med_dose": [50.0, 50.0, 50.0],
            "med_dose_unit": ["mg", "mg", "mg"],
        }
    )
    out = convert(df, PREFERRED_UNITS)

    assert out.height == 3
    assert out.get_column("med_dose_converted").to_list() == [50.0, 50.0, 50.0]


@pytest.mark.parametrize("label", LABELS)
def test_n_in_preferred_unit_counts_rows_already_in_the_preferred_unit(label):
    """Pins the derivation both notebooks use for the `n_in_preferred_unit` column in
    index_paralytic_dose.csv / sedation_dose.csv: a row-wise comparison of the RAW
    `med_dose_unit` against `med_dose_unit_converted`, summed per med_category.

    Ketamine at this site is the motivating case: 8 of 13 administrations were
    charted in mcg and only 5 already in the preferred mg, so the published median
    pools two unit populations rather than one. This frame mirrors that shape (2 raw
    mg, 3 raw mcg, all converting to mg) and pins that the column reads 2, not 5 and
    not 0 -- a reader must be able to see the split without opening the companion
    counts-only table.
    """
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["ketamine"] * 5,
            "med_dose": [50.0, 60.0, 30.0, 31.0, 40.0],
            "med_dose_unit": ["mg", "mg", "mcg", "mcg", "mcg"],
        }
    )
    out = convert(df, PREFERRED_UNITS)

    n_in_preferred_unit = (
        out.filter(pl.col("med_dose_unit") == pl.col("med_dose_unit_converted")).height
    )
    assert n_in_preferred_unit == 2
    assert out.height == 5  # n vs n_in_preferred_unit is the "5 of which 2" signal


@pytest.mark.parametrize("label", LABELS)
def test_n_in_preferred_unit_equals_n_when_every_row_is_already_the_preferred_unit(label):
    """The agents unaffected by the contamination (rocuronium, propofol at this site):
    n_in_preferred_unit must equal n exactly, not merely be close to it."""
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["rocuronium", "rocuronium", "rocuronium"],
            "med_dose": [50.0, 50.0, 100.0],
            "med_dose_unit": ["mg", "mg", "mg"],
        }
    )
    out = convert(df, PREFERRED_UNITS)
    n_in_preferred_unit = (
        out.filter(pl.col("med_dose_unit") == pl.col("med_dose_unit_converted")).height
    )
    assert n_in_preferred_unit == out.height == 3


@pytest.mark.parametrize("label", LABELS)
def test_row_order_and_original_columns_are_preserved(label):
    """The returned frame lines back up with the input row for row -- necessary for
    every downstream group_by to attribute the right converted dose to the right
    original administration."""
    convert = CONVERTERS[label]
    df = pl.DataFrame(
        {
            "med_category": ["vecuronium", "rocuronium", "succinylcholine"],
            "med_dose": [10.0, 50.0, 100.0],
            "med_dose_unit": ["mg", "mg", "mg"],
            "offset_minutes": [-5.0, 0.0, 12.0],
        }
    )
    out = convert(df, PREFERRED_UNITS)

    assert out.get_column("med_category").to_list() == df.get_column("med_category").to_list()
    assert out.get_column("med_dose").to_list() == df.get_column("med_dose").to_list()
    assert out.get_column("offset_minutes").to_list() == df.get_column(
        "offset_minutes"
    ).to_list()
    assert out.get_column("med_dose_converted").to_list() == df.get_column(
        "med_dose"
    ).to_list()  # already all mg -> preferred unit is mg -> unchanged
