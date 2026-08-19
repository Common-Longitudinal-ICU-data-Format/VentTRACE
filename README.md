# VentTRACE

**CLIF Version:** 2.1

**clifpy Version:** `>=0.5.0`

A site-run CLIF pipeline for a multi-site study describing the clinical context around paralytic
administrations in hospitalized adults. VentTRACE uses the paralytic administration as the index
event and evaluates nearby invasive mechanical ventilation (IMV) transitions, sedative
administrations, medication doses, organ support, outcomes, and CPT `31500` documentation.

This study is **intubation-adjacent, not intubation-confirming**. A paralytic administration is not
treated as proof that an intubation occurred, and CPT `31500` is a comparator rather than a
reference standard.

## Instructions

Run all commands from the repository root.

### 1. Configure the Site

macOS or Linux:

```bash
cp config/config_template.json config/config.json
```

Windows Command Prompt:

```bat
copy config\config_template.json config\config.json
```

Edit `config/config.json` and replace the site-specific values. In particular, set
`data_directory` to the directory containing the site's CLIF tables; no demo dataset is bundled
with this repository. Confirm the exact dose unit used by the site for all eight study
medications.

```json
{
  "site_name": "Your_Site_Name",
  "data_directory": "C:/path/to/clif/tables",
  "filetype": "parquet",
  "timezone": "US/Eastern",
  "output_directory": "./output",
  "collapse_gap_minutes": 15,
  "imv_window_before_minutes": 30,
  "imv_window_after_minutes": 60,
  "sedation_window_minutes": 5,
  "medication_dose_units": {
    "rocuronium": "mg",
    "succinylcholine": "mg",
    "vecuronium": "mg",
    "midazolam": "mg",
    "etomidate": "mg",
    "ketamine": "mg",
    "propofol": "mg",
    "fentanyl": "mcg"
  },
  "medication_dose_upper_bounds": {
    "rocuronium": 400,
    "succinylcholine": 400,
    "vecuronium": 30,
    "midazolam": 50,
    "etomidate": 200,
    "ketamine": 100,
    "propofol": 500,
    "fentanyl": 500
  },
  "stitch_hours": 6,
  "trach_window_hours": 24,
  "min_age": 18,
  "date_start": "2018-01-01",
  "date_end": "2025-12-31"
}
```

The study-window and dose-bound settings are part of the analysis definition and should not be
changed for a site run unless directed by the study team. Keep `output_directory` set to
`./output` when using the provided launchers. See [`config/README.md`](config/README.md) for
additional configuration notes.

### 2. Install Dependencies

Python is managed with [uv](https://docs.astral.sh/uv/getting-started/installation/). The project
currently requires Python 3.14 or newer.

```bash
uv sync
```

### 3. Run the Pipeline

macOS or Linux:

```bash
./run_all.sh
```

If the executable bit is unavailable, use:

```bash
bash run_all.sh
```

Windows Command Prompt:

```bat
run_all.bat
```

Both launchers run steps 01 through 07 in order, stop at the first failure, and write one log per
step under `output/final_no_phi/logs/run_<UTC timestamp>/`.

To rerun selected steps when their prerequisite intermediates are already current:

```bash
./run_all.sh 02 03
```

```bat
run_all.bat 02 03
```

Selected steps run in the order supplied. The launchers do not resolve dependencies: step 02
requires step 01, step 03 requires steps 01 and 02, and later steps similarly require current
upstream outputs. Run the complete pipeline for a final site submission.

An individual step can also be run directly:

```bash
uv run python code/04_covariates.py
```

### 4. Verify the Code

```bash
uv run pytest
```

### 5. Upload Results to Box

Complete the full pipeline first so step 07 creates and validates
`output/final_no_phi/artifact_manifest.csv`.

1. Confirm that `output/final_no_phi/artifact_manifest.csv` exists and that the pipeline completed
   without an error.
2. Open the study's designated Box folder.
3. In the Box web interface, select **New > Folder Upload** and choose
   `output/final_no_phi/`. If using Box Drive, copy that complete folder into the designated study
   directory.
4. Keep `artifact_manifest.csv`, all aggregate CSV/JSON files, `figures/`, and `logs/` together in
   the upload.

> [!WARNING]
> Upload **only** `output/final_no_phi/`. Do not upload `output/`,
> `output/intermediate_phi/`, source CLIF tables, or row-level extracts. The included `logs/`
> directory can contain encounter-block identifiers. Intermediate files contain identifiers and
> real timestamps. The correct results directory name is `final_no_phi`, not `final_non_phi`.

## Objective

For each qualifying paralytic administration, VentTRACE asks:

1. How are paralytic administrations distributed in time and across medications?
2. How many distinct paralytic-index events occur within an encounter block?
3. Does the respiratory record show a transition onto IMV from 30 minutes before through 60
   minutes after the index event?
4. Was a qualifying sedative administered within 5 minutes before or after the index event, and at
   what dose?
5. What patient characteristics, organ support, outcomes, dose distributions, and CPT coding
   patterns surround these events?

Administrations occurring within 15 minutes of the first administration are folded into one
**index paralytic**. This is an anchor-and-close window, not a chaining window.

## Important: ED or ICU ADT Data Required

The cohort is not restricted to patients admitted directly to an ICU. An encounter block must have
an ADT record with `location_category` equal to `ed` or `icu`. ADT data must include complete
location intervals so the pipeline can identify event-time location, exclude indexes anchored in
procedural locations, calculate ICU length of stay, and identify ICU mortality.

A raw IMV record is **not** required for cohort inclusion. Respiratory support is used to identify
tracheostomy exclusions and characterize whether an IMV transition occurred near the paralytic.

## Required CLIF Tables and Fields

### 1. `hospitalization`

| Column | Description |
|---|---|
| `patient_id` | Unique patient identifier |
| `hospitalization_id` | Unique hospitalization identifier |
| `admission_dttm` | Hospital admission date/time |
| `discharge_dttm` | Hospital discharge date/time |
| `age_at_admission` | Age at admission in years |
| `admission_type_category` | Admission type category |
| `discharge_category` | Discharge disposition, including expired status |

### 2. `adt`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `hospital_id` | Hospital identifier |
| `hospital_type` | Hospital type, used in hospital/year summaries |
| `location_category` | Location category, including `ed`, `icu`, and `procedural` |
| `location_type` | Location subtype, including ICU subtype |
| `in_dttm` | Location entry date/time |
| `out_dttm` | Location exit date/time |

### 3. `respiratory_support`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `recorded_dttm` | Respiratory support record date/time |
| `device_category` | Respiratory device category, including `imv` and `trach collar` |
| `device_name` | Source respiratory device name |
| `mode_category` | Standardized ventilation mode category |
| `mode_name` | Source ventilation mode name |
| `tracheostomy` | Tracheostomy indicator |
| `fio2_set` | Set FiO2 |
| `lpm_set` | Set oxygen flow in liters per minute |
| `peep_set` | Set PEEP |
| `tidal_volume_set` | Set tidal volume |
| `resp_rate_set` | Set respiratory rate |
| `resp_rate_obs` | Observed respiratory rate |
| `pressure_support_set` | Set pressure support |
| `peak_inspiratory_pressure_set` | Set peak inspiratory pressure |

These fields support the `clifpy` respiratory waterfall and SOFA calculation. The table itself is
required, but a qualifying encounter may have no respiratory rows and will then be reported as
having no device record.

### 4. `medication_admin_intermittent`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `admin_dttm` | Medication administration date/time |
| `med_category` | Standardized medication category |
| `mar_action_category` | MAR action category |
| `med_dose` | Administered dose |
| `med_dose_unit` | Administered dose unit |

**Required paralytic categories:** `rocuronium`, `succinylcholine`, `vecuronium`

**Required sedative categories:** `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl`

Only administrations with `mar_action_category == "given"`, the medication's exact configured dose
unit, a finite positive dose, and the configured dose plausibility rule enter the analysis.

### 5. `patient`

| Column | Description |
|---|---|
| `patient_id` | Unique patient identifier |
| `sex_category` | Sex category |
| `race_category` | Race category |
| `ethnicity_category` | Ethnicity category |
| `death_dttm` | Date/time of death, when available |

### 6. `patient_procedures`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `procedure_code` | Procedure code |
| `procedure_code_format` | Procedure code format |
| `procedure_billed_dttm` | Procedure billing date/time required by the CLIF schema |

The pipeline checks for CPT `31500` anywhere in the encounter block. The billing date is read
because it is required by the CLIF 2.1 schema, but no date alignment is performed.

## Optional CLIF Tables and Fields

The pipeline runs without the following tables. Missing optional inputs are reported through
coverage outputs rather than interpreted as confirmed absence of the clinical condition. Missing
SOFA components receive the `clifpy` default component score of 0, while
`step04__sofa_coverage.csv` reports component availability.

### 7. `medication_admin_continuous`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `admin_dttm` | Administration date/time |
| `med_category` | Standardized medication category |
| `med_dose` | Dose used by SOFA when available |
| `med_dose_unit` | Dose unit used by SOFA when available |

Table 1 vasopressor categories include `norepinephrine`, `vasopressin`, `epinephrine`,
`phenylephrine`, and `dopamine`.

### 8. `crrt_therapy`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `recorded_dttm` | CRRT record date/time |

### 9. `vitals`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `recorded_dttm` | Vital sign date/time |
| `vital_category` | Standardized vital sign category |
| `vital_value` | Vital sign value |

Used categories include `sbp`, `dbp`, `map`, `heart_rate`, `spo2`, and `weight_kg`. Supported
aliases such as `HeartRate`, `weightKg`, and `SpO2` are normalized before analysis.

### 10. `hospital_diagnosis`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `diagnosis_code` | ICD diagnosis code |
| `diagnosis_code_format` | Diagnosis code format |

Used to calculate the Charlson Comorbidity Index. Format values are normalized
case-insensitively after loading, so `ICD10CM` and `icd10cm` are equivalent.

### 11. `labs`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `lab_result_dttm` | Lab result date/time |
| `lab_category` | Standardized lab category |
| `lab_value` | Source lab value |
| `lab_value_numeric` | Numeric lab value |

**SOFA categories:** `creatinine`, `platelet_count`, `po2_arterial`, `bilirubin_total`

### 12. `patient_assessments`

| Column | Description |
|---|---|
| `hospitalization_id` | Unique hospitalization identifier |
| `recorded_dttm` | Assessment date/time |
| `assessment_category` | Standardized assessment category |
| `numerical_value` | Numeric assessment value |
| `categorical_value` | Categorical assessment value |

**SOFA category:** `gcs_total`

The `position` table is not read; proning is not part of this study.

## Cohort Identification

The base cohort is defined by the following criteria:

1. **Age:** at least 18 years at the first hospitalization in the encounter block.
2. **Time period:** block admission falls within the configured inclusive `date_start` and
   `date_end` timestamp bounds. The template uses `2018-01-01` and `2025-12-31`. This calendar
   filter is skipped when `site_name` is `mimic` because MIMIC timestamps are date-shifted.
3. **Location:** at least one ADT interval is categorized as `ed` or `icu`.
4. **Paralytic exposure:** at least one qualifying `rocuronium`, `succinylcholine`, or `vecuronium`
   administration occurs in the encounter block.
5. **Tracheostomy exclusion:** no tracheostomy indicator or `trach collar` record occurs from block
   admission through 24 hours after admission.

Hospitalizations for the same patient separated by no more than 6 hours are stitched into an
`encounter_block`, the analytic unit used throughout the pipeline.

Within the cohort:

- Qualifying paralytic administrations are folded into index events using the configured
  15-minute anchor-and-close window.
- Formed indexes anchored within an ADT `procedural` interval are excluded.
- IMV transition status is evaluated in the inclusive window from 30 minutes before through 60
  minutes after the index.
- Sedation status is evaluated in the inclusive 5-minute window on either side of the index.
- Valid-index Table 1 analyses require both an IMV transition and a qualifying sedative.
- Pre-index organ-support covariates use inclusive 1-, 6-, and 24-hour lookback windows.

## Expected Results

The paths below use the template's `output_directory` value, `./output`. Keep this default when
using `run_all.sh` or `run_all.bat`; both launchers place logs and report the final file count
under `output/`.

| Output | Description |
|---|---|
| `final_no_phi/fig_1__main_consort.csv` and `final_no_phi/figures/fig_1__main_consort.png` | Main flow from qualifying administrations through the valid-index Table 1 populations |
| `final_no_phi/table1_by_agent_block_readable.csv` | Human-readable Table 1 using one first-valid index per encounter block |
| `final_no_phi/table1_by_agent_index_readable.csv` | Human-readable Table 1 using all valid index events |
| `final_no_phi/table1_by_agent_block.json` | Numeric block-level Table 1 payload for cross-site aggregation |
| `final_no_phi/table1_by_agent_index.json` | Numeric index-level Table 1 payload for cross-site aggregation |
| `final_no_phi/step01__*.csv` through `step04__*.csv` | Cohort, medication, context, coverage, dose, and hospital/year summaries |
| `final_no_phi/fig_A1__*.csv` through `fig_T2__*.csv` | Auditable aggregate data used to draw each figure |
| `final_no_phi/figures/` | PNG figures with stems matching their source CSV files |
| `final_no_phi/logs/` | Timestamped console logs for each pipeline step; not inventoried by the artifact manifest |
| `final_no_phi/artifact_manifest.csv` | Producer, dataframe, sources, row count, size, and SHA-256 for each shareable artifact |

Step 04 includes hospital/year trends, weight-normalized dose ECDFs, etomidate/ketamine
percentiles, local dose tiers and five-bin plots, valid-index dose summaries by clinical strata,
valid-index dose bins, and a dose-specific eligibility flow. Site percentiles must not be averaged;
the published integer numerators and denominators support later consortium aggregation.

Protected row-level intermediates are written to `output/intermediate_phi/` and are not a study
deliverable. Run logs are written inside `output/final_no_phi/logs/`.

## Pipeline Steps

| Step | Script | Description |
|---|---|---|
| 1 | `code/01_cohort.py` | Builds the adult ED/ICU paralytic cohort, stitches encounter blocks, applies the early-tracheostomy exclusion, and waterfalls respiratory support |
| 2 | `code/02_index_paralytic.py` | Forms 15-minute paralytic indexes, excludes procedural-location anchors, and summarizes administration and inter-index gaps |
| 3 | `code/03_context.py` | Identifies nearby IMV transitions and sedative administrations and publishes timing and dose summaries |
| 4 | `code/04_covariates.py` | Adds demographics, outcomes, organ support, CCI, SOFA, dose/weight analyses, strata, and hospital/year trends |
| 5 | `code/05_table_one.py` | Produces the main CONSORT, block- and index-level Table 1 outputs, and organ-support/source-coverage figures |
| 6 | `code/06_reference_cpt.py` | Compares first-index context categories with block-level CPT `31500` presence |
| 7 | `code/07_artifact_manifest.py` | Validates declared shareable outputs and writes their provenance and checksums |

See [`code/README.md`](code/README.md) for the per-step input/output map and
[`docs/pipeline_flow.md`](docs/pipeline_flow.md) for the full analytic walkthrough and disclosure
boundary.
