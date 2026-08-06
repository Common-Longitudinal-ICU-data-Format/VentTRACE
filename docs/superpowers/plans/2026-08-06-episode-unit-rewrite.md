# Episode Unit Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the analytic unit from the stitched encounter to the intubation episode, anchor t₀ on the waterfall, and gate episodes on an induction-agent administration — implementing D34–D39 of the design spec.

**Architecture:** `01_cohort.py` stops deciding t₀ and gains a raw-IMV projection. `02_index_imv.py` is rewritten end to end: it scans the waterfalled device sequence for episode starts, anchors t₀ on each, labels each with charting delay and lookback, gates on induction medications, and emits one row per candidate episode. `03`/`04`/`05` are rekeyed from `encounter_block` to `intubation_episode_id`. `07` gains a two-unit reporting convention and a rewritten Tier D.

**Tech Stack:** Python 3.14, marimo notebooks stored as `.py`, polars (pandas only at clifpy boundaries), clifpy 0.5.0, matplotlib, pytest.

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- **Run notebooks as** `uv run python code/NN_name.py`. They are marimo notebooks; cells are functions whose arguments declare dependencies, and a cell's `return` tuple must match its declared names exactly.
- **A variable may not be redefined across marimo cells.** Use `_`-prefixed locals for anything cell-scoped, or give it a distinct name.
- **polars throughout; pandas only at the two clifpy boundaries** (`stitch_encounters`, `process_resp_support_waterfall`), both inside `01`.
- **No helper functions across notebooks** (D8). Repeated logic is copy-pasted deliberately — a shared helper would corrupt every method identically, and correlated errors are indistinguishable from genuine agreement.
- **The only correct clifpy timestamp conversion** is `series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)` (§5.13). `.dt.tz_localize(None)` alone silently shifts by ~1 h via the pytz LMT offset.
- **Lower-case every `*_category` column immediately after load, and write every literal in lower case** (D21) — `'imv'`, `'given'`, `'trach collar'`.
- **Pass every casing variant to `from_file` filters** (D22), e.g. `{'device_category': ['IMV', 'imv', 'Imv']}`.
- **Every filter prints its row, episode, block and patient counts** before and after (§4).
- **No silent defaults.** Every parameter affecting a result is read from `config.json` and echoed at the top of the notebook.
- **`output/final_no_phi/` is aggregates only**, minimum cell size **n ≥ 10** for every reported statistic, no `patient_id`, no row-level records, no raw `.csv`/`.parquet` data files. A cell of exactly **zero is published**; only the 1–9 range is suppressed, and suppression drops the whole row.
- **Every figure is drawn from a published table** (D26), never recomputed from PHI frames.
- **`config.json` keys in play:** `window_hours: 3`, `episode_gap_hours: 3`, `pair_gap_hours: 3`, `stitch_hours: 6`, `trach_window_hours: 24`, `min_age: 18`.
- **Method medication lists.** `SED` = `midazolam`, `etomidate`, `ketamine`, `propofol`, `fentanyl`. `PARA` = `rocuronium`, `succinylcholine`, `vecuronium`. Their union is the eight categories D38's filter uses.
- **Expected MIMIC counts** at each stage, for verifying a step did what it should: 34,017 blocks → 42,488 candidate episode starts → 40,270 sustained → 13,500 qualified, over 12,503 blocks and 11,935 patients.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `code/01_cohort.py` | who is in the study; hospitalizations → blocks; device timelines | Modify — `bfill=True`, emit `cohort_resp_imv_raw.parquet`, slim `cohort_index.parquet`, move the Δ QC out |
| `code/02_index_imv.py` | device rows → episodes; t₀; window; labels; CONSORT B | **Rewrite** |
| `code/03_method_sedative.py` | `SED` profiler | Modify — rekey to `intubation_episode_id` |
| `code/04_method_paralytic.py` | `PARA` profiler | Modify — same rekey, applied independently (D8) |
| `code/05_method_pair.py` | `PAIR` scan + pair→episode assignment | Modify — rekey, add D39 assignment |
| `code/06_reference_cpt.py` | CPT 31500 presence | Modify — rekey, block-level Tier C note |
| `code/07_agreement.py` | schema gate, Tiers A–E, figures | Modify — rename, two-unit reporting, Tier D rewrite, two new figures |
| `config/config.json`, `config/config_template.json` | parameters | Already updated with `episode_gap_hours: 3` |

---

## Task 1: `01` — stop deciding t₀, start publishing raw IMV

**Files:**
- Modify: `code/01_cohort.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `output/intermediate_phi/cohort_resp_imv_raw.parquet` with columns `encounter_block: Int32`, `recorded_dttm: Datetime` (one row per distinct raw charted IMV timestamp per block). `cohort_index.parquet` with columns `encounter_block: Int32`, `patient_id: String`, `cohort_run_id: String`, `list_hospitalization_id: List(String)` — **and no `t0_dttm`, `window_start`, `window_end` or `intubation_episode_id`**.

- [ ] **Step 1: Set the waterfall flag and record why it is inert**

In the waterfall cell, change the call and add the comment:

```python
    _waterfalled = process_resp_support_waterfall(
        _resp_in,
        id_col="hospitalization_id",
        # D6. This flag CANNOT change device_category: waterfall.py:274 ffills it
        # unconditionally, and bfill reaches only num_cols_fill (fio2_set, peep_set,
        # tidal_volume_set, ...) at :320-336 -- after the device heuristics at :199-226
        # have already run. We read device_category and nothing else out of this frame,
        # so the flag is inert here. Set as specified rather than silently dropped.
        bfill=True,
        verbose=True,
    )
```

- [ ] **Step 2: Add the raw-IMV projection cell**

Add a new cell immediately after the waterfall cell. `resp_raw` and `encounter_mapping` already exist in the notebook.

```python
@app.cell
def _(encounter_mapping, pl, resp_raw, PHI_DIR):
    # The raw charted IMV rows, block-keyed. Under D34 no RULE reads this frame -- t0 is
    # the waterfalled episode start. Its only consumer is charting_delay_min in 02, which
    # is a published statistic rather than a filter.
    cohort_resp_imv_raw = (
        resp_raw.filter(pl.col("device_category") == "imv")
        .join(encounter_mapping, on="hospitalization_id", how="inner")
        .select(["encounter_block", "recorded_dttm"])
        .unique()
        .sort(["encounter_block", "recorded_dttm"])
    )

    assert cohort_resp_imv_raw.height > 0, (
        "no raw charted imv rows survived the block join -- every block entered the "
        "cohort on one (D23 still governs admission), so this cannot legitimately be empty"
    )
    cohort_resp_imv_raw.write_parquet(PHI_DIR / "cohort_resp_imv_raw.parquet")
    print(f"cohort_resp_imv_raw.parquet  {cohort_resp_imv_raw.height:,} rows -> {PHI_DIR}")
    print(f"  blocks represented         {cohort_resp_imv_raw.get_column('encounter_block').n_unique():,}")
    return (cohort_resp_imv_raw,)
```

- [ ] **Step 3: Run `01` and confirm the new artifact**

Run: `uv run python code/01_cohort.py`
Expected: prints `cohort_resp_imv_raw.parquet  724,215 rows` (±, depending on extract) and `blocks represented  34,017`. The existing CONSORT A numbers are unchanged: 34,017 blocks / 31,124 patients.

- [ ] **Step 4: Slim `cohort_index.parquet`**

Find the cell that builds `cohort_index` and remove the four columns that moved to `02`. The projection becomes:

```python
    cohort_index = cohort.select(
        [
            "encounter_block",
            "patient_id",
            "cohort_run_id",
            "list_hospitalization_id",
        ]
    ).sort("encounter_block")

    # t0_dttm, window_start, window_end and intubation_episode_id are NOT written here.
    # Under D34 t0 is a property of an episode and 02 resolves it; under D35 a block has
    # several. A block-level t0 written here would be a stale duplicate of the first
    # episode's -- exactly the drift D14 warns about.
    assert cohort_index.get_column("encounter_block").is_unique().all(), (
        "encounter_block is not unique in cohort_index"
    )
```

- [ ] **Step 5: Delete the t₀ resolution cell and the Δ QC cell**

Remove the cell that computes `t0_dttm` from `resp_raw`, the cell that computes `window_start` / `window_end`, and QC 1 (the `Δ = waterfall_t₀ − raw_t₀` statistic). QC 1 moves to `02` as `charting_delay_min` in Task 3. Keep QC 2 (timestamp alignment), QC 3 (blocks per encounter) and QC 4.

Update QC 4's label, since it no longer references t₀:

```python
    # QC 4 -- the direct measure of the artifact stitching exists to remove. Phrased on the
    # block's first IMV row rather than on t0, which 01 no longer computes.
    _first_imv_hosp = (
        resp_raw.filter(pl.col("device_category") == "imv")
        .join(encounter_mapping, on="hospitalization_id", how="inner")
        .sort(["encounter_block", "recorded_dttm"])
        .group_by("encounter_block", maintain_order=True)
        .agg(imv_hosp=pl.col("hospitalization_id").first())
    )
```

- [ ] **Step 6: Run `01` and verify the schema change**

Run: `uv run python code/01_cohort.py`
Then verify:

```bash
uv run python -c "
import polars as pl
c = pl.read_parquet('output/intermediate_phi/cohort_index.parquet')
assert set(c.columns) == {'encounter_block','patient_id','cohort_run_id','list_hospitalization_id'}, c.columns
print('cohort_index.parquet schema OK:', c.columns, c.height, 'rows')
r = pl.read_parquet('output/intermediate_phi/cohort_resp_imv_raw.parquet')
assert r.columns == ['encounter_block','recorded_dttm'], r.columns
print('cohort_resp_imv_raw.parquet OK:', r.height, 'rows')
"
```
Expected: both assertions pass, `cohort_index.parquet` has 34,017 rows.

- [ ] **Step 7: Commit**

```bash
git add code/01_cohort.py
git commit -m "feat(01): publish raw IMV rows, stop deciding t0 (D34, D35)

01 no longer computes a block-level t0 or window bounds -- both became
properties of an episode and 02 resolves them. Emits cohort_resp_imv_raw
so 02 can publish charting_delay_min. bfill=True per D6, with the reason
it is inert recorded at the call site."
```

---

## Task 2: `02` — the episode scan

**Files:**
- Rewrite: `code/02_index_imv.py`

**Interfaces:**
- Consumes: `cohort_index.parquet` and `cohort_resp_waterfall.parquet` from Task 1.
- Produces: an in-notebook frame `episodes` with columns `encounter_block: Int32`, `t0_dttm: Datetime`, `ep_num: Int32`, and a boolean `sustained`. Not yet written to disk.

- [ ] **Step 1: Add the worked examples to spec §5.9**

The rule needs test cases the way §7.3 gives them to `PAIR`. Add this subsection to `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` immediately before `### 5.10`:

```markdown
#### Worked examples

Device sequences within one block, at `episode_gap_hours = 3`. Times in minutes from an arbitrary origin. `·` is a null device.

| # | sequence | episode starts | why |
|---|---|---|---|
| (a) | `0 nasal · 60 imv · 90 imv · 120 imv` | `{60}` | 90 and 120 have imv within 3 h behind them |
| (b) | `0 imv · 30 nasal · 400 imv` | `{}` | 0 starts an episode but a non-imv device lands 30 min later — not sustained. 400 starts one and survives |
| (c) | `0 imv · 400 imv` | `{0, 400}` | 400 min > 180, so the second is its own episode |
| (d) | `0 imv · 179 imv` | `{0}` | 179 < 180, still the same episode |
| (e) | `0 imv · 180 imv` | `{0, 180}` | the boundary is inclusive: exactly 180 min of no imv qualifies |
| (f) | `0 · · 0 imv · 100 imv` | `{0}` | a leading null passes the pre-period test vacuously (D37) |
| (g) | `0 imv` (only row) | `{0}` | an empty forward window passes the sustained test (D37) |

Case (b)'s second episode and case (e) are the two the implementation is most likely to get wrong: the first because a rejected candidate must not consume the rows after it, the second because the comparison is `>=` and not `>`.
```

- [ ] **Step 2: Write the notebook header, config and self-test**

Replace `code/02_index_imv.py` entirely. Start with:

```python
import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from datetime import timedelta
    from pathlib import Path

    import polars as pl

    import marimo as mo

    return Path, json, mo, pl, timedelta


@app.cell
def _(mo):
    mo.md(
        """
        # 02 — Episode detection and CONSORT B

        `01` says which blocks are in the study. It does not say how many intubations a
        block holds, when each began, or whether any of them is one we can see happen.
        This notebook answers all three, and its CONSORT is a headline result rather
        than a preprocessing note.

        Three rules, in order:

        ```
        1  an imv row starts an episode iff no imv row precedes it
           within episode_gap_hours in the same block          (D36)

        2  reject if a non-null non-imv device appears within
           episode_gap_hours after the start                   (sustained)

        t0 = the episode's first WATERFALLED imv row            (D34)

        3  reject unless one of the eight induction agents is
           charted `given` within t0 +/- window_hours           (D38)
        ```

        A null device, and an empty window, pass rules 1 and 2 — absence of charting is
        not evidence of ventilation (D37).

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` §5.9–§5.13
        """
    )
    return


@app.cell
def _(Path, json, timedelta):
    _config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(_config_path, "r") as _f:
        config = json.load(_f)

    SITE = config["site_name"]
    DATA_DIR = config["data_directory"]
    FILETYPE = config["filetype"]
    TIMEZONE = config["timezone"]
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    EPISODE_GAP_HOURS = config["episode_gap_hours"]
    WINDOW_HOURS = config["window_hours"]
    EPISODE_GAP = timedelta(hours=EPISODE_GAP_HOURS)
    WINDOW = timedelta(hours=WINDOW_HOURS)

    # The union of the SED and PARA lists (D38). Written out rather than imported: this
    # notebook must be readable on its own, and D8 wants the duplication visible.
    SED_CATEGORIES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
    PARA_CATEGORIES = ["rocuronium", "succinylcholine", "vecuronium"]
    INDUCTION_CATEGORIES = SED_CATEGORIES + PARA_CATEGORIES

    print(f"site               : {SITE}")
    print(f"episode_gap_hours  : {EPISODE_GAP_HOURS}")
    print(f"window_hours       : {WINDOW_HOURS}")
    print(f"induction agents   : {', '.join(INDUCTION_CATEGORIES)}")
    return (
        DATA_DIR,
        EPISODE_GAP,
        EPISODE_GAP_HOURS,
        FILETYPE,
        INDUCTION_CATEGORIES,
        PARA_CATEGORIES,
        PHI_DIR,
        SED_CATEGORIES,
        SHARE_DIR,
        SITE,
        TIMEZONE,
        WINDOW,
        WINDOW_HOURS,
    )


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy returns tz-aware columns whose tzinfo carries the pytz LMT offset --
        `DstTzInfo 'US/Eastern' LMT-1 day, 19:04:00 STD`. `.dt.tz_localize(None)` alone
        drops the ATTACHED offset rather than the correct one and shifts every timestamp
        by about an hour, silently. See §5.13.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)
```

- [ ] **Step 3: Write the self-test cell with the §5.9 worked examples**

Add this cell next. It runs before any data is loaded, exactly as `05`'s does.

```python
@app.cell
def _(pl, timedelta):
    def find_episode_starts(df, gap):
        """Rules 1 and 2 as one function, so the worked examples test the real thing.

        `df` is one block's waterfalled rows: columns `encounter_block`, `recorded_dttm`,
        `device_category`, sorted by time. Returns the surviving episode start rows.

        Rule 1 is a shift(1) over IMV-ONLY rows, which is what makes this short. A
        mid-episode imv row has imv within `gap` behind it and disqualifies itself, so the
        same predicate that tests the pre-period also segments the timeline -- there is no
        episode loop and no in-episode state to carry (D36).
        """
        _imv = (
            df.filter(pl.col("device_category") == "imv")
            .select(["encounter_block", "recorded_dttm"])
            .unique()
            .sort(["encounter_block", "recorded_dttm"])
            .with_columns(prev_imv=pl.col("recorded_dttm").shift(1).over("encounter_block"))
        )
        # `>= gap` and not `> gap`: exactly `gap` of no imv qualifies -- worked example (e).
        _cand = _imv.filter(
            pl.col("prev_imv").is_null()
            | ((pl.col("recorded_dttm") - pl.col("prev_imv")) >= gap)
        ).select(["encounter_block", "recorded_dttm"])

        _other = (
            df.filter(
                pl.col("device_category").is_not_null()
                & (pl.col("device_category") != "imv")
            )
            .select(["encounter_block", "recorded_dttm"])
            .unique()
            .sort(["encounter_block", "recorded_dttm"])
        )
        if _other.height == 0:
            return _cand.with_columns(sustained=pl.lit(True))

        # Rule 2. join_asof forward matches right >= left, but we need STRICTLY after t0,
        # so the probe key is nudged by one microsecond. A non-imv device charted at the
        # very same instant as t0 (possible across two hospitalizations in one block) is
        # then not treated as a violation of a window that starts after it.
        _probe = _cand.with_columns(
            _probe_dttm=pl.col("recorded_dttm") + timedelta(microseconds=1)
        ).sort("_probe_dttm")
        _joined = _probe.join_asof(
            _other.rename({"recorded_dttm": "next_other_dttm"}).sort("next_other_dttm"),
            left_on="_probe_dttm",
            right_on="next_other_dttm",
            by="encounter_block",
            strategy="forward",
        )
        return _joined.select(
            "encounter_block",
            "recorded_dttm",
            sustained=pl.col("next_other_dttm").is_null()
            | ((pl.col("next_other_dttm") - pl.col("recorded_dttm")) > gap),
        )

    return (find_episode_starts,)


@app.cell
def _(find_episode_starts, pl, timedelta):
    def _self_test():
        """The §5.9 worked examples, run as assertions before any real data is touched."""
        _gap = timedelta(hours=3)

        def _run(seq):
            _df = pl.DataFrame(
                {
                    "encounter_block": [1] * len(seq),
                    "recorded_dttm": [
                        timedelta(minutes=m) + pl.datetime(2130, 1, 1).to_python()
                        if False
                        else None
                        for m, _ in seq
                    ],
                    "device_category": [d for _, d in seq],
                }
            )
            return _df

        _base = __import__("datetime").datetime(2130, 1, 1)

        def _mk(seq):
            return pl.DataFrame(
                {
                    "encounter_block": pl.Series([1] * len(seq), dtype=pl.Int32),
                    "recorded_dttm": [_base + timedelta(minutes=m) for m, _ in seq],
                    "device_category": [d for _, d in seq],
                }
            ).sort("recorded_dttm")

        cases = [
            ("a", [(0, "nasal cannula"), (60, "imv"), (90, "imv"), (120, "imv")], [60]),
            ("b", [(0, "imv"), (30, "nasal cannula"), (400, "imv")], [400]),
            ("c", [(0, "imv"), (400, "imv")], [0, 400]),
            ("d", [(0, "imv"), (179, "imv")], [0]),
            ("e", [(0, "imv"), (180, "imv")], [0, 180]),
            ("f", [(0, None), (30, None), (60, "imv"), (160, "imv")], [60]),
            ("g", [(0, "imv")], [0]),
        ]
        for _label, _seq, _want in cases:
            _got_df = find_episode_starts(_mk(_seq), _gap).filter("sustained")
            _got = [
                int((r - _base).total_seconds() // 60)
                for r in _got_df.get_column("recorded_dttm").to_list()
            ]
            assert sorted(_got) == _want, (
                f"worked example ({_label}): expected {_want}, got {sorted(_got)}"
            )
        print("§5.9 worked examples (a)-(g) pass")

    _self_test()
    return
```

- [ ] **Step 4: Run the notebook and verify the self-test fires**

Run: `uv run python code/02_index_imv.py`
Expected: prints `§5.9 worked examples (a)-(g) pass`. If case (e) fails with `expected [0, 180], got [0]`, the comparison is `>` where the spec says `>=`. If case (b) fails with `expected [400], got []`, a rejected candidate is wrongly consuming the rows after it.

- [ ] **Step 5: Delete the dead scaffolding from Step 3**

The `_run` and `_self_test`-internal `_df` builder in Step 3 was left in as a stub. Remove `_run` entirely — only `_mk` is used. Re-run and confirm the self-test still passes.

- [ ] **Step 6: Apply the scan to the real waterfall**

```python
@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")
    resp_waterfall = pl.read_parquet(PHI_DIR / "cohort_resp_waterfall.parquet")

    COHORT_RUN_ID = cohort_index.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"cohort_index carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    assert "t0_dttm" not in cohort_index.columns, (
        "cohort_index still carries t0_dttm. 01 must be re-run: under D34 t0 belongs to "
        "an episode and this notebook resolves it, so a block-level t0 here is stale."
    )

    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"cohort blocks     : {cohort_index.height:,}")
    print(f"waterfalled rows  : {resp_waterfall.height:,}")
    return COHORT_RUN_ID, cohort_index, resp_waterfall


@app.cell
def _(EPISODE_GAP, find_episode_starts, pl, resp_waterfall):
    _scanned = find_episode_starts(
        resp_waterfall.sort(["encounter_block", "recorded_dttm"]), EPISODE_GAP
    )
    candidates = _scanned.rename({"recorded_dttm": "t0_dttm"})

    _n_cand = candidates.height
    _n_sus = candidates.filter("sustained").height
    print(f"candidate episode starts (rule 1) : {_n_cand:,}")
    print(f"  blocks represented              : {candidates.get_column('encounter_block').n_unique():,}")
    print(f"sustained (rule 2)                : {_n_sus:,}   (-{_n_cand - _n_sus:,})")
    return (candidates,)
```

- [ ] **Step 7: Run and check against the expected counts**

Run: `uv run python code/02_index_imv.py`
Expected: `candidate episode starts (rule 1) : 42,488`, `blocks represented : 34,017`, `sustained (rule 2) : 40,270   (-2,218)`.

If the candidate count is far higher, rule 1's comparison is likely `>` on the wrong side or the shift is not partitioned `.over("encounter_block")`.

- [ ] **Step 8: Commit**

```bash
git add code/02_index_imv.py docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md
git commit -m "feat(02): episode scan with the D36 duration rule

One shift(1) over imv-only rows is both the pre-period test and the
segmenter -- 6.96M waterfall rows to 42,488 candidates with no episode
loop. Adds the §5.9 worked examples to the spec and runs them as
assertions before any data loads, following 05's precedent.

42,488 candidates -> 40,270 sustained on MIMIC."
```

---

## Task 3: `02` — t₀, episode numbering, and the labels

**Files:**
- Modify: `code/02_index_imv.py`

**Interfaces:**
- Consumes: `candidates` from Task 2 and `cohort_resp_imv_raw.parquet` from Task 1.
- Produces: an in-notebook frame `episodes` with `encounter_block: Int32`, `t0_dttm: Datetime`, `ep_num: Int32`, `sustained: Boolean`, `window_start: Datetime`, `window_end: Datetime`, `no_lookback: Boolean`, `imv_charted: Boolean`, `first_charted_imv_dttm: Datetime`, `charting_delay_min: Float64`.

- [ ] **Step 1: Number the episodes and fix the window**

```python
@app.cell
def _(WINDOW, candidates, pl):
    # ep_num is assigned over the SUSTAINED set only, so the ids a reader sees are the
    # ones the study uses. Numbering candidates instead would leave gaps in the sequence
    # for every rejected row, which reads as missing data rather than as a rejection.
    episodes_numbered = (
        candidates.filter("sustained")
        .sort(["encounter_block", "t0_dttm"])
        .with_columns(
            ep_num=pl.int_range(1, pl.len() + 1).over("encounter_block").cast(pl.Int32),
            window_start=pl.col("t0_dttm") - WINDOW,
            window_end=pl.col("t0_dttm") + WINDOW,
        )
    )

    _per_block = episodes_numbered.group_by("encounter_block").len()
    print(f"episodes numbered : {episodes_numbered.height:,}")
    print(f"reintubations     : {episodes_numbered.filter(pl.col('ep_num') > 1).height:,}")
    print("\nepisodes per block:")
    print(_per_block.get_column("len").value_counts().sort("len"))
    return (episodes_numbered,)
```

- [ ] **Step 2: Assert the windows barely overlap**

```python
@app.cell
def _(WINDOW, episodes_numbered, pl):
    # Two episodes in one block are at least episode_gap_hours apart by rule 1, but the
    # medication window is window_hours EITHER SIDE, so windows can in principle overlap
    # and one administration can be ranked into two episodes. Measured on MIMIC the
    # minimum observed gap is 346 min against a 360 min overlap threshold, so this happens
    # exactly once. Reported rather than designed around -- but asserted so a site where
    # it is common finds out here instead of in Tier A.
    _gaps = episodes_numbered.sort(["encounter_block", "t0_dttm"]).with_columns(
        gap_min=(
            pl.col("t0_dttm") - pl.col("t0_dttm").shift(1).over("encounter_block")
        ).dt.total_minutes()
    )
    _overlap_min = 2 * WINDOW.total_seconds() / 60.0
    _n_overlap = _gaps.filter(pl.col("gap_min") < _overlap_min).height
    _n_pairs = _gaps.filter(pl.col("gap_min").is_not_null()).height
    _pct = 100.0 * _n_overlap / _n_pairs if _n_pairs else 0.0

    print(f"consecutive episode pairs in a block : {_n_pairs:,}")
    print(f"  with overlapping windows           : {_n_overlap:,} ({_pct:.2f}%)")
    assert _pct < 5.0, (
        f"{_pct:.1f}% of consecutive episode pairs have overlapping medication windows. "
        f"An administration in the overlap is ranked into BOTH episodes, so Tier A's "
        f"denominator double-counts it. At this rate that is no longer negligible -- "
        f"either episode_gap_hours is too small for this site or window_hours is too large."
    )
    return
```

- [ ] **Step 3: Run and confirm the overlap number**

Run: `uv run python code/02_index_imv.py`
Expected: `consecutive episode pairs in a block : 7,777`, `with overlapping windows : 1 (0.01%)`, assertion passes.

- [ ] **Step 4: Add the charting-delay statistic**

```python
@app.cell
def _(PHI_DIR, episodes_numbered, pl):
    imv_raw = pl.read_parquet(PHI_DIR / "cohort_resp_imv_raw.parquet")

    # The episode's own stretch, so a charted row belonging to the NEXT episode cannot be
    # attributed to this one.
    _bounded = episodes_numbered.sort(["encounter_block", "t0_dttm"]).with_columns(
        _next_t0=pl.col("t0_dttm").shift(-1).over("encounter_block")
    )
    _charted = (
        _bounded.join(imv_raw, on="encounter_block", how="left")
        .filter(
            (pl.col("recorded_dttm") >= pl.col("t0_dttm"))
            & (pl.col("_next_t0").is_null() | (pl.col("recorded_dttm") < pl.col("_next_t0")))
        )
        .group_by(["encounter_block", "t0_dttm"])
        .agg(first_charted_imv_dttm=pl.col("recorded_dttm").min())
    )

    episodes_labelled = (
        episodes_numbered.join(_charted, on=["encounter_block", "t0_dttm"], how="left")
        .with_columns(
            imv_charted=pl.col("first_charted_imv_dttm").is_not_null(),
            charting_delay_min=(
                pl.col("first_charted_imv_dttm") - pl.col("t0_dttm")
            ).dt.total_seconds()
            / 60.0,
        )
    )

    # D34. The waterfall relabels null-device rows to imv and never deletes a charted row,
    # so its imv set is a superset of the raw one IN TIME and its first element cannot be
    # later than the raw first element. A negative delay is therefore impossible unless the
    # two frames are on different time bases -- see §5.13.
    _neg = episodes_labelled.filter(pl.col("charting_delay_min") < 0)
    assert _neg.height == 0, (
        f"{_neg.height:,} episodes have a NEGATIVE charting delay, e.g. "
        f"{_neg.head(3).select(['encounter_block', 't0_dttm', 'first_charted_imv_dttm']).to_dicts()}. "
        "That is impossible by construction: the raw charted imv rows are a subset of the "
        "waterfalled ones. The two frames are on different time bases -- check that both "
        "went through to_site_naive (§5.13)."
    )

    _d = episodes_labelled.get_column("charting_delay_min").drop_nulls()
    print(f"charting delay (first charted imv - t0), minutes")
    print(f"  never charted : {episodes_labelled.get_column('charting_delay_min').null_count():,}")
    print(f"  exactly 0     : {(_d == 0).sum():,} ({100 * (_d == 0).mean():.1f}%)")
    for _pc in (0.5, 0.75, 0.9, 0.95, 0.99):
        print(f"  p{int(_pc * 100):<3}          : {_d.quantile(_pc):.0f}")
    print(f"  max           : {_d.max():,.0f}")
    return (episodes_labelled, imv_raw)
```

- [ ] **Step 5: Run and check the delay distribution**

Run: `uv run python code/02_index_imv.py`
Expected: `exactly 0` near 77%, `p90` near 23, `p99` near 540, `max` near 6,389, `never charted` in the single digits. The negative-delay assertion passes.

- [ ] **Step 6: Add the `no_lookback` label**

```python
@app.cell
def _(episodes_labelled, pl, resp_waterfall):
    # The old `arrived_intubated` class, kept as a label rather than an exclusion (D37).
    # It is the first number §5.11 says to read, and Tier D stratifies on it.
    _block_first = resp_waterfall.group_by("encounter_block").agg(
        _block_first_dttm=pl.col("recorded_dttm").min()
    )
    episodes = (
        episodes_labelled.join(_block_first, on="encounter_block", how="left")
        .with_columns(no_lookback=pl.col("t0_dttm") == pl.col("_block_first_dttm"))
        .drop(["_block_first_dttm", "_next_t0"])
    )

    _n = episodes.filter("no_lookback").height
    print(f"no_lookback (t0 is the block's first respiratory row) : {_n:,} "
          f"({100 * _n / episodes.height:.1f}%)")
    return (episodes,)
```

- [ ] **Step 7: Run and verify**

Run: `uv run python code/02_index_imv.py`
Expected: `no_lookback ... : 21,258` or thereabouts over the 40,270 sustained set. (The 7,130 / 52.8% figure in the spec is over the *qualified* set, which Task 4 produces — do not expect it here.)

- [ ] **Step 8: Commit**

```bash
git add code/02_index_imv.py
git commit -m "feat(02): waterfall-anchored t0, episode numbering, charting delay (D34)

t0 is the episode's first waterfalled imv row. The raw charted row is kept
as first_charted_imv_dttm and published as charting_delay_min: 77.3% zero,
p90 23 min, p99 540 min. The delay cannot be negative by construction and
02 asserts it -- a firing means the frames are on different time bases,
not that the site charts oddly.

Also asserts overlapping medication windows stay rare (1 pair of 7,777)."
```

---

## Task 4: `02` — the induction-med gate, CONSORT B, outputs

**Files:**
- Modify: `code/02_index_imv.py`

**Interfaces:**
- Consumes: `episodes` from Task 3, `cohort_index.parquet` for `list_hospitalization_id`.
- Produces: `output/intermediate_phi/index_imv.parquet` — one row per **candidate** episode with `intubation_episode_id: String`, `encounter_block: Int32`, `patient_id: String`, `cohort_run_id: String`, `ep_num: Int32`, `index_class: String`, `index_qualified: Boolean`, `t0_dttm`, `window_start`, `window_end`, `list_hospitalization_id: List(String)`, `no_lookback`, `imv_charted`, `first_charted_imv_dttm`, `charting_delay_min`. Plus `consort_index.csv`, `index_class_rates.csv`, `charting_delay.csv` in `final_no_phi/`.

- [ ] **Step 1: Load the intermittent medication table through the bridge**

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## The explode-and-drop bridge

        CLIF tables are keyed on `hospitalization_id`; this study is keyed on
        `encounter_block` and then on the episode. The bridge below is the **only** place
        this notebook may name a hospitalization, and the column is dropped the moment the
        join lands. An induction agent given in the ED presentation and an IMV row charted
        after transfer belong to one block; if `hospitalization_id` survived into the
        window filter, rule 3 would quietly revert to the unstitched unit.
        """
    )
    return


@app.cell
def _(cohort_index, pl):
    bridge = (
        cohort_index.select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    print(f"blocks              : {bridge.get_column('encounter_block').n_unique():,}")
    print(f"hospitalization ids : {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    INDUCTION_CATEGORIES,
    TIMEZONE,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    from clifpy.tables import MedicationAdminIntermittent

    # D22 -- the load-time filter runs on raw site data, before any lower-casing we
    # control, so every casing variant must be passed or a site that writes 'Propofol'
    # silently yields an empty frame.
    _variants = sorted(
        {c for m in INDUCTION_CATEGORIES for c in (m, m.upper(), m.capitalize())}
    )
    _tbl = MedicationAdminIntermittent.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "med_category", "admin_dttm", "mar_action_category"],
        filters={"hospitalization_id": bridge_hosp_ids, "med_category": _variants},
    )
    _pdf = _tbl.df.copy()
    _pdf["admin_dttm"] = to_site_naive(_pdf["admin_dttm"])

    med_induction = pl.from_pandas(_pdf).with_columns(
        med_category=pl.col("med_category").str.to_lowercase(),
        mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
    )

    _seen = set(med_induction.get_column("med_category").unique().to_list())
    _missing = sorted(set(INDUCTION_CATEGORIES) - _seen)
    assert _seen <= set(INDUCTION_CATEGORIES), (
        f"the load-time filter let through categories outside the list: "
        f"{sorted(_seen - set(INDUCTION_CATEGORIES))}"
    )
    assert med_induction.height > 0, (
        "no induction agent rows loaded at all. Either the filter's casing variants miss "
        "this site's spelling (D22) or the extract has no intermittent medications."
    )
    if _missing:
        print(f"NOT PRESENT at this site: {', '.join(_missing)}")
        print("  (rule 3 still runs -- it needs any ONE of the list, not all of them)")
    print(f"induction agent rows loaded : {med_induction.height:,}")
    print(med_induction.get_column("med_category").value_counts(sort=True))
    return (med_induction,)
```

- [ ] **Step 2: Run and confirm the load**

Run: `uv run python code/02_index_imv.py`
Expected: prints `NOT PRESENT at this site: etomidate, succinylcholine` — MIMIC's intermittent table carries neither, which is a real property of the extract and not a bug. Row count in the hundreds of thousands.

- [ ] **Step 3: Apply rule 3**

```python
@app.cell
def _(bridge, episodes, med_induction, pl):
    _given = (
        med_induction.filter(pl.col("mar_action_category") == "given")
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # the drop is the point of the bridge
        .select(["encounter_block", "admin_dttm"])
    )

    _hit = (
        episodes.select(["encounter_block", "t0_dttm", "window_start", "window_end"])
        .join(_given, on="encounter_block", how="inner")
        .filter(
            (pl.col("admin_dttm") >= pl.col("window_start"))
            & (pl.col("admin_dttm") <= pl.col("window_end"))
        )
        .select(["encounter_block", "t0_dttm"])
        .unique()
        .with_columns(has_induction_med=pl.lit(True))
    )

    episodes_gated = episodes.join(
        _hit, on=["encounter_block", "t0_dttm"], how="left"
    ).with_columns(has_induction_med=pl.col("has_induction_med").fill_null(False))

    _n = episodes_gated.filter("has_induction_med").height
    print(f"episodes with an induction agent in the window : {_n:,} "
          f"(-{episodes_gated.height - _n:,})")
    return (episodes_gated,)
```

- [ ] **Step 4: Run and check rule 3's yield**

Run: `uv run python code/02_index_imv.py`
Expected: `episodes with an induction agent in the window : 13,500 (-26,770)`.

- [ ] **Step 5: Assign `index_class` over the candidate set**

```python
@app.cell
def _(candidates, cohort_index, episodes_gated, pl):
    # index_class is assigned over the CANDIDATE set, not the sustained set: D20 keeps
    # every row 02 evaluated so Tier D can run over the rejections without a second pass.
    _rejected = (
        candidates.filter(~pl.col("sustained"))
        .select(["encounter_block", "t0_dttm"])
        .with_columns(index_class=pl.lit("not_sustained"))
    )
    _evaluated = episodes_gated.with_columns(
        index_class=pl.when(pl.col("has_induction_med"))
        .then(pl.lit("qualified"))
        .otherwise(pl.lit("no_induction_med"))
    )

    index_imv_all = (
        pl.concat([_evaluated, _rejected], how="diagonal")
        .with_columns(index_qualified=pl.col("index_class") == "qualified")
        .sort(["encounter_block", "t0_dttm"])
        .with_columns(
            ep_num=pl.col("ep_num").fill_null(
                pl.int_range(1, pl.len() + 1).over("encounter_block").cast(pl.Int32)
            )
        )
        .join(cohort_index.select(["encounter_block", "patient_id", "cohort_run_id",
                                   "list_hospitalization_id"]),
              on="encounter_block", how="left")
        .with_columns(
            intubation_episode_id=pl.format(
                "{}_E{}", pl.col("encounter_block"), pl.col("ep_num")
            )
        )
    )

    assert index_imv_all.height == candidates.height, (
        f"index_imv has {index_imv_all.height:,} rows against {candidates.height:,} "
        "candidates -- every candidate must survive with a class (D20)"
    )
    assert index_imv_all.get_column("intubation_episode_id").is_unique().all(), (
        "intubation_episode_id is not unique. ep_num is not contiguous within a block."
    )
    assert index_imv_all.get_column("index_class").null_count() == 0, "unclassified episodes"

    index_class_counts = (
        index_imv_all.get_column("index_class")
        .value_counts()
        .with_columns(pct=100.0 * pl.col("count") / index_imv_all.height)
        .sort("count", descending=True)
    )
    print(index_class_counts)
    return index_class_counts, index_imv_all
```

- [ ] **Step 6: Run and verify the class partition**

Run: `uv run python code/02_index_imv.py`
Expected: `qualified 13,500`, `no_induction_med 26,770`, `not_sustained 2,218`, summing to 42,488. All three assertions pass.

- [ ] **Step 7: Write CONSORT B with three counts per step**

```python
@app.cell
def _(index_imv_all, pl):
    consort_rows = []

    def _add(step, df, prev_n, note=""):
        consort_rows.append(
            {
                "step": step,
                "n_episodes": df.height,
                "n_blocks": df.get_column("encounter_block").n_unique(),
                "n_patients": df.get_column("patient_id").n_unique(),
                "n_excluded": 0 if prev_n is None else prev_n - df.height,
                "note": note,
            }
        )
        _r = consort_rows[-1]
        print(
            f"{_r['step']:<40} episodes={_r['n_episodes']:>9,}  "
            f"blocks={_r['n_blocks']:>9,}  patients={_r['n_patients']:>9,}  "
            f"excluded={_r['n_excluded']:>9,}"
        )
        return df.height

    _n = _add("candidate episode starts", index_imv_all, None, "rule 1, no imv within episode_gap_hours before")

    _s1 = index_imv_all.filter(pl.col("index_class") != "not_sustained")
    _n = _add("exclude: not_sustained", _s1, _n, "non-IMV device within episode_gap_hours after")

    _s2 = _s1.filter(pl.col("index_class") != "no_induction_med")
    _n = _add("exclude: no_induction_med", _s2, _n, "no induction agent in t0 +/- window_hours")

    _add("INDEX IMV EPISODE SET", _s2, None, "N**")

    consort_index_df = pl.DataFrame(consort_rows)
    return (consort_index_df,)
```

- [ ] **Step 8: Write the outputs**

```python
@app.cell
def _(
    COHORT_RUN_ID,
    PHI_DIR,
    SHARE_DIR,
    consort_index_df,
    index_class_counts,
    index_imv_all,
    pl,
):
    index_imv_out = index_imv_all.select(
        [
            "intubation_episode_id",
            "encounter_block",
            "patient_id",
            "cohort_run_id",
            "ep_num",
            "index_class",
            "index_qualified",
            "t0_dttm",
            "window_start",
            "window_end",
            "list_hospitalization_id",
            "no_lookback",
            "imv_charted",
            "first_charted_imv_dttm",
            "charting_delay_min",
        ]
    ).sort(["encounter_block", "ep_num"])

    index_imv_out.write_parquet(PHI_DIR / "index_imv.parquet")
    consort_index_df.write_csv(SHARE_DIR / "consort_index.csv")

    index_class_rates = index_class_counts.select(
        pl.lit(COHORT_RUN_ID).alias("cohort_run_id"),
        "index_class",
        pl.col("count").alias("n"),
        pl.col("pct").round(2).alias("pct_of_candidates"),
    )
    index_class_rates.write_csv(SHARE_DIR / "index_class_rates.csv")

    # charting_delay.csv -- binned, and every bin below 10 dropped rather than merged (D26).
    _bins = [0, 1, 5, 15, 30, 60, 120, 240, 480, 1440, 10**9]
    _labels = ["0", "1-4", "5-14", "15-29", "30-59", "60-119", "120-239",
               "240-479", "480-1439", "1440+"]
    _q = index_imv_out.filter(pl.col("index_qualified"))
    _binned = (
        _q.filter(pl.col("charting_delay_min").is_not_null())
        .with_columns(
            bin=pl.col("charting_delay_min").cut(_bins[1:-1], labels=_labels)
        )
        .group_by("bin")
        .len()
        .rename({"len": "n"})
    )
    _kept = _binned.filter((pl.col("n") == 0) | (pl.col("n") >= 10))
    _dropped = _binned.height - _kept.height
    charting_delay_df = _kept.with_columns(
        cohort_run_id=pl.lit(COHORT_RUN_ID),
        n_suppressed_bins=pl.lit(_dropped),
    ).select(["cohort_run_id", "bin", "n", "n_suppressed_bins"]).sort("bin")
    charting_delay_df.write_csv(SHARE_DIR / "charting_delay.csv")

    print(f"index_imv.parquet      {index_imv_out.height:,} rows -> {PHI_DIR}")
    print(f"  of which qualified   {_q.height:,}   (N**)")
    print(f"consort_index.csv      {consort_index_df.height} steps -> {SHARE_DIR}")
    print(f"index_class_rates.csv  {index_class_rates.height} classes")
    print(f"charting_delay.csv     {charting_delay_df.height} bins, {_dropped} suppressed")
    print("\nCONSORT B"); print(consort_index_df)
    return
```

- [ ] **Step 9: Run and verify every output**

Run: `uv run python code/02_index_imv.py`
Then:

```bash
uv run python -c "
import polars as pl
i = pl.read_parquet('output/intermediate_phi/index_imv.parquet')
print(i.height, 'rows;', i.filter(pl.col('index_qualified')).height, 'qualified')
q = i.filter(pl.col('index_qualified'))
assert q.height == 13500, q.height
assert q['encounter_block'].n_unique() == 12503
assert q['patient_id'].n_unique() == 11935
assert i['intubation_episode_id'].is_unique().all()
assert q.filter(pl.col('no_lookback')).height == 7130
print('index_imv.parquet verified')
print(pl.read_csv('output/final_no_phi/consort_index.csv'))
"
```
Expected: all assertions pass, CONSORT prints four rows.

- [ ] **Step 10: Confirm no PHI leaked into the published CSVs**

```bash
uv run python -c "
import polars as pl, glob
for f in ['consort_index.csv','index_class_rates.csv','charting_delay.csv']:
    c = pl.read_csv('output/final_no_phi/'+f).columns
    bad = [x for x in c if x=='patient_id' or x.endswith('_dttm')]
    assert not bad, (f, bad)
    print(f, 'OK', c)
"
```
Expected: three `OK` lines.

- [ ] **Step 11: Commit**

```bash
git add code/02_index_imv.py
git commit -m "feat(02): induction-med gate, CONSORT B on three units (D38)

Rule 3 keeps an episode only if one of the eight induction agents is
charted given in t0 +/- window_hours. 40,270 -> 13,500 over 12,503 blocks
and 11,935 patients. Every CONSORT step reports episodes, blocks and
patients, since the unit changed at the top of this stage.

index_class is assigned over the CANDIDATE set so Tier D can run over the
rejections without a second pass (D20)."
```

---

## Task 5: `03_method_sedative.py` — rekey to the episode

**Files:**
- Modify: `code/03_method_sedative.py`

**Interfaces:**
- Consumes: `index_imv.parquet` from Task 4.
- Produces: `method_SED_episode.parquet` with the §6.4 core columns keyed on `intubation_episode_id`, plus the ranked tail; and `method_SED_ranked.json` keyed on `intubation_episode_id`.

- [ ] **Step 1: Carry the episode key through the bridge**

Replace the bridge cell's projection. Note `intubation_episode_id` joins the selection and `encounter_block` stays, because the CLIF join still happens at block level and the fan-out to episodes happens here.

```python
@app.cell
def _(index_imv, pl):
    bridge = (
        index_imv.select(
            [
                "intubation_episode_id",
                "encounter_block",
                "list_hospitalization_id",
                "t0_dttm",
                "window_start",
                "window_end",
            ]
        )
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )

    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # A block with several episodes appears on several bridge rows, so one administration
    # fans out to every episode of its block and the window filter then decides which
    # episodes it actually belongs to. That fan-out is intended: an administration in the
    # overlap of two windows genuinely belongs to both. 02 asserts the overlap stays rare.
    print(f"episodes           : {bridge.get_column('intubation_episode_id').n_unique():,}")
    print(f"encounter blocks   : {bridge.get_column('encounter_block').n_unique():,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids
```

- [ ] **Step 2: Rekey the ranking rule**

In the `rank_direction` function, replace every `"encounter_block"` with `"intubation_episode_id"`:

```python
    def rank_direction(df, direction):
        """Dedup to one row per (episode, med_category), then rank by proximity.

        "LAST before" and "FIRST after" are two statements of one rule: keep the
        administration nearest t0. Both are `argmin(|delta|)`, which is why one function
        serves both directions rather than two that could drift apart.
        """
        _nearest = pl.col("abs_delta").arg_min()
        return (
            df.with_columns(abs_delta=pl.col("delta_minutes").abs())
            .sort(["intubation_episode_id", "med_category", "abs_delta", "med_dose"])
            .group_by(["intubation_episode_id", "med_category"], maintain_order=True)
            .agg(
                med_dose=pl.col("med_dose").get(_nearest),
                med_dose_unit=pl.col("med_dose_unit").get(_nearest),
                admin_dttm=pl.col("admin_dttm").get(_nearest),
                delta_minutes=pl.col("delta_minutes").get(_nearest),
                abs_delta=pl.col("abs_delta").get(_nearest),
            )
            .sort(["intubation_episode_id", "abs_delta", "med_category"])
            .with_columns(
                rank=pl.int_range(1, pl.len() + 1).over("intubation_episode_id"),
                direction=pl.lit(direction),
            )
            .drop("abs_delta")
        )
```

- [ ] **Step 3: Rekey the ladder check**

```python
    # Rank 1 is defined as nearest to t0, so WITHIN an episode |delta| must be
    # non-decreasing in rank. That is the invariant the ranking actually guarantees.
    # The median-by-rank ladder printed below usually widens too, but it is NOT
    # guaranteed to and must not be asserted on: each rank is a median over a DIFFERENT
    # set of episodes.
    for _name, _df in (("before", before_ranked), ("after", after_ranked)):
        _viol = (
            _df.sort(["intubation_episode_id", "rank"])
            .with_columns(
                _prev=pl.col("delta_minutes").abs().shift(1).over("intubation_episode_id")
            )
            .filter(pl.col("_prev").is_not_null() & (pl.col("delta_minutes").abs() < pl.col("_prev")))
        )
        assert _viol.height == 0, (
            f"{_viol.height} {_name} rows are closer to t0 than the rank above them: "
            f"{_viol.head(3).to_dicts()}"
        )
```

- [ ] **Step 4: Rekey the episode table and rename the artifact**

```python
@app.cell
def _(after_ranked, before_ranked, index_imv, METHOD_ID, pl):
    def _rank1(df, prefix):
        return df.filter(pl.col("rank") == 1).select(
            "intubation_episode_id",
            pl.col("med_category").alias(f"nearest_{prefix}_med"),
            pl.col("delta_minutes").alias(f"nearest_{prefix}_min"),
        )

    _counts_before = before_ranked.group_by("intubation_episode_id").agg(n_before=pl.len())
    _counts_after = after_ranked.group_by("intubation_episode_id").agg(n_after=pl.len())

    method_episode = (
        index_imv.select(
            [
                "intubation_episode_id",
                "encounter_block",
                "patient_id",
                "ep_num",
                "cohort_run_id",
                "index_class",
                "index_qualified",
                pl.col("t0_dttm").alias("imv_dttm"),
            ]
        )
        .join(_counts_before, on="intubation_episode_id", how="left")
        .join(_counts_after, on="intubation_episode_id", how="left")
        .join(_rank1(before_ranked, "before"), on="intubation_episode_id", how="left")
        .join(_rank1(after_ranked, "after"), on="intubation_episode_id", how="left")
        .with_columns(
            method_id=pl.lit(METHOD_ID),
            n_before=pl.col("n_before").fill_null(0).cast(pl.Int32),
            n_after=pl.col("n_after").fill_null(0).cast(pl.Int32),
        )
        # `detected` is DERIVED from the ranked structure, never computed beside it, so the
        # binary and the profile cannot disagree.
        .with_columns(detected=(pl.col("n_before") > 0) | (pl.col("n_after") > 0))
        .select(
            [
                "intubation_episode_id",
                "encounter_block",
                "patient_id",
                "ep_num",
                "cohort_run_id",
                "index_class",
                "index_qualified",
                "method_id",
                "imv_dttm",
                "detected",
                "n_before",
                "n_after",
                "nearest_before_med",
                "nearest_before_min",
                "nearest_after_med",
                "nearest_after_min",
            ]
        )
        .sort(["encounter_block", "ep_num"])
    )

    assert method_episode.height == index_imv.height, (
        "the episode table must have exactly one row per candidate episode"
    )
    assert method_episode.get_column("intubation_episode_id").is_unique().all()
    return (method_episode,)
```

- [ ] **Step 5: Rekey the NDJSON and rename both output files**

In the `method_ranked` cell replace `"encounter_block"` with `"intubation_episode_id"` in the `_nest` selection, the `group_by`, both joins and the final `sort`. In the write cell:

```python
    method_episode.write_parquet(PHI_DIR / f"method_{METHOD_ID}_episode.parquet")
    method_ranked.write_ndjson(PHI_DIR / f"method_{METHOD_ID}_ranked.json")

    # A stale _encounter.parquet from before D35 would still load in 07 and would silently
    # supply the wrong denominator, so its absence is asserted rather than assumed.
    _stale = PHI_DIR / f"method_{METHOD_ID}_encounter.parquet"
    assert not _stale.exists(), (
        f"{_stale.name} is present from the pre-D35 design. Delete it -- it holds one row "
        "per encounter and 07 must not find it."
    )
```

- [ ] **Step 6: Delete the stale artifacts and run**

```bash
rm -f output/intermediate_phi/method_*_encounter.parquet
uv run python code/03_method_sedative.py
```
Expected: runs clean, prints `method_SED_episode.parquet  42,488 rows`. The detection rate over the qualified set will be very high — near 1.0 minus the D25 on-t₀ population — which is D38 working as specified, not a bug.

- [ ] **Step 7: Verify the schema**

```bash
uv run python -c "
import polars as pl
d = pl.read_parquet('output/intermediate_phi/method_SED_episode.parquet')
assert d.columns[0] == 'intubation_episode_id', d.columns
assert d['intubation_episode_id'].is_unique().all()
q = d.filter(pl.col('index_qualified'))
print('qualified:', q.height, ' SED detected:', q['detected'].sum(), f\"({100*q['detected'].mean():.1f}%)\")
"
```
Expected: 13,500 qualified, detection well above 90%.

- [ ] **Step 8: Commit**

```bash
git add code/03_method_sedative.py
git commit -m "feat(03): rekey SED to intubation_episode_id (D35)

Bridge carries the episode key, so one administration fans out to every
episode of its block and the window filter decides which it belongs to.
Ranking, ladder check and NDJSON all keyed on the episode.
method_SED_encounter.parquet -> method_SED_episode.parquet, with an
assertion that the stale file is gone."
```

---

## Task 6: `04_method_paralytic.py` — the same rekey, applied independently

**Files:**
- Modify: `code/04_method_paralytic.py`

**Interfaces:**
- Consumes: `index_imv.parquet` from Task 4.
- Produces: `method_PARA_episode.parquet`, `method_PARA_ranked.json`, both keyed on `intubation_episode_id`.

- [ ] **Step 1: Apply Task 5 steps 1–5 to `04`**

`04` is a deliberate copy of `03` differing only in `MED_CATEGORIES = ["rocuronium", "succinylcholine", "vecuronium"]` and prose (D8). Apply the identical edits from Task 5 steps 1, 2, 3, 4 and 5 — bridge projection, `rank_direction`, ladder check, `method_episode`, NDJSON and both filenames.

**Do not** factor the shared code into a helper. The duplication is the point: a bug in a shared helper would corrupt `SED` and `PARA` identically, and correlated errors are indistinguishable from genuine agreement — the one failure mode an agreement study cannot survive.

- [ ] **Step 2: Run and verify**

```bash
uv run python code/04_method_paralytic.py
uv run python -c "
import polars as pl
d = pl.read_parquet('output/intermediate_phi/method_PARA_episode.parquet')
assert d['intubation_episode_id'].is_unique().all()
q = d.filter(pl.col('index_qualified'))
print('qualified:', q.height, ' PARA detected:', q['detected'].sum(), f\"({100*q['detected'].mean():.1f}%)\")
"
```
Expected: 13,500 qualified. `PARA`'s rate stays low — MIMIC's intermittent table carries no `succinylcholine`, which `04` prints as a missing agent.

- [ ] **Step 3: Confirm the two notebooks did not converge**

```bash
diff <(grep -c "" code/03_method_sedative.py) <(grep -c "" code/04_method_paralytic.py) || true
grep -n "MED_CATEGORIES = " code/03_method_sedative.py code/04_method_paralytic.py
```
Expected: the two `MED_CATEGORIES` lines differ. If either notebook now imports from the other, revert that — D8 forbids it.

- [ ] **Step 4: Commit**

```bash
git add code/04_method_paralytic.py
git commit -m "feat(04): rekey PARA to intubation_episode_id (D35)

The same edits as 03, applied independently rather than factored out. D8:
a shared helper would corrupt both methods identically and correlated
errors are indistinguishable from agreement."
```

---

## Task 7: `05_method_pair.py` — rekey and assign pairs to episodes

**Files:**
- Modify: `code/05_method_pair.py`

**Interfaces:**
- Consumes: `index_imv.parquet` from Task 4.
- Produces: `method_PAIR_pairs.parquet` with `intubation_episode_id` populated by the D39 assignment, and `method_PAIR_episode.parquet` with the §6.5 pair extension keyed on `intubation_episode_id`.

- [ ] **Step 1: Leave the scan alone**

The forward pass with consumption (`scan_encounter`) and the §7.3 self-test are unchanged. The scan is free-running over the block (D27) and knows nothing about episodes — that is correct and stays. Only what happens to its output changes.

- [ ] **Step 2: Change the bridge to block-level and keep episodes separate**

The scan needs block-level rows, not episode-level, so the bridge must **not** fan out. Replace the bridge cell:

```python
@app.cell
def _(index_imv, pl):
    # Block-level, deliberately. The scan is free-running over the whole block (D27), so
    # fanning the administrations out to episodes here would run the scan once per episode
    # and break D28's consumption across the boundary. Episodes rejoin at the assignment
    # step, after the pairs exist.
    bridge = (
        index_imv.select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
        .unique()
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    print(f"encounter blocks   : {bridge.get_column('encounter_block').n_unique():,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids
```

- [ ] **Step 3: Write the failing assertion for the D39 assignment**

Add this cell after the pairs frame is built but before it is written. It will fail until Step 4 exists.

```python
@app.cell
def _(pairs_assigned, pairs_raw, pl):
    # D39 is a PARTITION, not a labelling: summing n_pairs over a block's episodes must
    # recover the block's pair count exactly. A pair scored into two episodes would inflate
    # every rate in Tier E and would not show up anywhere else.
    _per_block_before = pairs_raw.group_by("encounter_block").len().rename({"len": "n_raw"})
    _per_block_after = (
        pairs_assigned.group_by("encounter_block").len().rename({"len": "n_assigned"})
    )
    _cmp = _per_block_before.join(_per_block_after, on="encounter_block", how="full", coalesce=True)
    _bad = _cmp.filter(
        pl.col("n_raw").fill_null(0) != pl.col("n_assigned").fill_null(0)
    )
    assert _bad.height == 0, (
        f"{_bad.height} blocks lost or duplicated pairs in the episode assignment: "
        f"{_bad.head(3).to_dicts()}. D39 must partition."
    )
    assert pairs_assigned.get_column("intubation_episode_id").null_count() == 0, (
        "some pairs were not assigned to an episode. Every pair is in a block, and every "
        "block in index_imv has at least one candidate episode, so this cannot happen "
        "unless the join key is wrong."
    )
    print(f"D39 assignment is a partition: {pairs_assigned.height:,} pairs conserved")
    return
```

- [ ] **Step 4: Run and watch it fail**

Run: `uv run python code/05_method_pair.py`
Expected: `NameError: name 'pairs_assigned' is not defined` — the assignment cell does not exist yet.

- [ ] **Step 5: Implement the D39 assignment**

Insert this cell before the assertion cell. `pairs_raw` is the scan's output before assignment; rename the existing pairs frame to `pairs_raw` if it is called something else.

```python
@app.cell
def _(index_imv, pairs_raw, pl):
    # D39 -- each pair goes to the episode whose t0 is nearest to pair_dttm, ties to the
    # earlier episode. Nearest-t0 needs no new concept: every pair already carries a
    # distance to a t0. The alternative, re-running the scan per episode, would need an
    # episode END the design does not define.
    _eps = index_imv.select(
        ["encounter_block", "intubation_episode_id", "ep_num", "t0_dttm",
         "window_start", "window_end", "patient_id", "cohort_run_id",
         "index_class", "index_qualified"]
    )

    pairs_assigned = (
        pairs_raw.join(_eps, on="encounter_block", how="inner")
        .with_columns(
            _dist=(pl.col("pair_dttm") - pl.col("t0_dttm")).dt.total_seconds().abs()
        )
        # ep_num breaks the tie toward the earlier episode.
        .sort(["pair_id", "_dist", "ep_num"])
        .group_by("pair_id", maintain_order=True)
        .first()
        .drop("_dist")
        .with_columns(
            imv_dttm=pl.col("t0_dttm"),
            pair_to_t0_min=(
                pl.col("pair_dttm") - pl.col("t0_dttm")
            ).dt.total_seconds() / 60.0,
            in_window=(pl.col("pair_dttm") >= pl.col("window_start"))
            & (pl.col("pair_dttm") <= pl.col("window_end")),
        )
        .sort(["encounter_block", "pair_seq"])
    )

    _multi = (
        pairs_assigned.join(
            index_imv.group_by("encounter_block").len().filter(pl.col("len") > 1),
            on="encounter_block", how="semi",
        )
    )
    print(f"pairs assigned            : {pairs_assigned.height:,}")
    print(f"  in multi-episode blocks : {_multi.height:,}")
    print(f"  in_window               : {pairs_assigned.get_column('in_window').sum():,}")
    return (pairs_assigned,)
```

- [ ] **Step 6: Run and verify the partition assertion passes**

Run: `uv run python code/05_method_pair.py`
Expected: `D39 assignment is a partition: N pairs conserved`, and the §7.3 worked examples still print `(a)-(f) pass`.

- [ ] **Step 7: Rekey the episode aggregation**

In the cell that collapses pairs to one row per unit, replace `encounter_block` with `intubation_episode_id` in the `group_by`, the joins onto `index_imv`, and the final `sort`. Rename the frame and the output file:

```python
    method_episode.write_parquet(PHI_DIR / f"method_{METHOD_ID}_episode.parquet")
    pairs_out.write_parquet(PHI_DIR / f"method_{METHOD_ID}_pairs.parquet")

    assert not (PHI_DIR / f"method_{METHOD_ID}_ranked.json").exists(), (
        "a stale method_PAIR_ranked.json is present from an earlier design. Delete it -- "
        "PAIR emits no ranked artifact (D30) and 07 must not find one."
    )
    assert not (PHI_DIR / f"method_{METHOD_ID}_encounter.parquet").exists(), (
        "a stale method_PAIR_encounter.parquet is present from the pre-D35 design."
    )
```

- [ ] **Step 8: Run and verify the episode-level output**

```bash
uv run python code/05_method_pair.py
uv run python -c "
import polars as pl
e = pl.read_parquet('output/intermediate_phi/method_PAIR_episode.parquet')
p = pl.read_parquet('output/intermediate_phi/method_PAIR_pairs.parquet')
assert e['intubation_episode_id'].is_unique().all()
assert e.height == 42488, e.height
assert (e['detected'] == (e['n_pairs'] > 0)).all(), 'detected must be derived from n_pairs'
assert e.group_by('intubation_episode_id').len()['len'].max() == 1
assert p['intubation_episode_id'].null_count() == 0
print('pairs:', p.height, ' episodes with a pair:', e['detected'].sum())
print('sum n_pairs == pair rows:', e['n_pairs'].sum() == p.height)
"
```
Expected: all assertions pass and `sum n_pairs == pair rows: True`.

- [ ] **Step 9: Commit**

```bash
git add code/05_method_pair.py
git commit -m "feat(05): assign pairs to the nearest episode (D39)

The free-running scan is untouched -- it still runs once per block with
D28 consumption intact, and the bridge stays block-level so fanning out to
episodes cannot break the pass. Each resulting pair is then assigned to the
episode whose t0 is nearest, ties to the earlier.

The assignment is asserted to be a partition: summing n_pairs over a
block's episodes recovers the block's pair count. A pair scored twice
would inflate every Tier E rate and show up nowhere else."
```

---

## Task 8: `06_reference_cpt.py` — rekey

**Files:**
- Modify: `code/06_reference_cpt.py`

**Interfaces:**
- Consumes: `index_imv.parquet` from Task 4.
- Produces: `reference_cpt.parquet` with one row per candidate episode keyed on `intubation_episode_id`, carrying `cpt_present: Boolean`, `encounter_block`, `cohort_run_id`, `index_class`, `index_qualified`.

- [ ] **Step 1: Rekey the output and record the block-level limitation**

CPT carries no usable timing (D1), so a code billed anywhere in the block marks every episode of that block. Add the note at the point where the fan-out happens:

```python
@app.cell
def _(index_imv, pl, proc_cohort):
    _blocks_with_code = (
        proc_cohort.select("encounter_block").unique().with_columns(cpt_present=pl.lit(True))
    )

    # A code billed anywhere in the block marks EVERY episode of that block. CPT has no
    # usable timing (D1), so it cannot distinguish a block's first intubation from its
    # reintubation. Tier C therefore reports at block level, and the fan-out here is
    # bookkeeping rather than a claim about which episode was coded.
    reference_cpt = (
        index_imv.select(
            ["intubation_episode_id", "encounter_block", "patient_id", "ep_num",
             "cohort_run_id", "index_class", "index_qualified"]
        )
        .join(_blocks_with_code, on="encounter_block", how="left")
        .with_columns(cpt_present=pl.col("cpt_present").fill_null(False))
        .sort(["encounter_block", "ep_num"])
    )

    assert reference_cpt.height == index_imv.height
    assert reference_cpt.get_column("intubation_episode_id").is_unique().all()
    return (reference_cpt,)
```

- [ ] **Step 2: Rebase the capture gate on episodes**

```python
    # D24 -- capture is computed BEFORE anything is scored.
    _q = reference_cpt.filter(pl.col("index_qualified"))
    _n_with = _q.filter("cpt_present").height
    capture_rate = _n_with / _q.height if _q.height else 0.0
    informative = (_n_with >= 10) and (capture_rate >= 0.05)

    print(f"index-set episodes            : {_q.height:,}")
    print(f"  carrying CPT 31500          : {_n_with:,}")
    print(f"  capture rate                : {capture_rate:.4f}")
    print(f"  blocks carrying the code    : {_q.filter('cpt_present')['encounter_block'].n_unique():,}")
    print(f"  informative (D24)           : {informative}")
    if not informative:
        print("  -> 07 writes reference_scoring.csv with null metrics, which is the true result")
```

- [ ] **Step 3: Run and verify**

```bash
uv run python code/06_reference_cpt.py
uv run python -c "
import polars as pl
r = pl.read_parquet('output/intermediate_phi/reference_cpt.parquet')
assert r.height == 42488, r.height
assert r['intubation_episode_id'].is_unique().all()
print('reference_cpt rekeyed OK;', r.filter(pl.col('index_qualified') & pl.col('cpt_present')).height, 'qualified episodes carry the code')
"
```
Expected: assertions pass, and the code count is in the single digits — MIMIC's extract holds 116 CPT rows, so `informative` is `False`, which is the published result.

- [ ] **Step 4: Commit**

```bash
git add code/06_reference_cpt.py
git commit -m "feat(06): rekey CPT reference to the episode (D35)

A code billed anywhere in the block marks every episode of that block --
CPT has no usable timing, so it cannot tell a first intubation from a
reintubation. Recorded at the fan-out and reflected in Tier C's unit.
Capture gate rebased on qualified episodes."
```

---

## Task 9: `07` — schema gate, rename, two-unit reporting, Tier A relabel

**Files:**
- Modify: `code/07_agreement.py`

**Interfaces:**
- Consumes: `method_{SED,PARA,PAIR}_episode.parquet`, `method_{SED,PARA}_ranked.json`, `method_PAIR_pairs.parquet`, `reference_cpt.parquet`, `index_imv.parquet`.
- Produces: unchanged Tier A/B/C/E CSV filenames, with `n_blocks` and `n_patients` columns added to every rate table.

- [ ] **Step 1: Update the schema gatekeeper**

```python
    _CORE = {
        "intubation_episode_id": pl.String,
        "encounter_block": pl.Int32,
        "patient_id": pl.String,
        "ep_num": pl.Int32,
        "cohort_run_id": pl.String,
        "index_class": pl.String,
        "index_qualified": pl.Boolean,
        "method_id": pl.String,
        "imv_dttm": pl.Datetime,
        "detected": pl.Boolean,
    }
```

and the load loop:

```python
    for _m in ("SED", "PARA", "PAIR"):
        _df = pl.read_parquet(PHI_DIR / f"method_{_m}_episode.parquet")
        _cols, _types = EPISODE_SCHEMA[_m]
        ...
```

Rename `ENCOUNTER_SCHEMA` to `EPISODE_SCHEMA` throughout.

- [ ] **Step 2: Update the `detected` derivation check**

```python
        _derived = (
            (pl.col("n_pairs") > 0) if _m == "PAIR"
            else ((pl.col("n_before") > 0) | (pl.col("n_after") > 0))
        )
        _mismatch = _df.filter(pl.col("detected") != _derived).height
        assert _mismatch == 0, (
            f"{_m}: {_mismatch} rows where `detected` disagrees with the structure it is "
            "supposed to be derived from (§6.4). The two were computed separately."
        )
```

- [ ] **Step 3: Rekey the join and add the unit assertion**

```python
    _keys = ["intubation_episode_id", "encounter_block", "patient_id", "ep_num",
             "index_class", "index_qualified"]
    ...
    assert joined.height == index_imv.height, (
        f"the joined table has {joined.height:,} rows against {index_imv.height:,} "
        "candidate episodes -- a join fanned out or dropped rows"
    )
    assert joined.get_column("intubation_episode_id").is_unique().all()
```

- [ ] **Step 4: Add the two-unit reporting helper**

Every rate table gains block and patient counts, because under D35 an episode rate and an encounter rate are different quantities.

```python
@app.cell
def _(pl):
    def unit_counts(df):
        """Episodes, blocks and patients for one frame.

        Reported on every rate table under D35: a block may contribute several episodes,
        so an episode rate and an encounter rate are different numbers and a table that
        names neither is ambiguous. It also makes the dependence visible where it matters
        -- kappa assumes independent units, and a block contributing seven episodes
        violates that quietly.
        """
        return {
            "n_episodes": df.height,
            "n_blocks": df.get_column("encounter_block").n_unique(),
            "n_patients": df.get_column("patient_id").n_unique(),
        }

    return (unit_counts,)
```

Apply it to A.1: add `n_blocks` and `n_patients` columns alongside the existing `n`.

- [ ] **Step 5: Relabel the A.2 `neither` cell**

In the A.2 construction, after the contingency counts are built:

```python
    # D38 -- the `neither` cell is empty by construction for SED x PARA, because the
    # episode filter reads the same eight drugs over the same window. What lands there is
    # the D25 population: an administration falling exactly on t0 belongs to neither
    # half-open direction, so the episode passes rule 3 and still scores detected=false.
    # Labelled rather than reported as a finding.
    _cell_note = pl.when(
        (pl.col("method_a") == "SED") & (pl.col("method_b") == "PARA")
        & (pl.col("cell") == "neither")
    ).then(pl.lit("D25 on-t0 charting, not disagreement (D38)")).otherwise(pl.lit(""))
    a2_pub = a2_pub.with_columns(cell_note=_cell_note)
```

- [ ] **Step 6: Run and check Tier A**

```bash
uv run python code/07_agreement.py 2>&1 | head -80
```
Expected: the schema gate passes for all three methods, `joined` has 42,488 rows, A.1 prints with `n_blocks` and `n_patients`, and the `SED`/`PARA` union rate over the qualified set is at or very near 1.000 — D38 working as specified.

- [ ] **Step 7: Commit**

```bash
git add code/07_agreement.py
git commit -m "feat(07): episode schema gate and two-unit reporting (D35, D38)

EPISODE_SCHEMA keyed on intubation_episode_id, methods loaded from
_episode.parquet. Every rate table carries n_episodes, n_blocks and
n_patients, since under D35 those are three different denominators and
kappa's independence assumption is visibly strained by a block that
contributes seven episodes.

A.2's SED x PARA `neither` cell is labelled as the D25 on-t0 population
rather than reported as agreement evidence."
```

---

## Task 10: `07` — Tier D rewritten

**Files:**
- Modify: `code/07_agreement.py`

**Interfaces:**
- Consumes: `joined` from Task 9.
- Produces: `specificity_by_lookback.csv`, `specificity_by_ep_num.csv`, `specificity_not_sustained.csv`, `specificity_pair_free_running.csv`, `specificity_gap.csv`.

- [ ] **Step 1: Replace the Tier D markdown cell**

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## Tier D — specificity

        **This tier was weakened by D37 and says so.** It used to rest on
        `arrived_intubated`: those patients were intubated before arrival, so any `SED`
        firing around their first charted IMV row was a false positive *by construction* —
        the one stratum in the study whose answer was known without a gold standard.

        D37 admits that group to the primary analysis. The replacement contrasts below are
        weaker, and **each names its own confounder**. None is a false-positive count by
        construction.

        D.4 is the salvage. `SED`, `PARA` and `PAIR`'s windowed reading are all identically
        zero on the `no_induction_med` stratum, because D38 rejected those episodes for
        containing none of the drugs those three look for. `PAIR` on the free-running basis
        is not constrained — its scan covers the whole block — so its rate there measures
        ambient sedative–paralytic pairing on the largest stratum in the study.
        """
    )
    return
```

- [ ] **Step 2: D.1 by `no_lookback`**

```python
@app.cell
def _(SHARE_DIR, analytic, apply_min_cell, detected_expr, pl, unit_counts):
    def _rates(df, group_col, label_col):
        _rows = []
        for _grp, _sub in df.group_by(group_col, maintain_order=True):
            _v = _grp[0] if isinstance(_grp, tuple) else _grp
            _r = {label_col: str(_v), **unit_counts(_sub)}
            for _m, _b in (("SED", None), ("PARA", None),
                           ("PAIR", "in_window"), ("PAIR", "free_running")):
                _name = _m if _b is None else f"{_m}_{_b}"
                _r[f"{_name}_n"] = int(_sub.select(detected_expr(_m, _b or "free_running")).to_series().sum())
                _r[f"{_name}_rate"] = round(
                    _sub.select(detected_expr(_m, _b or "free_running")).to_series().mean(), 4
                )
            _rows.append(_r)
        return pl.DataFrame(_rows)

    d1 = _rates(analytic.sort("no_lookback"), "no_lookback", "no_lookback")
    d1_pub = apply_min_cell(
        d1, [c for c in d1.columns if c.endswith("_n") or c.startswith("n_")], "D.1"
    )
    d1_pub.write_csv(SHARE_DIR / "specificity_by_lookback.csv")
    print("D.1 detection rate by no_lookback")
    print("  confounder: case mix. These patients are disproportionately transfers.")
    print(d1_pub)
    return d1_pub, _rates
```

- [ ] **Step 3: D.2 by `ep_num`**

```python
@app.cell
def _(SHARE_DIR, _rates, analytic, apply_min_cell, pl):
    _binned = analytic.with_columns(
        ep_group=pl.when(pl.col("ep_num") == 1).then(pl.lit("1")).otherwise(pl.lit(">1"))
    ).sort("ep_group")
    d2 = _rates(_binned, "ep_group", "ep_num")
    d2_pub = apply_min_cell(
        d2, [c for c in d2.columns if c.endswith("_n") or c.startswith("n_")], "D.2"
    )
    d2_pub.write_csv(SHARE_DIR / "specificity_by_ep_num.csv")
    print("D.2 detection rate by episode number")
    print("  confounder: illness trajectory. A reintubation happens deep in an ICU stay,")
    print("  where the ambient rate of sedative charting is far higher.")
    print(d2_pub)
    return (d2_pub,)
```

- [ ] **Step 4: D.3 the `not_sustained` stratum**

```python
@app.cell
def _(SHARE_DIR, _rates, apply_min_cell, joined, pl):
    _probe = joined.filter(
        pl.col("index_class").is_in(["qualified", "not_sustained"])
    ).sort("index_class")
    d3 = _rates(_probe, "index_class", "index_class")
    d3_pub = apply_min_cell(
        d3, [c for c in d3.columns if c.endswith("_n") or c.startswith("n_")], "D.3"
    )
    d3_pub.write_csv(SHARE_DIR / "specificity_not_sustained.csv")
    print("D.3 qualified vs not_sustained -- the residual probe")
    print("  confounder: a not_sustained episode adjacent to a real intubation elsewhere")
    print("  in the block can borrow its medications.")
    print(d3_pub)
    return (d3_pub,)
```

- [ ] **Step 5: D.4 the degenerate-stratum table**

```python
@app.cell
def _(SHARE_DIR, detected_expr, joined, pl):
    _nim = joined.filter(pl.col("index_class") == "no_induction_med")

    _rows = []
    for _m, _b, _interp in (
        ("SED", "free_running", False),
        ("PARA", "free_running", False),
        ("PAIR", "in_window", False),
        ("PAIR", "free_running", True),
    ):
        _n = int(_nim.select(detected_expr(_m, _b)).to_series().sum())
        _rows.append({
            "method": _m,
            "basis": _b if _m == "PAIR" else "",
            "n_detected": _n,
            "rate": round(_n / _nim.height, 4) if _nim.height else None,
            "interpretable": _interp,
            "note": "" if _interp else "0 by construction (D38) -- reporting the filter, not a result",
        })
    d4 = pl.DataFrame(_rows)

    # The three degenerate rows MUST be zero. If one is not, the D38 filter in 02 and the
    # method's own medication list have drifted apart, and Tier A's denominator is wrong.
    _nonzero = d4.filter(~pl.col("interpretable") & (pl.col("n_detected") > 0))
    assert _nonzero.height == 0, (
        f"{_nonzero.to_dicts()} fired on the no_induction_med stratum. Those episodes were "
        "rejected for containing none of the eight induction agents in the window, so a "
        "windowed method cannot detect one. 02's INDUCTION_CATEGORIES and this method's "
        "MED_CATEGORIES have drifted apart (D38)."
    )

    d4.write_csv(SHARE_DIR / "specificity_pair_free_running.csv")
    print(f"D.4 the no_induction_med stratum, n = {_nim.height:,}")
    print("  PAIR free_running is the only interpretable row: its scan covers the whole")
    print("  block, so it is not constrained by the window filter that built this stratum.")
    print(d4)
    return (d4,)
```

- [ ] **Step 6: The specificity summary table**

```python
@app.cell
def _(SHARE_DIR, d1_pub, d3_pub, d4, pl):
    _q = {r["index_class"]: r for r in d3_pub.to_dicts()}.get("qualified", {})
    _ns = {r["index_class"]: r for r in d3_pub.to_dicts()}.get("not_sustained", {})
    _d4 = {(r["method"], r["basis"]): r for r in d4.to_dicts()}

    _rows = []
    for _name, _key in (("SED", "SED"), ("PARA", "PARA"),
                        ("PAIR in_window", "PAIR_in_window")):
        _qr, _nr = _q.get(f"{_key}_rate"), _ns.get(f"{_key}_rate")
        _rows.append({
            "method": _name, "contrast": "D.3 not_sustained",
            "qualified": _qr, "comparator": _nr,
            "gap": round(_qr - _nr, 4) if (_qr is not None and _nr is not None) else None,
            "known_answer": False,
        })
    _qr = _q.get("PAIR_free_running_rate")
    _nr = _d4[("PAIR", "free_running")]["rate"]
    _rows.append({
        "method": "PAIR free_running", "contrast": "D.4 no_induction_med",
        "qualified": _qr, "comparator": _nr,
        "gap": round(_qr - _nr, 4) if (_qr is not None and _nr is not None) else None,
        "known_answer": False,
    })

    specificity_gap = pl.DataFrame(_rows)
    specificity_gap.write_csv(SHARE_DIR / "specificity_gap.csv")
    print("D summary -- a method whose gap approaches zero is detecting being in an ICU,")
    print("not detecting intubation. `known_answer` is False on every row: D37 removed the")
    print("one stratum where it was True.")
    print(specificity_gap)
    return (specificity_gap,)
```

- [ ] **Step 7: Delete the stale D.1 artifact and run**

```bash
rm -f output/final_no_phi/specificity_by_index_class.csv
uv run python code/07_agreement.py 2>&1 | tail -60
```
Expected: five specificity CSVs written, the D.4 zero-assertion passes, and `specificity_gap.csv` has four rows all carrying `known_answer = false`.

- [ ] **Step 8: Commit**

```bash
git add code/07_agreement.py
git commit -m "feat(07): rewrite Tier D after D37 removed its comparator

D37 admitted arrived_intubated to the primary analysis, which was the one
stratum whose answer was known by construction. The replacement is four
contrasts that each name their own confounder, and the summary table
carries known_answer=false on every row rather than implying otherwise.

D.4 is the salvage: SED, PARA and PAIR-in-window are all identically zero
on no_induction_med because D38 built that stratum out of their own
medication list -- and that zero is ASSERTED, so a drift between 02's
INDUCTION_CATEGORIES and a method's MED_CATEGORIES fails here. PAIR
free-running is unconstrained and measures ambient pairing on 26,770
episodes."
```

---

## Task 11: `07` — the two new figures and manifest conformance

**Files:**
- Modify: `code/07_agreement.py`

**Interfaces:**
- Consumes: `consort_index.csv` and `charting_delay.csv` from Task 4, `specificity_gap.csv` from Task 10.
- Produces: `episode_funnel.png`, `charting_delay.png`, and an updated `specificity_gap.png`.

- [ ] **Step 1: `episode_funnel.png`**

Drawn from the published CSV, never from the PHI frames (D26).

```python
@app.cell
def _(SHARE_DIR, finish, plt, pl):
    _c = pl.read_csv(SHARE_DIR / "consort_index.csv")
    _fig, _ax = plt.subplots(figsize=(9, 5))
    _steps = _c.get_column("step").to_list()
    _eps = _c.get_column("n_episodes").to_list()
    _y = range(len(_steps))
    _ax.barh(list(_y), _eps, color="#4C72B0")
    _ax.set_yticks(list(_y))
    _ax.set_yticklabels(_steps, fontsize=9)
    _ax.invert_yaxis()
    _ax.set_xlabel("episodes")
    for _i, (_e, _b, _p) in enumerate(
        zip(_eps, _c.get_column("n_blocks"), _c.get_column("n_patients"))
    ):
        _ax.text(_e, _i, f"  {_e:,} ep / {_b:,} blk / {_p:,} pt", va="center", fontsize=8)
    _ax.set_xlim(0, max(_eps) * 1.45)
    finish(
        _fig, "episode_funnel.png",
        "CONSORT B. Three units per step: a block may contribute several episodes, so "
        "the episode count and the encounter count are different quantities (D35). "
        "Drawn from consort_index.csv.",
    )
    return
```

- [ ] **Step 2: `charting_delay.png`**

```python
@app.cell
def _(SHARE_DIR, finish, plt, pl):
    _d = pl.read_csv(SHARE_DIR / "charting_delay.csv")
    _sup = int(_d.get_column("n_suppressed_bins")[0]) if _d.height else 0
    _fig, _ax = plt.subplots(figsize=(9, 4.5))
    _ax.bar(_d.get_column("bin").to_list(), _d.get_column("n").to_list(), color="#DD8452")
    _ax.set_xlabel("first charted IMV row − t₀  (minutes)")
    _ax.set_ylabel("episodes")
    _ax.set_yscale("log")
    _ax.set_xticklabels(_d.get_column("bin").to_list(), rotation=16, ha="right")
    finish(
        _fig, "charting_delay.png",
        "How late the device field is filled in relative to the settings-based inference "
        "that anchors t₀ (D34). Zero for 77% of episodes, but the p99 is nine hours — "
        "which is a charting delay, not a settings-reading error. "
        f"{_sup} bin(s) suppressed below n = 10 and dropped rather than merged (D26).",
    )
    return
```

- [ ] **Step 3: Repoint `specificity_gap.png` at the new table**

The figure reads `specificity_gap.csv`, whose columns changed in Task 10 — it now has `method`, `contrast`, `qualified`, `comparator`, `gap`, `known_answer` instead of one row per `index_class`. Redraw as a paired bar per method:

```python
    _s = pl.read_csv(SHARE_DIR / "specificity_gap.csv")
    _fig, _ax = plt.subplots(figsize=(9, 4.5))
    _x = range(_s.height)
    _w = 0.38
    _ax.bar([i - _w / 2 for i in _x], _s.get_column("qualified").to_list(), _w,
            label="qualified", color="#4C72B0")
    _ax.bar([i + _w / 2 for i in _x], _s.get_column("comparator").to_list(), _w,
            label="comparator", color="#C44E52")
    _ax.set_xticks(list(_x))
    _ax.set_xticklabels(_s.get_column("method").to_list(), rotation=16, ha="right")
    _ax.set_ylabel("detection rate")
    _ax.legend()
    finish(
        _fig, "specificity_gap.png",
        "Detection rate in the index set against each method's comparator stratum. "
        "`known_answer` is false on every row: D37 admitted arrived_intubated to the "
        "primary analysis, which was the only stratum whose answer was known by "
        "construction. Each contrast's confounder is named in Tier D.",
    )
```

- [ ] **Step 4: Run and check every figure exists**

```bash
uv run python code/07_agreement.py
ls -1 output/final_no_phi/*.png
```
Expected: ten PNGs including `episode_funnel.png` and `charting_delay.png`.

- [ ] **Step 5: Assert the output manifest matches the spec**

Add a final cell to `07`:

```python
@app.cell
def _(SHARE_DIR):
    # §8's "Outputs written by 07" plus the two CONSORTs and 02's tables. Declared here so
    # a table added without a spec entry -- or promised and never written -- fails loudly.
    _expected = {
        "consort_cohort.csv", "cohort_qc.csv",
        "consort_index.csv", "index_class_rates.csv", "charting_delay.csv",
        "agreement_detection_rates.csv", "agreement_pairwise.csv",
        "agreement_concordance.csv", "agreement_combinations.csv",
        "timing_offset_summary.csv", "timing_offset_by_rank.csv", "timing_by_medication.csv",
        "reference_capture_rate.csv", "reference_scoring.csv",
        "specificity_by_lookback.csv", "specificity_by_ep_num.csv",
        "specificity_not_sustained.csv", "specificity_pair_free_running.csv",
        "specificity_gap.csv",
        "pair_count_distribution.csv", "pair_gap_distribution.csv",
        "pair_agent_combinations.csv", "pair_index_offsets.csv", "pair_t0_concordance.csv",
        "consort_flow.png", "index_class_strata.png", "episode_funnel.png",
        "charting_delay.png", "timing_offset_distribution.png", "timing_by_medication.png",
        "agreement_overview.png", "specificity_gap.png",
        "pair_offset_distribution.png", "pair_agent_combinations.png",
    }
    _actual = {p.name for p in SHARE_DIR.iterdir() if p.suffix in (".csv", ".png")}
    assert not (_expected - _actual), f"declared but MISSING: {sorted(_expected - _actual)}"
    assert not (_actual - _expected), f"present but UNDECLARED: {sorted(_actual - _expected)}"
    print(f"output manifest conforms to §8: {len(_actual)} artifacts")
    return
```

- [ ] **Step 6: Run and reconcile the manifest**

Run: `uv run python code/07_agreement.py`
If the assertion fires with `present but UNDECLARED`, the file is either a stale artifact from a previous design — delete it — or a real new output, in which case add it to both `_expected` and §8's table in the spec.

- [ ] **Step 7: Commit**

```bash
git add code/07_agreement.py
git commit -m "feat(07): episode funnel and charting-delay figures, manifest assert

Both drawn from published CSVs rather than PHI frames (D26), so the n>=10
suppression is inherited instead of reimplemented. specificity_gap.png
redrawn against Tier D's new table shape.

Adds a manifest assertion against §8: a table written without a spec entry,
or promised and never written, now fails at the end of the run."
```

---

## Task 12: Full-pipeline verification

**Files:**
- No production changes. Creates: `docs/superpowers/plans/2026-08-06-episode-unit-rewrite-verification.md`

**Interfaces:**
- Consumes: everything.
- Produces: a verification record.

- [ ] **Step 1: Clean run from scratch**

```bash
rm -rf output/intermediate_phi/*.parquet output/intermediate_phi/*.json
for n in 01_cohort 02_index_imv 03_method_sedative 04_method_paralytic \
         05_method_pair 06_reference_cpt 07_agreement; do
  echo "=== $n ==="
  uv run python code/$n.py > /tmp/venttrace_$n.log 2>&1 && echo PASS || { echo FAIL; tail -30 /tmp/venttrace_$n.log; break; }
done
```
Expected: seven `PASS` lines.

- [ ] **Step 2: Check the headline numbers**

```bash
uv run python -c "
import polars as pl
i = pl.read_parquet('output/intermediate_phi/index_imv.parquet')
q = i.filter(pl.col('index_qualified'))
checks = [
  ('candidate episodes', i.height, 42488),
  ('qualified episodes', q.height, 13500),
  ('qualified blocks', q['encounter_block'].n_unique(), 12503),
  ('qualified patients', q['patient_id'].n_unique(), 11935),
  ('reintubations', q.filter(pl.col('ep_num')>1).height, 997),
  ('no_lookback', q.filter(pl.col('no_lookback')).height, 7130),
]
for name, got, want in checks:
    print(f'{name:<22} {got:>8,}  expected {want:>8,}  {\"OK\" if got==want else \"MISMATCH\"}')
"
```
Expected: six `OK` lines. A mismatch means a rule diverged from the spec — do not adjust the expected value, find the rule.

- [ ] **Step 3: Determinism — re-run and diff every published table**

```bash
cp -r output/final_no_phi /tmp/venttrace_run1
for n in 01_cohort 02_index_imv 03_method_sedative 04_method_paralytic \
         05_method_pair 06_reference_cpt 07_agreement; do
  uv run python code/$n.py > /dev/null 2>&1 || { echo "FAIL on $n"; break; }
done
for f in output/final_no_phi/*.csv; do
  b=$(basename "$f")
  if diff -q <(grep -v cohort_run_id "$f") <(grep -v cohort_run_id "/tmp/venttrace_run1/$b") > /dev/null; then
    echo "same  $b"
  else
    echo "DIFF  $b"
  fi
done
```
Expected: every line reads `same`. `cohort_run_id` is excluded because it is the run timestamp and is expected to change.

- [ ] **Step 4: PHI scan of every published artifact**

```bash
uv run python -c "
import polars as pl, glob, sys
bad = []
for f in sorted(glob.glob('output/final_no_phi/*.csv')):
    c = pl.read_csv(f).columns
    for col in c:
        if col == 'patient_id' or col.endswith('_dttm') or col == 'hospitalization_id':
            bad.append((f, col))
assert not bad, bad
print('PHI scan clean across', len(glob.glob('output/final_no_phi/*.csv')), 'CSVs')
"
```
Expected: `PHI scan clean across N CSVs`.

- [ ] **Step 5: Minimum cell size audit**

```bash
uv run python -c "
import polars as pl, glob
viol = []
for f in sorted(glob.glob('output/final_no_phi/*.csv')):
    d = pl.read_csv(f)
    for col in d.columns:
        if col.startswith('n') and d[col].dtype in (pl.Int64, pl.Int32):
            s = d[col].drop_nulls()
            b = s.filter((s >= 1) & (s <= 9))
            if b.len(): viol.append((f.split('/')[-1], col, b.to_list()))
print('cells in the 1-9 range:', viol if viol else 'none')
"
```
Expected: `none`. Any hit is a suppression bug — `apply_min_cell` was not applied to that table.

- [ ] **Step 6: Run the pytest suite**

```bash
uv run pytest tests/ -v
```
Expected: `test_clifpy_tz_boundary.py` passes.

- [ ] **Step 7: Write the verification record**

Create `docs/superpowers/plans/2026-08-06-episode-unit-rewrite-verification.md` containing the actual output of Steps 1–6, the `cohort_run_id` both runs used, and any expected-value mismatch with its explanation.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/plans/2026-08-06-episode-unit-rewrite-verification.md
git commit -m "test: full-pipeline verification of the episode rewrite

Clean run 01-07, headline counts against the spec, determinism diff over
every published CSV, PHI scan, and a minimum-cell-size audit."
```

---

## Self-Review

**Spec coverage.** D34 → Tasks 1, 3. D35 → Tasks 4–9. D36 → Task 2. D37 → Tasks 2, 3 (worked examples f/g, `no_lookback`). D38 → Task 4, plus the Tier A relabel in Task 9 and the D.4 assertion in Task 10. D39 → Task 7. §5.10 labels → Task 3. §5.11 CONSORT → Task 4. §5.12 outputs → Task 4. §5.13 → the `to_site_naive` docstring in Task 2 and the negative-delay assertion in Task 3. §6.1 key → Task 4. §6.4 rename → Tasks 5–7. §6.5 assignment → Task 7. §8 Tier A → Task 9, Tier D → Task 10, output manifest → Task 11. §10 config → already applied.

**Not covered, deliberately.** §5.13's `tests/test_clifpy_tz_boundary.py` already exists and passes; Task 12 runs it rather than rewriting it. Tier B and Tier E need no changes beyond the rekey they inherit from the `joined` frame in Task 9 — both read the ranked JSON and the pairs table, whose keys change but whose logic does not.

**Type consistency.** `intubation_episode_id` is `String` everywhere and formed only in Task 4. `ep_num` is `Int32` everywhere, formed in Task 3 and filled for rejected candidates in Task 4. `charting_delay_min` is `Float64` and nullable. `find_episode_starts(df, gap) -> DataFrame[encounter_block, recorded_dttm, sustained]` is defined once in Task 2 and used in Tasks 2 only. `unit_counts(df) -> dict` is defined in Task 9 and used in Task 10. `detected_expr(method, basis)` is pre-existing in `07` and unchanged. `_rates(df, group_col, label_col)` is defined in Task 10 Step 2 and reused in Steps 3 and 4 — it is returned from that cell so the later cells can take it as an argument.

**Known gap, flagged not fixed.** Task 3's `no_lookback` count (Step 7) is over the *sustained* set and will not match the spec's 7,130, which is over the *qualified* set produced in Task 4. The step says so explicitly rather than setting an expectation that will look like a failure.
