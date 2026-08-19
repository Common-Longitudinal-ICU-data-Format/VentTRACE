"""Configured medication-unit contract shared by steps 01-04."""

import ast
import json
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
DOSE_NOTEBOOKS = {
    label: ROOT / "code" / filename
    for label, filename in {
        "02_index_paralytic": "02_index_paralytic.py",
        "03_context": "03_context.py",
        "04_covariates": "04_covariates.py",
    }.items()
}
MEDICATION_NOTEBOOKS = {
    label: ROOT / "code" / filename
    for label, filename in {
        "01_cohort": "01_cohort.py",
        "02_index_paralytic": "02_index_paralytic.py",
        "03_context": "03_context.py",
    }.items()
}
EXPECTED_UNITS = {
    "rocuronium": "mg",
    "succinylcholine": "mg",
    "vecuronium": "mg",
    "midazolam": "mg",
    "etomidate": "mg",
    "ketamine": "mg",
    "propofol": "mg",
    "fentanyl": "mcg",
}
UPPER_BOUNDS = {
    "etomidate": 200.0,
    "fentanyl": 500.0,
    "ketamine": 100.0,
    "midazolam": 50.0,
    "propofol": 500.0,
    "rocuronium": 400.0,
    "succinylcholine": 400.0,
    "vecuronium": 30.0,
}


def _load_function(path, name):
    tree = ast.parse(path.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, f"expected one {name} in {path.name}"
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"pl": pl}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


PREPARERS = {
    label: _load_function(path, "prepare_configured_doses")
    for label, path in DOSE_NOTEBOOKS.items()
}
SUMMARY_FILTERS = {
    label: _load_function(path, "filter_doses_for_summary")
    for label, path in DOSE_NOTEBOOKS.items()
}
ELIGIBILITY_EXPRESSIONS = {
    label: _load_function(path, "medication_dose_eligible_expr")
    for label, path in MEDICATION_NOTEBOOKS.items()
}


def test_template_configures_every_study_medication():
    config = json.loads((ROOT / "config" / "config_template.json").read_text())
    assert config["medication_dose_units"] == EXPECTED_UNITS
    assert config["medication_dose_upper_bounds"] == UPPER_BOUNDS


@pytest.mark.parametrize("label,eligible_expr", ELIGIBILITY_EXPRESSIONS.items())
def test_medication_eligibility_uses_strict_configured_dose_bounds(
    label, eligible_expr
):
    frame = pl.DataFrame(
        {
            "row_id": list(range(9)),
            "med_category": [
                "ketamine", "ketamine", "fentanyl", "fentanyl", "rocuronium",
                "rocuronium", "rocuronium", "rocuronium", "rocuronium",
            ],
            "med_dose": [99.0, 100.0, 499.0, 500.0, 399.0, 400.0, 0.0, None, 500.0],
            "med_dose_unit": [
                "mg", "mg", "mcg", "mcg", "mg", "mg", "mg", "mg", "mg/kg",
            ],
        }
    )
    out = frame.filter(eligible_expr(EXPECTED_UNITS, UPPER_BOUNDS))
    assert out["row_id"].to_list() == [0, 2, 4], label


@pytest.mark.parametrize("label,eligible_expr", ELIGIBILITY_EXPRESSIONS.items())
def test_configured_per_kg_eligibility_bypasses_absolute_bound(label, eligible_expr):
    units = {**EXPECTED_UNITS, "rocuronium": "mg/kg"}
    frame = pl.DataFrame(
        {
            "row_id": [0, 1, 2],
            "med_category": ["rocuronium"] * 3,
            "med_dose": [500.0, 0.0, 399.0],
            "med_dose_unit": ["mg/kg", "mg/kg", "mg"],
        }
    )
    out = frame.filter(eligible_expr(units, UPPER_BOUNDS))
    assert out["row_id"].to_list() == [0], label


@pytest.mark.parametrize("label,path", MEDICATION_NOTEBOOKS.items())
def test_medication_event_paths_accept_given_only(label, path):
    tree = ast.parse(path.read_text())
    assignments = [
        ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "MAR_ACTIONS" for target in node.targets)
    ]
    assert assignments == [["given"]], label


@pytest.mark.parametrize("label,prepare", PREPARERS.items())
def test_configured_doses_are_not_converted_or_relabelled(label, prepare):
    frame = pl.DataFrame(
        {
            "med_category": ["rocuronium", "fentanyl"],
            "med_dose": [50.0, 25.0],
            "med_dose_unit": ["mg", "mcg"],
        }
    )
    out = prepare(frame, EXPECTED_UNITS)
    assert out["med_dose_converted"].to_list() == [50.0, 25.0]
    assert out["med_dose_unit_converted"].to_list() == ["mg", "mcg"]
    assert out["_convert_status"].to_list() == ["configured_unit"] * 2


@pytest.mark.parametrize("label,prepare", PREPARERS.items())
def test_per_kg_configured_dose_is_preserved(label, prepare):
    units = {**EXPECTED_UNITS, "rocuronium": "mg/kg"}
    frame = pl.DataFrame(
        {
            "med_category": ["rocuronium"],
            "med_dose": [1.2],
            "med_dose_unit": ["mg/kg"],
        }
    )
    out = prepare(frame, units)
    assert out["med_dose_converted"].to_list() == [1.2]
    assert out["med_dose_unit_converted"].to_list() == ["mg/kg"]


@pytest.mark.parametrize("label,prepare", PREPARERS.items())
def test_nonconfigured_unit_is_rejected(label, prepare):
    frame = pl.DataFrame(
        {
            "med_category": ["rocuronium"],
            "med_dose": [1.2],
            "med_dose_unit": ["mg/kg"],
        }
    )
    with pytest.raises(AssertionError, match="non-configured"):
        prepare(frame, EXPECTED_UNITS)


@pytest.mark.parametrize("label,prepare", PREPARERS.items())
def test_unusable_doses_are_excluded(label, prepare):
    frame = pl.DataFrame(
        {
            "med_category": ["rocuronium"] * 3,
            "med_dose": [50.0, None, float("nan")],
            "med_dose_unit": ["mg", "mg", "mg"],
        }
    )
    assert prepare(frame, EXPECTED_UNITS).height == 1


@pytest.mark.parametrize("label,filter_doses", SUMMARY_FILTERS.items())
def test_absolute_bounds_do_not_apply_to_configured_per_kg_units(label, filter_doses):
    frame = pl.DataFrame(
        {
            "row_id": [0, 1, 2, 3, 4],
            "med_category": ["rocuronium"] * 4 + ["ketamine"],
            "med_dose_unit": ["mg", "mg", "mg", "mg/kg", "mg"],
            "med_dose_converted": [-1.0, 399.0, 400.0, 500.0, 5_000.0],
        }
    )
    out = filter_doses(frame, UPPER_BOUNDS)
    assert out["row_id"].to_list() == [1, 3]


@pytest.mark.parametrize("label,path", DOSE_NOTEBOOKS.items())
def test_no_clifpy_dose_converter_remains(label, path):
    assert "convert_dose_units_by_med_category" not in path.read_text(), label


@pytest.mark.parametrize("label,path", DOSE_NOTEBOOKS.items())
def test_dose_summaries_still_publish_mean_and_sample_sd(label, path):
    tree = ast.parse(path.read_text())
    keywords = {
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
    }
    if label != "04_covariates":
        assert {"mean_dose", "sd_dose"} <= keywords


@pytest.mark.parametrize(
    "filename",
    ["fig_B1__paralytic_dose_ecdf.csv", "fig_E3__sedation_dose_ecdf.csv"],
)
def test_generated_dose_ecdfs_respect_configured_strict_bounds(filename):
    config_path = ROOT / "config" / "config.json"
    if not config_path.exists():
        pytest.skip("config/config.json absent; pipeline has not been set up")
    config = json.loads(config_path.read_text())
    output = Path(config["output_directory"])
    if not output.is_absolute():
        output = ROOT / output
    path = output / "final_no_phi" / filename
    if not path.exists():
        pytest.skip(f"{filename} absent; run the pipeline first")

    frame = pl.read_csv(path).with_columns(
        pl.col("med_category")
        .replace_strict(
            config["medication_dose_upper_bounds"], return_dtype=pl.Float64
        )
        .alias("upper_bound")
    )
    assert frame.filter(pl.col("dose") >= pl.col("upper_bound")).is_empty()
