# Block Summary and CPT Comparator — Design

**Project:** VentTRACE **Date:** 2026-08-12 **Status:** Design, approved for planning

**Amends:** `2026-08-10-paralytic-index-design.md`. That document stands; this one reverses three of its out-of-scope bullets and adds decisions P26–P38. It is a separate file rather than an edit so the record shows what changed, when, and why — the same reason P18 and P21 carry their amendments in place instead of being silently rewritten.

Decision numbering continues from P25. Section numbering restarts.

------------------------------------------------------------------------

## 1. Purpose

The 2026-08-10 design answered what surrounds a paralytic. It described index events and said nothing about the patients they happened to, and it deliberately refused to compare itself against anything.

This amendment adds two deliverables, both requested by the study lead following senior-author review:

1. **A comparator.** For each encounter block with an index paralytic, was a CPT `31500` (endotracheal intubation) billed anywhere in that block — and does that agreement strengthen as the paralytic evidence strengthens?
2. **Table 1.** The cohort description a manuscript needs: demographics, comorbidity, physiology and life support before the index, and outcomes after it. Published twice — once per encounter block, once per index event.

Neither changes the index definition, the cohort, or anything `01`–`03` computes. Both are read-only consumers of what those notebooks already write.

### What this reverses

The 2026-08-10 §11 declared three things out of scope. All three are withdrawn here, each with its original reasoning left standing beside the reversal:

| withdrawn bullet | original reasoning | why it is reversed |
|---|---|---|
| "Agreement statistics. No kappa, no Jaccard, no 2×2 tables, no concordance counts. There is one method." | The old build's method comparison was complete; keeping the machinery would answer a question no longer asked. | The question being asked now is not *which method is right* but *does billing corroborate what we found*. The machinery is not revived: no tiered agreement, no reference gate, no episode qualifier. One 3×2 table. |
| "Reference standards. No CPT, no ICD." | CPT was one of five competing detectors under an anchor that has moved. | CPT returns as a **comparator, not a reference standard** (P26). It is never treated as truth and no statistic is published that would require it to be. |
| "Extubation, duration of ventilation, and outcomes. Not touched." | Scope control on a study about index definition. | Table 1 without outcomes is not a Table 1. Restricted to ICU/hospital mortality and length of stay; ventilator duration and extubation remain out of scope. |

------------------------------------------------------------------------

## 2. Decisions

| \# | Decision | Rationale |
|---|---|---|
| P26 | **CPT `31500` is a comparator, not a reference standard.** An absent code means "no IMV was performed, or it was not charted", and the two are indistinguishable in the data. No sensitivity, no specificity, no NPV, no kappa is published. | Set by the study lead. The denominator is blocks that already have an index paralytic (P27), so the false-negative cell — billed as intubated, no paralytic found — is excluded by construction and every statistic that needs it would be computed on a cell that cannot be observed. Publishing PPV-shaped quantities only is not a limitation being tolerated; it is the only honest reading of this denominator, and saying so on the page is what stops a reader treating CPT as truth. |
| P27 | **The denominator is the encounter blocks with at least one index paralytic — 1,547 of the cohort's 34,017.** | Set by the study lead. The question is "given that we called an index paralytic, did billing agree", and that question conditions on our own call. The consequence in P26 is accepted explicitly rather than discovered later. |
| P28 | **The block's representative event is its first index paralytic, `p_num = 1`.** Every block-level artifact in this amendment is keyed on it. | Set by the study lead. "By encounter block, not by index" needs a rule for the 343 blocks with more than one index event, and the first is the only choice that is well defined for every block, stable under P6's anchor-and-close fold, and the same event a clinician would call "the intubation of this admission". Later index events are not discarded — they are the whole content of the index-level Table 1 (P34). |
| P29 | **The comparison is at block level with no time alignment, and the limitation is published rather than argued away.** | Set by the study lead, after the block-day alternative was put and declined. A block flagged CPT-positive may have been billed for an intubation days from the index paralytic — the dominant case in this cohort is a patient already on IMV (1,135 of 1,547 blocks) receiving a paralytic for ongoing ICU care, in a block whose CPT code belongs to an intubation on admission day. P30 measures exactly this rather than assuming it away. |
| P30 | **`cpt_offset_distribution.csv` publishes the days between `t₀` and the nearest CPT `31500` date.** | The only instrument that recovers what P29 gives up. It costs no new table and no new join, and it converts "the block-level flag might not be time-aligned" from a caveat a reader must take on faith into a distribution they can read. `procedure_billed_dttm` is trusted to the day and not to the minute, which is why this is a day-binned distribution and not a minute offset. |
| P31 | **The cascade is a 3×2 of mutually exclusive evidence tiers, assigned from the block's first index event only.** Tier 1 index only · tier 2 index + IMV transition · tier 3 index + IMV transition + sedation. | Set by the study lead. A single 2×2 cannot be built on this denominator (every block is tier-1 positive by definition, so the table would be degenerate). The cascade asks a better question anyway: agreement is expected to rise monotonically as evidence tightens, and whether it does is the finding. Tiers come from the block's `p_num = 1` event so that a tier describes one clinical act, not evidence assembled from two intubations days apart. |
| P32 | **`medication_admin_continuous` is opened**, reversing the 2026-08-10 scope line "`medication_admin_continuous` is never opened. Every dose in this study is a discrete charted push." | Vasopressor exposure cannot be established from intermittent charting, and "was this patient already on pressors" is the covariate the senior author asked for by name. The reversal is bounded: continuous medications supply a **presence flag in a look-back window** and nothing else. No dose, no rate, no infusion-derived index event, no `during_infusion` band. The original decision's concern — that continuous data would create a second, competing definition of the index event — does not arise, because nothing here defines an event. |
| P33 | **Every pre-index exposure is a presence test over a look-back window ending at `t₀`, evaluated at 1 h, 6 h and 24 h.** One helper implements the interval, and all four sources call it. | Set by the study lead (6 h and 24 h), with 1 h added to satisfy the senior author's "at the time of intubation" — a 6-hour look-back is not that, and 1/6/24 h also aligns the table column-for-column with the RSI project's `any_vasopressor_1hr_prior` / `6hrs` / `24hrs`. Four sources × three windows is twelve interval tests; written independently they will disagree about a row landing exactly on the far edge, and a one-row disagreement between "on pressors" and "on CRRT" is invisible in aggregate. Same reasoning as P15, applied to a wider surface. The window is closed at both ends: `t₀ - Xh <= dttm <= t₀`. |
| P34 | **Table 1 is published twice: by encounter block (`p_num = 1`, n = 1,547) and by index paralytic event (n = 2,117).** Identical row inventory, different unit. | Set by the study lead. The block table is the manuscript's Table 1. The index table is what the study's own analytic unit requires and is the only place a block's later paralytics appear. Because the row inventories are identical, the two are directly comparable, and the difference between them measures what re-paralysis contributes. |
| P35 | **Every Table 1 row carries a `rule` column and a `unit` column.** | Set by the study lead. These CSVs are merged across consortium sites and pasted into manuscripts, arriving detached from the notebook that produced them; every other artifact in this pipeline depends on `pipeline_flow.md` being read alongside it. A rule column also defuses the trap P34 creates: block-level outcomes repeat down the index-level table, so `los_hospital_days` there must state "block-level value, repeated per index event in the block" or a reader will average it. |
| P36 | **Continuous variables publish mean, SD, median, Q1 and Q3 — all five.** Categoricals publish `n` and `pct`. | Set by the study lead. Mean beside median is how a reader detects skew without a figure, and LOS, CCI and the index-per-block count are all heavily right-skewed. The RSI reference table publishes median/IQR alone, which is the specific gap the senior-author review asked to close. Counts beside percentages, likewise: a percentage without its numerator cannot be pooled across sites. |
| P37 | **AMENDED 2026-08-12 by the study lead: two independent definitions, with no invariant coupling them.** `hospital_mortality` = `death_dttm` falling inside a member hospitalization's admission→discharge interval **OR** `discharge_category == 'expired'`. `icu_mortality` = `death_dttm` falling inside an ADT `icu` interval. Nothing else. **`icu_mortality_undeterminable` is withdrawn.** | **Supersedes the original decision, which made ICU mortality a subset of hospital mortality and published a third `undeterminable` count for deaths flagged by `discharge_category` alone.** The bound on `death_dttm` is retained and still not decoration: in CLIF the `patient` table's `death_dttm` can be registry-sourced and will fire for a patient discharged alive who died months later at home, which unbounded would be published as in-hospital mortality. What the amendment drops is the coupling. Implementation of the original wording asserted the subset and disjointness properties, and those assertions **fired on real data at MIMIC** — 9 of 34,017 blocks with `icu_mortality` true while `hospital_mortality` was false, and 373 with `icu_mortality` and `undeterminable` simultaneously true. Diagnosed: every violation is `death_dttm` landing **after** `discharge_dttm` by under 24 hours (median 20.1 h, max 23 h 58 m), with the ADT `icu` interval likewise extending past discharge and 35 of the 36 affected index-bearing blocks carrying `discharge_category == 'expired'`. No death preceded its admission. These are in-hospital deaths whose recorded death timestamp trails the recorded discharge timestamp — a MIMIC recording artifact, not patients who died at home. Two ways of closing the gap were put to the study lead and both declined in favour of simplicity: adding death-in-ICU as a third route into `hospital_mortality`, and a 24-hour grace window past discharge (a threshold fitted to one site's artifact, with zero headroom at the observed maximum). **Accepted consequence, recorded here so a reader meets it rather than discovers it: `icu_mortality` is not a subset of `hospital_mortality`, and at a site with this artifact the ICU count can exceed the hospital count in a small number of blocks. The two are independent measurements published side by side, and neither is derived from the other.** |
| P38 | **LOS is summed over the block's member hospitalizations, not measured as the block's span.** | Set by the study lead. A block stitches up to 4 hospitalizations (`max_hosp_per_block = 4` at MIMIC) separated by gaps of up to `stitch_hours`; the span would count that gap time, during which the patient was not in the hospital. ICU LOS is summed over the block's ADT `icu` intervals on the same principle. |

------------------------------------------------------------------------

## 3. Architecture

Three new notebooks, appended. `01`, `02` and `03` are not modified.

| notebook | opens | reads | writes |
|---|---|---|---|
| `04_covariates.py` | `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `position`, `hospital_diagnosis`, and re-opens `hospitalization` and `adt` (already-required tables, no contract change) | `index_context.parquet`, `cohort_index.parquet` | `intermediate_phi/index_covariates.parquet` (2,117 rows, PHI); `final_no_phi/covariate_coverage.csv` |
| `05_table_one.py` | — | `index_covariates.parquet` | `table1_by_agent_block.csv`, `table1_by_agent_index.csv`, `figures/T1_life_support_by_window.png`, `figures/T2_source_coverage.png` |
| `06_reference_cpt.py` | `patient_procedures` | `index_covariates.parquet` | `cpt_cascade.csv`, `cpt_cascade_qc.csv`, `cpt_offset_distribution.csv`, `figures/F1_cpt_cascade.png`, `figures/F2_cpt_offset.png` |

`04` is the **sole owner of the analytic row**. It reads `index_context.parquet` alone for the event spine — that frame already carries every `index_paralytic.parquet` column plus the D and E results, so joining both would be a redundant join on the same key. It derives the tier from `index_context.parquet`, joins every covariate, attaches block-level attributes, and writes one frame. `05` and `06` only aggregate that frame: neither re-derives a block, re-selects `p_num`, nor re-computes a tier. Both assert their input height against the frame's, so a divergence fails rather than producing two tables with different N.

`run_all.sh` becomes `STEPS=(01_cohort 02_index_paralytic 03_context 04_covariates 05_table_one 06_reference_cpt)`.

### 3.1 The analytic frame

`index_covariates.parquet` — one row per index paralytic event, 2,117 at MIMIC.

```
keys          encounter_block · p_num · index_paralytic_id · patient_id · t_dttm
from 02       agent_label · n_admins · is_coadmin · n_agents
from 03       imv_transition · no_transition_reason · prior_device_category
              any_sedative · sedative_agent_set
tier          evidence_tier in {1, 2, 3}   -- computed per row from its own D/E flags;
              the cascade (P31) reads it from the p_num = 1 row only
demographics  age_at_admission · sex_category · race_category · ethnicity_category
comorbidity   cci
physiology    lowest_sbp_{1,6,24}h · highest_hr_{1,6,24}h · lowest_spo2_{1,6,24}h · weight_kg
life support  vasopressor_{1,6,24}h · crrt_{1,6,24}h · prone_{1,6,24}h
location      location_at_index in {ed, icu, other}
block-level   n_index_in_block · los_hospital_days · los_icu_days
              hospital_mortality · icu_mortality
```

Block-level columns are constant within a block and repeat down its rows; P35's `unit` column is what keeps that legible downstream.

### 3.2 Attribute resolution

A block stitches up to 4 hospitalizations, so an attribute recorded per hospitalization is undefined until the spec says which one. Every such case is resolved to **the hospitalization containing `t₀`** — the one the index paralytic was actually charted under — rather than the block's first or last:

| attribute | resolved as |
|---|---|
| `age_at_admission` | from the hospitalization containing `t₀` |
| `cci` | computed on the hospitalization containing `t₀` |
| `location_at_index` | the ADT row where `in_dttm <= t₀ < out_dttm`, mapped to `ed` / `icu` / `other`; `unknown` when no ADT row covers `t₀` |
| `weight_kg` | the most recent `vitals` weight at or before `t₀`, no look-back limit; null when the patient has none |
| `race_category`, `ethnicity_category`, `sex_category`, `death_dttm` | from `patient`, which is patient-level and needs no resolution |

The alternative — the block's first hospitalization — was rejected because a block's ED presentation and its inpatient admission can carry different recorded ages and different diagnosis lists, and the index paralytic belongs to exactly one of them.

`combination` as a Table 1 stratum means any `agent_label` containing `+` — the co-administration labels `index_composition.csv` already separates from same-agent redose. A block whose first index event is a rocuronium redose has `agent_label == 'rocuronium'` and belongs to the `rocuronium` column, not `combination`.

The frame carries identifiers and `t_dttm`, so `utils/suppress.py` will refuse it — correctly. It is a PHI intermediate; only the aggregations cross into `final_no_phi/`.

------------------------------------------------------------------------

## 4. Implementation constraints

**Loading (P19, restated because this amendment adds seven tables).** Every new table is read through its clifpy table class via `from_file`, with load-time filters enumerating casing variants (P20), and the timezone is then removed with `to_site_naive` — `series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)`. A bare `.dt.tz_localize(None)` is forbidden: clifpy returns a correct instant tagged with an LMT-based tzinfo, so stripping without converting keeps a wall clock that was never right and shifts every row by about an hour. Timezone conversion is never done in polars, whose DST table stops extrapolating US rules around 2099 while MIMIC's dates are shifted into the 2100s. **Note for porting:** the `Induction_Variability_RSI` project, used here as the Table 1 reference, calls `.dt.tz_localize(None)` directly on clifpy output. Its covariate logic may be read for structure; its timezone handling may not be copied.

**Interval arithmetic.** All minute/hour arithmetic is done inside polars with `pl.col(c).dt.epoch("s")`. No `datetime.timestamp()`, no `astimezone`, no `fromtimestamp`.

**One window helper.** `in_lookback(t0_col, dttm_col, hours)` is defined once in `04` and used by all four exposure sources (P33). Closed at both ends.

**The `hospitalization_id` bridge.** `06` maps CPT rows to blocks through the explode-and-drop bridge of the 2026-08-10 §6.1 — the only sanctioned place `hospitalization_id` may be named. A block is CPT-positive if **any** member hospitalization carries the code.

**Vasopressor vocabulary.** `norepinephrine`, `vasopressin`, `epinephrine`, `phenylephrine`, `dopamine` — a module constant, not a config key, for the reason P11 gives about the gap bins: a site that changed the list would make its Table 1 non-comparable with every other site's.

**Optional tables degrade to null, never to false.** `patient` and `patient_procedures` are required; absent, the notebook fails loudly. `crrt_therapy`, `position`, `vitals` and `hospital_diagnosis` are optional: absent, their derived columns are **null** rather than `false`, and `covariate_coverage.csv` publishes 0%. A null cannot be misread as "this patient had no CRRT"; a `false` can, and would be indistinguishable from a clinical finding.

------------------------------------------------------------------------

## 5. Sub-analysis F — the CPT comparator

`06_reference_cpt.py`. CPT rows are `procedure_code == '31500'` with `procedure_code_format` matching the CPT casing variants, reduced to one boolean per block.

**`cpt_cascade.csv`** — the 3×2. Rows are the three tiers of P31, mutually exclusive, summing to 1,547.

```
evidence_tier · rule · n_blocks · n_cpt_yes · n_cpt_no · pct_coded
```

**`cpt_cascade_qc.csv`** — denominator quality: blocks with any `patient_procedures` row at all, and the distribution of CPT codes per block. A site with thin billing extracts is visible here rather than being reported as poor agreement in the table above.

**`cpt_offset_distribution.csv`** — P30. Days between `t₀` and the nearest CPT `31500` date, binned, with an explicit `no_cpt` row. Signed, so "billed before the paralytic" and "billed after" are separable.

**Expected shape at MIMIC, stated so a departure is noticeable.** 1,135 of 1,547 blocks have their first index paralytic given to a patient already on IMV, so tier 1 will dominate and tiers 2–3 will be thin (473 blocks have an IMV transition on *any* index event, so 473 is a ceiling for tier 2 + tier 3 combined, not their value — a block whose transition sits on a later paralytic is tier 1 here). This is the ever-IMV cohort filter of P2 showing through at block level, and it is the first table in the study that makes it visible per block. A cascade where tier 1 is small would mean something upstream changed.

**Observed at MIMIC, 2026-08-12 — the cascade is empty, and the reason is a site fact.**
The tier partition came out as predicted (1,084 / 121 / 342, summing to 1,547; tiers 2+3 =
463, just under the 473 ceiling implied by `imv_transition_summary.csv`). **`pct_coded` is
0.0 in all three tiers.** This is not a defect and was verified rather than assumed:

- MIMIC's `patient_procedures` holds 1,045,729 rows, of which 116,032 (11.1%) are
  CPT-format — so the format filter works and CPT data is present.
- Procedure code `31500` appears **15 times in the entire table**. MIMIC codes inpatient
  procedures via ICD-9 (469,209 rows) and ICD-10-PCS (390,446); CPT is professional
  billing, which this extract largely does not carry for ICU stays.
- Of those 15 hospitalizations, 9 fall inside the ever-IMV cohort and **none** falls in
  the 1,547 index-bearing blocks. `cpt_cascade_qc.csv` reports
  `pct_blocks_with_any_procedure_row = 0.06`.

Two consequences worth stating plainly. **First, P26 is what keeps this readable.** Under the
denominator of P27 the result is "uniformly not charted", and had this analysis published
sensitivity or kappa it would have reported 0% agreement — which a reader would take as the
paralytic index failing against truth, rather than as MIMIC not using this code. The decision
to publish `pct_coded` beside a coverage QC table, and no agreement statistic, is the only
reason the output says what actually happened. **Second, those 9 blocks are the
false-negative cell made concrete**: CPT-coded intubations among ever-IMV patients with no
index paralytic, every one of them excluded by construction from the denominator P27 sets.
The limitation P26 records in the abstract is observable here as a specific, countable set.

**For the multi-site protocol:** sub-analysis F cannot answer its question at a site whose
extract lacks professional billing. `cpt_cascade_qc.csv` is what tells a site that before
they read the cascade, and a site reporting `pct_blocks_with_any_procedure_row` near zero
should treat F as not run rather than as a null result.

------------------------------------------------------------------------

## 6. Table 1

`05_table_one.py`. Two files, identical row inventory, different unit (P34). Long format: one row per statistic, one column per stratum.

```
statistic · rule · unit · rocuronium · succinylcholine · vecuronium · combination · overall · site_name
```

Strata come from `agent_label` of the row's index event; `combination` collects the co-administration labels that `index_composition.csv` already separates from redose. **Every stratum column is emitted even when structurally empty** — succinylcholine is absent from MIMIC entirely, and a column present at one site and missing at another is what breaks a multi-site merge. This is the published-zero convention of P21, applied to columns.

Row inventory, with P36's five statistics for every continuous variable and `n` + `pct` for every categorical:

```
demographics   age_at_admission · sex_category · race_category · ethnicity_category · n_patients
comorbidity    cci
physiology     lowest_sbp · highest_hr · lowest_spo2   × {1h, 6h, 24h} · weight_kg
life support   vasopressor · crrt · prone              × {1h, 6h, 24h}
context at t0  imv_transition · already_on_imv · any_sedative · location_at_index
outcomes       hospital_mortality · icu_mortality
               los_hospital_days · los_icu_days · n_index_in_block
coverage       one pct per source table
```

`race_category` and `ethnicity_category` are published as **raw mCIDE categories with counts**, not collapsed into a derived race/ethnicity variable. The RSI project collapses to five buckets inside its analysis; collapsing at publication would make the site's own distribution unrecoverable, and the coordinating centre can collapse a count table but cannot un-collapse one.

------------------------------------------------------------------------

## 7. Figures

Four, all drawn from published CSVs and never from an in-memory frame, following the conventions already set in `02` and `03`: fixed categorical colours never cycled, published zeros drawn as baseline diamonds, no number on a plot that is not in the CSV beside it.

| figure | shows | why this form |
|---|---|---|
| `F1_cpt_cascade.png` | The 3×2 as a mosaic: row height ∝ tier n, split by CPT yes/no | Tiers are very unequal (tier 1 in the thousands against tiers 2–3 in the hundreds). Grouped bars would render the small tiers as hairlines; a mosaic encodes the size disparity and the coded fraction in one mark. |
| `F2_cpt_offset.png` | Signed days from `t₀` to the nearest CPT code | The evidence for P29's limitation. A mass at day 0 means the block flag is time-aligned; a long right tail means it is not. |
| `T1_life_support_by_window.png` | Vasopressor · CRRT · prone × 1 h / 6 h / 24 h, grouped by agent | The 1 h → 24 h ramp is where "already shocked" separates from "crashed at intubation", and that is a shape, not a number. |
| `T2_source_coverage.png` | One bar per new CLIF table | The figure a site reads first to know whether its Table 1 is trustworthy. Makes a structural zero look different from a clinical one at a glance. |

------------------------------------------------------------------------

## 8. Testing

| test | pins |
|---|---|
| `tests/test_lookback_window.py` | P33's interval, closed at both ends: a row exactly on `t₀ - 24h` is in, one a second earlier is out, one after `t₀` is out. Mirrors `test_pair_gaps.py`. |
| `tests/test_cpt_bridge.py` | A 4-hospitalization block with the CPT on its 3rd member flags positive; a code on a hospitalization outside the block does not leak in. |
| `tests/test_block_row_contract.py` | The `p_num = 1` subset height equals `index_per_block.csv`'s ≥1-index total; `05` and `06` agree on N; every block-level column is constant within its block. |
| `tests/test_mortality_bound.py` | P37 as amended: a `death_dttm` outside the stay does not count as in-hospital mortality; `discharge_category == 'expired'` alone does; `icu_mortality` is decided by the ADT `icu` interval alone and is deliberately not constrained by `hospital_mortality`. |
| extend `tests/test_clifpy_tz_boundary.py` | The existing no-naive-timestamp AST check is extended to `04`, `05` and `06`. |
| extend `tests/test_publish_guard.py` | `index_covariates.parquet`'s column set is rejected by `publish()` — the frame is PHI and must stay that way. |

------------------------------------------------------------------------

## 9. Out of scope

- **Any statistic requiring the false-negative cell.** Sensitivity, specificity, NPV and kappa are not published, for the reason P26 gives. A reader who wants them needs a denominator this study does not use.
- **Block-day or minute-level CPT alignment.** Declined by the study lead (P29). `cpt_offset_distribution.csv` is what stands in its place.
- **Infusion doses and rates.** `medication_admin_continuous` supplies presence flags only (P32).
- **Ventilator duration, extubation, reintubation linkage.** Outcomes are restricted to mortality and LOS.
- **SOFA and other composite scores.** CCI only.
- **Changes to `01`, `02`, `03`.** The three new notebooks are read-only consumers.
- **Multi-site pooling.** Every artifact carries `site_name`; combining them is the coordinating centre's job.

------------------------------------------------------------------------

## 10. Data contract change

Seven CLIF tables are added to the site requirement. The top-level `README.md` required-tables section and `docs/pipeline_flow.md` §2 are updated in the same commit as the implementation.

| table | required | used for |
|---|---|---|
| `patient` | yes | sex, race, ethnicity, `death_dttm` |
| `patient_procedures` | yes | CPT `31500` |
| `medication_admin_continuous` | optional | vasopressor presence |
| `crrt_therapy` | optional | CRRT presence |
| `position` | optional | prone presence |
| `vitals` | optional | worst SBP / HR / SpO₂, weight |
| `hospital_diagnosis` | optional | CCI via clifpy |

Optional means the pipeline runs without it, the derived columns are null, and coverage publishes 0% (§4).
