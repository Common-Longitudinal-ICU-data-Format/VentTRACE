## Code directory

Six marimo notebooks plus one artifact-audit step, run in order by
[`../run_all.sh`](../run_all.sh), each named for the
CLIF table it opens rather than for a step number that would drift as the design changes. The
full walkthrough — what each one does, why, and the numbers this run produced — is
[`../docs/pipeline_flow.md`](../docs/pipeline_flow.md); this file is just the map.

| notebook | what it does | reads | writes |
|---|---|---|---|
| `01_cohort.py` | Builds the analytic cohort: adults, ED/ICU, at least one qualifying paralytic administration, no trach in 24h; stitches hospitalizations `<6h` apart into `encounter_block`; waterfalls available `respiratory_support` rows. Raw IMV is context/QC, not an inclusion requirement. | `hospitalization`, `adt`, `medication_admin_intermittent`, `respiratory_support` | `output/intermediate_phi/step01__*.parquet` (PHI); `output/final_no_phi/step01__*.csv` |
| `02_index_paralytic.py` | Folds paralytic administrations within 15 minutes of one another into index paralytics; publishes the administration-pair and inter-index gap distributions. | `medication_admin_intermittent`, filtered to the paralytics | `output/intermediate_phi/step02__index_paralytic.parquet` (PHI); `step02__*.csv`, paired `fig_A1`, `fig_B1`, `fig_C1` data/PNGs |
| `03_context.py` | For each index paralytic: does the ventilator record show a device transition onto IMV within ±60 min, and was a sedative charted in the same window, at what dose. | `step01__cohort_resp_waterfall.parquet`, `medication_admin_intermittent` filtered to the sedatives | `output/intermediate_phi/step03__index_context.parquet` (PHI); `step03__*.csv`, paired `fig_D1`, `fig_E1`–`fig_E3` data/PNGs |
| `04_covariates.py` | The sole owner of the study's analytic row: one row per index paralytic, carrying the four-way IMV/sedation context category, demographics, DBP and other physiology, device- and agent-specific life support, CLIF ICU type, 24 h SOFA, and block outcomes. | `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `hospital_diagnosis`, `labs`, `patient_assessments`, and re-opens `hospitalization`, `adt`, and respiratory support through `compute_sofa_polars` | `output/intermediate_phi/step04__index_covariates.parquet` (PHI); `step04__sofa_coverage.csv`, `fig_T2__source_coverage.csv` |
| `05_table_one.py` | Table 1, published twice from one row inventory and in two files each: a human-readable CSV and a JSON carrying the long numeric form plus provenance. | nothing — reads `step04__index_covariates.parquet` | stable `table1_by_agent_{block,index}_readable.csv` and `.json`; paired `fig_T1` and `fig_T2` outputs |
| `06_reference_cpt.py` | The CPT `31500` comparator: four mutually exclusive paralytic context categories against a block-level billing flag. Presence only; no date is compared. | `patient_procedures` | paired `fig_F1__cpt_cascade.csv/.png`, `fig_F1__cpt_cascade_qc.csv` |
| `07_artifact_manifest.py` | Rejects stale, missing or undeclared shareable files and records provenance and checksums. | all declared outputs | `artifact_manifest.csv` |

Run individually with `uv run python code/<script>.py`, or all together with
`./run_all.sh` from the repo root (see the top-level [`README.md`](../README.md)).

Every figure dataframe is named `figure_<id>_df`; its CSV and PNG share one
`fig_<ID>__<description>` stem. Supporting outputs use `stepNN__<description>`. The four
Table 1 names remain unchanged for consortium compatibility.

`utils/suppress.py` is the only route into `output/final_no_phi/` — `publish()` for CSV,
`publish_json()` for the aggregation payloads, both refusing to write a frame carrying an
identifier or a datetime column through one shared check. See [`../docs/pipeline_flow.md`](../docs/pipeline_flow.md) §6.

`01` retains the encounter-stitching and waterfall machinery, but cohort eligibility now follows
the paralytic anchor: a qualifying administration is required and a raw IMV row is not.
