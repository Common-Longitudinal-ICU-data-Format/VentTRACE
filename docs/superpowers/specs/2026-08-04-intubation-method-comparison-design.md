# Intubation Detection Method Comparison — Design

**Project:** VentTRACE **Date:** 2026-08-04 **Status:** Design, approved for planning **Companion document:** [`docs/intubation_extubation_methods.md`](../../intubation_extubation_methods.md) — the methods catalog that motivated this build

------------------------------------------------------------------------

## 1. Purpose

The methods catalog established that intubation detection definitions disagree, and quantified that disagreement for one signal source only: the `device_category` transition rule (M1–M4). This project measures a **second, orthogonal axis** — the *signal source* itself.

Two medication signals are compared head to head on the same patients at the same moment:

| ID | Signal | Whiteboard item | Source table |
|---|---|---|---|
| `SED` | Induction agent administration | \(0\) | `medication_admin_intermittent` |
| `PARA` | Paralytic administration | \(1\) | `medication_admin_intermittent` |

Two further sources are **not** compared methods. Each does a different job:

| ID | Signal | Whiteboard item | Role | Source table |
|---|---|---|---|---|
| `DEV` | `device_category` transition non-IMV → IMV | \(2\) | **index qualifier** — defines which encounters have an observable intubation at all (§5.9) | `respiratory_support` |
| `CPT` | CPT 31500 present in the encounter | (c1) | **partial gold-truth reference** | `patient_procedures` |

The deliverable answers two questions: **do these signals identify the same patients**, and **how is their charting distributed in time relative to the intubation**. A third question falls out of the index qualifier itself: **on what fraction of ventilated encounters is the intubation visible in the record at all** — the CONSORT of `02_index_imv.py` is a first-class result, not a preprocessing detail.

### Scope

- **Intubation only.** Extubation is out of scope for this build; the catalog already covers it and it can be a later phase.
- **The analytic unit is the stitched encounter**, not `hospitalization_id`. `01_cohort.py` runs `stitch_encounters` first and everything downstream keys on `encounter_block` — see §5.1 for why this is a correctness requirement rather than a convenience.
- **First IMV episode only.** One index event per encounter. Reintubation, *intubation*-episode stitching, and outcome classification are out of scope. (Encounter stitching is in scope and happens first; the two senses of "stitching" are unrelated.)
- **Intermittent medications only.** Both medication methods read `medication_admin_intermittent`. The continuous-infusion signal (whiteboard item 3) is out of scope — see §11.
- **CPT is the sole reference.** ICD procedure codes are out of scope — see §11.
- **Testing target is MIMIC**, with the pipeline written to run at any consortium site via config.

------------------------------------------------------------------------

## 2. Decisions

Each decision below was made explicitly during design. Recorded with rationale so the choice is auditable and reversible.

| \# | Decision | Rationale |
|------------------------|------------------------|------------------------|
| D1 | **Four signals with three distinct roles: two methods under test, one index qualifier, one reference.** Neither `DEV` nor `CPT` enters the agreement matrix. | Catalog §12.2 establishes procedure codes confirm *presence* but never *timing*, and their capture rate varies by site, payer and era. A code cannot be a peer to a timestamped signal. `DEV`'s exclusion has a separate cause — see D19. |
| D1a | **The continuous-infusion method (`INF`) is removed.** | It detects a *state* — "this patient is on sedation, therefore probably ventilated" — not the intubation event. Its signal necessarily lags t₀ and cannot distinguish an intubation from ongoing ICU sedation, so it would contribute detections without contributing evidence about timing. |
| D1b | **The ICD reference is removed; CPT 31500 is the sole reference.** | Removing ICD-10-PCS while keeping ICD-9 would leave a reference that is effectively dead for a 2018–2025 cohort, so the reference is dropped whole rather than partially. One reference also removes the question of what to do when CPT and ICD disagree. |
| D2 | **The device signal uses the M2 symmetric 2/2 rule only**, not all of M1–M4. | The M1–M4 spread is already quantified in the catalog. Re-running it here would measure a known result and obscure the new one. |
| D3 | **Analytic unit is one row per stitched `encounter_block`**, anchored on t₀ = first charted IMV row in the block. | Collapses event matching entirely: no greedy pairing, no order-dependence, no tolerance windows. Agreement becomes a plain binary table; timing becomes offset distributions on a shared axis. |
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
| D15 | **Encounters are stitched before any cohort criterion is applied**, with `stitch_hours = 6`. | An ED intubation and the inpatient IMV charting that follows can carry different `hospitalization_id`s. Unstitched, `PARA` fires on one and `DEV` on the other and the agreement matrix records a disagreement that is purely administrative. Stitching last would mean filtering on a unit the study does not use. |
| D16 | **Stitching is preceded by a patient-level IMV-ever pre-filter.** | Stitching joins the full hospitalization and ADT tables and iterates to a fixed point; running it on every patient at a site is wasteful when every cohort criterion requires an IMV row. The filter is **patient**-level, not hospitalization-level, precisely because the IMV may be charted under a different `hospitalization_id` than the one anchoring the block — filtering hospitalizations here would discard the rows stitching exists to reunite. Changes no result (§5.2). |
| D17 | **Location criterion is ED *or* ICU, evaluated across the whole stitched block.** | Set by the study lead. ED-or-ICU is what admits the ED intubation that never reaches an ICU and the ward patient intubated on ICU transfer; requiring ICU alone would drop the first group, which is exactly where the medication and device signals are most likely to diverge. |
| D18 | **Tracheostomy in the first 24 h excludes the encounter, tested on two signals: `tracheostomy = True` *or* `device_category = 'Trach Collar'`.** | mCIDE defines `IMV` as "Endotracheal Tube Ventilation, **Tracheostomy Ventilation**" — a trach patient on a vent charts as plain `IMV` and would otherwise enter as a false intubation with no induction or paralytic to find. Either signal alone leaks: the boolean misses sites that only chart the device, and `Trach Collar` is a weaning device that a continuously-ventilated trach patient may never receive. |
| D19 | **`DEV` becomes the index qualifier in `02_index_imv.py`, not a method in the agreement matrix.** Encounters whose index IMV fails the M2 rule are excluded before any method runs. | Anchored on t₀, the M2 rule cannot detect a *different* event from `SED` and `PARA` — t₀ is already fixed for all three. All it can report is whether the pre-intubation period was documented and the IMV sustained. That is a statement about record completeness, not an independent signal, so scoring it against medication signals was comparing a data-availability fact to a clinical one. Making it the qualifier puts it where it belongs and leaves `SED` × `PARA` measured on encounters where the intubation is genuinely observable. |
| D20 | **The excluded encounters are retained and analysed, not discarded.** `02` writes a classification for every cohort encounter; §8 runs the method rates over the excluded strata as a specificity probe. | The arrived-intubated group is the sharpest available test of whether `SED` is detecting intubation or ICU sedation: these patients were intubated before arrival, so any `SED` firing in the ±3 h window around their first charted IMV row is by construction *not* an induction. Throwing the group away would discard the one stratum with a known answer. |

------------------------------------------------------------------------

## 3. Architecture

```         
code/
  01_cohort.py            encounter stitch + cohort CONSORT + waterfall + t₀ + window bounds
  02_index_imv.py         index CONSORT — is the intubation observable? (DEV, M2 rule)
  03_method_sedative.py   ┐  each fully self-contained:
  04_method_paralytic.py  ┘  config → index_imv + ONE CLIF table
                             → own logic → artifacts → assert own schema
  05_reference_cpt.py     CPT 31500 presence
  06_agreement.py         schema gatekeeper + agreement + distributions
```

`01` and `02` are the two funnel stages and each emits its own CONSORT: `01` answers *who is in the study*, `02` answers *whose intubation we can actually see*. Only `02`'s survivors reach the methods.

The only things crossing a notebook boundary are **artifacts on disk** and the **schema contract in §6**. `06_agreement.py` validates the schema of every input on load and fails loudly rather than silently mis-joining.

All notebooks are marimo notebooks stored as `.py`, run as `uv run python code/NN_name.py`, matching the existing consortium convention.

Only `01_cohort.py` knows that `hospitalization_id` exists as a unit. It resolves stitching once and publishes `list_hospitalization_id` in `cohort_index.parquet` as the bridge key; every downstream notebook explodes that list to reach the CLIF tables and aggregates straight back to `encounter_block`. No notebook re-derives a block.

**Dataframe library:** polars throughout, per the root `pyproject.toml`. Two clifpy functions take and return pandas — `stitch_encounters` and `process_resp_support_waterfall` — so `01_cohort.py` converts to pandas immediately before each call and back to polars immediately after. Those are the only two pandas boundaries in the project, both inside `01`.

------------------------------------------------------------------------

## 4. Implementation constraints

The code must be readable by a clinician-researcher reviewing the definition, not only by its author. These are requirements, not preferences.

- **One logical step per marimo cell**, with a markdown cell above it stating what the step does in plain language.
- **No helper functions across notebooks**, and inside a notebook only where a step is genuinely repeated. Prefer an explicit repeated expression over an abstraction that hides the definition being tested.
- **Name intermediate columns explicitly** rather than chaining long expressions. A reviewer must be able to inspect `is_in_window`, `is_target_med`, `delta_minutes`, `rank` as real columns before they are collapsed into the JSON.
- **No clever vectorisation** where a plain filter and join expresses the same thing. Cohort sizes are small enough that clarity wins over speed.
- **Every filter prints its row, encounter-block and patient count** before and after, so the CONSORT and the method yields are visible while running, not only in the final artifact.
- **Each method notebook ends with an explicit schema assertion block** against §6. Copy-pasted deliberately across both — duplication here is the point of D8.
- **No silent defaults.** Every parameter that affects a result is read from `config.json` and echoed at the top of the notebook.

------------------------------------------------------------------------

## 5. Cohort and index event — `01_cohort.py`, `02_index_imv.py`

**The analytic unit is the stitched `encounter_block`, not `hospitalization_id`.** Everything downstream keys on it.

The analytic set is built in two stages, each with its own CONSORT. §5.1–§5.8 cover `01_cohort.py`, which answers *who is in the study*. §5.9–§5.12 cover `02_index_imv.py`, which answers *whose intubation is observable in the record*.

### 5.1 Why stitching comes first

`stitch_encounters` merges hospitalizations separated by less than `stitch_hours` into a single `encounter_block`, which is how an ED presentation and the inpatient admission that follows it become one encounter.

This study is close to a worst case without it. A patient given rocuronium in the ED and first charted on IMV after transfer has `PARA` firing under one `hospitalization_id` while the device transition sits under another. Unstitched, that reads as **methods disagreeing** when it is one intubation split across an administrative boundary — and every disagreement statistic in §8 inherits the artifact. Worse, the same split makes the encounter look *arrived intubated* to §5.9, since the inpatient record opens with an IMV row and the ED pre-period is invisible. Stitching is a correctness requirement here, not a convenience.

### 5.2 Step 0 — the IMV-ever pre-filter

Stitching is expensive: it joins the full hospitalization and ADT tables and iterates to a fixed point. Restrict it to patients who could possibly qualify.

```
  1.  load respiratory_support   columns=['hospitalization_id']
                                 filters={'device_category': ['IMV']}
  2.  distinct hospitalization_id  →  join hospitalization  →  distinct patient_id
  3.  P_imv = patients with ≥1 IMV row anywhere in their record
```

Only `hospitalization` and `adt` rows for `P_imv` are loaded and stitched. This is a **pure efficiency filter and changes no result**: every criterion below requires an IMV row, so a patient with none could never enter the cohort by any path.

The filter is deliberately patient-level, not hospitalization-level. A patient's IMV may be charted under a different `hospitalization_id` than the one that will anchor their encounter block, so filtering hospitalizations here would discard rows that stitching is supposed to reunite.

### 5.3 Stitching

`stitch_encounters(hospitalization, adt, time_interval=stitch_hours)` with `stitch_hours = 6` from config. Takes pandas, returns pandas — the second and last pandas boundary in the project (§3).

Two properties of the returned block, both read from `clifpy/utils/stitching_encounters.py:132-141`, matter downstream:

| Field | Aggregation | Consequence |
|---|---|---|
| `admission_dttm` | `min` across the block | The block clock starts at the earliest admission — this is what the 24h trach window anchors on |
| `discharge_dttm` | `max` across the block | |
| `age_at_admission` | `last` | Age comes from the *last* hospitalization in the block, while the clock starts at the first. Immaterial across a 6h gap, but it is the value the adult criterion tests |
| `list_hospitalization_id` | sorted unique | **The bridge key.** Method notebooks explode this to filter CLIF tables, then aggregate back to `encounter_block` |

### 5.4 CONSORT A — cohort

The first of the two CONSORTs. Reported at **every** step, each with encounter-block and patient counts, so no filter is silent.

```         
  all encounter_blocks for IMV-ever patients            N
    │
    ├─ INCLUSIONS
    │   └─ age_at_admission ≥ 18                       −n₁
    │       └─ date filter (skipped when site is MIMIC) −n₂
    │           └─ ≥1 ADT row, location_category
    │              ∈ {ed, icu}                          −n₃
    │               └─ ≥1 resp row, device_category
    │                  = 'IMV'                          −n₄
    │
    └─ EXCLUSION
        └─ tracheostomy or trach collar within 24h
           of block admission_dttm                      −n₅
             └─ ANALYTIC COHORT                          N*
```

Order matters: CONSORT reports the marginal loss at each step in this sequence, so the sequence is part of the definition. Inclusions are applied before the exclusion so that n₅ counts only patients who would otherwise have qualified.

**Step 0** is itself a CONSORT row — total patients and encounter blocks in the source data, then the count surviving the IMV-ever filter — so the reduction from the full table is visible rather than assumed.

### 5.5 Criterion detail

**Adult** — `age_at_admission ≥ min_age` (default 18) on the stitched block. Note the aggregation caveat from §5.3: `age_at_admission` is taken from the *last* hospitalization in the block while the clock starts at the first. Across a 6h gap the two cannot differ, but the criterion is stated on the value actually tested rather than on an idealised one.

**Date filter** — `site_name.lower() == "mimic"` → **no date restriction** (MIMIC timestamps are date-shifted, so a calendar filter is meaningless). Otherwise → block `admission_dttm` within `date_start` … `date_end`, default `2018-01-01` … `2025-12-31`.

**Location** — at least one ADT row anywhere in the block with `location_category ∈ {ed, icu}`. Both are valid mCIDE values. This is deliberately **ED *or* ICU, not ICU alone**: a substantial share of intubations happen in the ED, and requiring ICU would systematically drop the patients whose induction medications are best documented.

**IMV** — at least one `respiratory_support` row in the block with `device_category = 'IMV'`. Evaluated on the **raw** table, before the waterfall, so cohort membership never depends on an imputed device.

**Tracheostomy exclusion** — exclude the block if, within `[admission_dttm, admission_dttm + trach_window_hours]` (default 24 h), any `respiratory_support` row satisfies **either**:

```
   tracheostomy = True                 the boolean flag
   OR
   device_category = 'Trach Collar'    a distinct mCIDE category
```

> **Both signals are required.** mCIDE defines `Trach Collar` as its own `device_category`, separate from the boolean `tracheostomy` column — and `IMV`'s own mCIDE description reads *"Endotracheal Tube Ventilation, **Tracheostomy Ventilation**"*, so a patient ventilated through a tracheostomy is charted as plain `IMV`. Testing only one signal leaks trach patients into a cohort about intubation. This is catalog §9.3, which no method in the catalog handled.

The `trach_window_hours` clock runs from the **stitched block's** `admission_dttm` (the minimum across the block), not from the individual hospitalization's — otherwise a trach identified in the ED presentation would escape the window of the inpatient admission it was stitched to.

### 5.6 Waterfall and t₀

1.  Subset `respiratory_support` to all hospitalizations listed in the cohort's `list_hospitalization_id`.
2.  Run `process_resp_support_waterfall(..., bfill=False)`.
3.  Map rows to `encounter_block` via `list_hospitalization_id`, then order by `recorded_dttm` **within the block**.
4.  **t₀ = earliest `recorded_dttm` where `device_category == 'IMV'`**, per `encounter_block`.
5.  `window_start = t₀ − window_hours`, `window_end = t₀ + window_hours`.

Step 3 is what makes stitching effective: the waterfall runs per `hospitalization_id`, but the transition sequence `DEV` evaluates is assembled across the whole block in time order.

### 5.7 QC statistics

| Stat | Purpose |
|---|---|
| `Δ = waterfall_t₀ − raw_t₀` — median, IQR, % nonzero | D6 makes a negative Δ very unlikely, but the device/mode heuristics and the hourly `HH:59:59` scaffold run regardless of `bfill`. A negative Δ in any meaningful fraction invalidates the offset distributions and must be resolved before results are read. |
| Blocks per encounter — distribution of `len(list_hospitalization_id)` | Shows how much stitching actually did. If nearly every block is a single hospitalization, stitching is not the mechanism it was added for and that should be known before interpreting §8. |
| % of blocks whose t₀ falls in a *different* `hospitalization_id` than the block's first | The direct measure of the artifact §5.1 exists to remove. |

### 5.8 Outputs of `01`

| File | Contents |
|---|---|
| `cohort.parquet` | one row per included `encounter_block`, with demographics and `list_hospitalization_id` |
| `cohort_resp_waterfall.parquet` | waterfalled respiratory rows for cohort blocks, carrying `encounter_block` |
| `cohort_index.parquet` | `encounter_block`, `patient_id`, `intubation_episode_id`, `cohort_run_id`, `list_hospitalization_id`, `t0_dttm`, `window_start`, `window_end` |
| `consort_cohort.json` / `.csv` | step label, n encounter blocks remaining, n patients remaining, n excluded |
| `cohort_qc.csv` | the three statistics in §5.7 |

`cohort_index.parquet` is consumed by `02` only. The methods read `index_imv.parquet` (§5.12), never this file — reading it directly would silently include the encounters `02` exists to remove.

### 5.9 Index IMV — `02_index_imv.py`

`01` guarantees every cohort encounter has a t₀. It does **not** guarantee that t₀ is an intubation we can see happen. Three quite different situations all produce a first charted IMV row:

- the patient was intubated here, and the record documents the airway before and after — t₀ is a real transition;
- the patient arrived already intubated, so the record opens mid-ventilation and t₀ is merely where charting started;
- the record is too thin around t₀ to tell the two apart.

Only the first supports the question this study asks. Comparing `SED` and `PARA` across all three mixes a measurement of *charting practice at intubation* with a measurement of *who gets transferred intubated*, and the two move in opposite directions: an already-intubated patient has no induction to find, so both methods correctly report nothing, and that correct silence would be scored as agreement about an intubation that never happened here.

`02` therefore applies the M2 symmetric 2/2 rule at t₀ as an **index qualifier**. Source: `cohort_resp_waterfall.parquet`, which already carries `encounter_block`, so no explode is needed. Writing t₀ as row index `i` within the encounter block's waterfalled rows ordered by `recorded_dttm` across all its hospitalizations:

```         
   index qualifies  ≡  ¬IMV(i-2) ∧ ¬IMV(i-1) ∧ IMV(i) ∧ IMV(i+1)
```

**Boundary policy is `B_strict`** — if row `i-2`, `i-1` or `i+1` does not exist, the corresponding term is false and the index does not qualify. This matches the convention the catalog applies to M2 in §3.1 and is stated here rather than inherited from language semantics.

### 5.10 The index taxonomy

Every cohort encounter gets exactly one `index_class`, assigned in this order:

| `index_class` | Condition | Meaning |
|---|---|---|
| `qualified` | the rule above fires | t₀ is a documented, sustained non-IMV → IMV transition |
| `arrived_intubated` | t₀ is the block's **first** respiratory row | no pre-period exists; ventilation predates the record |
| `insufficient_lookback` | exactly one respiratory row precedes t₀ | a pre-period exists but is too thin for a 2-row rule |
| `imv_not_sustained` | row `i+1` is absent or non-IMV | the IMV is a single isolated row — a charting blip, or the encounter ends at t₀ |

The first two are **observability** failures: the data needed to see a transition is not there. The third is a **judgment** failure under M2: the data is there and the rule declines it.

> **`prior_row_imv` is not in this taxonomy, and cannot be.** An earlier draft listed it as a fourth failure — row `i-1` or `i-2` exists but is IMV. That condition is unreachable by construction: t₀ is defined as the *earliest* row with `device_category = 'IMV'` (§5.6), so no row preceding it can be IMV. With t₀ pinned this way, `¬IMV(i-1) ∧ ¬IMV(i-2)` is satisfied automatically whenever those rows exist, and the M2 rule reduces to a lookback-depth test plus a sustain test. The taxonomy above is therefore exhaustive: `qualified` plus three failures is a complete partition of the cohort.

This reduction is also why `DEV` cannot be a peer method (D19). Once t₀ is fixed, the rule has no freedom left to disagree about *when* the intubation was — only to report whether the surrounding rows exist.

### 5.11 CONSORT B — index

The second CONSORT, and a headline result rather than a preprocessing note.

```         
  analytic cohort from 01                             N*
    │
    ├─ EXCLUDE arrived_intubated                      −m₁
    │    t₀ is the block's first respiratory row
    │
    ├─ EXCLUDE insufficient_lookback                  −m₂
    │    fewer than two rows precede t₀
    │
    ├─ EXCLUDE imv_not_sustained                      −m₃
    │    row i+1 absent or non-IMV
    │
    └─ INDEX IMV SET                                  N**
```

Reported alongside it, as a table with rates over `N*` and with patient counts:

| `index_class` | n | % of `N*` |
|---|---|---|
| `qualified` | 1 202 | 54.3 |
| `arrived_intubated` | 698 | 31.5 |
| `insufficient_lookback` | 187 | 8.4 |
| `imv_not_sustained` | 127 | 5.7 |
| **total** | **2 214** | **100.0** |

*(Illustrative shape, not results.)* The `arrived_intubated` rate is the number to read first: catalog §9.4 reports ~31% across sites, so a site landing far from that has either a stitching problem (§5.7) or a genuinely different referral pattern, and which one it is must be settled before `N**` is trusted. `insufficient_lookback` is a charting-density measure — it rises at sites that chart respiratory support sparsely — and is the stratum most sensitive to the waterfall's hourly scaffold.

### 5.12 Outputs of `02`

| File | Contents |
|---|---|
| `index_imv.parquet` | **one row per cohort encounter, not per qualified encounter.** All of `cohort_index.parquet` plus `index_class` and `index_qualified` (bool) |
| `consort_index.json` / `.csv` | the steps in §5.11 with encounter-block and patient counts |
| `index_class_rates.csv` | the stratum table in §5.11 |

Keeping the excluded rows in the file rather than filtering them out is deliberate (D20). The methods run over every row and carry `index_class` into their own output (§6.4); `06` is the single place that splits primary from probe. No notebook ever has to reach back past `02`, and no notebook silently decides the analytic set on its own.

------------------------------------------------------------------------

## 6. Method contract

Each method is a **profiler**, not merely a detector. Anchored on t₀, it reports the ranked medication sequence around the intubation — with dose, unit and lag — from which the binary detection flag falls out for free.

### 6.1 The intubation episode

Every artifact is keyed on `intubation_episode_id`, formed as `{encounter_block}_E1`.

Because this build is scoped to the first IMV episode only (§1), the suffix is **always `E1`** and there is exactly one episode per cohort encounter. The suffix exists so that widening scope to reintubation later adds `_E2` rows without changing any key, join or schema.

`encounter_block` is an int32 seeded from the sorted row index and propagated to a fixed point (`clifpy/utils/stitching_encounters.py:119-131`), so it is unique across the whole site — the library itself joins on it alone at `:151`. It is a valid standalone key.

It is nonetheless **not stable across runs**: the value is a row position, so a site re-extract that adds or removes a hospitalization renumbers every block. Three consequences:

- The episode id is written once into `cohort_index.parquet` and read verbatim downstream. No notebook reconstructs it.
- `01` asserts the key is unique before writing.
- `01` also writes a **`cohort_run_id`** — the ISO timestamp of the run — into `cohort_index.parquet`. `02` carries it into `index_imv.parquet`, every method copies it into its encounter parquet unchanged, and `06_agreement.py` asserts all inputs carry the same value. Without it, joining a `SED` artifact from one cohort run to a `PARA` artifact from another produces a table that is silently wrong: the ids match, the rows are real, and they describe different patients. One column and one assertion close that off.

### 6.2 The ranking rule

Within the window `[window_start, window_end]` from `index_imv.parquet`:

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

One JSON object per intubation episode, emitted by both methods. Written as newline-delimited JSON so it streams and appends cleanly.

```json
{
  "encounter_block": 1001,
  "patient_id": "P042",
  "index_class": "qualified",
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

`delta_minutes` is signed: negative before t₀, positive after. Both arrays are empty when nothing was found; the object is still written, so the file has one record per cohort encounter.

### 6.4 `method_<ID>_encounter.parquet` — joinable

One row per **cohort** encounter, including non-detections and including the encounters `02` excluded. Emitted by both methods. This is what §8 joins on; the JSON is not join-friendly at scale.

> **Why methods run on the excluded encounters too.** Restricting the run to `index_qualified = true` would be the obvious reading of §5.11, and it is wrong here: D20's specificity probe needs the method rates *inside* the excluded strata, and computing them later would mean a second pass over the medication tables under logic that would then exist in two places. Running everything once and carrying `index_class` through costs nothing — the window is already fixed for every cohort encounter by `01` — and leaves the primary/probe split as a single `filter` in `06`. **The subsetting decision lives in `06`, not in the methods.**

| Column | Type | Notes |
|---|---|---|
| `encounter_block` | int32 | the analytic unit |
| `patient_id` | str | carried through for patient-level counts |
| `intubation_episode_id` | str | `{encounter_block}_E1`, copied from `index_imv` |
| `cohort_run_id` | str | copied unchanged from `index_imv`; §6.1 |
| `index_class` | str | copied unchanged from `index_imv`; §5.10 |
| `index_qualified` | bool | copied unchanged from `index_imv` |
| `method_id` | str | `SED` or `PARA` |
| `imv_dttm` | datetime | t₀, copied from `index_imv` |
| `detected` | bool | see below |
| `n_before` | int | count of ranked entries before t₀ |
| `n_after` | int | count of ranked entries after t₀ |
| `nearest_before_med` | str | `med_category` at before-rank 1; null if none |
| `nearest_before_min` | float | `delta_minutes` at before-rank 1; null if none |
| `nearest_after_med` | str | `med_category` at after-rank 1; null if none |
| `nearest_after_min` | float | `delta_minutes` at after-rank 1; null if none |
**`detected` is derived, not independently computed:** `detected = (n_before > 0) OR (n_after > 0)`.

There is no `non_detection_reason` column. For a medication method the reason is always the same — no qualifying `med_category` was charted in the window — so a column carrying one constant string would add a field without adding a fact. The informative non-detection reasons all concern whether the intubation was observable, and those live in `index_class` (§5.10), one stage upstream where they are decided.

Deriving the binary from the ranked structure rather than computing it separately means the two cannot disagree. Non-detections are retained as `detected = false` rows; they are the denominator for every rate in §8.

------------------------------------------------------------------------

## 7. Method definitions

Both methods evaluate against `index_imv.parquet` and are restricted to the window `[window_start, window_end]`. They differ **only** in which `med_category` values they admit — the ranking rule of §6.2 is identical across them, and both read `medication_admin_intermittent`. Neither filters on `index_qualified`; it carries the column through and `06` decides the subset (§6.4).

**How a method reaches the CLIF tables.** CLIF tables are keyed on `hospitalization_id`; the study is keyed on `encounter_block`. Both methods bridge the two the same way, and this is the *only* place a method may mention `hospitalization_id`:

```         
   1.  read index_imv.parquet
   2.  explode list_hospitalization_id      →  one row per (encounter_block, hospitalization_id)
   3.  load the CLIF table filtered to those hospitalization_ids
   4.  join back on hospitalization_id      →  attach encounter_block, t0_dttm, window bounds
   5.  DROP hospitalization_id immediately  →  all logic below is per encounter_block
```

Step 5 is a requirement, not tidiness. A medication given in the ED presentation and an IMV row charted after transfer belong to one encounter; if `hospitalization_id` survives into the window filter or the ranking, the method silently reverts to the unstitched unit and reintroduces exactly the artifact D15 removes. Dropping the column makes that mistake impossible to write rather than merely discouraged.

### `SED` — `03_method_sedative.py`

**Induction medications — the agents used to intubate a patient. All are intermittently dosed.**

Source: `medication_admin_intermittent` **only**, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
midazolam | etomidate | ketamine | propofol | fentanyl
```

Ranked per §6.2. At most 5 before-ranks and 5 after-ranks.

> **`SED` reads the intermittent table only — never the continuous table.** Propofol and fentanyl are also charted as continuous maintenance infusions, but those rows live in `medication_admin_continuous` and are out of scope for this build (§11). An induction bolus and a maintenance infusion are the same drug performing two different clinical acts, distinguished by which table they are charted in. Pulling propofol from both would conflate intubating a patient with sedating one already ventilated.

`med_dose` and `med_dose_unit` are taken verbatim from the administration row. **No unit conversion or dose normalisation is performed** — the raw charted value is what a reviewer needs to see, and normalising would hide unit heterogeneity that is itself worth measuring across sites.

### `PARA` — `04_method_paralytic.py`

Source: `medication_admin_intermittent`, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
rocuronium | succinylcholine | vecuronium
```

Ranked per §6.2. At most 3 before-ranks and 3 after-ranks. Dose handling as for `SED`.

### `DEV` — no method notebook

**The device signal has no notebook in this section.** It is the index qualifier, and it lives in `02_index_imv.py` (§5.9–§5.12) — upstream of every method, where it decides who is analysed rather than competing to be detected.

Nothing about the M2 rule changed in the move; only its role did. Anchored on t₀, the rule can no longer disagree with `SED` and `PARA` about *when* the intubation was, because `01` already fixed t₀ for all of them. What it reports is whether the record documents a pre-period and a sustained IMV — a fact about charting completeness (catalog §9.4). Scored inside an agreement matrix, that fact would have masqueraded as a clinical signal and dragged every κ toward it. See D19, and §5.10 for why the taxonomy has three failure classes rather than the four an earlier draft listed.

------------------------------------------------------------------------

## 8. Reference and agreement

### `05_reference_cpt.py`

Source: `patient_procedures` — `procedure_code`, `procedure_code_format`. Reached by the same explode-and-drop bridge as §7, so a code billed under any hospitalization in the block counts for the encounter. **`billing_provider_id` is not read, and `procedure_billed_dttm` is read only to confirm the row belongs to the encounter — never as an event time.**

| Reference | Format | Code |
|---|---|---|
| `CPT` | CPT | `31500` — emergency endotracheal intubation |

Output: `reference_cpt.parquet` — one row per cohort encounter, keyed on `intubation_episode_id` and carrying `cohort_run_id`, with a `cpt_present` boolean.

Also reports the **code capture rate**: the fraction of the cohort carrying the code. Every metric in Tier C must be read against this number first — where capture is low, the reference is uninformative at that site and is reported as such rather than scored.

> **CPT 31500 is a narrow reference and its ceiling should be stated up front.** It codes *emergency* endotracheal intubation, so elective and operative airway management is not captured, and billing completeness varies by site, payer and era. Sensitivity computed against it is bounded by that capture, not by the method under test — which is precisely why it is a *partial* gold truth and not a peer in the agreement matrix (D1).

### `06_agreement.py`

> **All numbers in the tables below are illustrative shape, not results.** They exist to fix the output format so the notebook can be written and reviewed before any data is run. Real values come from executing the pipeline.

#### Step 0 — the joined analytic table

The notebook validates the schema of each `method_*_encounter.parquet` against §6.4, asserts every input carries the same `cohort_run_id` (§6.1), then joins both plus `reference_cpt.parquet` on `intubation_episode_id`. Every cohort encounter appears exactly once. This wide table is the input to **Tier A** and **Tier C**.

```         
episode_id | index_class           | SED PARA | sed_bef para_bef | cpt
-----------+-----------------------+----------+------------------+-----
 1001_E1   | qualified             |  1    1  |   -4.0     -2.0  |  1
 1002_E1   | qualified             |  1    1  |   -9.0     -6.0  |  1
 1003_E1   | qualified             |  1    0  |  -12.0      NaN  |  0
 1004_E1   | qualified             |  0    0  |    NaN      NaN  |  0
 1005_E1   | arrived_intubated     |  1    0  |   -3.0      NaN  |  0
 1006_E1   | imv_not_sustained     |  0    0  |    NaN      NaN  |  0
-----------+-----------------------+----------+------------------+-----
 N* rows, one per cohort encounter
 *_bef = nearest_before_min (rank 1), signed minutes
 NaN where that direction had no ranked entry
```

**Every table in Tiers A, B and C is computed on `index_class = 'qualified'` only** — the `N**` set from §5.11. This is the single subsetting step in the whole pipeline and it happens here, in one visible filter, so a reader of `06` can see exactly which denominator every rate below uses. The non-qualified rows are used once, in the specificity probe (Tier D), and nowhere else.

**Tier B reads the `method_*_ranked.json` files instead**, because the encounter table carries only rank 1. The full rank ladder — and the per-medication breakdown it enables — lives only in the JSON.

#### Tier A — do the methods find the same patients?

**A.1 Detection rate per method.** The marginal, before any pairing.

| method | detected | n | rate |
|---|---|---|---|
| `SED` | ✓ | 1 043 | 0.87 |
| `PARA` | ✓ | 809 | 0.67 |
| — | index set N\*\* | 1 202 | 1.00 |

**A.2 The 2×2.** One complete contingency table, so κ and Jaccard are recomputable from it by hand — a deliberate auditability property.

|  | `PARA` ✓ | `PARA` ✗ | total |
|---|---|---|---|
| `SED` ✓ | 784 | 259 | 1 043 |
| `SED` ✗ | 25 | 134 | 159 |
| **total** | **809** | **393** | **1 202** |

| pair | both | only `SED` | only `PARA` | neither | Jaccard | Cohen κ |
|---|---|---|---|---|---|---|
| `SED` × `PARA` | 784 | 259 | 25 | 134 | 0.73 | 0.40 |

The two off-diagonal cells are asymmetric and read differently. **Only `SED`** is the expected majority: sedation without paralysis is a real and common technique. **Only `PARA`** should be small — a paralytic given with no induction agent charted is closer to a documentation gap than a clinical choice, so this cell is where charting failure concentrates and its size is worth reporting on its own.

**A.3 Concordance histogram.** How many of the two fired on the same encounter.

| methods firing | n | \% |
|---|---|---|
| 0 | 134 | 11.1 |
| 1 | 284 | 23.6 |
| 2 | 784 | 65.2 |

The `0` row is the one to read first: encounters with a *documented, sustained* intubation — §5.9 guaranteed that much — where neither medication signal fired at all. Because the index qualifier has already removed the arrived-intubated group, this count can no longer be explained away as "the patient came in on a vent". It is a direct measure of intubations performed here whose medications were never charted in the ±3 h window.

> **No upset plot.** With two methods the combination space is four cells and A.2 already shows all of them. An upset plot over two sets carries no information the 2×2 lacks, and drawing one would imply a dimensionality the study no longer has. Removed rather than kept for symmetry with an earlier draft.

#### Tier B — how is charting distributed in time?

Computed by flattening the `method_*_ranked.json` files into a long frame of ranked entries, filtered to `index_class = 'qualified'`. Each episode contributes **at most one entry per medication per direction** (§6.2), so no patient is over-weighted by repeat dosing.

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
| `SED` | `CPT` | 604 | 439 | 61 | 98 | 0.91 | 0.58 | 0.71 |
| `PARA` | `CPT` | 521 | 288 | 144 | 249 | 0.78 | 0.64 | 0.71 |

The block carries a standing caveat in the notebook output: **codes establish presence, never timing** (catalog §12.2), and where capture rate is low the reference is reported as uninformative rather than scored.

> **Read PPV against C.1, not on its own.** At the illustrative 0.50 capture rate, half the index set lacks the code despite having a documented intubation by construction — so most "false positives" are encounters the reference simply failed to code, not encounters the method got wrong. Sensitivity is the more interpretable column here; PPV is bounded above by capture and will look poor for any method regardless of quality.

#### Tier D — specificity probe on the excluded strata

The one place the non-qualified encounters are used (D20). Same methods, same ±3 h window, same code — only the stratum changes.

**D.1 Detection rate by `index_class`.**

| `index_class` | n | `SED` rate | `PARA` rate |
|---|---|---|---|
| `qualified` | 1 202 | 0.87 | 0.67 |
| `arrived_intubated` | 698 | 0.44 | 0.09 |
| `insufficient_lookback` | 187 | 0.61 | 0.38 |
| `imv_not_sustained` | 127 | 0.31 | 0.11 |

*(Illustrative shape, not results.)*

**`arrived_intubated` is the row with a known answer**, and that is what makes this tier worth running. Those patients were intubated before they arrived, so nothing in the ±3 h window around their first charted IMV row can be an induction. Every detection in that row is therefore a false positive **by construction** — no reference, no adjudication and no assumption about coding required. It is the only stratum in the study where the truth is known without a gold standard.

Read the two columns against each other. `PARA` at 0.09 is behaving: paralytics are given to intubate, so they are nearly absent when no intubation happened here. `SED` at 0.44 is the finding — roughly half of already-intubated patients receive a charted sedative in any given 6-hour span, because midazolam, propofol and fentanyl are maintenance ICU drugs as much as induction drugs. That number is the empirical version of the warning in D10, and it belongs in the results rather than in a footnote: **it bounds how much of `SED`'s 0.87 in the qualified stratum is signal and how much is ambient ICU sedation.**

The gap between a method's `qualified` rate and its `arrived_intubated` rate is the sharpest single-number summary of specificity this design can produce, so it is reported explicitly:

| method | qualified | arrived_intubated | gap |
|---|---|---|---|
| `SED` | 0.87 | 0.44 | **0.43** |
| `PARA` | 0.67 | 0.09 | **0.58** |

A method whose gap approaches zero is not detecting intubation at all — it is detecting being in an ICU.

> **What Tier D is not.** The strata differ clinically, not just in observability: arrived-intubated patients are transfers, and transfers differ in acuity, sedation practice and length of stay. The gap is therefore a *bound*, not an unconfounded specificity estimate, and is reported as such. It is still the strongest specificity evidence available without chart review, which is why it is a tier rather than a footnote.

#### Outputs written by `06`

| File | Contents |
|---|---|
| `agreement_detection_rates.csv` | A.1 |
| `agreement_pairwise.csv` | A.2 |
| `agreement_concordance.csv` | A.3 |
| `timing_offset_summary.csv` | B.1 |
| `timing_offset_by_rank.csv` | B.2 |
| `timing_by_medication.csv` | B.3 |
| `timing_offset_distribution.png` | B.4 |
| `reference_capture_rate.csv` | C.1 |
| `reference_scoring.csv` | C.2 |
| `specificity_by_index_class.csv` | D.1 |
| `specificity_gap.csv` | D.1 gap table |

All go to `output/final_no_phi/` and are subject to the n ≥ 10 minimum cell size in §9 — any row of any table with a cell below 10 is suppressed rather than published.

> **The n ≥ 10 rule bites hardest on B.3.** Per-medication breakdowns split the cohort finely — the illustrative `vecuronium` row above shows n = 27, and a rarer agent or a smaller site will fall below 10. Suppression here is row-level: the medication is dropped from the published table rather than pooled into an "other" category, since pooling across agents with different units and dose scales would produce a meaningless median.

------------------------------------------------------------------------

## 9. Outputs and data security

Follows the existing rules in [`output/README.md`](../../../output/README.md) and [`guides/primer.md`](../../../guides/primer.md).

| Directory | Contents |
|------------------------------------|------------------------------------|
| `output/intermediate_phi/` | `cohort.parquet`, `cohort_resp_waterfall.parquet`, `cohort_index.parquet`, `cohort_qc.csv`, `index_imv.parquet`, `method_{SED,PARA}_ranked.json`, `method_{SED,PARA}_encounter.parquet`, `reference_cpt.parquet` |
| `output/final_no_phi/` | both CONSORT count sets, `index_class_rates.csv`, agreement matrices, offset distribution summaries, reference-scored metrics, specificity tables, plots |

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
  "stitch_hours": 6,
  "trach_window_hours": 24,
  "min_age": 18,
  "date_start": "2018-01-01",
  "date_end": "2025-12-31"
}
```

Everything below `output_directory` is new. `date_start` and `date_end` are ignored when `site_name.lower() == "mimic"`.

| Key | Consumed by | Effect |
|---|---|---|
| `window_hours` | `01` | half-width of the t₀ detection window (D4). Written into `cohort_index.parquet` as `window_start` / `window_end` and consumed by `03` and `04` as data, never recomputed (D9). The only parameter that changes a *detection* result, and it applies identically to both medication methods (§6.2) |
| `stitch_hours` | `01` | `time_interval` passed to `stitch_encounters` (D15). Changes the analytic unit itself, so every count in the study moves with it |
| `trach_window_hours` | `01` | the exclusion clock in §5.5 (D18) |
| `min_age` | `01` | the adult criterion, tested on `age_at_admission` |

The last three are **cohort** parameters, not detection parameters: they change who is in the denominator rather than who is detected. `01` echoes all four at the top of the notebook and writes them into `cohort_qc.csv`, so a published result carries the cohort definition that produced it. Everything else is a path or a site label.

------------------------------------------------------------------------

## 11. Out of scope

Recorded so these are visible omissions rather than oversights.

**Removed from an earlier draft of this spec:**

- **The continuous-infusion method `INF`** (whiteboard item 3) — propofol / dexmedetomidine / fentanyl infusion starts. Removed per D1a. Consequently `medication_admin_continuous` is not read anywhere in the pipeline, and `infusion_gap_hours` is not a config key.
- **The ICD reference** — ICD-10-PCS `0BH17EZ`, `0BH18EZ`, `5A1935Z`, `5A1945Z`, `5A1955Z` and ICD-9 `9604`, `9670`–`9672`. Removed per D1b. CPT 31500 is the sole reference.
- **`DEV` as a compared method**, with its own notebook and its rows in the agreement matrix. Not deleted — *relocated* per D19 to `02_index_imv.py`, where the same M2 rule now qualifies the index event instead of competing to detect it. The `prior_row_imv` non-detection reason from that draft was removed outright as unreachable (§5.10).

**Out of scope from the start:**

- Extubation detection of any kind.
- Second and subsequent intubations; reintubation labelling; episode stitching.
- Outcome classification (success / failed / WLST) — catalog M3's tree.
- Tracheostomy handling — no cohort exclusion and no method adjustment.
- The M1 / M3 / M4 device transition rules.
- Pre-waterfall vs post-waterfall sensitivity analysis (settled by D5).
- M5 non-device signals (LPM onset, vent-observation cessation).
- Chart review (catalog Tier 2).