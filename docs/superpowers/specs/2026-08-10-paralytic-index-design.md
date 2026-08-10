# Paralytic-Indexed Airway Analysis — Design

**Project:** VentTRACE **Date:** 2026-08-10 **Status:** Design, approved for planning

**Supersedes:** `2026-08-04-intubation-method-comparison-design.md`, deleted in the same commit that adds this file. That document described a five-signal method-comparison study anchored on the ventilator record. This one describes a single-method study anchored on the paralytic. The two share a cohort and nothing else, so the old spec is removed rather than amended — its reasoning stays reachable in git history, where it cannot be mistaken for a description of code that runs.

------------------------------------------------------------------------

## 1. Purpose

The previous build asked whether several ways of saying "an intubation happened here" agreed with one another. It answered that question, and the answer was structurally constrained: every method was pinned to a t₀ the ventilator record had already fixed, so no method could disagree about *when*, only about whether its own drug appeared near a time it did not choose.

This build inverts the anchor. **The paralytic administration is the index event.** Everything else — the ventilator, the sedative — is measured against it.

The deliverable answers four questions:

1. **How are paralytic administrations distributed in time relative to one another?** Two paralytics two minutes apart are one clinical act; two paralytics two days apart are two. The distribution of those gaps is the evidence for where the boundary between them lies.
2. **Given a 15-minute boundary, how many distinct index paralytic events does a hospitalization have, and how far apart are they?**
3. **Does the ventilator record show a transition onto invasive ventilation around the index paralytic?** Not "was IMV charted" — a patient already ventilated satisfies that without anything having happened — but *did the device change*, within ±60 minutes.
4. **Was a sedative charted in the same ±60 minutes, and at what dose?**

There is no second method, no reference standard and no agreement statistic. There is one index definition and four sub-analyses hanging off it.

### Scope

- **Intubation-adjacent, not intubation-confirming.** The study describes what surrounds a paralytic. It does not adjudicate whether an intubation occurred.
- **The analytic unit is the index paralytic event**, keyed `{encounter_block}_P{n}`. A block contributes as many rows as it has index events.
- **Intermittent medications only.** `medication_admin_continuous` is never opened. Every dose in this study is a discrete charted push.
- **Encounters are stitched first** and every artifact carries `encounter_block`. See §5.
- **Testing target is MIMIC**, with the pipeline written to run at any consortium site via config.

------------------------------------------------------------------------

## 2. Decisions

Each decision below was made explicitly during design. Recorded with rationale so the choice is auditable and reversible. Numbering restarts at `P1`; where a decision carries over from the superseded design its reasoning is restated in full rather than cited, because the document that held it is gone.

| \# | Decision | Rationale |
|------------------------|------------------------|------------------------|
| P1 | **The paralytic is the index event. There is exactly one method.** `SED`, `PAIR`, `DEV` as a scored method, and `CPT` are all removed. | Set by the study lead. The comparison the old build ran is complete; what remains unanswered is what the paralytic itself marks. Keeping the other methods alongside would preserve machinery — the agreement tiers, the reference gate, the episode qualifier — that answers a question no longer being asked, and every one of those parts is coupled to an anchor that has moved. |
| P2 | **`01_cohort.py` is unchanged, including the ever-IMV pre-filter.** | Set by the study lead. The cohort stays adults · 2018–2025 · ED or ICU · ever on IMV · no tracheostomy in the first 24 h. The consequence is stated rather than left implicit: because every block already reached a ventilator, the sub-analysis D hit rate has a floor built into the cohort and **must not be read as specificity**. It is "given that this patient was ventilated at some point, did the device change around this paralytic" — a narrower and answerable question. |
| P3 | **The paralytic list is `rocuronium`, `succinylcholine`, `vecuronium`.** | Set by the study lead, unchanged from the superseded `PARA` method. These are the rapid-onset intubating agents. `cisatracurium` and `atracurium` are in the mCIDE `med_category` vocabulary and are deliberately excluded: they are overwhelmingly maintenance-blockade agents, and including them would turn sub-analysis A from a study of induction sequences into a study of ICU paralysis protocols. The exclusion is a scope choice, not a claim that those agents are never used to intubate. |
| P4 | **An administration is `mar_action_category ∈ {given, bolus}`.** | The mCIDE vocabulary permits `given · not_given · bolus · other`. The superseded design kept `given` alone, which carries a silent failure mode: a site charting every one-time IV push as `bolus` would report zero paralytics, and zero is indistinguishable from a site that gives none. `bolus` describes a drug that entered the patient and is precisely how an intubating paralytic is charted in many EHRs. Both are kept and the split is printed per agent, so the mix is a published fact rather than an assumption. |
| P5 | **The analytic unit is `encounter_block`, not `hospitalization_id`.** | An ED presentation and the inpatient admission that follows can carry different `hospitalization_id`s, so the paralytic is charted under one and the ventilator under the other. Under the old ventilator anchor that split cost a drug; under a paralytic anchor it costs the *device transition*, and sub-analysis D would report "no transition nearby" for an intubation that plainly happened. Stitching is what makes D answerable at all. `hospitalization_id` is named only inside the explode-and-drop bridge (§6.1) and dropped the moment the join lands. |
| P6 | **Index paralytics are formed by anchor-and-close at `collapse_gap_minutes` (15), never by transitive chaining.** The first unconsumed administration anchors an event; every administration within 15 minutes **of that anchor** joins it; the first administration beyond opens a new event. | Chaining has no bound. An agent redosed every fourteen minutes walks one event forward indefinitely — and its timestamp then sits hours from most of its own doses, which destroys the clock that sub-analyses C, D and E all measure against. Anchoring makes `span_minutes ≤ 15` an **assertable invariant** rather than a hope. The same rule, for the same reason, governed the agent-event fold in the superseded `05_method_pair.py`, and `tests/test_collapse_agent_events.py` already pins it. Inclusive at the boundary: an administration landing exactly on `t + 15 min` merges, so the parameter reads as "within 15 minutes". |
| P7 | **15 minutes is a clinical definition, not a measured optimum, and no empirical valley supports it.** Sub-analysis A publishes the whole gap distribution so the reader can see that. | The superseded build measured this directly and the data declined to answer. Co-administration of two *different* paralytics is a Δ ≤ 1 min phenomenon; from Δ = 2 minutes onward, different-agent and same-agent intervals ran at indistinguishable rates, with no trough anywhere to fit a threshold to. What 15 minutes buys is the paralytic *redosing* that would otherwise fragment one induction sequence into several index events. Because the threshold is a judgment, the evidence is published beside it (Figure A.1, with the threshold drawn on the plot) rather than summarised away into a single number. |
| P8 | **`t` — the study clock — is the `admin_dttm` of the index event's first administration.** Not the mean, not the last, not the nearest to anything. | Sub-analyses C, D and E all measure offsets, and offsets are meaningless unless every one of them is taken from the same instant. The first administration is the only choice that is both well defined for a single-dose event and stable under P6 — the anchor *is* the first administration by construction, so the clock and the fold cannot disagree. |
| P9 | **Sub-analysis A enumerates all unordered pairs within a block, same-agent pairs included, and does not restrict to adjacent administrations.** | Set by the study lead. Adjacent-only would miss `roc 12:00 … vec 12:10` whenever anything is charted between them, and the sub-15-minute mass is exactly where the threshold decision lives. The quadratic growth is accepted; §7.1 caps and asserts the total pair count so an unexpectedly dense site fails loudly instead of silently producing a differently-shaped histogram. |
| P10 | **The 7-day cap is a bin, not a filter.** Pairs separated by more than 7 days are counted in a `>7d` overflow bin. | A filter would make the histogram's own denominator depend on the cap, so two sites with different long-stay mixes would not be comparable even on the short bins. An overflow bin keeps the denominator whole and makes the discarded mass visible. |
| P11 | **The gap bin edges are a module constant, not a config key.** | They are an analysis grid, not a site parameter. A site that changed its bins would make its histogram non-comparable with every other site's, which is the one thing a multi-site distribution exists for. The superseded design used the same reasoning for its threshold sweep grid. |
| P12 | **Sub-analysis D detects a *transition*, not a state.** A waterfalled row is a transition when `device_category == 'imv'` and either there is no preceding row in the block or the preceding row's `device_category != 'imv'`. `null` is not `imv`, so `null → imv` is a transition; a block whose first row is `imv` has that row as a transition. | Set by the study lead, twice and explicitly. "Was IMV charted in ±60 min" is satisfied by a patient who has been on the ventilator for a week — it reports the state of the airway, not an event. A transition reports an event. The block-opens-on-IMV case counts because a patient whose record begins on a ventilator did have an airway secured; that it happened before the extract's first row is a property of the extract, not evidence that nothing occurred. Sub-analysis D publishes `prior_device_category` so this case is countable and separable at read time. |
| P13 | **The transition is computed on the waterfalled timeline, not on raw `respiratory_support`.** | Two reasons. **Mechanical:** a transition needs "the row before", and only the waterfall's gap-free hourly scaffold makes that well defined; on raw charting the previous non-null row may be many hours back. **Clinical:** the waterfall relabels a null-device row to `imv` when the ventilator settings on it look like a ventilator, and the superseded build measured that inference as landing at or before the human device entry in 100% of cases — exactly zero delay in 77.3% of episodes, but 55 min at p95 and 540 min at p99. An intubation is a high-stress event and nobody stops to fill in the device field; the ventilator's settings reach the chart the moment it is connected. The waterfall is therefore the record closer to the event. |
| P14 | **No de-bouncing rule is applied to transitions. `n_transitions_in_window` is published instead.** | The waterfall's hourly scaffold means a brief non-IMV blip manufactures a spurious transition, and the superseded design had a "sustained" test to suppress exactly that. Reintroducing it here would be a second threshold with no evidence behind it — the sub-analysis A distribution says nothing about device continuity — so the effect is measured and left visible rather than tuned away. A reader who wants a stricter reading can compute it from the published counts. |
| P15 | **Sub-analyses D and E share one window predicate, implemented once in `03_context.py`.** | This is the single exception to the no-shared-helper posture inherited from the old design, and it is narrow on purpose. D and E must ask about the *same* ±60 minutes; two independent implementations of an interval test drift at the boundary condition, and a one-row disagreement between "IMV was near" and "sedation was near" is invisible in aggregate and fatal to the joint reading. Detection logic stays separate; only the interval is shared. |
| P16 | **The sedative list is `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl`.** Sedation is a **covariate of the index paralytic, not a detector.** | Set by the study lead, unchanged from the superseded `SED` list. These are the induction agents, and the question the window asks is whether the paralytic was given as part of an induction or to a patient already sedated. Benzodiazepine and opioid adjuncts (`lorazepam`, `diazepam`, `morphine`, `hydromorphone`) were considered and declined: they would blur "induction happened here" with "this patient was comfortable", and `fentanyl` already straddles that line. |
| P17 | **Every sedative administration in the window is kept, not only the nearest per agent.** | The superseded design deduplicated by `med_category` because it was building a *rank ladder* and one patient redosed six times would have dominated a timing distribution of ranks. This study publishes an offset *histogram*, where every administration is a legitimate observation of when sedation was charted. Deduplicating would delete the redosing pattern the histogram is meant to show. |
| P18 | **`med_dose` and `med_dose_unit` are the raw charted values. No unit conversion, anywhere.** Dose statistics are keyed on `(med_category, med_dose_unit)`. | Normalising would hide unit heterogeneity that is itself worth measuring, and it cannot be done correctly without a weight the study does not carry. Keying on the unit means a site charting propofol in both `mg` and `mg/kg` produces two rows a reader can see, rather than one number that is silently wrong. |
| P19 | **The timezone always comes from `config["timezone"]`. No code path may consult the operating system's zone.** | Standing rule, carried forward intact because both of its failure modes are still live in this pipeline. **On the way in:** `.dt.tz_localize(None)` on a clifpy column drops the *attached* pytz LMT offset rather than the correct one and shifts every timestamp by about an hour without raising — fixed by `to_site_naive` (§4), pinned by `tests/test_clifpy_tz_boundary.py`. **On the way out:** `datetime.timestamp()` on a site-naive value re-attaches the *machine's* zone; on a host set to US/Central holding US/Eastern data, ten minutes across the November fall-back measures as seventy. A 60-minute artefact decides a 15-minute window outright — it splits one push of drug into two index paralytics, and the study's answer then changes with the machine. All minute arithmetic is done inside polars with `pl.col(c).dt.epoch("s") / 60.0`, which reads the stored wall-clock value and consults no zone at all. **One known exception remains, flagged rather than fixed:** `COHORT_RUN_ID` in `01_cohort.py` stamps `datetime.now()` in OS-local time. Nothing computes on it, but two sites' run ids are not comparable as timestamps. |
| P20 | **Every `*_category` column is lower-cased on load and every literal in the codebase is written in lower case.** Load-time filters passed to `from_file` enumerate every casing variant. | Case is the one vocabulary difference that fails *silently*. A mismatched category value does not raise; it matches zero rows, and a filter matching zero rows looks exactly like a site where the thing never happens. A `from_file` filter runs before any normalisation we control, which is why the variants are enumerated at that one boundary and nowhere else. |
| P21 | **Published cells below n = 10 are suppressed, and every figure is drawn from a published table.** | Carried forward. Drawing from the published table makes the suppression automatic instead of something reimplemented per plot, and removes the possibility of a figure disagreeing with the CSV beside it. A suppressed histogram bin is **dropped, not merged into its neighbour** — merging moves mass the reader cannot see move; dropping it and stating the dropped total in the caption keeps the omission visible. |
| P22 | **The all-pairs table of sub-analysis A is never persisted at row level.** Only bin counts are written. | A block with 40 paralytic administrations contributes 780 pairs. The raw pair list is large, fully re-derivable, and has no consumer — and an artifact with no consumer invites drift. |
| P23 | **The n ≥ 10 suppression rule is the one shared helper in the project.** It lives in `utils/suppress.py` and both `02` and `03` import it. | This is a deliberate exception to the local-duplication posture of §4, and the reason the exception is safe is that the failure modes point in opposite directions. Duplicating *analysis* logic risks correlated errors that look like agreement — the hazard the superseded design was built around, and which no longer exists here because there is nothing to agree with. Duplicating *suppression* logic risks one notebook publishing a cell the other would have withheld, which is a disclosure failure, not an analysis failure, and a disclosure failure must be impossible rather than merely unlikely. One implementation, one test, applied at every write. |

------------------------------------------------------------------------

## 3. Architecture

```
code/
  01_cohort.py            UNCHANGED — encounter stitch + cohort CONSORT + waterfall
  02_index_paralytic.py   paralytic administrations → sub-analyses A, B, C
                          → index_paralytic.parquet
  03_context.py           index paralytic ± 60 min → sub-analyses D, E
                          → index_context.parquet
utils/
  config.py               UNCHANGED
  suppress.py             NEW — the n ≥ 10 rule, imported by 02 and 03 (P23)
```

```
   CLIF parquet
        │
  01_cohort.py ............ encounter blocks + waterfalled device timeline
        │
        │  medication_admin_intermittent
        │    med_category ∈ {rocuronium, succinylcholine, vecuronium}
        │    mar_action_category ∈ {given, bolus}
        ▼
  02_index_paralytic.py
        │
        │  A  all-pairs gap distribution, log bins, 7d overflow
        │  B  anchor-and-close at 15 min  →  INDEX PARALYTICS
        │  C  gap distribution between index paralytics
        ▼
   index_paralytic.parquet ....... one row per index paralytic
        │
  03_context.py
        │
        │  D  first non-IMV → IMV transition in t ± 60   (waterfall)
        │  E  sedatives in t ± 60, with dose and unit
        ▼
   final_no_phi/ ................. aggregates + figures, n ≥ 10
```

The split falls where the **data sources change**, not where the sub-analyses happen to be numbered. Everything in `02` touches `medication_admin_intermittent` and nothing else, which makes sub-analyses A–C self-validating: a gap distribution needs no second table to be checked against, so a failure in D can never obscure whether the index set is right. `03` is the only notebook that joins the waterfall and the only one that loads a second medication list.

`index_paralytic.parquet` is the contract between them, specified in §6.2.

Only `01_cohort.py` knows that `hospitalization_id` exists as a unit. It resolves stitching once and publishes `list_hospitalization_id` in `cohort_index.parquet` as the bridge key; `02` explodes that list to reach the medication table and aggregates straight back to `encounter_block`. No notebook re-derives a block.

All notebooks are marimo notebooks stored as `.py`, run as `uv run python code/NN_name.py`. **Dataframe library:** polars throughout. The only pandas boundaries in the project are the two clifpy functions `stitch_encounters` and `process_resp_support_waterfall`, both inside `01`.

------------------------------------------------------------------------

## 4. Implementation constraints

The code must be readable by a clinician-researcher reviewing the definition, not only by its author. These are requirements, not preferences.

- **One logical step per marimo cell**, with a markdown cell above it stating what the step does in plain language.
- **Name intermediate columns explicitly** rather than chaining long expressions. A reviewer must be able to inspect `gap_minutes`, `is_anchor`, `index_paralytic_id`, `imv_offset_minutes` as real columns before they are collapsed into an aggregate.
- **Every filter prints its row, encounter-block and index-event count** before and after, so the funnel is visible while running, not only in the final artifact.
- **No silent defaults.** Every parameter that affects a result is read from `config.json` and echoed at the top of the notebook. The bin edges are the stated exception (P11) and are echoed too.
- **Every category filter must be provably non-empty.** A filter returning zero rows is the expected result at a site where the thing never happens and the symptom of a vocabulary mismatch where it happens constantly. Notebooks assert non-empty and print the distinct values seen, so the two cases are distinguishable without reading the data by hand.
- **`to_site_naive` is defined locally in each notebook that needs it**, not imported. A bug in a shared datetime helper corrupts every consumer identically, and identical corruption is the hardest kind to see. The duplication is the design. `utils/suppress.py` is the one deliberate exception and P23 states why it points the other way.

```python
def to_site_naive(series):
    """The only correct way to get a naive site-local timestamp out of clifpy."""
    return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)
```

- **All minute arithmetic goes through polars epoch conversion** (P19):

```python
def epoch_minutes(column):
    return pl.col(column).dt.epoch("s") / 60.0
```

------------------------------------------------------------------------

## 5. Cohort — `01_cohort.py`, unchanged

No change is made to `01`. It is described here only so this document is self-contained.

**Criteria**, applied to the stitched block:

| | |
|---|---|
| age | ≥ `min_age` (18) at admission |
| dates | `date_start` … `date_end` (2018-01-01 … 2025-12-31) |
| location | ED **or** ICU at some point in the block |
| ventilation | at least one **raw charted** `device_category == 'imv'` row |
| exclusion | tracheostomy in the first `trach_window_hours` (24) — `tracheostomy` truthy **or** `device_category == 'trach collar'` |

**Stitching comes first.** Hospitalizations less than `stitch_hours` (6) apart for the same patient are merged into an `encounter_block`, and every notebook after `01` keys on the block (P5).

**The waterfall makes the device record continuous.** `clifpy`'s `process_resp_support_waterfall` inserts hourly scaffold rows, forward-fills `device_category` unconditionally, and relabels a row with a null device to `imv` when the ventilator settings on it look like a ventilator. Sub-analysis D consumes exactly this output (P13).

Two properties of the waterfall are load-bearing downstream and are recorded so no later reader treats them as incidental:

- **`bfill` is inert for this pipeline.** The flag reaches only the numeric setters, after the device heuristics have already run. Flipping it changes ventilator settings and can never change which rows are IMV.
- **After the unconditional forward-fill, ~0.2% of waterfalled rows still carry a null device**, all of them before the block's first charted device. That residue is where `null → imv` transitions come from (P12).

**Outputs consumed by this study:** `cohort_index.parquet` (with `list_hospitalization_id`, `patient_id`, `cohort_run_id`) and `cohort_resp_waterfall.parquet`.

------------------------------------------------------------------------

## 6. The index paralytic — `02_index_paralytic.py`

### 6.1 The explode-and-drop bridge

CLIF tables are keyed on `hospitalization_id`; this study is keyed on `encounter_block`. The bridge is the **only** place `02` may name a hospitalization, and the column is dropped the moment the join lands.

```
cohort_index.parquet
    explode list_hospitalization_id
        → bridge(hospitalization_id, encounter_block, patient_id)
            → filter medication_admin_intermittent at load on these ids
                → join → DROP hospitalization_id
                    → everything below is per block
```

The drop is a requirement, not tidiness. If `hospitalization_id` survived into the gap computation, sub-analysis A would silently revert to the unstitched unit and a paralytic in the ED would never pair with one on the floor. Dropping the column makes that mistake impossible to write rather than merely discouraged. `02` asserts the column is absent after the join.

### 6.2 The administration set

One definition, used by sub-analyses A and B alike:

```
medication_admin_intermittent
  hospitalization_id ∈ cohort            (load-time filter)
  med_category ∈ {rocuronium, succinylcholine, vecuronium}       P3
  mar_action_category ∈ {given, bolus}                           P4
  columns: hospitalization_id, admin_dttm, med_category,
           mar_action_category, med_dose, med_dose_unit
```

Categories are lower-cased immediately after load (P20). `med_category` is **not** filtered at load time — the list is three values, and filtering after lower-casing is both cheaper to reason about and immune to the casing hole, since our own filter then runs on a column we normalised ourselves.

The notebook prints a `value_counts` per agent and per `mar_action_category`, and names any listed agent that is absent. An absent agent is **not an error** — succinylcholine in particular is missing from many formularies — but every rate below is then computed without it, and that must be visible. The notebook asserts only that the set is non-empty as a whole.

### 6.3 Anchor and close

Per `encounter_block`, walking forward in time:

```
sort by (admin_dttm, med_category)
    ↑ med_category breaks an exact-timestamp tie alphabetically,
      so the output is byte-identical across runs

first unconsumed row              →  ANCHOR.  t := its admin_dttm
every row with admin_dttm ≤ t + collapse_gap_minutes  →  joins this event
first row beyond that             →  new ANCHOR
```

Worked example, `collapse_gap_minutes = 15`:

```
 12:00  rocuronium        ANCHOR      index #1, t = 12:00
 12:10  vecuronium        ≤ 12:15     joins #1
 12:20  succinylcholine   > 12:15     ANCHOR   index #2, t = 12:20
 12:32  rocuronium        ≤ 12:35     joins #2
 09:14  (next day) roc    ANCHOR      index #3

 3 index paralytics.  spans 10, 12, 0 minutes.
```

Note what anchoring buys: the 12:20 administration is within 15 minutes of the 12:10 one, and a transitive rule would have merged all three. Under P6 it does not, and `span_minutes ≤ 15` holds for every event without exception.

Every administration belongs to **exactly one** index event. There is no eligibility filter at this step — the index set is a partition of the administration set, and `Σ n_admins` over all index events equals the administration count. `02` asserts that.

### 6.4 `index_paralytic.parquet` — the contract

One row per index paralytic, written to `output/intermediate_phi/`.

| column | type | |
|---|---|---|
| `index_paralytic_id` | str | `{encounter_block}_P{n}`, `n` in time order from 1 |
| `encounter_block` | int | |
| `patient_id` | str | |
| `cohort_run_id` | str | provenance; `03` asserts it matches |
| `p_num` | int | 1 = first index paralytic of the block |
| `t_dttm` | datetime, site-naive | **the study clock** (P8) |
| `n_admins` | int | administrations folded into this event |
| `span_minutes` | float | last − first; **asserted ≤ 15** |
| `is_coadmin` | bool | `n_admins > 1` |
| `agents` | list\[str\] | sorted distinct `med_category` |
| `n_agents` | int | |
| `agent_label` | str | `agents` joined with `+`, e.g. `rocuronium+vecuronium` |
| `doses` | list\[struct\] | one per administration: `med_category`, `med_dose`, `med_dose_unit`, `mar_action_category`, `offset_minutes` |

`offset_minutes` inside `doses` is measured from `t_dttm`, so it is `0.0` for the anchor and in `(0, 15]` for the rest.

`agent_label` is sorted alphabetically so one combination is one row of any downstream table rather than several orderings of itself.

**Assertions on write:** `index_paralytic_id` unique; `span_minutes ≤ collapse_gap_minutes` for every row; `Σ n_admins` equals the administration count; `p_num` contiguous from 1 within each block; no null in any non-`doses` column.

------------------------------------------------------------------------

## 7. Sub-analyses

### 7.0 The shared gap-bin grid

Used identically by A and C, so the two histograms are directly comparable (P11).

```python
GAP_BIN_EDGES_MIN = [0, 1, 2, 5, 10, 15, 30, 60,
                     120, 360, 720, 1440, 4320, 10080]
GAP_BIN_LABELS = ["0", "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]",
                  "(15,30]", "(30,60]", "(1,2]h", "(2,6]h", "(6,12]h",
                  "(12,24]h", "(1,3]d", "(3,7]d", ">7d"]
```

An exact zero gap gets its own bin — two agents charted on the same minute is the single most informative value in the distribution and must not be pooled with "under a minute". Every other bin is left-open, right-closed. The final bin is the overflow (P10): pairs beyond 10,080 minutes are counted there, never dropped.

### 7.1 A — the co-administration gap distribution

For every `encounter_block`, every **unordered pair** of administrations in the set of §6.2, including same-agent pairs (P9):

```
gap_minutes = | epoch_minutes(i) − epoch_minutes(j) |     for all i < j
```

Published three ways:

| table | rows |
|---|---|
| `coadmin_gap_distribution.csv` | bin × `{pooled, same_agent, cross_agent}` → n |
| `coadmin_gap_by_pair.csv` | bin × unordered agent pair → n. The pair label is the two agents sorted alphabetically and joined with `+` — `rocuronium+vecuronium`, never `vecuronium+rocuronium` — so one pair is one row rather than two orderings of itself. Same-agent pairs appear as `rocuronium+rocuronium`. |
| `paralytic_admin_summary.csv` | agent × `mar_action_category` → n administrations, n blocks, n patients |

The same/cross split is the point of the table. `rocuronium → rocuronium` at 3 minutes is a redose; `rocuronium → succinylcholine` at 3 minutes is a co-administration. The pooled histogram cannot distinguish them, and they justify the 15-minute boundary for different reasons (P7).

**Figure A.1** — histogram of `gap_minutes` on the bin grid, log-spaced x-axis, a marked vertical rule at 15 minutes, the same/cross split shown as two series. Produced **before** B, and depending on nothing B computes, so it reads as evidence for the threshold rather than as a consequence of it.

**The O(n²) guard.** A block with *n* administrations contributes *n(n−1)/2* pairs. `02` prints the maximum `n` per block, the total pair count, and the ten densest blocks' counts; it then asserts

```python
MAX_TOTAL_PAIRS = 10_000_000
```

**This is a memory ceiling, not a clinical one, and it is stated as such so nobody reads it as a study parameter.** Ten million pairs of two timestamps and two labels is roughly a 300 MB polars frame — comfortable, and about three orders of magnitude above what MIMIC's paralytic density implies. A site that trips it has charting unlike anything this design was checked against, and the right response is to look at the ten densest blocks the notebook just printed and decide deliberately, not to raise the constant. The histogram it would otherwise produce would be dominated by a handful of long-stay patients, which is a silent failure the assertion converts into a loud one.

### 7.2 B — index paralytics

Defined in §6.3–6.4. Published aggregates:

| table | contents |
|---|---|
| `index_paralytic_summary.csv` | n index paralytics; n blocks; n patients; % `is_coadmin`; `n_admins` distribution; `span_minutes` p50/p90/max; counts by `agent_label` |
| `index_paralytic_dose.csv` | `med_category` × `med_dose_unit` → n, median, p25, p75 |

Dose statistics are keyed on the unit and never converted (P18).

### 7.3 C — the gap between index paralytics

The same construction as A, applied to index paralytics instead of raw administrations: all unordered pairs of `t_dttm` within a block, the identical bin grid, the identical overflow bin.

| table | contents |
|---|---|
| `index_gap_distribution.csv` | bin → n pairs |
| `index_per_block.csv` | index paralytics per block → n blocks |

**Figure C.1** overlays C on A using the same bins. By construction C has **zero mass in every bin up to and including `(10,15]`** — and the bound is strict, not approximate. An anchor at `t` closes at `t + 15` inclusive, so the next anchor is the first administration *strictly after* `t + 15`; consecutive index paralytics are therefore always more than 15 minutes apart, and every non-consecutive pair is wider still. `02` asserts those six bins are empty. A non-zero count there is a bug in the fold, not a finding, and the assertion is the cheapest possible test that P6 was implemented as written.

### 7.4 D — the non-IMV → IMV transition

Source: `cohort_resp_waterfall.parquet` (P13). Per `encounter_block`, sorted by `recorded_dttm`:

```
a row is a TRANSITION when
      device_category == 'imv'
  AND ( no preceding row exists in the block
        OR preceding device_category != 'imv' )

null is not imv  →  null → imv  IS a transition
block opens on imv  →  that first row IS a transition
imv → imv  →  not a transition
```

For each index paralytic, scan `[t − context_window_minutes, t + context_window_minutes]` — inclusive at both ends — and keep the **earliest** transition inside it.

Recorded per index paralytic:

| column | |
|---|---|
| `imv_transition` | bool |
| `imv_transition_dttm` | datetime, null when false |
| `imv_offset_minutes` | signed, `transition − t`; negative means the vent came first |
| `prior_device_category` | the device immediately before the transition; **null when the block opens on IMV** |
| `n_transitions_in_window` | ≥ 1 when `imv_transition`; the de-bouncing evidence (P14) |
| `no_transition_reason` | null when `imv_transition`, else one of below |

`no_transition_reason` ∈ `{already_on_imv, no_transition_in_window, no_device_record}`:

- `already_on_imv` — the most recent waterfall row at or before `t` carries `device_category == 'imv'` (a backward as-of join on `recorded_dttm`, keyed on `encounter_block`), and no transition occurs anywhere in the window.
- `no_transition_in_window` — the patient is not on IMV at `t` and no transition occurs in the window either.
- `no_device_record` — the block has no waterfall row at or before `t`. Expected to be rare; printed with a count.

| table | contents |
|---|---|
| `imv_transition_summary.csv` | `imv_transition` × `no_transition_reason` → n; and `prior_device_category` → n among transitions |
| `imv_offset_distribution.csv` | 5-minute bins across `[−60, +60]` → n |

**Figure D.1** — histogram of `imv_offset_minutes`, 5-minute bins, zero line marked, drawn from `imv_offset_distribution.csv`.

Offset bins are `[−60,−55)`, … , `[55, 60]` — 24 bins, left-closed and right-open except the last, which is closed so an offset of exactly `+60` has a home.

**Assertions:** `|imv_offset_minutes| ≤ context_window_minutes` on every recorded transition; `imv_transition` true implies `imv_transition_dttm` and `imv_offset_minutes` non-null and `no_transition_reason` null, and false implies the converse.

### 7.5 E — sedation in the same window

The identical window predicate as D (P15). Source: `medication_admin_intermittent`, `med_category ∈ {midazolam, etomidate, ketamine, propofol, fentanyl}` (P16), `mar_action_category ∈ {given, bolus}` (P4). **Every** administration in the window is kept (P17).

Recorded per index paralytic:

| column | |
|---|---|
| `any_sedative` | bool |
| `n_sedative_admins` | int |
| `sedative_agents` | list\[str\], sorted distinct |
| `nearest_sedative_med` | agent of the administration with the smallest \|offset\| |
| `nearest_sedative_offset_min` | signed |
| `sedatives` | list\[struct\]: `med_category`, `admin_dttm`, `offset_minutes`, `med_dose`, `med_dose_unit`, `mar_action_category` |

Ties on \|offset\| for `nearest_sedative_med` break alphabetically by `med_category`, so the column is byte-identical across runs.

| table | contents |
|---|---|
| `sedation_summary.csv` | `any_sedative` → n; `sedative_agents` set → n; `n_sedative_admins` distribution |
| `sedation_offset_distribution.csv` | 5-minute bins across `[−60, +60]` × `med_category` → n |
| `sedation_dose.csv` | `med_category` × `med_dose_unit` → n, median, p25, p75 |

**Figure E.1** — offset histogram across ±60 min, one series per agent, drawn from `sedation_offset_distribution.csv`. **Figure E.2** — dose distribution per `(med_category, med_dose_unit)`, drawn from `sedation_dose.csv`.

------------------------------------------------------------------------

## 8. Outputs and data security

```
output/intermediate_phi/          row-level, never leaves the site
  cohort_index.parquet            from 01, unchanged
  cohort_resp_waterfall.parquet   from 01, unchanged
  index_paralytic.parquet         §6.4                          (02)
  index_context.parquet           index_paralytic + D + E cols  (03)

output/final_no_phi/              shareable aggregates, n ≥ 10
  paralytic_admin_summary.csv       A
  coadmin_gap_distribution.csv      A
  coadmin_gap_by_pair.csv           A
  index_paralytic_summary.csv       B
  index_paralytic_dose.csv          B
  index_gap_distribution.csv        C
  index_per_block.csv               C
  imv_transition_summary.csv        D
  imv_offset_distribution.csv       D
  sedation_summary.csv              E
  sedation_offset_distribution.csv  E
  sedation_dose.csv                 E
  figures/  A.1  C.1  D.1  E.1  E.2
```

**Rules**, all carried forward (P21):

- No `patient_id`, no row-level records, no raw data files in `final_no_phi/`.
- Every reported cell with n < 10 is suppressed.
- Suppression is applied by `utils/suppress.py`, imported by both `02` and `03` (P23). It is the only shared code in the project.
- Every figure is drawn from a published table, so suppression propagates to the plot automatically.
- A suppressed histogram bin is dropped, not merged; the caption states the dropped total.
- Every artifact carries `cohort_run_id`. `03` asserts its input's run id is single-valued and matches its own. Without that check, joining an index artifact from one extract to a waterfall from another produces a table that is silently wrong — the ids match, the rows are real, and they describe different patients. `encounter_block` is seeded from a row index and is **not stable across re-extracts**.

------------------------------------------------------------------------

## 9. Configuration

`config/config_template.json` after the overhaul:

```json
{
    "site_name": "Your_Site_Name",
    "data_directory": "./clif_demo",
    "filetype": "parquet",
    "timezone": "US/Eastern",
    "output_directory": "./output",
    "collapse_gap_minutes": 15,
    "context_window_minutes": 60,
    "stitch_hours": 6,
    "trach_window_hours": 24,
    "min_age": 18,
    "date_start": "2018-01-01",
    "date_end": "2025-12-31"
}
```

Removed: `window_hours` (the old t₀ ± 3 h detection window), `episode_gap_hours` (`02_index_imv.py`'s lookback), `pair_gap_hours` (`05_method_pair.py`'s pairing threshold), `infusion_prep_minutes` (the continuous-table reclassification, and the continuous table is gone).

`collapse_gap_minutes` keeps its name and its value. **Changing it is a re-run of `02`, never a post-hoc filter** — a wider fold produces a *different* index set, not a superset of the current one, because merging two events changes which administration anchors the result and therefore moves `t` for everything downstream.

`GAP_BIN_EDGES_MIN`, `GAP_BIN_LABELS` and `MAX_TOTAL_PAIRS` are module constants in `02`, not config keys (P11).

------------------------------------------------------------------------

## 10. Testing

```
keep      tests/test_clifpy_tz_boundary.py
              the pytz LMT trap. Unchanged — P19 still depends on it.

retarget  tests/test_collapse_agent_events.py
              already pins anchor-and-close and the DST epoch-minutes
              shortcut for the deleted 05. Repoint at 02's index builder,
              which is the same rule on a different agent list.

retarget  tests/test_e7_suppression.py  →  tests/test_min_cell_suppression.py
              Tier E.7 is gone. Repoint at utils/suppress.py (P23): cells
              at n = 9, 10 and 11; a frame where every cell is suppressed;
              and the dropped-total that captions report.

new       tests/test_pair_gaps.py
              all-pairs enumeration on a hand-built block; bin edge
              behaviour at 0, 1, 15, 60, 1440 and 10080 minutes; the
              >7d overflow bin; the same/cross split.

new       tests/test_imv_transition.py
              the four cases of P12 — non-imv→imv, null→imv,
              block-opens-on-imv, imv→imv — plus first-transition-in-window
              selection when several transitions fall inside ±60, and each
              of the three no_transition_reason values.
```

`run_all.sh` becomes `STEPS=(01_cohort 02_index_paralytic 03_context)`.

------------------------------------------------------------------------

## 11. Out of scope

- **Agreement statistics.** No kappa, no Jaccard, no 2×2 tables, no concordance counts. There is one method.
- **Reference standards.** No CPT, no ICD.
- **Continuous medications.** No infusion-prep reclassification, no `during_infusion` band, no threshold sweep.
- **Sedation as a detector.** Sedation is a covariate of the index paralytic (P16); no `SED` method is defined and no sedative-derived index event exists.
- **Extubation, duration of ventilation, and outcomes.** Not touched.
- **Reintubation linkage beyond `p_num`.** The design counts a block's index paralytics in order and says nothing about the relationship between them beyond the gap distribution of §7.3.
- **Cohort changes.** `01` is unchanged (P2), including the ever-IMV pre-filter and its consequence for how sub-analysis D may be read.

------------------------------------------------------------------------

## 12. Removal manifest

Deleted with this document, since the document is what supersedes it:

```
docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md
```

Deleted during implementation, as the first step of the plan — the pipeline must never be in a state where a notebook reads an anchor that no longer exists:

```
code/02_index_imv.py
code/03_method_sedative.py
code/04_method_paralytic.py
code/05_method_pair.py
code/06_reference_cpt.py
code/07_agreement.py
```

Added: `utils/suppress.py` (P23), `code/02_index_paralytic.py`, `code/03_context.py`.

Rewritten: `docs/pipeline_flow.md`, `run_all.sh`, `config/config_template.json`, `config/config.json`. The two config files are edited key-for-key per §9; `config/config.json` keeps this site's `site_name`, `data_directory` and `timezone` values untouched.

Superseded plans under `docs/superpowers/plans/` are left in place — they are historical records of completed work, not descriptions of current code, and the spec they implemented is recoverable from git.

Stale artifacts under `output/intermediate_phi/` from the previous design (`index_imv.parquet`, `method_*.parquet`, `method_*.json`) are **asserted absent** by `02` on write, for the same reason the old `04` asserted against a pre-D35 file: a stale artifact still loads, still joins, and supplies the wrong denominator without raising.
