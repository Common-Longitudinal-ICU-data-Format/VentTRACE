"""Validate and inventory every shareable VentTRACE artifact."""

import hashlib
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.suppress import publish


ROOT = Path(__file__).parent.parent
with open(ROOT / "config" / "config.json") as config_file:
    CONFIG = json.load(config_file)

OUTPUT_DIR = Path(CONFIG["output_directory"])
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = ROOT / OUTPUT_DIR
SHARE_DIR = OUTPUT_DIR / "final_no_phi"
SITE = CONFIG["site_name"]


# filename, kind, producer, figure_id, primary dataframe, direct source files
CATALOG = [
    ("step01__consort_cohort.csv", "data", "01_cohort", None, "consort_df", "intermediate_phi/step01__cohort.parquet"),
    ("step01__cohort_qc.csv", "qc", "01_cohort", None, "cohort_qc", "intermediate_phi/step01__cohort_index.parquet"),
    ("step02__paralytic_administration_summary.csv", "data", "02_index_paralytic", None, "admin_summary", "intermediate_phi/step01__cohort_index.parquet"),
    ("fig_A1__paralytic_administration_pair_gaps.csv", "figure_data", "02_index_paralytic", "A1", "figure_a1_df", "final_no_phi/step02__paralytic_administration_summary.csv"),
    ("step02__paralytic_pair_gaps_by_agent_pair.csv", "data", "02_index_paralytic", None, "gap_by_pair", "intermediate_phi/step01__cohort_index.parquet"),
    ("fig_C1__index_paralytic_pair_gaps.csv", "figure_data", "02_index_paralytic", "C1", "figure_c1_df", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step02__index_paralytics_per_block.csv", "data", "02_index_paralytic", None, "index_per_block", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step02__index_paralytic_summary.csv", "data", "02_index_paralytic", None, "index_summary", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step02__index_paralytic_composition.csv", "data", "02_index_paralytic", None, "index_composition", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step02__paralytic_dose_unit_corrections.csv", "qc", "02_index_paralytic", None, "paralytic_dose_unit_corrections", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step02__index_paralytic_dose_summary.csv", "data", "02_index_paralytic", None, "index_dose", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step02__paralytic_dose_raw_unit_counts.csv", "qc", "02_index_paralytic", None, "paralytic_dose_units", "intermediate_phi/step02__index_paralytic.parquet"),
    ("fig_B1__paralytic_dose_ecdf.csv", "figure_data", "02_index_paralytic", "B1", "figure_b1_df", "intermediate_phi/step02__index_paralytic.parquet"),
    ("step03__imv_transition_summary.csv", "data", "03_context", None, "transition_summary", "intermediate_phi/step03__index_context.parquet"),
    ("step03__imv_prior_device.csv", "data", "03_context", None, "prior_device", "intermediate_phi/step03__index_context.parquet"),
    ("fig_D1__imv_transition_offset.csv", "figure_data", "03_context", "D1", "figure_d1_df", "intermediate_phi/step03__index_context.parquet"),
    ("step03__imv_transitions_per_window.csv", "data", "03_context", None, "transitions_in_window", "intermediate_phi/step03__index_context.parquet"),
    ("step03__sedation_summary.csv", "data", "03_context", None, "sedation_summary", "intermediate_phi/step03__index_context.parquet"),
    ("fig_E1__sedation_offset.csv", "figure_data", "03_context", "E1", "figure_e1_df", "intermediate_phi/step03__index_context.parquet"),
    ("step03__sedation_dose_unit_corrections.csv", "qc", "03_context", None, "sedation_dose_unit_corrections", "intermediate_phi/step03__index_context.parquet"),
    ("fig_E2__sedation_dose_summary.csv", "figure_data", "03_context", "E2", "figure_e2_df", "intermediate_phi/step03__index_context.parquet"),
    ("step03__sedation_dose_raw_unit_counts.csv", "qc", "03_context", None, "sedation_dose_units", "intermediate_phi/step03__index_context.parquet"),
    ("fig_E3__sedation_dose_ecdf.csv", "figure_data", "03_context", "E3", "figure_e3_df", "intermediate_phi/step03__index_context.parquet"),
    ("step04__sofa_coverage.csv", "qc", "04_covariates", None, "sofa_coverage", "intermediate_phi/step04__index_covariates.parquet"),
    ("fig_T2__source_coverage.csv", "figure_data", "04_covariates", "T2", "figure_t2_df", "intermediate_phi/step04__index_covariates.parquet"),
    ("table1_by_agent_block_readable.csv", "table", "05_table_one", None, "table1_block_readable", "intermediate_phi/step04__index_covariates.parquet"),
    ("table1_by_agent_block.json", "table", "05_table_one", None, "table1_block", "intermediate_phi/step04__index_covariates.parquet"),
    ("table1_by_agent_index_readable.csv", "table", "05_table_one", None, "table1_index_readable", "intermediate_phi/step04__index_covariates.parquet"),
    ("table1_by_agent_index.json", "table", "05_table_one", None, "table1_index", "intermediate_phi/step04__index_covariates.parquet"),
    ("fig_T1__organ_support_by_window.csv", "figure_data", "05_table_one", "T1", "figure_t1_df", "final_no_phi/table1_by_agent_block.json"),
    ("fig_F1__cpt_cascade.csv", "figure_data", "06_reference_cpt", "F1", "figure_f1_df", "intermediate_phi/step04__index_covariates.parquet"),
    ("fig_F1__cpt_cascade_qc.csv", "qc", "06_reference_cpt", "F1", "cpt_cascade_qc", "final_no_phi/fig_F1__cpt_cascade.csv"),
]

FIGURES = [
    ("A1", "paralytic_administration_pair_gaps", "02_index_paralytic", "figure_a1_df"),
    ("B1", "paralytic_dose_ecdf", "02_index_paralytic", "figure_b1_df"),
    ("C1", "index_paralytic_pair_gaps", "02_index_paralytic", "figure_c1_df"),
    ("D1", "imv_transition_offset", "03_context", "figure_d1_df"),
    ("E1", "sedation_offset", "03_context", "figure_e1_df"),
    ("E2", "sedation_dose_summary", "03_context", "figure_e2_df"),
    ("E3", "sedation_dose_ecdf", "03_context", "figure_e3_df"),
    ("T1", "organ_support_by_window", "05_table_one", "figure_t1_df"),
    ("T2", "source_coverage", "05_table_one", "figure_t2_df"),
    ("F1", "cpt_cascade", "06_reference_cpt", "figure_f1_df"),
]

for figure_id, description, producer, dataframe in FIGURES:
    stem = f"fig_{figure_id}__{description}"
    CATALOG.append(
        (
            f"figures/{stem}.png",
            "figure",
            producer,
            figure_id,
            dataframe,
            f"final_no_phi/{stem}.csv",
        )
    )


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path):
    if path.suffix == ".csv":
        return pl.read_csv(path).height
    if path.suffix == ".json":
        with open(path) as file:
            return len(json.load(file)["rows"])
    return None


def main():
    table1_path = SHARE_DIR / "table1_by_agent_block.json"
    with open(table1_path) as file:
        cohort_run_id = json.load(file)["meta"]["cohort_run_id"]

    declared = {entry[0] for entry in CATALOG}
    actual = {
        str(path.relative_to(SHARE_DIR))
        for path in SHARE_DIR.rglob("*")
        if path.is_file() and path.name != "artifact_manifest.csv"
    }
    unexpected = sorted(actual - declared)
    assert not unexpected, f"undeclared or stale shareable artifacts: {unexpected}"

    missing_sources = sorted(
        source_files
        for *_, source_files in CATALOG
        if not (OUTPUT_DIR / source_files).exists()
    )
    assert not missing_sources, f"declared source artifacts are missing: {missing_sources}"

    rows = []
    missing_required = []
    for filename, kind, producer, figure_id, dataframe, source_files in CATALOG:
        path = SHARE_DIR / filename
        exists = path.exists()
        if not exists and kind == "figure":
            source = OUTPUT_DIR / source_files
            if source.exists() and row_count(source) == 0:
                status = "not_generated_empty_source"
            else:
                missing_required.append(filename)
                status = "missing"
        elif not exists:
            missing_required.append(filename)
            status = "missing"
        else:
            status = "generated"

        rows.append(
            {
                "artifact_id": f"{figure_id}.{kind}" if figure_id else Path(filename).stem,
                "filename": filename,
                "kind": kind,
                "producer_step": producer,
                "figure_id": figure_id,
                "primary_dataframe": dataframe,
                "source_files": source_files,
                "status": status,
                "row_count": row_count(path) if exists else None,
                "byte_size": path.stat().st_size if exists else None,
                "sha256": sha256(path) if exists else None,
                "site_name": SITE,
                "cohort_run_id": cohort_run_id,
            }
        )

    assert not missing_required, f"required shareable artifacts are missing: {missing_required}"
    manifest = pl.DataFrame(rows).sort(["producer_step", "filename"])
    assert manifest.get_column("filename").is_unique().all()
    assert manifest.get_column("artifact_id").is_unique().all()
    publish(manifest, SHARE_DIR / "artifact_manifest.csv", "artifact_manifest")
    print(f"validated {manifest.height} declared artifacts for {SITE}")


if __name__ == "__main__":
    main()
