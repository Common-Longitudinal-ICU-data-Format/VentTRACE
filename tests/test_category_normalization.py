"""Category values are canonical before any exact match, join, or grouping."""

import ast
import datetime
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl
import pytest

from clifpy.tables import (
    Labs,
    MedicationAdminContinuous,
    PatientAssessments,
    RespiratorySupport,
    Vitals,
)


ROOT = Path(__file__).parent.parent
NOTEBOOKS = {
    path.stem: path
    for path in sorted((ROOT / "code").glob("0[1-4]_*.py"))
}


def _load_function(path, name, namespace=None):
    tree = ast.parse(path.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, f"expected one {name} in {path.name}"
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {"pl": pl, **(namespace or {})}
    exec(compile(module, str(path), "exec"), scope)
    return scope[name]


NORMALIZERS = {
    label: _load_function(path, "normalize_category_columns")
    for label, path in NOTEBOOKS.items()
}


@pytest.mark.parametrize("label,normalize", NORMALIZERS.items())
def test_source_categories_are_trimmed_lowercased_and_null_preserving(label, normalize):
    columns = [
        "device_category",
        "location_category",
        "mar_action_category",
        "med_category",
        "discharge_category",
        "sex_category",
    ]
    raw = [" IMV ", "iMv", " Given ", "Rocuronium ", " EXPIRED", None]
    frame = pl.DataFrame(
        {column: raw for column in columns},
        schema_overrides={column: pl.String for column in columns},
    )

    result = normalize(frame, *columns)

    expected = ["imv", "imv", "given", "rocuronium", "expired", None]
    for column in columns:
        assert result.get_column(column).to_list() == expected, label


def test_vital_category_aliases_are_canonical():
    path = ROOT / "code" / "04_covariates.py"
    normalize = NORMALIZERS["04_covariates"]
    normalize_vital = _load_function(
        path,
        "normalize_vital_category",
        {"normalize_category_columns": normalize},
    )
    frame = pl.DataFrame(
        {
            "vital_category": [
                " SpO2 ",
                "SpO₂",
                "HeartRate",
                " HEART_RATE ",
                "weightKg",
                " WEIGHT_KG ",
                None,
            ]
        },
        schema_overrides={"vital_category": pl.String},
    )

    assert normalize_vital(frame).get_column("vital_category").to_list() == [
        "spo2",
        "spo2",
        "heart_rate",
        "heart_rate",
        "weight_kg",
        "weight_kg",
        None,
    ]


def test_sofa_inputs_are_canonical_before_clifpy_rereads_them(tmp_path):
    path = ROOT / "code" / "04_covariates.py"
    normalize = NORMALIZERS["04_covariates"]
    normalize_vital = _load_function(
        path,
        "normalize_vital_category",
        {"normalize_category_columns": normalize},
    )
    prepare = _load_function(
        path,
        "prepare_sofa_inputs",
        {
            "Labs": Labs,
            "MedicationAdminContinuous": MedicationAdminContinuous,
            "PatientAssessments": PatientAssessments,
            "Path": Path,
            "RespiratorySupport": RespiratorySupport,
            "Vitals": Vitals,
            "normalize_category_columns": normalize,
            "normalize_vital_category": normalize_vital,
            "source_category_variants": _load_function(path, "source_category_variants"),
        },
    )
    source = tmp_path / "source"
    destination = tmp_path / "prepared"
    source.mkdir()
    dttm = [datetime.datetime(2024, 1, 1), datetime.datetime(2024, 1, 2)]
    ids = ["H1", "H2"]

    pl.DataFrame(
        {
            "hospitalization_id": ids,
            "lab_result_dttm": dttm,
            "lab_category": ["Creatinine", "creatinine"],
            "lab_value": ["1", "2"],
            "lab_value_numeric": [1.0, 2.0],
        }
    ).write_parquet(source / "clif_labs.parquet")
    pl.DataFrame(
        {
            "hospitalization_id": ids,
            "recorded_dttm": dttm,
            "vital_category": ["SpO₂", "spo2"],
            "vital_value": [98.0, 97.0],
        }
    ).write_parquet(source / "clif_vitals.parquet")
    pl.DataFrame(
        {
            "hospitalization_id": ids,
            "recorded_dttm": dttm,
            "assessment_category": ["GCS_TOTAL", "gcs_total"],
            "numerical_value": [15.0, 14.0],
            "categorical_value": [None, None],
        }
    ).write_parquet(source / "clif_patient_assessments.parquet")
    pl.DataFrame(
        {
            "hospitalization_id": ids,
            "recorded_dttm": dttm,
            "device_category": [" iMv ", "IMV"],
            "mode_category": [" Pressure Support ", "pressure support"],
            "fio2_set": [0.5, 0.4],
            "lpm_set": [None, None],
            "tidal_volume_set": [500.0, 450.0],
            "resp_rate_set": [16.0, 14.0],
        }
    ).write_parquet(source / "clif_respiratory_support.parquet")
    pl.DataFrame(
        {
            "hospitalization_id": ids,
            "admin_dttm": dttm,
            "med_category": ["Norepinephrine", "norepinephrine"],
            "med_dose": [0.1, 0.2],
            "med_dose_unit": ["mcg/kg/min", "mcg/kg/min"],
        }
    ).write_parquet(source / "clif_medication_admin_continuous.parquet")

    prepare(source, "parquet", "UTC", destination, ["H1"])

    assert pl.read_parquet(destination / "clif_labs.parquet")["lab_category"].to_list() == [
        "creatinine"
    ]
    assert pl.read_parquet(destination / "clif_vitals.parquet")["vital_category"].to_list() == [
        "spo2"
    ]
    assert pl.read_parquet(destination / "clif_patient_assessments.parquet")[
        "assessment_category"
    ].to_list() == ["gcs_total"]
    respiratory = pl.read_parquet(destination / "clif_respiratory_support.parquet")
    assert respiratory.select("device_category", "mode_category").row(0) == (
        "IMV",
        "pressure support",
    )
    assert pl.read_parquet(destination / "clif_medication_admin_continuous.parquet")[
        "med_category"
    ].to_list() == ["norepinephrine"]


def test_source_category_filter_variants_cover_supported_vital_aliases():
    variants = _load_function(ROOT / "code" / "04_covariates.py", "source_category_variants")

    assert {"weight_kg", "WeightKg", "weightKg", "WEIGHTKG"} <= set(
        variants(["weight_kg"])
    )
    assert {"spo2", "SpO2", "SpO₂", "SPO₂"} <= set(variants(["spo2"]))


def test_initial_medication_pushdown_is_normalized():
    path = ROOT / "code" / "01_cohort.py"
    canonical_sql = _load_function(path, "canonical_category_sql")
    source = pd.DataFrame(
        {
            "med_category": [
                "IMV",
                " imv ",
                "\tImV\n",
                "\u00a0IMV\u00a0",
                "\u2003imv\u2003",
                "other",
                None,
            ]
        }
    )
    connection = duckdb.connect()
    connection.register("source", source)
    try:
        matched = connection.sql(
            f"SELECT med_category FROM source WHERE {canonical_sql('med_category')} = 'imv'"
        ).fetchall()
    finally:
        connection.close()

    assert len(matched) == 5
    assert "canonical_category_sql(\"med_category\")" in path.read_text()
