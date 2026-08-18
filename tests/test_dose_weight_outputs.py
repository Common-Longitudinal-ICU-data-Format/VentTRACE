"""Contracts for dose/weight selection and consortium-poolable outputs."""

import ast
from datetime import datetime
import json
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
NOTEBOOK = ROOT / "code" / "04_covariates.py"


def _load_function(name):
    tree = ast.parse(NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"pl": pl}
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[name]


SELECT_WEIGHTS = _load_function("select_dose_weights")
ECDF = _load_function("ecdf_by_dose_per_weight")
NORMALISE = _load_function("_normalised")


def _share_dir():
    with open(ROOT / "config" / "config.json") as file:
        output = Path(json.load(file)["output_directory"])
    if not output.is_absolute():
        output = ROOT / output
    return output / "final_no_phi"


def test_weight_selector_prefers_current_hospital_and_latest_valid_value():
    t0 = datetime(2025, 2, 1, 12)
    events = pl.DataFrame(
        {
            "index_paralytic_id": ["event"],
            "patient_id": ["patient"],
            "current_hospitalization_id": ["current"],
            "t_dttm": [t0],
        }
    )
    hospitalizations = pl.DataFrame(
        {
            "hospitalization_id": ["prior", "current"],
            "patient_id": ["patient", "patient"],
            "admission_dttm": [datetime(2025, 1, 20), datetime(2025, 2, 1)],
        }
    )
    weights = pl.DataFrame(
        {
            "hospitalization_id": ["prior", "current", "current", "current"],
            "recorded_dttm": [
                datetime(2025, 1, 31),
                datetime(2025, 2, 1, 8),
                datetime(2025, 2, 1, 11),
                datetime(2025, 2, 1, 11),
            ],
            "vital_value": [90.0, 70.0, 80.0, 75.0],
        }
    )

    out = SELECT_WEIGHTS(events, hospitalizations, weights)

    assert out["dose_weight_kg"][0] == 75.0
    assert out["dose_weight_source"][0] == "current_hospitalization"


def test_weight_selector_uses_only_valid_prior_weight_within_28_days():
    t0 = datetime(2025, 3, 1)
    events = pl.DataFrame(
        {
            "index_paralytic_id": ["event"],
            "patient_id": ["patient"],
            "current_hospitalization_id": ["current"],
            "t_dttm": [t0],
        }
    )
    hospitalizations = pl.DataFrame(
        {
            "hospitalization_id": ["old", "recent", "current"],
            "patient_id": ["patient"] * 3,
            "admission_dttm": [
                datetime(2024, 12, 1),
                datetime(2025, 2, 10),
                datetime(2025, 3, 1),
            ],
        }
    )
    weights = pl.DataFrame(
        {
            "hospitalization_id": ["old", "recent", "recent", "current"],
            "recorded_dttm": [
                datetime(2025, 1, 1),
                datetime(2025, 2, 20),
                datetime(2025, 2, 21),
                datetime(2025, 3, 2),
            ],
            "vital_value": [80.0, 301.0, 85.0, 75.0],
        }
    )

    out = SELECT_WEIGHTS(events, hospitalizations, weights)

    assert out["dose_weight_kg"][0] == 85.0
    assert out["dose_weight_source"][0] == "prior_hospitalization_28d"


def test_weight_selector_returns_null_when_only_future_or_out_of_range_values_exist():
    events = pl.DataFrame(
        {
            "index_paralytic_id": ["event"],
            "patient_id": ["patient"],
            "current_hospitalization_id": ["current"],
            "t_dttm": [datetime(2025, 3, 1)],
        }
    )
    hospitalizations = pl.DataFrame(
        {
            "hospitalization_id": ["current"],
            "patient_id": ["patient"],
            "admission_dttm": [datetime(2025, 3, 1)],
        }
    )
    weights = pl.DataFrame(
        {
            "hospitalization_id": ["current", "current"],
            "recorded_dttm": [datetime(2025, 3, 2), datetime(2025, 2, 28)],
            "vital_value": [80.0, 10.0],
        }
    )

    out = SELECT_WEIGHTS(events, hospitalizations, weights)

    assert out["dose_weight_kg"][0] is None
    assert out["dose_weight_source"][0] is None


def test_normalized_ecdf_preserves_integer_pooling_counts():
    df = pl.DataFrame(
        {
            "med_category": ["etomidate", "etomidate", "etomidate"],
            "dose_per_weight_unit": ["mg/kg"] * 3,
            "dose_per_weight": [0.2, 0.2, 0.3],
        }
    )
    out = ECDF(df)

    assert out["n_at_dose"].to_list() == [2, 1]
    assert out["n_cum"].to_list() == [2, 3]
    assert out["n_total"].to_list() == [3, 3]
    assert out["ecdf"].to_list() == pytest.approx([2 / 3, 1.0], abs=5e-7)


def test_configured_per_kg_dose_is_not_divided_by_weight_again():
    frame = pl.DataFrame(
        {
            "med_dose_converted": [70.0, 1.2],
            "med_dose_unit_converted": ["mg", "mg/kg"],
            "dose_weight_kg": [70.0, None],
        }
    )

    out = NORMALISE(frame)

    assert out["dose_per_weight"].to_list() == [1.0, 1.2]
    assert out["dose_per_weight_unit"].to_list() == ["mg/kg", "mg/kg"]


def test_generated_site_outputs_are_reconcilable_and_poolable():
    share = _share_dir()
    required = [
        "step04__intubations_by_hospital_year.csv",
        "fig_B2__paralytic_dose_per_weight_ecdf.csv",
        "fig_E4__sedation_dose_per_weight_ecdf.csv",
        "step04__combined_induction_dose_distribution_percentiles.csv",
        "fig_E5__induction_dose_tiers.csv",
        "fig_G1__dose_per_weight_consort.csv",
    ]
    if not all((share / name).exists() for name in required):
        pytest.skip("dose/weight outputs absent; run step 04 first")

    counts = pl.read_csv(share / required[0])
    tiers = pl.read_csv(share / required[4])
    flow = pl.read_csv(share / required[5])
    percentiles = pl.read_csv(share / required[3])

    expected_blocks = pl.read_csv(
        share / "step02__index_paralytics_per_block.csv"
    )["n_blocks"].sum()
    assert counts["n_intubations"].sum() == expected_blocks
    assert tiers.height == 8
    assert tiers.group_by(["site_name", "drug"]).agg(
        pl.col("n_admin_windows").sum().alias("sum_n"),
        pl.col("n_total").first().alias("n_total"),
    ).filter(pl.col("sum_n") != pl.col("n_total")).is_empty()
    if tiers["n_total"].max() > 0:
        assert set(percentiles["percentile"].unique()) == set(range(1, 100))
    else:
        assert percentiles.is_empty()
    assert flow.sort(["population", "stage_order"]).group_by("population").agg(
        pl.col("n_remaining").diff().drop_nulls().max().alias("largest_increase")
    ).filter(pl.col("largest_increase") > 0).is_empty()
