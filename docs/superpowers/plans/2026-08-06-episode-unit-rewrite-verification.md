# Episode Unit Rewrite — Verification Record

Plan: [`2026-08-06-episode-unit-rewrite.md`](2026-08-06-episode-unit-rewrite.md)
Branch: `episode-unit-rewrite` · Site: MIMIC · `cohort_run_id` `2026-08-06T14:03:41`

## 1. Clean run

All seven notebooks pass, run in sequence from empty `intermediate_phi/`.

| notebook | result |
|---|---|
| `01_cohort.py` | PASS |
| `02_index_imv.py` | PASS — §5.9 worked examples (a)–(g) pass before any data loads |
| `03_method_sedative.py` | PASS |
| `04_method_paralytic.py` | PASS |
| `05_method_pair.py` | PASS — §7.3 worked examples (a)–(f) pass |
| `06_reference_cpt.py` | PASS |
| `07_agreement.py` | PASS — output manifest conforms to §8, 34 artifacts |

## 2. Headline counts against the spec

| | got | expected | |
|---|---|---|---|
| candidate episodes | 42,488 | 42,488 | OK |
| sustained (rule 2) | 40,270 | 40,270 | OK |
| qualified episodes | 13,500 | 13,500 | OK |
| qualified blocks | 12,503 | 12,503 | OK |
| qualified patients | 11,935 | 11,935 | OK |
| `no_lookback` | 7,130 | 7,130 | OK |
| reintubations (`ep_num > 1`) | 1,940 | ~~997~~ 1,940 | **expectation corrected** |
| `intubation_episode_id` unique | yes | yes | OK |

**The reintubation expectation was wrong, not the code.** 997 came from a prototype that
numbered `ep_num` over the *qualified* set. The implementation numbers over the *sustained*
set: 1,940 qualified episodes have an earlier sustained episode in their block, against 997
with an earlier qualified one. Sustained numbering is correct — a `no_induction_med` episode
is still a real ventilation episode, so an intubation following one genuinely is the block's
second. Numbering only qualified episodes would also make Tier D.2 circular, since "an
earlier episode also had induction charted" describes the filter rather than the patient.
Spec §5.10, §5.11, §6.1, D35 and the flow doc were corrected to 1,940 in 1,654 blocks.

## 3. Defects found and fixed

Five, four of them caught by assertions the plan added rather than by inspection.

**1 — `cohort_resp_imv_raw` spanned the pre-exclusion block set.** `resp_raw` is built from
`encounter_mapping`, which covers every stitched block including the 1,125 later removed by
the trach exclusion. Caught on the first run by the projection's own block-count assertion
(`-1,125 cohort blocks have no raw charted imv row`). Fixed with a semi-join to `cohort`,
matching how the waterfall is already scoped.

**2 — `ep_num` collision for rejected candidates.** Filling rejected rows with a
chronological rank over the whole block collides with the numbering already assigned to that
block's sustained rows: a block whose rejected candidate sorts first emits two rows numbered
`E1`. Caught in a five-line scratch test before the first run. Rejected candidates now
continue *after* the block's real episodes — which is also the better semantics, since
interleaving would renumber a genuine intubation to `E2` because a charting blip preceded it.

**3 — null windows on rejected candidates (the serious one).** `window_start` /
`window_end` were computed only for the sustained set, so all 2,218 `not_sustained`
candidates carried nulls. The methods filter on the window and a null comparison is silently
false, so every rejected candidate detected nothing. **Tier D.3 would have compared `SED`'s
real 0.977 against a fabricated 0.0 and reported it as near-perfect specificity.** Exposed by
`03`'s printed rate-by-`index_class` table showing exactly 0.0 where a real rate was
expected. The window is now fixed for every candidate where it is created, and `02` asserts
no candidate lacks one. `SED` on `not_sustained` is 0.307.

**4 — the PARA × PAIR integrity check fanned out.** It keyed on `encounter_block`, so under
D35 one suspect episode pulled in *all* of its block's pairs, including those D39 assigned to
other episodes, and scored them against the wrong t₀. The signature was the explained counts
(88 + 44) exceeding the 63 being explained. Rekeyed to `intubation_episode_id` and
decomposed per episode. Now `63 = 32 (D25) + 31 (§6.5)`, zero unexplained.

**5 — `06`'s billing-lag statistic referenced a removed column.** `t0_dttm` left the
block-level bridge; under D35 "lag from t₀" is ambiguous for a multi-episode block. Anchored
on the block's earliest qualified t₀ as a stated convention — safe because nothing downstream
consumes it.

## 4. Suppression made legible

`PARA` had **9** detections on the `not_sustained` stratum — inside the 1–9 disclosive range
— so D.3's whole row is withheld under the n ≥ 10 rule. That leaves three of four contrasts
in `specificity_gap.csv` with no published gap.

The table now carries `comparator_status` (`ok` / `suppressed_n_below_10` / `not_available`)
so a withheld value is not read as an uncomputed one. The rate itself stays unpublished: the
stratum size is public in `consort_index.csv`, so a rate would make the suppressed count
recoverable by multiplication, which is the reason the row was withheld. `specificity_gap.png`
draws **no bar** where the comparator is suppressed rather than a zero-height one — a 0.0 bar
is a claim that the rate is zero, a different and much stronger statement.

## 5. Determinism

Full `02`→`07` re-run under a fresh `cohort_run_id`. **All 24 published CSVs byte-identical**
with `cohort_run_id` masked; 0 differing.

## 6. Data security

- **PHI scan:** clean across 24 CSVs — no `patient_id`, no `*_dttm`, no `hospitalization_id`.
- **Minimum cell size:** clean — no published count in the 1–9 range.
  Two columns are excluded by name and the exclusion is justified rather than pattern-matched:
  `n_methods` is an axis label (0–3, how many methods fired) and `n_units` counts distinct
  dose units (mg, mcg). Neither is a count of units-of-observation. A first pass flagged both;
  a heuristic that quietly skips a real count would be worse than one that cries wolf.
- **Output manifest:** conforms to §8, 34 artifacts, nothing missing or undeclared. It caught
  a stale `specificity_by_index_class.csv` on the first otherwise-green run.
- `tests/test_clifpy_tz_boundary.py`: 1 passed.

## 7. Results

| method | basis | rate | n / 13,500 |
|---|---|---|---|
| `SED` | — | **0.977** | 13,189 |
| `PARA` | — | 0.0433 | 584 |
| `PAIR` | `free_running` | 0.0576 | 777 |
| `PAIR` | `in_window` | 0.0367 | 495 |

`SED` at 0.977 is D38 working as specified, not a finding — the eligibility filter and the
method read the same eight drugs over the same window. The residual 311 non-detections are
the D25 on-t₀ population plus the paralytic-only episodes.

**A.3 concordance, `in_window`:** 0 methods 139 (1.03%) · 1 method 12,878 (95.39%) ·
2 methods 59 (0.44%) · 3 methods 424 (3.14%).

**Tier D.4 — the salvage.** On the 26,770 `no_induction_med` episodes, `SED`, `PARA` and
`PAIR`-in-window are all exactly 0 (asserted — that zero is the only observable signature of
drift between `02`'s `INDUCTION_CATEGORIES` and a method's `MED_CATEGORIES`).
`PAIR` free-running is **0.0177**, against 0.0576 in the index set — a gap of 0.0399 and a
ratio of **3.25×**. That is ambient sedative–paralytic pairing measured on the largest
stratum in the study, and it is the one interpretable specificity number the tier produces.

## 8. Correction

The `PAIR` counts in §7 were transcribed one too high — 778 / 496 against the artifact's
actual 777 / 495, and A.3's 1-method and 2-method cells likewise. Caught while verifying
that D40 left Tiers A-E untouched, by re-running `05` unchanged and reproducing 495. The
error was in this record, not in the pipeline: `method_PAIR_episode.parquet` has always
held 777 / 495. Corrected above.

## 8. Open

- **`ep_num` semantics** are now documented in three places but were never specified. §5.10
  says "chronological by t₀ within the block"; it now says "over the sustained set".
- **`bfill=True` costs real runtime.** The waterfall takes the bi-directional path through
  Phase 3's numeric fill across 239,209 mode blocks — roughly double the work, for values
  this pipeline never reads. D6 records that it cannot change `device_category`; it does not
  record the cost.
- **Three of four specificity contrasts have no published gap** at this site because the
  comparator stratum is too small to publish. A site with more `not_sustained` episodes will
  get all four.
