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
- **The analytic unit is the intubation episode** (D35), keyed `{encounter_block}_E{n}`. Encounters are still stitched first and every artifact still carries `encounter_block` — see §5.1 for why stitching is a correctness requirement rather than a convenience — but a block may contribute several episodes and the denominator of every rate in §8 is the episode.
- **All sustained IMV episodes, not just the first.** A block with a reintubation contributes `_E1` and `_E2`, and both are scored. What remains out of scope is *outcome* classification — whether an episode ended in extubation, trach or death — and any linkage between episodes of the same block beyond `ep_num`. (Encounter stitching is in scope and happens first; the two senses of "stitching" are unrelated.)
- **`PAIR` emits many pairs per block, but still one analytic row per episode.** The free-running scan finds every sedative–paralytic co-administration in the stay, so its pair-level artifact is not one row per episode. Each pair is assigned to the nearest episode (D39) and collapses to the analytic unit at §7.3 by designating two index pairs (D31).
- **Every detection comes from intermittent medications.** Both medication methods detect on `medication_admin_intermittent` alone. `medication_admin_continuous` is read under D40, but only to reclassify administrations already found there — it can remove a detection and never create one. The continuous-infusion *method* (whiteboard item 3) remains out of scope — see D1a and §11.
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
| D2 | ~~**The device signal uses the M2 symmetric 2/2 rule only**, not all of M1–M4.~~ **Superseded by D36** — the device rule is now a duration test, not a row test. | The reason D2 was written still holds and still excludes M1–M4: the M1–M4 spread is already quantified in the catalog, and re-running it here would measure a known result and obscure the new one. What changed is which single rule stands in that slot. |
| D3 | ~~**Analytic unit is one row per stitched `encounter_block`**, anchored on t₀ = first charted IMV row in the block.~~ **Superseded by D35** — the unit is the intubation episode, and a block may hold several. | The property D3 was chosen for survives intact and is the reason D35 is safe: every method is still pinned to one t₀ per unit, so event matching stays collapsed — no greedy pairing, no order-dependence, no tolerance windows. Agreement is still a plain binary table and timing is still offset distributions on a shared axis. What changed is only how many units a block contributes. |
| D4 | **Detection window is t₀ ± 3 hours**, symmetric. | Set by the study lead. Every method asks the same question over the same interval, so differences are attributable to the signal and not to the window. |
| D5 | **Respiratory pre-processing is fixed: post-waterfall, single policy.** No pre/post grid. | Catalog §12.4 requires the policy be settled before methods are compared. Fixing it in one place makes the agreement numbers mean exactly one thing; changing it later is a config edit, not a rewrite. |
| D6 | **Waterfall runs with `bfill=True`.** Set by the study lead. It is recorded here that this **cannot change any result in this pipeline**, and the reason is stated so no later reader treats the flag as load-bearing. | An earlier version of D6 set `bfill=False` on the rationale that backfilling would propagate a device backwards in time and manufacture an IMV row earlier than the first charting, sliding t₀. **That rationale was wrong.** `waterfall.py:274` forward-fills `device_category` unconditionally; the `bfill` flag reaches only `num_cols_fill` — `fio2_set`, `peep_set`, `tidal_volume_set`, `resp_rate_set` and siblings — at `:320-336`, and the device heuristics that relabel null-device rows to `imv` (`:199-226`) run *before* that fill. The pipeline reads `device_category` and nothing else out of the waterfall, so the flag is inert here in both directions. It is also nearly moot on the data: after the unconditional ffill, **0.2%** of waterfalled rows still carry a null device. |
| D7 | **No CPT code and no `billing_provider_id` in the cohort definition.** | Explicit study requirement. Distinguishes this cohort from `Induction_Variability_RSI`, which requires both. The CPT code enters only as the reference in notebook `06`. |
| D8 | **Every method notebook is fully self-contained. No shared helper module.** | A bug in a shared helper corrupts every method *identically*, and correlated errors are indistinguishable from genuine agreement — the one failure mode an agreement study cannot tolerate. Isolation makes mistakes surface as disagreement (visible) rather than as inflated concordance (invisible). |
| D9 | **The detection window is data, not code.** `02_index_imv.py` writes `window_start` / `window_end` into `index_imv.parquet`, one pair per episode. | Removes the usual cost of D8. There is no window logic to duplicate across notebooks, so there is nothing to drift, while detection logic stays fully independent. *(The producer moved from `01` to `02` under D34: t₀ is now decided by episode detection, so the window that hangs off it must be written where t₀ is resolved. The principle is unchanged.)* |
| D10 | **`SED` is the induction-agent list — the drugs used to intubate — and reads `medication_admin_intermittent` only.** | Induction agents are intermittently dosed. Propofol and fentanyl are also charted as continuous maintenance infusions, but those rows live in `medication_admin_continuous` and contribute no detections: detecting on them would conflate intubating a patient with sedating one already ventilated. **Amended by D40** — this row originally read "*and are never read*", which is no longer true: the continuous table is opened, as a disqualifier only. The property D10 was protecting survives in the sharper form "no detection originates there". `SED` is still expected to fire often, since midazolam and fentanyl are given for many non-airway reasons — that low specificity is a reportable property of the method, not a defect to tune away before measurement. |
| D11 | **Each method is a profiler, not just a detector.** It emits the ranked medication sequence around t₀ with dose, unit and lag; the binary `detected` is *derived* from that structure. | A binary answers "did the signal appear"; the ranked sequence answers "what was actually given, in what order, how far from the intubation". Deriving the binary from the ranks rather than computing it separately makes the two incapable of disagreeing. |
| D12 | **Ranks deduplicate by `med_category`: last administration before t₀, first after, ranked nearest-first.** | Nearest-first makes rank 1 the most clinically proximate entry, so rank 1 is comparable across patients. Dedup removes a real statistical artifact — under the previous all-signals contract a patient given six fentanyl doses contributed six observations to the timing distribution and dominated it. |
| D13 | **Ranking is over each method's own medication list only**, not over all charted medications. | Keeps every method strictly about its own signal, so the ranked output elaborates what the method detects rather than describing the ward. Consequence: rank counts are bounded by list size, so no rank cap is specified. |
| D14 | **Two artifacts per method: canonical `_ranked.json` plus a joinable `_episode.parquet`.** The raw undeduped signals table is dropped. | JSON carries nested ranks without null padding; parquet is what §8 can join at scale. The undeduped table had no remaining consumer once Tier B moved to ranked entries, and keeping an unconsumed artifact invites it to drift. |
| D15 | **Encounters are stitched before any cohort criterion is applied**, with `stitch_hours = 6`. | An ED intubation and the inpatient IMV charting that follows can carry different `hospitalization_id`s. Unstitched, `PARA` fires on one and `DEV` on the other and the agreement matrix records a disagreement that is purely administrative. Stitching last would mean filtering on a unit the study does not use. |
| D16 | **Stitching is preceded by a patient-level IMV-ever pre-filter.** | Stitching joins the full hospitalization and ADT tables and iterates to a fixed point; running it on every patient at a site is wasteful when every cohort criterion requires an IMV row. The filter is **patient**-level, not hospitalization-level, precisely because the IMV may be charted under a different `hospitalization_id` than the one anchoring the block — filtering hospitalizations here would discard the rows stitching exists to reunite. Changes no result (§5.2). |
| D17 | **Location criterion is ED *or* ICU, evaluated across the whole stitched block.** | Set by the study lead. ED-or-ICU is what admits the ED intubation that never reaches an ICU and the ward patient intubated on ICU transfer; requiring ICU alone would drop the first group, which is exactly where the medication and device signals are most likely to diverge. |
| D18 | **Tracheostomy in the first 24 h excludes the encounter, tested on two signals: `tracheostomy` truthy *or* `device_category == 'trach collar'`.** | mCIDE defines `IMV` as "Endotracheal Tube Ventilation, **Tracheostomy Ventilation**" — a trach patient on a vent charts as plain `IMV` and would otherwise enter as a false intubation with no induction or paralytic to find. Either signal alone leaks: the boolean misses sites that only chart the device, and `Trach Collar` is a weaning device that a continuously-ventilated trach patient may never receive. |
| D19 | **`DEV` is the index qualifier in `02_index_imv.py`, not a method in the agreement matrix.** It is the device signal that decides *which* episodes exist and *when* each began; nothing that fails it reaches the methods. | Anchored on t₀, a device rule cannot detect a *different* event from `SED` and `PARA` — t₀ is already fixed for all three by that very rule. All it can report is whether the surrounding record is consistent with a sustained intubation. That is a statement about the airway record, not an independent signal, so scoring it against medication signals was comparing a data-availability fact to a clinical one. **The rule itself changed under D36** — the M2 symmetric 2/2 row test became the 3 h device-continuity test — but `DEV`'s *role* did not, and this decision is about the role. |
| D20 | **Nothing `02` evaluates is discarded.** `02` writes one row per candidate episode with an `index_class`, including the ones it rejects, and §8 draws its specificity evidence from them. | Running the methods once over everything and carrying `index_class` through costs nothing — the window is already fixed for every candidate — and leaves the primary/probe split as a single `filter` in `07`. **The stratum this decision was originally written for is gone**: `arrived_intubated` was the group with a known answer, and D37 now admits it to the primary analysis. See D38 for what replaces it and the Tier D rewrite in §8 for how the specificity question is asked now. |
| D21 | **Every category column is lower-cased on load, and every literal compared against one is written in lower case.** Applies to `device_category`, `location_category`, `med_category`, `mar_action_category`, `mode_category`, `admission_type_category`, `discharge_category` — every `*_category` column the pipeline touches. | Case is the one vocabulary difference that fails *silently*. A mismatched category value does not raise; it matches zero rows, and a filter matching zero rows looks exactly like a site where the thing never happens. The waterfall already lower-cases four columns (`waterfall.py:147-149`), so the pipeline has two casings in it whether or not we plan for them. Normalising **down** rather than up means the library's own transformation is a no-op instead of something to undo, and there is exactly one rule to remember: lower-case, always. |
| D22 | **Load-time category filters pass every casing variant**, not just the mCIDE spelling. `filters={'device_category': ['IMV', 'imv', 'Imv']}`. | D21 normalises *after* load, but a `from_file` filter runs *before* anything we control — it is applied to raw site data as charted. A site that writes `imv` would be filtered to nothing and silently produce an empty cohort. Passing the variants closes the gap at the only point in the pipeline where our own lower-casing cannot reach, and §5.2 adds a cross-check that proves the filter missed nothing. |
| D23 | ~~**t₀ anchors on the earliest *raw charted* IMV row, not the earliest waterfalled one.**~~ **Superseded by D34 for the anchor. D23 still governs cohort admission** (§5.2, §5.5): a block enters the study on a *raw charted* IMV row, and that has not changed. | Retained in full because D34 is a reversal and the evidence that produced D23 is the evidence D34 reinterprets. Measured on MIMIC: **24.1% of cohort encounters** had a waterfalled t₀ *earlier* than the first charted IMV row (median −17 min, tail to −7.6 h), and 0% had it later. All 8,192 sat on a pre-existing row with `device_category` null and ventilator settings present, which `waterfall.py:199-215` relabels to `imv`. D23 read that gap as inference contaminating an observed quantity. D34 reads the same gap as **charting latency**, which is a claim about the clinical setting rather than about the data, and it is the study lead's call to make. |
| D24 | **The reference is gated on capture before it is scored.** `06` computes the capture rate first; if fewer than 10 index-set episodes carry the code, *or* capture falls below **0.05**, `07` writes `reference_scoring.csv` with `informative = false` and null metrics instead of sensitivity and PPV. | Measured on MIMIC under the pre-D35 design: **1 encounter** in an index set of 6,319 carried CPT 31500 (capture 0.0002), because the extract holds 116 CPT rows against 210,000 ICD rows. Scored anyway, that yields a sensitivity computed on a denominator of one — a number that looks like method performance, is quoted as method performance, and is really a statement about which billing systems the site exported. The gate makes "the reference cannot adjudicate here" the published result, which is the true one. The threshold is deliberately low: 0.05 is not a claim that 5% capture is adequate, only that below it the metric is not arguable. |
| D25 | **An administration falling exactly on t₀ belongs to neither direction, and the count is reported.** `[window_start, t₀)` and `(t₀, window_end]` are half-open by §6.2 and stay that way. | Assigning the tie to one side would make `before` and `after` asymmetric for no clinical reason, and assigning it to both would double-count a single event. Silently dropping it, though, is the real hazard — this site charts respiratory support on the hour, which is exactly the condition that makes an exact collision common. Measured: **807 of 32,902** `SED` administrations in-window (2.4%) and **19 of 455** `PARA` (4.2%). Both `SED` and `PARA` print it, so the drop is a stated quantity rather than an invisible one. |
| D26 | **Every figure is drawn from a published table, and where a histogram bin falls in the disclosive range the bin is dropped rather than merged into its neighbour.** | A figure recomputed from the PHI frames could disagree with the CSV beside it, and the reader has no way to tell which is right. Drawing from the published table makes the n ≥ 10 suppression automatic instead of something to reimplement per plot. Merging a suppressed bin into an adjacent one would move mass the reader cannot see move — dropping it and stating the dropped total in the caption keeps the omission visible. |
| D27 | **`PAIR` is a third method under test, and it is free-running: it scans the whole stitched encounter, not the ±3 h window.** t₀ is joined afterwards only to locate each pair on the timeline; it is never an input to detection. | A window-restricted pairing method would be close to redundant — the `SED`✓ ∧ `PARA`✓ cell of the 2×2 already says both fired in that window, so the only new fact would be the gap in minutes. Free-running makes it a genuine third detector: it can find a co-administration the device signal missed entirely, and it produces an independent intubation timestamp (§1). The cost is a denominator that is not comparable to `SED` and `PARA` — addressed by D33 rather than by narrowing the scan. |
| D28 | **The scan is a single forward pass with consumption.** At each administration, look forward to the first *available* opposite-class administration, skipping same-class ones in between; pair if the gap is under threshold; mark both consumed. Advance one step and never look back. | Set by the study lead. Skipping past same-class rows rather than stopping at them means a fentanyl charted before the midazolam still reaches the rocuronium — real charting routinely puts an analgesic ahead of the induction agent. Consumption keeps pairs non-overlapping, so a `pair_id` is countable and one paralytic cannot be the partner in three different pairs. Same-class rows stepped over are *not* consumed, so they get their own turn as the scan advances (§7.3). |
| D29 | **`pair_gap_hours` is its own config key (default 3), not `window_hours` reused. Changing it requires re-running `05`; it cannot be applied post hoc as a filter on the pairs table.** | The two parameters answer different questions and the sibling `Induction_Variability_RSI` study pairs at 5 min for cohort definition and 30 min for its timing sub-analysis, so someone will want to tighten this without moving the detection window. The re-run requirement is a correctness constraint, not a convenience: rejecting a pair leaves **both** rows available, which changes what everything downstream of them pairs with — so a tighter threshold yields a different pair set, not a subset of the current one. A reviewer who sees `gap_minutes` in a column will reach for a filter, so the non-monotonicity is stated where it will be read. |
| D30 | **`PAIR` is exempt from the §6.2 ranking rule and emits no `_ranked.json`.** It emits a pair-level parquet instead. | Ranking is a before/after ladder around a fixed t₀; `PAIR` has no such ladder because its unit is a two-drug event, not a single administration measured against an anchor. Forcing it into the ranked schema would mean inventing a rank for something that has no rank. Consequence: Tier B is computed over `SED` and `PARA` only, and `PAIR` gets its own tier (Tier E). |
| D31 | **Two index pairs are reported per episode, not one: the first pair chronologically and the pair nearest t₀.** Whether they are the same pair is itself a statistic. | The first pair tests t₀ — it is the earliest sedative–paralytic co-administration of the stay and therefore the medication signal's own candidate for the intubation, free to disagree with the device. The nearest pair keeps a reading tied to the IMV episode this study is about, whose offset is small by construction. Each alone discards what the other measures; `first_is_nearest` turns the redundancy into a result about how much pairing activity precedes the index intubation. |
| D32 | **Unpaired administrations survive as counts on the encounter row only.** There is no administration-level audit artifact. | Every table in §8 is computable from the pairs table and the two counts, so a third artifact would carry no consumer — and D14 already established that an unconsumed artifact invites drift. The trade is real and is accepted with eyes open: the scan is order-dependent and consuming, so a bug in the advance-and-consume logic cannot be caught by inspecting the outputs. §4's per-step count printing is the mitigation, and the worked examples in §7.3 are the test cases. |
| D33 | **With three methods, `A.2` becomes three pairwise 2×2 tables plus an eight-row combination table; the "no upset plot" note of the two-method draft is superseded.** | Three sets have eight combinations, which a single 2×2 can no longer show. The eight-row table carries the same information an upset plot would, stays a CSV subject to the n ≥ 10 rule in §9, and does not require a figure. The `PAIR` column of that table must be read against D27: it is free-running while the other two are windowed, so `detected_in_window` is reported alongside `detected` (§7.3) to make the comparison available on a matched denominator. |
| D34 | **t₀ is the episode's first *waterfalled* IMV row.** The raw charted row is not the anchor; it is retained as `first_charted_imv_dttm` and reported as `charting_delay_min`. Supersedes D23 for the anchor only — cohort admission still requires a raw charted IMV row. | Set by the study lead on a clinical argument the data cannot settle: **intubation is a high-stress event and device charting is deferred**, while the ventilator's settings reach the record the moment it is connected. Under that reading the settings-based inference at `waterfall.py:199-215` is *closer* to the event than the manual device entry, and D23 was correcting in the wrong direction. Measured per episode: the delay is **exactly zero for 77.3%**, p90 23 min, p95 55 min, **p99 540 min**, max 6,389 min, and only 6 episodes are never charted at all. A p99 of nine hours is not a plausible ventilator-settings error; it is a plausible charting delay, which is the evidence for the reading. **The delay can never be negative** — the waterfall only relabels nulls and never deletes a charted row, so its IMV set is a superset of the raw one in time — and `02` asserts that rather than trusting it. Publishing the delay turns the quantity D23 was decided on into a reportable property of the site's charting. |
| D35 | **The analytic unit is the intubation episode, `{encounter_block}_E{n}`, not the encounter block.** A block contributes as many rows as it has qualifying episodes. | The first-episode-only scope was a simplification, and it cost the study its reintubations — 1,940 episodes at MIMIC, in 1,654 blocks — which are exactly the events where an induction is charted without any of the surrounding context an admission provides. §6.1 already reserved the `_E{n}` key shape against this change, so no key, join or schema moves. The property D3 was chosen for is unaffected: one t₀ per unit still collapses event matching entirely. |
| D36 | **Episode segmentation and the pre-period test are the same operation.** An IMV row in the waterfalled sequence starts an episode iff no IMV row precedes it within `episode_gap_hours` in the same block. `episode_gap_hours` is its own config key, default 3. | Set by the study lead, replacing the M2 symmetric 2/2 row rule. Two gains, one structural and one clinical. **Structural:** a mid-episode IMV row has IMV inside its own lookback and disqualifies itself, so the same predicate that tests the pre-period also chops the timeline into episodes — 6.96 M rows to 42,488 candidates with one `shift(1)`, no episode loop, no in-episode state to track, no mid-episode branch to get wrong. **Clinical:** the M2 rule counted *rows*, so it measured charting density as much as ventilation. A duration measures ventilation. The key is separate from `window_hours` for the reason D29 gives: one is device continuity and the other is a medication window, and coupling them means tightening either silently redefines the other. |
| D37 | **Absence is not evidence of ventilation.** A null device, and an empty window, pass both the pre-period test and the sustained test. This retires `arrived_intubated` and `insufficient_lookback` as exclusions. | Set by the study lead. `B_strict` treated a missing row as a failed term, which made the two largest exclusions in the study — 18,533 and 3,282 encounters, 64% of the cohort between them — statements about charting rather than about patients. A patient wheeled in from the ED on a ventilator has an empty pre-period because they were on room air and nobody charted it, not because they were already ventilated here; with the block stitched across the ED and the inpatient stay (D15), their induction is *in the extract*. At MIMIC 52.8% of the final episode set has an empty pre-period. `arrived_intubated` survives as the non-excluding label `no_lookback`, because catalog §9.4 benchmarks that rate at ~31% across sites and it remains the first number to read. |
| D38 | **An episode qualifies only if at least one of the eight method medication categories is charted `given` in `medication_admin_intermittent` within t₀ ± `window_hours`.** | Set by the study lead over an objection recorded here in full, because it changes what §8 can claim. **The filter uses the same drugs, the same window and the same table the methods read, so `SED_detected ∨ PARA_detected` is true for every qualifying episode by construction.** A.2's `SED−/PARA−` cell and A.3's concordance-0 row are therefore empty by definition rather than by finding, and κ and Jaccard must be read as conditional on an induction agent having been charted. Two alternatives were measured and declined: filtering on `med_group ∈ {sedation, analgesia, anxiolytic, paralytics}` keeps 17,395 episodes with a union rate of 0.776 and preserves the cell; the eight categories keep 13,500 with a union rate of 1.000. The residual `SED−/PARA−` count is not quite zero — D25 puts an administration landing exactly on t₀ in neither half-open direction — but it then measures on-the-minute charting, not disagreement, and §8 labels it that way. Tiers B and E are unaffected: they measure where administrations sit in time, which a positivity filter does not touch. |
| D39 | **A `PAIR` pair is assigned to the episode whose t₀ is nearest; ties go to the earlier episode.** | D27 makes the scan free-running over the whole block, and under D35 a block may hold several episodes, so the scan's output must be partitioned before it can be counted per episode. Nearest-t₀ is the only assignment that needs no new concept — every pair already carries its distance to a t₀ — and it partitions rather than overlaps, so `n_pairs` summed over a block's episodes equals the block's pair count and no pair is scored twice. The alternative, re-running the scan per episode over a bounded stretch, would require an episode *end* the design does not define and would break D28's consumption across the boundary. |
| D40 | **An intermittent administration after t₀ that is followed within `infusion_prep_minutes` by a `start` row in `medication_admin_continuous` for the same `med_category` is maintenance-infusion prep, not an induction agent.** Applies to `SED` and `PARA`. `[window_start, t₀)` is exempt. Default 60 min. | Set by the study lead on a clinical argument: an infusion does not reach steady state on its own, so it is loaded with a bolus, and that bolus is charted in the intermittent table where it is indistinguishable from induction by drug and dose alone. The sequence *bolus → same-drug drip* after the airway is already secured is maintenance sedation being started, not the patient being intubated. **The before-window exemption is the load-bearing part and the data forced it.** Measured on `SED`'s qualified ranked entries: **30.1% of pre-t₀ entries are followed by a same-drug infusion start within 60 minutes, against 19.8% of post-t₀ entries** (n = 3,088 and 17,207; at a 15-minute threshold, 21.6% against 15.3%). A pre-t₀ bolus is *more* likely to precede a drip, not less — because induction → intubation → maintenance is the canonical sequence, and the bolus that starts it is the induction agent itself. A symmetric rule would additionally have reclassified **930 pre-t₀ entries**, every one of them a drug given before the airway was secured. The continuous table is read as a **disqualifier only and never as a detector**, which is what leaves D1a intact: no detection originates there, so `INF` stays removed and the study still does not claim an infusion means a ventilator. |
| D41 | **`during_infusion` — an administration given while a same-drug infusion is already running — is measured and published on both sides of t₀, and never acts.** | Proposed as a second disqualifier and declined on the measurement. On `SED`'s qualified ranked entries it is charted at **48.9% of before-t₀ entries and 57.5% of after-t₀ entries** (n = 3,088 and 17,207). The 8.6-point gap is real but useless: **the flag fires on nearly half of every dose given *before* the airway event** — doses that are induction agents almost by definition — so as a test for "this is not induction" it carries a false-positive rate near 49%. It reports that the patient is on sedation, which is a property of the admission and not of the airway. Disqualifying on it after t₀ only would be an asymmetric rule with no discriminating basis; symmetrically it would delete 1,510 of the study's 3,088 pre-t₀ entries. `PARA` shows the same flag at 0.6% and 4.1% (n = 178 and 410), which is what a genuinely rare event looks like by comparison. It is retained as a published band on the decomposed timing figure because *that* is a genuine result — it shows that most post-intubation sedative charting is maintenance, and therefore that `SED`'s apparent sensitivity rests almost entirely on its pre-t₀ half. Computed by backward as-of join — the most recent same-drug continuous event is not a `stop` — which needs no start/stop interval pairing and so is unaffected by MIMIC's 257-row imbalance between the two. |
| D42 | **The refinement is reported as a paired sub-analysis, not propagated through Tier A.** `SED` and `PARA` publish `detected` and `detected_induction_only`; every Tier A/B/C/D table continues to run on `detected` unchanged. D38's eligibility filter is **not** refined. | Two separate reasons, and the second is the one that matters. **Mechanically:** `07`'s basis machinery is `PAIR`-specific by construction — the column is named `pair_basis` and non-`PAIR` methods are skipped on the second basis — so generalising it makes A.3 an eight-way lattice to answer a question one paired comparison answers. **Substantively:** pushing the refinement into D38 would destroy the measurement it creates. If an episode qualifies only when a *non-prep* induction agent is charted, then every surviving episode has one by definition and `SED`'s refined rate snaps back to 1.000 — the same circularity D38 already records, reintroduced one layer down. Keeping the filter unrefined is precisely what makes the refined rate readable, and it holds N at 13,500 so both numbers share a denominator. |
| D43.1 | **`05`'s hospitalization → `encounter_block` bridge is de-duplicated with `.unique()`, and the de-duplication is asserted rather than assumed.** | This repairs a defect, not a preference, and the defect is worth recording because of how quietly it hid. D35 moved `index_imv` to episode grain, so exploding `list_hospitalization_id` yields one row per (episode, hospitalization) — and `05` is the one notebook that deliberately drops the episode key from its bridge (D27, D39), because its scan is free-running over the whole block. Un-deduplicated, the inner join therefore replicated **every medication administration once per episode in the block**, and the forward pass paired clones with clones. **Every assertion in the notebook passed throughout**: `pair_id` uniqueness, the D39 partition and both conservation checks are all true of a duplicated frame, because duplicated inputs yield self-consistent duplicated outputs. Verified before the fix that the map is genuinely 1:1 — 0 hospitalizations appear in more than one block — so the duplicate rows carried no information at all. Bridge rows 43,006 → 34,419; the verification note in §7.3 records what that moved. |
| D43.2 | **The collapse window is 15 minutes, read from `config.json` as `collapse_gap_minutes`. It is a clinical definition of one induction sequence, and no empirical valley supports it.** | The data were asked and declined to answer, so the evidence is *published* (E.7, `pair_collapse_deltas.csv` / `.png`) rather than summarised away into a threshold. Co-administration of two different same-class agents is a Δ ≤ 1 min phenomenon: at Δ = 0 there are **4,615** different-agent intervals against **301** same-agent redoses (15.3×), at Δ = 1 **883** against **223** (4.0×), and from Δ = 2 onward the two series run at the *same* rate (6,127 vs 6,952, 0.88×). **95.3% of the positive excess sits at Δ ≤ 1**, and there is no trough at 15 minutes to fit to — there is no trough anywhere. What 15 minutes buys is the *paralytic* redosing that drives the residual multi-pair episodes (`108083_E3` charts five vecuronium doses across 50 minutes), and the span it names is a rapid-sequence induction as a clinician would bound one. That judgment is stated wherever the number appears — here, in E.7's caption and on the figure itself — so no reader mistakes a definition for a measurement. Changing it is a re-run, not a post-hoc filter, for the reason D29 gives about `pair_gap_hours`. |
| D43.3 | **The fold groups by `drug_class` (SED vs PARA), not by CLIF `med_group`.** | `med_group` splits fentanyl (`analgesia`) from propofol (`sedation`), so grouping by it would fail to merge the single most common co-administration in the data — `fentanyl+propofol`, 29,030 events. The fold must equally never cross the class boundary in the other direction: a sedative and a paralytic merged into one event leave the scan nothing to pair. `drug_class` is the only key with both properties, and it is the two lists §7.1 and §7.2 already declare, so the fold defines no new vocabulary. D38 measured and declined `med_group` for episode eligibility; this is the same vocabulary failing for the same reason in a second place, and it is recorded twice rather than once because the two uses would otherwise look independently arguable. |
| D43.4 | **Merging is anchored, never chained: a row joins the current event only while it is within the window of that event's *first* administration, and the moment it is strictly past it the row opens a new event and becomes the new anchor.** | Chaining has no bound. An agent charted every ten minutes would walk one event forward across the whole stay — measured at 115 min for the worst chained event at MIMIC — and would swallow the second intubation of a re-intubated patient entirely, which is the population D35 exists to recover. Anchoring makes `span_min ≤ collapse_gap_minutes` an *assertable invariant* rather than a hope, and `05` asserts it (max event span at MIMIC: exactly 15.0 min). The cost is 1.8% more events than chaining would produce, which buys a bounded and auditable definition. Strictly greater, not greater-or-equal, so a row landing exactly on the limit still merges and the parameter reads as "within 15 minutes" inclusively. |
| D43.5 | **An agent event's `med_category` is a combined label: every agent the event contains, sorted alphabetically and joined with `+`.** | The fold itself is blind to which agents are involved (D43.4) — a redose of one and a co-administration of two are the same clinical fact — but the *output* must not be. `fentanyl+propofol` preserves the clinical picture the pair table exists to report, makes every merge auditable from the published row rather than from a notebook print, and keeps E.3 honest. **On E.3's own basis — the index pairs of qualified episodes, 777 of them — the sedative domain is 10 labels over a 17-cell contingency, of which 12 cells survive the n ≥ 10 rule carrying 7 distinct sedative labels**; that is `pair_agent_combinations.csv` as published, 12 rows, and **half of them carry a combined label** (`fentanyl+propofol` 95 index pairs against rocuronium, `fentanyl+midazolam` 41 against vecuronium). Over the whole pair table — a **different and larger grid, which E.3 does not publish** — the same quantities are 12 labels over 19 cells with 14 at n ≥ 10; they are named here only so the two bases can never again be reported as one, which has already happened twice in this work. Those combinations were always in the data and were previously reported as whichever single agent happened to win the scan. Alphabetical sorting makes the label canonical, so one combination is one row of E.3 rather than several orderings of itself. |
| D43.6 | **`med_dose` and `med_dose_unit` on a merged event refer to the first agent named in the label, taken from that agent's earliest administration in the event.** | Doses of different drugs cannot be summed — propofol in mg beside fentanyl in mcg — and §7.3 forbids unit conversion outright, so an aggregate dose is not available at any price. Nulling the field instead would silently kill E.3's `median_sed_dose`, the one clinical number in that table. Naming one agent's dose keeps the column numeric and keeps the value *true of something*, and because the label is alphabetically sorted (D43.5) the rule is self-consistent: the same combination always reports the same agent's dose, at every site. Which agent that is, the reader gets by reading the label — which is why the label sits in the table beside the two columns rather than anywhere else. |
| D44 | **The timezone always comes from `config["timezone"]`. No code path may consult the operating system's zone — not on the way in, and not on the way out.** | Set by the study lead as a standing rule after a second leak was found, one §5.13's existing guard does not cover. **On the way in**, `.dt.tz_localize(None)` on a clifpy column drops the *attached* LMT offset rather than the correct one, shifting every timestamp by about an hour without raising; that is §5.13, it is fixed by `to_site_naive`, and it is pinned by `tests/test_clifpy_tz_boundary.py`. **On the way out**, `datetime.timestamp()` on a site-naive value re-attaches the *machine's* zone: on a host set to US/Central holding US/Eastern data, 10 minutes of wall clock across the November fall-back measures as **70**. A 60-minute artefact decides a 15-minute window outright, splitting one push of drug into two agent events — and the answer then changes with the machine, which the byte-identical-across-runs property of §6.2 forbids outright. `05` converts inside polars with `epoch_minutes()`, `pl.col(c).dt.epoch("s") / 60`, which reads the stored wall-clock value and consults no zone at all; `tests/test_collapse_agent_events.py` pins it across a DST fall-back so the shortcut cannot come back. **One known exception remains, flagged here rather than fixed**: `COHORT_RUN_ID` in `code/01_cohort.py` stamps `datetime.now()` in OS-local time. Nothing computes on it — it is a provenance label, not analytic data — but it is ambiguous across machines, so two sites' run ids are not comparable as timestamps and must not be read as though they were. |

------------------------------------------------------------------------

## 3. Architecture

```         
code/
  01_cohort.py            encounter stitch + cohort CONSORT + waterfall
  02_index_imv.py         episode detection + t₀ + window bounds + index CONSORT (DEV)
  03_method_sedative.py   ┐  each fully self-contained:
  04_method_paralytic.py  │  config → index_imv + ONE CLIF table
  05_method_pair.py       ┘  → own logic → artifacts → assert own schema
  06_reference_cpt.py     CPT 31500 presence
  07_agreement.py         schema gatekeeper + agreement + distributions
```

`01` and `02` are the two funnel stages and each emits its own CONSORT: `01` answers *who is in the study*, `02` answers *when, and how many times, each of them was intubated*. Only `02`'s survivors reach the methods.

The two stages also split cleanly by unit. `01` is the only notebook that thinks in **hospitalizations** and it resolves them into blocks; `02` is the only notebook that thinks in **device rows** and it resolves them into episodes. Everything from `03` onward sees only episodes.

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

**Three units, resolved in order, each by exactly one stage.** `hospitalization_id` is resolved into `encounter_block` by `01` and never seen again (§5.3). `encounter_block` plus the device timeline is resolved into `intubation_episode_id` by `02` and is thereafter carried but not keyed on (§5.9). **The analytic unit is the episode** (D35), and everything from `03` onward keys on it.

The analytic set is built in two stages, each with its own CONSORT. §5.1–§5.8 cover `01_cohort.py`, which answers *who is in the study*. §5.9–§5.13 cover `02_index_imv.py`, which answers *when, and how many times, each of them was intubated*.

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

### 5.6 Waterfall

`01` produces the device timelines. It no longer decides t₀ — that moved to `02` with D34, because t₀ is now a property of an episode and `01` does not know what an episode is.

1.  Subset `respiratory_support` to all hospitalizations listed in the cohort's `list_hospitalization_id`.
2.  Run `process_resp_support_waterfall(..., bfill=True)` on those rows (D6 — the flag is inert here, and D6 records why it is set anyway).
3.  Map waterfalled rows to `encounter_block` via `list_hospitalization_id`, then order by `recorded_dttm` **within the block**. This is `cohort_resp_waterfall.parquet`.
4.  Separately, project the **raw** rows where `device_category == 'imv'` to `(encounter_block, recorded_dttm)`. This is `cohort_resp_imv_raw.parquet`, and its only consumer is the charting-delay statistic in `02` (D34) — no rule reads it.

Step 3 is what makes stitching effective: the waterfall runs per `hospitalization_id`, but the sequence §5.9 scans is assembled across the whole block in time order. An ED presentation and the inpatient admission stitched to it form one continuous respiratory record, so an intubation in the ED and the ventilation that follows upstairs are one episode rather than two.

**Both frames are produced because they answer different questions, and only one of them is a rule.** The waterfalled frame is the airway record made continuous, and every device test in §5.9 runs on it. The raw IMV frame is the record of what a human typed, and it exists solely so the gap between the two can be published rather than assumed. Under D23 that relationship was inverted — the raw frame held the rule and the waterfall was the suspect — and D34 reverses it on a clinical argument recorded there.

> **This is where D21 pays for itself.** `clifpy/utils/waterfall.py:147-149` **lower-cases** `device_category`, `device_name`, `mode_category` and `mode_name`. Under a spec that compared against mCIDE casing, that single line would silently break every device test: `device_category == 'IMV'` on waterfalled data does not error, it matches nothing, and every block comes back with no episodes at all.
>
> Because D21 already lower-cased the column on load, the waterfall's transformation is a **no-op** — the values it writes are the values that were there. No step re-normalises anything, no notebook holds two vocabularies, and the same literal `'imv'` is correct on both sides of the call.
>
> The library also coerces `tracheostomy` to `1.0` / `0.0` with `pd.to_numeric` (`:152-159`), which is why §5.5 tests truthiness rather than identity.
>
> **This is worth stating as a general property, not a note about one function.** Normalising to a *canonical* vocabulary means every library that touches the data must be checked for whether it agrees with that canon. Normalising *down* means the only libraries that can hurt you are the ones that upper-case — and none do, because lower-casing is the near-universal convention. The rule is cheaper to hold than the exceptions to it.

### 5.7 QC statistics

| Stat | Purpose |
|---|---|
| Timestamp alignment — every non-scaffold waterfalled row exists in the raw table, per hospitalization | The waterfall adds rows only at `HH:59:59`; it never invents a timestamp elsewhere. If the raw and waterfalled frames are converted from clifpy by different paths this subset relation breaks immediately, which is how the pytz/LMT one-hour bug was caught (§5.13). |
| Blocks per encounter — distribution of `len(list_hospitalization_id)` | Shows how much stitching actually did. If nearly every block is a single hospitalization, stitching is not the mechanism it was added for and that should be known before interpreting §8. |
| % of blocks whose first IMV row falls in a *different* `hospitalization_id` than the block's first row | The direct measure of the artifact §5.1 exists to remove. |

The Δ statistic that used to head this table has moved to `02` and become `charting_delay_min` (§5.10). It is now per **episode** rather than per block, because under D35 a block has several, and it is now a published result rather than a QC check, because under D34 it is the quantity the anchor was chosen on.

### 5.8 Outputs of `01`

| File | Contents |
|---|---|
| `cohort.parquet` | one row per included `encounter_block`, with demographics and `list_hospitalization_id` |
| `cohort_resp_waterfall.parquet` | waterfalled respiratory rows for cohort blocks, carrying `encounter_block` |
| `cohort_resp_imv_raw.parquet` | `encounter_block`, `recorded_dttm` for **raw charted** IMV rows only. Sole consumer is `charting_delay_min` in `02` (D34) |
| `cohort_index.parquet` | `encounter_block`, `patient_id`, `cohort_run_id`, `list_hospitalization_id` — the join spine |
| `consort_cohort.json` / `.csv` | step label, n encounter blocks remaining, n patients remaining, n excluded |
| `cohort_qc.csv` | the statistics in §5.7 |

**`cohort_index.parquet` no longer carries `t0_dttm`, `window_start`, `window_end` or `intubation_episode_id`.** All four moved to `index_imv.parquet` when D34 and D35 made them properties of an episode rather than of a block. `01` writing a block-level t₀ that `02` then overrode per episode would be exactly the kind of stale duplicate D14 warns about.

The three parquets are consumed by `02` only. The methods read `index_imv.parquet` (§5.12) and never these — reading them directly would silently include the candidates `02` exists to reject.

### 5.9 Episode detection — `02_index_imv.py`

`01` guarantees every cohort block contains at least one charted IMV row. It does **not** say how many intubations that block holds, when each began, or whether any of them is an intubation we can see happen. `02` answers all three, and its CONSORT is a first-class result rather than a preprocessing note.

**Source:** `cohort_resp_waterfall.parquet`, which already carries `encounter_block`, so no explode is needed. The sequence is ordered by `recorded_dttm` **within the block**, across all its hospitalizations. `cohort_resp_imv_raw.parquet` is read too, but only for the charting-delay statistic — no rule reads it.

Three rules, applied in order. All three device tests use `episode_gap_hours` (D36); the medication test uses `window_hours` (D4).

**Rule 1 — episode start.** An `imv` row starts an episode iff no `imv` row precedes it within `episode_gap_hours` in the same block.

```
                    ← episode_gap_hours →
              ┌────────────────────────────┐
   this imv   │  any imv charting in here? │
   row  ──────┤                            │
              └────────────────────────────┘
                    │                  │
                  YES                 NO
                    │                  │
                    ▼                  ▼
          already ventilated —    THIS ROW STARTS
          not a start            AN EPISODE
```

> **One predicate doing two jobs, which is the whole reason this stays simple.** It *is* the pre-period test — if no IMV precedes within the interval then every row in that interval is by definition a different device or nothing at all. And it is *also* the segmenter: a mid-episode IMV row has IMV inside its own lookback and disqualifies itself, so consecutive IMV rows collapse to the one that started the run.
>
> There is no episode loop, no in-episode state to carry, and no mid-episode branch to get wrong. On MIMIC, 6,957,207 waterfalled rows reduce to **42,488 candidates** with a single `shift(1)` over IMV-only rows.

**Rule 2 — sustained.** Reject the candidate if any row in `(ep_start, ep_start + episode_gap_hours]` carries a non-null `device_category` that is not `imv`. **A null device passes** (D37). MIMIC: −2,218 → 40,270.

**t₀ = `ep_start`** (D34). Not the first raw charted IMV row. `window_start = t₀ − window_hours`, `window_end = t₀ + window_hours`.

**Rule 3 — induction-med positivity.** Reject the candidate unless at least one `medication_admin_intermittent` row with `mar_action_category = 'given'` and `med_category` in the eight method categories (§7.1, §7.2) falls in `[window_start, window_end]` (D38). MIMIC: −26,770 → **13,500**.

> **Rule 3 conditions the study on the thing the study measures, and D38 records that in full.** `SED ∨ PARA` is true for every qualifying episode by construction. §8's Tier A is correspondingly narrowed — from "do the methods find the same intubations?" to "given that an induction agent was charted, do the methods catalog it the same way?" — and the A.2 `SED−/PARA−` cell is empty by definition rather than by finding. This is the study lead's decision, taken with the alternative measured; it is written here so no reader mistakes an artifact of the cohort for a result.

**What retired, and why it is not a loss.** The M2 symmetric 2/2 rule with `B_strict` boundary policy is gone (D36), and with it the `arrived_intubated`, `insufficient_lookback` and `prior_row_imv` classes. The first two retired because D37 stopped treating a missing row as a failed term. `prior_row_imv` retired for a different reason worth stating: under Rule 1 an IMV row with IMV in its lookback is not a *class*, it is simply not an episode start — it sits inside an episode that was already emitted at its own beginning. The condition that was once a rejection is now the mechanism that finds the right row.

### 5.10 What `02` labels but does not exclude

Every surviving episode carries these. They are strata for §8, not filters — the single subsetting decision in the pipeline lives in `07` (D20).

| Column | Type | Meaning | MIMIC |
|---|---|---|---|
| `ep_num` | int | 1 = index intubation, > 1 = reintubation, chronological by t₀ within the block **over the sustained set** | 1,940 of 13,500 are > 1, in 1,654 blocks |
| `no_lookback` | bool | t₀ is the block's **first** respiratory row — the old `arrived_intubated` (D37) | 7,130 of 13,500 (52.8%) |
| `imv_charted` | bool | some raw charted IMV row exists in this episode | 13,494 of 13,500 |
| `first_charted_imv_dttm` | datetime | earliest raw charted IMV row at or after t₀ and before the next candidate start; null if none | |
| `charting_delay_min` | float | `first_charted_imv_dttm − t₀`; null if never charted | see below |

**`charting_delay_min` is the quantity D34 was decided on, and it is now published rather than avoided.**

| | |
|---|---|
| delay exactly 0 | 77.3% |
| p90 | 23 min |
| p95 | 55 min |
| p99 | **540 min (9 h)** |
| max | 6,389 min (4.4 days) |
| never charted in the episode | 7 episodes |

`charting_delay_min ≥ 0` is guaranteed, not hoped for: the waterfall relabels null-device rows to `imv` and never deletes a charted row, so its IMV set is a superset of the raw one in time and its first element cannot be later. **`02` asserts it.** A site where the assertion fires has a frame-alignment bug — almost certainly the pytz/LMT one in §5.13 — not an unusual charting culture.

A p99 of nine hours is the argument for D34 stated as a number. It is not a plausible error in reading ventilator settings; it is a plausible delay in filling out a device field after a crash intubation.

### 5.11 CONSORT B — index

The second CONSORT, and a headline result rather than a preprocessing note. **Every step reports three counts** — episodes, encounter blocks and patients — because the unit changed at the top of this stage and a reader tracking blocks through `01` needs the bridge.

```         
  cohort blocks from 01                             34,017 blocks / 31,124 patients
    │
    │  6,957,207 waterfalled device rows
    ▼
  candidate episode starts                          42,488 episodes / 34,017 blocks
    │    Rule 1 — no IMV within episode_gap_hours before
    │
    ├─ EXCLUDE not_sustained                        −2,218
    │    a non-IMV device within episode_gap_hours after
    │
    ├─ EXCLUDE no_induction_med                     −26,770
    │    none of the 8 agents given in t₀ ± window_hours
    │
    └─ INDEX IMV EPISODE SET                        13,500 episodes
                                                    12,503 blocks / 11,935 patients
```

Reported alongside it, as a table with rates over the candidate set:

| `index_class` | episodes | % |
|---|---|---|
| `qualified` | 13,500 | 31.8 |
| `not_sustained` | 2,218 | 5.2 |
| `no_induction_med` | 26,770 | 63.0 |
| **total** | **42,488** | **100.0** |

Three numbers to read, in this order.

**`no_lookback` at 52.8%** is the first. Catalog §9.4 reports an arrived-intubated rate around 31% across sites, so a site landing far from that has either a stitching problem (§5.7) or a genuinely different referral pattern, and which one it is must be settled before the episode set is trusted. Note that this is now a rate *within* the qualifying set rather than an exclusion, so it is not directly comparable to a catalog figure computed as an exclusion — the difference is D37 and should be stated when the two are placed side by side.

**`no_induction_med` at 63.0%** is the second, and it is mostly not a data-quality statement. Two thirds of sustained ventilation episodes in a stay are not intubations — they are the continuation of ventilation across a gap in charting, a return from theatre, a re-scan after a device change. Rule 3 is what separates *the episode began here* from *ventilation resumed here*, and this is the size of that separation.

**Episodes per block** is the third: 11,675 blocks with one, 701 with two, 99 with three, tail to seven. A site where this is flat at one has either no reintubations or an `episode_gap_hours` too wide to see them.

> **`ep_num` counts sustained episodes, not qualified ones**, and the difference is large: 1,940 qualified episodes have an earlier *sustained* episode in their block against 997 with an earlier *qualified* one. The sustained numbering is the correct one. A `no_induction_med` episode is still a real ventilation episode — it simply had no induction charted — so an intubation that follows one genuinely is the block's second. Numbering only qualified episodes would also make Tier D.2 circular, since "an earlier episode also had induction charted" describes the filter rather than the patient.

### 5.12 Outputs of `02`

| File | Contents |
|---|---|
| `index_imv.parquet` | **one row per candidate episode, not per qualified episode.** `intubation_episode_id`, `encounter_block`, `patient_id`, `cohort_run_id`, `ep_num`, `index_class`, `index_qualified`, `t0_dttm`, `window_start`, `window_end`, `list_hospitalization_id`, plus the §5.10 labels |
| `consort_index.json` / `.csv` | the steps in §5.11 with episode, block and patient counts |
| `index_class_rates.csv` | the stratum table in §5.11 |
| `charting_delay.csv` | the `charting_delay_min` distribution in §5.10, binned and suppressed per §9 |

Keeping the rejected candidates in the file rather than filtering them out is deliberate (D20). The methods run over every row and carry `index_class` into their own output (§6.4); `07` is the single place that splits primary from probe. No notebook ever has to reach back past `02`, and no notebook silently decides the analytic set on its own.

> **`index_imv.parquet` is the only file in the pipeline that knows what an episode is.** Everything downstream receives episodes as given and never re-derives one. That is what makes D36 a config change rather than a rewrite: moving `episode_gap_hours` re-runs `02` and everything after it consumes the new set without a line changing.

### 5.13 The clifpy timezone boundary

Referenced from §5.7 and §5.10. This is a correctness constraint on every notebook, not a note about one function.

clifpy returns timestamp columns that are timezone-**aware**, and the `tzinfo` attached is a pytz `DstTzInfo` carrying the **LMT** offset — `US/Eastern` arrives as `LMT-1 day, 19:04:00 STD`, a pre-standardisation local mean time roughly 56 minutes off the modern offset. Calling `.dt.tz_localize(None)` on such a column drops the *attached* offset rather than the *correct* one, shifting every timestamp by about an hour. It does not raise. It does not warn. Every downstream comparison still runs, and every one of them is wrong by an amount small enough to look like clinical variation.

The only correct conversion, repeated verbatim in every notebook rather than shared (D8):

``` python
def to_site_naive(series):
    """The only correct way to get a naive site-local timestamp out of clifpy."""
    return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)
```

Three defences, in order of how early they fire:

1.  **`tests/test_clifpy_tz_boundary.py`** pins the behaviour against the installed clifpy, so a library upgrade that changes the returned `tzinfo` fails a test rather than a study.
2.  **The timestamp-alignment check in §5.7.** The waterfall only ever *adds* rows, at `HH:59:59` scaffold positions, so every non-scaffold waterfalled timestamp must exist in the raw table for its own hospitalization. If the raw and waterfalled frames took different conversion paths the subset relation breaks immediately. This is how the bug was originally caught.
3.  **`charting_delay_min ≥ 0` in §5.10.** The raw IMV rows are a subset of the waterfalled ones in time, so a negative delay is impossible unless the two frames are on different bases.

Each check compares two frames that *must* agree; none of them tests the conversion in isolation, because a conversion applied consistently-wrongly to one frame is undetectable from that frame alone.

------------------------------------------------------------------------

## 6. Method contract

Each method is a **profiler**, not merely a detector. Anchored on t₀, it reports the ranked medication sequence around the intubation — with dose, unit and lag — from which the binary detection flag falls out for free.

### 6.1 The intubation episode

Every analytic artifact is keyed on `intubation_episode_id`, formed as `{encounter_block}_E{ep_num}` with `ep_num` running from 1 in chronological order of t₀ within the block (D35).

A block contributes as many rows as it has candidate episodes. At MIMIC, 11,675 qualifying blocks hold one, 701 hold two, 99 hold three, with a tail to seven; **1,940 of 13,500 qualifying episodes are reintubations**, spread over 1,654 blocks.

> **This key shape was reserved before it was needed.** An earlier draft of this section read *"the suffix is always `E1` … it exists so that widening scope to reintubation later adds `_E2` rows without changing any key, join or schema."* D35 is that widening, and the promise held: no key, join or schema moved. The cost of carrying an unused suffix for one build was one character per row; the cost of not having carried it would have been a migration of every artifact in §6 and every join in §8.

`method_PAIR_pairs.parquet` is the one artifact that is *not* one row per episode (§6.5). Its own key is `pair_id`, formed as `{encounter_block}_P{pair_seq}` — **block-scoped, not episode-scoped**, because the scan that produces it is free-running over the block (D27) and a pair exists before it is assigned to an episode (D39). It carries `intubation_episode_id` as a foreign key so it still joins to everything else. The two id schemes are deliberately distinct in both separator letter and cardinality — `_E` is many per block but one per analytic row, `_P` is many per analytic row — so a mis-join fails on the key rather than silently fanning rows out.

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
     "delta_minutes": -4.0,
     "infusion_prep": false, "during_infusion": false, "lag_to_infusion_min": null},
    {"rank": 2, "med_category": "midazolam", "med_dose": 2.0,
     "med_dose_unit": "mg", "admin_dttm": "2130-04-12T03:02:00",
     "delta_minutes": -12.0,
     "infusion_prep": false, "during_infusion": false, "lag_to_infusion_min": 41.0},
    {"rank": 3, "med_category": "fentanyl", "med_dose": 100.0,
     "med_dose_unit": "mcg", "admin_dttm": "2130-04-12T02:55:00",
     "delta_minutes": -19.0,
     "infusion_prep": false, "during_infusion": true, "lag_to_infusion_min": null}
  ],
  "after": [
    {"rank": 1, "med_category": "midazolam", "med_dose": 2.0,
     "med_dose_unit": "mg", "admin_dttm": "2130-04-12T03:52:00",
     "delta_minutes": 38.0,
     "infusion_prep": true, "during_infusion": false, "lag_to_infusion_min": 8.0},
    {"rank": 2, "med_category": "fentanyl", "med_dose": 100.0,
     "med_dose_unit": "mcg", "admin_dttm": "2130-04-12T04:30:00",
     "delta_minutes": 76.0,
     "infusion_prep": false, "during_infusion": true, "lag_to_infusion_min": null}
  ]
}
```

`delta_minutes` is signed: negative before t₀, positive after. Both arrays are empty when nothing was found; the object is still written, so the file has one record per candidate episode.

**The three D40/D41 fields are per-administration properties, carried on every entry in both arrays.**

- `lag_to_infusion_min` — minutes from this administration to the next `start` row in `medication_admin_continuous` for the same `med_category`, or null if the drug is never subsequently infused. Signed positive by construction; the as-of join is forward-only.
- `infusion_prep` — `direction == "after" AND lag_to_infusion_min <= infusion_prep_minutes`. **Always false on a `before` entry**, because D40 exempts that half. The field is still written there rather than omitted, so a consumer can filter on one predicate across both arrays without special-casing direction.
- `during_infusion` — the most recent same-drug row in `medication_admin_continuous` before this administration is not a `stop`. Computed on **both** halves (D41), where it is the whole point: the field exists to be compared across t₀, and suppressing it before t₀ would manufacture the asymmetry D41 went looking for and did not find.

Note in the example that entry `before`/rank 2 carries a non-null `lag_to_infusion_min` of 41 minutes and is still not prep. That is the ordinary induction → maintenance sequence and D40 leaves it alone; the lag is published so the exemption can be audited rather than trusted.

### 6.4 `method_<ID>_episode.parquet` — joinable

One row per **candidate episode**, including non-detections and including the episodes `02` rejected. Emitted by all three methods. This is what §8 joins on; the JSON is not join-friendly at scale.

> **Renamed from `method_<ID>_encounter.parquet` under D35.** The file holds one row per episode, and a block can now contribute several — a name promising encounter cardinality would be wrong in exactly the way §6.1 designs the key schemes to prevent. The rename is mechanical and was taken now rather than left as a stale label.

The table below has two parts. The **core columns** (`encounter_block` through `detected`) are emitted by every method and are what `07` validates on load. The **ranked columns** (`n_before` through `nearest_after_min`) are emitted by `SED` and `PARA` only; `PAIR` replaces them with the pair columns of §6.5. A method is validated against the core plus exactly one extension, never both.

> **Why methods run on the rejected episodes too.** Restricting the run to `index_qualified = true` would be the obvious reading of §5.11, and it is wrong here: Tier D needs the method rates *inside* the rejected strata, and computing them later would mean a second pass over the medication tables under logic that would then exist in two places. Running everything once and carrying `index_class` through costs nothing — the window is already fixed for every candidate episode by `02` — and leaves the primary/probe split as a single `filter` in `07`. **The subsetting decision lives in `07`, not in the methods.**
>
> One stratum is degenerate and §8 says so rather than reporting it as a result: every `no_induction_med` episode is `SED−` and `PARA−` by construction (D38), so its detection rate is 0 by definition. `PAIR` is the exception — it is free-running, so it can fire on an episode the window filter rejected.

| Column | Type | Notes |
|---|---|---|
| `intubation_episode_id` | str | `{encounter_block}_E{ep_num}`, copied from `index_imv` — **the analytic key** |
| `encounter_block` | int32 | carried through; a block may appear on several rows |
| `patient_id` | str | carried through for patient-level counts |
| `ep_num` | int | copied unchanged from `index_imv`; §5.10 |
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
| `detected_induction_only` | bool | D40. `detected` with prep administrations removed |
| `n_after_induction` | int | distinct `med_category` with ≥1 **non-prep** administration after t₀ |
| `n_after_prep` | int | distinct `med_category` with ≥1 prep administration after t₀. Not the complement of `n_after_induction` — a drug with both a prep and a non-prep dose counts in both. Carried so F.4 can cross-tab against `charting_delay_min` without reopening the medication tables |
| `n_before_during` | int | D41, descriptive. Distinct `med_category` with ≥1 administration before t₀ given during a running same-drug infusion |
| `n_after_during` | int | D41, descriptive. The same after t₀ |
**`detected` is derived, not independently computed:** `detected = (n_before > 0) OR (n_after > 0)`, and `detected_induction_only = (n_before > 0) OR (n_after_induction > 0)`. The before-half is common to both because D40 exempts it.

> **The counts are taken on the unranked window set, and filtering the published ladder does not reproduce them.** This is a real discrepancy, stated here rather than left to be discovered. `n_after` and `n_after_induction` both count *distinct `med_category` values holding at least one qualifying administration*, computed before §6.2's deduplication runs. The ladder keeps only the administration **nearest t₀** per category, so a category whose nearest after-dose is prep but whose second dose is not contributes to `n_after_induction` while its single ladder entry is flagged `infusion_prep`. Counting off the ladder would score that episode as having no induction evidence for the drug when it has some.
>
> The ordering is therefore fixed and is not an implementation detail: **filter, then rank — never rank, then filter.** `detected_induction_only` is computed from the window set directly; the ladder carries `infusion_prep` for profiling only. `07` must not recompute a rate by filtering `method_<ID>_ranked.json`.

There is no `non_detection_reason` column. For a medication method the reason is always the same — no qualifying `med_category` was charted in the window — so a column carrying one constant string would add a field without adding a fact. The informative non-detection reasons all concern whether the intubation was observable, and those live in `index_class` (§5.10), one stage upstream where they are decided.

Deriving the binary from the ranked structure rather than computing it separately means the two cannot disagree. Non-detections are retained as `detected = false` rows; they are the denominator for every rate in §8.

For `PAIR` the same principle holds with a different source structure: `detected = n_pairs > 0`, derived from the pairs table rather than computed alongside it (§6.5).

### 6.5 `PAIR` artifacts

`PAIR` emits two files. The pair-level table is canonical — the episode table is derived from it entirely, so the two cannot disagree.

**`method_PAIR_pairs.parquet` — canonical, one row per pair.** Not one row per episode: an episode with no pairs contributes no rows here, and a long stay may contribute many. Ordered by `encounter_block`, then `pair_seq`.

**Pairs are found per block and assigned per episode (D39).** The scan is free-running over the whole block (D27, D28), so it runs once and knows nothing about episodes. Each resulting pair is then assigned to the episode whose t₀ is nearest to `pair_dttm`, ties to the earlier episode. The assignment is a partition: summing `n_pairs` over a block's episodes recovers the block's pair count exactly, and no pair is scored twice. `05` asserts that conservation rather than assuming it.

**The two members of a pair are *agent events*, not administrations (D43).** Before the scan runs, `05` folds same-class administrations within `collapse_gap_minutes` of each other into one agent event (§7.3). So `sed_med_category` may carry a combined label such as `fentanyl+propofol`, `sed_admin_dttm` is the **earliest** administration in that event, and `sed_med_dose` belongs to the first agent the label names (D43.6). `n_sed_admin` and `sed_span_min` — and the paralytic pair of them — are the fold's audit trail: how many rows were merged, and how far apart the first and last of them were. Every merge is therefore recoverable from the published pair row without re-reading the medication table.

| Column | Type | Notes |
|---|---|---|
| `encounter_block` | int32 | the scan's unit |
| `patient_id` | str | |
| `intubation_episode_id` | str | the episode this pair was assigned to (D39) — the analytic key |
| `ep_num` | int32 | copied unchanged from the assigned episode; §5.10 |
| `cohort_run_id` | str | copied unchanged; §6.1 |
| `index_class` | str | copied unchanged; §5.10 |
| `index_qualified` | bool | copied unchanged |
| `pair_id` | str | `{encounter_block}_P{pair_seq}` |
| `pair_seq` | int | 1-based, in scan order within the encounter |
| `first_class` | str | `SED`, `PARA`, or `SIMULTANEOUS` when the gap is exactly zero |
| `sed_med_category` | str | the sedative member — the agent event's label: every agent it contains, sorted alphabetically and joined with `+` (D43.5) |
| `sed_med_dose` | float | verbatim from the earliest administration of the **first agent the label names** (D43.6); never summed across agents |
| `sed_med_dose_unit` | str | verbatim, same row as `sed_med_dose` |
| `sed_admin_dttm` | datetime | the **earliest** administration in the event — its anchor (D43.4) |
| `n_sed_admin` | int32 | administrations folded into the event; 1 when nothing merged |
| `sed_span_min` | float64 | last minus first administration in the event, minutes; `≤ collapse_gap_minutes` by construction, asserted in `05` |
| `para_med_category` | str | the paralytic member, same labelling rule (D43.5) |
| `para_med_dose` | float | verbatim, first agent named (D43.6) |
| `para_med_dose_unit` | str | verbatim, same row as `para_med_dose` |
| `para_admin_dttm` | datetime | the **earliest** administration in the event |
| `n_para_admin` | int32 | administrations folded into the event |
| `para_span_min` | float64 | as `sed_span_min` |
| `pair_dttm` | datetime | the **earlier** of the two event anchors — the pair's own intubation timestamp |
| `gap_minutes` | float | `abs(sed_admin_dttm − para_admin_dttm)` — between the two *anchors*, always ≥ 0 and always `< pair_gap_hours × 60` |
| `imv_dttm` | datetime | t₀, copied from `index_imv` |
| `pair_to_t0_min` | float | signed: `pair_dttm − imv_dttm`, negative before t₀ |
| `in_window` | bool | `pair_dttm` falls within `[window_start, window_end]` |

`in_window` is the only place `PAIR` touches the ±3 h window, and it is descriptive rather than restrictive — the scan already ran over the whole encounter (D27). It exists so `07` can report the free-running and window-matched readings side by side without a second pass.

**`method_PAIR_episode.parquet` — one row per candidate episode.** Core columns of §6.4 plus the pair extension below, replacing the ranked columns. `detected` is `n_pairs > 0`, counted over the pairs assigned to that episode.

| Column | Type | Notes |
|---|---|---|
| `n_pairs` | int | 0 for a non-detection |
| `n_unpaired_sed` | int | sedative **agent events** the scan never paired (D32, D43). One unpaired event may stand for several charted doses — its `n_admin` — so this is not a count of administration rows |
| `n_unpaired_para` | int | paralytic **agent events** the scan never paired; same caveat |
| `detected_in_window` | bool | any pair with `in_window`; the matched-denominator reading (D33) |
| `first_is_nearest` | bool | whether the two index pairs are the same pair; null when `n_pairs = 0` |
| `first_pair_id` … | | the **first pair chronologically** — `pair_id`, `first_class`, `sed_med_category`, `sed_med_dose`, `sed_med_dose_unit`, `n_sed_admin`, `sed_span_min`, `para_med_category`, `para_med_dose`, `para_med_dose_unit`, `n_para_admin`, `para_span_min`, `gap_minutes`, `pair_to_t0_min`, each prefixed `first_` |
| `near_pair_id` … | | the **pair nearest t₀** — same fourteen fields, each prefixed `near_` |

The four fold columns travel *inside* each member's group rather than being appended after `pair_to_t0_min`, so a member's identity, dose and audit trail stay adjacent in both blocks. **That order is a contract, not a formatting choice**: `07`'s schema gate asserts exact column-list equality against this file, so a column inserted elsewhere fails the run rather than drifting. The episode table is 43 columns wide.

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

> **Every `SED` detection originates in the intermittent table. The continuous table is read, but only to take detections away.** Propofol and fentanyl are also charted as continuous maintenance infusions. An induction bolus and a maintenance infusion are the same drug performing two different clinical acts, distinguished by which table they are charted in, so pulling propofol from both would conflate intubating a patient with sedating one already ventilated. `medication_admin_continuous` is loaded, filtered to this method's `med_category` list and nothing else, solely to classify intermittent rows that have already been found. **No row of it can create a detection.** The two flags consume it differently and both subsets are needed: D40 reads only `mar_action_category = 'start'`, since prep is defined against an infusion *beginning*; D41 reads the **full event stream** — `start`, `stop`, `dose_change`, `going` — because "is a drip running right now" is answered by the most recent event of any kind, not by starts alone. That asymmetry is what keeps D1a's removal of `INF` intact, and it is why the earlier form of this note ("never the continuous table") was revised rather than deleted: the sentence it was protecting is still true.

**D40 — infusion prep.** An administration in `(t₀, window_end]` followed within `infusion_prep_minutes` by a same-`med_category` infusion `start` is flagged `infusion_prep` and excluded from `detected_induction_only`. `[window_start, t₀)` is exempt. **D41 — during infusion.** Every administration in both halves is flagged `during_infusion` when the most recent same-drug continuous row before it is not a `stop`. This flag is descriptive and changes no rate.

Alongside the two ordinary artifacts, `SED` writes `method_SED_prep_sweep.parquet` — the D40 rule recomputed over the threshold grid `5, 10, 15, 30, 45, 60, 90, 120, 150, 180` minutes, per `med_category` and pooled. The configured `infusion_prep_minutes` is one point on that grid and carries no special status in the file; §8.2 publishes the curve so the threshold can be chosen against evidence rather than defended from first principles.

`med_dose` and `med_dose_unit` are taken verbatim from the administration row. **No unit conversion or dose normalisation is performed** — the raw charted value is what a reviewer needs to see, and normalising would hide unit heterogeneity that is itself worth measuring across sites.

### 7.2 `PARA` — `04_method_paralytic.py`

Source: `medication_admin_intermittent`, filtered to `mar_action_category = 'given'` and `med_category` in:

```         
rocuronium | succinylcholine | vecuronium
```

Ranked per §6.2. At most 3 before-ranks and 3 after-ranks. Dose handling as for `SED`.

**D40 and D41 apply here identically**, including `method_PARA_prep_sweep.parquet` over the same grid. The effect at MIMIC is small — 584 detected episodes fall to 553 at the 60-minute threshold, and `during_infusion` reaches 18 of 588 qualified ranked entries — but the rule is not carried here for its effect. It is carried because `SED` and `PARA` must mean the same thing by "an administration in the window", and a site that runs cisatracurium or vecuronium infusions for ventilator dyssynchrony will see a materially larger one. Applying it to only one method would make the two methods' `detected` columns non-comparable in Tier A while looking as though they were.

### 7.3 `PAIR` — `05_method_pair.py`

**Sedative–paralytic co-administration. The question is not "was a drug given near the intubation" but "were the two drug classes given together, and where in the stay".**

Source: `medication_admin_intermittent`, filtered to `mar_action_category = 'given'` and `med_category` in the **union** of the two lists, with each administration labelled by class:

```         
   class = SED    midazolam | etomidate | ketamine | propofol | fentanyl
   class = PARA   rocuronium | succinylcholine | vecuronium
```

The lists are re-declared literally in `05_method_pair.py` and not imported from `03` or `04` (D8). They must stay identical to §7.1 and §7.2 — the schema assertion block at the end of the notebook checks the declared lists against the values actually present in the output.

**The scan is not restricted to the window.** It runs over every qualifying administration in the stitched encounter — folded into agent events first (below), so what the scan itself walks is the event sequence. The §6.2 sort is applied on both sides of the fold and is the same sort each time: by `admin_dttm` with ties broken alphabetically by `med_category`, which for an event means its **anchor** timestamp and its **combined label**. t₀ is joined afterwards to compute `pair_to_t0_min` and `in_window`, and plays no part in which pairs form (D27).

`PAIR` runs in **two stages, and they are one algorithm**: the collapse below turns administrations into agent events, and the scan after it pairs those events. Reading either alone gives the wrong answer about what a pair is. Text written before D43 — D28, D32, and the three load-bearing properties below — says "administration" where the scan's unit is now an agent event. **The scan's unit changed; its rule did not**, which is why those passages were left as written rather than reworded around a change they do not describe.

#### The collapse — administrations become agent events (D43)

The scan counts *pairings*, so what it is handed decides what a pair means. A raw administration row is not a clinical event: one rapid-sequence induction is charted as fentanyl 08:14, propofol 08:14, rocuronium 08:15, and a repeat push of the same agent two minutes later is still the same push of drug. Handed those rows the scan forms a pair for every sedative it can match and reports several intubations where the chart describes one.

So before the scan runs, administrations of the same `drug_class` (D43.3) within `collapse_gap_minutes` of each other, in the same encounter, are folded into one **agent event**:

```
   for each (encounter_block, drug_class), rows already in §6.2 time order:
       start a new event at the first row
       each next row joins the event  if  t[row] - t[event's FIRST row] <= gap
       otherwise it opens a new event and becomes the new anchor
```

The comparison is against the event's **first** row and never against the previous one (D43.4). Chained, a repeatedly-charted agent would walk one event forward without bound and swallow the second intubation of a re-intubated patient; anchored, `span_min ≤ collapse_gap_minutes` holds end to end and `05` asserts it. The fold is *within* a class and never across it — a sedative and a paralytic merged into one event would leave the scan nothing to pair — and it is blind to which agents are involved, because a redose of one agent and a co-administration of two are the same clinical fact. What survives carries the combined label (D43.5), the dose of the first agent named (D43.6), `n_admin` and `span_min`.

**Worked examples for the fold**, at `collapse_gap_minutes = 15`. These are the implementation's test cases, asserted in `05`'s `_self_test` before any data is touched and again in `tests/test_collapse_agent_events.py`. Times are minutes from the first row; each is one drug class of one encounter.

| # | administrations at | events | what it pins |
|---|---|---|---|
| a | `0, 0` | `[0, 1]` | same-instant co-administration merges — the common case |
| b | `0, 15` | `[0, 1]` | exactly at the limit still merges (`>`, not `>=`) |
| c | `0, 16` | `[0]`, `[1]` | one minute past the limit splits |
| d | `0, 10, 20` | `[0, 1]`, `[2]` | **anchored, not chained** — 20 is 20 min past the event's start, so it splits even though it is only 10 min past its predecessor. This is the one example a chained implementation fails |
| e | `0, 5, 10, 15` | `[0, 1, 2, 3]` | a run inside one window stays one event |
| f | `0` | `[0]` | singleton — the fold is a no-op on an unmerged row |

**Minutes are computed inside polars with `pl.col(...).dt.epoch("s")`, never with `datetime.timestamp()`** (D44). A naive `.timestamp()` re-applies the operating system's zone, and across a DST fall-back that turns 10 minutes of wall clock into 70 — enough to split one push of drug into two events, and to make the answer depend on the machine.

> **Why the collapse cannot move a paralytic across a window boundary.** An agent event is anchored on its **earliest** administration — the same row `04_method_paralytic.py` already sees for that agent — so a pair's `para_admin_dttm` never moves *later* than the row `04` is evaluating. The cross-notebook `PARA` × `PAIR` integrity check in §8 was therefore expected to break and did not: it still decomposes exactly (`only_b` 62 = D25's on-t₀ rule 32 + §6.5's `in_window`-on-`pair_dttm` rule 30, zero unexplained). Recorded because both D43.4 and the integrity note in Tier A would otherwise lead a reader to expect a third boundary rule that does not exist.

> **Verification note — two independent causes, one number.** `PAIR` emitted **4,110** pairs before this change and emits **1,535** after, a 62% drop, and anyone comparing runs needs to know that most of it is a *defect fix* rather than a definition change. The bridge fan-out (D43.1) was replicating every administration once per episode in its block; the collapse (D43.2–D43.6) then merged co-administered and redosed rows into agent events. Measured together, in-pipeline: bridge rows **43,006 → 34,419**; **370,687** administrations entering the fold; **276,450** agent events leaving it (SED 274,333 / PARA 2,117), max span exactly **15.0 min**; pairs **4,110 → 1,535** over 1,215 encounter_blocks; **1,272** episodes with at least one pair, of which **1,075 (84.5%)** now carry exactly one, against 61% before; max pairs in any block **52 → 9**. `sed_med_category` takes **12** distinct values including combined labels, `para_med_category` 2 (rocuronium 1,127, vecuronium 408). Published artifacts go **34 → 36** (25 CSV + 11 PNG), the two new ones being E.7. Earlier scratchpad figures for this work disagree with these and are wrong: they were computed through the timezone conversion D44 bans.

#### The pairing rule

A single forward pass with consumption (D28). It runs over **agent events** — one per element of the arrays below — and that is the only thing the collapse changed about it; the rule, its consumption semantics and `pair_gap_hours` are untouched:

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

**The rows below are agent events, and the timestamps are event anchors** — the scan never sees anything else (D43). Read as raw administrations they would now be wrong, and instructively so: at `collapse_gap_minutes = 15` the collapse would fold (a)'s fentanyl and midazolam into one event labelled `fentanyl+midazolam`, and (b) into a single sedative event against a single paralytic event — one pair, not two. That is the behaviour this change exists to produce. Each stage's examples are stated in its own terms; the fold's are in the table above.

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

`med_dose` and `med_dose_unit` are taken verbatim from an administration row, with no unit conversion or normalisation, as in §7.1. Unit heterogeneity across the two members of a pair — a sedative in mg beside a paralytic in mg/kg — is a reportable property, not something to reconcile. Where a member is a merged agent event, the row is the earliest administration of the **first agent its label names** (D43.6): doses of different drugs cannot be summed, and the alternative — nulling the field — would take E.3's `median_sed_dose` with it.

### 7.4 `DEV` — no method notebook

**The device signal has no notebook in this section.** It is the index qualifier, and it lives in `02_index_imv.py` (§5.9–§5.12) — upstream of every method, where it decides who is analysed rather than competing to be detected.

`DEV` does more than qualify now: under D34 it also *sets* t₀, and under D36 it decides how many episodes a block holds. That makes its exclusion from the agreement matrix stronger rather than weaker. Anchored on a t₀ the device rule itself produced, `SED` and `PARA` cannot disagree with it about *when* the intubation was — there is nothing left for it to be scored on except whether the surrounding record is consistent with sustained ventilation, which is a fact about charting (catalog §9.4). Scored inside an agreement matrix that fact would masquerade as a clinical signal and drag every κ toward it. See D19, and §5.9 for the rule itself.

------------------------------------------------------------------------

## 8. Reference and agreement

### 8.1 `06_reference_cpt.py`

Source: `patient_procedures` — `procedure_code`, `procedure_code_format`. Reached by the same explode-and-drop bridge as §7, so a code billed under any hospitalization in the block counts for the encounter. **`billing_provider_id` is not read, and `procedure_billed_dttm` is read only to confirm the row belongs to the encounter — never as an event time.**

| Reference | Format | Code |
|---|---|---|
| `CPT` | CPT | `31500` — emergency endotracheal intubation |

Output: `reference_cpt.parquet` — one row per candidate episode, keyed on `intubation_episode_id` and carrying `cohort_run_id`, with a `cpt_present` boolean. A code billed anywhere in the block marks every episode of that block, which is a known limitation: CPT carries no usable timing (D1), so it cannot distinguish a block's first intubation from its reintubation. Tier C reports it at block level for that reason.

Also reports the **code capture rate**: the fraction of the cohort carrying the code. Every metric in Tier C must be read against this number first — where capture is low, the reference is uninformative at that site and is reported as such rather than scored.

> **CPT 31500 is a narrow reference and its ceiling should be stated up front.** It codes *emergency* endotracheal intubation, so elective and operative airway management is not captured, and billing completeness varies by site, payer and era. Sensitivity computed against it is bounded by that capture, not by the method under test — which is precisely why it is a *partial* gold truth and not a peer in the agreement matrix (D1).

### 8.2 `07_agreement.py`

> **All numbers in the tables below are illustrative shape, not results.** They exist to fix the output format so the notebook can be written and reviewed before any data is run. Real values come from executing the pipeline, and they are not close to these — the illustrative tables were sized against an index set of ~1 200 and a `SED` detection rate of 0.87; the first real run gave N\*\* = 6 319 and 0.42, and the D34–D38 rewrite moved N\*\* again to 13 500 episodes over 12 503 blocks. Read the tables below for their *columns*, and `output/final_no_phi/` for their *values*.
>
> **Two things below are exceptions and are measurements, not shape.** E.7's three-span evidence table and the `PARA` × `PAIR` decomposition in Tier A (`only_b` 62 = 32 + 30) are read off the current run's published artifacts, because in both cases the *number itself* is the point — one is the evidence a threshold is not fitted to (D43.2), the other is a cross-notebook integrity check that means nothing if it cannot be quoted. Both are marked **measured** where they appear.

#### Step 0 — the joined analytic table

The notebook validates the schema of each `method_*_episode.parquet` against §6.4, asserts every input carries the same `cohort_run_id` (§6.1), then joins all three plus `reference_cpt.parquet` on `intubation_episode_id`. Every candidate episode appears exactly once. This wide table is the input to **Tier A** and **Tier C**.

```         
episode_id | index_class           | SED PARA | sed_bef para_bef | cpt
-----------+-----------------------+----------+------------------+-----
 1001_E1   | qualified             |  1    1  |   -4.0     -2.0  |  1
 1001_E2   | qualified             |  1    0  |   -6.0      NaN  |  1
 1002_E1   | qualified             |  1    1  |   -9.0     -6.0  |  1
 1003_E1   | qualified             |  1    0  |  -12.0      NaN  |  0
 1004_E1   | qualified             |  0    0  |    NaN      NaN  |  0
 1005_E1   | not_sustained         |  1    0  |   -3.0      NaN  |  0
 1006_E1   | no_induction_med      |  0    0  |    NaN      NaN  |  0
-----------+-----------------------+----------+------------------+-----
 one row per candidate episode; block 1001 contributes two
 *_bef = nearest_before_min (rank 1), signed minutes
 NaN where that direction had no ranked entry
```

**Every table in Tiers A, B, C and E is computed on `index_class = 'qualified'` only** — the `N**` set from §5.11. This is the single subsetting step in the whole pipeline and it happens here, in one visible filter, so a reader of `07` can see exactly which denominator every rate below uses. The rejected rows are used once, in Tier D, and nowhere else.

**Rates are reported per episode, with the block and patient counts alongside.** Under D35 a block may contribute several rows, so an episode rate and an encounter rate are different quantities and every table names which it is. Where a statistic would be distorted by a block contributing repeatedly — κ in particular, which assumes independent units — the table carries the block count so the dependence is visible.

**Tier B reads the `method_*_ranked.json` files instead**, because the episode table carries only rank 1. The full rank ladder — and the per-medication breakdown it enables — lives only in the JSON.

#### Tier A — do the methods find the same episodes?

> **Read Tier A as conditional, not marginal (D38).** An episode qualifies only if one of the eight method medication categories was charted `given` in the window, and `SED` and `PARA` read those same eight categories over that same window in that same table. So `SED ∨ PARA` is true for every episode in the denominator **by construction**, and Tier A's question is narrower than its heading: not *do the methods find the same intubations*, but **given that an induction agent was charted, do the methods catalog it the same way**.
>
> Two consequences, both reported rather than hidden. The `SED−/PARA−` cell of A.2 and the concordance-0 row of A.3 are near-empty by definition; they are **labelled as the D25 on-t₀ population**, which is what actually lands there — an administration falling exactly on t₀ belongs to neither half-open direction, so the episode passes the filter and still scores `detected = false`. And κ and Jaccard for the `SED`×`PARA` pair must be quoted with the conditioning stated, because a restricted margin inflates neither statistic honestly. `PAIR` is exempt from this: it is free-running (D27), so it can fire on an episode the window filter rejected and its cells are not constrained.

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
- **`PARA` × `PAIR` should be the tightest of the three**, and if it is not, something is wrong. A `PAIR` detection requires a paralytic by definition, so on the `in_window` basis `PAIR` ✓ ∧ `PARA` ✗ ought to be near-empty; a non-trivial count there means the two notebooks disagree about the paralytic list or about window membership, which is a bug rather than a finding. This cell is the closest thing the design has to a cross-notebook integrity check, and D8's deliberate duplication is what makes it meaningful. **The agent-event collapse (D43) was expected to break it and did not** — the decomposition is still exact, `only_b` 62 = 32 + 30 with nothing unexplained (**measured**, current run, not illustrative) — because an event is anchored on its earliest administration, which is the same row `04` sees; §7.3 gives the argument.

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

The clinical read: both ranked methods should cluster tightly just *before* t₀ — induction agents and paralytics are given to accomplish the intubation. A method whose bulk falls on the wrong side of t₀ is detecting something other than the intubation.

> **The prediction that the post-t₀ half would be sparse was wrong for `SED`, and B.5 is what corrects it.** An earlier form of this passage expected `after` arrays to be thin and read a large post-t₀ mass as evidence that t₀ was landing late. At MIMIC `SED` has **17,207 after-entries against 3,088 before** — the forward half carries more than five times the traffic. B.5 decomposes it and the explanation is not a t₀ error: **57.5% of those after-entries are given during a running same-drug infusion** and a further 19.8% precede one within an hour (D40, D41). That is maintenance sedation being titrated in a patient who is by then unambiguously ventilated. The window stays symmetric — an asymmetric window would bias the comparison and would need its own justification — but the forward half should be read as *mostly maintenance*, not as a second induction peak.
>
> `PARA` behaves as the original passage predicted: 588 qualified entries, and `during_infusion` on 18 of them. The contrast between the two methods is itself the result — the specific method stays clean on the forward half while the sensitive one does not.

**B.5 Offset distribution, decomposed (D40, D41).** The same axis as B.4, one panel per ranked method, with each method's entries stacked into three mutually exclusive bands — `during_infusion` first, then `infusion_prep`, then the residual induction band. Published as `timing_offset_decomposed.png`, a **new figure alongside** `timing_offset_distribution.png` rather than a replacement for it, so B.4 stays comparable against runs that predate D40.

Precedence matters and is fixed: an administration that is both is counted `during_infusion`, because "a drip was already running" is the stronger and less inferential statement. Reading the figure, the induction band is the one to follow across t₀ — it should peak in the last half-hour before zero and fall away immediately after, and at MIMIC it does.

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

#### Tier D — specificity

Same methods, same ±3 h window, same code — only the stratum changes.

> **This tier was weakened by D37 and the design says so rather than quietly reporting a lesser thing under the old name.** Tier D was built on `arrived_intubated`: those patients were intubated before they arrived, so any `SED` firing around their first charted IMV row was a false positive **by construction**, with no reference, no adjudication and no coding assumption required. It was the one stratum in the study where the truth was known without a gold standard.
>
> D37 admits that group to the primary analysis, on the argument that an empty pre-period usually means nobody charted room air rather than that ventilation predates the record — and with the block stitched across the ED and the inpatient stay (D15), an ED induction is genuinely in the extract. That argument is sound and the group is genuinely worth analysing, but it costs the study its known-answer stratum. What follows is the best available replacement, and it is weaker. **No table in this tier is a false-positive count by construction; each is a contrast that a plausible confounder could also explain**, and each names its confounder.

**D.1 Detection rate by `no_lookback`.** The closest surviving analogue to the old probe, over `index_class = 'qualified'`.

| `no_lookback` | n | `SED` | `PARA` | `PAIR` (`in_window`) | `PAIR` (`free_running`) |
|---|---|---|---|---|---|
| `false` — a pre-period exists | | | | | |
| `true` — t₀ is the block's first respiratory row | | | | | |

An episode with no pre-period has a t₀ that marks where *charting* began, which may or may not be where *ventilation* began. Where the two differ, a method firing in the window is detecting something other than this induction. The contrast therefore still bounds specificity — but only loosely, because these patients are disproportionately transfers, and transfers differ in acuity, sedation practice and length of stay. **Confounder: case mix, not just observability.**

**D.2 Detection rate by `ep_num`.** First intubation versus reintubation, over `index_class = 'qualified'`.

| `ep_num` | n | `SED` | `PARA` | `PAIR` (`in_window`) | `PAIR` (`free_running`) |
|---|---|---|---|---|---|
| 1 | | | | | |
| > 1 | 1,940 | | | | |

New under D35 and worth its own row: a reintubation happens on a patient already deep in an ICU stay, so the ambient rate of sedative charting around it is far higher than around an admission intubation. If `SED` holds its rate across the two while `PARA` drops, that is the D10 warning appearing in a place the old design could not look. **Confounder: illness trajectory.**

**D.3 The `not_sustained` stratum.** The residual probe, n = 2,218.

| `index_class` | n | `SED` | `PARA` | `PAIR` (`in_window`) | `PAIR` (`free_running`) |
|---|---|---|---|---|---|
| `qualified` | 13,500 | | | | |
| `not_sustained` | 2,218 | | | | |

An IMV row followed within three hours by a different device is a charting blip or a very brief ventilation. Neither should carry an induction. This is the nearest thing left to a known answer, and its weakness is size and heterogeneity rather than logic. **Confounder: a `not_sustained` episode adjacent to a real intubation elsewhere in the block can borrow its medications.**

**D.4 `PAIR` on the `no_induction_med` stratum.** n = 26,770, and the one place a rejected stratum still carries information.

| method | rate on `no_induction_med` | interpretable? |
|---|---|---|
| `SED` | 0 | no — 0 by construction (D38) |
| `PARA` | 0 | no — 0 by construction (D38) |
| `PAIR` (`in_window`) | 0 | no — 0 by construction (D38) |
| `PAIR` (`free_running`) | | **yes** |

`SED`, `PARA` and `PAIR`'s windowed reading are all identically zero here, because D38 rejected these episodes for containing none of the drugs those three look for in that window. Reporting them would be reporting the filter.

**`PAIR` on the free-running basis is not constrained**, because its scan covers the whole block (D27). Its rate on this stratum is therefore a clean measurement of one specific thing: **how often free-running sedative–paralytic pairing fires on a sustained ventilation episode that had no induction charted around it.** That is ambient ICU activity — proning, dyssynchrony, a procedure elsewhere in the stay — and it is the price of D27 stated as a number on the largest stratum in the study. It is the single most useful cell in this tier.

**The specificity summary table.** Reported explicitly, with the caveat carried into the table rather than left in prose:

| method | basis | contrast | qualified | comparator | gap | known answer? |
|---|---|---|---|---|---|---|
| `SED` | — | D.3 `not_sustained` | | | | no |
| `PARA` | — | D.3 `not_sustained` | | | | no |
| `PAIR` | `in_window` | D.3 `not_sustained` | | | | no |
| `PAIR` | `free_running` | D.4 `no_induction_med` | | | | no |

A method whose gap approaches zero is not detecting intubation — it is detecting being in an ICU. That reading survives D37 intact; what does not survive is the claim that the comparator is false-positive by construction.
#### Tier E — pair structure and independent timing

Computed from `method_PAIR_pairs.parquet`, filtered to `index_class = 'qualified'` like Tiers A–C. This is the tier that uses `PAIR`'s distinguishing property: it carries its own intubation timestamp, so it can be scored against t₀ rather than merely near it.

**E.1 Pairs per episode.** How much sedative–paralytic activity is assigned to each intubation (D39). Reported with a pairs-per-*block* column alongside, since the scan's natural unit is the block.

| n pairs in encounter | n encounters | \% |
|---|---|---|
| 0 | 300 | 25.0 |
| 1 | 671 | 55.8 |
| 2 | 158 | 13.1 |
| 3+ | 73 | 6.1 |

`pair_count_distribution.csv` carries three further columns beside these — `median_n_sed_admin`, `median_n_para_admin` and `pct_index_pair_folded` — so the amount of merging the collapse did is a *published* quantity rather than a notebook print (D43). A site whose index pairs are almost never folded and one whose index pairs are almost always folded are charting differently, and E.3's combined labels are only readable against that rate.

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

**E.7 The evidence the collapse window is not fitted to.** `collapse_gap_minutes` is a clinical definition (D43.2), so the distribution it was *not* derived from is published rather than left in a scratchpad. For each Δ from 0 to 45 minutes, the number of consecutive same-`drug_class` administrations that far apart in the peri-intubation context, split by whether the two rows name the **same agent** (a redose) or **different agents** (a co-administration) — the two phenomena the fold merges, which are not the same thing. Columns: `delta_min`, `same_agent`, `n`, plus `max_delta_min` and `n_beyond_max_delta` as whole-table margins.

Measured on the current run, not illustrative:

| span | different agent | same agent | ratio |
|---|---|---|---|
| Δ = 0 | 4,615 | 301 | 15.3× |
| Δ = 1 | 883 | 223 | 4.0× |
| Δ = 2 … 45 | 6,127 | 6,952 | 0.88× |

Co-administration is a Δ ≤ 1 min phenomenon and stops being one immediately: past Δ = 1 the two series run at the same rate, which is routine dosing and carries no co-administration signal at all. **There is no valley at 15 minutes, and the figure says so in its caption.** What the window past Δ = 1 buys is paralytic redosing, which is what the multi-pair episodes are actually made of. Computed in `05` — the only notebook holding the administrations — and emitted as counts only, with no identifier reaching the table; `07` applies the n ≥ 10 rule and plots it. `n_beyond_max_delta` is a margin rather than a cell, so it is withheld in the 1–9 range rather than handed to the row-level suppressor, which would drop the whole table on account of one number.

#### Tier F — how much of the medication signal is maintenance sedation?

The D40/D42 sub-analysis. It runs on the same analytic set as Tiers A–C (`index_class = 'qualified'`, N = 13,500) and reports `detected_induction_only` beside `detected`. **Tier F is the only place `detected_induction_only` appears** — Tiers A–E are unchanged and continue to read `detected` (D42), so every number in them stays comparable across the change.

**F.1 Paired comparison at the configured threshold.** One row per ranked method.

| method | n | detected | rate | detected, induction only | rate | gap | episodes flipped |
|---|---|---|---|---|---|---|---|
| `SED` | 13 500 | 13 189 | 0.9770 | 12 352 | 0.9150 | 0.0620 | 837 |
| `PARA` | 13 500 | 584 | 0.0433 | 553 | 0.0410 | 0.0023 | 31 |

`n` is identical across the two columns by construction — D42 holds the denominator fixed — so the gap is a pure reclassification effect and not a cohort effect. `episodes flipped` is the count losing their last piece of evidence, which is far smaller than the count of reclassified administrations because most episodes also hold pre-t₀ evidence that D40 exempts.

**F.2 Threshold sweep.** The rule recomputed over `5, 10, 15, 30, 45, 60, 90, 120, 150, 180` minutes. Published as `infusion_prep_sweep.csv` and plotted as `infusion_prep_sweep.png` — rate against threshold, one line per method, with the configured value marked.

The sweep exists because **`infusion_prep_minutes` cannot be defended from first principles at a single value.** A loading bolus precedes its drip by minutes, but charting granularity, order-entry lag and infusion-pump documentation all widen the observed lag, and the widening is site-specific. The curve lets a site read where its own rate stops moving. A flat curve past some point means the rule has stopped finding prep and started finding coincidence.

**F.3 Sweep by medication.** The same grid broken out by `med_category`, published as `infusion_prep_by_drug.csv`. Expected to separate sharply and that separation is the point: **fentanyl infusions are analgesia and propofol infusions are sedation**, so the two drugs have no reason to share a bolus-to-drip lag, and pooling them would report an average of two different clinical behaviours. `PARA`'s per-drug cells will mostly suppress under the n ≥ 10 rule at this site — vecuronium has 92 continuous orders site-wide — and are published as suppressed rather than dropped, so the breakdown's shape is visible even where its values are not.

**F.4 Prep rate by charting-delay stratum.** Published as `prep_by_charting_delay.csv`, stratified on `charting_delay_min` from `02` (D34): `0`, `1–30`, `31–60`, `61–180`, `>180`, `not_charted`.

> **This table exists to expose a confound in D40, not to confirm it.** The only thing separating "induction bolus, then maintenance drip" from "maintenance loading dose, then drip" is which side of t₀ the bolus falls on — and under D34 t₀ is the waterfalled IMV row, which arrives *late* under exactly the high-stress conditions that produce an intubation. The delay is 0 for 77.3% of episodes but p95 is 55 minutes, and D40's reclassifications concentrate in the +10 to +40 minute bins. Those two facts overlap.
>
> So some administrations D40 calls prep are induction boluses that were charted before a delayed vent row. If the prep rate rises with `charting_delay_min`, that is the mechanism showing itself and the rule is partly deleting the signal it was built to protect. If the rate is flat across strata, the two are independent and D40 is measuring what it claims. **The table is reported whichever way it comes out**, and a rising rate is a limitation on the sub-analysis rather than a reason to withhold it — the primary rates in Tiers A–E do not depend on D40 at all (D42), which is what makes it safe to publish an unflattering answer here.

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
| `timing_offset_decomposed.png` | B.5 |
| `reference_capture_rate.csv` | C.1 |
| `reference_scoring.csv` | C.2 |
| `specificity_by_lookback.csv` | D.1 |
| `specificity_by_ep_num.csv` | D.2 |
| `specificity_not_sustained.csv` | D.3 |
| `specificity_pair_free_running.csv` | D.4 |
| `specificity_gap.csv` | D summary table |
| `pair_count_distribution.csv` | E.1 |
| `pair_gap_distribution.csv` | E.2 |
| `pair_agent_combinations.csv` | E.3 |
| `pair_index_offsets.csv` | E.4 |
| `pair_t0_concordance.csv` | E.5 |
| `pair_offset_distribution.png` | E.6 |
| `pair_collapse_deltas.csv` | E.7 — gap between consecutive same-class administrations in the peri-intubation window, per Δ minute 0–45, split same-agent (redose) vs different-agent (co-administration). Computed by `05`, which is the only notebook that holds the administrations, and emitted as counts only |
| `pair_collapse_deltas.png` | E.7, the two series on a log y-axis with the chosen collapse window shaded — the published evidence that D43.2's 15 minutes is a clinical definition and not a fitted valley |
| `pair_agent_combinations.png` | E.3, sedative × paralytic heatmap, counts annotated |
| `consort_flow.png` | CONSORT A and B as one two-panel figure, drawn from the two CSVs |
| `index_class_strata.png` | §5.10 taxonomy — the denominator map, `qualified` highlighted |
| `agreement_overview.png` | A.1, A.2 and A.3 in one frame |
| `timing_by_medication.png` | B.3, median offset per agent, split before / after |
| `specificity_gap.png` | D summary, all three methods across every stratum, gaps in the title; the `known answer?` column is reproduced in the caption |
| `episode_funnel.png` | §5.11 CONSORT B as a funnel, episodes / blocks / patients on each step |
| `charting_delay.png` | §5.10 `charting_delay_min`, drawn from `charting_delay.csv`, log x-axis, p99 marked |
| `induction_only_comparison.csv` | F.1 |
| `infusion_prep_sweep.csv` | F.2 |
| `infusion_prep_by_drug.csv` | F.3 |
| `prep_by_charting_delay.csv` | F.4 |
| `infusion_prep_sweep.png` | F.2, rate against threshold, configured value marked |

All go to `output/final_no_phi/` and are subject to the n ≥ 10 minimum cell size in §9 — any row of any table with a cell below 10 is suppressed rather than published. Figures inherit that suppression by construction (D26): each is drawn from the published table rather than recomputed.

**Suppression is row-level and applies to the 1–9 range only.** A cell of exactly zero is published: it identifies nobody, and withholding it would turn "this never happened" into "this is missing" — a different and worse statement in a multi-site study, where a missing cell reads as a site that failed to run the notebook. Rows in the disclosive range are removed entirely rather than blanked, because a blanked cell in a table whose margins are published is often recoverable by subtraction. Every suppression is printed with the row that triggered it, so a shrunken table is never mistaken for a clean one.

**B.4 is normalised per method, not plotted as raw counts.** `SED` and `PARA` differ by more than an order of magnitude in entry volume at any real site; on a shared count axis the smaller method is a flat line against the axis, which reads as "no timing signal" when what it has is a smaller denominator. Shape is what B.4 asks about, and the counts behind it are published in B.1 and B.2.

> **The n ≥ 10 rule bites hardest on B.3.** Per-medication breakdowns split the cohort finely — the illustrative `vecuronium` row above shows n = 27, and a rarer agent or a smaller site will fall below 10. Suppression here is row-level: the medication is dropped from the published table rather than pooled into an "other" category, since pooling across agents with different units and dose scales would produce a meaningless median.

------------------------------------------------------------------------

## 9. Outputs and data security

Follows the existing rules in [`output/README.md`](../../../output/README.md) and [`guides/primer.md`](../../../guides/primer.md).

| Directory | Contents |
|------------------------------------|------------------------------------|
| `output/intermediate_phi/` | `cohort.parquet`, `cohort_resp_waterfall.parquet`, `cohort_resp_imv_raw.parquet`, `cohort_index.parquet`, `cohort_qc.csv`, `index_imv.parquet`, `method_{SED,PARA}_ranked.json`, `method_{SED,PARA,PAIR}_episode.parquet`, `method_PAIR_pairs.parquet`, `pair_collapse_deltas.parquet`, `reference_cpt.parquet` |
| `output/final_no_phi/` | both CONSORT count sets, `index_class_rates.csv`, `charting_delay.csv`, agreement matrices, offset distribution summaries, reference-scored metrics, specificity tables, plots |

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
  "episode_gap_hours": 3,
  "pair_gap_hours": 3,
  "infusion_prep_minutes": 60,
  "collapse_gap_minutes": 15,
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
| `window_hours` | `02` | half-width of the t₀ detection window (D4). Written into `index_imv.parquet` as `window_start` / `window_end` and consumed by `03` and `04` as data, never recomputed (D9). Changes a *detection* result for `SED` and `PARA`, and applies identically to both (§6.2). For `PAIR` it does not affect detection at all — only the descriptive `in_window` flag (§6.5). **It is also a cohort parameter now**: D38's eligibility filter runs over the same window, so moving it changes who is in the denominator as well as who is detected |
| `episode_gap_hours` | `02` | the device-continuity interval (D36). One interval serves both the pre-period test and the sustained test. Changes **how many episodes exist** and where each begins, so it moves every count in the study — widening it merges reintubations into their index episode, narrowing it splits a single ventilation across a charting gap. Separate from `window_hours` for the reason D29 gives about `pair_gap_hours`: two parameters that happen to share a default are not one parameter |
| `infusion_prep_minutes` | `03`, `04` | how long after an intermittent administration a same-drug infusion `start` may fall for that administration to be maintenance prep (D40). **The only detection parameter measured in minutes, deliberately** — the others are ward-scale intervals in hours, and this one is procedural: a loading bolus precedes its drip by minutes, and naming it in hours would invite a value an order of magnitude too large. Moves `detected_induction_only` only; `detected`, the cohort and every Tier A/B/C/D table are unaffected (D42). Read directly from config by `03` and `04` for the reason D9 gives about `pair_gap_hours` — `01` has no administration set in hand and nothing to precompute — and echoed by both |
| `pair_gap_hours` | `05` | maximum gap between the two members of a `PAIR` (D29). Read directly by `05` rather than written into an upstream artifact, because unlike `window_hours` there are no bounds to precompute — the scan needs the scalar. The only detection parameter not resolved upstream |
| `collapse_gap_minutes` | `05` | the agent-event fold (D43.2). Administrations of the same `drug_class` within this many minutes of the event's first row are one clinical event before the scan sees them (§7.3). It is a **detection** parameter in the same sense `pair_gap_hours` is — it changes what a pair is, not how a pair is counted — and it is equally not post-hoc filterable: widening it merges events that a narrower setting left available to pair with something else. Read directly by `05` for the same reason `pair_gap_hours` is, and echoed there. **The value is a clinical definition, not a fitted one**, and E.7 publishes the distribution it is not fitted to |
| `stitch_hours` | `01` | `time_interval` passed to `stitch_encounters` (D15). Changes the analytic unit itself, so every count in the study moves with it |
| `trach_window_hours` | `01` | the exclusion clock in §5.5 (D18) |
| `min_age` | `01` | the adult criterion, tested on `age_at_admission` |

The last three are **cohort** parameters, not detection parameters: they change who is in the denominator rather than who is detected. `episode_gap_hours` and — under D38 — `window_hours` are now both, which is stated here because a reader looking for "the parameters that change the denominator" would otherwise stop at the last three. `01` echoes its three at the top of the notebook and writes them into `cohort_qc.csv`, `02` echoes its two, and `05` echoes `pair_gap_hours` and `collapse_gap_minutes` and writes the former into `method_PAIR_pairs.parquet`'s accompanying schema assertion output, so a published result carries the definitions that produced it. Everything else is a path or a site label.

> **`pair_gap_hours` and `collapse_gap_minutes` are the two parameters D9 does not cover.** Every other detection parameter is resolved once upstream and consumed downstream as data, precisely so no notebook re-derives it. Neither of these can follow that pattern: `01` has no pair scan and no fold to run, and there are no bounds to precompute — both stages need the scalar itself. `05` therefore reads both from config directly and echoes both, which is the §4 "no silent defaults" requirement doing the work D9 does elsewhere.

------------------------------------------------------------------------

## 11. Out of scope

Recorded so these are visible omissions rather than oversights.

**Removed from an earlier draft of this spec:**

- **The continuous-infusion method `INF`** (whiteboard item 3) — propofol / dexmedetomidine / fentanyl infusion starts. Removed per D1a and still removed. **`medication_admin_continuous` is read as of D40**, by `03` and `04`, but only to disqualify intermittent administrations that have already been found — no detection originates in it, and dexmedetomidine is not read at all. `infusion_gap_hours` is still not a config key; the D40 parameter is `infusion_prep_minutes`, which bounds a bolus-to-drip lag rather than an infusion's own extent.
- **`during_infusion` as a disqualifier.** Measured, published, and declined per D41: it fires on 48.9% of pre-t₀ and 57.5% of post-t₀ ranked entries, so it cannot separate induction from maintenance. Retained as a descriptive band only.
- **The ICD reference** — ICD-10-PCS `0BH17EZ`, `0BH18EZ`, `5A1935Z`, `5A1945Z`, `5A1955Z` and ICD-9 `9604`, `9670`–`9672`. Removed per D1b. CPT 31500 is the sole reference.
- **`DEV` as a compared method**, with its own notebook and its rows in the agreement matrix. Not deleted — *relocated* per D19 to `02_index_imv.py`, where the device rule qualifies the index event instead of competing to detect it.
- **The M2 symmetric 2/2 row rule**, with its `B_strict` boundary policy and its `arrived_intubated` / `insufficient_lookback` / `prior_row_imv` / `imv_not_sustained` taxonomy. Replaced by D36 and D37 with a duration test. `arrived_intubated` survives as the non-excluding label `no_lookback` (§5.10); the other three are gone.
- **The raw-charted t₀ anchor** introduced by D23. Reversed by D34 after the study lead reinterpreted the 24.1% gap as charting latency rather than inference. D23 still governs cohort admission.
- **First-episode-only scope.** Widened by D35. Still out of scope: *outcome* classification for an episode (extubation, trach, death) and any linkage between episodes of a block beyond `ep_num`.
- **A `med_group`-based episode-eligibility filter**, which would have kept 17,395 episodes and preserved Tier A's `SED−/PARA−` cell. Measured and declined in favour of the eight method categories — see D38 for the trade and §8's Tier A note for what it costs.

**Out of scope from the start:**

- Extubation detection of any kind.
- Second and subsequent intubations; reintubation labelling; episode stitching.
- Outcome classification (success / failed / WLST) — catalog M3's tree.
- Tracheostomy handling — no cohort exclusion and no method adjustment.
- The M1 / M3 / M4 device transition rules.
- Pre-waterfall vs post-waterfall sensitivity analysis (settled by D5).
- M5 non-device signals (LPM onset, vent-observation cessation).
- Chart review (catalog Tier 2).