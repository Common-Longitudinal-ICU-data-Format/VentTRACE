#!/usr/bin/env python3
"""Check whether hospitalization_id is a safe key for VentTRACE joins."""

import argparse
import json
import sys
from pathlib import Path

import polars as pl
from clifpy.tables import Hospitalization


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "config.json"
SOURCE_COLUMNS = [
    "patient_id",
    "hospitalization_id",
    "admission_dttm",
    "discharge_dttm",
]


def analyze_hospitalization_ids(frame: pl.DataFrame) -> tuple[dict, pl.DataFrame]:
    """Return aggregate key metrics and the PHI rows that need investigation."""
    missing = sorted(set(SOURCE_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"hospitalization data are missing columns: {', '.join(missing)}")

    source = frame.select(SOURCE_COLUMNS).with_row_index("source_row_number", offset=2)
    source = source.with_columns(
        pl.col("patient_id").cast(pl.String),
        pl.col("hospitalization_id").cast(pl.String),
    )

    groups = (
        source.filter(pl.col("hospitalization_id").is_not_null())
        .group_by("hospitalization_id")
        .agg(
            duplicate_group_rows=pl.len(),
            duplicate_group_known_patients=pl.col("patient_id").drop_nulls().n_unique(),
            duplicate_group_null_patient_rows=pl.col("patient_id").is_null().sum(),
        )
    )
    duplicates = groups.filter(pl.col("duplicate_group_rows") > 1)
    duplicate_ids = duplicates.get_column("hospitalization_id")
    cross_patient_ids = duplicates.filter(
        pl.col("duplicate_group_known_patients") > 1
    ).get_column("hospitalization_id")

    duplicate_rows = source.filter(
        pl.col("hospitalization_id").is_in(duplicate_ids.implode())
    )
    cross_patient_rows = source.filter(
        pl.col("hospitalization_id").is_in(cross_patient_ids.implode())
    )

    total_rows = source.height
    null_hospitalization_rows = source.filter(
        pl.col("hospitalization_id").is_null()
    ).height
    null_patient_rows = source.filter(pl.col("patient_id").is_null()).height
    duplicate_rows_affected = duplicate_rows.height
    cross_patient_rows_affected = cross_patient_rows.height

    metrics = {
        "total_rows": total_rows,
        "unique_nonnull_hospitalization_ids": source.get_column("hospitalization_id")
        .drop_nulls()
        .n_unique(),
        "null_hospitalization_id_rows": null_hospitalization_rows,
        "null_patient_id_rows": null_patient_rows,
        "duplicate_hospitalization_ids": duplicates.height,
        "extra_duplicate_rows": int(
            duplicates.select(
                (pl.col("duplicate_group_rows") - 1).sum()
            ).item()
            or 0
        ),
        "duplicate_rows_affected": duplicate_rows_affected,
        "duplicate_rows_affected_pct": (
            100.0 * duplicate_rows_affected / total_rows if total_rows else 0.0
        ),
        "patients_with_duplicate_ids": duplicate_rows.get_column("patient_id")
        .drop_nulls()
        .n_unique(),
        "cross_patient_collision_ids": cross_patient_ids.len(),
        "cross_patient_rows_affected": cross_patient_rows_affected,
        "cross_patient_rows_affected_pct": (
            100.0 * cross_patient_rows_affected / total_rows if total_rows else 0.0
        ),
        "patients_in_cross_patient_collisions": cross_patient_rows.get_column("patient_id")
        .drop_nulls()
        .n_unique(),
        "same_patient_duplicate_ids": duplicates.filter(
            (pl.col("duplicate_group_known_patients") == 1)
            & (pl.col("duplicate_group_null_patient_rows") == 0)
        ).height,
        "duplicate_ids_with_null_patient": duplicates.filter(
            pl.col("duplicate_group_null_patient_rows") > 0
        ).height,
        "max_rows_for_one_hospitalization_id": int(
            duplicates.get_column("duplicate_group_rows").max() or 1
        ),
        "max_known_patients_for_one_hospitalization_id": int(
            duplicates.get_column("duplicate_group_known_patients").max() or 1
        ),
    }

    details = (
        source.join(groups, on="hospitalization_id", how="left")
        .with_columns(
            pl.when(pl.col("hospitalization_id").is_null())
            .then(pl.lit("null_hospitalization_id"))
            .when(
                (pl.col("duplicate_group_rows") > 1)
                & (pl.col("duplicate_group_known_patients") > 1)
            )
            .then(pl.lit("cross_patient_collision"))
            .when(
                (pl.col("duplicate_group_rows") > 1)
                & (pl.col("duplicate_group_null_patient_rows") > 0)
            )
            .then(pl.lit("duplicate_with_null_patient"))
            .when(pl.col("duplicate_group_rows") > 1)
            .then(pl.lit("same_patient_duplicate"))
            .when(pl.col("patient_id").is_null())
            .then(pl.lit("null_patient_id"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("issue")
        )
        .filter(pl.col("issue").is_not_null())
        .select(
            "issue",
            "source_row_number",
            "hospitalization_id",
            "patient_id",
            "admission_dttm",
            "discharge_dttm",
            "duplicate_group_rows",
            "duplicate_group_known_patients",
            "duplicate_group_null_patient_rows",
        )
        .sort(["issue", "hospitalization_id", "admission_dttm"], nulls_last=True)
    )
    return metrics, details


def print_report(metrics: dict, details_path: Path) -> None:
    """Print only aggregate, non-PHI diagnostics."""
    print("Hospitalization ID integrity check")
    print("=" * 38)
    print(f"hospitalization rows                 : {metrics['total_rows']:,}")
    print(
        "unique non-null hospitalization IDs : "
        f"{metrics['unique_nonnull_hospitalization_ids']:,}"
    )
    print(f"null hospitalization_id rows        : {metrics['null_hospitalization_id_rows']:,}")
    print(f"null patient_id rows                 : {metrics['null_patient_id_rows']:,}")
    print(f"duplicated hospitalization IDs       : {metrics['duplicate_hospitalization_ids']:,}")
    print(f"extra duplicate rows                 : {metrics['extra_duplicate_rows']:,}")
    print(
        "rows carrying a duplicated ID       : "
        f"{metrics['duplicate_rows_affected']:,} "
        f"({metrics['duplicate_rows_affected_pct']:.3f}%)"
    )
    print(f"patients carrying duplicated IDs     : {metrics['patients_with_duplicate_ids']:,}")
    print(f"cross-patient collision IDs          : {metrics['cross_patient_collision_ids']:,}")
    print(
        "rows in cross-patient collisions     : "
        f"{metrics['cross_patient_rows_affected']:,} "
        f"({metrics['cross_patient_rows_affected_pct']:.3f}%)"
    )
    print(
        "patients in cross-patient collisions : "
        f"{metrics['patients_in_cross_patient_collisions']:,}"
    )
    print(f"same-patient duplicate IDs           : {metrics['same_patient_duplicate_ids']:,}")
    print(
        "duplicate IDs with a null patient    : "
        f"{metrics['duplicate_ids_with_null_patient']:,}"
    )
    print(
        "maximum rows for one ID              : "
        f"{metrics['max_rows_for_one_hospitalization_id']:,}"
    )
    print(
        "maximum known patients for one ID    : "
        f"{metrics['max_known_patients_for_one_hospitalization_id']:,}"
    )
    print(f"PHI details                          : {details_path}")

    if metrics["cross_patient_collision_ids"]:
        print(
            "\nRESULT: UNSAFE. At least one hospitalization_id belongs to multiple "
            "patients. VentTRACE cannot determine which patient's ADT, medication, or "
            "respiratory rows are correct. Fix and propagate the key in the site ETL; "
            "do not deduplicate cohort_index."
        )
    elif (
        metrics["duplicate_hospitalization_ids"]
        or metrics["null_hospitalization_id_rows"]
        or metrics["null_patient_id_rows"]
    ):
        print(
            "\nRESULT: INVALID. The hospitalization table violates the CLIF primary-key "
            "contract and can fan out downstream joins. Reconcile these source rows "
            "before running VentTRACE."
        )
    else:
        print("\nRESULT: PASS. hospitalization_id is non-null and unique.")


def _resolved_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure null and duplicate hospitalization_id problems before stitching."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"site configuration JSON (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--details",
        type=Path,
        help="PHI parquet destination (default: <output_directory>/intermediate_phi/...)"
    )
    args = parser.parse_args(argv)

    config_path = args.config.expanduser().resolve()
    try:
        with config_path.open() as file:
            config = json.load(file)
        config_base = ROOT
        data_directory = _resolved_path(config["data_directory"], base=config_base)
        output_directory = _resolved_path(config["output_directory"], base=config_base)
        details_path = (
            args.details.expanduser().resolve()
            if args.details
            else output_directory
            / "intermediate_phi"
            / "hospitalization_id_diagnostic.parquet"
        )

        hospitalization = Hospitalization.from_file(
            data_directory=str(data_directory),
            filetype=config["filetype"],
            timezone=config["timezone"],
            output_directory=str(output_directory / "intermediate_phi"),
            columns=SOURCE_COLUMNS,
        )
        metrics, details = analyze_hospitalization_ids(pl.from_pandas(hospitalization.df))
        details_path.parent.mkdir(parents=True, exist_ok=True)
        details.write_parquet(details_path)
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"hospitalization ID check failed: {error}", file=sys.stderr)
        return 2

    print_report(metrics, details_path)
    has_violation = bool(
        metrics["duplicate_hospitalization_ids"]
        or metrics["null_hospitalization_id_rows"]
        or metrics["null_patient_id_rows"]
    )
    return 1 if has_violation else 0


if __name__ == "__main__":
    raise SystemExit(main())
