"""Tests for the standalone hospitalization key diagnostic."""

import importlib.util
from datetime import datetime
from pathlib import Path

import polars as pl


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "code" / "qc" / "check_hospitalization_ids.py"
SPEC = importlib.util.spec_from_file_location("check_hospitalization_ids", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
analyze_hospitalization_ids = MODULE.analyze_hospitalization_ids


def _frame(patient_ids, hospitalization_ids):
    size = len(patient_ids)
    return pl.DataFrame(
        {
            "patient_id": patient_ids,
            "hospitalization_id": hospitalization_ids,
            "admission_dttm": [datetime(2025, 1, day) for day in range(1, size + 1)],
            "discharge_dttm": [datetime(2025, 1, day + 1) for day in range(1, size + 1)],
        },
        schema_overrides={"patient_id": pl.String, "hospitalization_id": pl.String},
    )


def test_clean_hospitalization_keys_pass_without_details():
    metrics, details = analyze_hospitalization_ids(_frame(["p1", "p2"], ["h1", "h2"]))

    assert metrics["duplicate_hospitalization_ids"] == 0
    assert metrics["cross_patient_collision_ids"] == 0
    assert metrics["null_hospitalization_id_rows"] == 0
    assert details.is_empty()


def test_cross_patient_collision_quantifies_affected_rows_and_patients():
    frame = _frame(["p1", "p2", "p3"], ["shared", "shared", "unique"])
    metrics, details = analyze_hospitalization_ids(frame)

    assert metrics["duplicate_hospitalization_ids"] == 1
    assert metrics["extra_duplicate_rows"] == 1
    assert metrics["duplicate_rows_affected"] == 2
    assert metrics["patients_with_duplicate_ids"] == 2
    assert metrics["cross_patient_collision_ids"] == 1
    assert metrics["cross_patient_rows_affected"] == 2
    assert metrics["patients_in_cross_patient_collisions"] == 2
    assert details.get_column("issue").to_list() == [
        "cross_patient_collision",
        "cross_patient_collision",
    ]


def test_same_patient_duplicates_are_separated_from_cross_patient_collisions():
    metrics, details = analyze_hospitalization_ids(
        _frame(["p1", "p1", "p2"], ["repeated", "repeated", "unique"])
    )

    assert metrics["same_patient_duplicate_ids"] == 1
    assert metrics["cross_patient_collision_ids"] == 0
    assert details.get_column("issue").unique().to_list() == ["same_patient_duplicate"]


def test_null_keys_are_reported_even_when_other_ids_are_unique():
    metrics, details = analyze_hospitalization_ids(
        _frame(["p1", None, "p3"], [None, "h2", "h3"])
    )

    assert metrics["null_hospitalization_id_rows"] == 1
    assert metrics["null_patient_id_rows"] == 1
    assert set(details.get_column("issue")) == {
        "null_hospitalization_id",
        "null_patient_id",
    }
