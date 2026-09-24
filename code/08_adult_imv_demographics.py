"""Demographics of adult hospitalizations with at least one charted IMV row."""

import json
import sys
from pathlib import Path

import polars as pl
from clifpy.tables import Hospitalization, Patient
from clifpy.utils.io import fetch_lazy_result, load_data


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from utils.suppress import publish


RACE_LEVELS = [
    ("american indian or alaska native", "American Indian/Alaska Native"),
    ("asian", "Asian"),
    (
        "native hawaiian or other pacific islander",
        "Native Hawaiian or Other Pacific Islander",
    ),
    ("black or african american", "Black or African American"),
    ("white", "White"),
    ("more than one race", "More than One Race"),
]
ETHNICITY_LEVELS = [
    ("non-hispanic", "Not Hispanic or Latino"),
    ("hispanic", "Hispanic or Latino"),
]
SEX_LEVELS = [("female", "Female"), ("male", "Male")]


def normalize_categories(frame, *columns):
    """Strip and lowercase CLIF categorical values before matching."""
    return frame.with_columns(
        [
            pl.col(column).cast(pl.String).str.strip_chars().str.to_lowercase()
            for column in columns
        ]
    )


def select_adult_imv_hospitalizations(hospitalizations, imv_hospitalization_ids):
    """One row per hospitalization satisfying only age >=18 and any charted IMV."""
    assert hospitalizations.get_column("hospitalization_id").is_unique().all(), (
        "hospitalization source contains duplicate hospitalization_id values"
    )
    imv_ids = pl.DataFrame(
        {"hospitalization_id": pl.Series(imv_hospitalization_ids).unique()}
    )
    selected = hospitalizations.join(imv_ids, on="hospitalization_id", how="semi").filter(
        pl.col("age_at_admission") >= 18
    )
    return selected


def build_demographic_table(cohort):
    """Requested six-race table over complete Hispanic/non-Hispanic Female/Male cells."""
    count_columns = [
        f"{ethnicity_label} - {sex_label}"
        for _, ethnicity_label in ETHNICITY_LEVELS
        for _, sex_label in SEX_LEVELS
    ]
    included = cohort.filter(
        pl.col("race_category").is_in([value for value, _ in RACE_LEVELS])
        & pl.col("ethnicity_category").is_in(
            [value for value, _ in ETHNICITY_LEVELS]
        )
        & pl.col("sex_category").is_in([value for value, _ in SEX_LEVELS])
    )
    rows = []
    for race_value, race_label in RACE_LEVELS:
        race_frame = included.filter(pl.col("race_category") == race_value)
        row = {"Racial Categories": race_label}
        for ethnicity_value, ethnicity_label in ETHNICITY_LEVELS:
            for sex_value, sex_label in SEX_LEVELS:
                row[f"{ethnicity_label} - {sex_label}"] = race_frame.filter(
                    (pl.col("ethnicity_category") == ethnicity_value)
                    & (pl.col("sex_category") == sex_value)
                ).height
        row["Total"] = sum(row[column] for column in count_columns)
        assert sum(row[column] for column in count_columns) == row["Total"]
        rows.append(row)

    total = {"Racial Categories": "Total"}
    for column in [*count_columns, "Total"]:
        total[column] = sum(row[column] for row in rows)
    assert total["Total"] == included.height
    assert sum(total[column] for column in count_columns) == total["Total"]
    rows.append(total)
    return pl.DataFrame(rows).select("Racial Categories", *count_columns, "Total")


def main():
    with open(ROOT / "config" / "config.json") as config_file:
        config = json.load(config_file)

    data_dir = config["data_directory"]
    filetype = config["filetype"]
    TIMEZONE = config["timezone"]
    output_dir = Path(config["output_directory"])
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    share_dir = output_dir / "final_no_phi"
    share_dir.mkdir(parents=True, exist_ok=True)

    respiratory = load_data(
        "respiratory_support",
        data_dir,
        filetype,
        columns=["hospitalization_id", "device_category"],
        lazy=True,
    )
    imv_rows = fetch_lazy_result(
        respiratory.filter("lower(trim(device_category)) = 'imv'"),
        site_tz=TIMEZONE,
    )
    imv_ids = pl.from_pandas(imv_rows).get_column("hospitalization_id").unique()
    assert imv_ids.len() > 0, (
        "no respiratory_support hospitalization has device_category IMV"
    )

    hospitalization_table = Hospitalization.from_file(
        data_directory=data_dir,
        filetype=filetype,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "patient_id", "age_at_admission"],
        filters={"hospitalization_id": imv_ids.to_list()},
    )
    hospitalizations = pl.from_pandas(hospitalization_table.df)
    cohort = select_adult_imv_hospitalizations(hospitalizations, imv_ids)

    patient_ids = cohort.get_column("patient_id").unique().to_list()
    patient_table = Patient.from_file(
        data_directory=data_dir,
        filetype=filetype,
        timezone=TIMEZONE,
        columns=["patient_id", "sex_category", "race_category", "ethnicity_category"],
        filters={"patient_id": patient_ids},
    )
    patients = normalize_categories(
        pl.from_pandas(patient_table.df),
        "sex_category",
        "race_category",
        "ethnicity_category",
    )
    assert patients.get_column("patient_id").is_unique().all(), (
        "patient source contains duplicate patient_id values"
    )
    cohort_demographics = cohort.join(
        patients, on="patient_id", how="left", validate="m:1"
    )
    table = build_demographic_table(cohort_demographics)
    publish(
        table,
        share_dir / "step08__adult_imv_hospitalization_demographics.csv",
        "step08__adult_imv_hospitalization_demographics",
    )
    print(f"adult IMV hospitalizations: {cohort.height:,}")
    print(f"represented in demographic table: {table[-1, 'Total']:,}")
    print(f"patients: {cohort.get_column('patient_id').n_unique():,}")


if __name__ == "__main__":
    main()
