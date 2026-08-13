# VentTRACE

A single-site CLIF pipeline studying what surrounds a paralytic administration during intubation
in the ICU. Full walkthrough of what each notebook does and why:
[`docs/pipeline_flow.md`](docs/pipeline_flow.md). Authoritative design decisions:
[`docs/superpowers/specs/2026-08-10-paralytic-index-design.md`](docs/superpowers/specs/2026-08-10-paralytic-index-design.md).

## CLIF VERSION

Built and tested against `clifpy>=0.5.0` (see [`pyproject.toml`](pyproject.toml)), mCIDE
categories current as of 2026-08.

## Objective

The paralytic administration — not a ventilator record or a billing code — is the index event.
For every paralytic administration (folded into a single **index paralytic** when several land
within 15 minutes of one another), the study asks:

1. How are paralytic administrations distributed in time relative to one another?
2. How many distinct index paralytic events does a hospitalization have, and how far apart are
   they?
3. Does the ventilator record show a transition onto invasive ventilation within ±60 minutes of
   the index paralytic — a device *change*, not merely "was IMV charted"?
4. Was a sedative charted in the same ±60 minutes, and at what dose?

This is **intubation-adjacent, not intubation-confirming** — the study describes what surrounds a
paralytic, and does not adjudicate whether an intubation occurred.

## Required CLIF tables and fields

1. **hospitalization**: `patient_id`, `hospitalization_id`, `admission_dttm`, `age_at_admission`
2. **adt**: `hospitalization_id`, `location_category` (ED / ICU presence)
3. **respiratory_support**: `hospitalization_id`, `recorded_dttm`, `device_category`,
   `tracheostomy`, and the fields `clifpy`'s waterfall needs to infer device from ventilator
   settings
4. **medication_admin_intermittent**: `hospitalization_id`, `admin_dttm`, `med_category`,
   `mar_action_category`, `med_dose`, `med_dose_unit` — filtered to the paralytics
   (`rocuronium`, `succinylcholine`, `vecuronium`) and the sedatives (`midazolam`, `etomidate`,
   `ketamine`, `propofol`, `fentanyl`)
5. **patient**: `patient_id`, `sex_category`, `race_category`, `ethnicity_category`, `death_dttm`
6. **patient_procedures**: `hospitalization_id`, `procedure_code`, `procedure_code_format`,
   `procedure_billed_dttm`. Required procedure code: `31500` (endotracheal intubation). It is a
   comparator, not a reference standard — see the design's P26.
7. **medication_admin_continuous** *(optional — the pipeline runs without it and publishes 0%
   coverage)*: `hospitalization_id`, `admin_dttm`, `med_category`
8. **crrt_therapy** *(optional — the pipeline runs without it and publishes 0% coverage)*:
   `hospitalization_id`, `recorded_dttm`
9. **position** *(optional — the pipeline runs without it and publishes 0% coverage)*:
   `hospitalization_id`, `recorded_dttm`, `position_category`
10. **vitals** *(optional — the pipeline runs without it and publishes 0% coverage)*:
    `hospitalization_id`, `recorded_dttm`, `vital_category`, `vital_value`
11. **hospital_diagnosis** *(optional — the pipeline runs without it and publishes 0% coverage)*:
    `hospitalization_id`, `diagnosis_code`, `diagnosis_code_format`

`patient` and `patient_procedures` are required; `medication_admin_continuous`, `crrt_therapy`,
`position`, `vitals` and `hospital_diagnosis` are optional — absent, their derived columns are
null and `covariate_coverage.csv` publishes 0% for them. `04_covariates.py` also re-opens
`hospitalization` and `adt`, already required above; that is no new contract. See
[`docs/pipeline_flow.md`](docs/pipeline_flow.md) §2 for the full per-notebook table map.

## Cohort identification

Adults (≥18 at admission), ED or ICU at some point in the stay, at least one raw charted
`device_category == 'imv'` row, no tracheostomy signal in the first 24 hours. Hospitalizations
less than 6 hours apart for the same patient are stitched into one `encounter_block`, the
analytic unit for the whole pipeline. See [`docs/pipeline_flow.md`](docs/pipeline_flow.md) §3 for
the full CONSORT funnel.

## Expected results

Aggregate counts, rates, quantiles and figures — never a row-level record — written to
`output/final_no_phi/`. That directory, and only that directory, is what a site shares with the
project PI / consortium.

> [!WARNING]
> **Never upload patient-level data to Box.** Only `output/final_no_phi/` may be shared — no
> `patient_id`, no raw timestamp, nothing that describes one person. `output/intermediate_phi/`
> and `output/logs/` are row-level or PHI-adjacent and never leave the site — see
> [`docs/pipeline_flow.md`](docs/pipeline_flow.md) §6 and [`guides/primer.md`](guides/primer.md)
> for the full data-security rules.

## Running the pipeline

1. **Configure.**
   ```
   cp config/config_template.json config/config.json
   ```
   Then edit `config/config.json` — site name, path to your CLIF tables, file type, timezone.
   See [`config/README.md`](config/README.md).

2. **Install dependencies** (Python via [uv](https://docs.astral.sh/uv/getting-started/installation/)):
   ```
   uv sync
   ```

3. **Run.**
   ```
   ./run_all.sh            # 01_cohort -> ... -> 06_reference_cpt, in order
   ./run_all.sh 02 03      # or just a subset of steps
   ```
   Each run is logged to `output/logs/run_<UTC timestamp>/`. Results land in
   `output/final_no_phi/`; figures in `output/final_no_phi/figures/`.

4. **Verify.**
   ```
   uv run pytest
   ```

`code/README.md` has a short per-notebook description of what `01` through `06` each do.
