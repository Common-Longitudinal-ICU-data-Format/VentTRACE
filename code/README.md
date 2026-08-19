## Code directory

Six marimo notebooks plus one artifact-audit step, run in order by
[`../run_all.sh`](../run_all.sh), each named for the
CLIF table it opens rather than for a step number that would drift as the design changes. The
full walkthrough — what each one does, why, and the numbers this run produced — is
[`../docs/pipeline_flow.md`](../docs/pipeline_flow.md); this file is just the map.

| notebook | what it does | reads | writes |
|---|---|---|---|
| `01_cohort.py` | Builds the analytic cohort: adults, ED/ICU, at least one qualifying paralytic administration, no trach in 24h; stitches hospitalizations `<6h` apart into `encounter_block`; incrementally caches and waterfalls only required `respiratory_support` hospitalizations. Raw IMV is context/QC, not an inclusion requirement. | `hospitalization`, `adt`, `medication_admin_intermittent`, `respiratory_support` | `output/intermediate_phi/step01__*.parquet` and resumable waterfall cache (PHI); `output/final_no_phi/step01__*.csv` |
| `02_index_paralytic.py` | Folds paralytic administrations within 15 minutes, excludes formed indexes whose ADT anchor location is procedural, and publishes the administration-pair and retained inter-index gap distributions. | `medication_admin_intermittent`, filtered to the paralytics; `adt` | `output/intermediate_phi/step02__index_paralytic.parquet` (PHI); `step02__*.csv`, paired `fig_A1`, `fig_B1`, `fig_C1` data/PNGs |
| `03_context.py` | For each index paralytic: does the ventilator record show a device transition onto IMV from 30 min before through 60 min after, and was a sedative charted within configured ±5 min, at what dose; D.2 separately plots the nearest transition within ±6 h. | `step01__cohort_resp_waterfall.parquet`, `medication_admin_intermittent` filtered to the sedatives | `output/intermediate_phi/step03__index_context.parquet` (PHI); `step03__*.csv`, paired `fig_D1`–`fig_D2`, `fig_E1`–`fig_E3` data/PNGs |
| `04_covariates.py` | Owns the analytic row, including source-administration and post-merge lineage; block-first hospital/year counts and trends; the separate corrected 28-day dose-weight selector; normalized ECDFs; induction percentiles/tiers; and their eligibility flow. | `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `hospital_diagnosis`, `labs`, `patient_assessments`, and re-opens `hospitalization`, `adt`, and respiratory support through `compute_sofa_polars` | `output/intermediate_phi/step04__index_covariates.parquet` (PHI); `step04__*.csv`, paired `fig_B2`, `fig_E4`, `fig_E5`, `fig_G1`, `fig_H1`, and `fig_T2` data/PNGs |
| `05_table_one.py` | Builds Figure 1, the main CONSORT from qualifying paralytic administrations through Table 1; then publishes all valid events and one first-valid event per block in a human-readable CSV and aggregation JSON. | nothing — reads `step04__index_covariates.parquet` | paired `fig_1__main_consort.csv/.png`; stable `table1_by_agent_{block,index}_readable.csv` and `.json`; paired `fig_T1` and `fig_T2` outputs |
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
