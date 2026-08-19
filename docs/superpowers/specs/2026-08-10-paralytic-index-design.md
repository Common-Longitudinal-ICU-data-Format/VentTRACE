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
3. **Does the ventilator record show a transition onto invasive ventilation around the index paralytic?** Not "was IMV charted" — a patient already ventilated satisfies that without anything having happened — but *did the device change*, within the configured ±60-minute IMV window.
4. **Was a sedative charted within the configured ±5-minute sedation window, and at what dose?**

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
| P2 | **AMENDED 2026-08-17: cohort entry requires at least one qualifying paralytic administration, not a raw IMV row.** The patient-level efficiency pre-filter and the displayed block-level inclusion both use P3/P4 plus P25: rocuronium, succinylcholine, or vecuronium; `given`/`bolus`; non-rate unit. | Set by the study lead because a patient intubated immediately before death may receive a paralytic but never have IMV charted. Applying the change only to the displayed CONSORT row would be false: the earlier IMV-ever pre-filter would still remove that patient invisibly. Respiratory charting is context and QC; its absence becomes `no_device_record`, not cohort exclusion. |
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
| P15 | **AMENDED 2026-08-18: sub-analyses D and E share one inclusive symmetric-window predicate but supply independent configured widths.** D uses `imv_window_minutes = 60`; E uses `sedation_window_minutes = 5`. | Set by the study lead. Sharing boundary semantics prevents one implementation from excluding an endpoint the other includes, while independent parameters prevent a change to the sedation definition from changing IMV detection. Detection logic and histogram grids remain separate. |
| P16 | **The sedative list is `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl`.** Sedation is a **covariate of the index paralytic, not a detector.** | Set by the study lead, unchanged from the superseded `SED` list. These are the induction agents, and the question the window asks is whether the paralytic was given as part of an induction or to a patient already sedated. Benzodiazepine and opioid adjuncts (`lorazepam`, `diazepam`, `morphine`, `hydromorphone`) were considered and declined: they would blur "induction happened here" with "this patient was comfortable", and `fentanyl` already straddles that line. |
| P17 | **Every sedative administration in the window is kept, not only the nearest per agent.** | The superseded design deduplicated by `med_category` because it was building a *rank ladder* and one patient redosed six times would have dominated a timing distribution of ranks. This study publishes an offset *histogram*, where every administration is a legitimate observation of when sedation was charted. Deduplicating would delete the redosing pattern the histogram is meant to show. |
| P18 | **AMENDED 2026-08-10 by the study lead: doses are standardised with clifpy, not published raw.** `clifpy.utils.unit_converter.convert_dose_units_by_med_category` converts every intermittent dose to one preferred unit per `med_category` — `mcg` for fentanyl, `mg` for every other agent in this study, matching how each is conventionally charted. Dose statistics are then keyed on `med_category` **alone**. The raw `med_dose_unit` mix is not discarded: it is published separately, as a count of administrations per `(med_category, med_dose_unit)` with no dose statistics attached. **Extended, not superseded, by P41 (2026-08-15):** the converted median/IQR published here stays exactly as it is; the full ECDF on the *raw* charted unit is published alongside it. | **Supersedes the original decision, which forbade conversion anywhere.** That decision rested on two objections and the amendment answers both. *Heterogeneity would be hidden* — it is not; it moves to a table whose only job is to show it, which is a better instrument than a dose statistic that happens to be split by unit. *It cannot be done correctly without a weight the study does not carry* — clifpy takes `weight_kg` from the vitals table for `/kg` dosing, and for this study the question does not arise: every unit observed is a plain amount (`mg`, `mcg`), because only `medication_admin_intermittent` is opened and a discrete push is charted as a quantity, not a rate. A site that charts a paralytic per kilogram must supply vitals or the notebook fails loudly rather than converting on a missing weight. The concrete cost of the original decision: propofol was published as `mg, n = 1,427` beside `mcg, n = 6`, two rows a reader must combine by hand and cannot, since 6 doses charged in micrograms are almost certainly a charting artifact rather than a thousand-fold smaller dose. Keying on the unit made a data-quality signal look like a clinical finding. One consequence worth stating: standardising folds every small unit-fragment group into its parent — propofol `mcg` n = 6 into propofol n = 1,433, rocuronium `mcg` n = 3 into n = 1,585 — so the published quartiles are no longer computed over groups small enough for the triple to be inverted back to individual charted doses. That was an open concern under P21 and this decision closes it as a side effect rather than by suppression. |
| P19 | **The timezone always comes from `config["timezone"]`. No code path may consult the operating system's zone.** | `clifpy.from_file(..., timezone=TIMEZONE)` normalizes every recognized datetime to the configured site timezone. `to_site_naive` then strips that timezone with `.dt.tz_localize(None)` and does not convert it again. The respiratory waterfall is the one deliberate conversion boundary: its contract requires UTC and its output remains UTC, so `01` converts site-aware input to UTC before the call and converts the result back to `TIMEZONE` before stripping. `tests/test_clifpy_tz_boundary.py` pins both contracts. **On the way out:** `datetime.timestamp()` on a site-naive value re-attaches the *machine's* zone; on a host set to US/Central holding US/Eastern data, ten minutes across the November fall-back measures as seventy. All minute arithmetic is therefore done inside polars with `pl.col(c).dt.epoch("s") / 60.0`, which reads the stored wall-clock value and consults no zone at all. **One known exception remains, flagged rather than fixed:** `COHORT_RUN_ID` in `01_cohort.py` stamps `datetime.now()` in OS-local time. Nothing computes on it, but two sites' run ids are not comparable as timestamps. |
| P20 | **Every source `*_category` value is stripped and lower-cased before filtering, matching, joining, or grouping; every categorical literal is lower case.** Exact raw-category filters are not passed to `from_file`. The initial whole-site medication scan, where no cohort IDs exist yet, uses an equivalent whitespace-regex/lowercase DuckDB pushdown and then applies the same in-memory canonicalization. | Case and surrounding whitespace are vocabulary differences that fail *silently*: `IMV`, `imv`, and ` IMV ` must mean the same thing. Enumerating lower/title/upper variants is not genuinely case-insensitive and cannot cover whitespace or arbitrary mixed case. Normalizing before selection prevents a zero-row filter from looking like a site where the event never occurs. |
| P21 | **The disclosure boundary is row-level versus aggregate, not cell size. An aggregate cell is published at its true value, including counts of 1 to 9.** Every figure is still drawn from a published table. | **Amended 2026-08-10 by the study lead, superseding the n ≥ 10 cell rule this decision originally carried forward.** A binned count is a property of a bin, not of a person: "6 propofol administrations were charted in mcg" names nobody, and the cohort it is drawn from is already defined by a published inclusion rule. The threshold was inherited from a superseded design in which tables were far narrower. What it bought — deniability for a single cell — it paid for in a machinery of secondary suppression (see P24, withdrawn) that consumed three review rounds, produced three distinct subtraction leaks of its own, and in closing the third still delivered only a *bound* on the withheld value rather than the deniability it advertised. **A rule that must be defended by a second rule that must be defended by a third is not protecting anything; it is generating work.** What actually protects the patient is the prohibition that has never moved: nothing row-level, no `patient_id`, no record that describes one person, ever leaves the site. That is P23's job now. Drawing every figure from the published table is retained on its own merit — it removes the possibility of a figure disagreeing with the CSV beside it. |
| P22 | **The all-pairs table of sub-analysis A is never persisted at row level.** Only bin counts are written. | A block with 40 paralytic administrations contributes 780 pairs. The raw pair list is large, fully re-derivable, and has no consumer — and an artifact with no consumer invites drift. |
| P23 | **The row-level prohibition is the one shared helper in the project, and it is enforced mechanically at every write.** `utils/suppress.py` keeps its name and its role as the single route into `final_no_phi/`; what it enforces is now the P21 boundary. `publish()` refuses any frame carrying an identifier column — `patient_id`, `hospitalization_id`, `encounter_block`, `p_num`, or any column whose name ends in `_id`, with `cohort_run_id` the single exemption because it is a provenance stamp shared by every row of an extract and identifies nobody. It also refuses any frame carrying a **datetime column**: an aggregate has no timestamp, and every row-level artifact in this study does. | This is a deliberate exception to the local-duplication posture of §4, and the reason the exception is safe is that the failure modes point in opposite directions. Duplicating *analysis* logic risks correlated errors that look like agreement — the hazard the superseded design was built around, and which no longer exists here because there is nothing to agree with. Duplicating the *disclosure* check risks one notebook writing a file the other would have refused, which is not an analysis failure and must be impossible rather than merely unlikely. One implementation, one test, applied at every write. The check is now a column-name guard rather than a cell-count filter, which makes it both cheaper and — unlike the threshold it replaces — not defeatable by arithmetic across two files. The count-column requirement this decision originally carried was removed on review: it simultaneously **blocked** a legitimate key/value QC table (`cohort_qc.csv`, columns `stat,value`) and **failed to block** the thing it was written for — dropping the four identifier columns from `index_context.parquet` leaves a 2,117-row row-level frame that still carries `n_admins`, so it satisfied a check for "has a column starting with `n_`" while being pure row detail. The datetime guard catches that construction (`t_dttm`), costs nothing, and is not defeatable by adding a column. |
| P24 | **WITHDRAWN 2026-08-10, together with the cell-size rule it existed to defend (P21).** Secondary suppression — classifying every `gap_bin` into FULL / POOLED_ONLY / NONE so that two files sharing a key could not be differenced to recover a withheld cell — is removed in full, along with `coadmin_gap_pooled.csv`, the per-agent dose-leak guard in `03`, and the dropping of `n_administrations` from `paralytic_admin_summary.csv` (restored). | The decision is kept in the record rather than deleted, because what it found is still true and is the reason P21 moved. Three separate subtraction leaks were discovered in this design, each by a different construction and none visible in the code: `n_same_agent` minus its published `agent_pair` components; `paralytic_admin_summary.csv`'s `n_administrations` minus `index_paralytic_dose.csv`'s per-unit rows; and an agent's summed offset bins minus its published dose row. Each was closed, and closing the third still left the withheld value bounded to five candidates rather than nine, because the suppression algorithm is itself published and a reader can exclude the counts it would never have chosen. **The generalisable finding: a suppression threshold applied to a set of tables that share keys is not a local property of any one table, and cannot be made one.** Withholding a cell in a table whose margins are published does not remove information, it relocates it — and the relocation is invisible to the person applying the rule. Having to reason about it at all was the cost; under P21 the cost is zero and the protection that matters (P23) is a column-name check that no arithmetic can defeat. |
| P25 | **Medication rows whose dose unit is a rate are excluded before event construction and window matching.** Both `02` and `03` report the skipped count and aggregate `(med_category, med_dose_unit)` breakdown. | `medication_admin_intermittent` represents discrete administrations. A unit such as `mcg/hr` describes an infusion rate, cannot be converted to an amount without duration, and must not affect administration counts, event timing, or dose summaries. |
| P42 | **Every medication in this study charted as exact `mg/kg` is treated as a mislabeled absolute `mg` dose for calculation at every site.** The raw value and unit remain unchanged in the raw-unit counts and P41 ECDFs; `step02__paralytic_dose_unit_corrections.csv` and `step03__sedation_dose_unit_corrections.csv` publish the affected counts per agent. Every other `/kg` unit still fails. Rows with a null/non-finite dose or null unit remain in administration and raw-unit counts but are excluded, with a logged count, from converted dose statistics. | Set by the study lead after consortium runs found `mg/kg` values whose magnitudes represented conventional absolute-mg doses, first for rocuronium and succinylcholine and then among the sedatives. Interpreting those literally and multiplying by adult weight would produce implausibly large doses. The correction remains visible rather than rewriting the source, and exact matching prevents this rule from discarding the weight axis from rate or other weight-based units. |
| P43 | **Converted dose summaries use strict clinical plausibility ranges and publish mean, sample SD, median, p25 and p75.** Included doses satisfy `0 < dose < upper bound` after conversion: etomidate 200 mg, fentanyl 500 mcg, midazolam 50 mg, propofol 500 mg, rocuronium 400 mg, succinylcholine 400 mg and vecuronium 30 mg. Ketamine is unchanged because no threshold was supplied. Raw propofol `mcg` rows are excluded as inaccurate entries. These exclusions affect only converted summary tables and Figure E.2; administration detection, raw-unit counts and raw-unit ECDFs retain the source rows for QC. | Set by the study lead. The bounds remove clinically implausible data-entry artifacts without changing which administrations define an index event or sedation context. Applying them after conversion makes every threshold unit-explicit; retaining the raw QC artifacts makes every exclusion auditable. Mean and SD beside median and IQR make skew visible in the compact summary. |
| P45 | **Generated artifact names encode ownership and figure lineage.** Every plotted dataframe is `figure_<id>_df`; its published CSV and PNG share `fig_<ID>__<description>`. Supporting outputs use `stepNN__<description>`, including PHI intermediates. The four `table1_by_agent_*` pooling names remain unchanged. `07_artifact_manifest.py` rejects stale, missing or undeclared shareable files and publishes producer, dataframe, sources, row count, size and SHA-256. | Set by the study lead for audit and control. A figure and its data can be paired by basename without reading code, while every non-figure file identifies its producer. Table 1 is the explicit exception because those names are an external consortium contract. |
| P46 | **Dose/weight is an additive analysis using a separate corrected selector: latest valid 20-300 kg current-hospital weight at or before the event, otherwise latest prior-hospital weight within 28 days.** Existing raw ECDFs and Table 1 weight remain unchanged. Step 04 also publishes block-first event counts by configured healthcare system, event-time hospital, academic status and year; normalized ECDFs; etomidate/ketamine p1-p99; local four-tier integer counts; and a dose-specific eligibility flow. | Set by the study lead. Site tier numerators and denominators are collected now for later pooled logit random-effects analysis; local plots do not imply pooled estimates before all sites report. Full contract: `2026-08-18-dose-weight-and-site-counts-design.md`. |
| P47 | **AMENDED 2026-08-18: every study medication has one required site-configured unit and only `mar_action_category == "given"` rows in that exact normalized unit enter any analysis.** `config["medication_dose_units"]` must specify all eight agents. Non-fentanyl agents allow `mg` or `mg/kg`; fentanyl allows `mcg` or `mcg/kg`. Values and units are never converted or relabeled. A configured `/kg` value is already normalized, needs no weight, and is not checked against an absolute-unit upper bound. | Set by the study lead after reviewing Rush and UCMC unit distributions. This supersedes P4, P18, P25 and P42, plus the action/unit clauses of P2, P41, P43 and P46. It removes `bolus`, prevents minority-unit rows from changing event denominators, and makes the selected site unit explicit and reproducible. |
| P48 | **Figure D.2 is a fixed ±6-hour sensitivity view of the same P12 transitions, using one nearest transition per index paralytic and 30-minute bins.** An exact-distance tie selects the earlier transition. D.2 does not modify the configured ±60-minute D.1 detector, persisted `imv_transition`, or downstream cohort definitions. | Set by the study lead to show where a device transition falls beyond the primary window without turning IMV state rows into transitions or changing the primary analysis. One selected event per index preserves the D.1 counting unit; nearest selection answers temporal proximity over the wider window. |

P47 is the active medication action/unit contract. Earlier conversion, override, rate-only,
and `given`/`bolus` language is retained above as decision history but is no longer operative.
P43's mean/SD and median/IQR outputs remain; its absolute upper bounds apply only when the
configured unit is absolute.

------------------------------------------------------------------------

## 3. Architecture

```
code/
  01_cohort.py            qualifying-paralytic cohort + stitch + CONSORT + waterfall
  02_index_paralytic.py   paralytic administrations → sub-analyses A, B, C
                          → index_paralytic.parquet
  03_context.py           index paralytic ± 60 min → D; ± 5 min → E
                          → index_context.parquet
utils/
  config.py               UNCHANGED
  suppress.py             NEW — the row-level prohibition, the single route
                          into final_no_phi/, imported by 01, 02 and 03 (P23)
```

```
   CLIF parquet
        │
  01_cohort.py ............ encounter blocks + waterfalled device timeline
        │
        │  medication_admin_intermittent
        │    med_category ∈ {rocuronium, succinylcholine, vecuronium}
        │    mar_action_category == given
        │    med_dose_unit == config unit for this medication
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
   final_no_phi/ ................. aggregates + figures, no row-level records
```

The split falls where the **data sources change**, not where the sub-analyses happen to be numbered. Everything in `02` touches `medication_admin_intermittent` and nothing else, which makes sub-analyses A–C self-validating: a gap distribution needs no second table to be checked against, so a failure in D can never obscure whether the index set is right. `03` is the only notebook that joins the waterfall and the only one that loads a second medication list.

`step02__index_paralytic.parquet` is the contract between them, specified in §6.2.

Only `01_cohort.py` knows that `hospitalization_id` exists as a unit. It resolves stitching once and publishes `list_hospitalization_id` in `step01__cohort_index.parquet` as the bridge key; `02` explodes that list to reach the medication table and aggregates straight back to `encounter_block`. No notebook re-derives a block.

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
    """Strip clifpy's configured site timezone without shifting wall time."""
    return series.dt.tz_localize(None)
```

`01` does not use this helper on the waterfall output: that frame is UTC-aware and is explicitly
converted back with `.dt.tz_convert(TIMEZONE).dt.tz_localize(None)`.

- **All minute arithmetic goes through polars epoch conversion** (P19):

```python
def epoch_minutes(column):
    return pl.col(column).dt.epoch("s") / 60.0
```

------------------------------------------------------------------------

## 5. Cohort — `01_cohort.py`

**Criteria**, applied to the stitched block:

| | |
|---|---|
| age | ≥ `min_age` (18) at admission |
| dates | `date_start` … `date_end` (2018-01-01 … 2025-12-31) |
| location | ED **or** ICU at some point in the block |
| index signal | at least one qualifying P3/P4/P25 paralytic administration |
| exclusion | tracheostomy in the first `trach_window_hours` (24) — `tracheostomy` truthy **or** `device_category == 'trach collar'` |

**Stitching comes first.** Hospitalizations less than `stitch_hours` (6) apart for the same patient are merged into an `encounter_block`, and every notebook after `01` keys on the block (P5).

**The waterfall makes the available device record continuous.** `clifpy`'s `process_resp_support_waterfall` inserts hourly scaffold rows, forward-fills `device_category` unconditionally, and relabels a row with a null device to `imv` when the ventilator settings on it look like a ventilator. Sub-analysis D consumes exactly this output (P13). A cohort block may legitimately have no raw IMV row.

Two properties of the waterfall are load-bearing downstream and are recorded so no later reader treats them as incidental:

- **`bfill` is inert for this pipeline.** The flag reaches only the numeric setters, after the device heuristics have already run. Flipping it changes ventilator settings and can never change which rows are IMV.
- **After the unconditional forward-fill, ~0.2% of waterfalled rows still carry a null device**, all of them before the block's first charted device. That residue is where `null → imv` transitions come from (P12).

**Outputs consumed by this study:** `step01__cohort_index.parquet` (with `list_hospitalization_id`, `patient_id`, `cohort_run_id`) and `step01__cohort_resp_waterfall.parquet`.

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
  mar_action_category == given + exact configured dose unit      P47
  columns: hospitalization_id, admin_dttm, med_category,
           mar_action_category, med_dose, med_dose_unit
```

Categories are stripped and lower-cased immediately after load (P20). `med_category` is **not** filtered through `from_file` — the whole-site scan uses a normalized lazy pushdown, and the analytic filter then runs on a column canonicalized in memory.

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

Every administration belongs to **exactly one** index event. There is no eligibility filter at this step — the index set is a partition of the administration set, and `Σ n_before_merge_admin` over all index events equals the source administration count. Only after each index is formed are repeated medications within that index merged. `02` asserts both boundaries.

### 6.4 `step02__index_paralytic.parquet` — the contract

One row per index paralytic, written to `output/intermediate_phi/`.

| column | type | |
|---|---|---|
| `index_paralytic_id` | str | `{encounter_block}_P{n}`, `n` in time order from 1 |
| `encounter_block` | int | |
| `patient_id` | str | |
| `cohort_run_id` | str | provenance; `03` asserts it matches |
| `p_num` | int | 1 = first index paralytic of the block |
| `t_dttm` | datetime, site-naive | **the study clock** (P8) |
| `n_before_merge_admin` | int | source administrations folded into this event before same-medication merging |
| `n_admins` | int | medication entries after same-medication doses are merged within the formed index |
| `span_minutes` | float | last − first; **asserted ≤ 15** |
| `is_coadmin` | bool | `n_admins > 1` |
| `agents` | list\[str\] | sorted distinct `med_category` |
| `n_agents` | int | |
| `agent_label` | str | `agents` joined with `+`, e.g. `rocuronium+vecuronium` |
| `doses` | list\[struct\] | one per distinct medication in the formed index: `med_category`, summed finite known `med_dose`, `med_dose_unit`, earliest `mar_action_category`, earliest `offset_minutes` |

`offset_minutes` inside `doses` is measured from `t_dttm` and retains the earliest source offset for that medication. Same medications in different formed indexes are never merged. If some repeated rows have missing or non-finite doses, known finite values are summed; a medication with no known finite value retains a null dose.

`agent_label` is sorted alphabetically so one combination is one row of any downstream table rather than several orderings of itself.

**Assertions on write:** `index_paralytic_id` unique; `span_minutes ≤ collapse_gap_minutes` for every row; `Σ n_before_merge_admin` equals the source administration count; `n_admins == n_agents == len(doses)`; `p_num` contiguous from 1 within each block; no null in any non-`doses` column.

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

Published three ways. Every bin appears in every table at its true count (P21); there is no bin-mode partition.

| table | rows |
|---|---|
| `fig_A1__paralytic_administration_pair_gaps.csv` | bin × `{pooled, same_agent, cross_agent}` → n. Every bin on the grid, including bins with a count of zero. |
| `step02__paralytic_pair_gaps_by_agent_pair.csv` | bin × unordered agent pair → n. The pair label is the two agents sorted alphabetically and joined with `+` — `rocuronium+vecuronium`, never `vecuronium+rocuronium` — so one pair is one row rather than two orderings of itself. Same-agent pairs appear as `rocuronium+rocuronium`. |
| `step02__paralytic_administration_summary.csv` | agent × `mar_action_category` → n administrations, n blocks, n patients. |

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
| `step02__index_paralytic_summary.csv` | one row per `agent_label`: n index paralytics, n blocks, n patients, `n_coadmin` (formed indexes containing more than one distinct medication), `span_minutes` median and max |
| `step02__index_paralytic_dose_summary.csv` | `med_category` → cleaned n, mean, SD, median, p25, p75, in the standardised unit (P18, P43) |
| `step02__paralytic_dose_raw_unit_counts.csv` | `med_category` × configured `med_dose_unit` → n merged formed-index medication doses. Counts only; source administration QC remains in sub-analysis A. |

Doses retain the exact configured unit and numeric value without conversion (P47). The unit-count file documents the selected analysis population; missing doses remain there but do not inflate the summary `n`.

### 7.3 C — the gap between index paralytics

The same construction as A, applied to index paralytics instead of raw administrations: all unordered pairs of `t_dttm` within a block, the identical bin grid, the identical overflow bin.

| table | contents |
|---|---|
| `fig_C1__index_paralytic_pair_gaps.csv` | bin → n pairs |
| `step02__index_paralytics_per_block.csv` | index paralytics per block → n blocks |

**Figure C.1** overlays C on A using the same bins. By construction C has **zero mass in every bin up to and including `(10,15]`** — and the bound is strict, not approximate. An anchor at `t` closes at `t + 15` inclusive, so the next anchor is the first administration *strictly after* `t + 15`; consecutive index paralytics are therefore always more than 15 minutes apart, and every non-consecutive pair is wider still. `02` asserts those six bins are empty. A non-zero count there is a bug in the fold, not a finding, and the assertion is the cheapest possible test that P6 was implemented as written.

### 7.4 D — the non-IMV → IMV transition

Source: `step01__cohort_resp_waterfall.parquet` (P13). Per `encounter_block`, sorted by `recorded_dttm`:

```
a row is a TRANSITION when
      device_category == 'imv'
  AND ( no preceding row exists in the block
        OR preceding device_category != 'imv' )

null is not imv  →  null → imv  IS a transition
block opens on imv  →  that first row IS a transition
imv → imv  →  not a transition
```

For each index paralytic, scan `[t − imv_window_minutes, t + imv_window_minutes]` — inclusive at both ends — and keep the **earliest** transition inside it.

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
| `step03__imv_transition_summary.csv` | `imv_transition` × `no_transition_reason` → n; and `prior_device_category` → n among transitions |
| `fig_D1__imv_transition_offset.csv` | 5-minute bins across the configured IMV window (`[−60, +60]`) → n |
| `fig_D2__imv_transition_offset_6h.csv` | nearest transition per index in 30-minute bins across `[−360, +360]` → n |
| `step03__imv_prior_device.csv` | `prior_device_category` × `transition_opens_block` → n, among transitions |
| `step03__imv_transitions_per_window.csv` | `n_transitions_in_window` → n, contiguous from 1 to the observed maximum (the P14 de-bouncing evidence, one row per index paralytic that had a transition) |

**Figure D.1** — histogram of `imv_offset_minutes`, 5-minute bins, zero line marked, drawn from `fig_D1__imv_transition_offset.csv` and written to the same-stem PNG.

**Figure D.2** — sensitivity histogram of the nearest P12 transition within inclusive ±6 hours,
30-minute bins, earlier transition winning an exact-distance tie. It is drawn from
`fig_D2__imv_transition_offset_6h.csv` and written to the same-stem PNG.

Offset bins are `[−60,−55)`, … , `[55, 60]` — 24 bins, left-closed and right-open except the last, which is closed so an offset of exactly `+60` has a home.

**Assertions:** `|imv_offset_minutes| ≤ imv_window_minutes` on every recorded transition; `imv_transition` true implies `imv_transition_dttm` and `imv_offset_minutes` non-null and `no_transition_reason` null, and false implies the converse.

### 7.5 E — sedation in its configured window

The same inclusive predicate as D, supplied with `sedation_window_minutes = 5` (P15). Source: `medication_admin_intermittent`, `med_category ∈ {midazolam, etomidate, ketamine, propofol, fentanyl}` (P16), `mar_action_category == given`, and the exact configured unit (P47). **Every qualifying** administration in the window is kept (P17).

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
| `step03__sedation_summary.csv` | `any_sedative` × `agent_set` (the sorted, `+`-joined `sedative_agents`) → n, `median_n_admins` |
| `fig_E1__sedation_offset.csv` | 5-minute bins across the configured sedation window (`[−5, +5]`) × `med_category` → n |
| `fig_E2__sedation_dose_summary.csv` | `med_category` → cleaned n_admin_windows, mean, SD, median, p25, p75, in the standardised unit (P18, P43) |
| `step03__sedation_dose_raw_unit_counts.csv` | `med_category` × raw `med_dose_unit` → n administrations, counts only |

**Figure E.1** — offset histogram across the configured ±5 min, one series per agent, drawn from `fig_E1__sedation_offset.csv`. **Figure E.2** — dose distribution per `med_category` in its configured unit, drawn from `fig_E2__sedation_dose_summary.csv`. Each is written to a same-stem PNG. One panel per unit is retained because mg and mcg on a shared axis is a dual-axis chart in disguise.

------------------------------------------------------------------------

## 8. Outputs and data security

```
output/intermediate_phi/          row-level, never leaves the site
  step01__cohort_index.parquet            from 01
  step01__cohort_resp_waterfall.parquet   from 01
  step02__index_paralytic.parquet         §6.4
  step03__index_context.parquet           index paralytic + D + E cols

output/final_no_phi/              shareable aggregates — no row-level records (P21, P23)
  step01__*.csv through step04__*.csv    supporting and QC tables by owner
  fig_A1__*.csv through fig_T2__*.csv    plotted data keyed by figure ID
  figures/fig_A1__*.png through fig_T2__*.png  same-stem figures
  table1_by_agent_*.csv/.json            stable consortium contracts
  artifact_manifest.csv                  lineage, row counts and SHA-256
```

**Rules** (P21, P23):

- No `patient_id`, no `hospitalization_id`, no `encounter_block`, no `p_num`, no row-level records, no raw data files in `final_no_phi/`. This is the disclosure boundary and the only one.
- **Aggregate counts are published at their true value, including counts below 10.** Nothing is withheld, so nothing is recoverable by differencing two published files — the failure mode that produced three separate leaks under the withdrawn rule (P24) cannot arise.
- The boundary is enforced by `utils/suppress.py`, imported by both `02` and `03` (P23). It is the only shared code in the project, and it is the only route into `final_no_phi/`.
- Every figure is drawn from a published table, so a figure cannot disagree with the CSV beside it.
- A histogram bin with a count of zero is drawn and published as zero. Every bin on the grid appears in the table.
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
    "imv_window_minutes": 60,
    "sedation_window_minutes": 5,
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
retarget  tests/test_clifpy_tz_boundary.py
              clifpy site-time stripping and the waterfall UTC round trip (P19).

retarget  tests/test_collapse_agent_events.py
              already pins anchor-and-close and the DST epoch-minutes
              shortcut for the deleted 05. Repoint at 02's index builder,
              which is the same rule on a different agent list.

retarget  tests/test_e7_suppression.py  →  tests/test_publish_guard.py
              Tier E.7 is gone. Repoint at utils/suppress.py (P23): a frame
              carrying patient_id / hospitalization_id / encounter_block /
              p_num / any *_id is refused; a frame with no count column is
              refused; a clean aggregate is written unchanged, including its
              rows with counts of 1..9 and its rows with counts of 0.

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
- **Further cohort changes.** P2 defines the qualifying-paralytic cohort; no additional cohort rule is introduced downstream.

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
