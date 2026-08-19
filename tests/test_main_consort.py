"""Reconciliation contract for Figure 1, the main analysis CONSORT."""

import json
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "config.json"


def _paths():
    with open(CONFIG) as file:
        output = Path(json.load(file)["output_directory"])
    if not output.is_absolute():
        output = ROOT / output
    return (
        output / "intermediate_phi" / "step04__index_covariates.parquet",
        output / "final_no_phi" / "fig_1__main_consort.csv",
        output / "final_no_phi" / "step02__procedural_index_exclusion_summary.csv",
    )


@pytest.fixture(scope="module")
def sources():
    frame_path, consort_path, procedural_path = _paths()
    if not consort_path.exists():
        pytest.skip("fig_1__main_consort.csv absent; run code/05_table_one.py first")
    return (
        pl.read_parquet(frame_path),
        pl.read_csv(consort_path),
        pl.read_csv(procedural_path),
    )


def _population(consort, stage):
    row = consort.filter(
        (pl.col("row_type") == "population")
        & (pl.col("stage") == stage)
        & (pl.col("agent") == "overall")
    )
    assert row.height == 1, stage
    return row.row(0, named=True)


def _counts(frame):
    return {
        "n_source_administrations": frame.get_column("n_before_merge_admin").sum(),
        "n_postmerge_med_entries": frame.get_column("n_admins").sum(),
        "n_indexes": frame.height,
        "n_encounter_blocks": frame.get_column("encounter_block").n_unique(),
    }


def test_main_population_rows_reconcile_to_the_analytic_frame(sources):
    frame, consort, procedural = sources
    imv = frame.filter(pl.col("imv_transition"))
    valid = imv.filter(pl.col("any_sedative"))
    block = (
        valid.sort(["encounter_block", "p_num", "index_paralytic_id"])
        .unique("encounter_block", keep="first", maintain_order=True)
    )

    expected = {
        "nonprocedural_indexes": frame,
        "imv_transition": imv,
        "table1_index": valid,
        "table1_block": block,
    }
    for stage, source in expected.items():
        row = _population(consort, stage)
        for column, value in _counts(source).items():
            assert row[column] == value, (stage, column)

    formed_summary = procedural.filter(
        (pl.col("population") == "formed_indexes") & (pl.col("agent") == "overall")
    ).row(0, named=True)
    for stage in ("qualifying_administrations", "formed_indexes"):
        source = _population(consort, stage)
        assert source["n_source_administrations"] == formed_summary[
            "n_source_administrations"
        ]
    source = _population(consort, "qualifying_administrations")
    assert source["n_postmerge_med_entries"] is None
    assert source["n_indexes"] is None


def test_main_consort_exclusions_partition_each_gate(sources):
    frame, consort, procedural = sources
    imv = frame.filter(pl.col("imv_transition"))
    valid = imv.filter(pl.col("any_sedative"))

    imv_exclusion = consort.filter(
        (pl.col("row_type") == "exclusion")
        & (pl.col("stage") == "imv_transition")
    ).row(0, named=True)
    sedation_exclusion = consort.filter(
        (pl.col("row_type") == "exclusion")
        & (pl.col("stage") == "table1_index")
    ).row(0, named=True)
    procedural_exclusion = consort.filter(
        (pl.col("row_type") == "exclusion")
        & (pl.col("stage") == "nonprocedural_indexes")
    ).row(0, named=True)
    formed = procedural.filter(
        (pl.col("population") == "formed_indexes") & (pl.col("agent") == "overall")
    ).row(0, named=True)

    assert procedural_exclusion["n_indexes"] + frame.height == formed["n_indexes"]
    assert procedural_exclusion["n_blocks_removed"] == (
        formed["n_encounter_blocks"]
        - frame.get_column("encounter_block").n_unique()
    )

    assert imv_exclusion["n_indexes"] + imv.height == frame.height
    assert imv_exclusion["n_blocks_removed"] == (
        frame.get_column("encounter_block").n_unique()
        - imv.get_column("encounter_block").n_unique()
    )
    assert sedation_exclusion["n_indexes"] + valid.height == imv.height
    assert sedation_exclusion["n_blocks_removed"] == (
        imv.get_column("encounter_block").n_unique()
        - valid.get_column("encounter_block").n_unique()
    )

    details = consort.filter(
        (pl.col("row_type") == "exclusion_detail")
        & (pl.col("stage") == "imv_transition")
    )
    assert details.get_column("n_indexes").sum() == imv_exclusion["n_indexes"]


def test_main_consort_agent_strata_are_additive_except_blocks(sources):
    _, consort, _ = sources
    populations = consort.filter(pl.col("row_type") == "population")
    for stage in populations.get_column("stage").unique():
        stage_rows = populations.filter(pl.col("stage") == stage)
        overall = stage_rows.filter(pl.col("agent") == "overall").row(0, named=True)
        strata = stage_rows.filter(pl.col("agent") != "overall")
        assert strata.get_column("n_source_administrations").sum() == overall[
            "n_source_administrations"
        ]
        if overall["n_indexes"] is not None:
            assert strata.get_column("n_postmerge_med_entries").sum() == overall[
                "n_postmerge_med_entries"
            ]
            assert strata.get_column("n_indexes").sum() == overall["n_indexes"]


def test_source_medication_rows_reconcile_to_all_administrations(sources):
    _, consort, _ = sources
    source = _population(consort, "qualifying_administrations")
    medications = consort.filter(pl.col("row_type") == "source_medication")
    assert set(medications.get_column("agent")).issubset({
        "rocuronium",
        "succinylcholine",
        "vecuronium",
    })
    assert medications.get_column("n_source_administrations").sum() == source[
        "n_source_administrations"
    ]
