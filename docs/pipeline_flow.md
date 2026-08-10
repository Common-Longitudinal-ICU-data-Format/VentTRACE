# VentTRACE — how the pipeline works

A plain-language walkthrough of what each notebook does and why. The authoritative
definitions live in
[`superpowers/specs/2026-08-10-paralytic-index-design.md`](superpowers/specs/2026-08-10-paralytic-index-design.md);
this document is the map, not the territory. Where the two disagree, the spec wins.

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
   *did the device change*, within ±60 minutes?
4. Was a sedative charted in the same ±60 minutes, and at what dose?

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
│  C  gap distribution between index paralytics                    │
└───────┬──────────────────────────────────────────────────────────┘
        │  index_paralytic.parquet — one row per index paralytic
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 03_context.py           WHAT SURROUNDS IT                        │
│                                                                  │
│  D  first non-IMV → IMV transition in t ± 60 min                 │
│  E  sedatives charted in t ± 60 min, with dose                   │
└───────┬──────────────────────────────────────────────────────────┘
        │
   output/final_no_phi/   aggregates + figures, no row-level records
```

Three notebooks, run in order, each named for the CLIF table it opens rather than for a step
number that would drift as the design changes. `01` touches `hospitalization`, `adt` and
`respiratory_support`. `02` touches exactly one table —
`medication_admin_intermittent`, filtered to the three paralytics. `03` touches the waterfalled
device timeline from `01` and `medication_admin_intermittent` again, filtered to five sedatives.
`medication_admin_continuous` is never opened anywhere in this pipeline — every dose in this
study is a discrete charted push.

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
| ventilation | at least one raw charted `device_category == 'imv'` row |
| exclusion | tracheostomy in the first 24 h — `tracheostomy` truthy **or** `device_category == 'trach collar'` |

**Stitching comes first.** An ED presentation and the inpatient admission that follows it can
carry different `hospitalization_id`s. Hospitalizations less than 6 h apart for the same patient
are merged into one `encounter_block`, and every notebook after `01` keys on the block rather
than the raw id. Without this, a paralytic charted in the ED and a ventilator transition charted
after transfer would read as unrelated — one clinical act split by an administrative boundary.

**The waterfall makes the device record continuous.** Raw `respiratory_support` is charted
irregularly. `clifpy`'s `process_resp_support_waterfall` inserts hourly scaffold rows,
forward-fills `device_category`, and relabels a row with a null device to `imv` when the
ventilator settings on it look like a ventilator. Sub-analysis D reads this output, not the raw
table — see §5.

The funnel, as it stands for this cohort run:

```
   223,452 patients  (546,028 hospitalizations, source data)
        │
        │  step 0: keep patients with >=1 IMV row ever (efficiency pre-filter only)
        ▼
   31,533 patients   (110,320 hospitalizations)
        │
        │  stitch hospitalizations <6h apart  →  encounter_block
        ▼
   109,275 encounter blocks · 31,533 patients
        │  −0          age >= 18
        │  −0          date window (skipped — MIMIC)
        │  −20,561     >=1 ADT row in {ed, icu}
        ▼
   88,714
        │  −53,572     >=1 raw charted IMV row
        ▼
   35,142
        │  −1,125      trach signal in first 24h
        ▼
   34,017 ENCOUNTER BLOCKS · 31,124 PATIENTS   ← the analytic cohort
```

Two QC facts worth carrying: at most 4 hospitalizations were stitched into a single block, and
in 0.57% of blocks the first charted IMV row falls in a hospitalization *other than* the block's
first — direct, measured evidence for why stitching matters rather than an assumption that it
does.

**Outputs consumed downstream:** `cohort_index.parquet` (the join spine — `encounter_block`,
`patient_id`, `cohort_run_id`, `list_hospitalization_id`) and `cohort_resp_waterfall.parquet`
(the gap-free device timeline). `02` explodes `list_hospitalization_id` to reach the medication
table; `03` reads the waterfall for sub-analysis D. Neither notebook re-derives a block, and
neither ever names a raw `hospitalization_id` outside the one bridge step that reaches it (§4).

---

## 4. `02_index_paralytic.py` — the index event

Loads `medication_admin_intermittent`, filtered to `med_category ∈ {rocuronium,
succinylcholine, vecuronium}` and `mar_action_category ∈ {given, bolus}` — `bolus` is kept
alongside `given` because that is exactly how many EHRs chart a one-time IV push, which is
precisely what an intubating paralytic is. At this site: **1,585 rocuronium** and **575
vecuronium** administrations, both charted only as `given`. **Succinylcholine is absent from
this site's formulary** — not an error, just a fact every downstream rate is computed without.

The bridge from `hospitalization_id` to `encounter_block` is the one place this notebook is
allowed to name a hospitalization; the column is dropped the moment the join lands, so a
paralytic charted in the ED cannot fail to pair with one charted on the floor after transfer.

### A — the co-administration gap distribution

Every **unordered pair** of paralytic administrations within a block, same-agent pairs included,
computed **before** the fold and depending on nothing it decides — this is the evidence for the
15-minute boundary, not a consequence of choosing it. At this site: **1,192 pairs** total, and
the split is stark — **1,181 are same-agent** (a redose of the same drug) against **11
cross-agent** (two different paralytics). `rocuronium+rocuronium`'s own peak bin holds 234 pairs;
`rocuronium+vecuronium`'s peak holds 5. The pooled histogram cannot tell a redose from a
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
have two; the tail runs out to 12 in a single block. Co-administration inside an index event is
rare: only 42 of 2,117 (2.0%) fold more than one agent together.

Two facts are the design working, made visible in the published output rather than merely
asserted:

- **`max_span_min` is exactly 15.0 for both agents** — `index_paralytic_summary.csv`. That is
  the assertable invariant P6 bought by choosing anchor-and-close over transitive chaining: no
  index event, however many administrations it folds, can span more than the threshold that
  defines it.
- Doses, keyed on the charted unit and never converted: rocuronium is charted almost entirely in
  `mg` (n=1,582, median 50, IQR 50–100) with a handful in `mcg` (n=3, median 0.6) that a
  converted, pooled statistic would have silently mixed with the `mg` doses. Vecuronium: `mg`
  only, n=575, median 10 (IQR 6–10).

### C — the gap between index paralytics

The identical construction as A — all unordered pairs, the identical 15-bin grid — applied to
`t_dttm` instead of raw administration times. **1,110 inter-index pairs** are published, the
mass concentrated in the multi-day bins (234 beyond 7 days, 227 in 3–7 days) — the spacing of
genuinely separate paralytic episodes within a stay, not redosing.

**`index_gap_distribution.csv` has a count of zero in every bin below 15 minutes** — `0`,
`(0,1]`, `(1,2]`, `(2,5]`, `(5,10]`, `(10,15]`. That is not a data gap. It is the fold's defining
property made visible: an anchor at `t` closes at `t + 15` inclusive, so the next anchor is the
first administration *strictly after* `t + 15` — two index paralytics cannot be closer together
than the threshold that separates them, by construction. `02` asserts these six bins are empty
on every run; a non-zero count there would be a bug in the fold, not a finding.

**Output:** `index_paralytic.parquet`, written to `output/intermediate_phi/` — it carries
`t_dttm`, a real timestamp, so it is PHI and is never published. It is the spine `03` joins to.

---

## 5. `03_context.py` — what surrounds the index paralytic

Two questions over the identical ±60-minute window, sharing one predicate (P15) so that "the
vent was near" and "sedation was near" can never disagree at the boundary the way two
independent implementations of an interval test eventually would.

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
an intubation. This detects an **event**, not a **state**: "was IMV charted in ±60 min" is
satisfied by a patient who has been ventilated for a week and reports nothing about this
paralytic. A transition reports that the device actually changed.

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
other. What the airway was immediately before a transition (`imv_prior_device.csv`): nasal
cannula most often (129), then a block that opens on IMV with nothing charted before it at all
(111 — the patient arrived already-tubed), face mask (110), high-flow NC (64), NIPPV (40).

**No de-bouncing rule is applied** (P14) — the hourly scaffold can in principle manufacture a
spurious transition from a brief non-IMV blip, and `n_transitions_in_window` is published so
that effect is measurable rather than tuned away with a second unvalidated threshold. At this
site every one of the 484 detected transitions carries exactly `n_transitions_in_window = 1`; the
ambiguity P14 declines to suppress does not manifest in this run, and the published table is what
lets a reader confirm that rather than take it on trust.

### E — sedation in the same window

The identical ±60-minute predicate, applied to `medication_admin_intermittent` filtered to
`{midazolam, etomidate, ketamine, propofol, fentanyl}`. Sedation here is a **covariate** of the
index paralytic, not a detector — there is no `SED` method and no sedative-derived index event.
**Every** administration in the window is kept, not only the nearest per agent, because this
study publishes an offset histogram and deduplicating would delete the redosing pattern it
exists to show.

At this site, **etomidate is absent** — not an error, just a fact every rate below is computed
without. Of 2,117 index paralytics, **1,399 (66.1%) had at least one sedative charted** in the
window and **718 (33.9%) had none**. The most common charted sets: fentanyl+propofol (383),
propofol alone (324), fentanyl alone (242), fentanyl+midazolam (202), midazolam alone (128).

Dose statistics, keyed on `(med_category, med_dose_unit)` and never converted: fentanyl in `mcg`
(n=1,514, median 50, IQR 50–100), midazolam in `mg` (n=610, median 2, IQR 2–2 — a strikingly
fixed induction dose), propofol mostly in `mg` (n=1,427, median 20, IQR 10–40) with a small `mcg`
tail (n=6). Ketamine splits across `mcg` (n=8) and `mg` (n=5), each too small to pool and each
published as its own row rather than silently combined.

**What E's counts count: pairs, not administrations.** A block can hold several index
paralytics, and a single physical administration inside two overlapping ±60-minute windows
contributes a row to each. That is intentional — the administration genuinely happened within
±60 minutes of both — but it means `sedation_offset_distribution.csv` and `sedation_dose.csv`
publish **3,570 (index paralytic, administration) pairs**, not 3,570 distinct drug
administrations. The column is named `n_admin_windows` for exactly this reason, and reading it
as a count of doses given would overstate the true administration count by an unstated margin.

**Output:** `index_context.parquet` — `index_paralytic.parquet` plus D's and E's columns, one
row per index paralytic, written to `output/intermediate_phi/`. It carries raw timestamps
(`t_dttm`, `imv_transition_dttm`, per-dose `admin_dttm` inside `sedatives`) and is never
published in any form.

---

## 6. The disclosure boundary

**`output/intermediate_phi/` is row-level PHI and never leaves the site.** It holds real
timestamps and, upstream of the drop points described above, real identifiers — `cohort.parquet`,
`cohort_resp_waterfall.parquet`, `cohort_index.parquet`, `index_paralytic.parquet`,
`index_context.parquet`. Nothing in this directory is a deliverable. Copying a file out of it, by
any means, is a data breach.

**`output/final_no_phi/` is the only directory a site ever shares.** Everything in it is an
aggregate: a count, a rate, a quantile, keyed on a bin or a category — never a row that describes
one person.

**`utils/suppress.py`'s `publish()` is the only door between them**, imported by `02` and `03`
and nowhere else. It refuses to write (raises `AssertionError`, does not filter silently) a frame
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
| P2 | `01` is unchanged: adults, 2018–2025, ED/ICU, ever-IMV, no trach in 24h; stitch <6h apart | `01` | 34,017 blocks / 31,124 patients |
| P3 | paralytic list: `rocuronium`, `succinylcholine`, `vecuronium` (`cisatracurium`/`atracurium` excluded — maintenance agents, not induction) | `02` | 1,585 roc + 575 vec administered (succinylcholine absent at this site) |
| P4 | an administration is `mar_action_category ∈ {given, bolus}` | `02`, `03` | |
| P5 | analytic unit is `encounter_block`; `hospitalization_id` named only at the bridge, dropped the instant the join lands | `02`, `03` | |
| P6 | index paralytics formed by anchor-and-close at 15 min, never transitive chaining; inclusive at the boundary | `02` | `span_minutes <= 15` always; 2,117 index paralytics |
| P7 | 15 minutes is a clinical judgment, not a fitted optimum — the whole gap distribution is published beside it | `02` | Figure A.1 |
| P8 | `t` = the index event's first administration's `admin_dttm` | `02` | the clock C, D, E all measure against |
| P9 | sub-analysis A enumerates all unordered pairs, same-agent included, not adjacent-only | `02` | 1,192 pairs |
| P10 | the 7-day cap is an overflow bin, never a filter | `02` | |
| P12 | sub-analysis D detects a transition, not a state; null is not imv; a block opening on imv counts | `03` | 484 transitions / 2,117 |
| P13 | the transition is computed on the waterfalled timeline, never raw `respiratory_support` | `03` | |
| P14 | no de-bouncing rule on transitions; `n_transitions_in_window` published instead | `03` | 484 of 484 carry exactly 1 |
| P15 | D and E share one window predicate (±`context_window_minutes`, 60), implemented once | `03` | |
| P16 | sedative list: `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl` — a covariate, not a detector | `03` | etomidate absent at this site |
| P17 | every sedative administration in the window is kept, not only the nearest per agent | `03` | 3,570 (index paralytic, administration) pairs |
| P18 | `med_dose`/`med_dose_unit` are raw charted values, never converted; dose stats keyed on `(med_category, med_dose_unit)` | `02`, `03` | |
| P19 | the timezone always comes from `config["timezone"]`; no code path consults the OS zone | everywhere | |
| P20 | every `*_category` column lower-cased on load; every literal in the codebase written lower case | everywhere | |
| P21 / P23 | the disclosure boundary is row-level vs. aggregate; `publish()` refuses an identifier or a datetime column; nothing else is filtered | `utils/suppress.py` | see §6 |

---

## 8. Footguns

Things that have already bitten this codebase once.

**The pytz LMT trap.** `clifpy` returns timezone-aware columns whose `tzinfo` is
`DstTzInfo 'US/Eastern' LMT-1 day, 19:04:00 STD` — a *pre-standardisation* offset. Calling
`.dt.tz_localize(None)` drops the attached offset rather than the correct one and shifts
everything by about an hour, silently. The only correct move is:

```python
def to_site_naive(series):
    return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)
```

Pinned by `tests/test_clifpy_tz_boundary.py`. Defined locally in every notebook that needs it,
never imported — a bug in a shared datetime helper would corrupt every consumer identically, and
identical corruption is the hardest kind to see.

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

**A `write_csv` anywhere in `code/` other than inside `publish()` is a bug.** Every published
output is an aggregate and `utils/suppress.py`'s `publish()` is the only route into
`output/final_no_phi/` — it is what enforces §6's boundary. A notebook that calls `write_csv`
directly bypasses that check entirely, whatever it thinks it is writing.
