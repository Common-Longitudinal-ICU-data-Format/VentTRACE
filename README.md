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
3. Does the ventilator record show a transition onto invasive ventilation from 30 minutes before
   through 60 minutes after the index — a device *change*, not merely "was IMV charted"?
4. Was a sedative charted within the configured ±5-minute sedation window, and at what dose?

This is **intubation-adjacent, not intubation-confirming** — the study describes what surrounds a
paralytic, and does not adjudicate whether an intubation occurred.

## Required CLIF tables and fields

1. **hospitalization**: `patient_id`, `hospitalization_id`, `admission_dttm`, `age_at_admission`
2. **adt**: `hospitalization_id`, `hospital_id`, `hospital_type`, `location_category`,
   `location_type`, `in_dttm`, `out_dttm`
3. **respiratory_support**: `hospitalization_id`, `recorded_dttm`, `device_category`,
   `tracheostomy`, and the fields `clifpy`'s waterfall needs to infer device from ventilator
   settings
4. **medication_admin_intermittent**: `hospitalization_id`, `admin_dttm`, `med_category`,
   `mar_action_category`, `med_dose`, `med_dose_unit` — filtered to the paralytics
   (`rocuronium`, `succinylcholine`, `vecuronium`) and the sedatives (`midazolam`, `etomidate`,
   `ketamine`, `propofol`, `fentanyl`)
5. **patient**: `patient_id`, `sex_category`, `race_category`, `ethnicity_category`, `death_dttm`
6. **patient_procedures**: `hospitalization_id`, `procedure_code`, `procedure_code_format`,
   `procedure_billed_dttm`. Required procedure code: `31500` (endotracheal intubation). The
   comparison is **presence within the encounter block** — one `31500` on any member
   hospitalization means that block has an intubation. No date is compared;
   `procedure_billed_dttm` is read only because the CLIF 2.1 schema marks it required. It is a
   comparator, not a reference standard — see the design's P26.
7. **medication_admin_continuous** *(optional — the pipeline runs without it and publishes 0%
   coverage)*: `hospitalization_id`, `admin_dttm`, `med_category`
8. **crrt_therapy** *(optional — the pipeline runs without it and publishes 0% coverage)*:
   `hospitalization_id`, `recorded_dttm`
9. **vitals** *(optional — the pipeline runs without it and publishes 0% coverage)*:
   `hospitalization_id`, `recorded_dttm`, `vital_category`, `vital_value`
10. **hospital_diagnosis** *(optional — the pipeline runs without it and publishes 0% coverage)*:
     `hospitalization_id`, `diagnosis_code`, `diagnosis_code_format`. Format values are normalized
     case-insensitively after loading, so `ICD10CM` and `icd10cm` both contribute to clifpy CCI.
11. **labs** *(optional SOFA input; missing component scores default to 0)*: creatinine,
    platelet count, arterial PaO2, and total bilirubin
12. **patient_assessments** *(optional SOFA input; missing component scores default to 0)*:
    `gcs_total`

`position` is **not** read. Proning was withdrawn from the covariate set on 2026-08-14 at the
study lead's direction; a site does not need the table and its absence is not reported.

`patient` and `patient_procedures` are required; `medication_admin_continuous`, `crrt_therapy`,
`vitals`, `hospital_diagnosis`, `labs`, and `patient_assessments` are optional. Missing SOFA
component scores default to 0, while `step04__sofa_coverage.csv` publishes component availability.
`04_covariates.py` also re-opens
`hospitalization` and `adt`, already required above; that is no new contract. See
[`docs/pipeline_flow.md`](docs/pipeline_flow.md) §2 for the full per-notebook table map.

Every source `*_category` value is stripped and lower-cased before filtering, matching, joining,
or grouping. Thus `IMV`, `imv`, and ` IMV ` are equivalent. Standard `from_file` calls filter
categories only after loading the cohort IDs so exact loader filters cannot discard a site's casing;
the initial whole-site medication scan uses an equivalent normalized DuckDB pushdown. Supported
vital aliases such as `HeartRate`, `weightKg`, and `SpO₂` are also mapped to their canonical CLIF
names. Before `compute_sofa_polars` rereads its five source tables, step 04 stages cohort-scoped
temporary parquet inputs with the same canonical categories.

## Cohort identification

Adults (≥18 at admission), ED or ICU at some point in the stay, at least one qualifying
rocuronium, succinylcholine, or vecuronium administration (`given` with the medication's
exact `medication_dose_units` config value),
and no tracheostomy signal in the first 24 hours. A raw IMV row is not required because a patient
who dies immediately after intubation may never have one charted. Hospitalizations less than 6
hours apart for the same patient are stitched into one `encounter_block`, the analytic unit for
the whole pipeline. See [`docs/pipeline_flow.md`](docs/pipeline_flow.md) §3 for the full funnel.

## Expected results

Aggregate counts, rates, quantiles and figures — never a row-level record — written to
`output/final_no_phi/`. That directory, and only that directory, is what a site shares with the
project PI / consortium.

Figure data and PNGs use the same auditable stem, for example
`fig_E2__sedation_dose_summary.csv` and
`figures/fig_E2__sedation_dose_summary.png`. Other outputs begin with their producer step,
for example `step03__sedation_summary.csv`. `artifact_manifest.csv` records each artifact's
producer, dataframe, sources, row count, size and SHA-256. The four `table1_by_agent_*` names
remain stable for cross-site pooling.

`fig_1__main_consort.csv` and its same-stem PNG are the main analysis. They trace qualifying
paralytic administrations through index formation, IMV transition, sedation, and the index- and
block-level Table 1 populations. All lettered analyses are downstream subanalyses.

Step 04 also publishes block-first paralytic-index event counts by healthcare system, event-time
hospital, academic status, and year. These are intubation-adjacent operational counts, not confirmed
intubations. Weight-normalized dose ECDFs, etomidate/ketamine percentiles, local four-tier counts,
and a dose-specific eligibility flow are additive outputs. Tier files carry site-level integer
numerators and denominators for later consortium meta-analysis; site percentiles are never averaged.

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
   ./run_all.sh            # 01_cohort -> ... -> 07_artifact_manifest, in order
   ./run_all.sh 02 03      # or just a subset of steps
   ```
   Each run is logged to `output/logs/run_<UTC timestamp>/`. Results land in
   `output/final_no_phi/`; figures in `output/final_no_phi/figures/`.

4. **Verify.**
   ```
   uv run pytest
   ```

`code/README.md` has a short per-notebook description of what `01` through `06` each do.
