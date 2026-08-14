## Code directory

Six marimo notebooks, run in order by [`../run_all.sh`](../run_all.sh), each named for the
CLIF table it opens rather than for a step number that would drift as the design changes. The
full walkthrough — what each one does, why, and the numbers this run produced — is
[`../docs/pipeline_flow.md`](../docs/pipeline_flow.md); this file is just the map.

| notebook | what it does | reads | writes |
|---|---|---|---|
| `01_cohort.py` | Builds the analytic cohort: adults, ED/ICU, ever-IMV, no trach in 24h; stitches hospitalizations `<6h` apart into `encounter_block`; waterfalls `respiratory_support` into a gap-free device timeline. | `hospitalization`, `adt`, `respiratory_support` | `output/intermediate_phi/cohort_index.parquet`, `cohort_resp_waterfall.parquet` (PHI); `output/final_no_phi/consort_cohort.csv`, `cohort_qc.csv` |
| `02_index_paralytic.py` | Folds paralytic administrations within 15 minutes of one another into index paralytics (the study's index event); publishes the co-administration gap distribution and the gap between index paralytics. | `medication_admin_intermittent`, filtered to the paralytics | `output/intermediate_phi/index_paralytic.parquet` (PHI); several `output/final_no_phi/*.csv` + `figures/` |
| `03_context.py` | For each index paralytic: does the ventilator record show a device transition onto IMV within ±60 min, and was a sedative charted in the same window, at what dose. | `cohort_resp_waterfall.parquet`, `medication_admin_intermittent` filtered to the sedatives | `output/intermediate_phi/index_context.parquet` (PHI); several `output/final_no_phi/*.csv` + `figures/` |
| `04_covariates.py` | The sole owner of the study's analytic row: one row per index paralytic, carrying the evidence tier, demographics, comorbidity, physiology and life support in 1/6/24 h look-backs, and block-level LOS and mortality. Everything downstream aggregates this one frame. | `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `hospital_diagnosis`, and re-opens `hospitalization` and `adt` | `output/intermediate_phi/index_covariates.parquet` (PHI); `output/final_no_phi/covariate_coverage.csv` |
| `05_table_one.py` | Table 1, published twice from one row inventory (by encounter block at its first index, and by index event) and in two files each: a human-readable CSV, and a JSON carrying the long numeric form plus a provenance header — for this pipeline, its tests, and cross-site pooling alike. Every row carries its own rule and unit. | nothing — reads `index_covariates.parquet` | `table1_by_agent_{block,index}_readable.csv`, `table1_by_agent_{block,index}.json`, `figures/T1_*.png`, `figures/T2_*.png` |
| `06_reference_cpt.py` | The CPT `31500` comparator: three mutually exclusive evidence tiers against a block-level billing flag. Presence only — one code anywhere in the block means that block has an intubation, and no date is compared. | `patient_procedures` | `cpt_cascade.csv`, `cpt_cascade_qc.csv`, `figures/F1_*.png` |

Run individually with `uv run python code/<script>.py`, or all together with
`./run_all.sh` from the repo root (see the top-level [`README.md`](../README.md)).

`utils/suppress.py` is the only route into `output/final_no_phi/` — `publish()` for CSV,
`publish_json()` for the aggregation payloads, both refusing to write a frame carrying an
identifier or a datetime column through one shared check. See [`../docs/pipeline_flow.md`](../docs/pipeline_flow.md) §6.

`01`'s cohort logic and the encounter-stitching/waterfall machinery are unchanged from the
pipeline's previous, ventilator-anchored design; `02` and `03` are what changed when the anchor
moved to the paralytic administration.
