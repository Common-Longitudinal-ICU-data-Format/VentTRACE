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

**Tier A — do the methods find the same patients?**
Pairwise 4×4 Jaccard and Cohen's κ across `SED`, `PARA`, `DEV`, `INF`. An upset plot of detection sets. A histogram of how many methods fired per hospitalization (0–4).

**Tier B — how is charting distributed in time?**
Offset distributions over [−180, +180] minutes for `SED`, `PARA`, `INF` on a shared axis, from the `_signals` tables. Reported per method: median, IQR, % of signals before t₀ vs after. `DEV` is excluded from this tier by construction.

**Tier C — reference check.**
Per method, a 2×2 against `cpt_present` and separately against `icd_present`, yielding sensitivity, PPV and F1 — reported **after** the code capture rate, never before it.

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
