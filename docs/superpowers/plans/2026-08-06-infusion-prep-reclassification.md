# Infusion-Prep Reclassification Implementation Plan

**Goal:** Implement D40–D42 — reclassify post-t₀ intermittent sedative/paralytic doses that are loading boluses for a maintenance infusion, publish the effect as a paired sub-analysis (Tier F) plus a decomposed timing figure (B.5).

**Architecture:** `03` and `04` load `medication_admin_continuous` as a *disqualifier only* and flag each administration with `lag_to_infusion_min` / `during_infusion` (hospitalization-level, pre-bridge) and `infusion_prep` (episode-relative, post-bridge). `07` gains Tier F. Tiers A–E and D38 are untouched, so N stays 13,500 and every existing number remains comparable.

**Spec:** `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` — D40, D41, D42, §6.3, §6.4, §7.1, §7.2, §8.2 Tier F + B.5, §10, §11.

## Global constraints

- `infusion_prep_minutes` = 60. Sweep grid `5, 10, 15, 30, 45, 60, 90, 120, 150, 180`.
- **Filter, then rank — never rank, then filter** (§6.4). `detected_induction_only` and all `n_*` counts are computed on the unranked window set as `n_unique(med_category)`.
- The flags are computed **before** the explode-and-drop bridge, because they need `hospitalization_id`; `infusion_prep` is derived after, because it needs `delta_minutes`. `hospitalization_id` still dies at the bridge (§7).
- D8: `03` and `04` are deliberate copies. Every edit is applied to each independently.
- D21: lower-case every `*_category` value and literal.
- §5.13: `to_site_naive` for every clifpy timestamp.
- Aggregates only in `final_no_phi/`, n ≥ 10.

---

### Task 1: Config

**Files:** `config/config.json`, `config/config_template.json`

- [ ] Add `"infusion_prep_minutes": 60` after `"pair_gap_hours"` in both.

### Task 2: `03_method_sedative.py`

**Files:** `code/03_method_sedative.py`

- [ ] Import `MedicationAdminContinuous`; read `INFUSION_PREP_MINUTES` and define `PREP_SWEEP_MINUTES`.
- [ ] New cell: load continuous filtered to `bridge_hosp_ids`, lower-case, filter to `MED_CATEGORIES`. Print the `mar_action_category` value counts — a site charting no `start` makes D40 silently inert, so it must be visible.
- [ ] New cell `med_flagged`: two `join_asof` on `["hospitalization_id","med_category"]` — forward to the `start` subset for `lag_to_infusion_min`, backward to the **full** event stream for `during_infusion` (`last event is not 'stop'`). Re-sort between joins.
- [ ] Derive `infusion_prep = (delta_minutes > 0) & (lag_to_infusion_min <= INFUSION_PREP_MINUTES)` on `med_window`.
- [ ] Episode counts by `n_unique(med_category)`: `n_after_induction`, `n_after_prep`, `n_before_during`, `n_after_during`; `detected_induction_only = (n_before > 0) | (n_after_induction > 0)`.
- [ ] Carry `infusion_prep`, `during_infusion`, `lag_to_infusion_min` into the ranked NDJSON struct.
- [ ] Write `method_SED_prep_sweep.parquet` (threshold × index_class) and `method_SED_prep_by_drug.parquet` (threshold × index_class × med_category).
- [ ] Assert `detected_induction_only` implies `detected`.

### Task 3: `04_method_paralytic.py`

- [ ] Same edits, applied independently.

### Task 4: `07_agreement.py`

- [ ] `EPISODE_SCHEMA` `_RANKED_TAIL` gains the five new columns.
- [ ] Tier F cells: F.1 `induction_only_comparison.csv`, F.2 `infusion_prep_sweep.csv`, F.3 `infusion_prep_by_drug.csv`, F.4 `prep_by_charting_delay.csv` (strata `0`, `1-30`, `31-60`, `61-180`, `>180`, `not_charted`).
- [ ] Figures `infusion_prep_sweep.png`, `timing_offset_decomposed.png` (B.5, three stacked bands, `during_infusion` taking precedence).
- [ ] Extend the output manifest by the six new artifacts.

### Task 5: Docs and verification

- [ ] `docs/pipeline_flow.md` — D40/D41 in the rules table.
- [ ] Run `01`→`07`; confirm N = 13,500 and every Tier A–E number is unchanged.
- [ ] PHI scan, min-cell audit, manifest check.
