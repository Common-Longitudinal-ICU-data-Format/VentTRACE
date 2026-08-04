# Intubation Detection Method Comparison — Design

**Project:** VentTRACE
**Date:** 2026-08-04
**Status:** Design, approved for planning
**Companion document:** [`docs/intubation_extubation_methods.md`](../../intubation_extubation_methods.md) — the methods catalog that motivated this build

---

## 1. Purpose

The methods catalog established that intubation detection definitions disagree, and quantified that disagreement for one signal source only: the `device_category` transition rule (M1–M4). This project measures a **second, orthogonal axis** — the *signal source* itself.

Four candidate signals are compared head to head on the same patients at the same moment:

| ID | Signal | Whiteboard item |
|---|---|---|
| `SED` | Intermittent sedative/induction agent administration | (0) |
| `PARA` | Intermittent paralytic administration | (1) |
| `DEV` | `device_category` transition non-IMV → IMV | (2) |
| `INF` | Continuous sedation infusion start | (3) |

Two further sources serve as a **partial gold-truth reference**, not as compared methods:

| ID | Signal | Whiteboard item |
|---|---|---|
| `CPT` | CPT 31500 present in the hospitalization | (c1) |
| `ICD` | ICD-9/ICD-10-PCS intubation or mechanical-ventilation code present | (s) |

The deliverable answers two questions: **do these signals identify the same patients**, and **how is their charting distributed in time relative to the intubation**.

### Scope

- **Intubation only.** Extubation is out of scope for this build; the catalog already covers it and it can be a later phase.
- **First IMV episode only.** One index event per hospitalization. Reintubation, episode stitching, and outcome classification are out of scope.
- **Testing target is MIMIC**, with the pipeline written to run at any consortium site via config.

---

## 2. Decisions

Each decision below was made explicitly during design. Recorded with rationale so the choice is auditable and reversible.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Six signals: four methods under test, two reference sources.** CPT and ICD do not enter the agreement matrix. | Catalog §12.2 establishes procedure codes confirm *presence* but never *timing*, and their capture rate varies by site, payer and era. They cannot be peers to a timestamped signal. |
| D2 | **Device signal is one notebook using the M2 symmetric 2/2 rule**, not four notebooks for M1–M4. | The M1–M4 spread is already quantified in the catalog. Re-running it here would measure a known result and obscure the new one. |
| D3 | **Analytic unit is one row per hospitalization**, anchored on t₀ = first charted IMV row. | Collapses event matching entirely: no greedy pairing, no order-dependence, no tolerance windows. Agreement becomes a plain binary table; timing becomes offset distributions on a shared axis. |
| D4 | **Detection window is t₀ ± 3 hours**, symmetric. | Set by the study lead. Every method asks the same question over the same interval, so differences are attributable to the signal and not to the window. |
| D5 | **Respiratory pre-processing is fixed: post-waterfall, single policy.** No pre/post grid. | Catalog §12.4 requires the policy be settled before methods are compared. Fixing it in one place makes the agreement numbers mean exactly one thing; changing it later is a config edit, not a rewrite. |
| D6 | **Waterfall runs with `bfill=False`.** | `clifpy/utils/waterfall.py:12` — already the library default; `:58` confirms forward-fill only when False. Backfilling could propagate a device backwards in time and manufacture an IMV row earlier than the first real charting, sliding t₀ and with it all four ±3h windows. |
| D7 | **No CPT code and no `billing_provider_id` in the cohort definition.** | Explicit study requirement. Distinguishes this cohort from `Induction_Variability_RSI`, which requires both. Codes enter only as the reference in notebook `06`. |
| D8 | **Every method notebook is fully self-contained. No shared helper module.** | A bug in a shared helper corrupts all four methods *identically*, and correlated errors are indistinguishable from genuine agreement — the one failure mode an agreement study cannot tolerate. Isolation makes mistakes surface as disagreement (visible) rather than as inflated concordance (invisible). |
| D9 | **The detection window is data, not code.** `01_cohort.py` writes `window_start` / `window_end` into `cohort_index.parquet`. | Removes the usual cost of D8. There is no window logic to duplicate across four notebooks, so there is nothing to drift, while detection logic stays fully independent. |
| D10 | **Medication lists taken as written on the source whiteboard**, including fentanyl appearing in both `SED` and `INF`. | Deliberate. `SED` is expected to fire often because midazolam and fentanyl are given for many non-airway reasons; that low specificity is a reportable property of the method, not a defect to be tuned away before measurement. |

---

## 3. Architecture

```
code/
  01_cohort.py            cohort + CONSORT + waterfall + t₀ + window bounds
  02_method_sedative.py   ┐
  03_method_paralytic.py  │  each fully self-contained:
  04_method_device.py     │  config → cohort_index + ONE CLIF table
  05_method_infusion.py   ┘  → own logic → 2 parquets → assert own schema
  06_reference_codes.py   CPT 31500 + ICD codes
  07_agreement.py         schema gatekeeper + agreement + distributions
```

The only things crossing a notebook boundary are **parquet artifacts** and the **schema contract in §6**. `07_agreement.py` validates the schema of every input on load and fails loudly rather than silently mis-joining.

All notebooks are marimo notebooks stored as `.py`, run as `uv run python code/NN_name.py`, matching the existing consortium convention.

**Dataframe library:** polars throughout, per the root `pyproject.toml`. `process_resp_support_waterfall` takes a pandas DataFrame, so `01_cohort.py` converts to pandas immediately before that call and back to polars immediately after. That is the only pandas boundary in the project.

---

## 4. Implementation constraints

The code must be readable by a clinician-researcher reviewing the definition, not only by its author. These are requirements, not preferences.

- **One logical step per marimo cell**, with a markdown cell above it stating what the step does in plain language.
- **No helper functions across notebooks**, and inside a notebook only where a step is genuinely repeated. Prefer an explicit repeated expression over an abstraction that hides the definition being tested.
- **Name intermediate columns explicitly** rather than chaining long expressions. A reviewer must be able to inspect `is_in_window`, `is_target_med`, `offset_minutes` as real columns.
- **No clever vectorisation** where a plain filter and join expresses the same thing. Cohort sizes are small enough that clarity wins over speed.
- **Every filter prints its row and hospitalization count** before and after, so the CONSORT and the method yields are visible while running, not only in the final artifact.
- **Each method notebook ends with an explicit schema assertion block** against §6. Copy-pasted deliberately across the four — duplication here is the point of D8.
- **No silent defaults.** Every parameter that affects a result is read from `config.json` and echoed at the top of the notebook.

---

## 5. Cohort and CONSORT — `01_cohort.py`

### Inclusion, applied in this order

```
  all hospitalizations                                      N
    └─ age_at_admission ≥ 18                              −n₁
        └─ date filter (skipped when site is MIMIC)       −n₂
            └─ ≥1 ADT row with location_category = 'icu'  −n₃
                └─ ≥1 resp row with device_category='imv' −n₄
                    └─ ANALYTIC COHORT                     N*
```

Order matters: the CONSORT reports the marginal loss at each step in this sequence, so the sequence is part of the definition.

### Date filter

`site_name.lower() == "mimic"` → **no date restriction** (MIMIC timestamps are date-shifted, so a calendar filter is meaningless).
Otherwise → `admission_dttm` within `date_start` … `date_end`, default `2018-01-01` … `2025-12-31`.

### Waterfall and t₀

1. Subset `respiratory_support` to cohort hospitalizations.
2. Run `process_resp_support_waterfall(..., bfill=False)`.
3. **t₀ = earliest `recorded_dttm` where `device_category == 'imv'`**, per hospitalization.
4. `window_start = t₀ − 3h`, `window_end = t₀ + 3h`.

### QC statistic

Report `Δ = waterfall_t₀ − raw_t₀` (median, IQR, % nonzero). D6 makes a negative Δ very unlikely, but the device/mode heuristics and the hourly `HH:59:59` scaffold run regardless of `bfill`, so this is cheap insurance that t₀ still corresponds to real charting. A nonzero negative Δ in any meaningful fraction of the cohort invalidates the offset distributions and must be investigated before results are interpreted.

### Outputs

| File | Contents |
|---|---|
| `cohort.parquet` | one row per included hospitalization, with demographics |
| `cohort_resp_waterfall.parquet` | waterfalled respiratory rows for cohort hospitalizations |
| `cohort_index.parquet` | `hospitalization_id`, `t0_dttm`, `window_start`, `window_end` |
| `consort.json` / `consort.csv` | step label, n remaining, n excluded |

---

## 6. Method contract

Every method notebook emits exactly two files with identical schemas across methods.

**`method_<ID>_signals.parquet`** — long format, one row per signal found in the window. This table is what produces the charting-distribution plots.

| Column | Type | Notes |
|---|---|---|
| `hospitalization_id` | str | |
| `method_id` | str | one of `SED`, `PARA`, `DEV`, `INF` |
| `signal_dttm` | datetime | |
| `offset_minutes` | float | signed, `signal_dttm − t₀`; negative = before intubation |
| `signal_detail` | str | `med_category`, or the device transition type for `DEV` |

**`method_<ID>_encounter.parquet`** — one row per **cohort** hospitalization, including non-detections.

| Column | Type | Notes |
|---|---|---|
| `hospitalization_id` | str | |
| `method_id` | str | |
| `detected` | bool | |
| `n_signals` | int | 0 when not detected |
| `first_signal_dttm` | datetime | null when not detected |
| `nearest_signal_dttm` | datetime | signal closest to t₀; null when not detected |
| `first_offset_min` | float | null when not detected |
| `nearest_offset_min` | float | null when not detected |
| `non_detection_reason` | str | null when detected. Only `DEV` populates this; the medication methods always write null. |

Non-detections are retained as `detected = false` rows. They are the denominator for every rate in §8. The `_signals` table contains **only** signals that were found — a hospitalization with `detected = false` has no rows there at all, which is why the non-detection reason lives on the encounter table.

---

## 7. Method definitions

All four evaluate against `cohort_index.parquet` and are restricted to the window `[window_start, window_end]`.

### `SED` — `02_method_sedative.py`

Source: `medication_admin_intermittent`.
Fires on any administration with `mar_action_category = 'given'` and `med_category` in:

```
etomidate | ketamine | midazolam | fentanyl
```

`signal_detail` = the `med_category` that fired.

### `PARA` — `03_method_paralytic.py`

Source: `medication_admin_intermittent`.
Fires on any administration with `mar_action_category = 'given'` and `med_category` in:

```
rocuronium | succinylcholine | vecuronium
```

`signal_detail` = the `med_category` that fired.

### `DEV` — `04_method_device.py`

Source: `cohort_resp_waterfall.parquet`.
Fires when t₀ is a **documented non-IMV → IMV transition** under the M2 symmetric 2/2 rule. Writing t₀ as row index `i` within the hospitalization's waterfalled rows ordered by `recorded_dttm`:

```
   DEV fires  ≡  ¬IMV(i-2) ∧ ¬IMV(i-1) ∧ IMV(i) ∧ IMV(i+1)
```

**Boundary policy is `B_strict`** — if row `i-2`, `i-1` or `i+1` does not exist, the corresponding term is false and `DEV` does not fire. This matches the convention the catalog applies to M2 in §3.1 and is stated here rather than inherited from language semantics.

`signal_dttm` = t₀, so `offset_minutes` = 0 by construction. `DEV` therefore contributes to the binary agreement table in §8 Tier A but **not** to the offset distributions in Tier B.

When it fires, `signal_detail` = `documented_transition`. When it does not, `non_detection_reason` on the encounter table takes the first applicable value:

| Reason | Condition |
|---|---|
| `arrived_intubated` | t₀ is the hospitalization's first respiratory row |
| `insufficient_lookback` | fewer than two rows precede t₀ |
| `imv_not_sustained` | row `i+1` is absent or non-IMV |
| `prior_row_imv` | row `i-1` or `i-2` exists but is IMV |

> **What `DEV` actually measures.** Anchored on t₀, this method reports the fraction of the cohort whose pre-intubation period was documented at all — catalog §9.4, the arrived-intubated rate. A low `DEV` detection rate means the medication methods are firing on intubations whose device transition was never charted. That is a finding about site charting, not a failure of the method.

### `INF` — `05_method_infusion.py`

Source: `medication_admin_continuous`.
Fires when a continuous infusion **starts** within the window, with `med_category` in:

```
propofol | dexmedetomidine | fentanyl
```

**An infusion start is defined explicitly**, since `medication_admin_continuous` records repeated rate rows rather than start events: a row is an infusion start if, within the same hospitalization and the same `med_category`, either no earlier row exists, or the immediately preceding row is more than `infusion_gap_hours` earlier. Default `infusion_gap_hours = 6`, read from config.

This rule matters. Defining the start as simply the *first* row of that `med_category` in the hospitalization would systematically miss any patient already receiving that agent for an unrelated reason before intubation — a common pattern for dexmedetomidine and fentanyl.

`signal_dttm` = that start time. `signal_detail` = the `med_category`.

---

## 8. Reference and agreement

### `06_reference_codes.py`

Source: `patient_procedures` — `procedure_code`, `procedure_code_format`, `procedure_billed_dttm`. **`billing_provider_id` is not read.** Presence anywhere in the hospitalization; no timing use, per catalog §12.2.

| Reference | Format | Codes |
|---|---|---|
| `CPT` | CPT | `31500` |
| `ICD` | ICD-10-PCS | `0BH17EZ`, `0BH18EZ` (endotracheal airway insertion) |
| `ICD` | ICD-10-PCS | `5A1935Z`, `5A1945Z`, `5A1955Z` (mechanical ventilation <24h / 24–96h / >96h) |
| `ICD` | ICD-9 | `9604` (endotracheal tube insertion) |
| `ICD` | ICD-9 | `9670`, `9671`, `9672` (continuous mechanical ventilation) |

Output: `reference_codes.parquet` — one row per cohort hospitalization with `cpt_present` and `icd_present` booleans.

Also reports the **code capture rate**: the fraction of the cohort carrying any of these codes. Every reference-scored metric in Tier C must be read against this number first — where capture is low, the reference is uninformative at that site and is reported as such rather than scored.

### `07_agreement.py`

> **All numbers in the tables below are illustrative shape, not results.** They exist to fix the output format so the notebook can be written and reviewed before any data is run. Real values come from executing the pipeline.

#### Step 0 — the joined analytic table

The notebook first validates the schema of each `method_*_encounter.parquet` against §6, then joins all four plus `reference_codes.parquet` on `hospitalization_id`. Every cohort hospitalization appears exactly once. This single wide table is the input to all three tiers.

```
hosp_id  | SED  PARA  DEV  INF | sed_off  para_off  inf_off | cpt  icd
---------+---------------------+----------------------------+----------
 1001    |  1     1    1    1  |   -4.0     -7.0      +38.0  |  1    1
 1002    |  1     1    1    0  |   -9.0     -6.0        NaN  |  1    1
 1003    |  1     0    1    1  |  -12.0      NaN      +21.0  |  0    1
 1004    |  0     0    0    1  |    NaN      NaN     +115.0  |  0    0
 1005    |  1     1    0    1  |   -3.0     -5.0      +44.0  |  1    0
 ...     |                     |                            |
---------+---------------------+----------------------------+----------
 N* rows, one per cohort hospitalization
 offsets in minutes, signed, relative to t₀; NaN where not detected
 DEV offset omitted — 0 by construction (§7)
```

#### Tier A — do the methods find the same patients?

**A.1 Detection rate per method.** The marginal, before any pairing.

| method | detected | n | rate |
|---|---|---|---|
| `SED` | ✓ | 1 842 | 0.83 |
| `PARA` | ✓ | 1 431 | 0.65 |
| `DEV` | ✓ | 1 202 | 0.54 |
| `INF` | ✓ | 1 067 | 0.48 |
| — | cohort N* | 2 214 | 1.00 |

**A.2 Pairwise agreement, 4×4.** One row per unordered pair. `both` / `only A` / `only B` / `neither` are the four cells of the 2×2, so every row is a complete contingency table and κ is recomputable from it by hand — a deliberate auditability property.

| pair | both | only A | only B | neither | Jaccard | Cohen κ |
|---|---|---|---|---|---|---|
| `SED` × `PARA` | 1 388 | 454 | 43 | 329 | 0.74 | 0.51 |
| `SED` × `DEV` | 1 043 | 799 | 159 | 213 | 0.52 | 0.14 |
| `SED` × `INF` | 918 | 924 | 149 | 223 | 0.46 | 0.11 |
| `PARA` × `DEV` | 902 | 529 | 300 | 483 | 0.52 | 0.25 |
| `PARA` × `INF` | 811 | 620 | 256 | 527 | 0.48 | 0.24 |
| `DEV` × `INF` | 704 | 498 | 363 | 649 | 0.45 | 0.26 |

**A.3 Concordance histogram.** How many of the four fired on the same hospitalization.

| methods firing | n | % |
|---|---|---|
| 0 | 118 | 5.3 |
| 1 | 341 | 15.4 |
| 2 | 502 | 22.7 |
| 3 | 611 | 27.6 |
| 4 | 642 | 29.0 |

The `0` row is the one to read first: hospitalizations that are in the cohort — so they *have* an IMV row by construction — where no method fired at all. That count is a direct measure of how much intubation goes undetected by every signal simultaneously.

**A.4 Upset plot** of the 15 non-empty detection-set combinations, sorted by frequency. Plot only; the underlying counts are A.3 broken out by which specific methods fired.

#### Tier B — how is charting distributed in time?

Computed from the `method_*_signals.parquet` long tables, so a hospitalization with three sedative doses in the window contributes three rows. `DEV` is absent from this tier by construction (§7).

**B.1 Offset summary**, minutes relative to t₀, negative = charted before the first IMV row.

| method | n signals | median | IQR | % before t₀ | % within ±30 min |
|---|---|---|---|---|---|
| `SED` | 3 419 | −6.0 | −18.0 … −2.0 | 88.1 | 79.4 |
| `PARA` | 1 655 | −5.0 | −11.0 … −2.0 | 94.3 | 91.0 |
| `INF` | 1 210 | +41.0 | +12.0 … +96.0 | 17.2 | 34.8 |

**B.2 Offset distribution plot.** Overlaid histograms on a shared [−180, +180] minute axis, one series per method, with t₀ marked at zero.

```
        −180      −90        0        +90      +180  min
          |        |         |         |         |
  PARA          ▁▂▅█▇▃▁      │
  SED         ▁▂▄▇█▆▃▂▁      │
  INF                        │ ▂▄▅▄▃▂▂▁▁▁
                             ▲ t₀
```

The clinical read: `PARA` and `SED` should cluster tightly just *before* t₀ — the meds are given to accomplish the intubation. `INF` should sit *after* — sedation is continued once the patient is on the vent. A method whose mass falls on the wrong side of t₀ is detecting something other than the intubation.

#### Tier C — reference check

**C.1 Code capture rate, reported first.** Every metric in C.2 is uninterpretable without it.

| reference | n with code | capture rate |
|---|---|---|
| `CPT` 31500 | 1 106 | 0.50 |
| `ICD` (any listed) | 1 794 | 0.81 |
| either | 1 903 | 0.86 |

**C.2 Per-method scoring**, one block per reference. Reference-positive is treated as the condition; a method's non-detection in a reference-positive encounter is a false negative.

| method | vs | TP | FP | FN | TN | sensitivity | PPV | F1 |
|---|---|---|---|---|---|---|---|---|
| `SED` | `ICD` | 1 588 | 254 | 206 | 166 | 0.89 | 0.86 | 0.87 |
| `PARA` | `ICD` | 1 297 | 134 | 497 | 286 | 0.72 | 0.91 | 0.80 |
| `DEV` | `ICD` | 1 044 | 158 | 750 | 262 | 0.58 | 0.87 | 0.70 |
| `INF` | `ICD` | 901 | 166 | 893 | 254 | 0.50 | 0.84 | 0.63 |

Repeated as a second block against `CPT`. Both blocks carry a standing caveat in the notebook output: **codes establish presence, never timing** (catalog §12.2), and where capture rate is low the reference is reported as uninformative rather than scored.

#### Outputs written by `07`

| File | Contents |
|---|---|
| `agreement_detection_rates.csv` | A.1 |
| `agreement_pairwise.csv` | A.2 |
| `agreement_concordance.csv` | A.3 |
| `agreement_upset.png` | A.4 |
| `timing_offset_summary.csv` | B.1 |
| `timing_offset_distribution.png` | B.2 |
| `reference_capture_rate.csv` | C.1 |
| `reference_scoring.csv` | C.2 |

All go to `output/final_no_phi/` and are subject to the n ≥ 10 minimum cell size in §9 — any row of any table with a cell below 10 is suppressed rather than published.

---

## 9. Outputs and data security

Follows the existing rules in [`output/README.md`](../../../output/README.md) and [`guides/primer.md`](../../../guides/primer.md).

| Directory | Contents |
|---|---|
| `output/intermediate_phi/` | `cohort.parquet`, `cohort_resp_waterfall.parquet`, `cohort_index.parquet`, all `method_*` and `reference_codes.parquet` |
| `output/final_no_phi/` | CONSORT counts, agreement matrices, offset distribution summaries, reference-scored metrics, plots |

`output/final_no_phi/` constraints: aggregates only, **minimum cell size n ≥ 10** for every reported statistic, no `patient_id`, no row-level records, no raw `.csv` / `.parquet` data files.

---

## 10. Configuration

Extends the existing `config/config.json` schema read by `utils/config.py`.

```json
{
  "site_name": "mimic",
  "data_directory": "./clif_demo",
  "filetype": "parquet",
  "timezone": "US/Eastern",
  "output_directory": "./output",
  "window_hours": 3,
  "infusion_gap_hours": 6,
  "date_start": "2018-01-01",
  "date_end": "2025-12-31"
}
```

`window_hours`, `infusion_gap_hours`, `date_start` and `date_end` are new. `date_start` and `date_end` are ignored when `site_name.lower() == "mimic"`.

---

## 11. Out of scope

Recorded so these are visible omissions rather than oversights.

- Extubation detection of any kind.
- Second and subsequent intubations; reintubation labelling; episode stitching.
- Outcome classification (success / failed / WLST) — catalog M3's tree.
- Tracheostomy handling — no cohort exclusion and no method adjustment.
- The M1 / M3 / M4 device transition rules.
- Pre-waterfall vs post-waterfall sensitivity analysis (settled by D5).
- M5 non-device signals (LPM onset, vent-observation cessation).
- Chart review (catalog Tier 2).
