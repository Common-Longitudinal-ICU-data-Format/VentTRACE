# Dose ECDF Extract — Design

**Project:** VentTRACE **Date:** 2026-08-15 **Status:** Design, approved for planning

**Amends:** `2026-08-10-paralytic-index-design.md` (P18) and `2026-08-12-block-summary-and-cpt-comparator-design.md`. Both stand. This document adds one decision, P41. P43 (2026-08-17) later changed the converted summary tables but deliberately left P41's raw-unit ECDFs unchanged.

Decision numbering continues from P40. Section numbering restarts.

------------------------------------------------------------------------

## 1. Purpose

At the time of this amendment, P18 published a dose as three numbers — median, p25, p75 — on a unit-converted scale, keyed on `med_category` alone. P43 later added mean/SD and clinical filtering to that summary.

It is thinner than the data supports, and the pipeline already says so in its own margin. The comment at `code/02_index_paralytic.py:1313-1325` works out that polars places the q-th quantile of n sorted values at fractional index `(n-1)*q`, so whenever `(n-1)` is a multiple of 4 the published p25, median and p75 are **three verbatim charted doses** rather than synthesised statistics. Ketamine, n = 13, is the live instance at this site: `fig_E2__sedation_dose_summary.csv` publishes `0.03 / 0.15 / 16.0`, and all three are individual charted values.

This amendment publishes the distribution instead of three points that stand in for it: for every `(med_category, med_dose_unit)` pair, the **empirical cumulative distribution function** over the charted doses — every distinct dose value, how many administrations carried it, the running count, and the cumulative proportion.

The study lead's framing: *"for all the diff meds and unit do ECDF extract"*, and, on the rate question, *"we have limited to only non rate based doses so not sure why there is rate related dose remove them."*

### What this does not change

At implementation time, nothing changed in the four existing dose tables. P43 later changed the two converted summary tables and Figure E.2 while preserving `step02__paralytic_dose_raw_unit_counts.csv`, `step03__sedation_dose_raw_unit_counts.csv`, both raw-unit ECDFs, and their figures. P41 remains an additive QC distribution, not the clinically filtered summary population.

The alternative was put to the study lead and declined: the ECDF's `n_total` column carries every count that the two `*_dose_units.csv` files publish, which makes them exact duplicates by the same argument that retired Table 1's long CSV in `69a7c63`. Retiring them was offered and refused in favour of leaving already-reviewed artifacts untouched.

------------------------------------------------------------------------

## 2. Decision

| \# | Decision | Rationale |
|---|---|---|
| P41 | **Dose distributions are published as full ECDFs keyed on the raw charted `(med_category, med_dose_unit)` pair — one row per distinct dose value, carrying `n_at_dose`, `n_cum`, `n_total` and `ecdf`.** Amount units only; rate-charted rows are not published in any form. Additive to P18's converted summary and unchanged by P43's later summary-only plausibility filter. | Set by the study lead. Three quantiles cannot show bimodality, cannot show that 363 of 575 vecuronium administrations are the single value 10 mg, nor that 4 rocuronium administrations are charted at 0.0 mg. The raw ECDF is the complete QC aggregate: any quantile, threshold count or cross-site pooled raw distribution is recoverable from it. Keying on the **raw** unit makes it diagnostic: inaccurate units and implausible values excluded from P43's clinical summary remain visible here rather than disappearing silently. |

### The disclosure consequence, stated rather than discovered

A full ECDF over distinct values publishes every charted dose in a small group. `rocuronium` / `mcg` at this site is the smallest: n = 3, resolving to two rows — `0.6` carrying two administrations and `48.0` carrying one. A reader learns both values exactly, and that one of them was charted twice.

This is permitted, deliberately, and not by oversight. The n ≥ 10 small-cell rule was **withdrawn** by the study lead on 2026-08-10 (P21, amended; `docs/pipeline_flow.md` §6), and the boundary that replaced it is **row-level versus aggregate, not cell size**. A dose value with a count attached describes a dose, not a person; the cohort it is drawn from is defined by a published inclusion rule; and no identifier and no timestamp accompanies it — which is the whole of what `publish()` checks.

It is also not a new exposure. `fig_E2__sedation_dose_summary.csv` already publishes three of ketamine's thirteen charted doses verbatim under P18, as its own margin note records. The ECDF makes the exposure legible instead of incidental: a reader of an ECDF row with `n_total = 3` can see that the group is three administrations, whereas a reader of a p25/median/p75 triple cannot tell whether it was synthesised or copied.

------------------------------------------------------------------------

## 3. Architecture

Two notebooks touched, `02` and `03`. `01`, `04`, `05` and `06` are not modified.

`04` is presence-only by P32 — its own markdown states *"No dose, no rate, no infusion-derived index event"* — `05` contains no `med_dose` reference at all, and `06` reads only `patient_procedures`. No dose lives outside `02` and `03`, so the ECDF has no reach beyond them.

| notebook | new cells | writes |
|---|---|---|
| `02_index_paralytic.py` | `ecdf_by_group` helper; one publish cell; one figure cell | `output/final_no_phi/fig_B1__paralytic_dose_ecdf.csv`, `figures/fig_B1__paralytic_dose_ecdf.png` |
| `03_context.py` | `ecdf_by_group` helper; one publish cell; one figure cell | `output/final_no_phi/fig_E3__sedation_dose_ecdf.csv`, `figures/fig_E3__sedation_dose_ecdf.png` |

`B` is the free figure letter in `02` (which owns `A1` and `C1`); `E3` continues `03`'s `E1`/`E2` sedation series.

### 3.1 Source frames — reconciliation by construction

| notebook | source frame | defined at | rows at this site |
|---|---|---|---|
| `02` | `dose_converted` | `code/02_index_paralytic.py:1292` | 2,160 doses |
| `03` | `sedation_dose_converted` | `code/03_context.py:1322` | 3,570 (index paralytic, administration) pairs |

These are the **same frames**, grouped on the **same keys**, that already produce `step02__paralytic_dose_raw_unit_counts.csv` and `step03__sedation_dose_raw_unit_counts.csv`. `n_total` for a group is therefore identical to that group's `n` in those files, by construction rather than by agreement — the two cannot disagree without one of them being edited to stop using the frame.

The ECDF reads the **raw** `med_dose` and `med_dose_unit` columns from those frames, never `med_dose_converted` / `med_dose_unit_converted`. Both pairs are present on the frame; P41 uses the raw pair.

### 3.2 Rate units require no code

Rate-charted rows are removed upstream, at `code/02_index_paralytic.py:351` and `code/03_context.py:853`, by `~rate_unit_expr("med_dose_unit")` — the filter added by commit `305de1f`. Everything downstream of that point, `dose_converted` and `sedation_dose_converted` included, is amount-only already, and `02:1240` carries an assertion that no rate row can reach the converter.

So the amount-only property of P41 is **inherited, not re-asserted**. No new filter is written, `rate_unit_expr` gains no new caller, and `_rate_rows` stays what it is today: a marimo cell-local, counted into the run log, published nowhere. At this site both counts are `0`.

Publishing the rate population was designed and then withdrawn by the study lead on 2026-08-15. It would have been the pipeline's only published artifact drawn from a frame that is neither action-filtered nor index-anchored, and its `n_total` would have shared a column name with the amount tables while meaning something else entirely.

### 3.3 The helper is duplicated, not shared

`ecdf_by_group` is written into `02` and into `03` separately, as `to_site_naive` and `convert_doses_to_preferred_units` already are. `utils/suppress.py` remains the only shared code in the project (spec §4, P23).

The reasoning is the one `tests/test_dose_conversion.py` states for its own subject: duplicated analysis logic risks *visible* divergence between the two notebooks, which a test catches, while a shared bug in a `utils/` helper corrupts both identically and invisibly.

------------------------------------------------------------------------

## 4. Output contract

Identical schema in both files:

```
med_category,med_dose_unit,dose,n_at_dose,n_cum,n_total,ecdf
rocuronium,mcg,0.6,2,2,3,0.666667
rocuronium,mcg,48.0,1,3,3,1.0
rocuronium,mg,0.0,4,4,1582,0.002528
rocuronium,mg,0.3,10,14,1582,0.00885
rocuronium,mg,0.6,29,43,1582,0.027181
...
vecuronium,mg,100.0,7,575,575,1.0
```

| column | type | meaning |
|---|---|---|
| `med_category` | str | the agent, lower-cased at load per P20 |
| `med_dose_unit` | str | the **raw charted** unit, stripped and lower-cased at load; never the converted unit |
| `dose` | f32 | a distinct charted dose value within the group; carried at the upstream dtype, not widened |
| `n_at_dose` | u32 | administrations charted at exactly this dose |
| `n_cum` | u32 | running total of `n_at_dose`, ascending by `dose` |
| `n_total` | u32 | administrations in the group; equals this group's `n` in the matching `*_dose_units.csv` |
| `ecdf` | f64 | `n_cum / n_total`, rounded to 6 dp |

**A row with a null `med_dose` or a null `med_dose_unit` is dropped before grouping, and the count of dropped rows is printed to the run log.** Neither occurs at this site — both null counts are 0 across all 2,160 paralytic doses and 3,570 sedative pairs — but a null dose has no position in a cumulative distribution, and silently sorting it to one end would put it at the 0th or 100th percentile of a distribution it is not part of. Dropping it changes `n_total`, so it is reported rather than absorbed: a site whose `n_total` sits below the matching `*_dose_units.csv` count learns why from the log instead of filing a discrepancy.

**`n_cum` and `n_total` are authoritative; `ecdf` is a convenience column.** The rounding is for readability, and the exact value is recoverable from the two integers. A consortium partner pooling sites should sum `n_at_dose` across sites and recompute, never average `ecdf`.

**Sort:** `(med_category, med_dose_unit, dose)`, all ascending. That triple is the group-by key and is therefore unique by construction, so the sort is total and the output byte-identical across runs without an added tie-break column — which is what commit `6c70808` requires of every published sort.

**Empty input yields an empty frame carrying the full schema**, published as a header-only CSV rather than skipped. A file that is present and empty says "we looked, there were none"; a missing file is indistinguishable from a notebook that failed.

### 4.1 Expected size at this site

`fig_B1__paralytic_dose_ecdf.csv` — **118 rows** over 2,160 doses:

| med_category | med_dose_unit | n | distinct doses |
|---|---|---|---|
| rocuronium | mcg | 3 | 2 |
| rocuronium | mg | 1,582 | 87 |
| vecuronium | mg | 575 | 29 |

`fig_E3__sedation_dose_ecdf.csv` — **81 rows** over 3,570 pairs:

| med_category | med_dose_unit | n | distinct doses |
|---|---|---|---|
| fentanyl | mcg | 1,514 | 16 |
| ketamine | mcg | 8 | 7 |
| ketamine | mg | 5 | 5 |
| midazolam | mg | 610 | 13 |
| propofol | mcg | 6 | 4 |
| propofol | mg | 1,427 | 36 |

Both are smaller than several artifacts already published. Row count scales with distinct charted values, not with n — the 1,582-administration rocuronium group needs 87 rows because a site charts doses on a coarse grid.

------------------------------------------------------------------------

## 5. Figures

One step plot per notebook — `figures/fig_B1__paralytic_dose_ecdf.png` from `02` and `figures/fig_E3__sedation_dose_ecdf.png` from `03` — one panel per `(med_category, med_dose_unit)` group, following the conventions every existing figure cell in this pipeline already uses:

- **Read the published CSV back** via `pl.read_csv(SHARE_DIR / ...)`, never the in-memory frame. A figure that disagrees with its own CSV is a bug that only this convention can catch.
- **Palette:** `_BLUE = "#2a78d6"`, `_INK = "#0b0b0b"`, `_SECOND = "#52514e"`, `_MUTED = "#898781"`, `_GRID = "#e1e0d9"`, `_SURFACE = "#ffffff"`.
- **Step interpolation is `post`** — an ECDF is right-continuous, and `where="post"` is the only step style that draws that correctly. A line plot would imply doses were charted between the grid values, which is exactly the false reading the ECDF exists to prevent.
- Points marked at each charted dose so a 2-row group reads as two observations rather than as a continuous curve.
- Each panel titled with its group and `n_total`; y-axis fixed to `[0, 1]`; `set_axisbelow(True)`, x-grid only, top/right/left spines hidden, `tick_params` in `_MUTED`, `dpi=150`, `plt.close(_fig)` and a `print` confirming the path.
- **Zero-row skip guard** with an explanatory message, as figure E.2 carries at `03:1740` — `plt.subplots(0, 1, ...)` raises, and a site with no qualifying administration must not fail the run.
- Suptitle in the three-line house form: figure number and title, a subtitle naming the governing rule, and the published row count.

------------------------------------------------------------------------

## 6. Tests

New `tests/test_dose_ecdf.py`, following `tests/test_dose_conversion.py` exactly: the helper is lifted out of **both** notebooks by AST rather than imported — neither `02_index_paralytic` nor `03_context` is an importable module name, and importing either would run the pipeline against real PHI — and one identical suite runs against each copy, so an edit that quietly diverges the two fails here first.

| test | pins |
|---|---|
| `test_both_notebooks_define_the_function` | extraction actually returned a callable, so the rest cannot vacuously pass |
| `test_output_carries_exactly_the_published_columns` | the seven columns, in order |
| `test_ecdf_reaches_one` | the last row of every group has `ecdf == 1.0` and `n_cum == n_total` |
| `test_n_cum_is_monotone` | `n_cum` never decreases within a group |
| `test_counts_sum_to_total` | `sum(n_at_dose) == n_total` for every group |
| `test_ties_collapse_to_one_row` | ten administrations at one dose produce one row with `n_at_dose == 10`, not ten rows |
| `test_groups_do_not_bleed` | a dose in one `(med_category, med_dose_unit)` group never contributes to another's `n_cum` |
| `test_sort_is_total_and_stable` | output is sorted `(med_category, med_dose_unit, dose)`, the key triple is unique, and reversing the input row order produces an identical frame |
| `test_null_dose_rows_are_dropped_not_ranked` | a null `med_dose` is excluded from the group and from `n_total`, never sorted to an end |
| `test_empty_input_yields_empty_frame_with_schema` | an empty input frame returns an empty frame carrying all seven columns, not an error |
| `test_ecdf_is_recoverable_from_the_two_integers` | `abs(ecdf - n_cum / n_total) <= 5e-7` on every row. Asserted as a tolerance, not as equality against Python's `round()`: polars rounds half **away from zero** and Python rounds half **to even**, so an exact-equality test would pin an agreement between two rounding conventions rather than the 6-dp contract itself |

------------------------------------------------------------------------

## 7. Documentation

| file | change |
|---|---|
| `docs/pipeline_flow.md` | P41 added to the §7 rule table; the two CSVs and two figures added to the §2 artifact inventory; §4's and §5's dose narratives point at the raw-unit count and ECDF files beside each other |
| `docs/superpowers/specs/2026-08-10-paralytic-index-design.md` | P18 annotated to note it is extended, not superseded, by P41 |
| `code/README.md` | no change — the writes column already reads "several `output/final_no_phi/*.csv` + `figures/`" for both `02` and `03` |
| `README.md` | no change — it describes the study, not the artifact inventory |

------------------------------------------------------------------------

## 8. Out of scope

- **Retiring any existing dose artifact.** Offered and declined; see §1.
- **Rate-unit doses.** Withdrawn by the study lead; see §3.2.
- **An ECDF on the converted unit.** P18's median/IQR already occupies that scale. Publishing both a raw-unit and a converted-unit ECDF would put two files with the same column names and different denominators side by side, which is the failure mode §3.2 rejects for rate units.
- **Cross-site pooling logic.** The extract is designed to make pooling possible — integer counts, no averaged proportions — but the pooling itself belongs to the coordinating centre, not to a site notebook.
- **ECDFs of anything other than dose.** Offsets and gaps are already published as binned distributions, and re-cutting them as ECDFs is a separate decision nobody has asked for.
