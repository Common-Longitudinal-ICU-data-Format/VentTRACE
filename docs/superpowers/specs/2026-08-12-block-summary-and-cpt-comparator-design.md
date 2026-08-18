# Block Summary and CPT Comparator — Design

**Project:** VentTRACE **Date:** 2026-08-12 **Status:** Design, approved for planning

**Amends:** `2026-08-10-paralytic-index-design.md`. That document stands; this one reverses three of its out-of-scope bullets and adds decisions P26–P38. It is a separate file rather than an edit so the record shows what changed, when, and why — the same reason P18 and P21 carry their amendments in place instead of being silently rewritten.

Decision numbering continues from P25. Section numbering restarts.

------------------------------------------------------------------------

## 1. Purpose

The 2026-08-10 design answered what surrounds a paralytic. It described index events and said nothing about the patients they happened to, and it deliberately refused to compare itself against anything.

This amendment adds two deliverables, both requested by the study lead following senior-author review:

1. **A comparator.** For each encounter block with an index paralytic, was a CPT `31500` (endotracheal intubation) billed anywhere in that block — and does that agreement strengthen as the paralytic evidence strengthens?
2. **Table 1.** The cohort description a manuscript needs for valid indexes carrying paralytic, IMV-transition, and sedation evidence: demographics, comorbidity, physiology and life support before the index, and outcomes after it. Published twice — once per block with a valid index, once per valid index event.

Neither changes the index definition, the cohort, or anything `01`–`03` computes. Both are read-only consumers of what those notebooks already write.

### What this reverses

The 2026-08-10 §11 declared three things out of scope. All three are withdrawn here, each with its original reasoning left standing beside the reversal:

| withdrawn bullet | original reasoning | why it is reversed |
|---|---|---|
| "Agreement statistics. No kappa, no Jaccard, no 2×2 tables, no concordance counts. There is one method." | The old build's method comparison was complete; keeping the machinery would answer a question no longer asked. | The question being asked now is not *which method is right* but *does billing corroborate what we found*. The machinery is not revived: no reference gate or episode qualifier. One four-category × CPT table. |
| "Reference standards. No CPT, no ICD." | CPT was one of five competing detectors under an anchor that has moved. | CPT returns as a **comparator, not a reference standard** (P26). It is never treated as truth and no statistic is published that would require it to be. |
| "Extubation, duration of ventilation, and outcomes. Not touched." | Scope control on a study about index definition. | Table 1 without outcomes is not a Table 1. Restricted to ICU/hospital mortality and length of stay; ventilator duration and extubation remain out of scope. |

------------------------------------------------------------------------

## 2. Decisions

| \# | Decision | Rationale |
|---|---|---|
| P26 | **CPT `31500` is a comparator, not a reference standard.** An absent code means "no IMV was performed, or it was not charted", and the two are indistinguishable in the data. No sensitivity, no specificity, no NPV, no kappa is published. | Set by the study lead. The denominator is blocks that already have an index paralytic (P27), so the false-negative cell — billed as intubated, no paralytic found — is excluded by construction and every statistic that needs it would be computed on a cell that cannot be observed. Publishing PPV-shaped quantities only is not a limitation being tolerated; it is the only honest reading of this denominator, and saying so on the page is what stops a reader treating CPT as truth. |
| P27 | **The denominator is the encounter blocks with at least one index paralytic — 1,547 of the cohort's 34,017.** | Set by the study lead. The question is "given that we called an index paralytic, did billing agree", and that question conditions on our own call. The consequence in P26 is accepted explicitly rather than discovered later. |
| P28 | **AMENDED 2026-08-18: CPT and the general block-level artifacts retain the first index paralytic, `p_num = 1`; Table 1 is the explicit exception and uses the first valid index in each block.** A valid index has both a configured-window IMV transition and configured-window sedation. | Set by the study lead. CPT continues to describe all blocks with a paralytic index and must not inherit Table 1's narrower denominator. Table 1 instead describes the paralytic + IMV + sedation cohort, so a block whose first index is invalid but whose later index is valid is represented by that first valid event rather than excluded. |
| P29 | **The comparison is at block level with no time alignment, and the limitation is published rather than argued away.** | Set by the study lead, after the block-day alternative was put and declined. A block flagged CPT-positive may have been billed for an intubation days from the index paralytic — the dominant case in this cohort is a patient already on IMV (1,135 of 1,547 blocks) receiving a paralytic for ongoing ICU care, in a block whose CPT code belongs to an intubation on admission day. The limitation is stated on the notebook, in `code/README.md` and on figure F.1 rather than measured: P30 attempted to measure it and was withdrawn (see below). |
| ~~P30~~ | ~~**`cpt_offset_distribution.csv` publishes the days between `t₀` and the nearest CPT `31500` date.**~~ **WITHDRAWN 2026-08-14 by the study lead.** The comparison is presence: all the CPT codes for all the hospitalizations in an encounter block are pooled, and one `31500` anywhere in that pool means that block has the intubation. | The study lead's ruling: *"its just all the cpt for all the hospitions in thats eocunter blovck and if its there is 1 then thats encounter block has the intubation its thats simple."* The offset distribution answered a question nobody asked, and it did so with a date this study does not otherwise trust — `procedure_billed_dttm` is a **billing** timestamp, and a reduction over it invites reading a billing artifact as a clinical time. `cpt_offset_distribution.csv`, `F2_cpt_offset.png` and `nearest_offset_days` are removed; `procedure_billed_dttm` is still read (the CLIF 2.1 schema marks it required) and dropped immediately, and `tests/test_cpt_bridge.py::test_the_flag_carries_no_date_column` pins the removal so a date cannot creep back onto the block flag unnoticed. |
| P31 | **AMENDED 2026-08-18: the cascade is the mutually exclusive 2×2 partition of configured-window IMV transition × sedation, assigned from the block's first index event only.** IMV uses ±60 minutes and sedation uses ±5 minutes. Category 1 paralytic only (neither signal) · category 2 paralytic + IMV transition without sedation · category 3 paralytic + IMV transition + sedation · category 4 paralytic + sedation without IMV transition. The persisted field remains `evidence_tier` for the consortium artifact contract, but the values are categories, not an ordinal score. | Set by the study lead. The former three-row implementation placed every no-IMV event in category 1, including sedation-only events, so its “index only” label was incorrect. The four combinations now partition the two contextual signals exactly. Categories come from the block's `p_num = 1` event so that each row describes one clinical act, not evidence assembled from two intubations days apart. CPT remains a comparator and each `pct_coded` has its own category denominator; those percentages are not components of a total and must not be summed. |
| P32 | **`medication_admin_continuous` is opened**, reversing the 2026-08-10 scope line "`medication_admin_continuous` is never opened. Every dose in this study is a discrete charted push." | Vasopressor exposure cannot be established from intermittent charting, and "was this patient already on pressors" is the covariate the senior author asked for by name. The reversal is bounded: continuous medications supply a **presence flag in a look-back window** and nothing else. No dose, no rate, no infusion-derived index event, no `during_infusion` band. The original decision's concern — that continuous data would create a second, competing definition of the index event — does not arise, because nothing here defines an event. |
| P33 | **Every pre-index exposure is a presence test over a look-back window ending at `t₀`, evaluated at 1 h, 6 h and 24 h.** One helper implements the interval, and all four sources call it. | Set by the study lead (6 h and 24 h), with 1 h added to satisfy the senior author's "at the time of intubation" — a 6-hour look-back is not that, and 1/6/24 h also aligns the table column-for-column with the RSI project's `any_vasopressor_1hr_prior` / `6hrs` / `24hrs`. Four sources × three windows is twelve interval tests; written independently they will disagree about a row landing exactly on the far edge, and a one-row disagreement between "on pressors" and "on CRRT" is invisible in aggregate. Same reasoning as P15, applied to a wider surface. The window is closed at both ends: `t₀ - Xh <= dttm <= t₀`. |
| P39 | *(added 2026-08-14, amended the same day)* **Each Table 1 is published as two files from one row inventory:** a `_readable.csv`, and a `.json` carrying the long numeric form plus a provenance header. The long form was briefly also published as its own `.csv`; the study lead withdrew it on sight — *"do we need table1_by_agent_block now as there is .json and human readbale table 1"* — once it was confirmed that the JSON's `rows` array is that CSV's content exactly, byte for byte. Figure T.1 and `tests/test_block_row_contract.py` read the JSON instead. The trade accepted with it: the Table 1 JSONs are now the only non-CSV artifacts in `final_no_phi/`, and a site analyst who wants the numbers in a frame must unwrap `payload["rows"]` first. | Set by the study lead: *"make table 1's humanareadble in csv and also export as json for aggartions with other sites data."* Three consumers with genuinely different needs — the pipeline and its tests want one statistic per row; a person wants `63.2 (16.4)`; a coordinating centre pooling sites wants numbers as numbers, since a formatted string has to be parsed back apart and string parsing is where sites diverge. The readable CSV is **formatted from the published long CSV**, never recomputed: two tables that recompute the same quantity can disagree, two where one renders the other cannot. `NA` in the readable table means *not measured* and is typographically distinct from a measured `0` — the same distinction `covariate_coverage.csv` and figure T.2 exist to make. `publish_json()` sits behind `publish()`'s identifier and datetime checks in the same module: a second serialization, never a second disclosure policy. |
| P40 | *(added 2026-08-14)* **Proning is withdrawn from the covariate set.** `position` is no longer opened by any notebook, and `prone_{1,6,24}h` no longer exists. | Set by the study lead: *"remove the positon/prone from all lokations prne is not needed."* Proning is not a covariate of this study. The table is dropped outright rather than kept as an unused optional load, so a site does not need it and its absence is not reported as a coverage gap — an optional table nobody reads still costs every site an extract negotiation. |
| P44 | **AMENDED 2026-08-17: Table 1 adds lowest DBP; nonexclusive respiratory-device and vasopressor-agent flags at 1/6/24 h; CLIF ICU types plus ward/procedural locations; and 24 h SOFA from `clifpy.compute_sofa_polars`.** Missing SOFA components use CLIFpy's default score of 0 and `step04__sofa_coverage.csv` publishes component availability. | Set by the study lead. Device and vasopressor rows are deliberately nonexclusive, so their counts may sum above the table denominator. ICU subtypes use the full table denominator and reconcile to the aggregate ICU row. The clock remains the index paralytic `t₀`; the pipeline does not claim a separately adjudicated intubation timestamp. |
| P45 | **Generated artifact names encode ownership and figure lineage.** Figure dataframes use `figure_<id>_df`; plotted CSVs and PNGs share `fig_<ID>__<description>`; support files use `stepNN__<description>`. The four Table 1 pooling filenames stay unchanged. T.1 now publishes `fig_T1__organ_support_by_window.csv` from the Table 1 JSON and reads that CSV to draw the same-stem PNG. | Set by the study lead for audit and control. `artifact_manifest.csv` records every declared output, its dataframe and direct source, row count, size and checksum. |
| P34 | **AMENDED 2026-08-18: Table 1 includes only valid indexes with both an IMV transition and sedation.** It is published by block using each block's first valid index and by valid index event using every valid event. `n_index_in_block` counts valid indexes only. The two forms have identical statistic inventories and different units. | Set by the study lead. The block table is the manuscript's Table 1. A later valid index makes its block eligible even when `p_num = 1` is invalid; selecting the first valid event gives that block a representative from the population Table 1 claims to describe. The full `step04__index_covariates.parquet` and CPT denominator remain unchanged. |
| P35 | **Every Table 1 row carries a `rule` column and a `unit` column.** | Set by the study lead. These CSVs are merged across consortium sites and pasted into manuscripts, arriving detached from the notebook that produced them; every other artifact in this pipeline depends on `pipeline_flow.md` being read alongside it. A rule column also defuses the trap P34 creates: block-level outcomes repeat down the index-level table, so `los_hospital_days` there must state "block-level value, repeated per index event in the block" or a reader will average it. |
| P36 | **Continuous variables publish mean, SD, median, Q1 and Q3 — all five.** Categoricals publish `n` and `pct`. | Set by the study lead. Mean beside median is how a reader detects skew without a figure, and LOS, CCI and the index-per-block count are all heavily right-skewed. The RSI reference table publishes median/IQR alone, which is the specific gap the senior-author review asked to close. Counts beside percentages, likewise: a percentage without its numerator cannot be pooled across sites. |
| P37 | **AMENDED 2026-08-12 by the study lead: two independent definitions, with no invariant coupling them.** `hospital_mortality` = `death_dttm` falling inside a member hospitalization's admission→discharge interval **OR** `discharge_category == 'expired'`. `icu_mortality` = `death_dttm` falling inside an ADT `icu` interval. Nothing else. **`icu_mortality_undeterminable` is withdrawn.** | **Supersedes the original decision, which made ICU mortality a subset of hospital mortality and published a third `undeterminable` count for deaths flagged by `discharge_category` alone.** The bound on `death_dttm` is retained and still not decoration: in CLIF the `patient` table's `death_dttm` can be registry-sourced and will fire for a patient discharged alive who died months later at home, which unbounded would be published as in-hospital mortality. What the amendment drops is the coupling. Implementation of the original wording asserted the subset and disjointness properties, and those assertions **fired on real data at MIMIC** — 9 of 34,017 blocks with `icu_mortality` true while `hospital_mortality` was false, and 373 with `icu_mortality` and `undeterminable` simultaneously true. Diagnosed: every violation is `death_dttm` landing **after** `discharge_dttm` by under 24 hours (median 20.1 h, max 23 h 58 m), with the ADT `icu` interval likewise extending past discharge and 35 of the 36 affected index-bearing blocks carrying `discharge_category == 'expired'`. No death preceded its admission. These are in-hospital deaths whose recorded death timestamp trails the recorded discharge timestamp — a MIMIC recording artifact, not patients who died at home. Two ways of closing the gap were put to the study lead and both declined in favour of simplicity: adding death-in-ICU as a third route into `hospital_mortality`, and a 24-hour grace window past discharge (a threshold fitted to one site's artifact, with zero headroom at the observed maximum). **Accepted consequence, recorded here so a reader meets it rather than discovers it: `icu_mortality` is not a subset of `hospital_mortality`, and at a site with this artifact the ICU count can exceed the hospital count in a small number of blocks. The two are independent measurements published side by side, and neither is derived from the other.** |
| P38 | **LOS is summed over the block's member hospitalizations, not measured as the block's span.** | Set by the study lead. A block stitches up to 4 hospitalizations (`max_hosp_per_block = 4` at MIMIC) separated by gaps of up to `stitch_hours`; the span would count that gap time, during which the patient was not in the hospital. ICU LOS is summed over the block's ADT `icu` intervals on the same principle. |

------------------------------------------------------------------------

## 3. Architecture

Three downstream notebooks own covariates, Table 1, and CPT aggregation. `01` and `03` are
also amended by P2 so missing IMV charting no longer excludes a qualifying paralytic block.

| notebook | opens | reads | writes |
|---|---|---|---|
| `04_covariates.py` | `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `hospital_diagnosis`, `labs`, `patient_assessments`, and re-opens `hospitalization`, `adt`, and respiratory support through `compute_sofa_polars` | `step03__index_context.parquet`, `step01__cohort_index.parquet`, `step01__cohort_resp_waterfall.parquet` | `intermediate_phi/step04__index_covariates.parquet` (PHI); `final_no_phi/fig_T2__source_coverage.csv`, `step04__sofa_coverage.csv` |
| `05_table_one.py` | — | `step04__index_covariates.parquet` | stable `table1_by_agent_{block,index}_readable.csv` and `.json`; paired `fig_T1` and `fig_T2` data/PNGs |
| `06_reference_cpt.py` | `patient_procedures` | `step04__index_covariates.parquet` | `fig_F1__cpt_cascade.csv`, `fig_F1__cpt_cascade_qc.csv`, `figures/fig_F1__cpt_cascade.png` |
| `07_artifact_manifest.py` | — | all declared outputs | `artifact_manifest.csv` |

`04` is the **sole owner of the analytic row**. It reads `step03__index_context.parquet` alone for the event spine — that frame already carries every `step02__index_paralytic.parquet` column plus the D and E results, so joining both would be a redundant join on the same key. It derives the tier from `step03__index_context.parquet`, joins every covariate, attaches block-level attributes, and writes one frame. `06` aggregates the full frame for CPT. `05` applies only the specified Table 1 reduction: retain events with both contextual signals, recompute the valid-index count per block, and select the first valid event for the block form. It does not alter or republish the analytic frame.

`run_all.sh` runs `01_cohort` through `07_artifact_manifest`.

### 3.1 The analytic frame

`step04__index_covariates.parquet` — one row per index paralytic event, 2,117 at MIMIC.

```
keys          encounter_block · p_num · index_paralytic_id · patient_id · t_dttm
from 02       agent_label · n_before_merge_admin · n_admins · is_coadmin · n_agents
from 03       imv_transition · no_transition_reason · prior_device_category
              any_sedative · sedative_agent_set
category      evidence_tier in {1, 2, 3, 4} -- computed per row from its own D/E flags;
              the cascade (P31) reads it from the p_num = 1 row only
demographics  age_at_admission · sex_category · race_category · ethnicity_category
comorbidity   cci · sofa_total (worst values in [t0-24h, t0])
physiology    lowest_{sbp,dbp}_{1,6,24}h · highest_hr_{1,6,24}h · lowest_spo2_{1,6,24}h · weight_kg
life support  any vasopressor + each agent · CRRT · each CLIF respiratory device × {1h,6h,24h}
location      ed · icu + each CLIF location_type · ward · procedural · other · unknown
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
| `location_at_index` | the ADT row where `in_dttm <= t₀ < out_dttm`, mapped to `ed` / `icu` / `ward` / `procedural` / `other`; `unknown` when no ADT row covers `t₀`; ICU rows also retain the fixed CLIF `location_type` vocabulary |
| `weight_kg` | the most recent `vitals` weight at or before `t₀`, no look-back limit; null when the patient has none |
| `race_category`, `ethnicity_category`, `sex_category`, `death_dttm` | from `patient`, which is patient-level and needs no resolution |

The alternative — the block's first hospitalization — was rejected because a block's ED presentation and its inpatient admission can carry different recorded ages and different diagnosis lists, and the index paralytic belongs to exactly one of them.

`combination` as a Table 1 stratum means any `agent_label` containing `+` — the co-administration labels `step02__index_paralytic_composition.csv` already separates from same-agent redose. A block whose first index event is a rocuronium redose has `agent_label == 'rocuronium'` and belongs to the `rocuronium` column, not `combination`.

The frame carries identifiers and `t_dttm`, so `utils/suppress.py` will refuse it — correctly. It is a PHI intermediate; only the aggregations cross into `final_no_phi/`.

------------------------------------------------------------------------

## 4. Implementation constraints

**Loading (P19, restated because this amendment adds seven tables).** Every new table is read through its clifpy table class via `from_file`, with load-time filters enumerating casing variants (P20). clifpy normalizes recognized datetime columns to `TIMEZONE`; `to_site_naive` then removes that timezone with `series.dt.tz_localize(None)`, preserving the site-local wall clock without a second conversion. The respiratory waterfall in `01` is the only UTC boundary and is not used by this amendment. Timezone conversion is never done in polars, whose DST table stops extrapolating US rules around 2099 while MIMIC's dates are shifted into the 2100s.

**Diagnosis code formats.** `hospital_diagnosis` is not filtered by `diagnosis_code_format` during loading. The loaded values are stripped and lower-cased in memory before the complete frame is passed to `clifpy.calculate_cci`, so site variants such as `ICD10CM` and `icd10cm` are equivalent while clifpy remains responsible for selecting supported code systems.

**Interval arithmetic.** All minute/hour arithmetic is done inside polars with `pl.col(c).dt.epoch("s")`. No `datetime.timestamp()`, no `astimezone`, no `fromtimestamp`.

**One window helper.** `in_lookback(t0_col, dttm_col, hours)` is defined once in `04` and used by all four exposure sources (P33). Closed at both ends.

**The `hospitalization_id` bridge.** `06` maps CPT rows to blocks through the explode-and-drop bridge of the 2026-08-10 §6.1 — the only sanctioned place `hospitalization_id` may be named. A block is CPT-positive if **any** member hospitalization carries the code.

**Vasopressor vocabulary.** `norepinephrine`, `vasopressin`, `epinephrine`, `phenylephrine`, `dopamine` — a module constant, not a config key, for the reason P11 gives about the gap bins: a site that changed the list would make its Table 1 non-comparable with every other site's.

**Optional tables degrade to null, never to false.** `patient` and `patient_procedures` are required; absent, the notebook fails loudly. `crrt_therapy`, `position`, `vitals` and `hospital_diagnosis` are optional: absent, their derived columns are **null** rather than `false`, and `fig_T2__source_coverage.csv` publishes 0%. A null cannot be misread as "this patient had no CRRT"; a `false` can, and would be indistinguishable from a clinical finding.

------------------------------------------------------------------------

## 5. Sub-analysis F — the CPT comparator

`06_reference_cpt.py`. CPT rows are `procedure_code == '31500'` with `procedure_code_format` matching the CPT casing variants, reduced to one boolean per block.

**`fig_F1__cpt_cascade.csv`** — four mutually exclusive context categories × CPT presence, summing to the block denominator.

```
evidence_tier · rule · n_blocks · n_cpt_yes · n_cpt_no · pct_coded
```

**`fig_F1__cpt_cascade_qc.csv`** — denominator quality: blocks with any CPT-format `patient_procedures` row (`n_blocks_with_any_cpt_format_row` / `pct_blocks_with_any_cpt_format_row` — named for the CPT-format filter that actually produces them, not "any procedure of any kind"; see the observed result below for why the distinction matters), and the distribution of CPT codes per block. A site with thin billing extracts is visible here rather than being reported as poor agreement in the table above.

**Historical pre-amendment result at MIMIC, 2026-08-12.** The old three-row partition was
1,084 / 121 / 342, summing to 1,547. Category 1 then included sedation-only blocks and must
not be compared directly with the amended four-category output. The CPT finding is unchanged:
**`pct_coded` was 0.0 in every category**, and the reason was a site fact rather than a defect:

- MIMIC's `patient_procedures` holds 1,045,729 rows, of which 116,032 (11.1%) are
  CPT-format — so the format filter works and CPT data is present.
- Procedure code `31500` appears **15 times in the entire table**. MIMIC codes inpatient
  procedures via ICD-9 (469,209 rows) and ICD-10-PCS (390,446); CPT is professional
  billing, which this extract largely does not carry for ICU stays.
- Of those 15 hospitalizations, 9 fall inside the ever-IMV cohort and **none** falls in
  the 1,547 index-bearing blocks. `fig_F1__cpt_cascade_qc.csv` reports
  `pct_blocks_with_any_cpt_format_row = 0.06` — MIMIC has 1,045,729 procedure rows
  covering essentially every block, so this stat is deliberately scoped to
  CPT-*format* rows and not to "any procedure of any kind"; publishing it under an
  all-procedures name would read as a broken extract instead of as this site fact.

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
extract lacks professional billing. `fig_F1__cpt_cascade_qc.csv` is what tells a site that before
they read the cascade, and a site reporting `pct_blocks_with_any_cpt_format_row` near zero
should treat F as not run rather than as a null result.

------------------------------------------------------------------------

## 6. Table 1

`05_table_one.py`. The input is filtered to `imv_transition & any_sedative`, which is asserted equivalent to `evidence_tier == 3`. The index form includes every valid event. The block form includes every block with at least one valid event and uses its lowest-`p_num` valid event. Both forms have an identical statistic inventory and different units (P34). Long format: one row per statistic, one column per stratum.

```
statistic · rule · unit · rocuronium · succinylcholine · vecuronium · combination · overall · site_name
```

Strata come from `agent_label` of the valid index event; in the block form this is the block's first valid event. `combination` collects the co-administration labels that `step02__index_paralytic_composition.csv` already separates from redose. **Every stratum column is emitted even when structurally empty** — a column present at one site and missing at another is what breaks a multi-site merge. This is the published-zero convention of P21, applied to columns.

Row inventory, with P36's five statistics for every continuous variable and `n` + `pct` for every categorical:

```
demographics   age_at_admission · sex_category · race_category · ethnicity_category · n_patients
comorbidity    cci
physiology     lowest_sbp · lowest_dbp · highest_hr · lowest_spo2 × {1h, 6h, 24h} · weight_kg
life support   any/per-agent vasopressor · crrt · per-device respiratory support × {1h, 6h, 24h}
context at t0  imv_transition · already_on_imv · any_sedative · location_at_index
outcomes       hospital_mortality · icu_mortality
               los_hospital_days · los_icu_days · n_index_in_block (valid indexes only)
coverage       one pct per source table
```

`race_category` and `ethnicity_category` are published as **raw mCIDE categories with counts**, not collapsed into a derived race/ethnicity variable. The RSI project collapses to five buckets inside its analysis; collapsing at publication would make the site's own distribution unrecoverable, and the coordinating centre can collapse a count table but cannot un-collapse one.

------------------------------------------------------------------------

## 7. Figures

Three, all drawn from published CSVs and never from an in-memory frame, following the conventions already set in `02` and `03`: fixed categorical colours never cycled, published zeros drawn as baseline diamonds, no number on a plot that is not in the CSV beside it.

| figure | shows | why this form |
|---|---|---|
| `fig_F1__cpt_cascade.png` | Four context categories × CPT presence as a mosaic: row height ∝ category n, split by CPT yes/no | Categories can be very unequal. A mosaic encodes both the size disparity and each category's coded fraction without implying that the four `pct_coded` values should sum to 100%. |
| `T1_life_support_by_window.png` | Vasopressor · CRRT × 1 h / 6 h / 24 h | The 1 h → 24 h ramp is where "already shocked" separates from "crashed at intubation", and that is a shape, not a number. |
| `T2_source_coverage.png` | One bar per new CLIF table | The figure a site reads first to know whether its Table 1 is trustworthy. Makes a structural zero look different from a clinical one at a glance. |

------------------------------------------------------------------------

## 8. Testing

| test | pins |
|---|---|
| `tests/test_lookback_window.py` | P33's interval, closed at both ends: a row exactly on `t₀ - 24h` is in, one a second earlier is out, one after `t₀` is out. Mirrors `test_pair_gaps.py`. |
| `tests/test_cpt_bridge.py` | A 4-hospitalization block with the CPT on its 3rd member flags positive; a code on a hospitalization outside the block does not leak in. |
| `tests/test_block_row_contract.py` | The full `p_num = 1`/CPT denominator still reconciles independently; both Table 1 forms contain only valid indexes; the block form selects each block's first valid index and counts valid indexes only; every source block-level column is constant within its block. |
| `tests/test_mortality_bound.py` | P37 as amended: a `death_dttm` outside the stay does not count as in-hospital mortality; `discharge_category == 'expired'` alone does; `icu_mortality` is decided by the ADT `icu` interval alone and is deliberately not constrained by `hospital_mortality`. |
| extend `tests/test_clifpy_tz_boundary.py` | The existing no-naive-timestamp AST check is extended to `04`, `05` and `06`. |
| extend `tests/test_publish_guard.py` | `step04__index_covariates.parquet`'s column set is rejected by `publish()` — the frame is PHI and must stay that way. |

------------------------------------------------------------------------

## 9. Out of scope

- **Any statistic requiring the false-negative cell.** Sensitivity, specificity, NPV and kappa are not published, for the reason P26 gives. A reader who wants them needs a denominator this study does not use.
- **Any time alignment of the CPT flag** — block-day, minute-level, or the day-offset distribution that briefly stood in their place. Declined by the study lead twice: first as an alignment (P29), then as a measurement of what the missing alignment costs (P30, withdrawn). The flag is presence within the block, and the limitation is stated rather than quantified.
- **Infusion doses and rates.** `medication_admin_continuous` supplies presence flags only (P32).
- **Ventilator duration, extubation, reintubation linkage.** Outcomes are restricted to mortality and LOS.
- **Composite scores other than CCI and SOFA.**
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
| `vitals` | optional | worst SBP / HR / SpO₂, weight |
| `hospital_diagnosis` | optional | CCI via clifpy |

Optional means the pipeline runs without it, the derived columns are null, and coverage publishes 0% (§4). `position` was on this list until P40 withdrew it; it is no longer opened and a site does not need to supply it.
