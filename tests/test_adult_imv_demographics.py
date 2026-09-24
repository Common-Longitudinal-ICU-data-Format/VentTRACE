"""Contract tests for the independent adult IMV hospitalization summary."""

import importlib.util
from pathlib import Path

import polars as pl


ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "code" / "08_adult_imv_demographics.py"
SPEC = importlib.util.spec_from_file_location("adult_imv_demographics", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_selector_uses_only_adult_age_and_any_imv_hospitalization():
    hospitalizations = pl.DataFrame(
        {
            "hospitalization_id": ["adult_imv", "minor_imv", "missing_age", "adult_no_imv"],
            "patient_id": ["p1", "p2", "p3", "p4"],
            "age_at_admission": [18.0, 17.0, None, 65.0],
        }
    )
    selected = MODULE.select_adult_imv_hospitalizations(
        hospitalizations,
        ["adult_imv", "adult_imv", "minor_imv", "missing_age"],
    )

    assert selected.get_column("hospitalization_id").to_list() == ["adult_imv"]


def test_demographic_table_keeps_only_requested_categories_and_reconciles():
    cohort = pl.DataFrame(
        {
            "race_category": [
                "white",
                "other",
                "unknown",
                None,
                "more than one race",
            ],
            "ethnicity_category": [
                "non-hispanic",
                "hispanic",
                "unknown",
                None,
                "other",
            ],
            "sex_category": ["female", "male", "unknown", None, "other"],
        }
    )
    table = MODULE.build_demographic_table(cohort)

    expected_races = {
        "American Indian/Alaska Native",
        "Asian",
        "Native Hawaiian or Other Pacific Islander",
        "Black or African American",
        "White",
        "More than One Race",
        "Total",
    }
    assert set(table.get_column("Racial Categories")) == expected_races

    count_columns = [
        column
        for column in table.columns
        if column not in ("Racial Categories", "Total")
    ]
    race_rows = table.filter(pl.col("Racial Categories") != "Total")
    total = table.filter(pl.col("Racial Categories") == "Total").row(0, named=True)
    assert count_columns == [
        "Not Hispanic or Latino - Female",
        "Not Hispanic or Latino - Male",
        "Hispanic or Latino - Female",
        "Hispanic or Latino - Male",
    ]
    assert total["Total"] == 1
    assert sum(total[column] for column in count_columns) == 1
    assert race_rows.filter(
        pl.sum_horizontal([pl.col(column) for column in count_columns])
        != pl.col("Total")
    ).height == 0
    assert total["Not Hispanic or Latino - Female"] == 1
    assert total["Hispanic or Latino - Male"] == 0
