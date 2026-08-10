# Paralytic-Indexed Airway Analysis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five-signal method-comparison pipeline with a two-notebook study anchored on the index paralytic, implementing the five sub-analyses of `docs/superpowers/specs/2026-08-10-paralytic-index-design.md`.

**Architecture:** `01_cohort.py` is untouched. `02_index_paralytic.py` reads `medication_admin_intermittent` and nothing else, publishes the co-administration gap distribution (A), folds administrations into index paralytics at 15 minutes (B), publishes the inter-index gap distribution (C), and writes `index_paralytic.parquet`. `03_context.py` reads that artifact plus the waterfalled device timeline and a second medication list, and publishes the IMV-transition (D) and sedation (E) sub-analyses. The six superseded notebooks are deleted last, so the repo never sits in a state where `run_all.sh` names a file that does not exist.

**Tech Stack:** Python ≥3.14, polars, marimo (notebooks stored as `.py`, run as `uv run python code/NN_name.py`), clifpy ≥0.5.0 for CLIF table loading, matplotlib for figures, pytest for tests.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec.

- **Timezone always from `config["timezone"]`.** No code path may consult the OS zone. Never call `.timestamp()` on a datetime. All minute arithmetic goes through `epoch_minutes()`, defined as `pl.col(column).dt.epoch("s") / 60.0`. (Spec P19)
- **`to_site_naive` is defined locally in each notebook**, never imported: `series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)`. `utils/suppress.py` is the only shared code in the project. (Spec P23, §4)
- **Every `*_category` column is lower-cased immediately after load**, and every literal in the codebase is written in lower case. Load-time `from_file` filters enumerate every casing variant. (Spec P20)
- **`PARALYTICS = ["rocuronium", "succinylcholine", "vecuronium"]`** (Spec P3)
- **`SEDATIVES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]`** (Spec P16)
- **`MAR_ACTIONS = ["given", "bolus"]`** (Spec P4)
- **`MIN_CELL = 10`.** Published counts of 1..9 are suppressed by dropping the whole row; a count of exactly 0 is published. (Spec P21)
- **`med_dose` and `med_dose_unit` are never converted.** Dose statistics are keyed on `(med_category, med_dose_unit)`. (Spec P18)
- **One logical step per marimo cell**, with a markdown cell above it stating what the step does in plain language. Every filter prints its row, encounter-block and index-event count before and after. (Spec §4)
- **No silent defaults.** Every parameter that affects a result is read from `config.json` and echoed at the top of the notebook.
- **Commit messages carry no Claude attribution.** No `Co-Authored-By` trailer — the history is part of the study record.
- Run tests with `uv run pytest tests/ -v`. Run a notebook with `uv run python code/NN_name.py` from the repo root.

## File Structure

| File | Responsibility |
|---|---|
| `utils/suppress.py` | **New.** The n ≥ 10 rule and the `publish()` wrapper. The only shared module. |
| `code/02_index_paralytic.py` | **New.** Sub-analyses A, B, C. Reads `medication_admin_intermittent` only. Writes `index_paralytic.parquet`. |
| `code/03_context.py` | **New.** Sub-analyses D, E. Reads `index_paralytic.parquet`, `cohort_resp_waterfall.parquet`, `medication_admin_intermittent`. Writes `index_context.parquet`. |
| `tests/test_min_cell_suppression.py` | **New**, replaces `tests/test_e7_suppression.py`. |
| `tests/test_pair_gaps.py` | **New.** All-pairs enumeration and the gap bin grid. |
| `tests/test_imv_transition.py` | **New.** The four transition cases and the three no-transition reasons. |
| `tests/test_collapse_agent_events.py` | **Retargeted** from `05_method_pair.py` to `02_index_paralytic.py`. |
| `tests/test_clifpy_tz_boundary.py` | **Unchanged.** |
| `code/01_cohort.py` | **Unchanged.** |
| `config/config_template.json`, `config/config.json` | Key-for-key rewrite per spec §9. |
| `run_all.sh`, `docs/pipeline_flow.md` | Rewritten. |
| `code/02_index_imv.py`, `03_method_sedative.py`, `04_method_paralytic.py`, `05_method_pair.py`, `06_reference_cpt.py`, `07_agreement.py` | **Deleted, in Task 7.** |

## Inputs this pipeline consumes from `01_cohort.py`

Both are already produced and neither changes. Do not re-derive them.

```
output/intermediate_phi/cohort_index.parquet
    encounter_block          int
    patient_id               str
    cohort_run_id            str
    list_hospitalization_id  list[str]
    n_hospitalizations       int
    admission_dttm           datetime (site-naive)
    age_at_admission         float

output/intermediate_phi/cohort_resp_waterfall.parquet
    hospitalization_id  str
    recorded_dttm       datetime (site-naive)
    device_category     str, lower-cased
    encounter_block     int
    -- sorted by (encounter_block, recorded_dttm)
```

---

### Task 1: `utils/suppress.py` — the one shared helper

**Files:**
- Create: `utils/suppress.py`
- Create: `tests/test_min_cell_suppression.py`
- Delete: `tests/test_e7_suppression.py`

**Interfaces:**
- Consumes: nothing.
- Produces, used by Tasks 3, 4, 5, 6:
  - `MIN_CELL: int = 10`
  - `small_cell_mask(df: pl.DataFrame, count_cols: list[str], min_cell: int = MIN_CELL) -> pl.Series` — boolean, True where the row must be dropped
  - `apply_min_cell(df, count_cols, label, min_cell=MIN_CELL) -> tuple[pl.DataFrame, pl.DataFrame]` — `(kept, dropped)`
  - `publish(df, path, count_cols, label, min_cell=MIN_CELL) -> pl.DataFrame` — suppresses, writes CSV to `path`, prints what was dropped, returns the kept frame

- [ ] **Step 1: Write the failing test**

Create `tests/test_min_cell_suppression.py`:

```python
"""Pins the n >= 10 suppression rule (spec P21, §8).

This is the only shared module in the project and the reason it is shared is
recorded in P23: duplicating *analysis* logic risks correlated errors that look
like agreement, which no longer matters here; duplicating *suppression* logic
risks one notebook publishing a cell the other would have withheld, which is a
disclosure failure and has to be impossible rather than merely unlikely.

The rule, stated once: a published count of 1..9 is suppressed, suppression
drops the WHOLE ROW rather than blanking a cell, and a count of exactly zero is
published -- "this never happened" and "this is missing" are different
statements and a multi-site table may not confuse them.

Run:  uv run pytest tests/test_min_cell_suppression.py -v
"""

import polars as pl
import pytest

from utils.suppress import MIN_CELL, apply_min_cell, publish, small_cell_mask


def _frame(counts):
    return pl.DataFrame({"bin": [f"b{i}" for i in range(len(counts))], "n": counts})


def test_min_cell_is_ten():
    assert MIN_CELL == 10


@pytest.mark.parametrize(
    ("n", "dropped"),
    [(0, False), (1, True), (9, True), (10, False), (11, False), (1000, False)],
)
def test_boundary(n, dropped):
    """Zero is published; 1..9 are not; 10 is the first publishable positive count."""
    kept, gone = apply_min_cell(_frame([n]), ["n"], "t")
    assert (gone.height == 1) is dropped
    assert (kept.height == 1) is not dropped


def test_any_count_column_triggers():
    """A row is dropped if ANY of its published counts is disclosive."""
    df = pl.DataFrame({"bin": ["a", "b"], "n_x": [50, 50], "n_y": [50, 3]})
    kept, gone = apply_min_cell(df, ["n_x", "n_y"], "t")
    assert kept.get_column("bin").to_list() == ["a"]
    assert gone.get_column("bin").to_list() == ["b"]


def test_whole_row_is_dropped_not_blanked():
    """A blanked cell in a table whose margins are published is recoverable by
    subtraction, so the row goes entirely."""
    df = pl.DataFrame({"bin": ["a"], "n_x": [500], "n_y": [4]})
    kept, _ = apply_min_cell(df, ["n_x", "n_y"], "t")
    assert kept.height == 0


def test_fully_suppressed_frame_is_empty_not_an_error():
    """Every cell disclosive must yield an empty frame with the schema intact --
    downstream figure code reads this frame and must degrade, not raise."""
    kept, gone = apply_min_cell(_frame([1, 2, 3]), ["n"], "t")
    assert kept.height == 0
    assert kept.columns == ["bin", "n"]
    assert gone.height == 3


def test_mask_is_a_plain_boolean_series():
    mask = small_cell_mask(_frame([0, 5, 10]), ["n"])
    assert mask.to_list() == [False, True, False]


def test_publish_writes_only_the_kept_rows(tmp_path):
    path = tmp_path / "out.csv"
    kept = publish(_frame([50, 3, 12]), path, ["n"], "t")
    written = pl.read_csv(path)
    assert kept.height == 2
    assert written.get_column("n").to_list() == [50, 12]


def test_publish_reports_what_it_dropped(tmp_path, capsys):
    """Never silent: a suppressed row must be visible in the run log."""
    publish(_frame([50, 3]), tmp_path / "out.csv", ["n"], "gap_distribution")
    out = capsys.readouterr().out
    assert "gap_distribution" in out
    assert "1 row" in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_min_cell_suppression.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.suppress'`

- [ ] **Step 3: Write the implementation**

Create `utils/suppress.py`:

```python
"""The n >= 10 minimum cell rule, applied to everything written to final_no_phi.

The ONLY shared module in this project. Spec P23 records why this one is shared
when nothing else is: a suppression bug is a disclosure failure, not an analysis
failure, and it has to be impossible rather than merely unlikely.

The rule (spec §8):
  * a published count of 1..9 is suppressed
  * suppression drops the WHOLE ROW, not the cell -- a blanked cell in a table
    whose margins are published is often recoverable by subtraction
  * a count of exactly ZERO is published -- it identifies nobody, and dropping it
    would turn "this never happened" into "this is missing"
  * nothing is ever silent: what was dropped is printed
"""

import polars as pl

MIN_CELL = 10


def small_cell_mask(df, count_cols, min_cell=MIN_CELL):
    """True for rows that must not be published."""
    for col in count_cols:
        assert col in df.columns, f"count column {col!r} is not in the frame"
    mask = pl.lit(False)
    for col in count_cols:
        mask = mask | ((pl.col(col) > 0) & (pl.col(col) < min_cell))
    return df.select(mask.alias("_m")).get_column("_m")


def apply_min_cell(df, count_cols, label, min_cell=MIN_CELL):
    """Split a frame into (publishable, suppressed). Neither is written here."""
    mask = small_cell_mask(df, count_cols, min_cell)
    return df.filter(~mask), df.filter(mask)


def publish(df, path, count_cols, label, min_cell=MIN_CELL):
    """Suppress, write the survivors to `path` as CSV, report the loss, return them.

    Every write to final_no_phi goes through this function. Writing a CSV to that
    directory by any other route is a bug.
    """
    kept, dropped = apply_min_cell(df, count_cols, label, min_cell)
    if dropped.height:
        total = sum(dropped.get_column(c).sum() for c in count_cols)
        print(
            f"  [{label}] {dropped.height} row(s) suppressed under the n>={min_cell} "
            f"rule on {count_cols}; {total} observation(s) withheld"
        )
        print(dropped)
    kept.write_csv(path)
    print(f"  [{label}] {kept.height} row(s) -> {path}")
    return kept
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_min_cell_suppression.py -v`
Expected: PASS, 12 tests

If the import fails with `ModuleNotFoundError: No module named 'utils'`, add to `pyproject.toml` under a new `[tool.pytest.ini_options]` section:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

Then re-run.

- [ ] **Step 5: Delete the superseded suppression test**

`tests/test_e7_suppression.py` pins Tier E.7 of `07_agreement.py`, which Task 7 deletes. Its rule survives in `utils/suppress.py` and is now covered above.

```bash
git rm tests/test_e7_suppression.py
```

- [ ] **Step 6: Confirm the rest of the suite still passes**

Run: `uv run pytest tests/ -v`
Expected: PASS — `test_clifpy_tz_boundary.py`, `test_collapse_agent_events.py`, `test_min_cell_suppression.py`

- [ ] **Step 7: Commit**

```bash
git add utils/suppress.py tests/test_min_cell_suppression.py pyproject.toml
git commit -m "feat(utils): the n>=10 suppression rule as the project's one shared module

Spec P23. Duplicating analysis logic risks correlated errors that look like
agreement -- the hazard the superseded design was built around, and which no
longer exists with one method. Duplicating suppression logic risks one notebook
publishing a cell the other would have withheld, which is a disclosure failure
and must be impossible rather than unlikely.

publish() is the only sanctioned route to final_no_phi, so suppression cannot
be forgotten at a call site. Replaces tests/test_e7_suppression.py, whose
subject (Tier E.7 of 07_agreement) is deleted with the rest of that notebook."
```

---

### Task 2: `02_index_paralytic.py` — the administration set and the index fold

**Files:**
- Create: `code/02_index_paralytic.py`
- Modify: `tests/test_collapse_agent_events.py:1-55` (retarget the notebook path and docstring)

**Interfaces:**
- Consumes: `output/intermediate_phi/cohort_index.parquet` (schema above).
- Produces, used by Tasks 3, 4, 5, 6:
  - Notebook-level functions, extracted by AST in tests:
    - `epoch_minutes(column="admin_dttm") -> pl.Expr`
    - `collapse_agent_events(times: list[float], categories: list[str], gap_limit_min: float) -> list[list[int]]`
  - Notebook-level frames: `med_admin` (the §6.2 administration set), `index_paralytic`
  - Artifact `output/intermediate_phi/index_paralytic.parquet`, schema in Step 8.

- [ ] **Step 1: Create the notebook header and config cell**

Create `code/02_index_paralytic.py`:

```python
import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import polars as pl

    from clifpy.tables import MedicationAdminIntermittent

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        MedicationAdminIntermittent,
        Path,
        json,
        mo,
        pl,
        publish,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 02 — the index paralytic

        ```
        rocuronium | succinylcholine | vecuronium
        ```

        The paralytic is the study's index event. This notebook does three things and
        touches exactly one CLIF table while doing them:

        | | |
        |---|---|
        | **A** | the distribution of gaps between paralytic administrations |
        | **B** | the 15-minute fold that turns administrations into **index paralytics** |
        | **C** | the distribution of gaps between index paralytics |

        A is published **before** B and depends on nothing B computes, so it reads as
        evidence for the 15-minute boundary rather than as a consequence of it. Fifteen
        minutes is a clinical definition and no empirical valley supports it — see spec P7,
        and read Figure A.1 rather than taking the number on trust.

        Design: `docs/superpowers/specs/2026-08-10-paralytic-index-design.md` §6, §7.1–7.3
        """
    )
    return


@app.cell
def _(Path, json):
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
    FIG_DIR = SHARE_DIR / "figures"
    PHI_DIR.mkdir(parents=True, exist_ok=True)
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # P3. Lower case to match the lower-cased column (P20).
    PARALYTICS = ["rocuronium", "succinylcholine", "vecuronium"]
    # P4. 'bolus' is how many EHRs chart a one-time IV push, which is exactly what an
    # intubating paralytic is. Keeping 'given' alone risks a site reporting zero
    # paralytics, and zero is indistinguishable from a site that gives none.
    MAR_ACTIONS = ["given", "bolus"]

    COLLAPSE_GAP_MINUTES = config["collapse_gap_minutes"]

    # P11. An ANALYSIS grid, not a site parameter -- a site that changed its bins would
    # make its histogram non-comparable with every other site's, which is the one thing a
    # multi-site distribution is for. Constants here, deliberately not config keys.
    #
    # 13 breaks -> 14 cut bins; the exact-zero bin is carved out of the first, giving 15.
    # An exact zero gets its own bin because two agents charted on the same minute is the
    # single most informative value in the distribution and must not be pooled with
    # "under a minute".
    GAP_CUT_BREAKS = [1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 4320, 10080]
    GAP_CUT_LABELS = [
        "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]", "(15,30]", "(30,60]",
        "(1,2]h", "(2,6]h", "(6,12]h", "(12,24]h", "(1,3]d", "(3,7]d", ">7d",
    ]
    GAP_BIN_LABELS = ["0"] + GAP_CUT_LABELS

    # P9/P10 memory ceiling, NOT a clinical parameter. Ten million pairs of two floats and
    # two labels is roughly a 300 MB polars frame, about three orders of magnitude above
    # what MIMIC's paralytic density implies. A site that trips this has charting unlike
    # anything this design was checked against; the right response is to read the densest
    # blocks printed alongside and decide deliberately, not to raise the constant.
    MAX_TOTAL_PAIRS = 10_000_000

    print(f"site           : {SITE}")
    print(f"paralytics     : {' | '.join(PARALYTICS)}")
    print(f"mar actions    : {' | '.join(MAR_ACTIONS)}")
    print(f"collapse gap   : {COLLAPSE_GAP_MINUTES} min   (P6, P7)")
    print(f"gap bins       : {len(GAP_BIN_LABELS)}  {GAP_BIN_LABELS}")
    print(f"max pairs      : {MAX_TOTAL_PAIRS:,}")
    return (
        COLLAPSE_GAP_MINUTES,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        GAP_CUT_BREAKS,
        GAP_CUT_LABELS,
        GAP_BIN_LABELS,
        MAR_ACTIONS,
        MAX_TOTAL_PAIRS,
        PARALYTICS,
        PHI_DIR,
        SHARE_DIR,
        TIMEZONE,
    )
```

- [ ] **Step 2: Add the two timestamp helpers and the stale-artifact guard**

Append to `code/02_index_paralytic.py`:

```python
@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. `tz_convert` re-resolves against
        the tz database first. Pinned by `tests/test_clifpy_tz_boundary.py`.

        Defined locally, never imported (spec §4): a bug in a shared datetime helper
        corrupts every consumer identically, and identical corruption is the hardest kind
        to see.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def epoch_minutes(column="admin_dttm"):
        """Minutes since epoch, computed INSIDE polars, consulting no timezone at all.

        `datetime.timestamp()` on a site-naive value re-attaches the *machine's* zone. On
        a host set to US/Central holding US/Eastern data, ten minutes of wall clock across
        the November fall-back measures as seventy -- and seventy against a fifteen-minute
        fold splits one push of drug into two index paralytics, moving `t` for everything
        downstream. The answer would then depend on the laptop. Spec P19; pinned by
        `tests/test_collapse_agent_events.py`.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    return (epoch_minutes,)


@app.cell
def _(PHI_DIR):
    # A stale artifact from the superseded design still loads, still joins, and supplies
    # the wrong denominator without raising. Spec §12.
    _stale = [
        "index_imv.parquet",
        "method_SED_episode.parquet",
        "method_PARA_episode.parquet",
        "method_SED_ranked.json",
        "method_PARA_ranked.json",
        "method_PAIR_pairs.parquet",
    ]
    _present = [_n for _n in _stale if (PHI_DIR / _n).exists()]
    assert not _present, (
        f"artifacts from the superseded method-comparison design are present in "
        f"{PHI_DIR}: {_present}. Delete them -- they describe an IMV-anchored study and "
        "nothing in this pipeline should be able to read them."
    )
    print("no stale pre-overhaul artifacts present")
    return
```

- [ ] **Step 3: Add the explode-and-drop bridge and the administration set**

Append to `code/02_index_paralytic.py`:

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## The explode-and-drop bridge

        CLIF tables are keyed on `hospitalization_id`; this study is keyed on
        `encounter_block`. The bridge below is the **only** place this notebook may name a
        hospitalization, and the column is dropped the moment the join lands.

        That drop is a requirement, not tidiness (P5). If `hospitalization_id` survived
        into the gap computation, sub-analysis A would silently revert to the unstitched
        unit and a paralytic charted in the ED would never pair with one charted on the
        floor. Dropping the column makes that mistake impossible to write rather than
        merely discouraged.
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

    COHORT_RUN_ID = cohort_index.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"cohort_index carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    bridge = (
        cohort_index.select(["encounter_block", "patient_id", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # The map must be many-to-one: one hospitalization belongs to exactly one block.
    # Asserted rather than assumed -- a duplicated key here fans out every administration
    # on the join below, and the fan-out is self-consistent, so every downstream count
    # would still agree with itself while being wrong.
    assert bridge.get_column("hospitalization_id").is_unique().all(), (
        "a hospitalization_id appears in more than one encounter_block"
    )

    print(f"cohort_run_id      : {COHORT_RUN_ID}")
    print(f"encounter blocks   : {cohort_index.height:,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return COHORT_RUN_ID, bridge, bridge_hosp_ids, cohort_index


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    MAR_ACTIONS,
    MedicationAdminIntermittent,
    PARALYTICS,
    TIMEZONE,
    bridge,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    # Filtered on hospitalization_id at load, but deliberately NOT on med_category. The
    # list is three values; filtering after lower-casing is both cheaper to reason about
    # and immune to the casing hole P20 exists to patch, since our own filter then runs on
    # a column we normalised ourselves.
    _med = MedicationAdminIntermittent.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "admin_dttm",
            "med_category",
            "mar_action_category",
            "med_dose",
            "med_dose_unit",
        ],
        filters={"hospitalization_id": bridge_hosp_ids},
    )

    med_all = pl.from_pandas(
        _med.df.assign(admin_dttm=lambda d: to_site_naive(d["admin_dttm"]))
    ).with_columns(
        med_category=pl.col("med_category").str.to_lowercase(),
        mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
    )

    med_admin = (
        med_all.filter(
            pl.col("med_category").is_in(PARALYTICS)
            & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # the bridge ends here -- everything below is per block
    )

    assert "hospitalization_id" not in med_admin.columns, "the bridge leaked its key"

    # A category filter that matches nothing looks exactly like a site where the drug is
    # never given. Print what was actually found so the two are distinguishable, and fail
    # only if the whole list came back empty -- an individual agent may genuinely be absent
    # from a formulary; succinylcholine often is.
    _found = med_admin.group_by(["med_category", "mar_action_category"]).agg(n=pl.len())
    _missing = sorted(set(PARALYTICS) - set(med_admin.get_column("med_category").unique()))

    print(f"intermittent rows loaded : {med_all.height:,}")
    print(f"paralytic administrations: {med_admin.height:,}")
    print(f"  over encounter blocks  : {med_admin.get_column('encounter_block').n_unique():,}")
    print(f"  over patients          : {med_admin.get_column('patient_id').n_unique():,}")
    print(_found.sort("n", descending=True))
    if _missing:
        print(f"\nNOT PRESENT AT THIS SITE: {', '.join(_missing)}")
        print("  -> not an error, but every distribution below is computed without them")

    assert med_admin.height > 0, (
        "no administration matched the paralytic list at all. Either the site charts none "
        "of these agents, or the vocabulary differs -- compare the value_counts printed "
        "above against the mCIDE med_category list before trusting a zero."
    )
    return med_admin, med_all
```

- [ ] **Step 4: Add `collapse_agent_events`, lifted verbatim from the superseded `05`**

The function is already correct and already has a full test suite. Copy it exactly — do not
rewrite it, do not rename it, and do not "simplify" `epoch_minutes` into `.timestamp()`.

Append to `code/02_index_paralytic.py`:

```python
@app.cell
def _(mo):
    mo.md(
        r"""
        ## B — the fold: anchor and close at 15 minutes

        ```
        first unconsumed row            ->  ANCHOR.  t := its admin_dttm
        every row within 15 min OF THE ANCHOR   ->  joins this index event
        first row beyond that           ->  new ANCHOR
        ```

        **Anchored, never chained (P6).** Chaining has no bound: an agent redosed every
        fourteen minutes walks one event forward indefinitely, and its timestamp then sits
        hours from most of its own doses — which destroys the clock sub-analyses C, D and E
        all measure against. Anchoring makes `span_minutes <= 15` an *assertable
        invariant* rather than a hope.

        Worked example:

        ```
         12:00  rocuronium        ANCHOR      index #1, t = 12:00
         12:10  vecuronium        <= 12:15    joins #1
         12:20  succinylcholine   >  12:15    ANCHOR   index #2, t = 12:20
         12:32  rocuronium        <= 12:35    joins #2
        ```

        The 12:20 row is within 15 minutes of the 12:10 row, and a transitive rule would
        have merged all four into one event spanning 32 minutes. Under P6 it does not.
        """
    )
    return


@app.cell
def _(COLLAPSE_GAP_MINUTES):
    def collapse_agent_events(times, categories, gap_limit_min):
        """Fold administrations into index events. Returns [[i, ...], ...] in time order.

        `times` is minutes-since-epoch as floats, ascending, all from one encounter. The
        invariant is that **no event spans more than `gap_limit_min`**: a row joins the
        current event only while it is within the limit of that event's FIRST row, and the
        moment it is strictly past it the row opens a new event and becomes the new anchor.
        Anchored, never chained -- the comparison is against `times[event[0]]` and never
        against `times[i - 1]`, so a steady drip of closely-spaced doses cannot walk an
        event forward without bound.

        Strictly greater, not greater-or-equal: a row exactly `gap_limit_min` past the
        anchor still merges, so the parameter reads as "within 15 minutes" inclusively.

        `categories` takes no part in the decision and is only length-checked. That is the
        point rather than an oversight: a repeat of one agent and a co-administration of
        two are the same clinical fact -- one push of paralytic -- and must fold the same
        way. Which agents were involved is recorded on the event afterwards by the caller,
        as `agent_label`.
        """
        n = len(times)
        assert len(categories) == n, "times and categories are not the same length"
        if n == 0:
            return []
        events = []
        current = [0]
        for i in range(1, n):
            if times[i] - times[current[0]] > gap_limit_min:
                events.append(current)
                current = [i]
            else:
                current.append(i)
        events.append(current)
        return events

    print(f"collapse window: {COLLAPSE_GAP_MINUTES:.0f} min")
    return (collapse_agent_events,)
```

- [ ] **Step 5: Retarget the existing fold test onto the new notebook**

Modify `tests/test_collapse_agent_events.py`. Change only the docstring and the `NOTEBOOK`
constant — every test body below them is already correct for the new notebook, because the
function is byte-identical.

Replace lines 1–34 (the module docstring through the `NOTEBOOK = ...` assignment) with:

```python
"""Pins the index-paralytic fold in `code/02_index_paralytic.py` (spec P6, P19).

`collapse_agent_events` is what turns paralytic administrations into index
paralytics, and the index paralytic's first administration is `t` -- the clock
that sub-analyses C, D and E all measure against. A fold bug therefore does not
produce a slightly wrong count; it moves the study's origin.

The one property worth a test of its own is that the window is **anchored on the
event's first row, not chained off the previous one**. Chained, an agent redosed
every ten minutes would grow into one event spanning the whole stay, and its `t`
would sit hours from most of its own doses. Anchored, every event is bounded by
the gap end to end. Case (d) below is the case that tells the two apart, and it
is the only one a chained implementation fails.

This file previously pinned the same function in the deleted `05_method_pair.py`,
where it folded sedatives and paralytics separately before a pairing scan. The
function moved without changing; only its consumer did.

The function is lifted out of the notebook by AST rather than imported:
`02_index_paralytic` is a marimo notebook whose module name is not a Python
identifier, and importing it would run the whole pipeline against real PHI.

Run:  uv run pytest tests/test_collapse_agent_events.py -v
"""

import ast
import datetime
import os
import time
from pathlib import Path

import polars as pl
import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "02_index_paralytic.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())
```

In `test_grouping_ignores_categories`, change the category lists from sedatives to
paralytics so the test reads against this notebook's drug list — the assertion is unchanged
because the fold ignores categories, which is the point:

```python
def test_grouping_ignores_categories():
    """A repeat of one agent and a co-administration of two fold identically.

    Which agents were involved is recorded by the caller in `agent_label`; it must play no
    part in the fold, or a co-administration would become two index paralytics and the
    study would count one intubation twice.
    """
    times = [0, 2, 40]
    same = _call(times, categories=["rocuronium", "rocuronium", "rocuronium"])
    mixed = _call(times, categories=["rocuronium", "vecuronium", "succinylcholine"])
    assert same == mixed == [[0, 1], [2]]
```

And in `test_collapse_merges_across_a_dst_fall_back`, change the two category literals from
`["fentanyl", "rocuronium"]` to `["rocuronium", "vecuronium"]` in both calls.

- [ ] **Step 6: Run the retargeted test to verify it passes**

Run: `uv run pytest tests/test_collapse_agent_events.py -v`
Expected: PASS — all cases including `test_notebook_calls_no_naive_timestamp`, which now
walks `02_index_paralytic.py`.

If `test_notebook_calls_no_naive_timestamp` fails, you have a `.timestamp()` call in the
new notebook. Replace it with `epoch_minutes()`. Do not add an exemption.

- [ ] **Step 7: Add the fold driver and build `index_paralytic`**

Append to `code/02_index_paralytic.py`:

```python
@app.cell
def _(COLLAPSE_GAP_MINUTES, collapse_agent_events, epoch_minutes, med_admin, pl):
    # Sorted by (admin_dttm, med_category): med_category breaks an exact-timestamp tie
    # alphabetically, so the fold -- and therefore every offset downstream -- is
    # byte-identical across runs.
    _sorted = med_admin.sort(["encounter_block", "admin_dttm", "med_category"]).with_columns(
        _t_min=epoch_minutes("admin_dttm")
    )

    _grouped = _sorted.group_by("encounter_block", maintain_order=True).agg(
        pl.col("_t_min"), pl.col("med_category"), _row=pl.int_range(pl.len())
    )

    _rows = []
    for _block, _times, _cats, _ in _grouped.iter_rows():
        for _n, _event in enumerate(
            collapse_agent_events(_times, _cats, COLLAPSE_GAP_MINUTES), start=1
        ):
            _rows.append(
                {
                    "encounter_block": _block,
                    "p_num": _n,
                    "_first_pos": _event[0],
                    "_last_pos": _event[-1],
                    "n_admins": len(_event),
                }
            )

    # A row index within the block lets the fold's positional output be joined back to the
    # administration rows without a second sort. The sort key above is the only ordering
    # this notebook ever uses.
    _positioned = _sorted.with_columns(_pos=pl.int_range(pl.len()).over("encounter_block"))

    fold = pl.DataFrame(_rows).with_columns(
        index_paralytic_id=pl.concat_str(
            pl.col("encounter_block").cast(pl.String), pl.lit("_P"), pl.col("p_num").cast(pl.String)
        )
    )

    # Every administration belongs to exactly ONE index event: the index set is a partition
    # of the administration set, not a filter on it.
    assert fold.get_column("n_admins").sum() == med_admin.height, (
        f"the fold accounts for {fold.get_column('n_admins').sum():,} administrations but "
        f"{med_admin.height:,} were loaded -- the partition property is broken"
    )

    print(f"index paralytics : {fold.height:,}")
    print(f"  over blocks    : {fold.get_column('encounter_block').n_unique():,}")
    return fold, _positioned


@app.cell
def _(COHORT_RUN_ID, COLLAPSE_GAP_MINUTES, _positioned, cohort_index, fold, pl):
    # Attach every administration to its index event, then aggregate.
    _members = (
        _positioned.join(
            fold.select("encounter_block", "index_paralytic_id", "p_num", "_first_pos", "_last_pos"),
            on="encounter_block",
            how="inner",
        )
        .filter(
            (pl.col("_pos") >= pl.col("_first_pos")) & (pl.col("_pos") <= pl.col("_last_pos"))
        )
    )

    _anchor = _members.filter(pl.col("_pos") == pl.col("_first_pos")).select(
        "index_paralytic_id", t_dttm="admin_dttm", _t0_min="_t_min"
    )

    index_paralytic = (
        _members.join(_anchor, on="index_paralytic_id", how="inner")
        .with_columns(offset_minutes=(pl.col("_t_min") - pl.col("_t0_min")).round(3))
        .group_by(["encounter_block", "index_paralytic_id", "p_num", "t_dttm"], maintain_order=True)
        .agg(
            n_admins=pl.len(),
            span_minutes=(pl.col("_t_min").max() - pl.col("_t_min").min()).round(3),
            agents=pl.col("med_category").unique().sort(),
            doses=pl.struct(
                med_category="med_category",
                med_dose="med_dose",
                med_dose_unit="med_dose_unit",
                mar_action_category="mar_action_category",
                offset_minutes="offset_minutes",
            ),
        )
        .with_columns(
            n_agents=pl.col("agents").list.len().cast(pl.Int32),
            is_coadmin=pl.col("n_admins") > 1,
            agent_label=pl.col("agents").list.join("+"),
            cohort_run_id=pl.lit(COHORT_RUN_ID),
        )
        .join(cohort_index.select("encounter_block", "patient_id"), on="encounter_block", how="left")
        .select(
            "index_paralytic_id",
            "encounter_block",
            "patient_id",
            "cohort_run_id",
            "p_num",
            "t_dttm",
            "n_admins",
            "span_minutes",
            "is_coadmin",
            "agents",
            "n_agents",
            "agent_label",
            "doses",
        )
        .sort(["encounter_block", "p_num"])
    )

    # P6's invariant, asserted rather than hoped for. A violation means the fold chained.
    _over = index_paralytic.filter(pl.col("span_minutes") > COLLAPSE_GAP_MINUTES)
    assert _over.height == 0, (
        f"{_over.height:,} index paralytics span more than {COLLAPSE_GAP_MINUTES} min. "
        "collapse_agent_events anchors on the event's first row; a violation here means it "
        "chained off the previous row instead."
    )
    assert index_paralytic.get_column("index_paralytic_id").is_unique().all()
    assert index_paralytic.get_column("patient_id").null_count() == 0, (
        "an index paralytic has no patient -- a block in med_admin is absent from cohort_index"
    )
    _gap = index_paralytic.filter(
        pl.col("p_num") != pl.col("p_num").cum_count().over("encounter_block")
    )
    assert _gap.height == 0, "p_num is not contiguous from 1 within a block"

    print(f"index paralytics : {index_paralytic.height:,}")
    print(f"  co-administrations : {index_paralytic.get_column('is_coadmin').sum():,} "
          f"({100 * index_paralytic.get_column('is_coadmin').mean():.1f}%)")
    print(f"  max span (min)     : {index_paralytic.get_column('span_minutes').max()}")
    print(index_paralytic.group_by("agent_label").agg(n=pl.len()).sort("n", descending=True))
    return (index_paralytic,)
```

- [ ] **Step 8: Write the artifact**

Append to `code/02_index_paralytic.py`:

```python
@app.cell
def _(PHI_DIR, index_paralytic):
    _path = PHI_DIR / "index_paralytic.parquet"
    index_paralytic.write_parquet(_path)
    print(f"index_paralytic.parquet   {index_paralytic.height:,} rows -> {_path}")
    return


if __name__ == "__main__":
    app.run()
```

Resulting schema, which Tasks 5 and 6 consume:

```
index_paralytic_id  str      {encounter_block}_P{n}
encounter_block     int
patient_id          str
cohort_run_id       str
p_num               int      1 = first index paralytic of the block
t_dttm              datetime the study clock (P8)
n_admins            int
span_minutes        float    asserted <= collapse_gap_minutes
is_coadmin          bool
agents              list[str]  sorted distinct med_category
n_agents            int
agent_label         str      agents joined with "+"
doses               list[struct{med_category, med_dose, med_dose_unit,
                               mar_action_category, offset_minutes}]
```

- [ ] **Step 9: Run the notebook end to end**

Run: `uv run python code/02_index_paralytic.py`
Expected: completes without assertion failure and prints the index paralytic count.

If the stale-artifact assertion fires, the previous design's outputs are still on disk.
That is the assertion working. Move them aside:
`mkdir -p output/_pre_overhaul && mv output/intermediate_phi/index_imv.parquet output/intermediate_phi/method_* output/_pre_overhaul/`

- [ ] **Step 10: Commit**

```bash
git add code/02_index_paralytic.py tests/test_collapse_agent_events.py
git commit -m "feat(02): the index paralytic -- administration set and the 15-minute fold

Spec §6. Paralytic administrations within 15 minutes of an anchor fold into one
index paralytic; its first administration is t, the clock everything downstream
measures against.

Anchored, never chained (P6). A transitive rule would let an agent redosed every
fourteen minutes walk one event forward indefinitely, putting t hours away from
most of its own doses. Anchoring makes span_minutes <= 15 assertable, and it is
asserted.

collapse_agent_events and epoch_minutes are lifted verbatim from the superseded
05_method_pair.py -- same rule, different consumer -- so
tests/test_collapse_agent_events.py is retargeted rather than rewritten, and the
DST fall-back regression it pins carries over intact.

The index set is a partition of the administration set, not a filter on it:
sum(n_admins) == the loaded row count, asserted."
```

---

### Task 3: Sub-analysis A — the co-administration gap distribution

**Files:**
- Modify: `code/02_index_paralytic.py` (insert cells between the administration-set cell and the fold markdown cell, so A is computed before B)
- Create: `tests/test_pair_gaps.py`

**Interfaces:**
- Consumes from Task 2: `med_admin`, `epoch_minutes`, `GAP_CUT_BREAKS`, `GAP_CUT_LABELS`, `GAP_BIN_LABELS`, `MAX_TOTAL_PAIRS`, `publish`, `SHARE_DIR`.
- Produces, used by Task 4:
  - `gap_bin_expr(col: str = "gap_minutes") -> pl.Expr` — aliased `gap_bin`
  - `all_pair_gaps(df: pl.DataFrame, time_col: str, agent_col: str | None) -> pl.DataFrame` with columns `encounter_block`, `gap_minutes`, `agent_pair`, `is_same_agent`
  - CSVs `paralytic_admin_summary.csv`, `coadmin_gap_distribution.csv`, `coadmin_gap_by_pair.csv`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pair_gaps.py`:

```python
"""Pins the all-pairs enumeration and the gap bin grid of `02_index_paralytic.py`.

Sub-analysis A is the evidence for the 15-minute boundary (spec P7), so it is
published BEFORE the fold applies that boundary and depends on nothing the fold
computes. Two things can go wrong and neither announces itself:

  * the enumeration silently crossing an encounter_block boundary, which would
    manufacture gaps between different patients' drugs;
  * a bin edge landing on the wrong side, which moves mass across the very line
    the threshold is drawn at.

Both are checked below. The functions are lifted out of the marimo notebook by
AST, the way `tests/test_collapse_agent_events.py` does it: `02_index_paralytic`
is not an importable module name and importing it would run the pipeline against
real PHI.

Run:  uv run pytest tests/test_pair_gaps.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl
import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "02_index_paralytic.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())

GAP_CUT_BREAKS = [1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 4320, 10080]
GAP_CUT_LABELS = [
    "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]", "(15,30]", "(30,60]",
    "(1,2]h", "(2,6]h", "(6,12]h", "(12,24]h", "(1,3]d", "(3,7]d", ">7d",
]


def _load_from_notebook(name, namespace=None):
    found = [
        node
        for node in ast.walk(NOTEBOOK_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one def {name} in {NOTEBOOK.name}, found {len(found)}"
    )
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(namespace or {})
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[name]


_NS = {
    "pl": pl,
    "GAP_CUT_BREAKS": GAP_CUT_BREAKS,
    "GAP_CUT_LABELS": GAP_CUT_LABELS,
}
gap_bin_expr = _load_from_notebook("gap_bin_expr", _NS)
epoch_minutes = _load_from_notebook("epoch_minutes", {"pl": pl})
all_pair_gaps = _load_from_notebook("all_pair_gaps", {"pl": pl, "epoch_minutes": epoch_minutes})

BASE = datetime.datetime(2024, 3, 1, 12, 0)


def _admins(spec):
    """spec: list of (encounter_block, minutes_after_BASE, med_category)."""
    return pl.DataFrame(
        {
            "encounter_block": [b for b, _, _ in spec],
            "admin_dttm": [BASE + datetime.timedelta(minutes=m) for _, m, _ in spec],
            "med_category": [c for _, _, c in spec],
        }
    )


def _bins(values):
    return (
        pl.DataFrame({"gap_minutes": [float(v) for v in values]})
        .with_columns(gap_bin_expr())
        .get_column("gap_bin")
        .to_list()
    )


# ------------------------------------------------------------------ the bin grid


def test_exact_zero_gets_its_own_bin():
    """Two agents charted on the same minute is the most informative value in the
    distribution and must not be pooled with 'under a minute'."""
    assert _bins([0]) == ["0"]
    assert _bins([0.0001]) == ["(0,1]"]


@pytest.mark.parametrize(
    ("gap", "label"),
    [
        (1, "(0,1]"),
        (1.0001, "(1,2]"),
        (15, "(10,15]"),
        (15.0001, "(15,30]"),
        (60, "(30,60]"),
        (60.0001, "(1,2]h"),
        (1440, "(12,24]h"),
        (4320, "(1,3]d"),
        (10080, "(3,7]d"),
        (10080.0001, ">7d"),
        (100000, ">7d"),
    ],
)
def test_bin_edges_are_left_open_right_closed(gap, label):
    """Every interval is (a, b]. The 15-minute edge matters most: it is the line the
    fold is drawn at, and a value landing on the wrong side of it would make Figure A.1
    disagree with the boundary it is evidence for."""
    assert _bins([gap]) == [label]


def test_the_seven_day_cap_is_a_bin_not_a_filter():
    """A filter would make the histogram's own denominator depend on the cap, so two
    sites with different long-stay mixes would not be comparable even on the short bins
    (P10)."""
    labels = _bins([5, 20000, 30000])
    assert labels.count(">7d") == 2
    assert None not in labels


def test_every_gap_lands_in_exactly_one_named_bin():
    values = [0, 0.5, 1, 3, 7, 12, 15, 22, 45, 90, 200, 500, 1000, 2000, 5000, 10080, 99999]
    labels = _bins(values)
    assert None not in labels
    assert set(labels) <= set(["0"] + GAP_CUT_LABELS)


# --------------------------------------------------------- the pair enumeration


def test_n_administrations_yield_n_choose_2_pairs():
    pairs = all_pair_gaps(_admins([(1, 0, "rocuronium")] + [(1, m, "vecuronium") for m in (2, 40, 100)]))
    assert pairs.height == 6  # 4 choose 2


def test_pairs_never_cross_an_encounter_block():
    """The bridge drops hospitalization_id precisely so gaps are computed per block; a
    leak across blocks would manufacture a gap between two different patients' drugs."""
    pairs = all_pair_gaps(
        _admins([(1, 0, "rocuronium"), (1, 5, "rocuronium"), (2, 7, "rocuronium")])
    )
    assert pairs.height == 1
    assert pairs.get_column("encounter_block").to_list() == [1]


def test_same_agent_pairs_are_included_and_flagged():
    """roc->roc at 3 min is a redose and roc->sux at 3 min is a co-administration. Both
    are counted (P9) and the split is what tells them apart."""
    pairs = all_pair_gaps(
        _admins([(1, 0, "rocuronium"), (1, 3, "rocuronium"), (1, 6, "succinylcholine")])
    ).sort("gap_minutes")
    assert pairs.get_column("is_same_agent").to_list() == [True, False, False]


def test_agent_pair_label_is_alphabetical():
    """One pair is one row, never two orderings of itself."""
    pairs = all_pair_gaps(_admins([(1, 0, "vecuronium"), (1, 4, "rocuronium")]))
    assert pairs.get_column("agent_pair").to_list() == ["rocuronium+vecuronium"]


def test_same_agent_pair_label_repeats_the_agent():
    pairs = all_pair_gaps(_admins([(1, 0, "rocuronium"), (1, 4, "rocuronium")]))
    assert pairs.get_column("agent_pair").to_list() == ["rocuronium+rocuronium"]


def test_gap_is_absolute_and_order_independent():
    pairs = all_pair_gaps(_admins([(1, 40, "rocuronium"), (1, 0, "vecuronium")]))
    assert pairs.get_column("gap_minutes").to_list() == [40.0]


def test_a_single_administration_yields_no_pairs():
    assert all_pair_gaps(_admins([(1, 0, "rocuronium")])).height == 0


def test_empty_input_yields_an_empty_frame_not_an_error():
    empty = _admins([]).cast({"encounter_block": pl.Int64})
    assert all_pair_gaps(empty).height == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pair_gaps.py -v`
Expected: FAIL with `AssertionError: expected exactly one def gap_bin_expr in 02_index_paralytic.py, found 0`

- [ ] **Step 3: Add the two functions to the notebook**

Insert into `code/02_index_paralytic.py`, **after** the administration-set cell from Task 2
Step 3 and **before** the fold markdown cell from Task 2 Step 4:

```python
@app.cell
def _(mo):
    mo.md(
        r"""
        ## A — the co-administration gap distribution

        Every **unordered pair** of paralytic administrations inside an `encounter_block`,
        same-agent pairs included (P9). This is the evidence for the fifteen-minute
        boundary, and it is computed here — before the fold — so that it depends on
        nothing the fold decides.

        The same/cross split is the point of the table. `rocuronium → rocuronium` at three
        minutes is a **redose**; `rocuronium → succinylcholine` at three minutes is a
        **co-administration**. The pooled histogram cannot tell them apart, and they
        justify the boundary for different reasons.

        The 7-day cap is a **bin, not a filter** (P10). A filter would make the histogram's
        own denominator depend on the cap, so two sites with different long-stay mixes
        would not be comparable even on the short bins.
        """
    )
    return


@app.cell
def _(GAP_CUT_BREAKS, GAP_CUT_LABELS, pl):
    def gap_bin_expr(col="gap_minutes"):
        """Assign a gap in minutes to one of the 15 named bins.

        Every interval is left-open and right-closed -- (a, b] -- so a gap of exactly 15
        minutes lands in `(10,15]` and 15.0001 lands in `(15,30]`. That edge is the line
        the fold is drawn at, and putting a value on the wrong side of it would make
        Figure A.1 disagree with the boundary it is evidence for.

        An exact zero is carved out of the first cut bin and given its own label: two
        agents charted on the same minute is the single most informative value in this
        distribution and pooling it with "under a minute" would hide it.
        """
        return (
            pl.when(pl.col(col) == 0)
            .then(pl.lit("0"))
            .otherwise(
                pl.col(col).cut(GAP_CUT_BREAKS, labels=GAP_CUT_LABELS).cast(pl.String)
            )
            .alias("gap_bin")
        )

    return (gap_bin_expr,)


@app.cell
def _(epoch_minutes, pl):
    def all_pair_gaps(df, time_col="admin_dttm", agent_col="med_category"):
        """Every unordered pair within each encounter_block. O(n^2) per block, by design.

        Adjacent-only pairing would miss `roc 12:00 ... vec 12:10` whenever anything is
        charted between them, and the sub-15-minute mass is exactly where the threshold
        decision lives (P9).

        The join is on `encounter_block` and nothing else, so a pair can never span two
        blocks. `_i < _i_r` takes each unordered pair once. The agent label is the two
        agents sorted alphabetically and joined with `+`, so one pair is one row rather
        than two orderings of itself.

        Returns encounter_block, gap_minutes, agent_pair, is_same_agent.
        """
        indexed = (
            df.sort(["encounter_block", time_col, agent_col])
            .with_row_index("_i")
            .select(
                "encounter_block",
                "_i",
                _t=epoch_minutes(time_col),
                _a=pl.col(agent_col),
            )
        )
        return (
            indexed.join(indexed, on="encounter_block", how="inner", suffix="_r")
            .filter(pl.col("_i") < pl.col("_i_r"))
            .select(
                "encounter_block",
                gap_minutes=(pl.col("_t_r") - pl.col("_t")).abs().round(3),
                agent_pair=pl.concat_str(
                    pl.min_horizontal("_a", "_a_r"),
                    pl.lit("+"),
                    pl.max_horizontal("_a", "_a_r"),
                ),
                is_same_agent=pl.col("_a") == pl.col("_a_r"),
            )
        )

    return (all_pair_gaps,)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_pair_gaps.py -v`
Expected: PASS, 22 tests

- [ ] **Step 5: Add the O(n²) guard and the three published tables**

Append immediately after the `all_pair_gaps` cell in `code/02_index_paralytic.py`:

```python
@app.cell
def _(MAX_TOTAL_PAIRS, all_pair_gaps, gap_bin_expr, med_admin, pl):
    _per_block = med_admin.group_by("encounter_block").agg(n=pl.len())
    _expected = (_per_block.get_column("n") * (_per_block.get_column("n") - 1) // 2).sum()

    print(f"administrations per block: max {_per_block.get_column('n').max():,}, "
          f"median {_per_block.get_column('n').median()}")
    print("ten densest blocks:")
    print(_per_block.sort("n", descending=True).head(10))
    print(f"pairs to enumerate       : {_expected:,}")

    # A MEMORY ceiling, not a clinical one. A site that trips this has charting unlike
    # anything this design was checked against; read the densest blocks above and decide
    # deliberately rather than raising the constant.
    assert _expected <= MAX_TOTAL_PAIRS, (
        f"{_expected:,} pairs exceeds MAX_TOTAL_PAIRS ({MAX_TOTAL_PAIRS:,}). This is a "
        "memory guard, not a study parameter -- inspect the densest blocks printed above "
        "before changing it."
    )

    coadmin_pairs = all_pair_gaps(med_admin).with_columns(gap_bin_expr())
    assert coadmin_pairs.height == _expected, (
        f"enumerated {coadmin_pairs.height:,} pairs but expected {_expected:,} -- the join "
        "either crossed an encounter_block boundary or double-counted an unordered pair"
    )
    assert coadmin_pairs.get_column("gap_bin").null_count() == 0, "a gap fell outside every bin"
    return (coadmin_pairs,)


@app.cell
def _(GAP_BIN_LABELS, SHARE_DIR, coadmin_pairs, med_admin, pl, publish):
    admin_summary = (
        med_admin.group_by(["med_category", "mar_action_category"])
        .agg(
            n_administrations=pl.len(),
            n_blocks=pl.col("encounter_block").n_unique(),
            n_patients=pl.col("patient_id").n_unique(),
        )
        .sort(["med_category", "mar_action_category"])
    )
    publish(
        admin_summary,
        SHARE_DIR / "paralytic_admin_summary.csv",
        ["n_administrations", "n_blocks", "n_patients"],
        "paralytic_admin_summary",
    )

    # Pooled, same-agent and cross-agent as three columns on one row per bin, so a reader
    # sees the split without joining two tables. Reindexed onto the full bin list so an
    # empty bin is published as a zero rather than being absent -- "this never happened"
    # and "this is missing" are different statements (§8).
    _counts = (
        coadmin_pairs.group_by("gap_bin")
        .agg(
            n_pooled=pl.len(),
            n_same_agent=pl.col("is_same_agent").sum(),
            n_cross_agent=(~pl.col("is_same_agent")).sum(),
        )
    )
    gap_distribution = (
        pl.DataFrame({"gap_bin": GAP_BIN_LABELS})
        .with_row_index("bin_order")
        .join(_counts, on="gap_bin", how="left")
        .with_columns(
            pl.col("n_pooled").fill_null(0),
            pl.col("n_same_agent").fill_null(0),
            pl.col("n_cross_agent").fill_null(0),
        )
        .sort("bin_order")
    )
    publish(
        gap_distribution,
        SHARE_DIR / "coadmin_gap_distribution.csv",
        ["n_pooled", "n_same_agent", "n_cross_agent"],
        "coadmin_gap_distribution",
    )

    gap_by_pair = (
        coadmin_pairs.group_by(["agent_pair", "gap_bin"])
        .agg(n=pl.len())
        .join(
            pl.DataFrame({"gap_bin": GAP_BIN_LABELS}).with_row_index("bin_order"),
            on="gap_bin",
            how="left",
        )
        .sort(["agent_pair", "bin_order"])
    )
    publish(
        gap_by_pair,
        SHARE_DIR / "coadmin_gap_by_pair.csv",
        ["n"],
        "coadmin_gap_by_pair",
    )

    print("\nsub-15-minute mass, the boundary evidence:")
    print(
        gap_distribution.filter(
            pl.col("gap_bin").is_in(["0", "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]"])
        )
    )
    return (gap_distribution,)
```

- [ ] **Step 6: Run the notebook**

Run: `uv run python code/02_index_paralytic.py`
Expected: completes; three CSVs appear in `output/final_no_phi/`.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add code/02_index_paralytic.py tests/test_pair_gaps.py
git commit -m "feat(02): sub-analysis A, the co-administration gap distribution

Spec §7.1. Every unordered pair of paralytic administrations within a block,
same-agent pairs included, binned on a log grid with a >7d overflow.

Computed BEFORE the fold and depending on nothing the fold decides, so it reads
as evidence for the 15-minute boundary rather than a consequence of it (P7).

The same/cross split is the point of the table: roc->roc at three minutes is a
redose, roc->sux at three minutes is a co-administration, and the pooled
histogram cannot tell them apart.

The 7-day cap is a bin, not a filter (P10) -- a filter would make the
denominator depend on the cap and break cross-site comparability on the short
bins. MAX_TOTAL_PAIRS is a memory ceiling and is labelled as one in both the
constant's comment and the assertion message, so nobody reads it as a study
parameter."
```

---

### Task 4: Sub-analysis C and Figures A.1 / C.1

**Files:**
- Modify: `code/02_index_paralytic.py` (append after the artifact write from Task 2 Step 8, keeping `if __name__ == "__main__"` last)

**Interfaces:**
- Consumes from Tasks 2 and 3: `index_paralytic`, `all_pair_gaps`, `gap_bin_expr`, `gap_distribution`, `GAP_BIN_LABELS`, `publish`, `SHARE_DIR`, `FIG_DIR`.
- Produces: `index_gap_distribution.csv`, `index_per_block.csv`, `index_paralytic_summary.csv`, `index_paralytic_dose.csv`, `figures/A1_coadmin_gap_distribution.png`, `figures/C1_index_gap_distribution.png`.

- [ ] **Step 1: Load the dataviz skill before writing any chart code**

Both figures in this task are charts. Invoke the `dataviz` skill and follow it for colour,
axis and legend choices. Do not write the plotting cells before reading it.

- [ ] **Step 2: Add sub-analysis C**

Insert into `code/02_index_paralytic.py`, after the `index_paralytic.write_parquet` cell:

```python
@app.cell
def _(mo):
    mo.md(
        r"""
        ## C — the gap between index paralytics

        The same construction as A, applied to index paralytics instead of raw
        administrations: all unordered pairs within a block, the identical bin grid, the
        identical overflow bin.

        By construction C has **zero mass in every bin up to and including `(10,15]`**, and
        the bound is strict rather than approximate. An anchor at `t` closes at `t + 15`
        inclusive, so the next anchor is the first administration *strictly after* `t + 15`;
        consecutive index paralytics are therefore always more than 15 minutes apart, and
        every non-consecutive pair is wider still.

        The assertion below is the cheapest possible test that P6 was implemented as
        written. A non-zero count in those six bins is a bug in the fold, not a finding.
        """
    )
    return


@app.cell
def _(GAP_BIN_LABELS, SHARE_DIR, all_pair_gaps, gap_bin_expr, index_paralytic, pl, publish):
    _EMPTY_BY_CONSTRUCTION = ["0", "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]"]

    index_pairs = all_pair_gaps(
        index_paralytic.select("encounter_block", "t_dttm", "agent_label"),
        time_col="t_dttm",
        agent_col="agent_label",
    ).with_columns(gap_bin_expr())

    _violations = index_pairs.filter(pl.col("gap_bin").is_in(_EMPTY_BY_CONSTRUCTION))
    assert _violations.height == 0, (
        f"{_violations.height:,} pairs of index paralytics are 15 minutes apart or less. "
        "The fold closes at t+15 inclusive, so the next anchor is strictly after it and "
        "these bins cannot be reached. This is a bug in collapse_agent_events, not a finding."
    )

    _counts = index_pairs.group_by("gap_bin").agg(n=pl.len())
    index_gap_distribution = (
        pl.DataFrame({"gap_bin": GAP_BIN_LABELS})
        .with_row_index("bin_order")
        .join(_counts, on="gap_bin", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .sort("bin_order")
    )
    publish(
        index_gap_distribution,
        SHARE_DIR / "index_gap_distribution.csv",
        ["n"],
        "index_gap_distribution",
    )

    index_per_block = (
        index_paralytic.group_by("encounter_block")
        .agg(n_index=pl.len())
        .group_by("n_index")
        .agg(n_blocks=pl.len())
        .sort("n_index")
    )
    publish(
        index_per_block,
        SHARE_DIR / "index_per_block.csv",
        ["n_blocks"],
        "index_per_block",
    )
    return index_gap_distribution, index_pairs


@app.cell
def _(SHARE_DIR, index_paralytic, pl, publish):
    index_summary = (
        index_paralytic.group_by("agent_label")
        .agg(
            n_index=pl.len(),
            n_blocks=pl.col("encounter_block").n_unique(),
            n_patients=pl.col("patient_id").n_unique(),
            n_coadmin=pl.col("is_coadmin").sum(),
            median_span_min=pl.col("span_minutes").median(),
            max_span_min=pl.col("span_minutes").max(),
        )
        .sort("n_index", descending=True)
    )
    publish(
        index_summary,
        SHARE_DIR / "index_paralytic_summary.csv",
        ["n_index", "n_blocks", "n_patients", "n_coadmin"],
        "index_paralytic_summary",
    )

    # P18: no unit conversion, anywhere. Keying on the unit means a site charting in both
    # mg and mg/kg produces two rows a reader can see, rather than one number that is
    # silently wrong.
    index_dose = (
        index_paralytic.explode("doses")
        .unnest("doses")
        .group_by(["med_category", "med_dose_unit"])
        .agg(
            n=pl.len(),
            median_dose=pl.col("med_dose").median(),
            p25_dose=pl.col("med_dose").quantile(0.25),
            p75_dose=pl.col("med_dose").quantile(0.75),
        )
        .sort(["med_category", "n"], descending=[False, True])
    )
    publish(
        index_dose,
        SHARE_DIR / "index_paralytic_dose.csv",
        ["n"],
        "index_paralytic_dose",
    )
    return
```

- [ ] **Step 3: Add Figures A.1 and C.1**

Both are drawn **from the published CSVs and nothing else** (spec P21), so suppression
propagates automatically and the figure cannot disagree with the table beside it.

Append to `code/02_index_paralytic.py`, before `if __name__ == "__main__":`:

```python
@app.cell
def _():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return (plt,)


@app.cell
def _(FIG_DIR, GAP_BIN_LABELS, SHARE_DIR, pl, plt):
    # Drawn from the PUBLISHED table, never from the PHI frame (P21). A bin suppressed
    # under the n>=10 rule is therefore absent from the plot automatically, and the caption
    # states how many bins that was rather than leaving the gap unexplained.
    _a1 = pl.read_csv(SHARE_DIR / "coadmin_gap_distribution.csv")
    _dropped_a1 = len(GAP_BIN_LABELS) - _a1.height

    _fig, _ax = plt.subplots(figsize=(11, 5))
    _x = range(_a1.height)
    _ax.bar([i - 0.2 for i in _x], _a1.get_column("n_same_agent"), width=0.4,
            label="same agent (redose)")
    _ax.bar([i + 0.2 for i in _x], _a1.get_column("n_cross_agent"), width=0.4,
            label="different agents (co-administration)")
    _ax.set_xticks(list(_x))
    _ax.set_xticklabels(_a1.get_column("gap_bin"), rotation=45, ha="right")
    _ax.set_xlabel("gap between paralytic administrations")
    _ax.set_ylabel("pairs")
    _ax.set_yscale("log")
    if "(10,15]" in _a1.get_column("gap_bin").to_list():
        _ax.axvline(
            _a1.get_column("gap_bin").to_list().index("(10,15]") + 0.5,
            color="black", linestyle="--", linewidth=1,
        )
        _ax.text(
            _a1.get_column("gap_bin").to_list().index("(10,15]") + 0.6,
            _ax.get_ylim()[1] * 0.5,
            "15 min\n(the fold)", fontsize=8, va="top",
        )
    _ax.legend()
    _ax.set_title(
        "A.1 — gaps between paralytic administrations, all pairs within an encounter\n"
        "15 minutes is a clinical definition, not a measured optimum (spec P7)"
        + (f"\n{_dropped_a1} bin(s) suppressed under the n>=10 rule" if _dropped_a1 else "")
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "A1_coadmin_gap_distribution.png", dpi=150)
    plt.close(_fig)
    print(f"A1_coadmin_gap_distribution.png -> {FIG_DIR}")
    return


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _a1 = pl.read_csv(SHARE_DIR / "coadmin_gap_distribution.csv").select("gap_bin", "n_pooled")
    _c1 = pl.read_csv(SHARE_DIR / "index_gap_distribution.csv").select("gap_bin", "n")
    _both = _a1.join(_c1, on="gap_bin", how="left").with_columns(pl.col("n").fill_null(0))

    _fig, _ax = plt.subplots(figsize=(11, 5))
    _x = range(_both.height)
    _ax.bar([i - 0.2 for i in _x], _both.get_column("n_pooled"), width=0.4,
            label="A — raw administrations")
    _ax.bar([i + 0.2 for i in _x], _both.get_column("n"), width=0.4,
            label="C — index paralytics")
    _ax.set_xticks(list(_x))
    _ax.set_xticklabels(_both.get_column("gap_bin"), rotation=45, ha="right")
    _ax.set_xlabel("gap")
    _ax.set_ylabel("pairs")
    _ax.set_yscale("log")
    _ax.legend()
    _ax.set_title(
        "C.1 — what the fold removed\n"
        "C is empty at and below 15 minutes by construction; this is the confirmation"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "C1_index_gap_distribution.png", dpi=150)
    plt.close(_fig)
    print(f"C1_index_gap_distribution.png -> {FIG_DIR}")
    return
```

- [ ] **Step 4: Run the notebook**

Run: `uv run python code/02_index_paralytic.py`
Expected: completes; `output/final_no_phi/` holds seven CSVs and `figures/` holds two PNGs.

- [ ] **Step 5: Verify C is empty below 15 minutes in the published table**

Run: `uv run python -c "import polars as pl; d=pl.read_csv('output/final_no_phi/index_gap_distribution.csv'); print(d.head(6))"`
Expected: `n` is 0 for the bins `0`, `(0,1]`, `(1,2]`, `(2,5]`, `(5,10]`, `(10,15]`.

If any is non-zero the notebook would already have raised — this is a read-back confirmation
that the published artifact says what the assertion checked.

- [ ] **Step 6: Commit**

```bash
git add code/02_index_paralytic.py
git commit -m "feat(02): sub-analysis C, the inter-index gap distribution, plus figures A.1 and C.1

Spec §7.2-7.3. The same all-pairs construction as A, applied to index
paralytics, on the identical bin grid so the two histograms are directly
comparable.

C is empty at and below 15 minutes by construction and the notebook asserts it:
the fold closes at t+15 inclusive, so the next anchor is strictly after it. That
assertion is the cheapest complete test that P6 was implemented as written -- a
non-zero count in those six bins is a fold bug, not a finding.

Both figures are drawn from the published CSVs and nothing else (P21), so a
suppressed bin disappears from the plot automatically and the caption states how
many were dropped. Dose statistics are keyed on (med_category, med_dose_unit)
with no conversion (P18)."
```

---

### Task 5: `03_context.py` — sub-analysis D, the non-IMV → IMV transition

**Files:**
- Create: `code/03_context.py`
- Create: `tests/test_imv_transition.py`

**Interfaces:**
- Consumes from Task 2: `output/intermediate_phi/index_paralytic.parquet` (schema in Task 2 Step 8), plus `output/intermediate_phi/cohort_resp_waterfall.parquet` from `01`.
- Produces, used by Task 6:
  - `is_transition_expr() -> pl.Expr` — boolean, requires `_pos` and `_prev_device` columns
  - `mark_transitions(waterfall: pl.DataFrame) -> pl.DataFrame` — adds `_pos`, `_prev_device`, `is_transition`, `opens_block`
  - `in_window_expr(offset_col: str, window_minutes: float) -> pl.Expr` — the shared ±window predicate (P15)
  - Notebook frames `index_paralytic`, `context_d`
  - CSVs `imv_transition_summary.csv`, `imv_offset_distribution.csv`

- [ ] **Step 1: Write the failing test**

Create `tests/test_imv_transition.py`:

```python
"""Pins the non-IMV -> IMV transition rule of `code/03_context.py` (spec P12, P13).

Sub-analysis D asks whether the DEVICE CHANGED around the index paralytic, not
whether IMV was charted. The distinction is the whole design: a patient who has
been ventilated for a week satisfies "IMV was charted in +/-60 min" without
anything having happened, so a state test cannot answer the question a transition
test answers.

Four cases define the rule and all four are checked below:

    nasal  -> imv     TRANSITION      an observed device change
    null   -> imv     TRANSITION      null is not imv; this is the first thing
                                      we ever learned about the airway
    [first row] imv   TRANSITION      the block opens on a ventilator -- the
                                      airway was secured before the extract's
                                      first row, which is a property of the
                                      extract, not evidence nothing occurred
    imv    -> imv     not a transition

The null case is the one that bites: `shift(1) != 'imv'` evaluates to NULL, not
TRUE, when the previous device is null, so a naive predicate silently drops every
one of them. `test_null_predecessor_is_a_transition` is that regression.

Run:  uv run pytest tests/test_imv_transition.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl
import pytest

NOTEBOOK = Path(__file__).parent.parent / "code" / "03_context.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())


def _load_from_notebook(name, namespace=None):
    found = [
        node
        for node in ast.walk(NOTEBOOK_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one def {name} in {NOTEBOOK.name}, found {len(found)}"
    )
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(namespace or {})
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[name]


is_transition_expr = _load_from_notebook("is_transition_expr", {"pl": pl})
mark_transitions = _load_from_notebook(
    "mark_transitions", {"pl": pl, "is_transition_expr": is_transition_expr}
)
in_window_expr = _load_from_notebook("in_window_expr", {"pl": pl})

BASE = datetime.datetime(2024, 3, 1, 12, 0)


def _waterfall(spec):
    """spec: list of (encounter_block, hours_after_BASE, device_category | None)."""
    return pl.DataFrame(
        {
            "encounter_block": [b for b, _, _ in spec],
            "recorded_dttm": [BASE + datetime.timedelta(hours=h) for _, h, _ in spec],
            "device_category": [d for _, _, d in spec],
        },
        schema_overrides={"device_category": pl.String},
    )


def _flags(spec):
    return mark_transitions(_waterfall(spec)).get_column("is_transition").to_list()


# ------------------------------------------------------------- the four cases


def test_observed_non_imv_to_imv_is_a_transition():
    assert _flags([(1, 0, "nasal cannula"), (1, 1, "imv")]) == [False, True]


def test_null_predecessor_is_a_transition():
    """THE regression. `shift(1) != 'imv'` is NULL when the previous device is null,
    and a filter on NULL keeps nothing -- so a naive predicate silently drops every
    patient whose record begins before anyone charted a device."""
    assert _flags([(1, 0, None), (1, 1, "imv")]) == [False, True]


def test_a_block_opening_on_imv_is_a_transition():
    """There is no preceding row at all. The airway was secured before the extract's
    first row, which is a property of the extract and not evidence that nothing
    happened (P12)."""
    assert _flags([(1, 0, "imv"), (1, 1, "imv")]) == [True, False]


def test_imv_to_imv_is_not_a_transition():
    assert _flags([(1, 0, "imv"), (1, 1, "imv"), (1, 2, "imv")]) == [True, False, False]


# --------------------------------------------------------------- around them


def test_extubation_and_reintubation_give_two_transitions():
    """A patient taken off the vent and put back on has had two airway events."""
    assert _flags(
        [(1, 0, "imv"), (1, 1, "face mask"), (1, 2, "imv")]
    ) == [True, False, True]


def test_transitions_do_not_cross_an_encounter_block():
    """Block 2's first row must be judged against nothing, not against block 1's last."""
    assert _flags([(1, 0, "imv"), (2, 1, "imv")]) == [True, True]


def test_opens_block_is_recorded_separately_from_a_null_predecessor():
    """Both give prior_device_category = null, so the two cases are otherwise
    indistinguishable in the published table."""
    marked = mark_transitions(_waterfall([(1, 0, "imv"), (2, 0, None), (2, 1, "imv")]))
    assert marked.get_column("opens_block").to_list() == [True, True, False]
    assert marked.get_column("_prev_device").to_list() == [None, None, None]


def test_rows_are_ordered_within_the_block_before_shifting():
    """An unsorted input must not change the answer -- the shift is meaningless unless
    the frame is in time order within each block."""
    shuffled = _waterfall([(1, 2, "imv"), (1, 0, "nasal cannula"), (1, 1, "nasal cannula")])
    marked = mark_transitions(shuffled).sort(["encounter_block", "recorded_dttm"])
    assert marked.get_column("is_transition").to_list() == [False, False, True]


# ------------------------------------------------------- the shared +/- window


@pytest.mark.parametrize(
    ("offset", "inside"),
    [(-61, False), (-60, True), (-0.5, True), (0, True), (59.9, True), (60, True), (60.1, False)],
)
def test_window_is_inclusive_at_both_ends(offset, inside):
    """Sub-analyses D and E share this one predicate (P15). Two implementations of an
    interval test drift at the boundary, and a one-row disagreement between 'IMV was
    near' and 'sedation was near' is invisible in aggregate and fatal to the joint
    reading."""
    got = (
        pl.DataFrame({"offset_minutes": [float(offset)]})
        .select(in_window_expr("offset_minutes", 60.0).alias("x"))
        .get_column("x")
        .to_list()
    )
    assert got == [inside]


def test_window_rejects_a_null_offset():
    """A null offset means no candidate row was found at all and must not pass."""
    got = (
        pl.DataFrame({"offset_minutes": [None]}, schema={"offset_minutes": pl.Float64})
        .select(in_window_expr("offset_minutes", 60.0).alias("x"))
        .get_column("x")
        .to_list()
    )
    assert got == [False]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_imv_transition.py -v`
Expected: FAIL — `FileNotFoundError: .../code/03_context.py`

- [ ] **Step 3: Create the notebook header, config and helpers**

Create `code/03_context.py`:

```python
import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import polars as pl

    from clifpy.tables import MedicationAdminIntermittent

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        MedicationAdminIntermittent,
        Path,
        json,
        mo,
        pl,
        publish,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 03 — what surrounds the index paralytic

        Two questions over the same ±60 minutes, asked with the **same window predicate**:

        | | |
        |---|---|
        | **D** | did the device transition from non-IMV to IMV? |
        | **E** | was a sedative charted, and at what dose? |

        D detects a **transition, not a state** (P12). "Was IMV charted in ±60 min" is
        satisfied by a patient who has been on the ventilator for a week — it reports the
        condition of the airway, not an event. A transition reports an event.

        The window predicate is shared between D and E and is the single exception to this
        project's duplicate-don't-share posture (P15). Two implementations of an interval
        test drift at the boundary, and a one-row disagreement between "IMV was near" and
        "sedation was near" is invisible in aggregate and fatal to the joint reading.

        Design: `docs/superpowers/specs/2026-08-10-paralytic-index-design.md` §7.4–7.5
        """
    )
    return


@app.cell
def _(Path, json):
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
    FIG_DIR = SHARE_DIR / "figures"
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    CONTEXT_WINDOW_MINUTES = float(config["context_window_minutes"])

    # P16. Sedation is a COVARIATE of the index paralytic, not a detector -- the question
    # is whether the paralytic was given as part of an induction or to a patient already
    # sedated. Benzodiazepine and opioid adjuncts were considered and declined: they blur
    # "induction happened here" with "this patient was comfortable".
    SEDATIVES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
    MAR_ACTIONS = ["given", "bolus"]

    # 5-minute bins across the full 120 minutes: 24 bins, left-closed and right-open
    # except the last, which is closed so an offset of exactly +60 has a home.
    OFFSET_BIN_WIDTH = 5

    print(f"site           : {SITE}")
    print(f"window         : +/- {CONTEXT_WINDOW_MINUTES:.0f} min   (P15)")
    print(f"sedatives      : {' | '.join(SEDATIVES)}")
    print(f"mar actions    : {' | '.join(MAR_ACTIONS)}")
    return (
        CONTEXT_WINDOW_MINUTES,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        MAR_ACTIONS,
        OFFSET_BIN_WIDTH,
        PHI_DIR,
        SEDATIVES,
        SHARE_DIR,
        TIMEZONE,
    )


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Pinned by
        `tests/test_clifpy_tz_boundary.py`. Defined locally, never imported (spec §4).
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def epoch_minutes(column):
        """Minutes since epoch, computed INSIDE polars, consulting no timezone at all.

        `datetime.timestamp()` on a site-naive value re-attaches the machine's zone; ten
        minutes across a DST fall-back would measure as seventy. Spec P19.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    return (epoch_minutes,)


@app.cell
def _(pl):
    def in_window_expr(offset_col, window_minutes):
        """The +/- window, defined ONCE and used by both D and E (P15).

        Inclusive at both ends. A null offset means no candidate row was found at all and
        must not pass -- absence of a candidate is not presence at the boundary.
        """
        return (
            pl.col(offset_col).is_not_null()
            & (pl.col(offset_col) >= -window_minutes)
            & (pl.col(offset_col) <= window_minutes)
        )

    return (in_window_expr,)
```

- [ ] **Step 4: Add the transition functions**

Append to `code/03_context.py`:

```python
@app.cell
def _(mo):
    mo.md(
        r"""
        ## D — the non-IMV → IMV transition

        ```
        a row is a TRANSITION when
              device_category == 'imv'
          AND ( no preceding row exists in the block
                OR preceding device_category != 'imv' )

        null is not imv     ->  null -> imv  IS a transition
        block opens on imv  ->  that first row IS a transition
        imv -> imv          ->  not a transition
        ```

        Computed on the **waterfalled** timeline, not raw `respiratory_support` (P13). Two
        reasons. *Mechanical:* a transition needs "the row before", and only the
        waterfall's gap-free hourly scaffold makes that well defined. *Clinical:* the
        waterfall relabels a null-device row to `imv` when the ventilator settings on it
        look like a ventilator, and that inference lands at or before the human device
        entry in every case measured — exactly zero delay in 77.3% of episodes, but 55 min
        at p95 and 540 min at p99. An intubation is a high-stress event and nobody stops to
        fill in the device field; the ventilator's settings reach the chart the moment it is
        connected.

        **No de-bouncing (P14).** The hourly scaffold means a brief non-IMV blip
        manufactures a spurious transition. `n_transitions_in_window` is published so the
        size of that effect is measurable, but no suppression rule is applied — it would be
        a second threshold with no evidence behind it.
        """
    )
    return


@app.cell
def _(pl):
    def is_transition_expr():
        """True where the device changes to IMV. Needs `_pos` and `_prev_device`.

        The `_prev_device.is_null()` term is load-bearing and is the reason this is a named
        function rather than an inline predicate. In polars, `shift(1) != 'imv'` evaluates
        to NULL -- not TRUE -- when the previous device is null, and a filter on NULL keeps
        nothing. Written naively, this rule would silently drop every patient whose record
        begins before anyone charted a device, which is where `null -> imv` transitions
        come from. Pinned by tests/test_imv_transition.py.
        """
        return (
            (pl.col("device_category") == "imv")
            & (
                (pl.col("_pos") == 0)
                | pl.col("_prev_device").is_null()
                | (pl.col("_prev_device") != "imv")
            )
        )

    return (is_transition_expr,)


@app.cell
def _(is_transition_expr, pl):
    def mark_transitions(waterfall):
        """Add `_pos`, `_prev_device`, `opens_block` and `is_transition` to the timeline.

        Sorted here rather than trusting the caller: the shift is meaningless unless the
        frame is in time order within each block, and `01` writing it sorted is a fact that
        could change without this notebook noticing.

        `opens_block` is recorded separately from `_prev_device` because both the
        block-opens-on-IMV case and the null-predecessor case give a null prior device, and
        the published table has to be able to tell them apart.
        """
        return (
            waterfall.sort(["encounter_block", "recorded_dttm"])
            .with_columns(
                _pos=pl.int_range(pl.len()).over("encounter_block"),
                _prev_device=pl.col("device_category").shift(1).over("encounter_block"),
            )
            .with_columns(
                opens_block=pl.col("_pos") == 0,
                is_transition=is_transition_expr(),
            )
        )

    return (mark_transitions,)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_imv_transition.py -v`
Expected: PASS, 17 tests

- [ ] **Step 6: Load the inputs and compute sub-analysis D**

Append to `code/03_context.py`:

```python
@app.cell
def _(PHI_DIR, pl):
    index_paralytic = pl.read_parquet(PHI_DIR / "index_paralytic.parquet")
    resp_waterfall = pl.read_parquet(PHI_DIR / "cohort_resp_waterfall.parquet")

    COHORT_RUN_ID = index_paralytic.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"index_paralytic carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    # encounter_block is seeded from a row index, so a re-extract renumbers everything.
    # Joining an index artifact from one run to a waterfall from another produces a table
    # that is silently wrong: the ids match, the rows are real, and they describe different
    # patients. §8.
    _blocks_missing = (
        index_paralytic.join(
            resp_waterfall.select("encounter_block").unique(), on="encounter_block", how="anti"
        )
        .get_column("encounter_block")
        .n_unique()
    )
    assert _blocks_missing == 0, (
        f"{_blocks_missing:,} encounter_blocks in index_paralytic have no waterfall rows. "
        "The two artifacts are almost certainly from different cohort runs -- check "
        "cohort_run_id and re-run 01 and 02 together."
    )

    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"index paralytics  : {index_paralytic.height:,}")
    print(f"waterfall rows    : {resp_waterfall.height:,}")
    return COHORT_RUN_ID, index_paralytic, resp_waterfall


@app.cell
def _(
    CONTEXT_WINDOW_MINUTES,
    epoch_minutes,
    in_window_expr,
    index_paralytic,
    mark_transitions,
    pl,
    resp_waterfall,
):
    _marked = mark_transitions(resp_waterfall)
    _transitions = _marked.filter(pl.col("is_transition")).select(
        "encounter_block",
        "recorded_dttm",
        "opens_block",
        prior_device_category="_prev_device",
        _tr_min=epoch_minutes("recorded_dttm"),
    )
    print(f"transitions on the whole timeline : {_transitions.height:,}")

    _idx = index_paralytic.select(
        "index_paralytic_id", "encounter_block", "t_dttm", _t_min=epoch_minutes("t_dttm")
    )

    _candidates = (
        _idx.join(_transitions, on="encounter_block", how="inner")
        .with_columns(imv_offset_minutes=(pl.col("_tr_min") - pl.col("_t_min")).round(3))
        .filter(in_window_expr("imv_offset_minutes", CONTEXT_WINDOW_MINUTES))
    )

    # The EARLIEST transition in the window, not the nearest to t. "First" is what was
    # asked for and the two differ whenever a transition precedes t and another follows it.
    _first = (
        _candidates.sort(["index_paralytic_id", "recorded_dttm"])
        .group_by("index_paralytic_id", maintain_order=True)
        .agg(
            imv_transition_dttm=pl.col("recorded_dttm").first(),
            imv_offset_minutes=pl.col("imv_offset_minutes").first(),
            prior_device_category=pl.col("prior_device_category").first(),
            transition_opens_block=pl.col("opens_block").first(),
            n_transitions_in_window=pl.len(),
        )
    )

    # Device state at t, for the already_on_imv reason: the most recent waterfall row at or
    # before t, by backward as-of join keyed on the block.
    _state = (
        _idx.sort("t_dttm")
        .join_asof(
            _marked.sort("recorded_dttm").select(
                "encounter_block", "recorded_dttm", _state_device="device_category"
            ),
            left_on="t_dttm",
            right_on="recorded_dttm",
            by="encounter_block",
            strategy="backward",
        )
        .select("index_paralytic_id", "_state_device", _has_row=pl.col("recorded_dttm").is_not_null())
    )

    context_d = (
        index_paralytic.join(_first, on="index_paralytic_id", how="left")
        .join(_state, on="index_paralytic_id", how="left")
        .with_columns(
            imv_transition=pl.col("imv_transition_dttm").is_not_null(),
            n_transitions_in_window=pl.col("n_transitions_in_window").fill_null(0).cast(pl.Int32),
        )
        .with_columns(
            no_transition_reason=pl.when(pl.col("imv_transition"))
            .then(pl.lit(None, dtype=pl.String))
            .when(~pl.col("_has_row").fill_null(False))
            .then(pl.lit("no_device_record"))
            .when(pl.col("_state_device") == "imv")
            .then(pl.lit("already_on_imv"))
            .otherwise(pl.lit("no_transition_in_window"))
        )
        .drop(["_state_device", "_has_row"])
    )

    _bad = context_d.filter(
        pl.col("imv_transition") & (pl.col("imv_offset_minutes").abs() > CONTEXT_WINDOW_MINUTES)
    )
    assert _bad.height == 0, f"{_bad.height:,} transitions sit outside the window"
    assert context_d.filter(
        pl.col("imv_transition") & pl.col("no_transition_reason").is_not_null()
    ).height == 0, "a detected transition also carries a no_transition_reason"
    assert context_d.filter(
        ~pl.col("imv_transition") & pl.col("no_transition_reason").is_null()
    ).height == 0, "a non-detection carries no reason"
    assert context_d.height == index_paralytic.height, "the join changed the row count"

    print(f"index paralytics with a transition in +/-{CONTEXT_WINDOW_MINUTES:.0f} min : "
          f"{context_d.get_column('imv_transition').sum():,} / {context_d.height:,} "
          f"({100 * context_d.get_column('imv_transition').mean():.1f}%)")
    print(context_d.group_by("no_transition_reason").agg(n=pl.len()).sort("n", descending=True))
    return (context_d,)
```

- [ ] **Step 7: Publish the D tables**

Append to `code/03_context.py`:

```python
@app.cell
def _(CONTEXT_WINDOW_MINUTES, OFFSET_BIN_WIDTH, SHARE_DIR, context_d, pl, publish):
    transition_summary = (
        context_d.group_by(["imv_transition", "no_transition_reason"])
        .agg(n=pl.len(), n_blocks=pl.col("encounter_block").n_unique())
        .sort("n", descending=True)
    )
    publish(
        transition_summary,
        SHARE_DIR / "imv_transition_summary.csv",
        ["n", "n_blocks"],
        "imv_transition_summary",
    )

    # P12: block-opens-on-IMV and a null-device predecessor both give a null prior device,
    # so transition_opens_block is what separates them in the published table.
    prior_device = (
        context_d.filter(pl.col("imv_transition"))
        .with_columns(
            prior_device_category=pl.col("prior_device_category").fill_null("(none charted)")
        )
        .group_by(["prior_device_category", "transition_opens_block"])
        .agg(n=pl.len())
        .sort("n", descending=True)
    )
    publish(
        prior_device,
        SHARE_DIR / "imv_prior_device.csv",
        ["n"],
        "imv_prior_device",
    )

    # 24 five-minute bins across the full 120 minutes, left-closed and right-open except
    # the last, which is closed so an offset of exactly +60 has a home.
    _n_bins = int(2 * CONTEXT_WINDOW_MINUTES // OFFSET_BIN_WIDTH)
    _edges = [
        -CONTEXT_WINDOW_MINUTES + OFFSET_BIN_WIDTH * i for i in range(_n_bins + 1)
    ]
    _labels = [f"[{_edges[i]:.0f},{_edges[i + 1]:.0f})" for i in range(_n_bins)]
    _labels[-1] = f"[{_edges[-2]:.0f},{_edges[-1]:.0f}]"

    _binned = (
        context_d.filter(pl.col("imv_transition"))
        .with_columns(
            _b=(
                ((pl.col("imv_offset_minutes") + CONTEXT_WINDOW_MINUTES) // OFFSET_BIN_WIDTH)
                .cast(pl.Int32)
                .clip(0, _n_bins - 1)
            )
        )
        .group_by("_b")
        .agg(n=pl.len())
    )
    offset_distribution = (
        pl.DataFrame({"_b": list(range(_n_bins)), "offset_bin": _labels})
        .with_columns(pl.col("_b").cast(pl.Int32))
        .join(_binned, on="_b", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .sort("_b")
        .rename({"_b": "bin_order"})
    )
    publish(
        offset_distribution,
        SHARE_DIR / "imv_offset_distribution.csv",
        ["n"],
        "imv_offset_distribution",
    )
    return


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 8: Run the notebook**

Run: `uv run python code/03_context.py`
Expected: completes; three CSVs appear in `output/final_no_phi/`.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add code/03_context.py tests/test_imv_transition.py
git commit -m "feat(03): sub-analysis D, the non-IMV to IMV transition

Spec §7.4. D detects a TRANSITION, not a state. 'Was IMV charted in +/-60 min'
is satisfied by a patient ventilated for a week -- it reports the condition of
the airway, not an event.

Four cases, all pinned: nasal->imv and null->imv and block-opens-on-imv are
transitions; imv->imv is not. The null case is the one that bites -- in polars
shift(1) != 'imv' is NULL, not TRUE, when the previous device is null, so a
naive predicate silently drops every patient whose record begins before anyone
charted a device. is_transition_expr exists as a named, tested function for
exactly that reason.

Computed on the waterfalled timeline (P13): a transition needs 'the row before',
and only the gap-free scaffold makes that well defined.

No de-bouncing (P14). n_transitions_in_window is published so the spurious-blip
effect is measurable; suppressing it would be a second threshold with no
evidence behind it."
```

---

### Task 6: Sub-analysis E, `index_context.parquet`, and Figures D.1 / E.1 / E.2

**Files:**
- Modify: `code/03_context.py` (insert the E cells before the `if __name__ == "__main__":` block, then the artifact write, then the figures)

**Interfaces:**
- Consumes from Task 5: `context_d`, `in_window_expr`, `epoch_minutes`, `to_site_naive`, `SEDATIVES`, `MAR_ACTIONS`, `CONTEXT_WINDOW_MINUTES`, `OFFSET_BIN_WIDTH`, `publish`.
- Produces: `output/intermediate_phi/index_context.parquet`; CSVs `sedation_summary.csv`, `sedation_offset_distribution.csv`, `sedation_dose.csv`; figures `D1_imv_offset.png`, `E1_sedation_offset.png`, `E2_sedation_dose.png`.

- [ ] **Step 1: Load the dataviz skill before writing any chart code**

Three of this task's deliverables are charts. Invoke the `dataviz` skill and follow it. Do
not write the plotting cells before reading it.

- [ ] **Step 2: Add the sedative load and window join**

Insert into `code/03_context.py`, after the D publishing cell and before
`if __name__ == "__main__":`:

```python
@app.cell
def _(mo):
    mo.md(
        r"""
        ## E — sedation in the same window

        The **identical** window predicate as D (P15), applied to
        `medication_admin_intermittent` over the five induction agents.

        **Every** administration in the window is kept, not just the nearest per agent
        (P17). The superseded design deduplicated by `med_category` because it was building
        a rank ladder, where one patient redosed six times would have dominated a
        distribution of ranks. This study publishes an offset *histogram*, where every
        administration is a legitimate observation of when sedation was charted —
        deduplicating would delete the redosing pattern the histogram exists to show.

        `med_dose` and `med_dose_unit` are the raw charted values and are **never
        converted** (P18). Dose statistics are keyed on `(med_category, med_dose_unit)`, so
        a site charting propofol in both `mg` and `mg/kg` produces two rows a reader can
        see rather than one number that is silently wrong.
        """
    )
    return


@app.cell
def _(
    CONTEXT_WINDOW_MINUTES,
    DATA_DIR,
    FILETYPE,
    MAR_ACTIONS,
    MedicationAdminIntermittent,
    PHI_DIR,
    SEDATIVES,
    TIMEZONE,
    epoch_minutes,
    in_window_expr,
    context_d,
    pl,
    to_site_naive,
):
    # The bridge again -- 03 reaches the medication table by hospitalization_id and drops
    # the column at the join, exactly as 02 does (P5). cohort_index is re-read here rather
    # than threaded through index_paralytic, which deliberately carries no hospitalization.
    _cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")
    _bridge = (
        _cohort_index.select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    _hosp_ids = _bridge.get_column("hospitalization_id").unique().to_list()

    _sed = MedicationAdminIntermittent.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "admin_dttm",
            "med_category",
            "mar_action_category",
            "med_dose",
            "med_dose_unit",
        ],
        filters={"hospitalization_id": _hosp_ids},
    )

    sed_admin = (
        pl.from_pandas(_sed.df.assign(admin_dttm=lambda d: to_site_naive(d["admin_dttm"])))
        .with_columns(
            med_category=pl.col("med_category").str.to_lowercase(),
            mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
        )
        .filter(
            pl.col("med_category").is_in(SEDATIVES)
            & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(_bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")
    )

    assert "hospitalization_id" not in sed_admin.columns, "the bridge leaked its key"

    _found = sed_admin.get_column("med_category").unique().to_list()
    _missing = sorted(set(SEDATIVES) - set(_found))
    print(f"sedative administrations : {sed_admin.height:,}")
    print(sed_admin.group_by(["med_category", "mar_action_category"]).agg(n=pl.len()).sort("n", descending=True))
    if _missing:
        print(f"\nNOT PRESENT AT THIS SITE: {', '.join(_missing)}")
    assert sed_admin.height > 0, (
        "no administration matched the sedative list at all -- compare the value_counts "
        "above against the mCIDE med_category list before trusting a zero."
    )

    sed_in_window = (
        context_d.select(
            "index_paralytic_id", "encounter_block", _t_min=epoch_minutes("t_dttm")
        )
        .join(
            sed_admin.with_columns(_s_min=epoch_minutes("admin_dttm")),
            on="encounter_block",
            how="inner",
        )
        .with_columns(offset_minutes=(pl.col("_s_min") - pl.col("_t_min")).round(3))
        .filter(in_window_expr("offset_minutes", CONTEXT_WINDOW_MINUTES))
        .select(
            "index_paralytic_id",
            "med_category",
            "admin_dttm",
            "offset_minutes",
            "med_dose",
            "med_dose_unit",
            "mar_action_category",
        )
    )

    print(f"sedative administrations inside a window : {sed_in_window.height:,}")
    return sed_admin, sed_in_window


@app.cell
def _(context_d, pl, sed_in_window):
    _nearest = (
        sed_in_window.with_columns(_abs=pl.col("offset_minutes").abs())
        # med_category breaks a tie on identical |offset| alphabetically, so the column is
        # byte-identical across runs.
        .sort(["index_paralytic_id", "_abs", "med_category"])
        .group_by("index_paralytic_id", maintain_order=True)
        .agg(
            nearest_sedative_med=pl.col("med_category").first(),
            nearest_sedative_offset_min=pl.col("offset_minutes").first(),
        )
    )

    _agg = (
        sed_in_window.group_by("index_paralytic_id")
        .agg(
            n_sedative_admins=pl.len(),
            sedative_agents=pl.col("med_category").unique().sort(),
            sedatives=pl.struct(
                med_category="med_category",
                admin_dttm="admin_dttm",
                offset_minutes="offset_minutes",
                med_dose="med_dose",
                med_dose_unit="med_dose_unit",
                mar_action_category="mar_action_category",
            ),
        )
    )

    index_context = (
        context_d.join(_agg, on="index_paralytic_id", how="left")
        .join(_nearest, on="index_paralytic_id", how="left")
        .with_columns(
            n_sedative_admins=pl.col("n_sedative_admins").fill_null(0).cast(pl.Int32),
            sedative_agents=pl.col("sedative_agents").fill_null([]),
            # An EMPTY array, not a null: the record is written for every index paralytic
            # so "nothing was given" and "this was not processed" stay distinguishable.
            sedatives=pl.col("sedatives").fill_null([]),
        )
        .with_columns(any_sedative=pl.col("n_sedative_admins") > 0)
        .sort(["encounter_block", "p_num"])
    )

    assert index_context.height == context_d.height, "the sedation join changed the row count"
    assert index_context.filter(
        pl.col("any_sedative") & pl.col("nearest_sedative_med").is_null()
    ).height == 0, "an index paralytic has sedation but no nearest agent"

    print(f"index paralytics with sedation in window : "
          f"{index_context.get_column('any_sedative').sum():,} / {index_context.height:,} "
          f"({100 * index_context.get_column('any_sedative').mean():.1f}%)")
    return (index_context,)
```

- [ ] **Step 3: Publish the E tables and write the artifact**

Append to `code/03_context.py`, still before `if __name__ == "__main__":`:

```python
@app.cell
def _(
    CONTEXT_WINDOW_MINUTES,
    OFFSET_BIN_WIDTH,
    PHI_DIR,
    SHARE_DIR,
    index_context,
    pl,
    publish,
    sed_in_window,
):
    index_context.write_parquet(PHI_DIR / "index_context.parquet")
    print(f"index_context.parquet   {index_context.height:,} rows -> {PHI_DIR}")

    sedation_summary = (
        index_context.with_columns(agent_set=pl.col("sedative_agents").list.join("+"))
        .with_columns(
            agent_set=pl.when(pl.col("agent_set") == "")
            .then(pl.lit("(none)"))
            .otherwise(pl.col("agent_set"))
        )
        .group_by(["any_sedative", "agent_set"])
        .agg(n=pl.len(), median_n_admins=pl.col("n_sedative_admins").median())
        .sort("n", descending=True)
    )
    publish(sedation_summary, SHARE_DIR / "sedation_summary.csv", ["n"], "sedation_summary")

    _n_bins = int(2 * CONTEXT_WINDOW_MINUTES // OFFSET_BIN_WIDTH)
    _edges = [-CONTEXT_WINDOW_MINUTES + OFFSET_BIN_WIDTH * i for i in range(_n_bins + 1)]
    _labels = [f"[{_edges[i]:.0f},{_edges[i + 1]:.0f})" for i in range(_n_bins)]
    _labels[-1] = f"[{_edges[-2]:.0f},{_edges[-1]:.0f}]"
    _grid = (
        pl.DataFrame({"bin_order": list(range(_n_bins)), "offset_bin": _labels})
        .with_columns(pl.col("bin_order").cast(pl.Int32))
        .join(sed_in_window.select("med_category").unique(), how="cross")
    )

    _binned = sed_in_window.with_columns(
        bin_order=(
            ((pl.col("offset_minutes") + CONTEXT_WINDOW_MINUTES) // OFFSET_BIN_WIDTH)
            .cast(pl.Int32)
            .clip(0, _n_bins - 1)
        )
    ).group_by(["bin_order", "med_category"]).agg(n=pl.len())

    sedation_offsets = (
        _grid.join(_binned, on=["bin_order", "med_category"], how="left")
        .with_columns(pl.col("n").fill_null(0))
        .sort(["med_category", "bin_order"])
    )
    publish(
        sedation_offsets,
        SHARE_DIR / "sedation_offset_distribution.csv",
        ["n"],
        "sedation_offset_distribution",
    )

    # P18: keyed on the unit, never converted.
    sedation_dose = (
        sed_in_window.group_by(["med_category", "med_dose_unit"])
        .agg(
            n=pl.len(),
            median_dose=pl.col("med_dose").median(),
            p25_dose=pl.col("med_dose").quantile(0.25),
            p75_dose=pl.col("med_dose").quantile(0.75),
        )
        .sort(["med_category", "n"], descending=[False, True])
    )
    publish(sedation_dose, SHARE_DIR / "sedation_dose.csv", ["n"], "sedation_dose")
    return
```

- [ ] **Step 4: Add Figures D.1, E.1 and E.2**

All three are drawn from the published CSVs and nothing else (P21). Append to
`code/03_context.py`, before `if __name__ == "__main__":`:

```python
@app.cell
def _():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return (plt,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _d1 = pl.read_csv(SHARE_DIR / "imv_offset_distribution.csv").sort("bin_order")
    _dropped = 24 - _d1.height

    _fig, _ax = plt.subplots(figsize=(11, 4.5))
    _ax.bar(range(_d1.height), _d1.get_column("n"))
    _ax.set_xticks(range(_d1.height))
    _ax.set_xticklabels(_d1.get_column("offset_bin"), rotation=90, fontsize=7)
    _ax.axvline(_d1.height / 2 - 0.5, color="black", linestyle="--", linewidth=1)
    _ax.set_xlabel("minutes from the index paralytic  (negative = the vent came first)")
    _ax.set_ylabel("index paralytics")
    _ax.set_title(
        "D.1 — where the non-IMV to IMV transition sits relative to the index paralytic"
        + (f"\n{_dropped} bin(s) suppressed under the n>=10 rule" if _dropped else "")
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "D1_imv_offset.png", dpi=150)
    plt.close(_fig)
    print(f"D1_imv_offset.png -> {FIG_DIR}")
    return


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _e1 = pl.read_csv(SHARE_DIR / "sedation_offset_distribution.csv")
    _agents = sorted(_e1.get_column("med_category").unique().to_list())

    _fig, _ax = plt.subplots(figsize=(11, 4.5))
    for _agent in _agents:
        _s = _e1.filter(pl.col("med_category") == _agent).sort("bin_order")
        _ax.plot(_s.get_column("bin_order"), _s.get_column("n"), marker="o",
                 markersize=3, label=_agent)
    _ax.axvline(11.5, color="black", linestyle="--", linewidth=1)
    _ax.set_xlabel("5-minute bin across the 120-minute window (bin 12 starts at t)")
    _ax.set_ylabel("administrations")
    _ax.legend(fontsize=8)
    _ax.set_title(
        "E.1 — sedative administrations around the index paralytic\n"
        "every administration in the window, not just the nearest per agent (P17)"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "E1_sedation_offset.png", dpi=150)
    plt.close(_fig)
    print(f"E1_sedation_offset.png -> {FIG_DIR}")
    return


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _e2 = pl.read_csv(SHARE_DIR / "sedation_dose.csv").with_columns(
        label=pl.concat_str(pl.col("med_category"), pl.lit("\n"), pl.col("med_dose_unit"))
    )

    _fig, _ax = plt.subplots(figsize=(11, 4.5))
    _y = range(_e2.height)
    _ax.barh(list(_y), _e2.get_column("median_dose"))
    _ax.errorbar(
        _e2.get_column("median_dose"),
        list(_y),
        xerr=[
            (_e2.get_column("median_dose") - _e2.get_column("p25_dose")).to_list(),
            (_e2.get_column("p75_dose") - _e2.get_column("median_dose")).to_list(),
        ],
        fmt="none", ecolor="black", capsize=3,
    )
    _ax.set_yticks(list(_y))
    _ax.set_yticklabels(_e2.get_column("label"), fontsize=7)
    _ax.set_xlabel("charted dose, median and IQR — NOT converted between units")
    _ax.set_title(
        "E.2 — sedative dose by agent and charted unit\n"
        "one row per (agent, unit): heterogeneity is shown, never normalised away (P18)"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "E2_sedation_dose.png", dpi=150)
    plt.close(_fig)
    print(f"E2_sedation_dose.png -> {FIG_DIR}")
    return
```

- [ ] **Step 5: Run the notebook**

Run: `uv run python code/03_context.py`
Expected: completes; `index_context.parquet` written; three more CSVs and three PNGs
appear.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add code/03_context.py
git commit -m "feat(03): sub-analysis E, sedation in the index window, plus figures D.1/E.1/E.2

Spec §7.5. The identical window predicate as D (P15), applied to the five
induction agents over medication_admin_intermittent.

Every administration in the window is kept, not just the nearest per agent
(P17). The superseded design deduplicated by med_category because it was
building a rank ladder; this study publishes an offset histogram, where every
administration is a legitimate observation and deduplicating would delete the
redosing pattern the histogram exists to show.

Doses are keyed on (med_category, med_dose_unit) and never converted (P18), so a
site charting propofol in both mg and mg/kg produces two visible rows rather
than one silently wrong number.

All three figures read the published CSVs and nothing else, so suppression
propagates automatically and the captions state what was dropped."
```

---

### Task 7: Remove the superseded pipeline

Left until last so the repo never sits in a state where `run_all.sh` names a notebook that
does not exist, and so every deletion happens after its replacement is proven to run.

**Files:**
- Delete: `code/02_index_imv.py`, `code/03_method_sedative.py`, `code/04_method_paralytic.py`, `code/05_method_pair.py`, `code/06_reference_cpt.py`, `code/07_agreement.py`
- Modify: `run_all.sh:21` (the `STEPS` array)
- Modify: `config/config_template.json`, `config/config.json`
- Rewrite: `docs/pipeline_flow.md`

- [ ] **Step 1: Confirm nothing references the notebooks about to be deleted**

Run: `grep -rn "02_index_imv\|03_method_sedative\|04_method_paralytic\|05_method_pair\|06_reference_cpt\|07_agreement" --include="*.py" --include="*.sh" --include="*.md" --include="*.toml" . | grep -v "^./docs/superpowers/plans/" | grep -v "^./docs/superpowers/specs/"`

Expected: only `run_all.sh` and `docs/pipeline_flow.md`, both rewritten below. If a test
file appears, it was not retargeted — go back and fix it before deleting anything.

- [ ] **Step 2: Delete the six notebooks**

```bash
git rm code/02_index_imv.py code/03_method_sedative.py code/04_method_paralytic.py \
       code/05_method_pair.py code/06_reference_cpt.py code/07_agreement.py
```

- [ ] **Step 3: Rewrite the `STEPS` array in `run_all.sh`**

Replace line 21:

```bash
STEPS=(01_cohort 02_index_imv 03_method_sedative 04_method_paralytic \
       05_method_pair 06_reference_cpt 07_agreement)
```

with:

```bash
STEPS=(01_cohort 02_index_paralytic 03_context)
```

Leave everything else in the file unchanged — the UTC log directory, the `uv sync`, the
per-step timing and the config-exists check all still apply.

- [ ] **Step 4: Rewrite both config files**

`config/config_template.json` becomes exactly:

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

`config/config.json` gets the same keys but **keeps this site's values** for `site_name`,
`data_directory`, `filetype`, `timezone` and `output_directory`:

```json
{
    "site_name": "mimic",
    "data_directory": "/Users/sudo_sage/Downloads/work/clif_m",
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

Removed keys and why (spec §9): `window_hours` was the old t₀ ± 3 h detection window;
`episode_gap_hours` was `02_index_imv.py`'s lookback; `pair_gap_hours` was
`05_method_pair.py`'s pairing threshold; `infusion_prep_minutes` drove the
continuous-table reclassification, and the continuous table is no longer opened.

- [ ] **Step 5: Rewrite `docs/pipeline_flow.md`**

Replace the whole file. It is the plain-language map of the pipeline; the spec is the
territory. Cover, in this order:

1. **What the study asks now** — the anchor inverted, and why that changes what can be
   concluded. State the P2 consequence explicitly: the cohort is ever-IMV, so D's hit rate
   has a floor and is not specificity.
2. **The pipeline at a glance** — the ASCII diagram from spec §3, reproduced.
3. **`01_cohort.py`** — unchanged; keep the existing stitching and waterfall explanations
   from the current document, including the "the settings say ventilator, so call it a
   ventilator" diagram, which is now load-bearing for sub-analysis D rather than for t₀.
4. **`02_index_paralytic.py`** — sub-analyses A, B, C, with the anchor-and-close worked
   example and the point that A is published before B applies its boundary.
5. **`03_context.py`** — sub-analyses D and E, with the four transition cases drawn out.
6. **Every rule in one table** — the format of the current §9, listing: cohort criteria;
   stitching at 6 h; the paralytic list; `given|bolus`; all-pairs gaps with the 7-day
   overflow bin; anchor-and-close at 15 min; `t` = the anchor's `admin_dttm`; the
   transition rule; the ±60 window shared by D and E; no unit conversion; n ≥ 10
   suppression.
7. **Footguns** — carry forward, edited to the new codebase: the pytz LMT trap; the
   `.timestamp()` trap; case sensitivity; `bfill` in the waterfall being inert;
   `encounter_block` not being stable across runs. **Add one:** `collapse_gap_minutes`
   cannot be applied post hoc — a wider fold merges two events and therefore *moves* `t`,
   so it produces a different index set rather than a coarser view of the current one, and
   filtering `span_minutes` on the output is not equivalent to re-running `02`.
8. **Delete** everything about `SED`, `PARA`, `PAIR`, `DEV`, `CPT`, the agreement tiers,
   the D40/D41 infusion reasoning, and the "one thing to keep in mind when reading Tier A"
   section. Update the header link to point at
   `superpowers/specs/2026-08-10-paralytic-index-design.md`.

Drop the "Counts shown are MIMIC, `cohort_run_id` 2026-08-06" line and its figures — every
count in the old document was computed under the IMV anchor and none of them survive the
inversion. Reinstate real numbers only after Step 6 has run the pipeline end to end.

- [ ] **Step 6: Run the whole pipeline from a clean output directory**

```bash
mv output output_pre_overhaul_$(date -u +%Y%m%dT%H%M%SZ)
./run_all.sh
```

Expected: three steps, all green. `output/final_no_phi/` holds thirteen CSVs plus
`figures/` with five PNGs; `output/intermediate_phi/` holds the `01` artifacts plus
`index_paralytic.parquet` and `index_context.parquet`.

- [ ] **Step 7: Fill the real counts into `docs/pipeline_flow.md`**

Read them from the run log and the published CSVs — not from memory, and not from the old
document. At minimum: encounter blocks, paralytic administrations, index paralytics, the
co-administration percentage, the D transition rate with its reason breakdown, and the E
any-sedative rate.

- [ ] **Step 8: Run the full suite one more time**

Run: `uv run pytest tests/ -v`
Expected: PASS — `test_clifpy_tz_boundary.py`, `test_collapse_agent_events.py`,
`test_min_cell_suppression.py`, `test_pair_gaps.py`, `test_imv_transition.py`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: delete the method-comparison pipeline; the paralytic anchor stands alone

Spec §12. The six notebooks below implemented a study that no longer runs, and
each is coupled to an anchor that has moved:

  02_index_imv       IMV is no longer the index event
  03_method_sedative sedation is a covariate now, not a detector
  04_method_paralytic superseded by 02_index_paralytic
  05_method_pair     its collapse rule was promoted; the pairing was not
  06_reference_cpt   a comparator for a comparison that ended
  07_agreement       Tiers A-F all measured method agreement

Deleted last, after their replacements were proven to run, so the repo never
sat in a state where run_all.sh named a file that did not exist.

Config loses window_hours, episode_gap_hours, pair_gap_hours and
infusion_prep_minutes -- the last of those drove the continuous-table
reclassification, and the continuous table is no longer opened at all. It gains
context_window_minutes for the +/-60 shared by D and E.

pipeline_flow.md is rewritten against the new anchor, with every count
recomputed: the old figures were all measured under the IMV anchor and none of
them survive the inversion."
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: §5 cohort → unchanged, asserted in Task 5
Step 6; §6.1 bridge → Task 2 Step 3; §6.2 administration set → Task 2 Step 3; §6.3 fold →
Task 2 Steps 4–7; §6.4 artifact → Task 2 Step 8; §7.0 bin grid → Task 2 Step 1 and Task 3
Step 3; §7.1 A → Task 3; §7.2 B → Task 4 Step 2; §7.3 C → Task 4 Step 2; §7.4 D → Task 5;
§7.5 E → Task 6; §8 outputs and suppression → Task 1 plus every `publish()` call; §9 config
→ Task 7 Step 4; §10 tests → Tasks 1, 2, 3, 5; §11 out of scope → nothing to build; §12
removal → Task 7. Decisions P1–P23 each appear in a code comment or a test docstring at the
point they govern.

**One gap found and closed:** spec §7.4 lists `prior_device_category` among D's outputs but
does not say how the block-opens-on-IMV case is distinguished from a null-device
predecessor, since both yield a null prior device. Task 5 adds `transition_opens_block` and
publishes `imv_prior_device.csv` keyed on both, which makes the two separable at read time.
That is one more CSV than spec §8 lists — an addition, not a contradiction.

**Placeholder scan:** none. Every code step carries the actual code; every test step carries
the actual assertions; every "run this" step states the exact command and the expected
outcome.

**Type consistency:** `epoch_minutes` takes a column name in both notebooks and defaults to
`"admin_dttm"` in `02` only, where every caller uses that column;`03` calls it with an
explicit argument every time. `all_pair_gaps` is called with defaults in Task 3 and with
`time_col="t_dttm", agent_col="agent_label"` in Task 4 — both signatures match the
definition. `publish(df, path, count_cols, label)` is called identically at all thirteen
sites. `index_paralytic_id` is the join key from Task 2 through Task 6 with no rename.
`in_window_expr(offset_col, window_minutes)` is called with a positional float in Tasks 5
and 6 and in the test.
