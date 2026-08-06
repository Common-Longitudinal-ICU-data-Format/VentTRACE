# PAIR Agent-Event Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `PAIR` from emitting several pairs for one intubation. Two independent causes are fixed: a **join fan-out defect** introduced by the episode rewrite, and the absence of any **temporal collapse** of same-class administrations into a single clinical agent event.

**Architecture:** `05_method_pair.py` gains a de-duplicated bridge and a new collapse stage between row selection and the scan: consecutive administrations of the same `drug_class` within `collapse_gap_minutes` become one *agent event* carrying a combined agent label. The scan, its consumption semantics (D28) and `pair_gap_hours` (D29) are untouched — they now operate on events rather than raw rows. `07_agreement.py` absorbs the widened `sed_med_category` domain, a repaired PARA×PAIR integrity check, and a new published figure.

**Tech Stack:** Python 3.14, marimo notebooks stored as `.py`, polars, clifpy 0.5.0, matplotlib, pytest.

---

## Context — why this change

Episode `677_E2` currently emits **10 pairs**, every one of them reading `midazolam 16:53 / rocuronium 16:56`. Episode `108083_E3` emits 5. The pair table has 4,110 rows where the published `pair_gap_distribution.csv` from the previous run recorded 2,166.

Two separate causes were measured (diagnostics in the session scratchpad, `dx1`–`dx9`):

**Cause 1 — bridge fan-out (a defect).** `05_method_pair.py:137-141` explodes `list_hospitalization_id` **without `.unique()`**. Since D35, `index_imv` is at episode grain (42,488 rows over 34,017 blocks), so a block with *k* episodes lists its hospitalization *k* times, the inner join at `05:200` replicates every medication row *k*×, and the scan pairs clone-with-clone. `03`/`04` are unaffected — they keep `intubation_episode_id` on the bridge and the fan-out is intended there (`03:149-153`); `05` deliberately dropped that key (D27/D39) without collapsing the rows it was disambiguating. Every existing assertion passes, because duplicated inputs yield self-consistent duplicated outputs.

**Cause 2 — no agent-event collapse.** Co-administration of two different same-class agents is a Δ=0 phenomenon (83% at exactly 0 min, 96% by 1 min; `fentanyl+propofol` n=4,127 and `fentanyl+midazolam` n=3,436 peri-intubation). D28's "step over, don't consume" already prevents that from making extra pairs, so collapsing sedatives alone is a ~0.4% no-op. The residual multi-pair episodes are driven by **repeat paralytic dosing** — `108083_E3` has five vecuronium doses across 50 minutes. Those separations have no empirical valley (median 209 min; 12% within 15 min), so the threshold is a **clinical definition, not a fit to the data**, and must be documented as such.

### Decisions taken (record these as **D40** in the spec)

| # | Decision | Rationale |
|---|---|---|
| D40.1 | Bridge in `05` is de-duplicated with `.unique()` | Each hospitalization belongs to exactly one block (verified: 0 hospitalizations appear in >1 block), so the map is 1:1 and duplicate rows are meaningless. |
| D40.2 | Collapse window is **15 minutes**, from `config.json` key `collapse_gap_minutes` | A clinical definition of one induction sequence. **No empirical valley supports it** — this must be stated wherever it is reported. |
| D40.3 | Grouping key is **`drug_class`** (SED vs PARA), not CLIF `med_group` | `med_group` splits fentanyl (`analgesia`) from propofol (`sedation`), which would fail to merge the single most common co-administration. D38 already measured and declined `med_group`. |
| D40.4 | Merging is **anchored, not chained** — a new event starts when a row is more than the window past the event's **first** administration | Chained merging has an unbounded span (measured max 115 min at MIMIC). Anchored costs 1.8% more events and makes `span <= collapse_gap_minutes` an assertable invariant. |
| D40.5 | `sed_med_category` / `para_med_category` carry a **combined label**, agents sorted alphabetically and joined with `+` | Preserves the clinical picture and makes every merge auditable in the output. |
| D40.6 | `med_dose` / `med_dose_unit` refer to the **first agent named in the label** | Doses of different drugs cannot be summed (mg vs mcg; §7.3 forbids unit conversion). Keeping them numeric preserves E.3's `median_sed_dose`. The rule is self-consistent because the label is alphabetically sorted. |

---

## Global Constraints

Copied from the existing spec. Every task's requirements implicitly include this section.

- **Run notebooks as** `uv run python code/NN_name.py`. They are marimo notebooks; cells are functions whose arguments declare dependencies, and a cell's `return` tuple must match its declared names exactly.
- **A variable may not be redefined across marimo cells.** Use `_`-prefixed locals for anything cell-scoped, or give it a distinct name.
- **polars throughout**; pandas only at the two clifpy boundaries, both inside `01`.
- **No helper functions across notebooks** (D8). Repeated logic is copy-pasted deliberately.
- **The only correct clifpy timestamp conversion** is `series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)` (§5.13).
- **Lower-case every `*_category` column immediately after load**, and write every literal in lower case (D21).
- **Every filter prints its row, episode, block and patient counts** before and after (§4).
- **No silent defaults.** Every parameter affecting a result is read from `config.json` and echoed at the top of the notebook.
- **`output/final_no_phi/` is aggregates only**, minimum cell size **n ≥ 10**. A cell of exactly zero is published; only 1–9 is suppressed, and suppression drops the whole row.
- **Every figure is drawn from a published table** (D26), never recomputed from a PHI frame.
- **Method medication lists.** `SED` = `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl`. `PARA` = `rocuronium`, `succinylcholine`, `vecuronium`.
- **D29 still holds.** `pair_gap_hours` is not post-hoc filterable, and a changed threshold requires a re-run. The collapse stage does not change this — it changes what the scan is handed, not how the scan decides.

### Expected MIMIC numbers after this plan

Verified by simulation before the plan was written. An implementer whose run disagrees has a bug.

> **Corrected after Task 2.** The simulation read the medication parquet directly with polars
> `convert_time_zone`; the pipeline loads through clifpy and `to_site_naive`, which is the only
> correct conversion here (§5.13, pinned by `tests/test_clifpy_tz_boundary.py`). The two differ by
> one hour, so rows straddling a DST transition shift relative to each other. Every pair-level
> number was unaffected (a uniform shift cannot change a delta) and matched exactly; only the event
> census moved, by 4 in 276,450. The numbers below are the notebook's, which are authoritative.

| Quantity | Before | After |
|---|---|---|
| bridge rows | 43,006 | **34,419** |
| scan input rows (administrations) | 716,382 | 370,687 |
| **agent events** entering the scan | — | **276,450** (SED 274,333 / PARA 2,117) |
| max event span | — | **exactly 15.0 min** |
| max `n_admin` per event | — | 11 (SED), 3 (PARA) |
| merged events (`n_admin > 1`) | — | 74,449 |
| multi-agent events (label contains `+`) | — | 58,493 |
| **pairs emitted** | 4,110 | **1,535** |
| blocks with ≥1 pair | 1,216 | 1,215 |
| episodes with ≥1 pair | 1,273 | 1,271 |
| episodes with exactly 1 pair | 780 (61%) | **1,073 (84.4%)** |
| max pairs per block | 52 | 9 |
| `sed_med_category` distinct values | 4 | **12** |
| `para_med_category` distinct values | 2 | 2 (`rocuronium` 1,127, `vecuronium` 408) |
| E.3 combination cells | 6 | **19** (14 at n ≥ 10) |

Most common merged labels: `fentanyl+propofol` (29,030 events), `fentanyl+midazolam` (26,901), `midazolam+propofol` (1,262), `fentanyl+midazolam+propofol` (1,103). No paralytic combination reaches a pair at MIMIC.

---

## File Structure

| File | Change |
|---|---|
| `config/config.json`, `config/config_template.json` | Add `collapse_gap_minutes: 15` |
| `code/05_method_pair.py` | Bridge `.unique()`; collapse stage; combined labels; widened assertions |
| `code/07_agreement.py` | Schema gate; Tier E rekey + widened E.3; PARA×PAIR integrity repair; new figure; manifest |
| `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` | D40; §6.5 columns; §7.3 collapse rule; §8 manifest |
| `docs/pipeline_flow.md` | §5 PAIR diagram |
| `tests/test_collapse_agent_events.py` | **New** — pytest for the collapse function |

---

## Task 1 — Fix the bridge fan-out in `05_method_pair.py`

**This is a standalone defect fix and must land before anything else**, because every number downstream is measured against it.

- [ ] In the bridge cell at `code/05_method_pair.py:136-141`, append `.unique()` to the explode chain.
- [ ] Add an assertion immediately after, with a message that explains the failure mode:
      `assert bridge.get_column("hospitalization_id").is_duplicated().sum() == 0`, message to the effect of *"a hospitalization maps to more than one encounter_block; the inner join below would replicate every administration and the scan would pair clones with clones."*
- [ ] Extend the existing comment block at `05:145-150`. It currently explains why the episode key is dropped; it must also say that dropping the key is exactly why the rows must be de-duplicated here — `index_imv` is at episode grain (D35), so the explode yields one row per (episode, hospitalization) and only the block mapping is wanted.
- [ ] Add a print of bridge rows before and after the `.unique()` (§4 counts rule).

**Verification:** `uv run python code/05_method_pair.py` prints bridge rows `43,006 -> 34,419`, and `method_PAIR_pairs.parquet` has **1,581 rows** over 1,216 blocks, max 9 pairs in any block.

---

## Task 2 — Add the anchored agent-event collapse to `05_method_pair.py`

- [ ] Add `"collapse_gap_minutes": 15` to both `config/config.json` and `config/config_template.json`.
- [ ] In the config cell (`05:55-96`), read `COLLAPSE_GAP_MINUTES = config["collapse_gap_minutes"]`, echo it in the parameter print block alongside `pair_gap_hours`, and add it to the cell's return tuple.
- [ ] Write a pure function `collapse_agent_events(times, categories, gap_limit_min)` in its own cell, in the same style as `scan_encounter` (`05:273-299`): a docstring naming the invariant, a plain forward fold, no polars. It returns a list of index-lists, one per event. A new event begins when `times[i] - times[event_start] > gap_limit_min` — **strictly greater**, anchored on the event's first row, never on the previous row.
- [ ] Write a `_self_test()` cell for it in the style of `05:301-323`, asserting these worked examples at `gap_limit_min=15`:

  | # | input times | expected grouping | what it pins |
  |---|---|---|---|
  | a | `[0, 0]` | `[[0, 1]]` | same-instant co-administration merges |
  | b | `[0, 15]` | `[[0, 1]]` | exactly at the limit still merges (`>`, not `>=`) |
  | c | `[0, 16]` | `[[0], [1]]` | one minute past the limit splits |
  | d | `[0, 10, 20]` | `[[0, 1], [2]]` | **anchored, not chained** — 20 is 20 min past the event start, so it splits even though it is 10 min past its predecessor |
  | e | `[0, 5, 10, 15]` | `[[0, 1, 2, 3]]` | a run inside one window stays one event |
  | f | `[0]` | `[[0]]` | singleton |

- [ ] Apply the collapse to `scan_rows`, producing a new frame `agent_events` in its own cell, partitioned by `(encounter_block, drug_class)` and fed rows already sorted by `["encounter_block", "admin_dttm", "med_category"]` (the existing §6.2 sort at `05:207-210` — do not change it; determinism depends on it).
- [ ] Each event carries:
  - `admin_dttm` = the **earliest** administration in the event
  - `med_category` = `"+".join(sorted(set(agents)))` — D40.5
  - `med_dose`, `med_dose_unit` = the values of the earliest administration **of the first agent named in the label** — D40.6. Keep the dtypes as they are (`Float64` / `String`); E.3's `median_sed_dose` depends on `med_dose` staying numeric.
  - `n_admin` = number of administrations folded in
  - `span_min` = last minus first administration, in minutes
- [ ] Assert the invariants: `span_min <= COLLAPSE_GAP_MINUTES` for every event; event count is ≤ row count; the sum of `n_admin` equals the input row count (nothing lost, nothing duplicated).
- [ ] Print the collapse counts: administrations in, events out, merged events, multi-agent events, and the top merged labels.
- [ ] Point the driver loop at `05:329-386` at `agent_events` instead of `scan_rows`. **The scan itself does not change.**
- [ ] Add `n_sed_admin`, `n_para_admin`, `sed_span_min`, `para_span_min` to the emitted pair rows.
- [ ] Add a pytest at `tests/test_collapse_agent_events.py` covering the same six worked examples plus a property check that concatenating the returned index-lists reproduces `range(n)` exactly.

**Verification:** the collapse print reports **276,446 events** from 370,687 administrations (SED 274,329 / PARA 2,117), max span exactly 15.0, and `method_PAIR_pairs.parquet` has **1,535 rows**.

---

## Task 3 — Widen `05`'s assertions and episode aggregation for combined labels

- [ ] The list-drift assertion at `05:634-648` compares `sed_med_category` / `para_med_category` against the declared lists. Split each value on `+` and check the resulting set, so a combined label is validated agent-by-agent. Keep the failure message's diagnostic value — it must still name the offending value and the declared list.
- [ ] The unit-mismatch check at `05:651` compares `sed_med_dose_unit` to `para_med_dose_unit`. Confirm it still means what it says now that units refer to the first-named agent; adjust the comment if the meaning shifted.
- [ ] Add the four new columns to `INDEX_PAIR_FIELDS` (`05:495-500`) so they propagate into the `first_` and `near_` blocks of `method_PAIR_episode.parquet`. **Order matters** — `07`'s schema gate asserts exact column-list equality.
- [ ] Confirm the conservation assertions at `05:465-470` and `05:596-599` still hold.

**Verification:** `05` runs clean end to end; `method_PAIR_episode.parquet` carries the new columns in both `first_` and `near_` blocks.

---

## Task 4 — Update `07_agreement.py`'s schema gate and Tier E

- [ ] Add the new columns to `_INDEX_PAIR_FIELDS` and `_PAIR_TAIL` at `07:133-142`, in the exact order `05` writes them. The gate at `07:157` asserts list equality, so an extra or misordered column fails the run.
- [ ] **Fix the block-keying bug at `07:1154-1169`.** `first_pairs_q` groups by `encounter_block` and takes the block's first pair, while everything around it is episode-keyed since D35 — so a multi-episode block contributes only its E1-region pair to E.2's "index pairs" basis and E.3's agent table. Group by `intubation_episode_id` instead, matching `05:508-521`. Rename `enc_q` to something episode-accurate and fix the "encounters" wording in the E.1/E.4/E.5/E.6 prints.
- [ ] E.3 (`07:~1250-1300` and the figure at `07:1742-1777`): the sed×para domain widens from 6 cells to **19** (14 at n ≥ 10). Confirm `apply_min_cell` still suppresses correctly and the heatmap remains legible with 12 row labels — combined labels are long, so the axis may need rotation or a wider figure.
- [ ] E.2's `pair_gap_distribution.csv` caption block at `07:1231-1238` claims to be "the empirical test of `pair_gap_hours`". Add a sentence that gaps are now measured between **agent events**, not administrations, and name `collapse_gap_minutes`.
- [ ] Add `n_sed_admin` / `n_para_admin` summary statistics to E.1 or a new E.7, so the amount of merging is visible in a published table rather than only in a notebook print.

**Verification:** `07` runs clean; `pair_agent_combinations.csv` has 14 published rows; every Tier E table is episode-keyed.

---

## Task 5 — Repair the PARA×PAIR integrity decomposition

`07:524-581` hard-asserts that every in-window `PAIR+ & PARA−` episode is explained by exactly one of two boundary rules (D25's on-t₀ paralytic, or §6.5's `in_window` evaluated on `pair_dttm`). At MIMIC it currently decomposes as `63 = 32 + 31` with zero unexplained. **This check is the most fragile consumer of pair construction and is expected to break**, because collapse moves a pair's `para_admin_dttm` to the earliest administration of its event, which can move a pair across a window boundary that `04` (which has no collapse) does not move with it.

- [ ] Run `07` and capture the actual decomposition and any unexplained episodes.
- [ ] For each unexplained episode, determine the mechanism from the data — do not guess. The likely third rule is *"the pair's paralytic event begins before `window_start` but contains an administration inside the window, which `04` sees and `05` no longer does."*
- [ ] Extend the decomposition with the new rule, named and counted like the existing two, and keep the assertion hard. If the residual cannot be driven to zero, **stop and report** rather than weakening the assertion — an unexplained residual here means `04` and `05` genuinely disagree about the paralytic list or the window, which is exactly what this check exists to catch.
- [ ] Update the comment at `07:530-534` to record the collapse as a third source of boundary disagreement.

**Verification:** the decomposition prints a complete accounting with zero unexplained, and the assertion is still an assertion.

---

## Task 6 — Publish the collapse-evidence figure and table

The threshold is a clinical judgment with no empirical valley (D40.2), so the evidence for it must be published rather than left in a scratchpad.

- [ ] Add a CSV `pair_collapse_deltas.csv`: for each Δ bin in 0–45 min, the count of consecutive same-`drug_class` intervals split by whether the two administrations are the **same agent** (a redose) or **different agents** (co-administration), restricted to the peri-intubation context. Apply `MIN_CELL` suppression. This is the table the figure is drawn from (D26).
- [ ] Add a figure `pair_collapse_deltas.png` following the F7 pattern at `07:1698-1739` — manual binning, `MIN_CELL` suppression, dropped mass stated in the caption, `finish(...)` for saving. Use `COLORS` and shade the chosen window. The caption must state that the co-administration signal sits at Δ ≤ 1 min while the threshold is 15 min, and say why (a clinical induction sequence, not a fitted valley).
- [ ] Add both filenames to the hard-coded manifest `_expected` at `07:1874-1890`. The manifest asserts in both directions, so an undeclared file fails the run just as a missing one does.
- [ ] Add both to the §8 output table in the design spec.

**Verification:** `output/final_no_phi/` contains exactly 36 artifacts (26 CSV + 11 PNG… recount against the manifest) and the manifest assertion passes.

---

## Task 7 — Record the decisions in the spec and the flow doc

- [ ] Add **D40** (all six sub-decisions above) to the §2 decisions table in `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md`, each with its rationale. D40.2 must state plainly that no empirical valley supports 15 minutes.
- [ ] Add the collapse rule and its six worked examples to §7.3, beside the existing scan pseudocode, so the two stages read as one algorithm.
- [ ] Update §6.5's `PAIR` column tables with the four new columns.
- [ ] Update the `05` diagram in `docs/pipeline_flow.md:316-345` to show the collapse stage ahead of the scan, with a concrete example (`fentanyl 12:00 + propofol 12:00 -> one SED event -> one pair`).
- [ ] Record the bridge fan-out as a defect in a short verification note, alongside the before/after numbers, so the 4,110 → 1,535 drop is traceable by anyone comparing runs.

**Verification:** the spec's decision table, §6.5, §7.3 and §8 all agree with the code.

---

## Verification — end to end

1. `uv run python code/05_method_pair.py` — bridge `43,006 -> 34,419`; **276,446** agent events; **1,535** pairs; all assertions pass.
2. `uv run python code/07_agreement.py` — schema gate passes; PARA×PAIR decomposition fully explained; manifest assertion passes.
3. `uv run pytest tests/ -v` — including the new `test_collapse_agent_events.py`.
4. Re-run `05` and `07` a second time and confirm every published CSV is byte-identical (the determinism property the previous rewrite established).
5. Spot-check the episodes named in the Context section: `677_E2` and `108083_E3` should each now carry a small, explicable number of pairs — verify by hand what remains and confirm it is genuine repeat dosing rather than an artifact.
