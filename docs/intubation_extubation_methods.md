# Intubation & Extubation Definitions — Methods Catalog

**Project:** VentTRACE
**Source discussion:** [clifpy issue #124 — *Feature Request: Intubation Extubation functions*](https://github.com/Common-Longitudinal-ICU-data-Format/clifpy/issues/124)
**Status:** Reference catalog. Documents *what was proposed*, not what has been decided.
**Last updated:** 2026-07-29

---

## 1. Context

Issue #124 opened with a request to standardise intubation/extubation logic in `clifpy`, because
4–5 projects at a single site — and parallel efforts at other sites — each re-implement it.
Over nine comments, **four distinct methods** were proposed, written in three different notations
(prose bullets, SQL, pandas). They have never been compared side by side.

The final comment on the thread (@kaveriC, 2026-07-13) reads:

> @kaveriC @vaishvikc — create a new test project with different definitions discussed above

**VentTRACE is that project.** This document is its first deliverable: a normalised catalog of every
proposed method plus a rubric for validating them across consortium sites. The cross-site comparison
harness is specified separately.

### Contributors to the definitions

| Handle | Contribution |
|---|---|
| `@vaishvikc` | Issue body — strict 5-row window (**M1**); CHEST-run findings on device-free sites (**M5**) |
| `@cloverbunny` | Symmetric 2/2 window + reintubation + no-stitching stance (**M2**); the blip edge case |
| `@ingra107` | Endorsed M2's stitch-at-project-level position |
| `@whiskey0504` | SQL single-transition definition + outcome classification tree (**M3**) |
| `@wtliao319` | Hybrid strict ∪ candidate-rescue implementation (**M4**) |
| `@kaveriC` | Directed creation of this test project |

---

## 2. The substrate: why these methods disagree at all

Every method reads the same table and reduces it to the same question — *for each row, did the
patient just start or stop invasive mechanical ventilation?* They disagree because
`respiratory_support` is sparse, irregular, and inconsistently charted.

```
 clif_respiratory_support  (CLIF demo: 3,325 rows / 110 hospitalizations)
 ─────────────────────────────────────────────────────────────────────────
   hospitalization_id   recorded_dttm   device_category   mode_category   tracheostomy
                                              │
                                              ▼
                          ┌───────────────────────────────────┐
                          │  IMV            1,265   (38.0%)   │
                          │  Nasal Cannula    912   (27.4%)   │
                          │  ░░ NULL ░░       783   (23.5%)   │  ◄── the problem
                          │  Face Mask        249    (7.5%)   │
                          │  High Flow NC      81    (2.4%)   │
                          │  NIPPV             28    (0.8%)   │
                          │  CPAP               4    (0.1%)   │
                          │  Other              3    (0.1%)   │
                          └───────────────────────────────────┘
```

**Nearly one row in four carries no `device_category` at all** — more than Face Mask, HFNC, NIPPV,
CPAP and Other combined. Rows exist because *some* field was charted (a FiO₂, a PEEP, an observed
tidal volume), not because a device was recorded.

This matters more than any transition rule. A method's behaviour is the product of two independent
decisions:

```
       ┌─────────────────────┐        ┌─────────────────────┐
       │  (A) NULL / fill    │        │  (B) transition     │
       │      policy         │  ────► │      rule           │  ────►  events
       │  ffill? drop?       │        │  window width,      │
       │  NULL = non-IMV?    │        │  anchoring          │
       └─────────────────────┘        └─────────────────────┘
              ~50× spread                    ~7× spread
```

Measured on the demo dataset (§11.4), decision (A) changes event counts by up to **50×**; decision (B)
by about **7×**. The thread has debated (B) extensively and (A) barely at all.

Two further consequences of the substrate, both raised in the thread:

- **`mode_category` is not reliably present.** @cloverbunny: *"Mode may be absent depending on
  device."* In the demo, 1,873 of 3,325 rows (56%) have a NULL mode. Outputs that require
  mode-before / mode-after must tolerate nulls rather than drop the event.
- **Some sites chart no post-extubation device at all.** See **M5** (§7).

---

## 3. Common notation

All four methods are restated here in one formalism so they can be compared directly.

For a hospitalization `h`, let its respiratory-support rows be the sequence

```
        R_h = ( r_1 , r_2 , … , r_n )        ordered ascending by recorded_dttm
```

Let `d(i)` be the `device_category` of row `r_i` **after** the NULL policy `P` has been applied, and
define the primitive predicate:

```
        IMV(i)   ≡   d(i) = 'imv'
       ¬IMV(i)   ≡   d(i) ≠ 'imv'
```

An event is emitted **at a row index**, and that row's `recorded_dttm` becomes the event timestamp.

### 3.1 The three parameters every method leaves partly implicit

**(P) NULL policy** — what happens to the 23.5% of rows with no device:

| Policy | Meaning | Used by |
|---|---|---|
| `P_ffill` | Forward-fill `device_category` within hospitalization before evaluating | M1 (stated) |
| `P_null≠imv` | Leave NULL in place; NULL satisfies `¬IMV` | M3, M4 (by language semantics) |
| `P_drop` | Delete rows with NULL device before evaluating | nobody, but plausible |
| `P_waterfall` | Run `clifpy` waterfall first, which imputes device by heuristic | open question (§9.2) |

**(B) Boundary policy** — how `d(i)` behaves for `i < 1` or `i > n` (before the first / after the
last row). Write `⊥` for out-of-bounds.

| Policy | `¬IMV(⊥)` | `IMV(⊥)` |
|---|---|---|
| `B_strict` | false | false |
| `B_permissive` | **true** | false |

This is the least-discussed and highest-impact convention in the whole catalog. Under `B_strict` a
patient who arrives already ventilated generates **no** intubation event; under `B_permissive` they
generate one at their very first row. M3 and M4 are `B_permissive` — but *not by design*: it falls
out of SQL's `NULL IS DISTINCT FROM 'imv' → TRUE` and pandas' `~NaN.eq('imv') → True`. Neither
author states it.

**(A) Anchoring** — which row carries the extubation event:

```
            … IMV   IMV   IMV  │  FaceMask   FaceMask …
                          ▲    │      ▲
                          │    │      │
                  anchor "last IMV"   anchor "first non-IMV"
                       (M1)              (M2, M3, M4)
```

Both are defensible — the last IMV row is the last moment ventilation was observed; the first
non-IMV row is the first moment it was observed absent. The true extubation lies between them. But
the two anchors produce **different timestamps for the same clinical event**, and therefore different
ventilator durations. Measured concordance between M1 and M2 on extubation events is **zero**
(§8.3) — entirely because of this.

> **Convention used throughout this document:** where a proposal is silent, traces use `B_strict`
> for M1/M2 (their prose implies a real lag/lead value must exist) and the language-native
> `B_permissive` for M3/M4. Every such choice is flagged ⚠ at the point it is made.

---

## 4. Method M1 — Strict 5-row window

**Proposed by** `@vaishvikc`, issue #124 body.

### Definition

```
   intub(i)  ≡  ¬IMV(i-2) ∧ ¬IMV(i-1) ∧  IMV(i)  ∧  IMV(i+1) ∧  IMV(i+2)
   extub(i)  ≡   IMV(i-2) ∧  IMV(i-1) ∧  IMV(i)  ∧ ¬IMV(i+1) ∧ ¬IMV(i+2)
```

**NULL policy:** `P_ffill` (stated: *"Forward-fill `device_category`"*).
**Boundary:** ⚠ unspecified — `B_strict` assumed.
**Anchor:** intubation on **first IMV** row; extubation on **last IMV** row.

### Window diagram

```
   INTUBATION                                EXTUBATION

   i-2  i-1   i   i+1  i+2                   i-2  i-1   i   i+1  i+2
    ┌────┬────┬────┬────┬────┐                ┌────┬────┬────┬────┬────┐
    │ ¬  │ ¬  │IMV │IMV │IMV │                │IMV │IMV │IMV │ ¬  │ ¬  │
    │IMV │IMV │ ●  │    │    │                │    │    │ ●  │IMV │IMV │
    └────┴────┴────┴────┴────┘                └────┴────┴────┴────┴────┘
     └── 2 back ──┘└─ 3 fwd ──┘                └── 3 back ──┘└─ 2 fwd ─┘
                  ▲ event                                   ▲ event
```

### Note: M1 is *not* symmetric

The issue body lists five states for each event. For intubation that is 2 non-IMV + **3** IMV; for
extubation it is **3** IMV + 2 non-IMV. Every other method uses 2 + 2. This is easy to miss when
reading the bullets, and it makes M1 strictly the most conservative definition in the catalog — it
requires a fifth confirming row that M2/M4 do not.

@cloverbunny describes their approach as *"the two look back/look-forward device approach"*, which
is 2 + 2 — i.e. **M2, not M1**, despite the thread treating them as the same method.

### Behaviour

| | |
|---|---|
| **Catches** | Long, cleanly documented ventilator courses with unambiguous transitions |
| **Misses** | Patients arriving on IMV (no lookback exists → `B_strict` blocks the event) |
| **Misses** | Episodes shorter than 3 charted rows |
| **Misses** | Any course with a single-row device blip (§9.1) |
| **Never emits** | False positives from isolated stray rows — its conservatism is a genuine strength |

On the demo dataset M1 identifies intubation in **8 of 59** hospitalizations that have any IMV row
(§11.1) — an 86% miss rate, and its median episode duration is **3× longer** than M3/M4's because it
only ever sees the clean, long courses.

---

## 5. Method M2 — Symmetric 2/2 window + reintubation, no stitching

**Proposed by** `@cloverbunny`, endorsed by `@ingra107` (2026-02-10).

Prose, not code. Formalised here from three statements in the comment:

> *"the two look back/look-forward device approach is what we use in our project"*
> *"we also want to identify reintubation — in our project we just look forward to next period of intubation using same flag logic"*
> *"as long as there is documented non-IMV devices x2 rows, this should be flagged as extubation then people can stitch them together later if they want"*

### Definition

```
   intub(i)  ≡  ¬IMV(i-2) ∧ ¬IMV(i-1) ∧  IMV(i)  ∧  IMV(i+1)
   extub(i)  ≡   IMV(i-2) ∧  IMV(i-1) ∧ ¬IMV(i)  ∧ ¬IMV(i+1)

   reintub(i) ≡ intub(i) ∧ ∃ j < i : extub(j)      — any intubation after a prior extubation
```

**NULL policy:** ⚠ unspecified.
**Boundary:** ⚠ unspecified — `B_strict` assumed.
**Anchor:** intubation on **first IMV** row; extubation on **first non-IMV** row.

```
   INTUBATION                          EXTUBATION

   i-2  i-1   i   i+1                  i-2  i-1   i   i+1
    ┌────┬────┬────┬────┐               ┌────┬────┬────┬────┐
    │ ¬  │ ¬  │IMV │IMV │               │IMV │IMV │ ¬  │ ¬  │
    │IMV │IMV │ ●  │    │               │    │    │IMV │IMV │
    └────┴────┴────┴────┘               └────┴────┴─●──┴────┘
                                                    ▲ event on FIRST non-IMV
```

### The explicit design stance

M2's distinguishing contribution is a **policy position**, not a formula:

```
    ┌──────────────────────────────────────────────────────────────┐
    │  DETECT  extubation whenever 2 non-IMV rows are documented    │
    │          — even if reintubation follows 20 minutes later      │
    │                            │                                  │
    │                            ▼                                  │
    │  LABEL   the subsequent intubation as a reintubation          │
    │                            │                                  │
    │                            ▼                                  │
    │  DO NOT  stitch episodes together inside the package.         │
    │          Emit both episodes + the gap; let each project apply │
    │          its own cutoff (<1h? <24h? never?) downstream.       │
    └──────────────────────────────────────────────────────────────┘
```

@ingra107: *"knowing someone was extubated and intubated quickly is important and then having a way
to stitch at the project level."*

This is a direct contrast with **M3**, which bakes a 24-hour reintubation cutoff into the definition
itself. If the consortium adopts M2's stance, the function returns *all* episodes and stitching
becomes a separate, parameterised utility.

### Behaviour

| | |
|---|---|
| **Catches** | Everything M1 catches, plus episodes one row shorter |
| **Catches** | Rapid extubation→reintubation cycles, as distinct labelled events |
| **Misses** | Already-on-IMV arrivals (same boundary problem as M1) |
| **Misses** | Single-row blips (§9.1) |
| **Open** | ⚠ Comment does not state a NULL policy or an anchor; anchor assumed "first non-IMV" |

---

## 6. Method M3 — Single-transition SQL + outcome classification

**Proposed by** `@whiskey0504` (2026-02-11). The only proposal that classifies *outcomes*, not just events.

Operates on `resp_p`, described as *"a pre-processed respiratory support table"* — what that
pre-processing is remains ⚠ unspecified, and §8.4 shows it dominates the result.

```sql
WINDOW w AS (PARTITION BY hospitalization_id ORDER BY recorded_dttm)
```

### 6.1 Event definition — one row of lookback, no lookahead

```
   intub(i)  ≡  trach(i)=0  ∧  d(i-1) IS DISTINCT FROM 'imv'  ∧  d(i) = 'imv'
   extub(i)  ≡  trach(i)=0  ∧  d(i-1) = 'imv'  ∧  d(i) IS DISTINCT FROM 'imv'
```

```
   i-1    i                           i-1    i
    ┌────┬────┐                        ┌────┬────┐
    │ ¬  │IMV │   INTUBATION           │IMV │ ¬  │   EXTUBATION
    │IMV │ ●  │                        │    │IMV │
    │ or │    │                        │    │ ●  │
    │NULL│    │                        │    │ or │
    └────┴────┘                        │    │NULL│
                                       └────┴────┘
        no lookahead — fires on the first transition it sees
```

**`IS DISTINCT FROM` is the load-bearing detail.** Unlike `!=`, it returns TRUE when the left side
is NULL. Two consequences, one intended and one not:

- **Intended:** at row 1, `LAG(device)` is NULL, so a patient whose first row is IMV *does* get an
  intubation event. This is the only method that handles already-intubated arrivals — but it labels
  them as ordinary intubations, silently merging "intubated here" with "arrived intubated". The
  issue body explicitly asks for these to be *"flag[ged] or handle[d] separately"*; M3 does not.
- **Unintended:** on data with NULL devices, *every NULL row following an IMV row emits an
  extubation*. With the demo's 783 NULL rows this inflates M3 from 65 to 498 intubations (§11.4).
  M3 is only safe on a table where NULLs have already been resolved.

### 6.2 Tracheostomy handling

The only proposal that addresses trach explicitly:

```sql
WHERE (tracheostomy = 0 OR trach_1st = 1)   -- keep pre-trach rows + the trach placement row
```

Rationale: once a tracheostomy is placed, subsequent vent liberation is a clinically different
process and shouldn't be scored as extubation. In the demo, 111 of 3,325 rows carry
`tracheostomy = True`. Under M1/M2/M4 these rows are treated as ordinary IMV, so a trach patient
weaning to a trach collar registers as an **extubation** — almost certainly wrong.

### 6.3 Outcome classification tree

Applied **only to the first extubation** per hospitalization (`extub_1st`, isolated by cumulative
sum). Second and subsequent extubations are not classified.

```
                       extub(i) = 1
                            │
                            ▼
                  ┌──────────────────────┐
                  │ extub_cum = 1 ?      │   running SUM(extub) OVER w
                  └──────────┬───────────┘
                   no │      │ yes  →  extub_1st = 1
                      ▼      ▼
              [not classified]  ┌────────────────────────────────────────┐
                                │  code_status ≠ 'full'                  │
                                │        AND                             │
                                │  discharge ∈ {hospice, expired} ?      │
                                └───────────┬────────────────────────────┘
                                    yes │   │ no
                                        ▼   ▼
                            ┌──────────────┐ ┌────────────────────────────┐
                            │ withdrawl_lst│ │ ∃ intub within (t, t+24h] ? │
                            │  (WLST)      │ └──────────┬─────────────────┘
                            └──────────────┘     yes │  │ no
                                                     ▼  ▼
                                          ┌──────────────┐ ┌────────────────┐
                                          │ fail_extub   │ │ success_extub  │
                                          │ (reintub<24h)│ │                │
                                          └──────────────┘ └────────────────┘

   reintub(i) ≡ intub(i) ∧ not the patient's first intubation
```

Note the **precedence**: WLST is tested *before* failed extubation, so a patient who is reintubated
within 24 h and then dies on hospice is classified WLST, not failed. That ordering is a clinical
judgement embedded in the definition; it is defensible but should be a conscious consortium choice.

Required cross-table joins — all available in CLIF:

| Field | Table | Present in demo |
|---|---|---|
| `code_status_category` | `code_status` | ✅ Full, DNR, DNR/DNI, DNI_only, AND |
| `discharge_category` | `hospitalization` | ✅ incl. `Hospice`, `Expired` |

⚠ `code_status` is keyed on `patient_id` + `start_dttm`, not `hospitalization_id`. "Most recent code
status" must be resolved as *most recent at or before the extubation time, within the encounter* —
the SQL does not say this and the join is nontrivial.

### Behaviour

| | |
|---|---|
| **Catches** | Already-intubated arrivals; every transition, however brief |
| **Catches** | Outcome semantics no other method provides (success / failed / WLST) |
| **Catches** | Trach exclusion |
| **Risk** | Extremely sensitive to NULL devices — unusable on raw data (§8.4) |
| **Risk** | Blip patterns generate spurious event pairs (§9.1) |
| **Limitation** | Only the first extubation is classified; later ones get no outcome |

---

## 7. Method M4 — Strict flags ∪ candidate rescue

**Proposed by** `@wtliao319` (2026-04-06), matching the pattern `@cloverbunny` sketched in her
2026-03-02 screenshot. Described by its author as *"very similar to VC's proposed logic. The only
difference is that we added some handling for irregular records."*

It is a five-stage pipeline. Stages 2.1 and 2.2 are simple; the value is in 2.3 and 2.4.

```
   2.1  strict flags            2 + 2 window, same as M2
             │
   2.2  any-transition flags    imv_start / imv_end, same as M3
             │
             ▼
   2.3  intubation candidates   rows where 2.2 fired but 2.1 didn't,
   2.4  extubation candidates   rescued if a 5-row run confirms them
             │
             ▼
   2.5  UNION  →  intubation_flag_new = strict ∨ candidate
```

### 7.1 Stage 2.1 / 2.2 — strict and permissive layers

```
   strict_in(i) ≡  IMV(i) ∧  IMV(i+1) ∧ ¬IMV(i-1) ∧ ¬IMV(i-2)     (identical to M2 intub)
   strict_ex(i) ≡ ¬IMV(i) ∧ ¬IMV(i+1) ∧  IMV(i-1) ∧  IMV(i-2)     (identical to M2 extub)

   imv_start(i) ≡  IMV(i) ∧ ¬IMV(i-1)                              (identical to M3 intub)
   imv_end(i)   ≡ ¬IMV(i) ∧  IMV(i-1)                              (identical to M3 extub)
```

M4 therefore *contains* M2 and M3 as its two layers. Its contribution is the arbitration between them.

### 7.2 Stage 2.3 — intubation candidate rescue

A row that started IMV but failed the strict test is rescued if the next five rows are all IMV —
i.e. it really was the start of a sustained ventilator course — **and** it is not merely the
continuation of an intubation already in progress:

```
   cand_in(i) ≡  imv_start(i) ∧ ¬strict_in(i)
                 ∧  IMV(i+1..i+5)                        ← 5-row confirmation: this run is real
                 ∧ ( ¬IMV(i-2)  ∨  (IMV(i-2) ∧ ¬IMV(i-3..i-7)) )
                        │                    │
                        │                    └── i-2 was IMV, but it was an isolated blip:
                        │                        rows i-3…i-7 are all non-IMV ⇒ still a new start
                        └── ordinary case: nothing IMV behind us
```

### 7.3 Stage 2.4 — extubation candidate rescue

The mirror image, and the stage that targets @cloverbunny's edge case directly:

```
   cand_ex(i) ≡  imv_end(i) ∧ ¬strict_ex(i)
                 ∧  IMV(i-5..i-1)                        ← 5-row confirmation: real vent course behind
                 ∧ ( ¬IMV(i+2)  ∨  (IMV(i+2) ∧ ¬IMV(i+3..i+7)) )
                                          │
                                          └── IMV briefly returns at i+2, but it doesn't stick:
                                              rows i+3…i+7 are all non-IMV ⇒ this IS the extubation
```

Because `strict_ex` failed while `imv_end` held, `i+1` must be IMV. So `cand_ex` fires precisely on
the pattern **IMV×5 → non-IMV → IMV → non-IMV…** — a one-row dip back onto the vent after the true
extubation.

### 7.4 Cathy's stated rescue rules

The screenshot posted by `@cloverbunny` on 2026-03-02 states the same two patterns in prose:

```
  # update intubation if case like this:
  # non-imv (continuous 5) -> imv -> non-imv -> imv (intubation start candidate) -> imv (continuous 5)

  # update extubation if case like this:
  # imv (continuous 5) -> imv (extubation candidate) -> non-imv -> imv -> non-imv (continuous 5)

  # edge cases (their intubation can be very short period like 2 to 4 rows, so cannot catch them)
```

Her final line is an explicit acknowledgement that **episodes of 2–4 rows remain undetectable** by
any window-based rescue. That is a stated, accepted limitation of the whole M1/M2/M4 family.

### Behaviour

| | |
|---|---|
| **Catches** | Everything M2 catches, plus one-row-blip patterns on both sides |
| **Catches** | Already-intubated arrivals — accidentally, via pandas NaN semantics (§3.1) |
| **Suppresses** | Most of M3's spurious oscillation events, while keeping M3's coverage (§11.2: 94% agreement with M3, with 7 fewer events) |
| **Misses** | Episodes of 2–4 rows, per Cathy's own note |
| **Misses** | Blips where the surrounding run is shorter than 5 rows (§9.1 — the rescue does **not** fire on Cathy's own example) |
| **Fragility** | ⚠ Uses raw pandas `!=` / `~.eq()` on possibly-NA string dtypes. Under numpy `object` dtype `NaN != 'imv'` → `True`; under pandas nullable `StringDtype` it propagates `pd.NA` and `.astype(int)` raises. Behaviour is **dtype-dependent and unstated**. |

---

## 8. Method M5 — Non-device signals *(proposed, not specified)*

**Raised by** `@vaishvikc` (2026-03-02, "Learnings from CHEST run") and attributed in part to Will.

> *Some sites have **no facemask/HFNC/NC device charted**, but **LPM is set**. This suggests
> extubation happened, but **no device name was documented**.*
>
> Additional ideas to test:
> 1. Review two charts where LPM transitions from IMV to two separate LPM chartings.
> 2. Will's idea: check for **cessation of all observed values across two observed rows** as a
>    potential signal.

**No implementation of this exists.** It is catalogued because it identifies a failure mode that is
structurally invisible to M1–M4: if a site never charts a post-extubation device, then
`device_category` simply stops being IMV and becomes NULL, and every device-based method either
forward-fills the patient as still ventilated forever, or fires an extubation on a NULL row.

```
   Site A (device charted)              Site B (device-free charting)
   ───────────────────────              ────────────────────────────
   IMV       device=IMV                 IMV       device=IMV
   IMV       device=IMV                 IMV       device=IMV
   FaceMask  device=Face Mask           NULL      lpm_set=6      ◄── extubation happened here
   NC        device=Nasal Cannula       NULL      lpm_set=4
                                        NULL      (no vent obs)

   M1–M4 detect extubation ✅           M1/M2/M4 under ffill: never extubated ❌
                                        M3 under raw NULL: extubation on a NULL row ⚠
```

### Candidate signals to specify and test

| Signal | Definition sketch | Status |
|---|---|---|
| **S1 — LPM onset** | Two consecutive rows with `lpm_set` non-null following IMV rows, with no `device_category` | ⚠ needs threshold + row-count definition |
| **S2 — Vent-observation cessation** | Two consecutive rows where all of `peep_set`, `resp_rate_set`, `tidal_volume_set`, `peak_inspiratory_pressure_obs`, `minute_vent_obs` become null | ⚠ needs exact field list |
| **S3 — FiO₂ regime shift** | `fio2_set` present but all vent setters absent | not yet proposed |

**Open question for the consortium:** is M5 (a) a fallback applied only at sites that fail a
device-charting completeness check, (b) a universal additional signal unioned into whichever method
wins, or (c) out of scope for `clifpy` and left to site ETL? These have very different implications
for cross-site comparability.

---

## 9. Cross-cutting decision axes

These are **orthogonal to the choice of method**. Every one is currently unresolved, and each must be
decided explicitly — otherwise two sites can implement "the same method" and get different answers.

### 9.1 NULL / forward-fill policy — *highest impact*
Which of `P_ffill` / `P_null≠imv` / `P_drop` / `P_waterfall`? Demo impact: up to **50×** on event
counts (§11.4), illustrated row-by-row in §10.4. **This must be settled before the method choice.**

### 9.2 Pre- vs post-waterfall
@cloverbunny (2026-02-12): *"Wan-Ting also ran some project code by integrating the logic both PRE
and POST waterfall, the results are slightly different but not greatly so … decreases my worry
raised at CLIFATHON about post-waterfall changing stuff too much."*

`clifpy`'s waterfall inserts synthetic hourly scaffold rows at **HH:59:59**, applies device/mode
heuristics, builds run-length IDs and forward-fills numerics. Consequences for event detection:

```
   PRE-waterfall                          POST-waterfall
   ─────────────                          ──────────────
   rows = real chart events               rows = real events + hourly scaffold
   irregular spacing                      ≥1 row/hour, regular
   "2 rows" ≈ 2 clinical observations     "2 rows" may be 2 synthetic hourly rows
   NULL devices present                   devices heuristically imputed
```

**The critical interaction:** every method in this catalog counts *rows*, not *time*. Waterfall
changes what a row means. A 2-row confirmation window is a variable amount of wall-clock time
pre-waterfall and roughly 2 hours post-waterfall. A method tuned pre-waterfall is not the same
method post-waterfall, even with identical code. ⚠ Wan-Ting's "slightly different" result should be
re-measured with the metrics in §12 before it is treated as settled.

### 9.3 Tracheostomy
Only M3 handles it. Options: exclude post-trach rows entirely (M3), treat trach as IMV, or emit a
separate `trach_placement` event and terminate the IMV episode there. 111 demo rows affected.

### 9.4 Patients arriving already on IMV
34 of 110 demo hospitalizations (**31%**) have IMV as their first respiratory row. Options:
(a) no intubation event, episode left-censored — M1/M2; (b) intubation event at first row — M3/M4,
accidentally; (c) intubation event **flagged** `arrived_intubated = true`, which is what the issue
body actually asks for and what **no method implements**.

### 9.5 Zero / near-zero duration episodes
Issue body: *"likely failed intubation attempts, rapid reintubation/extubation events, or data
quality issues, and may require exclusion or special labeling."* Options: emit and flag, or suppress
below a threshold. Consistent with M2's stance, **emit and flag** keeps the decision at project level.
(None appear in the demo — every paired episode exceeds 1 h — so this must be measured at real sites.)

### 9.6 Episode stitching
**Direct conflict in the thread.** M2/`@ingra107` — never stitch inside the package, return all
episodes and let projects apply cutoffs. M3 — bake a 24-hour reintubation window into
`fail_extub`. These are reconcilable: emit unstitched episodes *plus* an optional
`stitch(gap_hours=…)` utility, and derive M3's outcome flags from that.

### 9.7 First vs all extubations
M3 classifies outcomes only for the first extubation. M1/M2/M4 emit all events with no outcomes.
If outcome classification is adopted, does it extend to every extubation?

### 9.8 Event anchoring
§3.1(A). Last-IMV vs first-non-IMV. Directly determines every reported ventilator duration. Must be
fixed globally.

### 9.9 Missing extubation
Issue body: if no extubation is detected, resolve via discharge → `discharged_on_imv`; in-hospital
death → `death_on_imv`; neither → `unknown`. Uncontested in the thread; include in whichever method wins.

---

## 10. Divergence traces

All traces produced by running the four definitions as formalised above over identical input.
`IN` = intubation emitted, `EX` = extubation emitted, `·` = no event.
No forward-fill is applied in §10.1–10.5 so that raw behaviour is visible.

### 10.1 Cathy's blip edge case

Posted by `@cloverbunny` (2026-02-12) as *"a weird edge case that would be missed by our logic"*,
after `@wtliao319` found several in production tables.

```
row  time   device          M1    M2    M3    M4
──────────────────────────────────────────────────
  1  08:00  IMV              ·     ·    IN    IN     ← M3/M4 fire on NULL→imv boundary
  2  08:20  IMV              ·     ·     ·     ·
  3  08:40  IMV              ·     ·     ·     ·
  4  09:00  NIPPV            ·     ·    EX     ·     ← M3 extubates on the blip
  5  09:20  IMV              ·     ·    IN     ·     ← M3 re-intubates
  6  09:40  NIPPV            ·     ·    EX     ·
  7  10:00  NIPPV            ·     ·     ·     ·
  8  10:20  High Flow NC     ·     ·     ·     ·
  9  10:40  High Flow NC     ·     ·     ·     ·
 10  11:00  High Flow NC     ·     ·     ·     ·
──────────────────────────────────────────────────
     TOTAL intub/extub     0/0   0/0   2/2   1/0
```

**This is the catalog's most important result. Three of four methods detect no extubation at all** —
including M4, whose candidate rescue was designed for exactly this pattern. The rescue requires five
consecutive IMV rows behind the candidate, and only three exist. Cathy's own caveat — *"their
intubation can be very short period like 2 to 4 rows, so cannot catch them"* — applies to her own
example.

M3 detects transitions but reads the trace as two separate ventilator courses rather than one
course with a documentation artefact.

Clinically the patient was almost certainly extubated once, at 09:00 or 10:00. **No proposed method
returns that.**

### 10.2 Clean textbook course — where everyone agrees on *events*

```
row  time   device          M1    M2    M3    M4
──────────────────────────────────────────────────
  1  08:00  Nasal Cannula    ·     ·     ·     ·
  2  08:20  Nasal Cannula    ·     ·     ·     ·
  3  08:40  IMV             IN    IN    IN    IN     ← unanimous
  4  09:00  IMV              ·     ·     ·     ·
  5  09:20  IMV              ·     ·     ·     ·
  6  09:40  IMV             EX     ·     ·     ·     ← M1 anchors on LAST IMV
  7  10:00  Face Mask        ·    EX    EX    EX     ← others anchor on FIRST non-IMV
  8  10:20  Face Mask        ·     ·     ·     ·
  9  10:40  Nasal Cannula    ·     ·     ·     ·
──────────────────────────────────────────────────
     TOTAL intub/extub     1/1   1/1   1/1   1/1
```

All four agree there was one intubation and one extubation — yet **M1's ventilator duration is 20
minutes shorter than everyone else's**, purely from anchoring. On real data with hours between
charted rows, this systematically biases duration downward.

### 10.3 Arrives already intubated

```
row  time   device          M1    M2    M3    M4
──────────────────────────────────────────────────
  1  08:00  IMV              ·     ·    IN    IN     ← boundary policy decides everything
  2  08:20  IMV              ·     ·     ·     ·
  3  08:40  IMV              ·     ·     ·     ·
  4  09:00  IMV             EX     ·     ·     ·
  5  09:20  Nasal Cannula    ·    EX    EX    EX
  6  09:40  Nasal Cannula    ·     ·     ·     ·
──────────────────────────────────────────────────
     TOTAL intub/extub     0/1   0/1   1/1   1/1
```

M1/M2 emit an **orphan extubation** — an extubation with no matching intubation. M3/M4 emit a
matched pair but claim the intubation happened at 08:00, which is false; it happened before the
data. Neither is right. The correct output is the issue body's own request: an extubation plus an
intubation flagged `arrived_intubated`, with the start time marked unknown. **31% of demo
hospitalizations hit this case.**

### 10.4 NULL `device_category` interleaved — no forward-fill

```
row  time   device          M1    M2    M3    M4
──────────────────────────────────────────────────
  1  08:00  IMV              ·     ·    IN     ·
  2  08:20  ░░NULL░░         ·     ·    EX     ·     ← spurious
  3  08:40  IMV              ·     ·    IN     ·     ← spurious
  4  09:00  ░░NULL░░         ·     ·    EX     ·     ← spurious
  5  09:20  ░░NULL░░         ·     ·     ·     ·
  6  09:40  IMV              ·     ·    IN     ·     ← spurious
  7  10:00  Nasal Cannula    ·     ·    EX     ·     ← the only real extubation
  8  10:20  Nasal Cannula    ·     ·     ·     ·
──────────────────────────────────────────────────
     TOTAL intub/extub     0/0   0/0   3/3   0/0
```

One patient, one ventilator course, one extubation. **M3 reports three intubations and three
extubations; M1/M2/M4 report none.** This single row pattern — which describes 23.5% of the demo
table — is why §9.1 must be resolved first.

### 10.5 Failed extubation with reintubation

```
row  time   device          M1    M2    M3    M4
──────────────────────────────────────────────────
  1  08:00  Nasal Cannula    ·     ·     ·     ·
  2  08:20  Nasal Cannula    ·     ·     ·     ·
  3  08:40  IMV             IN    IN    IN    IN
  4  09:00  IMV              ·     ·     ·     ·
  5  09:20  IMV             EX     ·     ·     ·
  6  09:40  Face Mask        ·    EX    EX    EX     ← extubation #1
  7  10:00  Face Mask        ·     ·     ·     ·
  8  10:20  IMV             IN    IN    IN    IN     ← reintubation (40 min later)
  9  10:40  IMV              ·     ·     ·     ·
 10  11:00  IMV              ·     ·     ·     ·
 11  11:20  IMV             EX     ·     ·     ·
 12  11:40  Nasal Cannula    ·    EX    EX    EX     ← extubation #2
 13  12:00  Nasal Cannula    ·     ·     ·     ·
──────────────────────────────────────────────────
     TOTAL intub/extub     2/2   2/2   2/2   2/2
```

Full agreement on event **count and position** (modulo anchoring). The methods diverge only on
*interpretation*: M2 emits two episodes and lets the project stitch; M3 additionally labels
extubation #1 `fail_extub = 1` because reintubation occurred within 24 h, and classifies nothing
about extubation #2 (only the first is classified).

Clean cases like this are where the thread's intuition that the methods are "basically the same"
comes from. §10.1 and §10.4 show where that intuition breaks.

---

## 11. Illustrative behaviour on the CLIF demo dataset

> ⚠ **These are demo-data figures, not site results.** 3,325 rows / 110 hospitalizations from the
> public CLIF demo set, which is small and MIMIC-derived. They are included to show the *shape and
> magnitude* of divergence, not to rank methods. Real ranking comes from the rubric in §12.

### 11.1 Event yield, forward-fill applied

```
 method   intubations   extubations   hosp w/ intub   hosp w/ extub   extub-only hosp
 ─────────────────────────────────────────────────────────────────────────────────────
 M1             9            42             8              39              34
 M2            10            46             8              42              37
 M3            65            51            59              45               0
 M4            62            47            58              43               0
 ─────────────────────────────────────────────────────────────────────────────────────
 59 of 110 hospitalizations contain at least one IMV row.
 34 of 110 begin with IMV as the first respiratory row (arrived ventilated).
```

**M1 and M2 detect intubation in 8 of 59 ventilated encounters — a 14% detection rate** — and
produce 34–37 encounters with an extubation but no intubation. M3/M4 have zero orphans, but only
because their boundary semantics manufacture an intubation at row 1.

The ~7× spread in intubation count (9 → 65) is the effect of the transition rule alone; NULL policy
is held constant here.

### 11.2 Pairwise event agreement (exact row + type match, forward-fill applied)

```
 pair       agreed   only-A   only-B   Jaccard
 ────────────────────────────────────────────────
 M1 vs M2       9       42       47      0.09   ◄── zero extubation agreement
 M1 vs M3       9       42      107      0.06
 M1 vs M4       9       42      100      0.06
 M2 vs M3      56        0       60      0.48
 M2 vs M4      56        0       53      0.51
 M3 vs M4     109        7        0      0.94   ◄── near-identical
 ────────────────────────────────────────────────
```

Two results worth stating plainly:

- **M1 vs M2 agree on all 9 intubations and on none of the 88 extubations.** They are described in
  the thread as the same approach. The disagreement is 100% anchoring (§3.1 A), not clinical logic.
- **M3 and M4 agree 94%** — M4 is effectively M3 with 7 spurious events suppressed. Once NULLs are
  resolved, choosing between them is a marginal decision; choosing between {M1, M2} and {M3, M4} is not.

### 11.3 Episode duration (intubation → next extubation)

```
 method  paired episodes   median      IQR            max      <1 h
 ──────────────────────────────────────────────────────────────────
 M1             6           66.5 h    21.5 – 83.2    113.0 h     0
 M2             7           65.0 h    13.2 – 79.9    117.0 h     0
 M3            51           21.0 h     5.8 – 70.5    355.0 h     0
 M4            47           24.1 h     7.7 – 76.5    355.0 h     0
 ──────────────────────────────────────────────────────────────────
```

**Median ventilator duration differs 3-fold between method families** (66 h vs 21 h) on identical
data. M1/M2 pair only 6–7 episodes out of 59 ventilated encounters, and the ones they pair are the
long clean courses — a textbook selection bias. Any study reporting "mean duration of mechanical
ventilation" is reporting a property of its detection method as much as of its patients.

### 11.4 Sensitivity to NULL policy — the dominant effect

```
                    ffill applied          raw, no ffill        ratio
                  intub    extub         intub    extub
 ──────────────────────────────────────────────────────────────────────
 M1                  9        42             2        2          0.2×
 M2                 10        46             3        8          0.3×
 M3                 65        51           498      485         7.7×   ◄──
 M4                 62        47            98      118         1.6×
 ──────────────────────────────────────────────────────────────────────
```

M3 goes from 65 to **498** intubations — every NULL row adjacent to an IMV row becomes a transition.
M1/M2 collapse the other way, because a NULL breaks their consecutive-row requirement.

Across the full grid the spread is **2 → 498 events, ~250×**, versus ~7× for the transition rule at
fixed NULL policy. **The pre-processing decision matters roughly an order of magnitude more than the
method decision.** This is the single most actionable finding in the catalog.

---

## 12. Validation rubric

Three tiers, ordered cheapest-first. Tier 0 runs everywhere and needs no labels; Tier 1 is
automatable; Tier 2 is expensive and therefore spent only where the cheaper tiers show disagreement.

```
        ┌─────────────────────────────────────────────────────────────┐
        │  TIER 0 — Label-free    every site, every method, mandatory │
        │  concordance + internal consistency + clinical plausibility │
        │  cost: compute only            → can only find disagreement │
        └───────────────────────────┬─────────────────────────────────┘
                                    │ methods passing gates
                                    ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  TIER 1 — Code-referenced        every site, automatable    │
        │  encounter-level vs procedure/billing codes                 │
        │  cost: compute only          → PRESENCE only, never timing  │
        └───────────────────────────┬─────────────────────────────────┘
                                    │ enriched by disagreement
                                    ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  TIER 2 — Chart review     sampled, disagreement-enriched   │
        │  human adjudication of ~50–100 encounters per site          │
        │  cost: clinician time       → the only tier that scores     │
        │                                event timing                 │
        └─────────────────────────────────────────────────────────────┘
```

### 12.1 Tier 0 — label-free metrics

Every metric is computed **per method × per site × per NULL policy**, so that §9.1 and §9.2 are
measured rather than assumed.

| ID | Metric | Why it matters |
|---|---|---|
| **R0.1** | Intubations and extubations per 1,000 hospitalizations | Gross yield; catches wildly over/under-calling |
| **R0.2** | **Detection coverage** — % of encounters with ≥1 IMV row that yield ≥1 intubation | Demo: M1 = 14%. A method that cannot find intubations in ventilated patients is disqualified |
| **R0.3** | **Orphan rate** — % extubations with no preceding intubation; % intubations with no following extubation | Demo: M1 34/39 encounters extub-only. Distinguishes true left-censoring from detection failure |
| **R0.4** | Episode duration median / IQR / max; % < 1 h; % > 30 d; % exceeding hospital LOS | Duration is the most-used downstream variable; §11.3 shows 3× method effects |
| **R0.5** | **Temporal validity** — events before `admission_dttm`, after `discharge_dttm`, or after death | Hard errors. Any nonzero count is a defect |
| **R0.6** | **Inter-method concordance** — pairwise Jaccard at event level (exact, and with ±1 h / ±4 h tolerance) and at encounter level | Separates genuine disagreement from pure anchoring offset |
| **R0.7** | **Pre-processing stability** — every metric above computed pre- and post-waterfall; report the ratio | Directly settles §9.2; re-tests Wan-Ting's "slightly different" |
| **R0.8** | **Device-charting completeness** — % IMV episodes ending in a charted non-IMV device vs NULL | Identifies M5 sites (§8); a site failing this makes all other results uninterpretable |

**Proposed gates** (⚠ for consortium ratification, not yet agreed):

```
   R0.2  detection coverage        ≥ 80% of ventilated encounters
   R0.3  orphan extubation rate    ≤ 10% + the site's arrived-intubated rate
   R0.5  temporal violations       = 0
   R0.4  episodes exceeding LOS    = 0
```

A method must pass at **every** site, not on average. Cross-site *stability* is the point of the
exercise: a method with mediocre-but-identical behaviour everywhere is more useful to the consortium
than one that is excellent at three sites and broken at a fourth.

### 12.2 Tier 1 — procedure-code reference

Score each method at the **encounter level** against procedure/billing codes.

```
                    code says intubated
                        yes        no
                    ┌──────────┬──────────┐
   method     yes   │    TP    │    FP    │      sensitivity = TP/(TP+FN)
   detects          ├──────────┼──────────┤      PPV         = TP/(TP+FP)
              no    │    FN    │    TN    │      F1
                    └──────────┴──────────┘
```

Reference codes (all four formats present in CLIF `patient_procedures`; demo contains
`0BH17EZ` ×11, `5A1945Z`, `5A1955Z`, ICD-9 `9604`, `9671`, `9672`):

| Format | Codes | Meaning |
|---|---|---|
| ICD-10-PCS | `0BH17EZ`, `0BH18EZ` | Insertion of endotracheal airway |
| ICD-10-PCS | `5A1935Z`, `5A1945Z`, `5A1955Z` | Mechanical ventilation <24 h / 24–96 h / >96 h |
| ICD-9 | `9604` | Insertion of endotracheal tube |
| ICD-9 | `9670`, `9671`, `9672` | Continuous mechanical ventilation |
| CPT | `31500` | Emergency endotracheal intubation |

**Two hard constraints on how Tier 1 may be used:**

1. **Presence only, never timing.** The column is `procedure_billed_dttm` — a billing timestamp,
   frequently day-granular or backdated to admission. It can confirm *that* an encounter involved
   intubation; it cannot confirm *when*. Any rubric that scores timing against these codes will
   overstate accuracy.
2. **Codes are a reference, not truth.** Coding completeness varies by site, payer and era. Report
   each site's **code capture rate** first — the % of encounters with ≥1 IMV row that carry any vent
   code. Where that rate is implausibly low, Tier 1 is uninformative at that site and should be
   reported as such rather than scored.

### 12.3 Tier 2 — chart review

The only tier that establishes ground truth for **timing**. Expensive, so sample deliberately.

**Stratified sampling frame** (target ~50–100 encounters per site):

| Stratum | Selection | Purpose |
|---|---|---|
| **S-A** Unanimous | All 4 methods agree on events and timing | Detects a *shared* blind spot — if all four are wrong together, no concordance metric can reveal it |
| **S-B** Split | Methods disagree on event count or position | Where the decision actually gets made — spend most of the budget here |
| **S-C** Silent | ≥1 IMV row but ≥1 method emits no event | Tests §9.4 and detection failure |
| **S-D** Extreme | Zero/near-zero duration, or duration > 30 d, or orphan events | Tests §9.5 |
| **S-E** Device-free | Encounters flagged by R0.8 | Tests whether M5 signals are real |

**Adjudication form** — one row per encounter, filled by a clinician blind to method output:

```
   was the patient invasively ventilated this encounter?     Y / N
   arrived already intubated?                                Y / N
   intubation #1 datetime (or UNKNOWN — arrived intubated)   ____
   extubation #1 datetime (or NONE)                          ____
   extubation #1 outcome:   success / reintubated ≤24h / WLST / trach / died on IMV
   tracheostomy placed this encounter?                       Y / N + datetime
   additional intubation/extubation pairs                    ____
   free text: what made this hard?                           ____
```

**Metrics:** event-level sensitivity and PPV against adjudicated events (match tolerance ±1 h and
±4 h, reported separately); **median absolute timestamp error in minutes**, reported separately for
intubation and extubation; outcome-classification accuracy for M3's tree.

### 12.4 Decision procedure

```
   1.  FIRST fix the NULL/pre-processing policy (§9.1, §9.2).
       Rubric metrics are not comparable across different policies, and §11.4 shows
       the policy dominates the method. Use R0.7 + R0.8 to choose it.

   2.  Apply Tier 0 gates at every site.  Eliminate methods that fail anywhere.

   3.  Rank survivors by Tier 1 encounter-level F1, reported per site.
       Prefer low cross-site variance over high mean.

   4.  Break remaining ties with Tier 2 sensitivity / PPV, then timestamp error.

   5.  Decide the cross-cutting axes (§9.3–§9.9) as explicit parameters of the
       chosen method, not as silent implementation details.
```

**Reporting constraints** (per [`output/README.md`](../output/README.md) and
[`guides/primer.md`](../guides/primer.md)): only aggregate results leave a site; minimum cell size
**n ≥ 10** for every reported statistic; no `patient_id`, no row-level records, no raw
`.csv`/`.parquet` in `output/final_no_phi/`. Chart-review adjudications are PHI and stay in
`output/intermediate_phi/`.

---

## 13. Summary comparison

| | **M1** | **M2** | **M3** | **M4** | **M5** |
|---|---|---|---|---|---|
| Proposer | `@vaishvikc` | `@cloverbunny` | `@whiskey0504` | `@wtliao319` | `@vaishvikc` / Will |
| Notation | prose | prose | SQL | pandas | idea only |
| Intub window | 2 + 3 | 2 + 2 | 1 + 0 | 2+2 ∪ rescue | n/a |
| Extub window | 3 + 2 | 2 + 2 | 1 + 0 | 2+2 ∪ rescue | n/a |
| Extub anchor | last IMV | first ¬IMV | first ¬IMV | first ¬IMV | n/a |
| NULL policy | ffill | ⚠ unstated | NULL = ¬IMV | NULL = ¬IMV | uses NULLs as signal |
| Boundary | ⚠ unstated | ⚠ unstated | permissive | permissive | n/a |
| Arrived intubated | missed | missed | unlabelled event | unlabelled event | n/a |
| Tracheostomy | ✗ | ✗ | ✅ excluded | ✗ | ✗ |
| Reintubation | ✗ | ✅ labelled | ✅ + 24 h rule | ✗ | ✗ |
| Outcome tree | ✗ | ✗ | ✅ | ✗ | ✗ |
| Stitching stance | — | never stitch | 24 h baked in | — | — |
| Blip handling | ✗ | ✗ | over-calls | partial (needs 5-row run) | ✗ |
| Device-free sites | ✗ | ✗ | ✗ | ✗ | ✅ target |
| Robust to raw NULLs | under-calls | under-calls | **fails (7.7×)** | moderate | n/a |

### What the catalog establishes

1. **No proposed method is correct on Cathy's own edge case** (§10.1) — three detect no extubation,
   one splits it into two courses.
2. **M1 ≠ M2** despite being discussed as one approach: different window widths and different
   extubation anchors, giving **zero** extubation agreement (§11.2).
3. **M3 ≈ M4** (94% agreement) once NULLs are resolved. The real choice is between families
   {M1, M2} and {M3, M4}, not within them.
4. **NULL/pre-processing policy outweighs method choice by ~10×** (§11.4) and must be decided first.
5. **31% of encounters arrive already ventilated**, and the correct behaviour the issue body asks
   for — an intubation flagged with unknown start time — **is implemented by nobody**.
6. **M3 alone provides outcome semantics**; M2 alone provides an explicit stitching policy. These
   are complementary and could be combined regardless of which transition rule wins.

### Open decisions for the consortium

```
   [ ]  §9.1  NULL / forward-fill policy                        ← decide first
   [ ]  §9.2  pre- vs post-waterfall                            ← decide first
   [ ]  §9.3  tracheostomy handling
   [ ]  §9.4  arrived-intubated: censor, event, or flag
   [ ]  §9.5  zero-duration episodes: suppress or flag
   [ ]  §9.6  stitching: package-level or project-level
   [ ]  §9.7  outcome classification: first extubation or all
   [ ]  §9.8  event anchoring: last-IMV or first-non-IMV
   [ ]  §9.9  missing extubation resolution  (uncontested — adopt)
   [ ]  §8    M5 device-free sites: fallback, universal, or out of scope
   [ ]  §12   ratify Tier 0 gate thresholds
```

---

## Appendix A — Source material, verbatim

Preserved so that nothing is lost in the normalisation above.

### A.1 — M1, issue body (`@vaishvikc`)

> **Current Logic**
> We use the respiratory support table with a longitudinal "waterfall" approach:
> - Group by hospitalization
> - Sort by recorded datetime
> - Forward-fill `device_category`
> - Generate lag and lead columns
>
> **Intubation Definition**
> `is_no_imv` (lag 2) · `is_no_imv` (lag 1) · `is_imv` (current) · `is_imv` (lead 1) · `is_imv` (lead 2)
>
> **Extubation Definition**
> `is_imv` (lag 2) · `is_imv` (lag 1) · `is_imv` (current) · `is_no_imv` (lead 1) · `is_no_imv` (lead 2)

Requested outputs: device before/after intubation and extubation; mode before/after each; location
category at intubation and extubation; episode ID; intubation start datetime; extubation end
datetime; time from intubation to extubation.

Stated edge cases: patients arriving already on IMV (start time unknown or preceding available data
— *"logic is needed to flag or handle these episodes separately"*); zero/near-zero delta between
intubation and extubation; no extubation identified (→ discharged on IMV / death on IMV / unknown).

### A.2 — M2, `@cloverbunny` 2026-02-10

> Yes, the two look back/look-forward device approach is what we use in our project; we previously
> constructed a pipeline that used a variety of different flowsheet elements that were inconsistently
> documented as well as intubation notes because we wanted to capture some of those super-short
> extubation cases, but I think now that those are hard to consistently accurately identify and this
> kind of standardization will work for majority of projects.
>
> Mode may be absent depending on device.
>
> While we are doing this, I think we also want to identify reintubation - in our project we just
> look forward to next period of intubation using same flag logic, and people can later implement
> whatever cutoffs they want.
>
> We've discussed in the time frame is very short (<1hr of extubation) if the intubation episode 1
> and 2 should be stitched together, but I think it depends on the project. I think that as long as
> there is documented non-IMV devices x2 rows, this should be flagged as extubation then people can
> stitch them together later if they want.

`@ingra107`, same day:

> agree with Cathy... knowing someone was extubated and intubated quickly is important and then
> having a way to stitch at the project level

### A.3 — M3, `@whiskey0504` 2026-02-11

Source table `resp_p`, *"a pre-processed respiratory support table partitioned by
`hospitalization_id` and ordered by `recorded_dttm`"*. All events defined on non-tracheostomy rows.

```sql
WINDOW w AS (PARTITION BY hospitalization_id ORDER BY recorded_dttm)

, intub: CASE
    WHEN tracheostomy = 0                                          -- not on tracheostomy
        AND LAG(device_category) OVER w IS DISTINCT FROM 'imv'     -- previous row is not IMV (or NULL)
        AND device_category = 'imv'                                -- current row is IMV
    THEN 1 ELSE 0 END

, extub: CASE
    WHEN tracheostomy = 0
        AND LAG(device_category) OVER w = 'imv'
        AND device_category IS DISTINCT FROM 'imv'
    THEN 1 ELSE 0 END

, extub_cum: SUM(extub) OVER w                                     -- running count of extubations
, extub_1st: CASE WHEN extub = 1 AND extub_cum = 1 THEN 1 ELSE 0 END

, withdrawl_lst: CASE
    WHEN extub_1st = 1
    AND TRIM(LOWER(code_status_category)) != 'full'
    AND TRIM(LOWER(discharge_category)) in ('hospice', 'expired')
    THEN 1 ELSE 0 END

, fail_extub: CASE
    WHEN extub_1st = 1 AND EXISTS (
        SELECT 1 FROM t1
        WHERE t1.hospitalization_id = t2.hospitalization_id
          AND t1.intub = 1
          AND t1.recorded_dttm >  t2.recorded_dttm
          AND t1.recorded_dttm <= t2.recorded_dttm + INTERVAL 24 HOUR
    ) THEN 1 ELSE 0 END

, success_extub: CASE
    WHEN extub_1st = 1 AND withdrawl_lst = 0 AND fail_extub = 0
    THEN 1 ELSE 0 END
```

Tracheostomy note:

```sql
WHERE (tracheostomy = 0 OR trach_1st = 1)   -- keep pre-trach rows plus the trach placement row
```

> Only the **first** extubation per hospitalization is evaluated — all outcome flags are conditioned
> on `extub_1st = 1`. Second and subsequent extubations are not classified.
> A **reintubation** is any intubation event (`intub = 1`) that is not the patient's first
> intubation — i.e. it follows a prior extubation.

### A.4 — Cathy's blip edge case, `@cloverbunny` 2026-02-12

> Weird edge case example that would be missed by our logic, @wtliao319 found several of these in
> our tables (table hypothetical example with made up timestamps)

| timestamp | device_name | device_category |
|---|---|---|
| 2024-01-01 08:00 | Ventilator | IMV |
| 2024-01-01 08:20 | Ventilator | IMV |
| 2024-01-01 08:50 | Ventilator | IMV |
| 2024-01-01 09:10 | Bi-PAP | NIPPV |
| 2024-01-01 09:40 | Ventilator | IMV |
| 2024-01-01 10:00 | Bi-PAP | NIPPV |
| 2024-01-01 10:30 | Bi-PAP | NIPPV |
| 2024-01-01 10:50 | HiFlo nasal cannula - heat | High Flow NC |
| 2024-01-01 11:20 | HiFlo nasal cannula - heat | High Flow NC |
| 2024-01-01 11:40 | HiFlo nasal cannula - heat | High Flow NC |

Same day, on pre/post waterfall:

> Wan-Ting also ran some project code by integrating the logic both PRE and POST waterfall, the
> results are slightly different but not greatly so, interested in others thoughts, decreases my
> worry raised at CLIFATHON about post-waterfall changing stuff too much

### A.5 — M5, `@vaishvikc` 2026-03-02

> **Learnings from CHEST run**
> - Some sites have **no facemask/FHNC/NC device charted**, but **LPM is set**.
>   - This suggests extubation happened, but **no device name was documented**.
>
> **Additional ideas to test**
> 1. Review two charts where LPM transitions from **IMV to two separate LPM chartings**.
> 2. Will's idea: check for **cessation of all observed values across two observed rows** as a
>    potential signal.

Cathy's rescue-rule screenshot, same day:

```
# update intubation if case like this:
# non-imv (continuous 5) -> imv -> non-imv -> imv (intubation start candidate)  -> imv (continuous 5)

# update extubation if case like this:
# imv (continuous 5) -> imv (extubation candidate) -> non-imv -> imv -> non-imv (continuous 5)

# edge cases (their intubation can be very short period like 2 to 4 rows, so cannot catch them)
```

### A.6 — M4, `@wtliao319` 2026-04-06

> the function we used in a previous project. it's very similar to VC's proposed logic. The only
> difference is that we added some handling for irregular records to better define the intubation
> events

```python
def find_intubation_extubation_events(resp_df_micu, verbose=True):
    """
    Find intubation and extubation events from respiratory support data.

    Uses a multi-step approach:
    - 2.1 Strict flags (require 2 consecutive devices on each side)
    - 2.2 IMV transition flags (any single transition)
    - 2.3 Intubation candidates (missed by strict flag, validated by lookahead)
    - 2.4 Extubation candidates (missed by strict flag, validated by lookback)
    - 2.5 Combined new flags
    """
    resp_df_micu_sub = resp_df_micu[['hospitalization_id', 'recorded_dttm', 'device_category']].copy()
    resp_df_micu_sub['recorded_dttm'] = pd.to_datetime(resp_df_micu_sub['recorded_dttm'])

    # Shifted device columns (within each hospitalization)
    g = resp_df_micu_sub.groupby('hospitalization_id')['device_category']
    resp_df_micu_sub['prev_device_1'] = g.shift(1)
    resp_df_micu_sub['prev_device_2'] = g.shift(2)
    resp_df_micu_sub['next_device_1'] = g.shift(-1)
    resp_df_micu_sub['next_device_2'] = g.shift(-2)

    dev   = resp_df_micu_sub['device_category'].str.lower()
    prev1 = resp_df_micu_sub['prev_device_1'].str.lower()
    prev2 = resp_df_micu_sub['prev_device_2'].str.lower()
    next1 = resp_df_micu_sub['next_device_1'].str.lower()
    next2 = resp_df_micu_sub['next_device_2'].str.lower()

    # 2.1 Strict intubation/extubation flags
    resp_df_micu_sub['intubation_flag'] = (
        (dev == 'imv') & (next1 == 'imv') & (prev1 != 'imv') & (prev2 != 'imv')
    ).astype(int)
    resp_df_micu_sub['extubation_flag'] = (
        (dev != 'imv') & (next1 != 'imv') & (prev1 == 'imv') & (prev2 == 'imv')
    ).astype(int)

    # 2.2 Any IMV transition flags
    resp_df_micu_sub['imv_start_flag'] = ((dev == 'imv') & (prev1 != 'imv')).astype(int)
    resp_df_micu_sub['imv_end_flag']   = ((dev != 'imv') & (prev1 == 'imv')).astype(int)

    # 2.3 Intubation candidates
    candidate_mask = (resp_df_micu_sub['imv_start_flag'] == 1) & (resp_df_micu_sub['intubation_flag'] == 0)
    next_shifts = {n: g.shift(-n).str.lower() for n in range(1, 6)}
    all_next_5_imv = (next_shifts[1].eq('imv') & next_shifts[2].eq('imv') &
                      next_shifts[3].eq('imv') & next_shifts[4].eq('imv') & next_shifts[5].eq('imv'))
    prev_shifts = {n: g.shift(n).str.lower() for n in range(3, 8)}
    prev_2_is_imv = prev2 == 'imv'
    prev_3_to_7_non_imv = (prev_shifts[3].ne('imv') & prev_shifts[4].ne('imv') &
                           prev_shifts[5].ne('imv') & prev_shifts[6].ne('imv') & prev_shifts[7].ne('imv'))
    prev_check = ~prev_2_is_imv | (prev_2_is_imv & prev_3_to_7_non_imv)
    resp_df_micu_sub['intubation_candidate'] = (candidate_mask & all_next_5_imv & prev_check).astype(int)

    # 2.4 Extubation candidates
    ext_candidate_mask = (resp_df_micu_sub['imv_end_flag'] == 1) & (resp_df_micu_sub['extubation_flag'] == 0)
    prev_imv = {n: g.shift(n).str.lower().eq('imv') for n in range(1, 6)}
    all_prev_5_imv = prev_imv[1] & prev_imv[2] & prev_imv[3] & prev_imv[4] & prev_imv[5]
    next_ext_shifts = {n: g.shift(-n).str.lower() for n in range(3, 8)}
    next_2_is_non_imv = next2 != 'imv'
    next_3_to_7_non_imv = (next_ext_shifts[3].ne('imv') & next_ext_shifts[4].ne('imv') &
                           next_ext_shifts[5].ne('imv') & next_ext_shifts[6].ne('imv') & next_ext_shifts[7].ne('imv'))
    next_check = next_2_is_non_imv | (~next_2_is_non_imv & next_3_to_7_non_imv)
    resp_df_micu_sub['extubation_candidate'] = (ext_candidate_mask & all_prev_5_imv & next_check).astype(int)

    # 2.5 Combined new flags
    resp_df_micu_sub['intubation_flag_new'] = (
        (resp_df_micu_sub['intubation_flag'] == 1) | (resp_df_micu_sub['intubation_candidate'] == 1)
    ).astype(int)
    resp_df_micu_sub['extubation_flag_new'] = (
        (resp_df_micu_sub['extubation_flag'] == 1) | (resp_df_micu_sub['extubation_candidate'] == 1)
    ).astype(int)

    if (dev == 'imv').sum() == 0:
        raise ValueError("No IMV records found - cannot identify intubation events")

    return resp_df_micu_sub
```

### A.7 — Project directive, `@kaveriC` 2026-07-13

> @kaveriC @vaishvikc - create a new test project with different definitions discussed above

---

## Appendix B — Requested output schema

Consolidated from the issue body (A.1) plus fields implied by M2 and M3. One row per IMV episode.

| Field | Source | Notes |
|---|---|---|
| `hospitalization_id` | respiratory_support | |
| `episode_id` | derived | sequential within hospitalization |
| `intubation_dttm` | respiratory_support | null when `arrived_intubated` |
| `extubation_dttm` | respiratory_support | null when no extubation detected |
| `imv_duration_hours` | derived | ⚠ depends on anchoring (§9.8) |
| `device_before_intubation` / `device_after_intubation` | respiratory_support | |
| `mode_before_intubation` / `mode_after_intubation` | respiratory_support | ⚠ often null (§2) |
| `device_before_extubation` / `device_after_extubation` | respiratory_support | |
| `mode_before_extubation` / `mode_after_extubation` | respiratory_support | ⚠ often null |
| `location_category_at_intubation` / `_at_extubation` | adt | join on time-in-location interval |
| `arrived_intubated` | derived | §9.4 — requested by A.1, implemented by nobody |
| `is_reintubation` | derived | M2 |
| `hours_since_prior_extubation` | derived | M2 — enables project-level stitching |
| `no_extubation_reason` | hospitalization | `discharged_on_imv` / `death_on_imv` / `unknown` (A.1) |
| `extubation_outcome` | derived | M3 — `success` / `failed` / `wlst` |
| `tracheostomy_placed` / `tracheostomy_dttm` | respiratory_support | M3 (§6.2) |
| `zero_duration_flag` | derived | §9.5 |
| `method_id` | — | which definition produced this row; required for the comparison harness |

---

## Appendix C — Reproducing the figures

All counts, traces and agreement statistics in §10–§11 were produced by implementing M1–M4 exactly
as formalised in §4–§7 and running them over `clif_demo/clif_respiratory_support.parquet`
(3,325 rows, 110 hospitalizations).

The verification script is **not** part of the project deliverable — the production implementation
belongs to the comparison harness specified separately. Conventions applied when a proposal was
silent are listed in §3.1 and flagged ⚠ at each point of use.

**Known limitations of these figures:** the CLIF demo set is small, MIMIC-derived, and not
representative of consortium site data — in particular its 31% arrived-intubated rate and 23.5% NULL
device rate will differ elsewhere. Figures show the *shape* of divergence; they do not rank methods.
Ranking requires §12 run at real sites.
