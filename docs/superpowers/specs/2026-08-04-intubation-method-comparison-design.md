# Intubation Detection Method Comparison — Design

**Project:** VentTRACE **Date:** 2026-08-04 **Status:** Design, approved for planning **Companion document:** [`docs/intubation_extubation_methods.md`](../../intubation_extubation_methods.md) — the methods catalog that motivated this build

------------------------------------------------------------------------

## 1. Purpose

The methods catalog established that intubation detection definitions disagree, and quantified that disagreement for one signal source only: the `device_category` transition rule (M1–M4). This project measures a **second, orthogonal axis** — the *signal source* itself.

Three medication signals are compared head to head on the same patients:

| ID | Signal | Whiteboard item | Anchoring | Source table |
|---|---|---|---|---|
| `SED` | Induction agent administration | \(0\) | window, t₀ ± 3 h | `medication_admin_intermittent` |
| `PARA` | Paralytic administration | \(1\) | window, t₀ ± 3 h | `medication_admin_intermittent` |
| `PAIR` | Sedative–paralytic co-administration | \(0\) × \(1\) | **free-running** — whole encounter | `medication_admin_intermittent` |

Two further sources are **not** compared methods. Each does a different job:

| ID | Signal | Whiteboard item | Role | Source table |
|---|---|---|---|---|
| `DEV` | `device_category` transition non-IMV → IMV | \(2\) | **index qualifier** — defines which encounters have an observable intubation at all (§5.9) | `respiratory_support` |
| `CPT` | CPT 31500 present in the encounter | (c1) | **partial gold-truth reference** | `patient_procedures` |

The deliverable answers two questions: **do these signals identify the same patients**, and **how is their charting distributed in time relative to the intubation**. A third question falls out of the index qualifier itself: **on what fraction of ventilated encounters is the intubation visible in the record at all** — the CONSORT of `02_index_imv.py` is a first-class result, not a preprocessing detail.

`PAIR` adds a fourth, which no other signal in this design can answer. `SED`, `PARA` and `DEV` are all pinned to t₀ (D19), so none of them can disagree about *when* the intubation was — only about whether a signal appeared near a time the device already fixed. `PAIR` scans the whole encounter and derives its own intubation timestamp, so it can be asked: **does the medication-derived intubation time agree with the device-derived one, and by how much?**

### Scope

- **Intubation only.** Extubation is out of scope for this build; the catalog already covers it and it can be a later phase.
- **The analytic unit is the stitched encounter**, not `hospitalization_id`. `01_cohort.py` runs `stitch_encounters` first and everything downstream keys on `encounter_block` — see §5.1 for why this is a correctness requirement rather than a convenience.
- **First IMV episode only.** One index event per encounter. Reintubation, *intubation*-episode stitching, and outcome classification are out of scope. (Encounter stitching is in scope and happens first; the two senses of "stitching" are unrelated.)
- **`PAIR` emits many pairs per encounter, but still one analytic row.** The free-running scan finds every sedative–paralytic co-administration in the stay, so its pair-level artifact is not one row per encounter. It collapses to the analytic unit at §7.3 by designating two index pairs (D25). This does not widen the study to reintubation: the extra pairs are *reported*, not *labelled* as intubations.
- **Intermittent medications only.** Both medication methods read `medication_admin_intermittent`. The continuous-infusion signal (whiteboard item 3) is out of scope — see §11.
- **CPT is the sole reference.** ICD procedure codes are out of scope — see §11.
- **Testing target is MIMIC**, with the pipeline written to run at any consortium site via config.

------------------------------------------------------------------------

## 2. Decisions

Each decision below was made explicitly during design. Recorded with rationale so the choice is auditable and reversible.

| \# | Decision | Rationale |
|------------------------|------------------------|------------------------|
| D1 | **Five signals with three distinct roles: three methods under test (`SED`, `PARA`, `PAIR`), one index qualifier (`DEV`), one reference (`CPT`).** Neither `DEV` nor `CPT` enters the agreement matrix. | Catalog §12.2 establishes procedure codes confirm *presence* but never *timing*, and their capture rate varies by site, payer and era. A code cannot be a peer to a timestamped signal. `DEV`'s exclusion has a separate cause — see D19. |
| D1a | **The continuous-infusion method (`INF`) is removed.** | It detects a *state* — "this patient is on sedation, therefore probably ventilated" — not the intubation event. Its signal necessarily lags t₀ and cannot distinguish an intubation from ongoing ICU sedation, so it would contribute detections without contributing evidence about timing. |
| D1b | **The ICD reference is removed; CPT 31500 is the sole reference.** | Removing ICD-10-PCS while keeping ICD-9 would leave a reference that is effectively dead for a 2018–2025 cohort, so the reference is dropped whole rather than partially. One reference also removes the question of what to do when CPT and ICD disagree. |
| D2 | **The device signal uses the M2 symmetric 2/2 rule only**, not all of M1–M4. | The M1–M4 spread is already quantified in the catalog. Re-running it here would measure a known result and obscure the new one. |
| D3 | **Analytic unit is one row per stitched `encounter_block`**, anchored on t₀ = first charted IMV row in the block. | Collapses event matching entirely: no greedy pairing, no order-dependence, no tolerance windows. Agreement becomes a plain binary table; timing becomes offset distributions on a shared axis. |
| D4 | **Detection window is t₀ ± 3 hours**, symmetric. | Set by the study lead. Every method asks the same question over the same interval, so differences are attributable to the signal and not to the window. |
| D5 | **Respiratory pre-processing is fixed: post-waterfall, single policy.** No pre/post grid. | Catalog §12.4 requires the policy be settled before methods are compared. Fixing it in one place makes the agreement numbers mean exactly one thing; changing it later is a config edit, not a rewrite. |
| D6 | **Waterfall runs with `bfill=False`.** | `clifpy/utils/waterfall.py:12` — already the library default; `:58` confirms forward-fill only when False. Backfilling could propagate a device backwards in time and manufacture an IMV row earlier than the first real charting, sliding t₀ and with it every ±3h window. |
| D7 | **No CPT code and no `billing_provider_id` in the cohort definition.** | Explicit study requirement. Distinguishes this cohort from `Induction_Variability_RSI`, which requires both. The CPT code enters only as the reference in notebook `06`. |
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
| D18 | **Tracheostomy in the first 24 h excludes the encounter, tested on two signals: `tracheostomy` truthy *or* `device_category == 'trach collar'`.** | mCIDE defines `IMV` as "Endotracheal Tube Ventilation, **Tracheostomy Ventilation**" — a trach patient on a vent charts as plain `IMV` and would otherwise enter as a false intubation with no induction or paralytic to find. Either signal alone leaks: the boolean misses sites that only chart the device, and `Trach Collar` is a weaning device that a continuously-ventilated trach patient may never receive. |
| D19 | **`DEV` becomes the index qualifier in `02_index_imv.py`, not a method in the agreement matrix.** Encounters whose index IMV fails the M2 rule are excluded before any method runs. | Anchored on t₀, the M2 rule cannot detect a *different* event from `SED` and `PARA` — t₀ is already fixed for all three. All it can report is whether the pre-intubation period was documented and the IMV sustained. That is a statement about record completeness, not an independent signal, so scoring it against medication signals was comparing a data-availability fact to a clinical one. Making it the qualifier puts it where it belongs and leaves `SED` × `PARA` measured on encounters where the intubation is genuinely observable. |
| D20 | **The excluded encounters are retained and analysed, not discarded.** `02` writes a classification for every cohort encounter; §8 runs the method rates over the excluded strata as a specificity probe. | The arrived-intubated group is the sharpest available test of whether `SED` is detecting intubation or ICU sedation: these patients were intubated before arrival, so any `SED` firing in the ±3 h window around their first charted IMV row is by construction *not* an induction. Throwing the group away would discard the one stratum with a known answer. |
| D21 | **Every category column is lower-cased on load, and every literal compared against one is written in lower case.** Applies to `device_category`, `location_category`, `med_category`, `mar_action_category`, `mode_category`, `admission_type_category`, `discharge_category` — every `*_category` column the pipeline touches. | Case is the one vocabulary difference that fails *silently*. A mismatched category value does not raise; it matches zero rows, and a filter matching zero rows looks exactly like a site where the thing never happens. The waterfall already lower-cases four columns (`waterfall.py:147-149`), so the pipeline has two casings in it whether or not we plan for them. Normalising **down** rather than up means the library's own transformation is a no-op instead of something to undo, and there is exactly one rule to remember: lower-case, always. |
| D22 | **Load-time category filters pass every casing variant**, not just the mCIDE spelling. `filters={'device_category': ['IMV', 'imv', 'Imv']}`. | D21 normalises *after* load, but a `from_file` filter runs *before* anything we control — it is applied to raw site data as charted. A site that writes `imv` would be filtered to nothing and silently produce an empty cohort. Passing the variants closes the gap at the only point in the pipeline where our own lower-casing cannot reach, and §5.2 adds a cross-check that proves the filter missed nothing. |
| D23 | **t₀ anchors on the earliest *raw charted* IMV row, not the earliest waterfalled one.** The waterfall is still produced and still supplies the transition sequence §5.9 evaluates — it just no longer decides *when* the intubation was. | Measured on MIMIC: **24.1% of cohort encounters** had a waterfalled t₀ *earlier* than the first charted IMV row (median −17 min, tail to −7.6 h), and 0% had it later. All 8,192 sat on a pre-existing row with `device_category` null and ventilator settings present, which `waterfall.py:199-215` relabels to `imv`. That inference may well be clinically right, but the study treats t₀ as observed fact and centres every ±3 h medication window on it. Anchoring on the charted row also makes t₀ consistent with the inclusion criterion that admitted the encounter (§5.5, raw IMV), so one definition of "IMV row" now serves both. Supersedes the post-waterfall anchor implied by D5; D5 otherwise stands — pre-processing is still fixed and single-policy. |
| D24 | **The reference is gated on capture before it is scored.** `06` computes the capture rate first; if fewer than 10 index-set encounters carry the code, *or* capture falls below **0.05**, `07` writes `reference_scoring.csv` with `informative = false` and null metrics instead of sensitivity and PPV. | Measured on MIMIC: **1 encounter** in the index set of 6,319 carries CPT 31500 (capture 0.0002), because the extract holds 116 CPT rows against 210,000 ICD rows. Scored anyway, that yields a sensitivity computed on a denominator of one — a number that looks like method performance, is quoted as method performance, and is really a statement about which billing systems the site exported. The gate makes "the reference cannot adjudicate here" the published result, which is the true one. The threshold is deliberately low: 0.05 is not a claim that 5% capture is adequate, only that below it the metric is not arguable. |
| D25 | **An administration falling exactly on t₀ belongs to neither direction, and the count is reported.** `[window_start, t₀)` and `(t₀, window_end]` are half-open by §6.2 and stay that way. | Assigning the tie to one side would make `before` and `after` asymmetric for no clinical reason, and assigning it to both would double-count a single event. Silently dropping it, though, is the real hazard — this site charts respiratory support on the hour, which is exactly the condition that makes an exact collision common. Measured: **807 of 32,902** `SED` administrations in-window (2.4%) and **19 of 455** `PARA` (4.2%). Both `SED` and `PARA` print it, so the drop is a stated quantity rather than an invisible one. |
| D26 | **Every figure is drawn from a published table, and where a histogram bin falls in the disclosive range the bin is dropped rather than merged into its neighbour.** | A figure recomputed from the PHI frames could disagree with the CSV beside it, and the reader has no way to tell which is right. Drawing from the published table makes the n ≥ 10 suppression automatic instead of something to reimplement per plot. Merging a suppressed bin into an adjacent one would move mass the reader cannot see move — dropping it and stating the dropped total in the caption keeps the omission visible. |
| D27 | **`PAIR` is a third method under test, and it is free-running: it scans the whole stitched encounter, not the ±3 h window.** t₀ is joined afterwards only to locate each pair on the timeline; it is never an input to detection. | A window-restricted pairing method would be close to redundant — the `SED`✓ ∧ `PARA`✓ cell of the 2×2 already says both fired in that window, so the only new fact would be the gap in minutes. Free-running makes it a genuine third detector: it can find a co-administration the device signal missed entirely, and it produces an independent intubation timestamp (§1). The cost is a denominator that is not comparable to `SED` and `PARA` — addressed by D33 rather than by narrowing the scan. |
| D28 | **The scan is a single forward pass with consumption.** At each administration, look forward to the first *available* opposite-class administration, skipping same-class ones in between; pair if the gap is under threshold; mark both consumed. Advance one step and never look back. | Set by the study lead. Skipping past same-class rows rather than stopping at them means a fentanyl charted before the midazolam still reaches the rocuronium — real charting routinely puts an analgesic ahead of the induction agent. Consumption keeps pairs non-overlapping, so a `pair_id` is countable and one paralytic cannot be the partner in three different pairs. Same-class rows stepped over are *not* consumed, so they get their own turn as the scan advances (§7.3). |
| D29 | **`pair_gap_hours` is its own config key (default 3), not `window_hours` reused. Changing it requires re-running `05`; it cannot be applied post hoc as a filter on the pairs table.** | The two parameters answer different questions and the sibling `Induction_Variability_RSI` study pairs at 5 min for cohort definition and 30 min for its timing sub-analysis, so someone will want to tighten this without moving the detection window. The re-run requirement is a correctness constraint, not a convenience: rejecting a pair leaves **both** rows available, which changes what everything downstream of them pairs with — so a tighter threshold yields a different pair set, not a subset of the current one. A reviewer who sees `gap_minutes` in a column will reach for a filter, so the non-monotonicity is stated where it will be read. |
| D30 | **`PAIR` is exempt from the §6.2 ranking rule and emits no `_ranked.json`.** It emits a pair-level parquet instead. | Ranking is a before/after ladder around a fixed t₀; `PAIR` has no such ladder because its unit is a two-drug event, not a single administration measured against an anchor. Forcing it into the ranked schema would mean inventing a rank for something that has no rank. Consequence: Tier B is computed over `SED` and `PARA` only, and `PAIR` gets its own tier (Tier E). |
| D31 | **Two index pairs are reported per encounter, not one: the first pair chronologically and the pair nearest t₀.** Whether they are the same pair is itself a statistic. | The first pair tests t₀ — it is the earliest sedative–paralytic co-administration of the stay and therefore the medication signal's own candidate for the intubation, free to disagree with the device. The nearest pair keeps a reading tied to the IMV episode this study is about, whose offset is small by construction. Each alone discards what the other measures; `first_is_nearest` turns the redundancy into a result about how much pairing activity precedes the index intubation. |
| D32 | **Unpaired administrations survive as counts on the encounter row only.** There is no administration-level audit artifact. | Every table in §8 is computable from the pairs table and the two counts, so a third artifact would carry no consumer — and D14 already established that an unconsumed artifact invites drift. The trade is real and is accepted with eyes open: the scan is order-dependent and consuming, so a bug in the advance-and-consume logic cannot be caught by inspecting the outputs. §4's per-step count printing is the mitigation, and the worked examples in §7.3 are the test cases. |
| D33 | **With three methods, `A.2` becomes three pairwise 2×2 tables plus an eight-row combination table; the "no upset plot" note of the two-method draft is superseded.** | Three sets have eight combinations, which a single 2×2 can no longer show. The eight-row table carries the same information an upset plot would, stays a CSV subject to the n ≥ 10 rule in §9, and does not require a figure. The `PAIR` column of that table must be read against D27: it is free-running while the other two are windowed, so `detected_in_window` is reported alongside `detected` (§7.3) to make the comparison available on a matched denominator. |

------------------------------------------------------------------------

## 3. Architecture

```         
code/
  01_cohort.py            encounter stitch + cohort CONSORT + waterfall + t₀ + window bounds
  02_index_imv.py         index CONSORT — is the intubation observable? (DEV, M2 rule)
  03_method_sedative.py   ┐  each fully self-contained:
  04_method_paralytic.py  │  config → index_imv + ONE CLIF table
  05_method_pair.py       ┘  → own logic → artifacts → assert own schema
  06_reference_cpt.py     CPT 31500 presence
  07_agreement.py         schema gatekeeper + agreement + distributions
```

`01` and `02` are the two funnel stages and each emits its own CONSORT: `01` answers *who is in the study*, `02` answers *whose intubation we can actually see*. Only `02`'s survivors reach the methods.

The only things crossing a notebook boundary are **artifacts on disk** and the **schema contract in §6**. `07_agreement.py` validates the schema of every input on load and fails loudly rather than silently mis-joining.

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
- **Each method notebook ends with an explicit schema assertion block** against §6. Copy-pasted deliberately across all three — duplication here is the point of D8. `05` asserts the core columns plus the pair extension (§6.5); `03` and `04` assert the core plus the ranked extension.
- **No silent defaults.** Every parameter that affects a result is read from `config.json` and echoed at the top of the notebook.
- **Lower-case every category column immediately after load, in a single named step, before any comparison** (D21). Every literal in the notebook is then written in lower case — `'imv'`, `'trach collar'`, `'ed'`, `'icu'`, `'given'`. A notebook that compares against a mixed-case literal anywhere has a bug that will not announce itself.
- **Every category filter must be provably non-empty.** A `filter` that returns zero rows is the expected result at a site where the thing never happens and the symptom of a vocabulary mismatch at a site where it happens constantly. Notebooks assert non-empty and print the distinct values seen, so the two cases are distinguishable without reading the data by hand.

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
  1.  load respiratory_support   columns=['hospitalization_id', 'device_category']
                                 filters={'device_category': ['IMV', 'imv', 'Imv']}
  2.  lower-case device_category, then keep == 'imv'
  3.  distinct hospitalization_id  →  join hospitalization  →  distinct patient_id
  4.  P_imv = patients with ≥1 IMV row anywhere in their record
```

**Step 1 lists casing variants; step 2 does the real matching** (D22). The `from_file` filter is the one comparison in the pipeline that happens *before* our own normalisation, on raw site data as charted, so it is the one place D21 cannot protect. A site charting `imv` would otherwise load zero rows and produce an empty cohort with no error.

The variant list is still a guess about a site's vocabulary, so it is **cross-checked rather than trusted**. The cohort respiratory load in §5.5 is *unfiltered* by category — it pulls every row for the cohort's hospitalizations. Lower-casing `device_category` there and recounting the encounters with an `'imv'` row must reproduce the set this step produced. If it does not, the filter missed a casing and the notebook fails rather than reporting a quietly undersized cohort.

Only `hospitalization` and `adt` rows for `P_imv` are loaded and stitched. This is a **pure efficiency filter and changes no result**: every criterion below requires an IMV row, so a patient with none could never enter the cohort by any path.

The filter is deliberately patient-level, not hospitalization-level. A patient's IMV may be charted under a different `hospitalization_id` than the one that will anchor their encounter block, so filtering hospitalizations here would discard rows that stitching is supposed to reunite.

### 5.3 Stitching

`stitch_encounters(hospitalization, adt, time_interval=stitch_hours)` with `stitch_hours = 6` from config. Takes pandas, returns pandas — the second and last pandas boundary in the project (§3).

**What the function actually returns is narrower than it looks.** `clifpy/utils/stitching_encounters.py:178` returns `(hospitalization_stitched, adt_stitched, encounter_mapping)` — the first two are the input tables with an `encounter_block` column appended, the third is the `hospitalization_id → encounter_block` map. The block-level aggregate the function builds internally at `:136-144` (`hospital_block2`, carrying `list_hospitalization_id` and the min/max block window) is **never returned**. `01` therefore derives the block table itself from `hospitalization_stitched`, which is one explicit `group_by` and is better for this study than inheriting the library's:

| Field | Aggregation `01` uses | Why not the library's |
|---|---|---|
| `admission_dttm` | `min` | same |
| `discharge_dttm` | `max` | same |
| `age_at_admission` | value from the row with the **minimum** `admission_dttm` | the library takes `last`, pairing an age from the end of the block with a clock that starts at its beginning. Immaterial across a 6 h gap, but there is no reason to inherit the mismatch when the correct value is the same one line of code |
| `list_hospitalization_id` | sorted unique | same |

Two consequences matter downstream:

- **`admission_dttm` is the block's earliest admission.** This is what the `trach_window_hours` clock anchors on, so a trach charted during an ED presentation is inside the window of the inpatient admission stitched to it.
- **`list_hospitalization_id` is the bridge key.** Method notebooks explode it to filter CLIF tables, then aggregate back to `encounter_block` (§7).

### 5.4 CONSORT A — cohort

The first of the two CONSORTs. Reported at **every** step, each with encounter-block and patient counts, so no filter is silent.

```         
  all encounter_blocks for IMV-ever patients            N
    │
    ├─ INCLUSIONS
    │   └─ age_at_admission ≥ 18                       −n₁
    │       └─ date filter (skipped when site is MIMIC) −n₂
    │           └─ ≥1 ADT row, location_category
    │              ∈ {'ed', 'icu'}                       −n₃
    │               └─ ≥1 resp row, device_category
    │                  == 'imv'                          −n₄
    │
    └─ EXCLUSION
        └─ tracheostomy or trach collar within 24h
           of block admission_dttm                      −n₅
             └─ ANALYTIC COHORT                          N*
```

Order matters: CONSORT reports the marginal loss at each step in this sequence, so the sequence is part of the definition. Inclusions are applied before the exclusion so that n₅ counts only patients who would otherwise have qualified.

**Step 0** is itself a CONSORT row — total patients and encounter blocks in the source data, then the count surviving the IMV-ever filter — so the reduction from the full table is visible rather than assumed.

### 5.5 Criterion detail

**Adult** — `age_at_admission ≥ min_age` (default 18) on the stitched block, taking the age from the block's earliest hospitalization so that age and clock come from the same row (§5.3).

**Date filter** — `site_name.lower() == "mimic"` → **no date restriction** (MIMIC timestamps are date-shifted, so a calendar filter is meaningless). Otherwise → block `admission_dttm` within `date_start` … `date_end`, default `2018-01-01` … `2025-12-31`.

All category comparisons below are on the **lower-cased** column against a lower-case literal (D21).

**Location** — at least one ADT row anywhere in the block with `location_category ∈ {'ed', 'icu'}`. Both are valid mCIDE values, already lower case in mCIDE. This is deliberately **ED *or* ICU, not ICU alone**: a substantial share of intubations happen in the ED, and requiring ICU would systematically drop the patients whose induction medications are best documented.

**IMV** — at least one `respiratory_support` row in the block with `device_category == 'imv'`. Evaluated on the **raw** table, before the waterfall, so cohort membership never depends on an imputed device.

**Tracheostomy exclusion** — exclude the block if, within `[admission_dttm, admission_dttm + trach_window_hours]` (default 24 h), any `respiratory_support` row satisfies **either**:

```
   tracheostomy is truthy              the boolean flag
   OR
   device_category == 'trach collar'   a distinct mCIDE category, lower-cased
```

`tracheostomy` is tested for truthiness rather than `is True` because the waterfall coerces it to `1.0` / `0.0` (`waterfall.py:152-159`). This exclusion runs on the raw table where it is still a boolean, but writing the test so it survives either representation costs nothing and removes a trap for anyone who later moves the check downstream.

> **Both signals are required.** mCIDE defines `Trach Collar` as its own `device_category`, separate from the boolean `tracheostomy` column — and `IMV`'s own mCIDE description reads *"Endotracheal Tube Ventilation, **Tracheostomy Ventilation**"*, so a patient ventilated through a tracheostomy is charted as plain `IMV`. Testing only one signal leaks trach patients into a cohort about intubation. This is catalog §9.3, which no method in the catalog handled.

The `trach_window_hours` clock runs from the **stitched block's** `admission_dttm` (the minimum across the block), not from the individual hospitalization's — otherwise a trach identified in the ED presentation would escape the window of the inpatient admission it was stitched to.

### 5.6 Waterfall and t₀

1.  Subset `respiratory_support` to all hospitalizations listed in the cohort's `list_hospitalization_id`.
2.  **t₀ = earliest `recorded_dttm` where `device_category == 'imv'` on the RAW table**, per `encounter_block` (D23).
3.  Run `process_resp_support_waterfall(..., bfill=False)` on the same rows.
4.  Map waterfalled rows to `encounter_block` via `list_hospitalization_id`, then order by `recorded_dttm` **within the block**.
5.  `window_start = t₀ − window_hours`, `window_end = t₀ + window_hours`.

**t₀ and the transition sequence come from different frames, deliberately.** t₀ is a charted fact and comes from the raw table — the same rows and the same comparison that admitted the encounter in §5.5, so one definition of "IMV row" serves both. The waterfall still runs and still supplies the ordered device sequence §5.9 evaluates, which is what it is genuinely good at: it makes the record continuous so a transition can be read off it. What it no longer does is decide *when* the intubation was.

> **What this cost.** Under the earlier post-waterfall anchor, 24.1% of MIMIC encounters had t₀ set by `waterfall.py:199-215` relabelling a null-device row to `imv`, always earlier than the charted row, median −17 min with a tail past −7 h. Every one of those 8,192 encounters would have had its ±3 h medication window centred on an inference. See D23.

Step 3 is what makes stitching effective: the waterfall runs per `hospitalization_id`, but the transition sequence §5.9 evaluates is assembled across the whole block in time order.

> **This is where D21 pays for itself.** `clifpy/utils/waterfall.py:147-149` **lower-cases** `device_category`, `device_name`, `mode_category` and `mode_name`. Under a spec that compared against mCIDE casing, that single line would silently break t₀: `device_category == 'IMV'` on waterfalled data does not error, it matches nothing, and every encounter comes back with a null t₀.
>
> Because D21 already lower-cased the column on load, the waterfall's transformation is a **no-op** — the values it writes are the values that were there. No step re-normalises anything, no notebook holds two vocabularies, and the same literal `'imv'` is correct on both sides of the call.
>
> The library also coerces `tracheostomy` to `1.0` / `0.0` with `pd.to_numeric` (`:152-159`), which is why §5.5 tests truthiness rather than identity.
>
> **This is worth stating as a general property, not a note about one function.** Normalising to a *canonical* vocabulary means every library that touches the data must be checked for whether it agrees with that canon. Normalising *down* means the only libraries that can hurt you are the ones that upper-case — and none do, because lower-casing is the near-universal convention. The rule is cheaper to hold than the exceptions to it.

### 5.7 QC statistics

| Stat | Purpose |
|---|---|
| `Δ = waterfall_t₀ − raw_t₀` — median, IQR, % negative | No longer a hazard check — D23 anchors on `raw_t₀`, so Δ cannot move a window. It is retained as the **direct measurement of how far the device heuristics disagree with charting**, and it is the quantity D23 was decided on. Δ > 0 is impossible by construction: forward-fill can only carry a device later in time and nothing deletes the charted row, so any nonzero Δ is the heuristic relabelling a null-device row earlier. A site with a Δ profile very different from MIMIC's 24.1% should revisit D23 rather than inherit it. |
| Timestamp alignment — every non-scaffold waterfalled row exists in the raw table, per hospitalization | The waterfall adds rows only at `HH:59:59`; it never invents a timestamp elsewhere. If the raw and waterfalled frames are converted from clifpy by different paths this subset relation breaks immediately, which is how the pytz/LMT one-hour bug was caught (§5.13). |
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

Only the first supports the question this study asks. Comparing `SED` and `PARA` across all three mixes a measurement of *charting practice at intubation* with a measurement of *who gets transferred intubated*, and the two move in opposite directions: an already-intubated patient has no induction to find, so the medication methods correctly report nothing, and that correct silence would be scored as agreement about an intubation that never happened here.

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
| `prior_row_imv` | row `i-1` or `i-2` is IMV **in the waterfall** | the settings say ventilated before the device was ever charted — t₀ is not the transition |
| `imv_not_sustained` | row `i+1` is absent or non-IMV | the IMV is a single isolated row — a charting blip, or the encounter ends at t₀ |

The first two are **observability** failures: the data needed to see a transition is not there. The last two are **judgment** failures under M2: the data is there and the rule declines it.

> **`prior_row_imv` exists only because of D23, and it is the interesting class.** While t₀ was the earliest *waterfalled* IMV row, this condition was unreachable by construction — nothing before the earliest IMV row can be IMV — and an earlier draft removed it as dead. Anchoring on the earliest *raw charted* row makes it live again, and what it now detects is precise: **the encounters where the waterfall's device heuristics say "ventilated" before any clinician charted a ventilator.**
>
> That is the same population D23 was decided on, seen from the other side. Under the old anchor those 24.1% silently became t₀ and dragged their medication window with them. Under D23 they keep an honest t₀ and are *labelled* — the disagreement between inference and charting becomes a reportable stratum instead of an invisible shift.
>
> The taxonomy is a complete partition: `qualified` plus four failure classes, assigned in the order listed.

None of this makes `DEV` a peer method (D19). Once t₀ is fixed by charting, the rule still has no freedom to disagree about *when* the intubation was — only to report what the surrounding rows look like.

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
    ├─ EXCLUDE prior_row_imv                          −m₃
    │    waterfall says IMV before the charted row
    │
    ├─ EXCLUDE imv_not_sustained                      −m₄
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

Keeping the excluded rows in the file rather than filtering them out is deliberate (D20). The methods run over every row and carry `index_class` into their own output (§6.4); `07` is the single place that splits primary from probe. No notebook ever has to reach back past `02`, and no notebook silently decides the analytic set on its own.

------------------------------------------------------------------------

## 6. Method contract

Each method is a **profiler**, not merely a detector. Anchored on t₀, it reports the ranked medication sequence around the intubation — with dose, unit and lag — from which the binary detection flag falls out for free.

### 6.1 The intubation episode

Every encounter-level artifact is keyed on `intubation_episode_id`, formed as `{encounter_block}_E1`.

Because this build is scoped to the first IMV episode only (§1), the suffix is **always `E1`** and there is exactly one episode per cohort encounter. The suffix exists so that widening scope to reintubation later adds `_E2` rows without changing any key, join or schema.

`method_PAIR_pairs.parquet` is the one artifact that is *not* one row per episode (§6.5). Its own key is `pair_id`, formed as `{encounter_block}_P{pair_seq}`, and it carries `intubation_episode_id` as a foreign key so it still joins to everything else. The two id schemes are deliberately distinct in both separator letter and cardinality — `_E` is one per encounter, `_P` is many — so a mis-join fails on the key rather than silently fanning rows out.

`encounter_block` is an int32 seeded from the sorted row index and propagated to a fixed point (`clifpy/utils/stitching_encounters.py:119-131`), so it is unique across the whole site — the library itself joins on it alone at `:151`. It is a valid standalone key.

It is nonetheless **not stable across runs**: the value is a row position, so a site re-extract that adds or removes a hospitalization renumbers every block. Three consequences:

- The episode id is written once into `cohort_index.parquet` and read verbatim downstream. No notebook reconstructs it.
- `01` asserts the key is unique before writing.
- `01` also writes a **`cohort_run_id`** — the ISO timestamp of the run — into `cohort_index.parquet`. `02` carries it into `index_imv.parquet`, every method copies it into its encounter parquet unchanged, and `07_agreement.py` asserts all inputs carry the same value. Without it, joining a `SED` artifact from one cohort run to a `PARA` artifact from another produces a table that is silently wrong: the ids match, the rows are real, and they describe different patients. One column and one assertion close that off.

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

> **§6.2 governs `SED` and `PARA` only. `PAIR` does not rank (D30).** Ranking is a before/after ladder around a fixed t₀, and `PAIR`'s unit is a two-drug event rather than a single administration measured against an anchor — there is nothing for a rank to order. `PAIR` is also not window-restricted (D27), so the `[window_start, t₀)` / `(t₀, window_end]` split that §6.2 is built on does not apply to it. Its scan is defined in §7.3 and its artifacts in §6.5.

### 6.3 `method_<ID>_ranked.json` — canonical, `SED` and `PARA` only

One JSON object per intubation episode, emitted by `SED` and `PARA`. **`PAIR` emits no ranked JSON** (D30). Written as newline-delimited JSON so it streams and appends cleanly.

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

One row per **cohort** encounter, including non-detections and including the encounters `02` excluded. Emitted by all three methods. This is what §8 joins on; the JSON is not join-friendly at scale.

The table below has two parts. The **core columns** (`encounter_block` through `detected`) are emitted by every method and are what `07` validates on load. The **ranked columns** (`n_before` through `nearest_after_min`) are emitted by `SED` and `PARA` only; `PAIR` replaces them with the pair columns of §6.5. A method is validated against the core plus exactly one extension, never both.

> **Why methods run on the excluded encounters too.** Restricting the run to `index_qualified = true` would be the obvious reading of §5.11, and it is wrong here: D20's specificity probe needs the method rates *inside* the excluded strata, and computing them later would mean a second pass over the medication tables under logic that would then exist in two places. Running everything once and carrying `index_class` through costs nothing — the window is already fixed for every cohort encounter by `01` — and leaves the primary/probe split as a single `filter` in `07`. **The subsetting decision lives in `07`, not in the methods.**

| Column | Type | Notes |
|---|---|---|
| `encounter_block` | int32 | the analytic unit |
| `patient_id` | str | carried through for patient-level counts |
| `intubation_episode_id` | str | `{encounter_block}_E1`, copied from `index_imv` |
| `cohort_run_id` | str | copied unchanged from `index_imv`; §6.1 |
| `index_class` | str | copied unchanged from `index_imv`; §5.10 |
| `index_qualified` | bool | copied unchanged from `index_imv` |
| `method_id` | str | `SED`, `PARA` or `PAIR` |
| `imv_dttm` | datetime | t₀, copied from `index_imv` |
| `detected` | bool | see below |
| — | | *ranked extension — `SED` and `PARA` only* |
| `n_before` | int | count of ranked entries before t₀ |
| `n_after` | int | count of ranked entries after t₀ |
| `nearest_before_med` | str | `med_category` at before-rank 1; null if none |
| `nearest_before_min` | float | `delta_minutes` at before-rank 1; null if none |
| `nearest_after_med` | str | `med_category` at after-rank 1; null if none |
| `nearest_after_min` | float | `delta_minutes` at after-rank 1; null if none |
**`detected` is derived, not independently computed:** `detected = (n_before > 0) OR (n_after > 0)`.

There is no `non_detection_reason` column. For a medication method the reason is always the same — no qualifying `med_category` was charted in the window — so a column carrying one constant string would add a field without adding a fact. The informative non-detection reasons all concern whether the intubation was observable, and those live in `index_class` (§5.10), one stage upstream where they are decided.

Deriving the binary from the ranked structure rather than computing it separately means the two cannot disagree. Non-detections are retained as `detected = false` rows; they are the denominator for every rate in §8.

For `PAIR` the same principle holds with a different source structure: `detected = n_pairs > 0`, derived from the pairs table rather than computed alongside it (§6.5).

### 6.5 `PAIR` artifacts

`PAIR` emits two files. The pair-level table is canonical — the encounter table is derived from it entirely, so the two cannot disagree.

**`method_PAIR_pairs.parquet` — canonical, one row per pair.** Not one row per encounter: an encounter with no pairs contributes no rows here, and a long stay may contribute many. Ordered by `encounter_block`, then `pair_seq`.

| Column | Type | Notes |
|---|---|---|
| `encounter_block` | int32 | the analytic unit |
| `patient_id` | str | |
| `intubation_episode_id` | str | copied from `index_imv` |
| `cohort_run_id` | str | copied unchanged; §6.1 |
| `index_class` | str | copied unchanged; §5.10 |
| `index_qualified` | bool | copied unchanged |
| `pair_id` | str | `{encounter_block}_P{pair_seq}` |
| `pair_seq` | int | 1-based, in scan order within the encounter |
| `first_class` | str | `SED`, `PARA`, or `SIMULTANEOUS` when the gap is exactly zero |
| `sed_med_category` | str | the sedative member |
| `sed_med_dose` | float | verbatim from the administration row |
| `sed_med_dose_unit` | str | verbatim |
| `sed_admin_dttm` | datetime | |
| `para_med_category` | str | the paralytic member |
| `para_med_dose` | float | verbatim |
| `para_med_dose_unit` | str | verbatim |
| `para_admin_dttm` | datetime | |
| `pair_dttm` | datetime | the **earlier** of the two administrations — the pair's own intubation timestamp |
| `gap_minutes` | float | `abs(sed_admin_dttm − para_admin_dttm)`, always ≥ 0 and always `< pair_gap_hours × 60` |
| `imv_dttm` | datetime | t₀, copied from `index_imv` |
| `pair_to_t0_min` | float | signed: `pair_dttm − imv_dttm`, negative before t₀ |
| `in_window` | bool | `pair_dttm` falls within `[window_start, window_end]` |

`in_window` is the only place `PAIR` touches the ±3 h window, and it is descriptive rather than restrictive — the scan already ran over the whole encounter (D27). It exists so `07` can report the free-running and window-matched readings side by side without a second pass.

**`method_PAIR_encounter.parquet` — one row per cohort encounter.** Core columns of §6.4 plus the pair extension below, replacing the ranked columns. `detected` is `n_pairs > 0`.

| Column | Type | Notes |
|---|---|---|
| `n_pairs` | int | 0 for a non-detection |
| `n_unpaired_sed` | int | sedative administrations the scan never paired (D32) |
| `n_unpaired_para` | int | paralytic administrations the scan never paired |
| `detected_in_window` | bool | any pair with `in_window`; the matched-denominator reading (D33) |
| `first_is_nearest` | bool | whether the two index pairs are the same pair; null when `n_pairs = 0` |
| `first_pair_id` … | | the **first pair chronologically** — `pair_id`, `first_class`, `sed_med_category`, `sed_med_dose`, `sed_med_dose_unit`, `para_med_category`, `para_med_dose`, `para_med_dose_unit`, `gap_minutes`, `pair_to_t0_min`, each prefixed `first_` |
| `near_pair_id` … | | the **pair nearest t₀** — same ten fields, each prefixed `near_` |

Both index-pair blocks are null throughout when `n_pairs = 0`. Ties for the nearest pair — two pairs equidistant from t₀ — are broken by taking the earlier one, so output is deterministic (§6.2 convention).

> **Why both index pairs, and not one (D31).** The first pair is the medication signal's own candidate for the intubation, chosen without reference to t₀, so `first_pair_to_t0_min` is free to be large and is a genuine test of the device-derived anchor. The nearest pair is tied to the IMV episode the study is about, so `near_pair_to_t0_min` is small by construction and measures charting proximity instead. Reporting one alone discards what the other measures. `first_is_nearest` converts the overlap into a result: the fraction of encounters where the earliest sedative–paralytic co-administration of the stay *is* the one at the index intubation.

------------------------------------------------------------------------

## 7. Method definitions

All three methods evaluate against `index_imv.parquet` and read `medication_admin_intermittent`. None filters on `index_qualified`; each carries the column through and `07` decides the subset (§6.4).

They split into two shapes:

- **`SED` (§7.1) and `PARA` (§7.2)** are window-restricted ranked profilers. They are restricted to `[window_start, window_end]` and differ **only** in which `med_category` values they admit — the ranking rule of §6.2 is identical across them.
- **`PAIR` (§7.3)** is a free-running pair scanner. It admits both lists at once, ignores the window during detection, and ranks nothing (D27, D30).

**How a method reaches the CLIF tables.** CLIF tables are keyed on `hospitalization_id`; the study is keyed on `encounter_block`. All three methods bridge the two the same way, and this is the *only* place a method may mention `hospitalization_id`:

```         
   1.  read index_imv.parquet
   2.  explode list_hospitalization_id      →  one row per (encounter_block, hospitalization_id)
   3.  load the CLIF table filtered to those hospitalization_ids
   4.  LOWER-CASE med_category and mar_action_category    (D21)
   5.  join back on hospitalization_id      →  attach encounter_block, t0_dttm, window bounds
   6.  DROP hospitalization_id immediately  →  all logic below is per encounter_block
```

Step 4 comes before any medication filtering, and the method's `med_category` list is written in lower case to match. Unlike §5.2 the medication load is **not** filtered on `med_category` at load time — the lists are short enough that filtering after lower-casing is both cheaper to reason about and immune to the casing hole D22 exists to patch. The `hospitalization_id` filter still applies at load.

Step 5 is a requirement, not tidiness. A medication given in the ED presentation and an IMV row charted after transfer belong to one encounter; if `hospitalization_id` survives into the window filter or the ranking, the method silently reverts to the unstitched unit and reintroduces exactly the artifact D15 removes. Dropping the column makes that mistake impossible to write rather than merely discouraged.

### 7.1 `SED` — `03_method_sedative.py`

**Induction medications — the agents used to intubate a patient. All are intermittently dosed.**

Source: `medication_admin_intermittent` **only**, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
midazolam | etomidate | ketamine | propofol | fentanyl
```

Ranked per §6.2. At most 5 before-ranks and 5 after-ranks.

> **`SED` reads the intermittent table only — never the continuous table.** Propofol and fentanyl are also charted as continuous maintenance infusions, but those rows live in `medication_admin_continuous` and are out of scope for this build (§11). An induction bolus and a maintenance infusion are the same drug performing two different clinical acts, distinguished by which table they are charted in. Pulling propofol from both would conflate intubating a patient with sedating one already ventilated.

`med_dose` and `med_dose_unit` are taken verbatim from the administration row. **No unit conversion or dose normalisation is performed** — the raw charted value is what a reviewer needs to see, and normalising would hide unit heterogeneity that is itself worth measuring across sites.

### 7.2 `PARA` — `04_method_paralytic.py`

Source: `medication_admin_intermittent`, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
rocuronium | succinylcholine | vecuronium
```

Ranked per §6.2. At most 3 before-ranks and 3 after-ranks. Dose handling as for `SED`.

### 7.3 `PAIR` — `05_method_pair.py`

**Sedative–paralytic co-administration. The question is not "was a drug given near the intubation" but "were the two drug classes given together, and where in the stay".**

Source: `medication_admin_intermittent`, filtered to `mar_action_category = 'given'` and `med_category` in the **union** of the two lists, with each administration labelled by class:

```         
   class = SED    midazolam | etomidate | ketamine | propofol | fentanyl
   class = PARA   rocuronium | succinylcholine | vecuronium
```

The lists are re-declared literally in `05_method_pair.py` and not imported from `03` or `04` (D8). They must stay identical to §7.1 and §7.2 — the schema assertion block at the end of the notebook checks the declared lists against the values actually present in the output.

**The scan is not restricted to the window.** It runs over every qualifying administration in the stitched encounter, ordered by `admin_dttm` with ties broken alphabetically by `med_category` (§6.2 convention). t₀ is joined afterwards to compute `pair_to_t0_min` and `in_window`, and plays no part in which pairs form (D27).

#### The pairing rule

A single forward pass with consumption (D28):

```
   available[0..n-1] = True
   seq = 0

   for i in 0 .. n-1:
       if not available[i]:  continue
       j = smallest index > i  where  available[j]  and  class(j) != class(i)
       if j exists  and  (t[j] - t[i]) < pair_gap_hours:
           seq += 1
           emit pair (i, j) as pair_seq = seq
           available[i] = False
           available[j] = False
       # advance to i+1 either way — never look back
```

Three properties are load-bearing and each is a place the implementation could plausibly go wrong:

1. **Same-class administrations are stepped over, not stopped at.** `j` is the first *opposite-class* row, not the adjacent row. A fentanyl charted ahead of the midazolam still reaches the rocuronium — real charting routinely puts an analgesic first.
2. **Same-class administrations stepped over are not consumed.** They remain `available` and get their own turn as `i` advances, which is how a second sedative pairs with a second paralytic.
3. **A consumed row is never reconsidered**, in either direction. The pass is strictly forward and each administration belongs to at most one pair, so `pair_id` is countable.

Pairing is symmetric in class: a paralytic looks forward for a sedative exactly as a sedative looks forward for a paralytic. `first_class` records which came first, or `SIMULTANEOUS` when `gap_minutes` is exactly zero — a same-minute charting that carries no order information and should not be assigned one.

#### Worked examples

These are the test cases for the implementation. Each is stated as input rows and expected pairs.

```
(a)  the motivating case — analgesic ahead of the induction agent
     fent 03:00(S)   midaz 03:01(S)   roc 03:02(P)   propofol 03:40(S)

     i=0 fent   -> first available PARA = roc, Δ 2 min   -> PAIR 1, consume fent + roc
     i=1 midaz  -> no available PARA ahead              -> no pair
     i=2 roc    -> consumed, skip
     i=3 prop   -> no available PARA ahead              -> no pair

     pairs: 1   (sed=fentanyl, para=rocuronium, gap 2.0, first_class SED)
     unpaired: 2 SED, 0 PARA

(b)  consumption frees the next pairing — two paralytics
     fent 03:00(S)   midaz 03:01(S)   roc 03:02(P)   vec 03:03(P)

     i=0 fent   -> roc, Δ 2 min   -> PAIR 1, consume fent + roc
     i=1 midaz  -> vec, Δ 2 min   -> PAIR 2, consume midaz + vec

     pairs: 2   unpaired: 0 SED, 0 PARA

(c)  paralytic first
     roc 03:00(P)    etom 03:01(S)

     pairs: 1   (sed=etomidate, para=rocuronium, gap 1.0, first_class PARA)

(d)  same minute
     etom 03:00(S)   roc 03:00(P)

     pairs: 1   (gap 0.0, first_class SIMULTANEOUS)

(e)  gap exceeds threshold — no pair, and neither row is consumed
     etom 03:00(S)   roc 07:00(P)          pair_gap_hours = 3

     i=0 etom -> roc is 240 min > 180  -> no pair, nothing consumed
     pairs: 0   unpaired: 1 SED, 1 PARA   detected = false

(f)  no opposite class present at all
     midaz 03:00(S)  fent 03:05(S)  propofol 09:00(S)

     pairs: 0   unpaired: 3 SED, 0 PARA   detected = false
```

Case (e) is the one that makes D29 concrete: because the rejected pair consumes nothing, a *tighter* `pair_gap_hours` leaves rows available that a looser one had removed. Re-running is required; filtering `gap_minutes` on the emitted table is not equivalent.

#### Dose handling

`med_dose` and `med_dose_unit` are taken verbatim from both administration rows, with no unit conversion or normalisation, as in §7.1. Unit heterogeneity across the two members of a pair — a sedative in mg beside a paralytic in mg/kg — is a reportable property, not something to reconcile.

### 7.4 `DEV` — no method notebook

**The device signal has no notebook in this section.** It is the index qualifier, and it lives in `02_index_imv.py` (§5.9–§5.12) — upstream of every method, where it decides who is analysed rather than competing to be detected.

Nothing about the M2 rule changed in the move; only its role did. Anchored on t₀, the rule can no longer disagree with `SED` and `PARA` about *when* the intubation was, because `01` already fixed t₀ for all of them. What it reports is whether the record documents a pre-period and a sustained IMV — a fact about charting completeness (catalog §9.4). Scored inside an agreement matrix, that fact would have masqueraded as a clinical signal and dragged every κ toward it. See D19, and §5.10 for why the taxonomy has three failure classes rather than the four an earlier draft listed.

------------------------------------------------------------------------

## 8. Reference and agreement

### 8.1 `06_reference_cpt.py`

Source: `patient_procedures` — `procedure_code`, `procedure_code_format`. Reached by the same explode-and-drop bridge as §7, so a code billed under any hospitalization in the block counts for the encounter. **`billing_provider_id` is not read, and `procedure_billed_dttm` is read only to confirm the row belongs to the encounter — never as an event time.**

| Reference | Format | Code |
|---|---|---|
| `CPT` | CPT | `31500` — emergency endotracheal intubation |

Output: `reference_cpt.parquet` — one row per cohort encounter, keyed on `intubation_episode_id` and carrying `cohort_run_id`, with a `cpt_present` boolean.

Also reports the **code capture rate**: the fraction of the cohort carrying the code. Every metric in Tier C must be read against this number first — where capture is low, the reference is uninformative at that site and is reported as such rather than scored.

> **CPT 31500 is a narrow reference and its ceiling should be stated up front.** It codes *emergency* endotracheal intubation, so elective and operative airway management is not captured, and billing completeness varies by site, payer and era. Sensitivity computed against it is bounded by that capture, not by the method under test — which is precisely why it is a *partial* gold truth and not a peer in the agreement matrix (D1).

### 8.2 `07_agreement.py`

> **All numbers in the tables below are illustrative shape, not results.** They exist to fix the output format so the notebook can be written and reviewed before any data is run. Real values come from executing the pipeline, and they are not close to these — the illustrative tables were sized against an index set of ~1 200 and a `SED` detection rate of 0.87; the first real run gave N\*\* = 6 319 and 0.42. Read the tables below for their *columns*, and `output/final_no_phi/` for their *values*.

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

**Every table in Tiers A, B and C is computed on `index_class = 'qualified'` only** — the `N**` set from §5.11. This is the single subsetting step in the whole pipeline and it happens here, in one visible filter, so a reader of `07` can see exactly which denominator every rate below uses. The non-qualified rows are used once, in the specificity probe (Tier D), and nowhere else.

**Tier B reads the `method_*_ranked.json` files instead**, because the encounter table carries only rank 1. The full rank ladder — and the per-medication breakdown it enables — lives only in the JSON.

#### Tier A — do the methods find the same patients?

> **`PAIR` is reported on two bases, and every table in Tier A is computed twice.** `PAIR`'s `detected` is free-running over the whole encounter while `SED` and `PARA` are window-restricted (D27), so a naive three-way table would compare signals measured over different spans. Each table below therefore carries a `pair_basis` column taking `free_running` (uses `detected`) or `in_window` (uses `detected_in_window`, §6.5). The `in_window` basis is the matched-denominator reading and is the one to quote when comparing `PAIR` head to head with the other two; the `free_running` basis is the one that shows what the method finds when it is allowed to look everywhere. `SED` and `PARA` rows are identical across the two bases by construction — a useful self-check.

**A.1 Detection rate per method.** The marginal, before any cross-tabulation.

| method | basis | detected | n | rate |
|---|---|---|---|---|
| `SED` | — | ✓ | 1 043 | 0.87 |
| `PARA` | — | ✓ | 809 | 0.67 |
| `PAIR` | `free_running` | ✓ | 902 | 0.75 |
| `PAIR` | `in_window` | ✓ | 731 | 0.61 |
| — | | index set N\*\* | 1 202 | 1.00 |

The gap between `PAIR`'s two rows is itself informative: it counts encounters where a sedative–paralytic co-administration exists in the stay but *not* near the index IMV. A large gap means either reintubation activity the study is not labelling, or an index t₀ that is landing away from the real intubation.

**A.2 The pairwise 2×2s.** Three tables now — `SED` × `PARA`, `SED` × `PAIR`, `PARA` × `PAIR` — each complete, so κ and Jaccard stay recomputable by hand. The `SED` × `PARA` table is shown as the exemplar; all three are written to `agreement_pairwise.csv` in the same shape, and the `PAIR` tables are written once per basis.

|  | `PARA` ✓ | `PARA` ✗ | total |
|---|---|---|---|
| `SED` ✓ | 784 | 259 | 1 043 |
| `SED` ✗ | 25 | 134 | 159 |
| **total** | **809** | **393** | **1 202** |

| pair | basis | both | only A | only B | neither | Jaccard | Cohen κ |
|---|---|---|---|---|---|---|---|
| `SED` × `PARA` | — | 784 | 259 | 25 | 134 | 0.73 | 0.40 |
| `SED` × `PAIR` | `in_window` | 718 | 325 | 13 | 146 | 0.68 | 0.35 |
| `PARA` × `PAIR` | `in_window` | 702 | 107 | 29 | 364 | 0.84 | 0.71 |

The off-diagonal cells are asymmetric and each reads differently:

- **Only `SED`** is the expected majority in the first row: sedation without paralysis is a real and common technique.
- **Only `PARA`** should be small — a paralytic given with no induction agent charted is closer to a documentation gap than a clinical choice, so this cell is where charting failure concentrates.
- **`PARA` × `PAIR` should be the tightest of the three**, and if it is not, something is wrong. A `PAIR` detection requires a paralytic by definition, so on the `in_window` basis `PAIR` ✓ ∧ `PARA` ✗ ought to be near-empty; a non-trivial count there means the two notebooks disagree about the paralytic list or about window membership, which is a bug rather than a finding. This cell is the closest thing the design has to a cross-notebook integrity check, and D8's deliberate duplication is what makes it meaningful.

**A.3 Concordance histogram.** How many of the three fired on the same encounter.

| methods firing | basis | n | \% |
|---|---|---|---|
| 0 | `in_window` | 131 | 10.9 |
| 1 | `in_window` | 198 | 16.5 |
| 2 | `in_window` | 171 | 14.2 |
| 3 | `in_window` | 702 | 58.4 |

The `0` row is the one to read first: encounters with a *documented, sustained* intubation — §5.9 guaranteed that much — where no medication signal fired at all. Because the index qualifier has already removed the arrived-intubated group, this count can no longer be explained away as "the patient came in on a vent". It is a direct measure of intubations performed here whose medications were never charted in the ±3 h window.

**A.4 The combination table.** Three sets have eight combinations, which no single 2×2 can show (D33). One row per combination, both bases.

| `SED` | `PARA` | `PAIR` | basis | n | \% |
|---|---|---|---|---|---|
| ✓ | ✓ | ✓ | `in_window` | 702 | 58.4 |
| ✓ | ✓ | ✗ | `in_window` | 82 | 6.8 |
| ✓ | ✗ | ✓ | `in_window` | 16 | 1.3 |
| ✓ | ✗ | ✗ | `in_window` | 243 | 20.2 |
| ✗ | ✓ | ✓ | `in_window` | 13 | 1.1 |
| ✗ | ✓ | ✗ | `in_window` | 12 | 1.0 |
| ✗ | ✗ | ✓ | `in_window` | 3 | 0.2 |
| ✗ | ✗ | ✗ | `in_window` | 131 | 10.9 |
| | | | | **1 202** | **100.0** |

Three rows are structurally near-impossible on the `in_window` basis and are the ones to inspect if they are not near zero: `✗ ✗ ✓` (a pair with neither member detected), `✗ ✓ ✓` and `✓ ✗ ✓` (a pair whose sedative or paralytic member went undetected by the corresponding method). All three imply a list or window disagreement between notebooks. On the `free_running` basis they are expected to be non-zero and mean something entirely different — a pair outside the window — which is why the basis column is not optional.

> **No upset plot.** A.4 carries exactly the information an upset plot over three sets would, stays a CSV subject to the n ≥ 10 rule in §9, and needs no figure. This supersedes the two-method draft's version of this note, which argued the combination space was too small to be worth drawing; at three methods the argument is instead that the table is the better rendering.

#### Tier B — how is charting distributed in time?

Computed by flattening the `method_*_ranked.json` files into a long frame of ranked entries, filtered to `index_class = 'qualified'`. Each episode contributes **at most one entry per medication per direction** (§6.2), so no patient is over-weighted by repeat dosing.

**Tier B covers `SED` and `PARA` only.** `PAIR` emits no ranked JSON and has no before/after ladder (D30), so it has nothing to contribute to B.1–B.4. Its timing analysis is Tier E, which asks a different question — where the pair sits relative to t₀, rather than where each administration sits.

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

The clinical read: both ranked methods should cluster tightly just *before* t₀ — induction agents and paralytics are given to accomplish the intubation. Mass appearing *after* t₀ is expected to be small and is meaningful when it appears: a post-intubation sedative bolus, or a paralytic redose. A method whose bulk falls on the wrong side of t₀ is detecting something other than the intubation.

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

| `index_class` | n | `SED` rate | `PARA` rate | `PAIR` rate (`in_window`) | `PAIR` rate (`free_running`) |
|---|---|---|---|---|---|
| `qualified` | 1 202 | 0.87 | 0.67 | 0.61 | 0.75 |
| `arrived_intubated` | 698 | 0.44 | 0.09 | 0.07 | 0.38 |
| `insufficient_lookback` | 187 | 0.61 | 0.38 | 0.33 | 0.49 |
| `imv_not_sustained` | 127 | 0.31 | 0.11 | 0.09 | 0.24 |

*(Illustrative shape, not results.)*

**`arrived_intubated` is the row with a known answer**, and that is what makes this tier worth running. Those patients were intubated before they arrived, so nothing in the ±3 h window around their first charted IMV row can be an induction. Every detection in that row is therefore a false positive **by construction** — no reference, no adjudication and no assumption about coding required. It is the only stratum in the study where the truth is known without a gold standard.

Read the columns against each other. `PARA` at 0.09 is behaving: paralytics are given to intubate, so they are nearly absent when no intubation happened here. `SED` at 0.44 is the finding — roughly half of already-intubated patients receive a charted sedative in any given 6-hour span, because midazolam, propofol and fentanyl are maintenance ICU drugs as much as induction drugs. That number is the empirical version of the warning in D10, and it belongs in the results rather than in a footnote: **it bounds how much of `SED`'s 0.87 in the qualified stratum is signal and how much is ambient ICU sedation.**

`PAIR`'s two columns separate two different claims about it, and the `arrived_intubated` row is where the separation matters most. On the `in_window` basis it should behave like `PARA`, since requiring a paralytic is what suppresses ambient sedation. On the `free_running` basis it will be substantially higher, because an already-intubated transfer often *is* paralysed and sedated later in the stay — for ARDS proning, for ventilator dyssynchrony — and the free-running scan has the whole admission to find it in. **That difference is the cost of D27 stated as a number**, and it is the honest way to report a free-running method: not as a flaw to be tuned away, but as the price paid for the ability to detect an intubation the window would have missed.

The gap between a method's `qualified` rate and its `arrived_intubated` rate is the sharpest single-number summary of specificity this design can produce, so it is reported explicitly:

| method | basis | qualified | arrived_intubated | gap |
|---|---|---|---|---|
| `SED` | — | 0.87 | 0.44 | **0.43** |
| `PARA` | — | 0.67 | 0.09 | **0.58** |
| `PAIR` | `in_window` | 0.61 | 0.07 | **0.54** |
| `PAIR` | `free_running` | 0.75 | 0.38 | **0.37** |

A method whose gap approaches zero is not detecting intubation at all — it is detecting being in an ICU.

> **What Tier D is not.** The strata differ clinically, not just in observability: arrived-intubated patients are transfers, and transfers differ in acuity, sedation practice and length of stay. The gap is therefore a *bound*, not an unconfounded specificity estimate, and is reported as such. It is still the strongest specificity evidence available without chart review, which is why it is a tier rather than a footnote.

#### Tier E — pair structure and independent timing

Computed from `method_PAIR_pairs.parquet`, filtered to `index_class = 'qualified'` like Tiers A–C. This is the tier that uses `PAIR`'s distinguishing property: it carries its own intubation timestamp, so it can be scored against t₀ rather than merely near it.

**E.1 Pairs per encounter.** How much sedative–paralytic activity a stay contains.

| n pairs in encounter | n encounters | \% |
|---|---|---|
| 0 | 300 | 25.0 |
| 1 | 671 | 55.8 |
| 2 | 158 | 13.1 |
| 3+ | 73 | 6.1 |

The `3+` row bounds how much of the free-running/`in_window` gap in A.1 is reintubation activity rather than a mis-placed t₀. Episode labelling stays out of scope (§1) — this row reports that the activity exists without claiming what it was.

**E.2 Gap distribution.** Minutes between the two members of a pair, always positive.

| basis | n pairs | median | IQR | % ≤ 5 min | % ≤ 30 min |
|---|---|---|---|---|---|
| all pairs | 1 407 | 3.0 | 1.0 … 11.0 | 62.4 | 88.1 |
| index pairs only (`first`) | 902 | 2.0 | 1.0 … 6.0 | 74.8 | 94.2 |

The 5-minute and 30-minute columns are chosen to be directly comparable to the sibling `Induction_Variability_RSI` study, which uses 5 min as its cohort-defining pair threshold and 30 min for its timing sub-analysis. **This is the empirical justification for or against `pair_gap_hours = 3`**: if the overwhelming mass sits under 30 minutes, a 3-hour threshold is admitting a long tail of coincidental co-occurrence, and the tail's size is what this table exposes. Because the threshold is not post-hoc filterable (D29), acting on that finding means a re-run — but the table tells you whether the re-run is worth doing.

**E.3 Which agents pair with which.** The sedative × paralytic contingency, over index pairs.

| `sed_med_category` | `para_med_category` | n | median gap | median sed dose | unit |
|---|---|---|---|---|---|
| etomidate | rocuronium | 388 | 1.0 | 20.0 | mg |
| etomidate | succinylcholine | 141 | 1.0 | 20.0 | mg |
| ketamine | rocuronium | 118 | 2.0 | 100.0 | mg |
| propofol | rocuronium | 96 | 3.0 | 100.0 | mg |
| midazolam | rocuronium | 87 | 8.0 | 2.0 | mg |
| fentanyl | rocuronium | 72 | 12.0 | 100.0 | mcg |

This is the clinical output the method exists to produce, and it is not derivable from `SED` and `PARA` run separately — those two report their marginals, never the joint. The etomidate/ketamine rows with rocuronium or succinylcholine are the rapid-sequence combinations; midazolam and fentanyl rows with longer median gaps are the ones most likely to be co-occurrence rather than a deliberate induction pair, and their share is a direct read on `SED`'s list breadth (D10).

**E.4 Index pair offsets.** Where each index pair sits relative to t₀, signed minutes.

| index pair | n | median | IQR | % within ±30 min |
|---|---|---|---|---|
| `first` (chronologically) | 902 | −6.0 | −21.0 … −2.0 | 71.3 |
| `near` (nearest t₀) | 902 | −4.0 | −9.0 … −2.0 | 92.7 |

| statistic | value |
|---|---|
| `first_is_nearest` | 0.83 |

**E.5 Device-versus-medication timing concordance.** The headline of this tier, and the question §1 added when `PAIR` was introduced. Computed on `first_pair_to_t0_min` — the pair chosen *without* reference to t₀, so the comparison is not circular.

| tolerance | n within | \% of detected |
|---|---|---|
| ±5 min | 402 | 44.6 |
| ±15 min | 585 | 64.9 |
| ±30 min | 643 | 71.3 |
| ±60 min | 704 | 78.0 |
| beyond ±180 min | 121 | 13.4 |

**Read the `beyond ±180 min` row against A.1's free-running/`in_window` gap** — they are two views of the same encounters. Every one of them is a case where the earliest sedative–paralytic co-administration of the stay is not near the index IMV. Three explanations compete, and this design cannot separate them: the patient was intubated somewhere the device charting did not follow, t₀ landed on a later ventilation episode, or the pair was coincidental. Reporting the row without adjudicating it is the correct move — it sizes the disagreement rather than explaining it away.

`near_pair_to_t0_min` is deliberately **not** used for E.5. Its offset is small by construction (D31), so scoring on it would produce a concordance number that reflects the selection rule rather than the data.

**E.6 Pair offset distribution plot.** `first_pair_to_t0_min` on a shared \[−180, +180\] minute axis with t₀ marked at zero, and the out-of-range count stated in the caption rather than clipped into the end bins.

```         
        −180      −90        0        +90      +180  min
          |        |         |         |         |
  PAIR         ▁▂▃▆█▇▄▂▁     │▁▁
                            ▲ t₀        (121 pairs beyond ±180 not shown)
```

Clipping the out-of-range mass into the edge bins would put the study's most interesting encounters — the ones in the `beyond ±180` row of E.5 — into a bin that reads as "just outside the window". Stating the count in the caption keeps them visible as what they are.

#### Outputs written by `07`

| File | Contents |
|---|---|
| `agreement_detection_rates.csv` | A.1 |
| `agreement_pairwise.csv` | A.2 |
| `agreement_concordance.csv` | A.3 |
| `agreement_combinations.csv` | A.4 |
| `timing_offset_summary.csv` | B.1 |
| `timing_offset_by_rank.csv` | B.2 |
| `timing_by_medication.csv` | B.3 |
| `timing_offset_distribution.png` | B.4 |
| `reference_capture_rate.csv` | C.1 |
| `reference_scoring.csv` | C.2 |
| `specificity_by_index_class.csv` | D.1 |
| `specificity_gap.csv` | D.1 gap table |
| `pair_count_distribution.csv` | E.1 |
| `pair_gap_distribution.csv` | E.2 |
| `pair_agent_combinations.csv` | E.3 |
| `pair_index_offsets.csv` | E.4 |
| `pair_t0_concordance.csv` | E.5 |
| `pair_offset_distribution.png` | E.6 |
| `pair_agent_combinations.png` | E.3, sedative × paralytic heatmap, counts annotated |
| `consort_flow.png` | CONSORT A and B as one two-panel figure, drawn from the two CSVs |
| `index_class_strata.png` | §5.10 taxonomy — the denominator map, `qualified` highlighted |
| `agreement_overview.png` | A.1, A.2 and A.3 in one frame |
| `timing_by_medication.png` | B.3, median offset per agent, split before / after |
| `specificity_gap.png` | D.1, all three methods across every stratum, gaps in the title |

All go to `output/final_no_phi/` and are subject to the n ≥ 10 minimum cell size in §9 — any row of any table with a cell below 10 is suppressed rather than published. Figures inherit that suppression by construction (D26): each is drawn from the published table rather than recomputed.

**Suppression is row-level and applies to the 1–9 range only.** A cell of exactly zero is published: it identifies nobody, and withholding it would turn "this never happened" into "this is missing" — a different and worse statement in a multi-site study, where a missing cell reads as a site that failed to run the notebook. Rows in the disclosive range are removed entirely rather than blanked, because a blanked cell in a table whose margins are published is often recoverable by subtraction. Every suppression is printed with the row that triggered it, so a shrunken table is never mistaken for a clean one.

**B.4 is normalised per method, not plotted as raw counts.** `SED` and `PARA` differ by more than an order of magnitude in entry volume at any real site; on a shared count axis the smaller method is a flat line against the axis, which reads as "no timing signal" when what it has is a smaller denominator. Shape is what B.4 asks about, and the counts behind it are published in B.1 and B.2.

> **The n ≥ 10 rule bites hardest on B.3.** Per-medication breakdowns split the cohort finely — the illustrative `vecuronium` row above shows n = 27, and a rarer agent or a smaller site will fall below 10. Suppression here is row-level: the medication is dropped from the published table rather than pooled into an "other" category, since pooling across agents with different units and dose scales would produce a meaningless median.

------------------------------------------------------------------------

## 9. Outputs and data security

Follows the existing rules in [`output/README.md`](../../../output/README.md) and [`guides/primer.md`](../../../guides/primer.md).

| Directory | Contents |
|------------------------------------|------------------------------------|
| `output/intermediate_phi/` | `cohort.parquet`, `cohort_resp_waterfall.parquet`, `cohort_index.parquet`, `cohort_qc.csv`, `index_imv.parquet`, `method_{SED,PARA}_ranked.json`, `method_{SED,PARA,PAIR}_encounter.parquet`, `method_PAIR_pairs.parquet`, `reference_cpt.parquet` |
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
  "pair_gap_hours": 3,
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
| `window_hours` | `01` | half-width of the t₀ detection window (D4). Written into `cohort_index.parquet` as `window_start` / `window_end` and consumed by `03` and `04` as data, never recomputed (D9). Changes a *detection* result for `SED` and `PARA`, and applies identically to both (§6.2). For `PAIR` it does not affect detection at all — only the descriptive `in_window` flag (§6.5) |
| `pair_gap_hours` | `05` | maximum gap between the two members of a `PAIR` (D29). Read directly by `05` rather than written into an upstream artifact, because unlike `window_hours` there are no bounds to precompute — the scan needs the scalar. The only detection parameter not resolved by `01` |
| `stitch_hours` | `01` | `time_interval` passed to `stitch_encounters` (D15). Changes the analytic unit itself, so every count in the study moves with it |
| `trach_window_hours` | `01` | the exclusion clock in §5.5 (D18) |
| `min_age` | `01` | the adult criterion, tested on `age_at_admission` |

The last three are **cohort** parameters, not detection parameters: they change who is in the denominator rather than who is detected. `01` echoes its four at the top of the notebook and writes them into `cohort_qc.csv`, and `05` echoes `pair_gap_hours` and writes it into `method_PAIR_pairs.parquet`'s accompanying schema assertion output, so a published result carries the definitions that produced it. Everything else is a path or a site label.

> **`pair_gap_hours` is the one parameter D9 does not cover.** Every other detection parameter is resolved once by `01` and consumed downstream as data, precisely so no notebook re-derives it. `pair_gap_hours` cannot follow that pattern: `01` has no pair scan to run and nothing to precompute. `05` therefore reads it from config directly and echoes it, which is the §4 "no silent defaults" requirement doing the work D9 does elsewhere.

------------------------------------------------------------------------

## 11. Out of scope

Recorded so these are visible omissions rather than oversights.

**Removed from an earlier draft of this spec:**

- **The continuous-infusion method `INF`** (whiteboard item 3) — propofol / dexmedetomidine / fentanyl infusion starts. Removed per D1a. Consequently `medication_admin_continuous` is not read anywhere in the pipeline, and `infusion_gap_hours` is not a config key.
- **The ICD reference** — ICD-10-PCS `0BH17EZ`, `0BH18EZ`, `5A1935Z`, `5A1945Z`, `5A1955Z` and ICD-9 `9604`, `9670`–`9672`. Removed per D1b. CPT 31500 is the sole reference.
- **`DEV` as a compared method**, with its own notebook and its rows in the agreement matrix. Not deleted — *relocated* per D19 to `02_index_imv.py`, where the same M2 rule now qualifies the index event instead of competing to detect it.
- **The post-waterfall t₀ anchor.** Replaced by D23 after measurement showed it moved t₀ on 24.1% of encounters. The `prior_row_imv` class, removed from an intermediate draft as unreachable under that anchor, is **reinstated** by D23 and is now the stratum that labels exactly those encounters (§5.10).

**Out of scope from the start:**

- Extubation detection of any kind.
- Second and subsequent intubations; reintubation labelling; episode stitching.
- Outcome classification (success / failed / WLST) — catalog M3's tree.
- Tracheostomy handling — no cohort exclusion and no method adjustment.
- The M1 / M3 / M4 device transition rules.
- Pre-waterfall vs post-waterfall sensitivity analysis (settled by D5).
- M5 non-device signals (LPM onset, vent-observation cessation).
- Chart review (catalog Tier 2).