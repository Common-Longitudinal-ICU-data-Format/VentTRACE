## Code directory

Three marimo notebooks, run in order by [`../run_all.sh`](../run_all.sh), each named for the
CLIF table it opens rather than for a step number that would drift as the design changes. The
full walkthrough — what each one does, why, and the numbers this run produced — is
[`../docs/pipeline_flow.md`](../docs/pipeline_flow.md); this file is just the map.

| notebook | what it does | reads | writes |
|---|---|---|---|
| `01_cohort.py` | Builds the analytic cohort: adults, ED/ICU, ever-IMV, no trach in 24h; stitches hospitalizations `<6h` apart into `encounter_block`; waterfalls `respiratory_support` into a gap-free device timeline. | `hospitalization`, `adt`, `respiratory_support` | `output/intermediate_phi/cohort_index.parquet`, `cohort_resp_waterfall.parquet` (PHI); `output/final_no_phi/consort_cohort.csv`, `cohort_qc.csv` |
| `02_index_paralytic.py` | Folds paralytic administrations within 15 minutes of one another into index paralytics (the study's index event); publishes the co-administration gap distribution and the gap between index paralytics. | `medication_admin_intermittent`, filtered to the paralytics | `output/intermediate_phi/index_paralytic.parquet` (PHI); several `output/final_no_phi/*.csv` + `figures/` |
| `03_context.py` | For each index paralytic: does the ventilator record show a device transition onto IMV within ±60 min, and was a sedative charted in the same window, at what dose. | `cohort_resp_waterfall.parquet`, `medication_admin_intermittent` filtered to the sedatives | `output/intermediate_phi/index_context.parquet` (PHI); several `output/final_no_phi/*.csv` + `figures/` |

Run individually with `uv run python code/<script>.py`, or all together with
`./run_all.sh` from the repo root (see the top-level [`README.md`](../README.md)).

`utils/suppress.py`'s `publish()` is the only route into `output/final_no_phi/` — every
published table goes through it, and it refuses to write a frame carrying an identifier or a
datetime column. See [`../docs/pipeline_flow.md`](../docs/pipeline_flow.md) §6.

`01`'s cohort logic and the encounter-stitching/waterfall machinery are unchanged from the
pipeline's previous, ventilator-anchored design; `02` and `03` are what changed when the anchor
moved to the paralytic administration.
