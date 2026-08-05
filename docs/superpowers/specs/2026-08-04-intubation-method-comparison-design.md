# Intubation Detection Method Comparison — Design

**Project:** VentTRACE **Date:** 2026-08-04 **Status:** Design, approved for planning **Companion document:** [`docs/intubation_extubation_methods.md`](../../intubation_extubation_methods.md) — the methods catalog that motivated this build

------------------------------------------------------------------------

## 1. Purpose

The methods catalog established that intubation detection definitions disagree, and quantified that disagreement for one signal source only: the `device_category` transition rule (M1–M4). This project measures a **second, orthogonal axis** — the *signal source* itself.

Three candidate signals are compared head to head on the same patients at the same moment:

| ID | Signal | Whiteboard item | Source table |
|---|---|---|---|
| `SED` | Induction agent administration | \(0\) | `medication_admin_intermittent` |
| `PARA` | Paralytic administration | \(1\) | `medication_admin_intermittent` |
| `DEV` | `device_category` transition non-IMV → IMV | \(2\) | `respiratory_support` |

One further source serves as a **partial gold-truth reference**, not as a compared method:

| ID | Signal | Whiteboard item | Source table |
|---|---|---|---|
| `CPT` | CPT 31500 present in the hospitalization | (c1) | `patient_procedures` |

The deliverable answers two questions: **do these signals identify the same patients**, and **how is their charting distributed in time relative to the intubation**.

### Scope

- **Intubation only.** Extubation is out of scope for this build; the catalog already covers it and it can be a later phase.
- **First IMV episode only.** One index event per hospitalization. Reintubation, episode stitching, and outcome classification are out of scope.
- **Intermittent medications only.** Both medication methods read `medication_admin_intermittent`. The continuous-infusion signal (whiteboard item 3) is out of scope — see §11.
- **CPT is the sole reference.** ICD procedure codes are out of scope — see §11.
- **Testing target is MIMIC**, with the pipeline written to run at any consortium site via config.

------------------------------------------------------------------------

## 2. Decisions

Each decision below was made explicitly during design. Recorded with rationale so the choice is auditable and reversible.

| \# | Decision | Rationale |
|------------------------|------------------------|------------------------|
| D1 | **Four signals: three methods under test, one reference source.** CPT does not enter the agreement matrix. | Catalog §12.2 establishes procedure codes confirm *presence* but never *timing*, and their capture rate varies by site, payer and era. A code cannot be a peer to a timestamped signal. |
| D1a | **The continuous-infusion method (`INF`) is removed.** | It detects a *state* — "this patient is on sedation, therefore probably ventilated" — not the intubation event. Its signal necessarily lags t₀ and cannot distinguish an intubation from ongoing ICU sedation, so it would contribute detections without contributing evidence about timing. |
| D1b | **The ICD reference is removed; CPT 31500 is the sole reference.** | Removing ICD-10-PCS while keeping ICD-9 would leave a reference that is effectively dead for a 2018–2025 cohort, so the reference is dropped whole rather than partially. One reference also removes the question of what to do when CPT and ICD disagree. |
| D2 | **Device signal is one notebook using the M2 symmetric 2/2 rule**, not four notebooks for M1–M4. | The M1–M4 spread is already quantified in the catalog. Re-running it here would measure a known result and obscure the new one. |
| D3 | **Analytic unit is one row per hospitalization**, anchored on t₀ = first charted IMV row. | Collapses event matching entirely: no greedy pairing, no order-dependence, no tolerance windows. Agreement becomes a plain binary table; timing becomes offset distributions on a shared axis. |
| D4 | **Detection window is t₀ ± 3 hours**, symmetric. | Set by the study lead. Every method asks the same question over the same interval, so differences are attributable to the signal and not to the window. |
| D5 | **Respiratory pre-processing is fixed: post-waterfall, single policy.** No pre/post grid. | Catalog §12.4 requires the policy be settled before methods are compared. Fixing it in one place makes the agreement numbers mean exactly one thing; changing it later is a config edit, not a rewrite. |
| D6 | **Waterfall runs with `bfill=False`.** | `clifpy/utils/waterfall.py:12` — already the library default; `:58` confirms forward-fill only when False. Backfilling could propagate a device backwards in time and manufacture an IMV row earlier than the first real charting, sliding t₀ and with it every ±3h window. |
| D7 | **No CPT code and no `billing_provider_id` in the cohort definition.** | Explicit study requirement. Distinguishes this cohort from `Induction_Variability_RSI`, which requires both. The CPT code enters only as the reference in notebook `05`. |
| D8 | **Every method notebook is fully self-contained. No shared helper module.** | A bug in a shared helper corrupts every method *identically*, and correlated errors are indistinguishable from genuine agreement — the one failure mode an agreement study cannot tolerate. Isolation makes mistakes surface as disagreement (visible) rather than as inflated concordance (invisible). |
| D9 | **The detection window is data, not code.** `01_cohort.py` writes `window_start` / `window_end` into `cohort_index.parquet`. | Removes the usual cost of D8. There is no window logic to duplicate across notebooks, so there is nothing to drift, while detection logic stays fully independent. |
| D10 | **`SED` is the induction-agent list — the drugs used to intubate — and reads `medication_admin_intermittent` only.** | Induction agents are intermittently dosed. Propofol and fentanyl are also charted as continuous maintenance infusions, but those rows live in `medication_admin_continuous` and are never read: reading them would conflate intubating a patient with sedating one already ventilated. `SED` is still expected to fire often, since midazolam and fentanyl are given for many non-airway reasons — that low specificity is a reportable property of the method, not a defect to tune away before measurement. |
| D11 | **Each method is a profiler, not just a detector.** It emits the ranked medication sequence around t₀ with dose, unit and lag; the binary `detected` is *derived* from that structure. | A binary answers "did the signal appear"; the ranked sequence answers "what was actually given, in what order, how far from the intubation". Deriving the binary from the ranks rather than computing it separately makes the two incapable of disagreeing. |
| D12 | **Ranks deduplicate by `med_category`: last administration before t₀, first after, ranked nearest-first.** | Nearest-first makes rank 1 the most clinically proximate entry, so rank 1 is comparable across patients. Dedup removes a real statistical artifact — under the previous all-signals contract a patient given six fentanyl doses contributed six observations to the timing distribution and dominated it. |
| D13 | **Ranking is over each method's own medication list only**, not over all charted medications. | Keeps every method strictly about its own signal, so the ranked output elaborates what the method detects rather than describing the ward. Consequence: rank counts are bounded by list size, so no rank cap is specified. |
| D14 | **Two artifacts per method: canonical `_ranked.json` plus a joinable `_encounter.parquet`.** The raw undeduped signals table is dropped. | JSON carries nested ranks without null padding; parquet is what §8 can join at scale. The undeduped table had no remaining consumer once Tier B moved to ranked entries, and keeping an unconsumed artifact invites it to drift. |

------------------------------------------------------------------------

## 3. Architecture

```         
code/
  01_cohort.py            cohort + CONSORT + waterfall + t₀ + window bounds
  02_method_sedative.py   ┐  each fully self-contained:
  03_method_paralytic.py  │  config → cohort_index + ONE CLIF table
  04_method_device.py     ┘  → own logic → artifacts → assert own schema
  05_reference_cpt.py     CPT 31500 presence
  06_agreement.py         schema gatekeeper + agreement + distributions
```

The only things crossing a notebook boundary are **artifacts on disk** and the **schema contract in §6**. `06_agreement.py` validates the schema of every input on load and fails loudly rather than silently mis-joining.

All notebooks are marimo notebooks stored as `.py`, run as `uv run python code/NN_name.py`, matching the existing consortium convention.

**Dataframe library:** polars throughout, per the root `pyproject.toml`. `process_resp_support_waterfall` takes a pandas DataFrame, so `01_cohort.py` converts to pandas immediately before that call and back to polars immediately after. That is the only pandas boundary in the project.

------------------------------------------------------------------------

## 4. Implementation constraints

The code must be readable by a clinician-researcher reviewing the definition, not only by its author. These are requirements, not preferences.

- **One logical step per marimo cell**, with a markdown cell above it stating what the step does in plain language.
- **No helper functions across notebooks**, and inside a notebook only where a step is genuinely repeated. Prefer an explicit repeated expression over an abstraction that hides the definition being tested.
- **Name intermediate columns explicitly** rather than chaining long expressions. A reviewer must be able to inspect `is_in_window`, `is_target_med`, `delta_minutes`, `rank` as real columns before they are collapsed into the JSON.
- **No clever vectorisation** where a plain filter and join expresses the same thing. Cohort sizes are small enough that clarity wins over speed.
- **Every filter prints its row and hospitalization count** before and after, so the CONSORT and the method yields are visible while running, not only in the final artifact.
- **Each method notebook ends with an explicit schema assertion block** against §6. Copy-pasted deliberately across the four — duplication here is the point of D8.
- **No silent defaults.** Every parameter that affects a result is read from `config.json` and echoed at the top of the notebook.

------------------------------------------------------------------------

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

`site_name.lower() == "mimic"` → **no date restriction** (MIMIC timestamps are date-shifted, so a calendar filter is meaningless). Otherwise → `admission_dttm` within `date_start` … `date_end`, default `2018-01-01` … `2025-12-31`.

### Waterfall and t₀

1.  Subset `respiratory_support` to cohort hospitalizations.
2.  Run `process_resp_support_waterfall(..., bfill=False)`.
3.  **t₀ = earliest `recorded_dttm` where `device_category == 'imv'`**, per hospitalization.
4.  `window_start = t₀ − 3h`, `window_end = t₀ + 3h`.

### QC statistic

Report `Δ = waterfall_t₀ − raw_t₀` (median, IQR, % nonzero). D6 makes a negative Δ very unlikely, but the device/mode heuristics and the hourly `HH:59:59` scaffold run regardless of `bfill`, so this is cheap insurance that t₀ still corresponds to real charting. A nonzero negative Δ in any meaningful fraction of the cohort invalidates the offset distributions and must be investigated before results are interpreted.

### Outputs

| File | Contents |
|------------------------------------|------------------------------------|
| `cohort.parquet` | one row per included hospitalization, with demographics |
| `cohort_resp_waterfall.parquet` | waterfalled respiratory rows for cohort hospitalizations |
| `cohort_index.parquet` | `hospitalization_id`, `t0_dttm`, `window_start`, `window_end` |
| `consort.json` / `consort.csv` | step label, n remaining, n excluded |

------------------------------------------------------------------------

## 6. Method contract

Each method is a **profiler**, not merely a detector. Anchored on t₀, it reports the ranked medication sequence around the intubation — with dose, unit and lag — from which the binary detection flag falls out for free.

### 6.1 The intubation episode

Every artifact is keyed on `intubation_episode_id`, formed as `{hospitalization_id}_E1`.

Because this build is scoped to the first IMV episode only (§1), the suffix is **always `E1`** and there is exactly one episode per cohort hospitalization. The suffix exists so that widening scope to reintubation later adds `_E2` rows without changing any key, join or schema.

### 6.2 The ranking rule

Within the window `[window_start, window_end]` from `cohort_index.parquet`:

```
   BEFORE   for each distinct med_category with ≥1 administration in [window_start, t₀)
              keep the LAST administration   (the one closest to t₀)
            then rank by proximity to t₀ — rank 1 is nearest

   AFTER    for each distinct med_category with ≥1 administration in (t₀, window_end]
              keep the FIRST administration  (the one closest to t₀)
            then rank by proximity to t₀ — rank 1 is nearest
```

Deduplication is **by `med_category`**, so a medication appears at most once in `before` and at most once in `after`. Repeat administrations of the same agent are collapsed to the single one nearest the intubation.

**No rank cap.** Ranks are naturally bounded by the size of the method's medication list — at most **5** for `SED` and **3** for `PARA`. A cap of 5 was considered and rejected as redundant: it exactly equals `SED`'s list length and exceeds `PARA`'s, so it can never truncate anything. Writing it would leave a constant a later reviewer reads as load-bearing when it is not.

Ties — two different medications sharing an identical `admin_dttm` — are broken alphabetically by `med_category`, so output is deterministic across runs.

### 6.3 `method_<ID>_ranked.json` — canonical

One JSON object per intubation episode, emitted by the two **medication** methods (`SED`, `PARA`). Written as newline-delimited JSON so it streams and appends cleanly.

```json
{
  "hospitalization_id": "1001",
  "intubation_episode_id": "1001_E1",
  "method_id": "SED",
  "imv_dttm": "2130-04-12T03:14:00",
  "before": [
    {"rank": 1, "med_category": "etomidate", "med_dose": 20.0,
     "med_dose_unit": "mg", "admin_dttm": "2130-04-12T03:10:00",
     "delta_minutes": -4.0},
    {"rank": 2, "med_category": "midazolam", "med_dose": 2.0,
     "med_dose_unit": "mg", "admin_dttm": "2130-04-12T03:02:00",
     "delta_minutes": -12.0},
    {"rank": 3, "med_category": "fentanyl", "med_dose": 100.0,
     "med_dose_unit": "mcg", "admin_dttm": "2130-04-12T02:55:00",
     "delta_minutes": -19.0}
  ],
  "after": [
    {"rank": 1, "med_category": "midazolam", "med_dose": 2.0,
     "med_dose_unit": "mg", "admin_dttm": "2130-04-12T03:52:00",
     "delta_minutes": 38.0},
    {"rank": 2, "med_category": "fentanyl", "med_dose": 100.0,
     "med_dose_unit": "mcg", "admin_dttm": "2130-04-12T04:30:00",
     "delta_minutes": 76.0}
  ]
}
```

`delta_minutes` is signed: negative before t₀, positive after. Both arrays are empty when nothing was found; the object is still written, so the file has one record per cohort hospitalization.

**`DEV` does not emit this file.** It has no medication signal, so an empty-array record would be a fiction rather than a fact. This asymmetry is deliberate and documented rather than papered over — `DEV` writes only its encounter parquet.

### 6.4 `method_<ID>_encounter.parquet` — joinable

One row per **cohort** hospitalization, including non-detections. Emitted by all three methods. This is what §8 joins on; the JSON is not join-friendly at scale.

| Column | Type | Notes |
|---|---|---|
| `hospitalization_id` | str | |
| `intubation_episode_id` | str | `{hospitalization_id}_E1` |
| `method_id` | str | one of `SED`, `PARA`, `DEV` |
| `imv_dttm` | datetime | t₀, copied from `cohort_index` |
| `detected` | bool | see below |
| `n_before` | int | count of ranked entries before t₀; 0 for `DEV` |
| `n_after` | int | count of ranked entries after t₀; 0 for `DEV` |
| `nearest_before_med` | str | `med_category` at before-rank 1; null if none |
| `nearest_before_min` | float | `delta_minutes` at before-rank 1; null if none |
| `nearest_after_med` | str | `med_category` at after-rank 1; null if none |
| `nearest_after_min` | float | `delta_minutes` at after-rank 1; null if none |
| `non_detection_reason` | str | null when detected. Only `DEV` populates this. |

**`detected` is derived, not independently computed:**

- medication methods — `detected = (n_before > 0) OR (n_after > 0)`
- `DEV` — `detected` = the transition rule fired (§7)

Deriving the binary from the ranked structure rather than computing it separately means the two cannot disagree. Non-detections are retained as `detected = false` rows; they are the denominator for every rate in §8.

------------------------------------------------------------------------

## 7. Method definitions

All three evaluate against `cohort_index.parquet` and are restricted to the window `[window_start, window_end]`. The two medication methods differ **only** in which `med_category` values they admit — the ranking rule of §6.2 is identical across them, and both read `medication_admin_intermittent`.

### `SED` — `02_method_sedative.py`

**Induction medications — the agents used to intubate a patient. All are intermittently dosed.**

Source: `medication_admin_intermittent` **only**, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
midazolam | etomidate | ketamine | propofol | fentanyl
```

Ranked per §6.2. At most 5 before-ranks and 5 after-ranks.

> **`SED` reads the intermittent table only — never the continuous table.** Propofol and fentanyl are also charted as continuous maintenance infusions, but those rows live in `medication_admin_continuous` and are out of scope for this build (§11). An induction bolus and a maintenance infusion are the same drug performing two different clinical acts, distinguished by which table they are charted in. Pulling propofol from both would conflate intubating a patient with sedating one already ventilated.

`med_dose` and `med_dose_unit` are taken verbatim from the administration row. **No unit conversion or dose normalisation is performed** — the raw charted value is what a reviewer needs to see, and normalising would hide unit heterogeneity that is itself worth measuring across sites.

### `PARA` — `03_method_paralytic.py`

Source: `medication_admin_intermittent`, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
rocuronium | succinylcholine | vecuronium
```

Ranked per §6.2. At most 3 before-ranks and 3 after-ranks. Dose handling as for `SED`.

### `DEV` — `04_method_device.py`

Source: `cohort_resp_waterfall.parquet`. Fires when t₀ is a **documented non-IMV → IMV transition** under the M2 symmetric 2/2 rule. Writing t₀ as row index `i` within the hospitalization's waterfalled rows ordered by `recorded_dttm`:

```         
   DEV fires  ≡  ¬IMV(i-2) ∧ ¬IMV(i-1) ∧ IMV(i) ∧ IMV(i+1)
```

**Boundary policy is `B_strict`** — if row `i-2`, `i-1` or `i+1` does not exist, the corresponding term is false and `DEV` does not fire. This matches the convention the catalog applies to M2 in §3.1 and is stated here rather than inherited from language semantics.

`DEV` has no medication signal and therefore **emits no `_ranked.json`** (§6.3). It writes only `method_DEV_encounter.parquet`, with `n_before = n_after = 0` and every `nearest_*` field null. It contributes to the binary agreement table in §8 Tier A but not to the ranked timing analysis in Tier B.

When the rule does not fire, `non_detection_reason` takes the first applicable value:

| Reason                  | Condition                                         |
|------------------------------------|------------------------------------|
| `arrived_intubated`     | t₀ is the hospitalization's first respiratory row |
| `insufficient_lookback` | fewer than two rows precede t₀                    |
| `imv_not_sustained`     | row `i+1` is absent or non-IMV                    |
| `prior_row_imv`         | row `i-1` or `i-2` exists but is IMV              |

> **What `DEV` actually measures.** Anchored on t₀, this method reports the fraction of the cohort whose pre-intubation period was documented at all — catalog §9.4, the arrived-intubated rate. A low `DEV` detection rate means the medication methods are firing on intubations whose device transition was never charted. That is a finding about site charting, not a failure of the method.

------------------------------------------------------------------------

## 8. Reference and agreement

### `05_reference_cpt.py`

Source: `patient_procedures` — `procedure_code`, `procedure_code_format`. **`billing_provider_id` is not read, and `procedure_billed_dttm` is read only to confirm the row belongs to the hospitalization — never as an event time.**

| Reference | Format | Code |
|---|---|---|
| `CPT` | CPT | `31500` — emergency endotracheal intubation |

Output: `reference_cpt.parquet` — one row per cohort hospitalization with a `cpt_present` boolean.

Also reports the **code capture rate**: the fraction of the cohort carrying the code. Every metric in Tier C must be read against this number first — where capture is low, the reference is uninformative at that site and is reported as such rather than scored.

> **CPT 31500 is a narrow reference and its ceiling should be stated up front.** It codes *emergency* endotracheal intubation, so elective and operative airway management is not captured, and billing completeness varies by site, payer and era. Sensitivity computed against it is bounded by that capture, not by the method under test — which is precisely why it is a *partial* gold truth and not a peer in the agreement matrix (D1).

### `06_agreement.py`

> **All numbers in the tables below are illustrative shape, not results.** They exist to fix the output format so the notebook can be written and reviewed before any data is run. Real values come from executing the pipeline.

#### Step 0 — the joined analytic table

The notebook validates the schema of each `method_*_encounter.parquet` against §6.4, then joins all three plus `reference_cpt.parquet` on `intubation_episode_id`. Every cohort hospitalization appears exactly once. This wide table is the input to **Tier A** and **Tier C**.

```         
episode_id | SED PARA DEV | sed_bef para_bef | cpt
-----------+--------------+------------------+-----
 1001_E1   |  1    1   1  |   -4.0     -2.0  |  1
 1002_E1   |  1    1   1  |   -9.0     -6.0  |  1
 1003_E1   |  1    0   1  |  -12.0      NaN  |  0
 1004_E1   |  0    0   0  |    NaN      NaN  |  0
 1005_E1   |  1    1   0  |   -3.0     -5.0  |  1
-----------+--------------+------------------+-----
 N* rows, one per cohort hospitalization
 *_bef = nearest_before_min (rank 1), signed minutes
 NaN where that direction had no ranked entry
 DEV omitted from the offset block — no medication signal (§7)
```

**Tier B reads the `method_*_ranked.json` files instead**, because the encounter table carries only rank 1. The full rank ladder — and the per-medication breakdown it enables — lives only in the JSON.

#### Tier A — do the methods find the same patients?

**A.1 Detection rate per method.** The marginal, before any pairing.

| method | detected | n | rate |
|---|---|---|---|
| `SED` | ✓ | 1 842 | 0.83 |
| `PARA` | ✓ | 1 431 | 0.65 |
| `DEV` | ✓ | 1 202 | 0.54 |
| — | cohort N\* | 2 214 | 1.00 |

**A.2 Pairwise agreement, 3×3.** One row per unordered pair. `both` / `only A` / `only B` / `neither` are the four cells of the 2×2, so every row is a complete contingency table and κ is recomputable from it by hand — a deliberate auditability property.

| pair | both | only A | only B | neither | Jaccard | Cohen κ |
|---|---|---|---|---|---|---|
| `SED` × `PARA` | 1 388 | 454 | 43 | 329 | 0.74 | 0.51 |
| `SED` × `DEV` | 1 043 | 799 | 159 | 213 | 0.52 | 0.14 |
| `PARA` × `DEV` | 902 | 529 | 300 | 483 | 0.52 | 0.25 |

**A.3 Concordance histogram.** How many of the three fired on the same hospitalization.

| methods firing | n | \% |
|---|---|---|
| 0 | 174 | 7.9 |
| 1 | 486 | 21.9 |
| 2 | 712 | 32.2 |
| 3 | 842 | 38.0 |

The `0` row is the one to read first: hospitalizations that are in the cohort — so they *have* an IMV row by construction — where no method fired at all. That count is a direct measure of how much intubation goes undetected by every signal simultaneously.

**A.4 Upset plot** of the 7 non-empty detection-set combinations, sorted by frequency. Plot only; the underlying counts are A.3 broken out by which specific methods fired.

> With three methods the upset plot is small enough that its 7 combinations could be tabulated directly. It is kept as a plot because the combination *identities* — `SED`-only versus `DEV`-only, say — are the interesting part, and those read faster visually than as a table of set labels.

#### Tier B — how is charting distributed in time?

Computed by flattening the `method_*_ranked.json` files into a long frame of ranked entries. Each episode contributes **at most one entry per medication per direction** (§6.2), so no patient is over-weighted by repeat dosing. `DEV` is absent from this tier by construction (§7).

**B.1 Offset summary by method and direction**, minutes relative to t₀.

| method | direction | n entries | median | IQR | % within ±30 min |
|---|---|---|---|---|---|
| `SED` | before | 2 918 | −8.0 | −19.0 … −3.0 | 78.2 |
| `SED` | after | 1 204 | +47.0 | +18.0 … +102.0 | 31.5 |
| `PARA` | before | 1 402 | −4.0 | −9.0 … −2.0 | 93.1 |
| `PARA` | after | 118 | +62.0 | +21.0 … +134.0 | 22.0 |

**B.2 Offset by rank.** Whether the rank ladder behaves — rank 1 nearest, later ranks progressively further from t₀. A ladder that does not monotonically widen indicates a ranking bug.

| method | direction | rank | n | median delta |
|---|---|---|---|---|
| `SED` | before | 1 | 1 811 | −4.0 |
| `SED` | before | 2 | 782 | −14.0 |
| `SED` | before | 3 | 291 | −38.0 |
| `SED` | before | 4 | 34 | −71.0 |
| `PARA` | before | 1 | 1 388 | −3.0 |
| `PARA` | before | 2 | 14 | −27.0 |

**B.3 Per-medication breakdown.** The output the ranked structure exists to produce — which agent, how far from the intubation, at what dose. This is not derivable from a binary detector.

| method | med_category | direction | n | median delta | median dose | unit |
|---|---|---|---|---|---|---|
| `SED` | etomidate | before | 891 | −4.0 | 20.0 | mg |
| `SED` | ketamine | before | 302 | −5.0 | 100.0 | mg |
| `SED` | propofol | before | 418 | −6.0 | 100.0 | mg |
| `SED` | midazolam | before | 744 | −12.0 | 2.0 | mg |
| `SED` | fentanyl | before | 981 | −18.0 | 100.0 | mcg |
| `PARA` | rocuronium | before | 1 044 | −3.0 | 70.0 | mg |
| `PARA` | succinylcholine | before | 331 | −2.0 | 100.0 | mg |
| `PARA` | vecuronium | before | 27 | −6.0 | 10.0 | mg |

Doses are the raw charted values with no unit conversion (§7), so `unit` must always be reported alongside — and a medication showing more than one unit across the cohort is itself a finding.

**B.4 Offset distribution plot.** Overlaid histograms on a shared \[−180, +180\] minute axis, one series per method, with t₀ marked at zero.

```         
        −180      −90        0        +90      +180  min
          |        |         |         |         |
  PARA          ▁▂▅█▇▃▁      │
  SED         ▁▂▄▇█▆▃▂▁      │▁▂▂▁
                             ▲ t₀
```

The clinical read: both methods should cluster tightly just *before* t₀ — induction agents and paralytics are given to accomplish the intubation. Mass appearing *after* t₀ is expected to be small and is meaningful when it appears: a post-intubation sedative bolus, or a paralytic redose. A method whose bulk falls on the wrong side of t₀ is detecting something other than the intubation.

> **Both remaining methods are pre-t₀ signals**, so the forward half of the ±3h window now carries much less traffic than the backward half. The window stays symmetric — an asymmetric window would bias the comparison and would need its own justification — but expect `after` arrays to be sparse, and read a large post-t₀ mass as a signal that t₀ itself is landing late.

#### Tier C — reference check

**C.1 Code capture rate, reported first.** Every metric in C.2 is uninterpretable without it.

| reference | n with code | capture rate |
|---|---|---|
| `CPT` 31500 | 1 106 | 0.50 |

**C.2 Per-method scoring.** Reference-positive is treated as the condition; a method's non-detection in a reference-positive encounter is a false negative.

| method | vs | TP | FP | FN | TN | sensitivity | PPV | F1 |
|---|---|---|---|---|---|---|---|---|
| `SED` | `CPT` | 1 004 | 838 | 102 | 270 | 0.91 | 0.54 | 0.68 |
| `PARA` | `CPT` | 892 | 539 | 214 | 569 | 0.81 | 0.62 | 0.70 |
| `DEV` | `CPT` | 701 | 501 | 405 | 607 | 0.63 | 0.58 | 0.61 |

The block carries a standing caveat in the notebook output: **codes establish presence, never timing** (catalog §12.2), and where capture rate is low the reference is reported as uninformative rather than scored.

> **Read PPV against C.1, not on its own.** At the illustrative 0.50 capture rate, half the cohort lacks the code despite having an IMV row by construction — so most "false positives" are encounters the reference simply failed to code, not encounters the method got wrong. Sensitivity is the more interpretable column here; PPV is bounded above by capture and will look poor for any method regardless of quality.

#### Outputs written by `06`

| File | Contents |
|---|---|
| `agreement_detection_rates.csv` | A.1 |
| `agreement_pairwise.csv` | A.2 |
| `agreement_concordance.csv` | A.3 |
| `agreement_upset.png` | A.4 |
| `timing_offset_summary.csv` | B.1 |
| `timing_offset_by_rank.csv` | B.2 |
| `timing_by_medication.csv` | B.3 |
| `timing_offset_distribution.png` | B.4 |
| `reference_capture_rate.csv` | C.1 |
| `reference_scoring.csv` | C.2 |

All go to `output/final_no_phi/` and are subject to the n ≥ 10 minimum cell size in §9 — any row of any table with a cell below 10 is suppressed rather than published.

> **The n ≥ 10 rule bites hardest on B.3.** Per-medication breakdowns split the cohort finely — the illustrative `vecuronium` row above shows n = 27, and a rarer agent or a smaller site will fall below 10. Suppression here is row-level: the medication is dropped from the published table rather than pooled into an "other" category, since pooling across agents with different units and dose scales would produce a meaningless median.

------------------------------------------------------------------------

## 9. Outputs and data security

Follows the existing rules in [`output/README.md`](../../../output/README.md) and [`guides/primer.md`](../../../guides/primer.md).

| Directory | Contents |
|------------------------------------|------------------------------------|
| `output/intermediate_phi/` | `cohort.parquet`, `cohort_resp_waterfall.parquet`, `cohort_index.parquet`, `method_{SED,PARA}_ranked.json`, `method_{SED,PARA,DEV}_encounter.parquet`, `reference_cpt.parquet` |
| `output/final_no_phi/` | CONSORT counts, agreement matrices, offset distribution summaries, reference-scored metrics, plots |

`output/final_no_phi/` constraints: aggregates only, **minimum cell size n ≥ 10** for every reported statistic, no `patient_id`, no row-level records, no raw `.csv` / `.parquet` data files.

------------------------------------------------------------------------

## 10. Configuration

Extends the existing `config/config.json` schema read by `utils/config.py`.

``` json
{
  "site_name": "mimic",
  "data_directory": "./clif_demo",
  "filetype": "parquet",
  "timezone": "US/Eastern",
  "output_directory": "./output",
  "window_hours": 3,
  "date_start": "2018-01-01",
  "date_end": "2025-12-31"
}
```

`window_hours`, `date_start` and `date_end` are new. `date_start` and `date_end` are ignored when `site_name.lower() == "mimic"`.

`window_hours` is the only parameter that changes a detection result, and it applies identically to both medication methods (§6.2). Everything else is a path or a site label.

------------------------------------------------------------------------

## 11. Out of scope

Recorded so these are visible omissions rather than oversights.

**Removed from an earlier draft of this spec:**

- **The continuous-infusion method `INF`** (whiteboard item 3) — propofol / dexmedetomidine / fentanyl infusion starts. Removed per D1a. Consequently `medication_admin_continuous` is not read anywhere in the pipeline, and `infusion_gap_hours` is not a config key.
- **The ICD reference** — ICD-10-PCS `0BH17EZ`, `0BH18EZ`, `5A1935Z`, `5A1945Z`, `5A1955Z` and ICD-9 `9604`, `9670`–`9672`. Removed per D1b. CPT 31500 is the sole reference.

**Out of scope from the start:**

- Extubation detection of any kind.
- Second and subsequent intubations; reintubation labelling; episode stitching.
- Outcome classification (success / failed / WLST) — catalog M3's tree.
- Tracheostomy handling — no cohort exclusion and no method adjustment.
- The M1 / M3 / M4 device transition rules.
- Pre-waterfall vs post-waterfall sensitivity analysis (settled by D5).
- M5 non-device signals (LPM onset, vent-observation cessation).
- Chart review (catalog Tier 2).