# VentTRACE — how the pipeline works

A plain-language walkthrough of what each notebook does and why. The authoritative
definitions live in
[`superpowers/specs/2026-08-10-paralytic-index-design.md`](superpowers/specs/2026-08-10-paralytic-index-design.md)
(`01`–`03`) and
[`superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md`](superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md)
(P26–P38, the amendment that is the entire rationale for `04`–`06`); this document is the map,
not the territory. Where either disagrees with a spec, the spec wins.

Counts shown are MIMIC, `cohort_run_id` 2026-08-10T14:15:46, read from the CSVs in
`output/final_no_phi/` as they stand.

---

## 1. What the study is actually asking

The previous build of this pipeline asked whether several ways of saying "an intubation
happened here" agreed with one another — sedatives, paralytics, a paired sedative-plus-paralytic
signal, and a billing code, all pinned to a t₀ the ventilator record had already fixed.

**This build inverts the anchor.** The paralytic administration is now the index event. There
is no second method, no reference standard, and no agreement statistic to compute — there is one
index definition and four questions asked about it:

1. How are paralytic administrations distributed in time relative to one another?
2. Given a 15-minute boundary, how many distinct index paralytic events does a hospitalization
   have, and how far apart are they?
3. Does the ventilator record show a transition onto invasive ventilation around the index
   paralytic — not "was IMV charted" (a patient already ventilated satisfies that trivially) but
   *did the device change*, from 30 minutes before through 60 minutes after the index?
4. Was a sedative charted within the configured ±5-minute sedation window, and at what dose?

**This is intubation-adjacent, not intubation-confirming.** The study describes what surrounds a
paralytic. It does not adjudicate whether an intubation occurred, and it carries no agreement
machinery at all — there is nothing to agree with, because there is exactly one method.

---

## 2. The pipeline at a glance

```
   CLIF parquet files
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 01_cohort.py            WHO is in the study                      │
│                                                                  │
│  adults · date range · ever on a vent · no pre-existing trach    │
│  stitch hospitalizations <6h apart    → encounter_block          │
│  waterfall respiratory_support        → a gap-free device timeline│
└───────┬──────────────────────────────────────────────────────────┘
        │  34,017 encounter blocks · 31,124 patients
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 02_index_paralytic.py   THE INDEX EVENT                          │
│                                                                  │
│  A  gap distribution across every pair of raw administrations    │
│  B  anchor-and-close at 15 min   →  2,117 INDEX PARALYTICS       │
│     exclude anchors in ADT procedural locations                   │
│  C  gap distribution between index paralytics                    │
└───────┬──────────────────────────────────────────────────────────┘
        │  step02__index_paralytic.parquet — one row per index paralytic
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 03_context.py           WHAT SURROUNDS IT                        │
│                                                                  │
│  D  first transition in -30/+60 min; nearest in ±6 h sensitivity │
│  E  sedatives charted in t ± 5 min (configured), with dose       │
└───────┬──────────────────────────────────────────────────────────┘
        │  step03__index_context.parquet
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 04_covariates.py        THE ANALYTIC ROW                         │
│                                                                  │
│  demographics · comorbidity · physiology and life support in     │
│  1/6/24h look-backs · block-level LOS and mortality               │
└───────┬──────────────────────────────────────────────────────────┘
        │  step04__index_covariates.parquet — PHI, the sole owner of the analytic row
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 05_table_one.py         TABLE 1                                  │
│                                                                  │
│  valid index = paralytic + IMV transition + sedation             │
│  all valid events, plus each block's first valid event           │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 06_reference_cpt.py     THE CPT 31500 COMPARATOR                 │
│                                                                  │
│  four mutually exclusive IMV/sedation context categories vs a    │
│  block-level billing flag                                         │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 07_artifact_manifest.py AUDIT AND CONTROL                        │
│                                                                  │
│  reject stale/missing files · record dataframe lineage + SHA-256 │
└───────┬──────────────────────────────────────────────────────────┘
        │
    output/final_no_phi/   aggregates + figures, no row-level records
```

Six notebooks and one artifact-audit step run in order. Each analysis notebook is named for the CLIF table it opens rather than for a step
number that would drift as the design changes. `01` touches `hospitalization`, `adt` and
`respiratory_support`. `02` touches `medication_admin_intermittent`, filtered to the three
paralytics, and `adt` for formed-index anchor locations. `03` touches the waterfalled
device timeline from `01` and `medication_admin_intermittent` again, filtered to five sedatives.
`04` is the sole owner of the study's analytic row — one row per index paralytic — and is the
only notebook that opens `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`
and `hospital_diagnosis`, re-opening `hospitalization` and `adt` alongside them; its
output, `step04__index_covariates.parquet`, is PHI (it carries `t_dttm` and the identifier columns) and
is never published. `05` opens no CLIF table — it reads `step04__index_covariates.parquet` and
the aggregate step-02 administration summary, builds Figure 1 as the main analysis CONSORT,
restricts Table 1 to events with both a configured-window IMV transition and sedation, and
publishes it twice: all valid events and each block's first valid event, in two stable forms each. `06` opens `patient_procedures`,
the only notebook in the pipeline that does, alongside `step04__index_covariates.parquet` and
`step01__cohort_index.parquet`. `medication_admin_continuous` is opened only by `04`; every dose measured
in `02`/`03` is a discrete charted push, not a continuous infusion.

**Artifact names are part of the audit trail.** Every plotted dataframe is named
`figure_<id>_df`; its data and PNG share one stem, such as
`fig_E2__sedation_dose_summary.csv` and
`figures/fig_E2__sedation_dose_summary.png`. Supporting outputs use
`stepNN__<description>`. `artifact_manifest.csv` records the producer, figure ID, primary
dataframe, sources, row count, byte size and SHA-256. The four `table1_by_agent_*` filenames
remain unchanged as consortium pooling contracts.

**New artifacts in `output/final_no_phi/`:** `fig_1__main_consort.csv` and its same-stem PNG
(from `05` — the primary flow from qualifying paralytic administrations through formed indexes,
IMV transition, sedation, and both Table 1 units); `fig_T2__source_coverage.csv` (from `04` — the null rate
of every derived covariate, including 0% for any optional CLIF table a site's extract lacks);
`table1_by_agent_block.*` and `table1_by_agent_index.*` (from `05` — identical statistic
inventories restricted to valid indexes, denominated in blocks with a valid index and in valid
index events respectively; the block table uses each block's first valid event, and each is published
as two files: a `_readable.csv` formatted for a person, and a `.json` carrying the long numeric
form plus a provenance header — read by this pipeline's own figure T.1, by its tests, and by a
coordinating centre pooling sites alike. **The Table 1 JSONs are the only artifacts in
`final_no_phi/` that are not CSVs**, and the only published tables a reader must unwrap
(`payload["rows"]`) before reading; the long form carried its own `.csv` until 2026-08-14, when
the study lead withdrew it as an exact duplicate of that array); `fig_F1__cpt_cascade.csv` and `fig_F1__cpt_cascade_qc.csv` (from `06` — four mutually exclusive
paralytic context categories against the CPT `31500` billing flag, and its QC). §2's table map above and
`code/README.md`'s table carry the same rows. The CPT comparison is **presence within the
encounter block**: all the codes for all the block's member hospitalizations are pooled, and one
`31500` anywhere in that pool means the block has an intubation. No date is compared — P30's
`cpt_offset_distribution.csv` and figure `F2_cpt_offset.png` were withdrawn on 2026-08-14. CPT
`31500` is a **comparator, not a reference standard** (spec P26 —
[`superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md`](superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md)),
and a site whose extract lacks professional billing sees an empty cascade —
`fig_F1__cpt_cascade_qc.csv`'s `pct_blocks_with_any_cpt_format_row` says so before the cascade itself does.
`02` and `03` also write `fig_B1__paralytic_dose_ecdf.csv` and `fig_E3__sedation_dose_ecdf.csv` with figures
of the same stems (P41) — the full empirical CDF of
charted dose per `(med_category, med_dose_unit)`, on the raw unit rather than the converted one,
so P18's unit fold is visible rather than inferred. `02` and `03` additionally write
Each medication uses the exact unit selected in `config["medication_dose_units"]` and the
strict eligibility limit in `config["medication_dose_upper_bounds"]`; no unit-correction
artifacts are produced because values and units are never relabeled.
For paralytics only, repeated instances of the same medication are summed after each index
event is formed and before B.1, B.2, or other index-dose analyses run. Raw administration
gap and count outputs remain unchanged, and medications never merge across formed indexes.

`04` adds P46's site-ready outputs. `step04__intubations_by_hospital_year.csv` counts one
block-first paralytic-index event by configured healthcare system, event-time ADT hospital,
academic status and calendar year; `fig_H1__intubations_by_hospital_year.csv/.png` presents the
same yearly trend with one line per hospital, colored by academic status. The measure remains
intubation-adjacent rather than adjudicated.
`fig_B2__paralytic_dose_per_weight_ecdf.csv` and
`fig_E4__sedation_dose_per_weight_ecdf.csv` publish normalized distributions with integer counts.
`step04__combined_induction_dose_distribution_percentiles.csv` publishes site-specific p1-p99 for
etomidate and ketamine. `fig_E5__induction_dose_tiers.csv` carries every local tier numerator and
denominator needed for later pooled logit random-effects analysis, while its PNG is explicitly
local and has no pooled confidence intervals. `fig_E5_2__induction_dose_bins.csv/.png` adds a local
five-bin view of the same normalized administration-window population, with 0.35 mg/kg etomidate
and 2.5 mg/kg ketamine included in the fourth bins. `step04__valid_index_induction_dose_by_stratum.csv`
restricts to the index-level Table 1 population (`imv_transition and any_sedative`), sums repeated
etomidate or ketamine administrations per index and drug, and reports mg/kg median, quartiles,
mean, sample SD, available N, and missing-weight N across location, 1-hour vasopressor exposure,
sex, ethnicity, white/non-white race, and SOFA scores 0-24. Location retains ED and ICU only.
Null/unknown values fold into not-on vasopressor, other sex, non-Hispanic ethnicity, and non-white
race. An index receiving both etomidate and ketamine contributes once to each drug summary.
`fig_E6__valid_index_induction_dose_bins.csv/.png` presents the requested five-bin
event-level distributions. `fig_G1__dose_per_weight_consort.csv` reports every dose and weight
exclusion without changing the block/patient analytic cohort.

**Figure 1 is the main analysis.** It ends at Table 1 and reports four counts at every applicable
stage: source paralytic administrations, medication entries after same-agent merging, formed
indexes, and encounter blocks. Exclusion rows report why indexes fail and how many blocks are
actually removed because none of their indexes pass. The 15-minute fold and same-agent merge are
transformations, not exclusions. The final block form selects one first-valid index per block;
additional valid indexes remain in the index-level Table 1 and are not clinical exclusions.
Subanalyses A-G start from populations already shown in Figure 1 and never feed filters back into it.

---

## 3. `01_cohort.py` — who is in

**Unchanged by this overhaul** (spec P2). The cohort definition, the stitching, and the
waterfall are exactly what they were before the anchor moved, because none of that logic knows
or cares which drug is being studied.

**Criteria**, applied to the stitched block:

| | |
|---|---|
| age | ≥ 18 at admission |
| dates | 2018-01-01 … 2025-12-31 (skipped at MIMIC — its timestamps are date-shifted, so a calendar filter is meaningless there) |
| location | ED **or** ICU at some point in the block |
| index signal | at least one qualifying rocuronium, succinylcholine, or vecuronium administration: `given`, exact configured unit, eligible configured dose |
| exclusion | tracheostomy in the first 24 h — `tracheostomy` truthy **or** `device_category == 'trach collar'` |

**Stitching comes first.** An ED presentation and the inpatient admission that follows it can
carry different `hospitalization_id`s. Hospitalizations less than 6 h apart for the same patient
are merged into one `encounter_block`, and every notebook after `01` keys on the block rather
than the raw id. Without this, a paralytic charted in the ED and a ventilator transition charted
after transfer would read as unrelated — one clinical act split by an administrative boundary.

**The waterfall makes the available device record continuous.** Raw `respiratory_support` is charted
irregularly. `clifpy`'s `process_resp_support_waterfall` inserts hourly scaffold rows,
forward-fills `device_category`, and relabels a row with a null device to `imv` when the
ventilator settings on it look like a ventilator. Sub-analysis D reads this output, not the raw
table — see §5. A block without a raw IMV row remains eligible; missing respiratory context is
reported as `no_device_record` rather than excluding a patient who died before IMV was charted.

The expensive CLIFpy operation is resumable. `01` caches its projected result by stable
`hospitalization_id` under `output/intermediate_phi/resp_waterfall_cache/`, with per-hospital
source digests and checksummed atomic batch shards. A rerun reuses current entries, waterfalls
only missing or changed hospitalizations from the final post-tracheostomy cohort, then attaches
the newly generated `encounter_block` mapping and `cohort_run_id`. The canonical
`step01__cohort_resp_waterfall.parquet` is atomically promoted immediately after assembly;
temporary or interrupted batches are never referenced by the cache manifest.

The funnel is evaluated in this order:

```
source hospitalizations
        │  keep all hospitalizations for patients with >=1 qualifying paralytic
        │  stitch same-patient hospitalizations <6h apart → encounter_block
        │  age >=18
        │  admission date window (skipped at MIMIC)
        │  >=1 ADT row in {ed, icu}
        │  >=1 qualifying paralytic administration in the stitched block
        │  exclude trach signal in the first 24h
        ▼
ANALYTIC COHORT
```

`step01__cohort_qc.csv` reports the hospitalization count per block, respiratory-row coverage, raw-IMV
coverage, and where the first IMV row falls among blocks that have one.

**Outputs consumed downstream:** `step01__cohort_index.parquet` (the join spine — `encounter_block`,
`patient_id`, `cohort_run_id`, `list_hospitalization_id`) and `step01__cohort_resp_waterfall.parquet`
(the gap-free device timeline). `02` explodes `list_hospitalization_id` to reach the medication
table; `03` reads the waterfall for sub-analysis D. Neither notebook re-derives a block, and
neither ever names a raw `hospitalization_id` outside the one bridge step that reaches it (§4).

---

## 4. `02_index_paralytic.py` — the index event

Loads `medication_admin_intermittent`, filtered to `med_category ∈ {rocuronium,
succinylcholine, vecuronium}`, `mar_action_category == given`, the medication's exact configured
unit, and its configured strict dose eligibility range. Rows that fail any of those criteria do
not form index events.

The bridge maps both medication rows and ADT intervals from `hospitalization_id` to
`encounter_block`. The raw identifier is dropped before folding, so a paralytic charted in the ED
cannot fail to pair with one charted on the floor after transfer.

### A — the paralytic administration gap distribution

Every **unordered pair** of paralytic administrations within a block, same-agent pairs included,
computed **before** the fold and depending on nothing it decides — this is the evidence for the
15-minute boundary, not a consequence of choosing it. At this site: **1,192 pairs** total, and
the split is stark — **1,181 are same-agent** (a redose of the same drug) against **11
cross-agent** (two different paralytics). `rocuronium+rocuronium` accounts for 980 of those pairs
and peaks at 223 in the `(3,7]d` bin; `rocuronium+vecuronium` totals 11 and peaks at 5, in `>7d`.
The pooled histogram cannot tell a redose from a
co-administration; the same/cross split is what lets it.

### The 15-minute fold — anchor and close

```
first unconsumed administration     →  ANCHOR.  t := its admin_dttm
every administration <= t + 15 min  →  joins this index event
first administration beyond that    →  new ANCHOR
```

**Anchored, never chained.** A row joins the event only while it is within 15 minutes of that
event's *first* row — never of the row before it. Chaining has no bound: an agent redosed every
14 minutes would walk one event forward indefinitely, and its clock would end up hours from most
of its own doses, which destroys the reference point sub-analyses C, D and E all measure offsets
against. Anchoring makes `span_minutes ≤ 15` an assertable invariant instead of a hope, and the
notebook asserts it on every write. Inclusive at the boundary: a dose landing exactly at `t + 15`
still merges.

Fifteen minutes is a **clinical** definition, not a fitted one — the same superseded build that
measured intubation timing directly found no empirical valley to fit a threshold to; from two
minutes onward, same-agent and cross-agent gaps ran at indistinguishable rates. What 15 minutes
buys is keeping a paralytic *redose* inside one induction sequence rather than fragmenting it
into several index events, and Figure A.1 publishes the whole distribution beside the line so a
reader can judge it directly rather than take the number on trust.

### B — the index paralytics

The fold produces **2,117 index paralytics** — **1,555 rocuronium** and **562 vecuronium** —
across **1,547 encounter blocks**. Most blocks have exactly one (1,204 of 1,547 — 77.8%); 236
have two; the tail runs out to 12 in a single block. Co-administration inside an index event —
folding *more than one agent* together — does not occur at this site: `agent_label` in
`step02__index_paralytic_summary.csv` carries only single-agent labels, zero of them cross-agent. What
is not rare is the same-agent **redose**: 42 of 2,117 index paralytics (2.0%) fold more than one
*administration* of the same agent together (`n_coadmin` in `step02__index_paralytic_summary.csv`).

After formation, each index anchor is attributed to the ADT interval satisfying
`in_dttm <= t_dttm < out_dttm`; null `out_dttm` is open-ended. Overlaps resolve by earliest
`in_dttm`, then normalized `location_category`, then `hospital_id`. Indexes resolving to exact
normalized category `procedural` are excluded; indexes with no covering interval are retained as
`unknown`. Remaining events are renumbered from 1 within each block. Figure A.1 remains based on
all qualifying administrations because it is evidence for the fold, while Figure C.1 and every
downstream artifact use retained indexes. `step02__procedural_index_exclusion_summary.csv`
reconciles formed, excluded, and retained populations.

Two facts are the design working, made visible in the published output rather than merely
asserted:

- **`max_span_min` is exactly 15.0 for both agents** — `step02__index_paralytic_summary.csv`. That is
  the assertable invariant P6 bought by choosing anchor-and-close over transitive chaining: no
  index event, however many administrations it folds, can span more than the threshold that
  defines it.
- Doses are retained without conversion in one configured unit per `med_category`. Repeated
  doses of the same medication are summed only within an already-formed index, yielding at
  most one dose row per medication and index. The configured-unit counts-only table is
  `step02__paralytic_dose_raw_unit_counts.csv`.
  `fig_B1__paralytic_dose_ecdf.csv` carries the same
  counts with the whole distribution attached: `n_total` there equals `n` here by construction,
  since both are grouped from one frame on one pair of keys.

### C — the gap between index paralytics

The identical construction as A — all unordered pairs, the identical 15-bin grid — applied to
`t_dttm` instead of raw administration times. **1,110 inter-index pairs** are published, the
mass concentrated in the multi-day bins (234 beyond 7 days, 227 in 3–7 days) — the spacing of
genuinely separate paralytic episodes within a stay, not redosing.

**`fig_C1__index_paralytic_pair_gaps.csv` has a count of zero in every bin below 15 minutes** — `0`,
`(0,1]`, `(1,2]`, `(2,5]`, `(5,10]`, `(10,15]`. That is not a data gap. It is the fold's defining
property made visible: an anchor at `t` closes at `t + 15` inclusive, so the next anchor is the
first administration *strictly after* `t + 15` — two index paralytics cannot be closer together
than the threshold that separates them, by construction. `02` asserts these six bins are empty
on every run; a non-zero count there would be a bug in the fold, not a finding.

**Output:** `step02__index_paralytic.parquet`, written to `output/intermediate_phi/` — it carries
`t_dttm`, a real timestamp, so it is PHI and is never published. It is the spine `03` joins to.

---

## 5. `03_context.py` — what surrounds the index paralytic

Two questions using one inclusive predicate (P15), with separate configured bounds: D uses
30 minutes before through 60 minutes after the index, while E remains symmetric at ±5 minutes.
Sharing the predicate keeps their boundary behavior consistent without coupling their clinical
definitions.

### D — the non-IMV → IMV transition

```
a row is a TRANSITION when
      device_category == 'imv'
  AND ( no preceding row exists in the block
        OR preceding device_category != 'imv' )

null is not imv     ->  null -> imv  IS a transition
block opens on imv  ->  that first row IS a transition
imv -> imv           ->  not a transition
```

Computed on the **waterfalled** timeline from `01`, not raw `respiratory_support` — the
waterfall is what makes "the row before" well defined at all, and its settings-based `imv`
inference reaches the chart before a human fills in the device field in a high-stress event like
an intubation. This detects an **event**, not a **state**: "was IMV charted nearby" is
satisfied by a patient who has been ventilated for a week and reports nothing about this
paralytic. A transition reports that the device actually changed.

Figure D.2 is an additive sensitivity view. It applies the same transition definition across an
inclusive ±6-hour window, selects one nearest transition per index paralytic (earlier wins an
exact-distance tie), and plots 30-minute bins. It does not alter D.1, `imv_transition`, or any
downstream cohort definition.

At this site, of 2,117 index paralytics:

| outcome | n | % |
|---|---|---|
| a transition occurred in the window | 484 | 22.9% |
| already on IMV at `t` — no transition needed | 1,586 | 74.9% |
| not on IMV at `t`, and nothing changed nearby | 37 | 1.7% |
| no waterfall device record at or before `t` | 10 | 0.5% |

**Remember the cohort floor (spec P2):** every block already reached IMV at some point, so the
22.9% detection rate here is not specificity — it is "given that this patient was ventilated at
some point, did the device change around *this* paralytic", a narrower and answerable question.

Where the transition sits relative to `t`: slightly more land *before* the paralytic (279 of 484,
57.6% — the vent came first) than after (205, 42.4%), and the single busiest 5-minute bin is
`[0,5)` with 50 — the paralytic and the device transition most often land within minutes of each
other. What the airway was immediately before a transition (`step03__imv_prior_device.csv`): nasal
cannula most often (129), then a block that opens on IMV with nothing charted before it at all
(111 — the patient arrived already-tubed), face mask (110), high-flow NC (64), NIPPV (40).

**No de-bouncing rule is applied** (P14) — the hourly scaffold can in principle manufacture a
spurious transition from a brief non-IMV blip, and `n_transitions_in_window` is published so
that effect is measurable rather than tuned away with a second unvalidated threshold. At this
site every one of the 484 detected transitions carries exactly `n_transitions_in_window = 1`; the
ambiguity P14 declines to suppress does not manifest in this run, and the published table is what
lets a reader confirm that rather than take it on trust.

### E — sedation in its configured window

The same inclusive predicate as D, supplied with the independent configured ±5-minute sedation
width, is applied to `medication_admin_intermittent` filtered to
`{midazolam, etomidate, ketamine, propofol, fentanyl}`. Sedation here is a **covariate** of the
index paralytic, not a detector — there is no `SED` method and no sedative-derived index event.
**Every** administration in the window is kept, not only the nearest per agent, because this
study publishes an offset histogram and deduplicating would delete the redosing pattern it
exists to show.

Dose statistics retain the exact configured unit per `med_category`, clinically filtered,
and keyed on `med_category` alone (P18/P43). Both tables publish mean, sample SD, median, p25
and p75. Included absolute-unit values satisfy `0 < dose <` the configured agent-specific upper
bound: etomidate 200 mg, fentanyl 500 mcg, ketamine 100 mg, midazolam 50 mg, propofol 500 mg,
rocuronium 400 mg, succinylcholine 400 mg and vecuronium 30 mg. Wrong-unit and ineligible-dose
administrations are excluded before event construction or window matching.

**What E's counts count: pairs, not administrations.** A block can hold several index
paralytics, and a physical administration inside two overlapping configured windows contributes
a row to each. The current ±5-minute sedation windows cannot overlap because index paralytics
are more than 15 minutes apart, but the pair-shaped output contract remains explicit if a site
changes the configured width. The column is named `n_admin_windows` for exactly this reason.
`fig_E3__sedation_dose_ecdf.csv`'s `n_total` is drawn from the same pairs, for the same reason — it is
not comparable row-for-row with `fig_B1__paralytic_dose_ecdf.csv`'s `n_total`, which counts
administrations, despite the two files sharing a column name and schema.

**Output:** `step03__index_context.parquet` — `step02__index_paralytic.parquet` plus D's and E's columns, one
row per index paralytic, written to `output/intermediate_phi/`. It carries raw timestamps
(`t_dttm`, `imv_transition_dttm`, per-dose `admin_dttm` inside `sedatives`) and is never
published in any form.

### P46 - normalized dose and local induction tiers

Step 04 selects a dose-specific weight independently of Table 1: the latest finite 20-300 kg
weight at or before the event in the current hospitalization, otherwise the latest prior-hospital
weight recorded within 28 days. Configured `/kg` values are already normalized and bypass
weight selection; absolute-unit values use P43's absolute-dose checks before division
before division. Missing weight reduces only normalized-dose denominators.

Sedation normalization retains E's existing unit: an `(index paralytic, administration)` pair.
The induction percentile and tier population is every etomidate or ketamine pair inside the
configured +/-5-minute window, with no additional normalized-dose range filter. The separate
valid-index summary and E.6 population requires the Table 1 index gate, sums repeated
administrations per drug/index, and includes crossover indexes in both received-drug summaries.
Site percentiles are descriptive and cannot
be averaged across sites. B.2/E.4 integer `n_at_dose` values can be concatenated to reconstruct a
pooled distribution; E.5 integer tier numerators and denominators support the later coordinating
center meta-analysis.

---

## 6. The disclosure boundary

**`output/intermediate_phi/` is row-level PHI and never leaves the site.** It holds real
timestamps and, upstream of the drop points described above, real identifiers —
`step01__cohort.parquet`, `step01__cohort_resp_imv_raw.parquet`,
`step01__cohort_resp_waterfall.parquet`, `step01__cohort_index.parquet`,
`step02__index_paralytic.parquet`, `step03__index_context.parquet`,
`step04__index_covariates.parquet`. Nothing in this
directory is a deliverable.
Copying a file out of it, by any means, is a data breach. `step04__index_covariates.parquet` carries
`index_paralytic_id`, `encounter_block`, `patient_id`, `p_num` and `t_dttm` — `publish()` refuses
it by construction, and `tests/test_publish_guard.py`'s
`test_index_covariates_column_set_is_refused` pins exactly that refusal.

**Run logs are written to `output/final_no_phi/logs/`.** The launchers capture each step's stdout
under `logs/run_<UTC timestamp>/`, and `02` can print `encounter_block` ids as part of its
memory-guard diagnostics (§4). `encounter_block` is not stable across runs (§8), but it is an id;
the logs are not covered by `publish()` and are excluded from the artifact manifest inventory.

**`output/final_no_phi/` is the only directory a site shares.** Its published CSV, JSON, and PNG
analysis artifacts are aggregates: counts, rates, and quantiles keyed on bins or categories, never
rows that describe one person. The `logs/` subdirectory is raw console output as described above.

**`utils/suppress.py` is the only door between them**, imported by every notebook and nowhere
else. It exposes two writers over one shared check: `publish()` for CSV, and `publish_json()`
for the Table 1 aggregation payloads `05` produces. JSON is a second *serialization*, never a
second policy — both refuse to write (raise `AssertionError`, do not filter silently) a frame
that carries either:

- an **identifier column** — `patient_id`, `hospitalization_id`, `encounter_block`, `p_num`, or
  any column whose name ends in `_id`. `cohort_run_id` is exempted — it is a provenance stamp
  shared by every row of an extract, not something that identifies a person.
- a **datetime column** — checked on dtype (`pl.Datetime`, naive or timezone-aware, and
  `pl.Date`), never on column name. An aggregate has no timestamp; every row-level artifact in
  this study does.

Nothing else is checked, and nothing is filtered: a row whose count is 0 is written, and a row
whose count is 3 is written. **The n ≥ 10 small-cell suppression rule this project used to
enforce is gone.** The boundary the study lead drew (spec P21, amended 2026-08-10) is row-level
versus aggregate, not cell size — a bin count of "6 propofol administrations charted in mcg"
describes a bin, not a person, and the cohort it is drawn from is already defined by a published
inclusion rule. The withdrawn rule bought deniability for a single small cell and paid for it in
a second layer of machinery — classifying every bin as fully published, pooled-only, or withheld
so that two files sharing a key could not be differenced to recover a suppressed value — that
itself produced three separate, independently-discovered subtraction leaks (a summary total
minus its published components; one table's count minus another's; a dose row minus its own
offset bins), and even after closing the third the suppression scheme still only bounded the
withheld value to a handful of candidates rather than truly hiding it. A rule that has to be
defended by a second rule that has to be defended by a third is not protecting anyone; it is
generating work. What actually protects the patient — nothing row-level, ever — never moved, and
is now the one thing `publish()` checks.

---

## 7. Every rule in one table

| # | Rule | Where | Effect / value |
|---|---|---|---|
| P2 | **amended 2026-08-17** — adults, date window, ED/ICU, >=1 qualifying paralytic, no trach in 24h; stitch <6h apart; raw IMV is not required | `01` | respiratory absence becomes context/QC rather than exclusion |
| P3 | paralytic list: `rocuronium`, `succinylcholine`, `vecuronium` (`cisatracurium`/`atracurium` excluded — maintenance agents, not induction) | `02` | 1,585 roc + 575 vec administered (succinylcholine absent at this site) |
| P4 | superseded by P47 | `01`, `02`, `03` | `bolus` excluded |
| P5 | analytic unit is `encounter_block`; `hospitalization_id` named only at the bridge, dropped the instant the join lands | `02`, `03` | |
| P6 | index paralytics formed by anchor-and-close at 15 min, never transitive chaining; inclusive at the boundary | `02` | `span_minutes <= 15` always; 2,117 index paralytics |
| P7 | 15 minutes is a clinical judgment, not a fitted optimum — the whole gap distribution is published beside it | `02` | Figure A.1 |
| P8 | `t` = the index event's first administration's `admin_dttm` | `02` | the clock C, D, E all measure against |
| P9 | sub-analysis A enumerates all unordered pairs, same-agent included, not adjacent-only | `02` | 1,192 pairs |
| P10 | the 7-day cap is an overflow bin, never a filter | `02` | |
| P12 | sub-analysis D detects a transition, not a state; null is not imv; a block opening on imv counts | `03` | 484 transitions / 2,117 |
| P13 | the transition is computed on the waterfalled timeline, never raw `respiratory_support` | `03` | |
| P14 | no de-bouncing rule on transitions; `n_transitions_in_window` published instead | `03` | 484 of 484 carry exactly 1 |
| P15 | D and E share one inclusive predicate but use independent config bounds: `imv_window_before_minutes` (30), `imv_window_after_minutes` (60), and symmetric `sedation_window_minutes` (5) | `03` | |
| P16 | sedative list: `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl` — a covariate, not a detector | `03` | etomidate absent at this site |
| P17 | every sedative administration in the configured window is kept, not only the nearest per agent | `03` | `(index paralytic, administration)` pairs |
| P18 | superseded by P47's configured-unit contract | `01`, `02`, `03`, `04` | no conversion or relabeling |
| P19 | the timezone always comes from `config["timezone"]`; no code path consults the OS zone | everywhere | |
| P20 | every source `*_category` value stripped and lower-cased before matching/grouping; category pushdowns are normalized rather than exact raw-value filters | everywhere | `IMV`, `imv`, and ` IMV ` are equivalent |
| P21 / P23 | the disclosure boundary is row-level vs. aggregate; `publish()` refuses an identifier or a datetime column; nothing else is filtered | `utils/suppress.py` | see §6 |
| P41 | **added 2026-08-15** — dose distributions also published as full ECDFs keyed on the raw charted `(med_category, med_dose_unit)` pair; one row per distinct dose with `n_at_dose`, `n_cum`, `n_total`, `ecdf`. Amount units only. Additive to P18 | `02`, `03` | 118 + 81 rows; ketamine's `mcg`/`mg` split visible without conversion |
| P42 | superseded by P47 | `02`, `03`, `04` | no unit overrides |
| P43/P49 | configured-unit summaries publish mean/SD and median/IQR; configured strict bounds define medication eligibility; absolute-unit upper bounds do not apply to configured `/kg` units | `01`, `02`, `03`, `04` | positive finite doses; all eight bounds required in config |
| P44 | Table 1 adds DBP, per-device respiratory support, per-agent vasopressors, CLIF ICU types, and `compute_sofa_polars` over `[t0-24h,t0]` | `04`, `05` | missing SOFA components score 0; coverage is published separately |
| P45 | figure dataframes use `figure_<id>_df`; each plotted CSV and PNG shares `fig_<ID>__<description>`; support outputs use `stepNN__<description>`; Table 1 pooling names remain stable | everywhere | `07_artifact_manifest.py` rejects stale, missing or undeclared outputs and records checksums |
| P46 | block-first hospital/year counts plus additive normalized-dose outputs; dose weight is latest valid 20-300 kg current-hospital weight, otherwise prior-hospital weight within 28 days; local induction tiers retain integer pooling counts | `04` | B.2, E.4, E.5, G.1 and step 04 aggregate files; analytic cohort unchanged |
| P47 | one required config unit per medication; `given` only; exact unit matching before event construction; no conversion; configured `/kg` is already normalized | `01`, `02`, `03`, `04` | fentanyl allows `mcg`/`mcg/kg`; other agents allow `mg`/`mg/kg` |

---

## 8. Footguns

Things that have already bitten this codebase once.

**The clifpy timezone boundary.** `from_file(..., timezone=TIMEZONE)` normalizes naive,
UTC-aware, and other aware inputs to the configured site timezone. Downstream code must not
repeat that conversion. It removes the timezone while preserving clifpy's site-local wall clock:

Every raw `data_directory/clif_*` source, including the five inputs staged for SOFA in step 04,
crosses this boundary before application-level normalization, joining, or analysis. Projection
and category/identifier filters passed to clifpy remain IO pushdown. Pipeline-generated cache,
intermediate, staged, and published files are not raw CLIF sources and continue to use Polars IO.

```python
def to_site_naive(series):
    return series.dt.tz_localize(None)
```

The respiratory waterfall is the deliberate exception. Its input contract is UTC, it creates UTC
scaffold rows, and it returns UTC. Notebook `01` converts clifpy's site-aware timestamps to UTC
before the call, then converts the result back to `TIMEZONE` before stripping. Relabeling stripped
local time as UTC is forbidden because that changes the represented instant.

Pinned by `tests/test_clifpy_tz_boundary.py`. `to_site_naive` is defined locally in every notebook
that needs it, never imported — a bug in a shared datetime helper would corrupt every consumer
identically, and identical corruption is the hardest kind to see.

**The same trap on the way out: `datetime.timestamp()`.** The timezone always comes from
`config["timezone"]`, and no code path may ask the operating system. `run_all.sh` gets this
right already — its log directory is stamped with `date -u`, never the local shell's zone.
Calling `.timestamp()` on a site-*naive* value does exactly what the rule forbids: it interprets
the wall clock in the *machine's* zone. On a host set to US/Central holding US/Eastern data, 10
minutes across the November fall-back measures as **70**, which is enough to split one push of
paralytic into two index events and move `t` for everything downstream — the answer would then
depend on the laptop. Convert inside polars instead, which consults no zone at all:

```python
def epoch_minutes(column):
    return pl.col(column).dt.epoch("s") / 60.0
```

Pinned by `tests/test_collapse_agent_events.py`.

**`encounter_block` is not stable across runs.** It is seeded from a row index, so a re-extract
renumbers everything. Every artifact carries a `cohort_run_id`, and `03` asserts its input's run
id is single-valued and matches `01`'s — without that check, joining an index artifact from one
extract to a waterfall from another produces a table that is silently wrong: the ids match, the
rows are real, and they describe different patients.

**The stale-artifact hazard.** A leftover artifact from the superseded ventilator-anchored
design — `index_imv.parquet`, `method_*.parquet`, `method_*.json` — would still load, still
join, and would supply the wrong denominator without raising. `02` asserts on start that none of
them are present in `output/intermediate_phi/` before it writes anything of its own.

**A `write_csv` or a `json.dump` to `final_no_phi/` anywhere in `code/` is a bug.** Every
published analysis output is an aggregate and `utils/suppress.py` — `publish()` for CSV,
`publish_json()` for JSON — is the only route for those artifacts; it is what enforces §6's
boundary. The launchers' raw `logs/` subdirectory is the explicit exception. A notebook that
writes the directory directly bypasses the aggregate-output check entirely, whatever it thinks it
is writing.
