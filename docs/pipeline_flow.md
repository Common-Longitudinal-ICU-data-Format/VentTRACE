# VentTRACE — how the pipeline works

A plain-language walkthrough of what each notebook does and why. The authoritative
definitions live in
[`superpowers/specs/2026-08-04-intubation-method-comparison-design.md`](superpowers/specs/2026-08-04-intubation-method-comparison-design.md);
this document is the map, not the territory. Where the two disagree, the spec wins.

Counts shown are MIMIC, `cohort_run_id` 2026-08-06.

---

## 1. What the study is actually asking

You have a ventilator chart and a medication chart. You want to find the moment
someone got a breathing tube, look at what drugs were given around that moment, and
ask whether "look for sedatives" and "look for paralytics" find the same events.

Everything below is machinery for finding **the moment**, precisely and repeatably.
Once the moment is fixed, comparing the methods is easy — they all measure against
the same clock.

---

## 2. The pipeline at a glance

```
  CLIF parquet files
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 01_cohort.py            WHO is in the study                      │
│                                                                  │
│  adults · date range · ever on a vent · no pre-existing trach    │
│  stitch hospitalizations <6h apart   → encounter_block           │
│  waterfall respiratory_support       → a gap-free device timeline│
└───────┬──────────────────────────────────────────────────────────┘
        │  34,017 blocks · 6,957,207 device rows
        │
┌───────▼──────────────────────────────────────────────────────────┐
│ 02_index_imv.py         WHEN did each intubation happen          │
│                                                                  │
│  3 rules → 13,500 episodes, each with a t0 and a ±3h window      │
└───────┬──────────────────────────────────────────────────────────┘
        │
        ├──────────────┬──────────────┐
        ▼              ▼              ▼
  ┌──────────┐  ┌───────────┐  ┌────────────┐
  │03 SED    │  │04 PARA    │  │05 PAIR     │   three ways to say
  │sedatives │  │paralytics │  │one of each │   "an intubation
  │in window │  │in window  │  │close in    │    happened here"
  └────┬─────┘  └─────┬─────┘  │time        │
       │              │        └─────┬──────┘
       └──────────────┴──────────────┘
                      │        ┌──────────────┐
                      │        │06 CPT 31500  │  a 4th opinion from billing
                      │        │              │  (1 episode in 6,319 at MIMIC —
                      │        │              │   a dead end, but measured
                      │        └──────┬───────┘   rather than assumed)
                      ▼               ▼
              ┌──────────────────────────────┐
              │ 07_agreement.py              │
              │ do they find the same events?│
              │ overlap · kappa · timing     │
              │ · figures                    │
              └──────────────────────────────┘
```

Two funnels, two CONSORT diagrams. `01` answers *who is in the study*; `02` answers
*when, and how many times, each of them was intubated*.

---

## 3. `01_cohort.py` — who is in

Nothing subtle here, but two choices matter downstream.

**Stitching comes first.** An ED presentation and the inpatient admission that
follows can carry different `hospitalization_id`s. If you don't join them, the
paralytic is charted under one id and the ventilator under the other, and the
agreement matrix records a disagreement that is purely administrative. So
hospitalizations less than 6 h apart for the same patient are merged into an
`encounter_block`, and **every notebook after this one keys on the block**.

**The waterfall makes the device record continuous.** Raw `respiratory_support`
is charted irregularly. `clifpy`'s waterfall inserts hourly scaffold rows, forward-fills
the device, and — the part that matters most here — **relabels a row with a null
device to `imv` when the ventilator settings on it look like a ventilator**
(`waterfall.py:199-215`). Hold onto that; §4 turns on it.

```
   raw chart          08:00 nasal    11:30 (null, PEEP 5, FiO2 100)    12:00 IMV
                                              │
   waterfall says     08:00 nasal    11:30  IMV                        12:00 IMV
                                              ▲
                                     "the settings say ventilator,
                                      so call it a ventilator"
```

---

## 4. `02_index_imv.py` — when did it happen

This is the heart of the pipeline and the part most recently rewritten.

### What the raw data looks like

One patient's device timeline, left to right. Each entry is one charted row.

```
 time →  08:00   09:00   11:30   12:00   12:05   14:00   18:00   22:00   02:00   02:10
 device  nasal   nasal   nasal   IMV     IMV     IMV     IMV     face    IMV     IMV
                                  ▲                               mask     ▲
                                  │                                        │
                          somebody got tubed                    they got tubed AGAIN
```

Two intubations, one hospital stay. The earlier design only ever found the first.
Finding both is the point of the rewrite.

### Rule 1 — where does an episode start?

Look at every IMV row in the waterfalled timeline. Ask one question:

```
                    ← 3 hours back →
              ┌────────────────────────┐
              │  was there any IMV     │
   this IMV   │  charting in here?     │
   row  ──────┤                        │
              └────────────────────────┘
                    │              │
                  YES             NO
                    │              │
                    ▼              ▼
          you're already      THIS ROW
          on the vent —       STARTS AN
          skip this row       EPISODE
```

**One test doing two jobs.** It *is* the "3 h before must be null or non-IMV"
rule — if no IMV precedes within 3 h then everything in that window is by
definition either a different device or nothing at all. And it is *also* what chops
the timeline into episodes: in the example above, the rows at 12:05, 14:00 and 18:00
each have IMV inside their own lookback and disqualify themselves. Only 12:00 and
02:00 survive.

There is no episode loop, no "am I inside an episode?" state to track, and no
mid-episode branch to get wrong. 6.96 M rows collapse to **42,488 candidates** with a
single `shift(1)` over IMV-only rows.

It also admits the patients who arrive already tubed. Somebody rolled in from the ED
on a ventilator has *nothing* in their 3 h lookback — the window is empty, empty
contains no IMV, so it passes. That is 53% of the final set, and the previous design
threw all of it away.

### Rule 2 — did the tube stay in?

```
   [start]
      │       ← 3 hours forward →
      ├────────────────────────────────┐
      │  any NON-IMV device charted?   │
      └────────────────────────────────┘
              │                  │
            YES                 NO
              │                  │
              ▼                  ▼
        REJECT              keep it
   "not_sustained"     a real intubation
```

A lone IMV row followed straight away by a face mask is a charting blip, not an
intubation. **−2,218 → 40,270.**

Note what passes: **null passes.** Three hours of no charting does not mean the
patient was extubated, it means nobody charted. Absence of evidence is not evidence
of absence — and that principle is precisely why the old `insufficient_lookback`
exclusion was wrong and has been deleted.

### The anchor — t₀ is the episode start

Not a rule, a definition: t₀ is the timestamp of the episode's first waterfalled IMV row. Nothing else. Worth dwelling on, because it reverses an earlier decision.

```
  what the WATERFALL says:   ... null  null  [imv]  imv  imv  imv ...
                                            ▲
                                            └─ t0. Possibly inferred from
                                               ventilator settings rather than
                                               from anyone charting a device.

  what a HUMAN CHARTED:      ...                    [imv]
                                                      ▲
                                                      └─ someone typed
                                                         "ventilator" into a box,
                                                         some minutes or hours later.
```

An intubation is a high-stress event. Nobody stops mid-crash to fill in the device
field. But the ventilator's settings reach the chart the moment it is connected, so
the settings-based inference lands **closer to the real event** than the manual
device entry does.

The delay is measurable, and it is now published rather than avoided:

| first charted IMV − t₀ | |
|---|---|
| exactly 0 | 77.3% |
| p90 | 23 min |
| p95 | 55 min |
| p99 | **540 min (9 h)** |
| max | 6,389 min (4.4 days) |
| never charted in the episode | 7 episodes |

That p99 tail is the argument made visible. **The delay is never negative** — the
waterfall only ever relabels nulls and never deletes a charted row, so its IMV can
only be at or before the charted one. `02` asserts that.

### Rule 3 — was any induction drug given at all?

```
        t0 − 3h              t0              t0 + 3h
           │─────────────────│─────────────────│
                 ▲    ▲            ▲      ▲
                 └────┴────────────┴──────┘
                  every medication_admin_intermittent row
                  with mar_action_category = 'given'

     is ANY of these one of the 8 drugs?
       midazolam · etomidate · ketamine · propofol · fentanyl
       rocuronium · succinylcholine · vecuronium
                       │
              NO ──────┴────── YES
               │                │
               ▼                ▼
        drop the episode    KEEP IT
```

**−26,770 → 13,500.**

### The funnel

```
   34,017 encounter blocks
        │
        │  6,957,207 waterfalled device rows
        ▼
   42,488  candidate episode starts        ← rule 1
        │    −2,218   not sustained        ← rule 2
        ▼
   40,270
        │  −26,770   no induction drug     ← rule 3
        ▼
   13,500  EPISODES   over 12,503 blocks, 11,935 patients
```

### Naming the episodes

```
  encounter_block 4471
    ├─ episode at 12:00  →  intubation_episode_id = "4471_E1"
    └─ episode at 02:00  →  intubation_episode_id = "4471_E2"
```

11,675 blocks have one episode · 701 have two · 99 have three · tail out to seven.
**1,940 episodes are reintubations** (`ep_num > 1`), across 1,654 blocks.

`ep_num` counts *sustained* episodes, not just qualified ones. A ventilation episode
with no induction charted is still a ventilation episode, so an intubation that
follows one really is the block's second.

This cost no schema churn: §6.1 of the spec already wrote the id as
`{encounter_block}_E1` with a note that the suffix existed so reintubation could be
added later without changing any key. Later arrived.

### What `02` labels but does not exclude

| column | meaning | n |
|---|---|---|
| `no_lookback` | t₀ is the block's first respiratory row — arrived intubated | 7,130 (52.8%) |
| `imv_charted` | some human charted a device in this episode | 13,494 |
| `charting_delay_min` | first charted IMV − t₀ | see table above |
| `ep_num` | 1 = index intubation, >1 = reintubation | 1,940 are >1 |

These are strata for `07`, not filters. The single subsetting decision in the whole
pipeline lives in `07`.

---

## 5. `03`, `04`, `05` — the three methods

Each is handed `(intubation_episode_id, t0, window_start, window_end)` and answers
"did I see an intubation here?" Each is **fully self-contained** — no shared helper
module, deliberately. A bug in a shared helper would corrupt all three *identically*,
and correlated errors are indistinguishable from genuine agreement, which is the one
failure mode an agreement study cannot survive.

```
   ┌────────────────────────────────────────────────────────┐
   │ 03 SED — sedatives                                     │
   │   midazolam etomidate ketamine propofol fentanyl       │
   │                                                        │
   │   t0-3h ─────────── t0 ─────────── t0+3h               │
   │      propofol            fentanyl                      │
   │         ▲                   ▲                          │
   │    "last one before"   "first one after"               │
   │    rank 1 = closest to t0, on either side              │
   │    deduplicated by drug, so six fentanyl doses         │
   │    contribute one observation, not six                 │
   └────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────┐
   │ 04 PARA — paralytics                                   │
   │   rocuronium succinylcholine vecuronium                │
   │   identical code, different list. On purpose.          │
   └────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────┐
   │ 05 PAIR — one of each, close together                  │
   │                                                        │
   │   scans the WHOLE stay, not the window:                │
   │      propofol ─── 4 min ─── rocuronium   ✓ a pair      │
   │                                                        │
   │   walk forward; the first opposite-class drug within   │
   │   3h wins; then BOTH are consumed and neither can      │
   │   pair again. Same-class rows in between are stepped   │
   │   over, not consumed — a fentanyl charted ahead of     │
   │   the induction agent still reaches the rocuronium.    │
   └────────────────────────────────────────────────────────┘
```

`PAIR` scans per block, so a block with several episodes gets several pairs. Each
pair is assigned to **the episode whose t₀ is nearest**, ties to the earlier episode:

```
  block 4471, whole-stay scan finds 3 pairs:

    P1 at 11:58        P2 at 13:40        P3 at 02:05
        │                  │                  │
        │  E1 t0=12:00     │                  │  E2 t0=02:00
        ▼                  ▼                  ▼
      2 min away        100 min away        5 min away
        │                  │                  │
        └──── E1 ──────────┘                  └──── E2
```

No pair is counted twice, and `detected = n_pairs > 0` still holds per episode.

---

## 6. `06_reference_cpt.py` — the outside opinion

Looks for CPT 31500 (emergency endotracheal intubation) in `patient_procedures`.

At MIMIC it doesn't work: the extract holds 116 CPT rows against ~210,000 ICD rows,
and **1 index episode of 6,319** carries the code. So `06` measures its own capture
rate *before* scoring anything, and if capture is under 5% it publishes
`informative = false` with null metrics instead of a sensitivity computed on a
denominator of one.

That is the honest result. A number computed on n = 1 looks like method performance,
gets quoted as method performance, and is really a statement about which billing
system the site exported.

---

## 7. `07_agreement.py` — do they agree?

Loads all five artifacts, **validates every schema on load** and fails loudly rather
than mis-joining, then runs five tiers.

```
  ┌── Tier A ── do the methods find the same episodes? ──────────────┐
  │   A.1  detection rate per method                                 │
  │   A.2  three pairwise 2x2 tables (SED×PARA, SED×PAIR, PARA×PAIR) │
  │   A.3  how many methods fired: 0, 1, 2 or 3                      │
  │   A.4  all eight combinations in one table                       │
  │        Jaccard and Cohen's kappa, written out longhand           │
  └──────────────────────────────────────────────────────────────────┘

  ┌── Tier B ── where in time is the charting? ──────────────────────┐
  │   offset distributions on a shared t0 axis — the whole reason    │
  │   for pinning every method to one clock                          │
  └──────────────────────────────────────────────────────────────────┘

  ┌── Tier C ── the reference check (gated, see §6) ─────────────────┐

  ┌── Tier D ── specificity: is SED detecting intubation, or ICU? ───┐
  │   stratified by no_lookback, by ep_num, and against the          │
  │   not_sustained episodes                                         │
  └──────────────────────────────────────────────────────────────────┘

  ┌── Tier E ── pair structure and independent timing ───────────────┐
  │   PAIR is the only method that derives its OWN intubation        │
  │   timestamp, so it is the only one that can disagree with the    │
  │   device about WHEN. E.5 is the headline: only 25% of first      │
  │   pairs land within ±30 min of t0, and 60% are beyond ±180 min.  │
  └──────────────────────────────────────────────────────────────────┘
```

Everything published lands in `output/final_no_phi/`: aggregates only, **minimum
cell size n ≥ 10**, no `patient_id`, no row-level records, no raw data files. Every
figure is drawn from a published table, so a suppressed cell is suppressed in the
plot automatically rather than by a second implementation of the same rule.

---

## 8. The one thing to keep in mind when reading Tier A

Rule 3 keeps an episode only if one of the eight drugs was given in the window.
`SED` and `PARA` then look for those same eight drugs, in that same window, in that
same table.

```
   rule 3 asks:  "was any of {8 drugs} given in ±3h?"   → keep the episode
   SED  asks:    "was any of {5 of them} given in ±3h?" → detected
   PARA asks:    "was any of {3 of them} given in ±3h?" → detected

   therefore:  SED_detected OR PARA_detected  is TRUE for every kept episode.
```

```
              PARA +      PARA −
           ┌───────────┬───────────┐
    SED +  │           │           │
           ├───────────┼───────────┤
    SED −  │           │  ~empty   │  ← can't fill up. Not a finding —
           └───────────┴───────────┘     it's the definition of the cohort.
```

Not *quite* empty: a drug charted at exactly t₀ belongs to neither the before nor
the after list, so a handful land there. But that residual measures on-the-minute
charting habits, not method disagreement.

**So Tier A's question is narrower than it looks.** Not "do the methods find the
same intubations?" but "**given that an induction drug was charted, do the methods
catalog it the same way?**" Tiers B and E are untouched by this — they measure where
drugs sit in time and how pairs are structured — and are the stronger results
because of it.

---

## 9. Every rule in one table

| # | Rule | Where | Effect |
|---|---|---|---|
| — | adults, date range, ever-IMV, ED or ICU, no trach in 24 h | `01` | 34,017 blocks |
| — | stitch hospitalizations < 6 h apart | `01` | defines `encounter_block` |
| 1 | an IMV row with no IMV in the previous 3 h starts an episode | `02` | 42,488 candidates |
| 2 | reject if a non-IMV device appears within 3 h after | `02` | −2,218 |
| — | t₀ = the episode's first **waterfalled** IMV row | `02` | not the charted one |
| 3 | reject unless one of the 8 induction drugs is given in t₀ ± 3 h | `02` | −26,770 |
| — | `SED` = 5 sedatives in t₀ ± 3 h, ranked nearest-first | `03` | |
| — | `PARA` = 3 paralytics in t₀ ± 3 h, ranked nearest-first | `04` | |
| — | `PAIR` = opposite-class drugs < 3 h apart, forward pass with consumption | `05` | whole stay |
| — | pairs assigned to the nearest episode t₀ | `05` | no double counting |
| — | reference gated on capture ≥ 0.05 before scoring | `06` | |
| — | published cells suppressed below n = 10 | `07` | |

---

## 10. Footguns

Things that have already bitten this codebase once.

**The pytz LMT trap.** `clifpy` returns timezone-aware columns whose `tzinfo` is
`DstTzInfo 'US/Eastern' LMT-1 day, 19:04:00 STD` — a *pre-standardisation* offset.
Calling `.dt.tz_localize(None)` drops the attached offset rather than the correct
one and shifts everything by about an hour, silently. The only correct move is:

```python
def to_site_naive(series):
    return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)
```

Pinned by `tests/test_clifpy_tz_boundary.py`. `01` also cross-checks that every
non-scaffold waterfall timestamp exists in the raw table, which is how the bug was
caught in the first place.

**Case sensitivity.** Every `*_category` column is lower-cased on load and every
literal in the codebase is written in lower case. A mismatched category value does
not raise — it matches zero rows, and a filter matching zero rows looks exactly like
a site where the thing never happens. Load-time filters pass every casing variant,
because those run before any of our own normalisation can reach them.

**`bfill` in the waterfall is not what it looks like.** `waterfall.py:274`
forward-fills `device_category` unconditionally; the `bfill` flag only reaches the
numeric setters at `:320-336`, after the device heuristics have already run.
Flipping it changes ventilator settings and can never change which rows are IMV.

**`pair_gap_hours` cannot be applied post hoc.** Rejecting a pair leaves *both*
administrations available to pair with something else, so tightening the threshold
yields a *different* pair set, not a subset of the current one. Filtering
`gap_minutes` on the output is not equivalent to re-running `05`.

**`encounter_block` is not stable across runs.** It is seeded from a row index, so a
re-extract renumbers everything. Every artifact carries a `cohort_run_id` and `07`
asserts they all match — without it, joining a `SED` artifact from one run to a
`PARA` artifact from another produces a table that is silently wrong: the ids match,
the rows are real, and they describe different patients.
