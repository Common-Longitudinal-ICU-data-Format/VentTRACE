# Block Summary and CPT Comparator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a block-level Table 1 (published twice, by encounter block and by index event) and a CPT `31500` comparator cascade to the VentTRACE pipeline, without modifying `01`–`03`.

**Architecture:** Three new marimo notebooks appended to the pipeline. `04_covariates.py` is the sole owner of the analytic row — it reads `index_context.parquet`, derives an evidence tier per event, joins every covariate from seven CLIF tables, and writes one 2,117-row PHI intermediate. `05_table_one.py` and `06_reference_cpt.py` only aggregate that frame; neither re-derives a block, re-selects `p_num`, nor re-computes a tier.

**Tech Stack:** Python 3.14, marimo notebooks, polars, clifpy (CLIF table loaders), matplotlib, pytest, uv.

**Design:** `docs/superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md` (decisions P26–P38).

## Global Constraints

Every task's requirements implicitly include this section.

- **Timezone (P19).** Every CLIF table loads via its clifpy class `from_file`, then the offset is removed with a locally-defined `to_site_naive(series)` = `series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)`. A bare `.dt.tz_localize(None)` is **forbidden** — clifpy returns a correct instant tagged with an LMT-based tzinfo, so stripping without converting shifts every row by ~1 hour. Never convert timezones in polars. Never call `datetime.timestamp()`, `astimezone`, or `fromtimestamp`.
- **Minute arithmetic (P19).** Inside polars only: `pl.col(c).dt.epoch("s") / 60.0`.
- **No shared helpers (spec §4).** `to_site_naive` and `epoch_minutes` are defined locally in each notebook, never imported. `utils/suppress.py` is the only shared module in this project.
- **Case (P20).** Every `*_category` value is lower-cased on load; every literal in the codebase is lower case; `from_file` filters enumerate casing variants because that filter runs before any normalisation we control.
- **Publishing (P21/P23).** `from utils.suppress import publish` is the only route into `output/final_no_phi/`. It raises if the frame carries `patient_id`, `hospitalization_id`, `encounter_block`, `p_num`, any `*_id` column (except `cohort_run_id`), or any `pl.Datetime`/`pl.Date` column.
- **Determinism.** Every published frame is sorted with a full tiebreak so output is byte-identical across runs (commit `6c70808`).
- **Window predicate (P33).** One helper, `in_lookback`, closed at both ends: `t0 - Xh <= dttm <= t0`. All four exposure sources call it.
- **Optional tables (spec §4).** `patient` and `patient_procedures` are required — absent, fail loudly. `crrt_therapy`, `position`, `vitals`, `hospital_diagnosis` are optional — absent, derived columns are **null, never false**, and coverage publishes 0%.
- **Commits.** No `Co-Authored-By` trailer. Conventional-commit prefixes matching this repo's history (`feat:`, `fix:`, `test:`, `docs:`, `add:`, `rm:`).
- **marimo cell form.** `@app.cell` / `def _(dep1, dep2):` / body / `return (name,)`. Cell-local names are `_`-prefixed. Dependencies are function parameters — there is no module scope.

## File Structure

| file | responsibility |
|---|---|
| `code/04_covariates.py` | **Create.** Sole owner of the analytic row. Opens `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `position`, `hospital_diagnosis`, and re-opens `hospitalization` and `adt`. Writes `output/intermediate_phi/index_covariates.parquet` (2,117 rows, PHI) and `output/final_no_phi/covariate_coverage.csv`. |
| `code/05_table_one.py` | **Create.** Aggregates the frame into `table1_by_agent_block.csv` (n=1,547) and `table1_by_agent_index.csv` (n=2,117), plus `figures/T1_life_support_by_window.png` and `figures/T2_source_coverage.png`. Opens no CLIF table. |
| `code/06_reference_cpt.py` | **Create.** Opens `patient_procedures`. Writes `cpt_cascade.csv`, `cpt_cascade_qc.csv`, `cpt_offset_distribution.csv`, `figures/F1_cpt_cascade.png`, `figures/F2_cpt_offset.png`. |
| `tests/test_lookback_window.py` | **Create.** Pins P33's interval boundaries. |
| `tests/test_mortality_bound.py` | **Create.** Pins P37's `death_dttm` bound and the undeterminable bucket. |
| `tests/test_cpt_bridge.py` | **Create.** Pins the explode-and-drop bridge for CPT. |
| `tests/test_block_row_contract.py` | **Create.** Pins the `p_num = 1` subset and block-column constancy. |
| `tests/test_collapse_agent_events.py` | **Modify.** Extend `ALL_NOTEBOOKS` (the no-naive-timestamp AST check) to `04`, `05`, `06`. |
| `tests/test_publish_guard.py` | **Modify.** Assert `index_covariates.parquet`'s column set is rejected by `publish()`. |
| `run_all.sh:24` | **Modify.** `STEPS` gains the three new notebooks. |
| `README.md` | **Modify.** Required-tables section gains seven tables. |
| `docs/pipeline_flow.md` | **Modify.** §2 notebook map gains three rows. |
| `code/README.md` | **Modify.** Notebook table gains three rows. |

---

### Task 1: `04_covariates.py` spine — event frame, evidence tier, and the window helper

**Files:**
- Create: `code/04_covariates.py`
- Create: `tests/test_lookback_window.py`
- Create: `tests/test_block_row_contract.py`

**Interfaces:**
- Consumes: `output/intermediate_phi/index_context.parquet` (2,117 rows; carries `index_paralytic_id`, `encounter_block`, `patient_id`, `cohort_run_id`, `p_num`, `t_dttm`, `agent_label`, `imv_transition`, `no_transition_reason`, `any_sedative`); `output/intermediate_phi/cohort_index.parquet` (34,017 rows; carries `encounter_block`, `patient_id`, `list_hospitalization_id`, `n_hospitalizations`).
- Produces: `in_lookback(t0_col, dttm_col, hours) -> pl.Expr`; `evidence_tier(imv_col, sed_col) -> pl.Expr`; the frame `index_covariates` with columns `index_paralytic_id, encounter_block, patient_id, cohort_run_id, p_num, t_dttm, agent_label, agent_stratum, imv_transition, no_transition_reason, any_sedative, evidence_tier, n_index_in_block`; module names `bridge`, `bridge_hosp_ids`, `to_site_naive`, `epoch_minutes`, `SITE`, `DATA_DIR`, `FILETYPE`, `TIMEZONE`, `PHI_DIR`, `SHARE_DIR`, `FIG_DIR`, `LOOKBACK_HOURS`.

- [ ] **Step 1: Write the failing test for the window predicate**

Create `tests/test_lookback_window.py`. The notebook is not an importable module name and importing it would run the pipeline against real PHI, so the function is lifted out by AST exactly as `tests/test_pair_gaps.py` does it.

```python
"""Pins the look-back window of `04_covariates.py` (spec P33).

Twelve interval tests live in that notebook -- four exposure sources times three
windows -- and they all call one helper for the reason P15 gives about D and E:
two implementations of an interval test drift at the boundary, and a one-row
disagreement between "on pressors" and "on CRRT" is invisible in aggregate.

The window is closed at BOTH ends: t0 - Xh <= dttm <= t0. A row exactly on the
far edge is in; a row one microsecond earlier is out; a row after t0 is out --
an exposure "before the index" may not include the index minute's own charting
sweeping forward.

Run:  uv run pytest tests/test_lookback_window.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl

NOTEBOOK = Path(__file__).parent.parent / "code" / "04_covariates.py"
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
    ns = {"pl": pl}
    ns.update(namespace or {})
    exec(compile(ast.Module(body=[found[0]], type_ignores=[]), NOTEBOOK.name, "exec"), ns)
    return ns[name]


in_lookback = _load_from_notebook("in_lookback")

T0 = datetime.datetime(2024, 3, 1, 12, 0, 0)


def _frame(offsets_minutes):
    return pl.DataFrame(
        {
            "t0": [T0] * len(offsets_minutes),
            "dttm": [T0 + datetime.timedelta(minutes=m) for m in offsets_minutes],
        }
    )


def test_far_edge_is_inclusive():
    """A row exactly on t0 - 24h is inside the 24h window."""
    got = _frame([-1440]).select(in_lookback("t0", "dttm", 24)).to_series().to_list()
    assert got == [True]


def test_one_microsecond_before_far_edge_is_out():
    df = pl.DataFrame(
        {
            "t0": [T0],
            "dttm": [T0 - datetime.timedelta(hours=24, microseconds=1)],
        }
    )
    assert df.select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [False]


def test_t0_itself_is_inclusive():
    """The window closes ON t0, so charting at the index minute counts."""
    assert _frame([0]).select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [True]


def test_after_t0_is_out():
    """One second after the index is not 'before the index'."""
    df = pl.DataFrame({"t0": [T0], "dttm": [T0 + datetime.timedelta(seconds=1)]})
    assert df.select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [False]


def test_windows_nest():
    """1h subset of 6h subset of 24h -- a row in a tighter window is in every wider one."""
    offsets = [-30, -180, -1000, -2000]
    df = _frame(offsets)
    got = df.select(
        in_lookback("t0", "dttm", 1).alias("h1"),
        in_lookback("t0", "dttm", 6).alias("h6"),
        in_lookback("t0", "dttm", 24).alias("h24"),
    )
    for row in got.iter_rows(named=True):
        assert not (row["h1"] and not row["h6"]), "in 1h but not 6h"
        assert not (row["h6"] and not row["h24"]), "in 6h but not 24h"
    assert got.to_dicts() == [
        {"h1": True, "h6": True, "h24": True},
        {"h1": False, "h6": True, "h24": True},
        {"h1": False, "h6": False, "h24": True},
        {"h1": False, "h6": False, "h24": False},
    ]


def test_null_dttm_is_not_in_window():
    """A missing timestamp is not an exposure. Null must not propagate as true."""
    df = pl.DataFrame({"t0": [T0], "dttm": [None]}, schema={"t0": pl.Datetime, "dttm": pl.Datetime})
    assert df.select(in_lookback("t0", "dttm", 24)).to_series().to_list() == [False]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_lookback_window.py -v`
Expected: FAIL — `FileNotFoundError` or `AssertionError: expected exactly one def in_lookback in 04_covariates.py, found 0`, because the notebook does not exist yet.

- [ ] **Step 3: Create `code/04_covariates.py` through the spine cell**

Write the notebook header, config cell, helper cell, and event-spine cell. Copy the header form exactly from `code/03_context.py`.

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

    from clifpy.tables import (
        Adt,
        CrrtTherapy,
        HospitalDiagnosis,
        Hospitalization,
        MedicationAdminContinuous,
        Patient,
        Position,
        Vitals,
    )

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        Adt,
        CrrtTherapy,
        HospitalDiagnosis,
        Hospitalization,
        MedicationAdminContinuous,
        Patient,
        Path,
        Position,
        Vitals,
        json,
        mo,
        pl,
        publish,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 04 — covariates of the index paralytic

        The sole owner of this study's analytic row. Everything downstream — both Table 1s
        and the CPT cascade — aggregates the single frame this notebook writes, and none of
        them re-derives a block, re-selects `p_num`, or re-computes a tier. That is what
        keeps `table1_by_agent_block.csv` and `cpt_cascade.csv` from disagreeing about N.

        One row per index paralytic event. Block-level attributes (LOS, mortality, the
        block's index count) are constant within a block and repeat down its rows; the
        `unit` column of Table 1 is what keeps that legible downstream (P35).

        Design: `docs/superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md`
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

    # P33. An ANALYSIS grid, not a site parameter -- a site that changed these windows
    # would make its Table 1 non-comparable with every other site's, which is the one
    # thing a multi-site Table 1 exists for. Same reasoning as P11's gap bins.
    # 1h is the senior author's "at the time of intubation"; 6h and 24h are the study
    # lead's. The trio also aligns column-for-column with the RSI reference table.
    LOOKBACK_HOURS = [1, 6, 24]

    # P32. Continuous medications supply a PRESENCE FLAG and nothing else -- no dose,
    # no rate, no infusion-derived index event. A module constant, not a config key,
    # for the reason P11 gives about the gap bins.
    VASOPRESSORS = [
        "norepinephrine",
        "vasopressin",
        "epinephrine",
        "phenylephrine",
        "dopamine",
    ]

    print(f"site           : {SITE}")
    print(f"lookback hours : {LOOKBACK_HOURS}")
    print(f"vasopressors   : {' | '.join(VASOPRESSORS)}")
    return (
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        LOOKBACK_HOURS,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        TIMEZONE,
        VASOPRESSORS,
        config,
    )


@app.cell
def _(TIMEZONE, pl):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Pinned by
        `tests/test_clifpy_tz_boundary.py`. Defined locally, never imported (spec §4).
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    def epoch_minutes(column):
        """Minutes since epoch, computed INSIDE polars, consulting no timezone at all.

        `datetime.timestamp()` on a site-naive value re-attaches the machine's zone; ten
        minutes across a DST fall-back would measure as seventy. Spec P19.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    def in_lookback(t0_col, dttm_col, hours):
        """True when `dttm_col` falls in the window `[t0 - hours, t0]`, closed at both ends.

        The ONE implementation every exposure source calls (P33). Twelve interval tests
        written independently -- four sources times three windows -- will disagree about a
        row landing exactly on the far edge, and that disagreement is invisible in
        aggregate while being fatal to a joint reading of "already shocked" versus
        "crashed at intubation".

        Closed at `t0` as well as at `t0 - hours`: a vasopressor charted on the index
        minute is an exposure at the index. Closed at the far edge so the parameter reads
        as "within 24 hours", matching how P6's fold closes inclusively at `t + 15`.

        Arithmetic is done on epoch seconds inside polars, which reads the stored naive
        wall-clock value and consults no timezone at all (P19).

        A null timestamp is NOT in the window: `null <= x` is null in polars, and a null
        exposure flag would later be filled or summed as if it were a measurement. The
        explicit `fill_null(False)` makes "we have no timestamp" resolve to "not an
        exposure in this window", which is what the source-coverage table (T2) exists to
        qualify.
        """
        _t0 = pl.col(t0_col).dt.epoch("s")
        _dttm = pl.col(dttm_col).dt.epoch("s")
        return (
            (_dttm <= _t0) & (_dttm >= _t0 - int(hours * 3600))
        ).fill_null(False)

    return epoch_minutes, in_lookback, to_site_naive
```

- [ ] **Step 4: Run the window test to verify it passes**

Run: `uv run pytest tests/test_lookback_window.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Add the event-spine cell**

Append to `code/04_covariates.py`. `index_context.parquet` already carries every `index_paralytic.parquet` column plus D and E, so it is read alone — joining both would be a redundant join on the same key.

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## The event spine

        `index_context.parquet` is read alone. It already carries every column
        `index_paralytic.parquet` has, plus D's transition result and E's sedation result,
        so reading both would be a redundant join on the same key.

        The **evidence tier** (P31) is computed here, per event, from that event's own D
        and E flags. Tier 3 requires both on the *same* event — which is exactly what P15
        bought by making D and E share one window predicate. The cascade in `06` reads
        this column from the `p_num = 1` row only; the tier exists on every row because the
        index-level Table 1 reports it too.

        `agent_stratum` collapses `agent_label` into the Table 1 columns: any label
        containing `+` is a co-administration and becomes `combination`; everything else
        keeps its agent name. A rocuronium redose has `agent_label == 'rocuronium'` and is
        therefore `rocuronium`, not `combination` (spec §3.2).
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    def evidence_tier(imv_col, sed_col):
        """The block's evidence tier, P31, computed per event from that event's own flags.

        3 = an IMV device transition AND a sedative in this event's own +/-60 min window
        2 = an IMV device transition, no sedative
        1 = neither

        Tier 3 conjoins D and E on the SAME event rather than on the block. A block whose
        first paralytic had a transition and whose fifth had sedation describes two
        clinical acts days apart, and calling that tier 3 would manufacture evidence that
        no single intubation ever produced.
        """
        return (
            pl.when(pl.col(imv_col) & pl.col(sed_col))
            .then(pl.lit(3))
            .when(pl.col(imv_col))
            .then(pl.lit(2))
            .otherwise(pl.lit(1))
            .cast(pl.Int8)
        )

    index_context = pl.read_parquet(PHI_DIR / "index_context.parquet")

    spine = index_context.select(
        "index_paralytic_id",
        "encounter_block",
        "patient_id",
        "cohort_run_id",
        "p_num",
        "t_dttm",
        "agent_label",
        "imv_transition",
        "no_transition_reason",
        "any_sedative",
    ).with_columns(
        evidence_tier("imv_transition", "any_sedative").alias("evidence_tier"),
        # Table 1 stratum. `+` is the co-administration marker `02` builds by joining the
        # sorted agent set; index_composition.csv already separates that from same-agent
        # redose, and this collapse keeps the two consistent.
        pl.when(pl.col("agent_label").str.contains(r"\+", literal=False))
        .then(pl.lit("combination"))
        .otherwise(pl.col("agent_label"))
        .alias("agent_stratum"),
        pl.len().over("encounter_block").cast(pl.Int32).alias("n_index_in_block"),
    )

    # The frame this notebook owns is the event frame; every consumer subsets it. A
    # height that has drifted from 03's output means an upstream re-run that this
    # notebook's inputs no longer match, and every count below would be silently off.
    assert spine.height == index_context.height, "the spine lost or duplicated events"
    assert spine.get_column("index_paralytic_id").is_unique().all(), (
        "index_paralytic_id is not unique in the spine"
    )
    assert spine.get_column("p_num").min() == 1, "p_num does not start at 1"

    _blocks = spine.get_column("encounter_block").n_unique()
    print(f"index events        : {spine.height:,}")
    print(f"encounter blocks    : {_blocks:,}")
    print(spine.group_by("evidence_tier").agg(n=pl.len()).sort("evidence_tier"))
    print(spine.group_by("agent_stratum").agg(n=pl.len()).sort("n", descending=True))
    return evidence_tier, index_context, spine
```

- [ ] **Step 6: Write the block-row contract test**

Create `tests/test_block_row_contract.py`. This one runs against the real published artifacts because the contract it pins is about the *produced* frame, not about a function.

```python
"""Pins the analytic-row contract of `04_covariates.py` (spec P28, P34).

Three notebooks consume one frame and the whole no-drift argument rests on them
agreeing about which rows exist. What can go wrong without announcing itself:

  * the p_num = 1 subset drifting from the number of blocks that have an index
    paralytic, which would make Table 1's N disagree with index_per_block.csv;
  * a block-level column (LOS, mortality) varying WITHIN a block, which would
    mean it was computed per event instead of per block and would make the
    index-level table's outcome rows meaningless;
  * the evidence tier being non-monotone in its inputs.

Skipped when the pipeline has not been run -- these assert on real output.

Run:  uv run pytest tests/test_block_row_contract.py -v
"""

import json
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "config.json"

pytestmark = pytest.mark.skipif(
    not CONFIG.exists(), reason="config/config.json absent; pipeline has not been set up"
)


def _dirs():
    with open(CONFIG) as f:
        cfg = json.load(f)
    out = Path(cfg["output_directory"])
    if not out.is_absolute():
        out = ROOT / out
    return out / "intermediate_phi", out / "final_no_phi"


@pytest.fixture(scope="module")
def frame():
    phi, _ = _dirs()
    path = phi / "index_covariates.parquet"
    if not path.exists():
        pytest.skip("index_covariates.parquet absent; run code/04_covariates.py first")
    return pl.read_parquet(path)


@pytest.fixture(scope="module")
def index_per_block():
    _, share = _dirs()
    path = share / "index_per_block.csv"
    if not path.exists():
        pytest.skip("index_per_block.csv absent; run code/02_index_paralytic.py first")
    return pl.read_csv(path)


def test_p_num_one_subset_matches_index_per_block(frame, index_per_block):
    """The block table's N must equal the blocks that have at least one index."""
    expected = index_per_block.get_column("n_blocks").sum()
    got = frame.filter(pl.col("p_num") == 1).height
    assert got == expected, (
        f"the p_num = 1 subset has {got:,} rows but index_per_block.csv reports "
        f"{expected:,} blocks with at least one index paralytic"
    )


def test_one_p_num_one_row_per_block(frame):
    first = frame.filter(pl.col("p_num") == 1)
    assert first.get_column("encounter_block").is_unique().all(), (
        "a block has more than one p_num = 1 row"
    )
    assert first.height == frame.get_column("encounter_block").n_unique()


def test_block_level_columns_are_constant_within_a_block(frame):
    """LOS, mortality and the block's index count are block properties, not event ones."""
    block_cols = [
        "n_index_in_block",
        "los_hospital_days",
        "los_icu_days",
        "hospital_mortality",
        "icu_mortality",
    ]
    present = [c for c in block_cols if c in frame.columns]
    assert present, "none of the block-level columns are in the frame"
    varying = (
        frame.group_by("encounter_block")
        .agg([pl.col(c).n_unique().alias(c) for c in present])
        .filter(pl.any_horizontal([pl.col(c) > 1 for c in present]))
    )
    assert varying.height == 0, (
        f"{varying.height:,} blocks have a block-level column that varies within the "
        f"block -- it was computed per event instead of per block: {varying.head(3)}"
    )


def test_evidence_tier_is_consistent_with_its_inputs(frame):
    bad = frame.filter(
        ((pl.col("evidence_tier") == 3) & ~(pl.col("imv_transition") & pl.col("any_sedative")))
        | ((pl.col("evidence_tier") == 2) & ~(pl.col("imv_transition") & ~pl.col("any_sedative")))
        | ((pl.col("evidence_tier") == 1) & pl.col("imv_transition"))
    )
    assert bad.height == 0, f"{bad.height:,} rows have a tier inconsistent with D/E"


def test_agent_stratum_collapses_only_combinations(frame):
    combo = frame.filter(pl.col("agent_stratum") == "combination")
    assert combo.filter(~pl.col("agent_label").str.contains(r"\+")).height == 0, (
        "a single-agent label was collapsed into 'combination'"
    )
    single = frame.filter(pl.col("agent_stratum") != "combination")
    assert single.filter(pl.col("agent_label").str.contains(r"\+")).height == 0, (
        "a co-administration label was not collapsed into 'combination'"
    )
```

- [ ] **Step 7: Run both tests**

Run: `uv run pytest tests/test_lookback_window.py tests/test_block_row_contract.py -v`
Expected: `test_lookback_window.py` PASSES (6). `test_block_row_contract.py` SKIPS every test (`index_covariates.parquet` absent) — that is correct at this point; it will run once Task 4 writes the frame.

- [ ] **Step 8: Commit**

```bash
git add code/04_covariates.py tests/test_lookback_window.py tests/test_block_row_contract.py
git commit -m "feat(04): event spine, evidence tier, and the shared look-back window

One helper implements P33's interval for all four exposure sources, closed at
both ends. The evidence tier conjoins D and E on the same event -- what P15
bought by making them share a window predicate."
```

---

### Task 2: Attribute resolution — patient, the hospitalization containing t₀, LOS and mortality

**Files:**
- Modify: `code/04_covariates.py` (append cells after the event spine)
- Create: `tests/test_mortality_bound.py`

**Interfaces:**
- Consumes: `spine`, `to_site_naive`, `epoch_minutes`, `in_lookback`, `DATA_DIR`, `FILETYPE`, `TIMEZONE`, `PHI_DIR` from Task 1.
- Produces: `bridge` (`encounter_block`, `patient_id`, `hospitalization_id`; one row per hospitalization); `resolve_mortality(df) -> pl.DataFrame`; `spine_resolved` — `spine` plus `hospitalization_id` (the one containing t₀), `age_at_admission`, `sex_category`, `race_category`, `ethnicity_category`, `location_at_index`, `los_hospital_days`, `los_icu_days`, `hospital_mortality`, `icu_mortality`.

- [ ] **Step 1: Write the failing mortality test**

Create `tests/test_mortality_bound.py`.

```python
"""Pins P37's mortality rules in `04_covariates.py`.

`death_dttm` in the CLIF `patient` table is a PATIENT-level date and can be
registry-sourced. Unbounded, "death_dttm is not null OR discharge_category is
expired" fires for someone discharged alive who died months later at home, and
publishes it as in-hospital mortality. The bound is therefore part of the
definition, not a refinement of it.

ICU attribution is by death TIME inside an ADT icu interval (P37, chosen over
last-known-location). Its cost is that a block flagged dead by discharge_category
alone cannot be attributed either way; that count is published as its own row
rather than being absorbed into either numerator, which is the same reasoning
that put `no_device_record` beside `no_transition_in_window` in sub-analysis D.

Run:  uv run pytest tests/test_mortality_bound.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl

NOTEBOOK = Path(__file__).parent.parent / "code" / "04_covariates.py"
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
    ns = {"pl": pl}
    ns.update(namespace or {})
    exec(compile(ast.Module(body=[found[0]], type_ignores=[]), NOTEBOOK.name, "exec"), ns)
    return ns[name]


resolve_mortality = _load_from_notebook("resolve_mortality")

ADMIT = datetime.datetime(2024, 1, 1, 8, 0)
DISCH = datetime.datetime(2024, 1, 10, 8, 0)


def _block(death_dttm, discharge_category, icu_in=None, icu_out=None):
    """One block, one member hospitalization, optionally one ADT icu interval."""
    return pl.DataFrame(
        {
            "encounter_block": [1],
            "admission_dttm": [ADMIT],
            "discharge_dttm": [DISCH],
            "discharge_category": [discharge_category],
            "death_dttm": [death_dttm],
            "icu_in_dttm": [icu_in],
            "icu_out_dttm": [icu_out],
        },
        schema={
            "encounter_block": pl.Int32,
            "admission_dttm": pl.Datetime,
            "discharge_dttm": pl.Datetime,
            "discharge_category": pl.String,
            "death_dttm": pl.Datetime,
            "icu_in_dttm": pl.Datetime,
            "icu_out_dttm": pl.Datetime,
        },
    )


def test_death_after_discharge_is_not_in_hospital_mortality():
    """The registry-linked case the bound exists for."""
    later = DISCH + datetime.timedelta(days=90)
    got = resolve_mortality(_block(later, "home")).to_dicts()[0]
    assert got["hospital_mortality"] is False
    assert got["icu_mortality"] is False


def test_death_before_admission_is_not_in_hospital_mortality():
    earlier = ADMIT - datetime.timedelta(days=1)
    got = resolve_mortality(_block(earlier, "home")).to_dicts()[0]
    assert got["hospital_mortality"] is False


def test_death_inside_the_stay_is_in_hospital_mortality():
    inside = ADMIT + datetime.timedelta(days=3)
    got = resolve_mortality(_block(inside, "expired")).to_dicts()[0]
    assert got["hospital_mortality"] is True


def test_expired_category_alone_is_in_hospital_mortality():
    """No death_dttm at all, but the encounter says expired."""
    got = resolve_mortality(_block(None, "expired")).to_dicts()[0]
    assert got["hospital_mortality"] is True


def test_expired_category_alone_is_not_icu_mortality():
    """No death time means no ADT icu interval can contain it, so icu_mortality is
    false while hospital_mortality is true. The two are independent (P37 amended)."""
    got = resolve_mortality(_block(None, "expired")).to_dicts()[0]
    assert got["hospital_mortality"] is True
    assert got["icu_mortality"] is False


def test_death_inside_an_icu_interval_is_icu_mortality():
    inside = ADMIT + datetime.timedelta(days=3)
    got = resolve_mortality(
        _block(
            inside,
            "expired",
            icu_in=ADMIT + datetime.timedelta(days=2),
            icu_out=ADMIT + datetime.timedelta(days=4),
        )
    ).to_dicts()[0]
    assert got["icu_mortality"] is True


def test_death_outside_every_icu_interval_is_not_icu_mortality():
    """Died on the floor after an ICU stay: in-hospital, not ICU."""
    inside = ADMIT + datetime.timedelta(days=6)
    got = resolve_mortality(
        _block(
            inside,
            "expired",
            icu_in=ADMIT + datetime.timedelta(days=2),
            icu_out=ADMIT + datetime.timedelta(days=4),
        )
    ).to_dicts()[0]
    assert got["hospital_mortality"] is True
    assert got["icu_mortality"] is False


def test_icu_death_after_discharge_is_icu_mortality_without_hospital_mortality():
    """The MIMIC artifact P37's amendment accepts, pinned so it cannot regress.

    death_dttm trails discharge_dttm by under a day and the icu interval extends past
    discharge too. icu_mortality fires; hospital_mortality does not, because the death
    time is outside the stay and the disposition is not 'expired'. The two flags are
    independent by design -- this is not a violation to be asserted away.
    """
    got = resolve_mortality(
        _block(
            DISCH + datetime.timedelta(hours=20),
            "home",
            icu_in=DISCH - datetime.timedelta(hours=6),
            icu_out=DISCH + datetime.timedelta(hours=24),
        )
    ).to_dicts()[0]
    assert got["icu_mortality"] is True
    assert got["hospital_mortality"] is False


def test_survivor_is_not_dead_by_any_route():
    got = resolve_mortality(_block(None, "home")).to_dicts()[0]
    assert got["hospital_mortality"] is False
    assert got["icu_mortality"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_mortality_bound.py -v`
Expected: FAIL — `AssertionError: expected exactly one def resolve_mortality in 04_covariates.py, found 0`.

- [ ] **Step 3: Add the bridge and the hospitalization/ADT cell**

Append to `code/04_covariates.py`. The bridge is copied from `02_index_paralytic.py` rather than imported — this project duplicates rather than shares, and the assertion is part of the copy.

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## Attribute resolution

        A block stitches up to four hospitalizations, so an attribute recorded *per
        hospitalization* is undefined until we say which one. Every such case resolves to
        **the hospitalization containing `t₀`** — the one the index paralytic was actually
        charted under (spec §3.2). The alternative, the block's first hospitalization, was
        rejected because an ED presentation and the inpatient admission that follows can
        carry different recorded ages and different diagnosis lists, and the paralytic
        belongs to exactly one of them.

        LOS is **summed over the block's member hospitalizations**, not measured as the
        block's span (P38): the span would count the stitch gaps, during which the patient
        was not in the hospital.

        Mortality is bounded (P37). `death_dttm` is patient-level in CLIF and can be
        registry-sourced, so unbounded it fires for a patient discharged alive who died at
        home months later.
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

    bridge = (
        cohort_index.select(["encounter_block", "patient_id", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # Many-to-one, asserted rather than assumed. A duplicated key fans out every row on
    # the joins below, and the fan-out is self-consistent -- every downstream count would
    # still agree with itself while being wrong. Same assertion, same reason, as `02`.
    assert bridge.get_column("hospitalization_id").is_unique().all(), (
        "a hospitalization_id appears in more than one encounter_block"
    )

    print(f"encounter blocks   : {cohort_index.height:,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids, cohort_index


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    Hospitalization,
    TIMEZONE,
    bridge,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    _hosp_table = Hospitalization.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "patient_id",
            "admission_dttm",
            "discharge_dttm",
            "age_at_admission",
            "discharge_category",
        ],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    _hosp_pd = _hosp_table.df.copy()
    for _c in ("admission_dttm", "discharge_dttm"):
        _hosp_pd[_c] = to_site_naive(_hosp_pd[_c])

    hospitalization = (
        pl.from_pandas(_hosp_pd)
        .with_columns(pl.col("discharge_category").str.to_lowercase())
        .join(bridge.select("hospitalization_id", "encounter_block"), on="hospitalization_id", how="inner")
    )

    print(f"hospitalizations loaded : {hospitalization.height:,}")
    print(hospitalization.group_by("discharge_category").agg(n=pl.len()).sort("n", descending=True))
    return (hospitalization,)


@app.cell
def _(Adt, DATA_DIR, FILETYPE, TIMEZONE, bridge, bridge_hosp_ids, pl, to_site_naive):
    # P20. The casing variants are enumerated at the from_file boundary because that
    # filter runs before any normalisation we control, and a filter matching zero rows
    # looks exactly like a site where the thing never happens.
    _ICU_VARIANTS = ["icu", "ICU", "Icu"]

    _adt_table = Adt.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "location_category", "in_dttm", "out_dttm"],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    _adt_pd = _adt_table.df.copy()
    for _c in ("in_dttm", "out_dttm"):
        _adt_pd[_c] = to_site_naive(_adt_pd[_c])

    adt = (
        pl.from_pandas(_adt_pd)
        .with_columns(pl.col("location_category").str.to_lowercase())
        .join(bridge.select("hospitalization_id", "encounter_block"), on="hospitalization_id", how="inner")
    )

    adt_icu = adt.filter(pl.col("location_category") == "icu")

    print(f"adt rows loaded : {adt.height:,}")
    print(f"  icu rows      : {adt_icu.height:,}")
    print(adt.group_by("location_category").agg(n=pl.len()).sort("n", descending=True).head(10))
    return adt, adt_icu
```

- [ ] **Step 4: Add `resolve_mortality` and the block-outcome cell**

`resolve_mortality` takes an already-joined frame so it is testable in isolation — the test above builds that frame by hand. Its contract: one row per (block, hospitalization, icu-interval) candidate, returning one row per block.

```python
@app.cell
def _(pl):
    def resolve_mortality(df):
        """P37's mortality rules, over a frame of block x hospitalization x icu-interval.

        Expects: encounter_block, admission_dttm, discharge_dttm, discharge_category,
        death_dttm, icu_in_dttm, icu_out_dttm. Rows repeat per icu interval; a block with
        no icu row carries nulls in the two icu columns.

        Returns one row per encounter_block with three booleans:

          hospital_mortality  death_dttm inside a member hospitalization's
                              admission -> discharge interval, OR
                              discharge_category == 'expired'
          icu_mortality       death_dttm inside an ADT icu interval

        Two INDEPENDENT measurements, published side by side (P37 as amended
        2026-08-12). Neither is derived from the other and icu_mortality is deliberately
        NOT constrained to be a subset of hospital_mortality: at MIMIC a death_dttm can
        trail its own discharge_dttm by up to 24 hours while the ADT icu interval extends
        past discharge too, so a handful of blocks are icu_mortality without satisfying
        the hospital_mortality bound. That is a recording artifact, and the amended
        decision accepts it rather than papering over it with a grace window fitted to
        one site.

        The bound on death_dttm is retained and is the whole point of the first flag (see
        the module docstring of tests/test_mortality_bound.py): unbounded, it fires for a
        patient discharged alive who died at home months later.
        """
        _death_in_stay = (
            pl.col("death_dttm").is_not_null()
            & (pl.col("death_dttm") >= pl.col("admission_dttm"))
            & (pl.col("death_dttm") <= pl.col("discharge_dttm"))
        )
        _death_in_icu = (
            pl.col("death_dttm").is_not_null()
            & pl.col("icu_in_dttm").is_not_null()
            & (pl.col("death_dttm") >= pl.col("icu_in_dttm"))
            & (pl.col("death_dttm") <= pl.col("icu_out_dttm"))
        )
        return (
            df.group_by("encounter_block")
            .agg(
                _death_in_stay.any().alias("_death_dated_in_stay"),
                (pl.col("discharge_category") == "expired").any().alias("_expired_category"),
                _death_in_icu.any().alias("icu_mortality"),
            )
            .with_columns(
                (pl.col("_death_dated_in_stay") | pl.col("_expired_category")).alias(
                    "hospital_mortality"
                )
            )
            .drop("_death_dated_in_stay", "_expired_category")
            .sort("encounter_block")
        )

    return (resolve_mortality,)
```

- [ ] **Step 5: Run the mortality test to verify it passes**

Run: `uv run pytest tests/test_mortality_bound.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Add the `patient` load and the block-outcomes assembly cell**

```python
@app.cell
def _(DATA_DIR, FILETYPE, Patient, TIMEZONE, cohort_index, pl, to_site_naive):
    # REQUIRED table (spec §4). Absent, this fails loudly rather than publishing a
    # Table 1 with no demographics -- race and ethnicity are the specific rows the
    # senior-author review asked for.
    _patient_ids = cohort_index.get_column("patient_id").unique().to_list()

    _pat_table = Patient.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "patient_id",
            "sex_category",
            "race_category",
            "ethnicity_category",
            "death_dttm",
        ],
        filters={"patient_id": _patient_ids},
    )
    _pat_pd = _pat_table.df.copy()
    _pat_pd["death_dttm"] = to_site_naive(_pat_pd["death_dttm"])

    patient = pl.from_pandas(_pat_pd).with_columns(
        pl.col("sex_category").str.to_lowercase(),
        pl.col("race_category").str.to_lowercase(),
        pl.col("ethnicity_category").str.to_lowercase(),
    )

    assert patient.get_column("patient_id").is_unique().all(), (
        "patient_id is not unique in the patient table"
    )
    print(f"patients loaded : {patient.height:,}")
    print(f"  with death_dttm : {patient.get_column('death_dttm').is_not_null().sum():,}")
    return (patient,)


@app.cell
def _(adt_icu, epoch_minutes, hospitalization, patient, pl, resolve_mortality):
    # LOS: summed over member hospitalizations, never the block's span (P38). The span
    # would count the stitch gaps, during which the patient was not in the hospital.
    los_hospital = (
        hospitalization.with_columns(
            (
                (epoch_minutes("discharge_dttm") - epoch_minutes("admission_dttm")) / 1440.0
            ).alias("_days")
        )
        .group_by("encounter_block")
        .agg(pl.col("_days").sum().round(3).alias("los_hospital_days"))
    )

    los_icu = (
        adt_icu.with_columns(
            ((epoch_minutes("out_dttm") - epoch_minutes("in_dttm")) / 1440.0).alias("_days")
        )
        .group_by("encounter_block")
        .agg(pl.col("_days").sum().round(3).alias("los_icu_days"))
    )

    # One row per (block, hospitalization, icu interval) for resolve_mortality. The
    # cross-product is bounded: at most 4 hospitalizations times the block's icu rows.
    _mortality_input = (
        hospitalization.join(
            patient.select("patient_id", "death_dttm"), on="patient_id", how="left"
        )
        .join(
            adt_icu.select(
                "encounter_block",
                pl.col("in_dttm").alias("icu_in_dttm"),
                pl.col("out_dttm").alias("icu_out_dttm"),
            ),
            on="encounter_block",
            how="left",
        )
        .select(
            "encounter_block",
            "admission_dttm",
            "discharge_dttm",
            "discharge_category",
            "death_dttm",
            "icu_in_dttm",
            "icu_out_dttm",
        )
    )

    block_outcomes = (
        resolve_mortality(_mortality_input)
        .join(los_hospital, on="encounter_block", how="left")
        .join(los_icu, on="encounter_block", how="left")
        # A block with no ADT icu row spent no time in an ICU. That is a measured zero,
        # not a missing value, and filling it keeps the median from being computed on a
        # denominator that silently drops non-ICU blocks.
        .with_columns(pl.col("los_icu_days").fill_null(0.0))
        .sort("encounter_block")
    )

    print(f"blocks with outcomes : {block_outcomes.height:,}")
    print(f"  hospital mortality : {block_outcomes.get_column('hospital_mortality').sum():,}")
    print(f"  icu mortality      : {block_outcomes.get_column('icu_mortality').sum():,}")
    return block_outcomes, los_hospital, los_icu
```

- [ ] **Step 7: Add the t₀-resolution cell**

```python
@app.cell
def _(adt, block_outcomes, hospitalization, patient, pl, spine):
    # The hospitalization containing t0 (spec §3.2). An interval join, not a "first
    # hospitalization" shortcut: the ED presentation and the inpatient admission carry
    # different ages and different diagnosis lists, and the paralytic belongs to one.
    _hosp_at_t0 = (
        spine.select("index_paralytic_id", "encounter_block", "t_dttm")
        .join(hospitalization, on="encounter_block", how="left")
        .filter(
            (pl.col("t_dttm") >= pl.col("admission_dttm"))
            & (pl.col("t_dttm") <= pl.col("discharge_dttm"))
        )
        # A t0 landing in two member hospitalizations would mean overlapping stays, which
        # the stitcher should have merged. Take the earliest admission deterministically
        # and assert the tie is rare enough to be visible.
        .sort(["index_paralytic_id", "admission_dttm", "hospitalization_id"])
        .group_by("index_paralytic_id", maintain_order=True)
        .first()
        .select(
            "index_paralytic_id",
            "hospitalization_id",
            "age_at_admission",
            # Carried onto the frame because Table 1 reports the discharge disposition
            # breakdown; resolved to the hospitalization containing t0 like every other
            # per-hospitalization attribute (spec §3.2).
            "discharge_category",
        )
    )

    _location_at_t0 = (
        spine.select("index_paralytic_id", "encounter_block", "t_dttm")
        .join(adt, on="encounter_block", how="left")
        .filter(
            (pl.col("t_dttm") >= pl.col("in_dttm")) & (pl.col("t_dttm") < pl.col("out_dttm"))
        )
        .sort(["index_paralytic_id", "in_dttm", "location_category"])
        .group_by("index_paralytic_id", maintain_order=True)
        .first()
        .select(
            "index_paralytic_id",
            pl.when(pl.col("location_category").is_in(["ed", "icu"]))
            .then(pl.col("location_category"))
            .otherwise(pl.lit("other"))
            .alias("location_at_index"),
        )
    )

    spine_resolved = (
        spine.join(_hosp_at_t0, on="index_paralytic_id", how="left")
        .join(_location_at_t0, on="index_paralytic_id", how="left")
        .join(
            patient.select(
                "patient_id", "sex_category", "race_category", "ethnicity_category"
            ),
            on="patient_id",
            how="left",
        )
        .join(block_outcomes, on="encounter_block", how="left")
        # No ADT row covers t0 -- a real charting gap, and a distinct value from `other`,
        # which means "in a location that is neither ED nor ICU".
        .with_columns(pl.col("location_at_index").fill_null("unknown"))
    )

    assert spine_resolved.height == spine.height, "attribute resolution changed the row count"

    _unresolved = spine_resolved.get_column("hospitalization_id").null_count()
    print(f"events resolved            : {spine_resolved.height:,}")
    print(f"  t0 outside every stay    : {_unresolved:,}")
    print(spine_resolved.group_by("location_at_index").agg(n=pl.len()).sort("n", descending=True))
    return (spine_resolved,)
```

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all pass; `test_block_row_contract.py` still skips.

- [ ] **Step 9: Commit**

```bash
git add code/04_covariates.py tests/test_mortality_bound.py
git commit -m "feat(04): resolve attributes to the hospitalization containing t0

Age and CCI are undefined for a block that stitches four hospitalizations until
the spec says which one -- resolved by interval, not by 'first'. LOS sums member
stays rather than spanning the block, so stitch gaps are not counted as
inpatient time. death_dttm is bounded to the stay: unbounded it fires for a
patient who died at home months after discharge."
```

---

### Task 3: Life-support exposure — vasopressor, CRRT, prone, in three windows

**Files:**
- Modify: `code/04_covariates.py` (append cells after attribute resolution)

**Interfaces:**
- Consumes: `spine_resolved`, `in_lookback`, `to_site_naive`, `bridge`, `bridge_hosp_ids`, `LOOKBACK_HOURS`, `VASOPRESSORS`, `DATA_DIR`, `FILETYPE`, `TIMEZONE` from Tasks 1–2.
- Produces: `load_optional(loader, label, **from_file_kwargs) -> (pandas.DataFrame | None)`; `exposure_flags(events, source, dttm_col, prefix) -> pl.DataFrame`; `exposures` — one row per `index_paralytic_id` with `vasopressor_{1,6,24}h`, `crrt_{1,6,24}h`, `prone_{1,6,24}h` (Boolean or all-null); `source_coverage` — a list of `(source, n_rows, n_blocks_with_rows, available)` records.

- [ ] **Step 1: Add the optional-loader and exposure-flag helpers**

The distinction this cell encodes is the one from spec §4: an optional table that is absent produces **null** columns, never `false`. A `false` is indistinguishable from a clinical finding; a null cannot be misread.

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## Life support before the index

        Three sources, three windows, one predicate (P33). Every exposure is a **presence
        test** — did any row for this patient land in `[t₀ - Xh, t₀]` — because that is all
        P32 permits continuous medications to supply. No dose, no rate, no infusion-derived
        index event.

        **An absent optional table yields null, never `false`.** "No vasopressor row in 24
        h" is returned identically by a patient on no pressors and by a site that does not
        populate `medication_admin_continuous`. A `false` would make the second look like
        the first; a null cannot be misread, and `covariate_coverage.csv` is what qualifies
        it.

        **Do NOT apply `rate_unit_expr` here.** `02` and `03` drop rate-charted rows from
        `medication_admin_intermittent` because a discrete push charted as `mcg/kg/min` is
        an infusion misfiled as a bolus (commit `305de1f`). This table is the opposite
        case: every row in `medication_admin_continuous` is rate-charted by definition, and
        filtering on that would zero the vasopressor column entirely — which would read as
        "no patient was on pressors" rather than as a bug. Presence of an infusion **is**
        the exposure here; no dose or rate is read at all (P32).
        """
    )
    return


@app.cell
def _(LOOKBACK_HOURS, in_lookback, pl):
    def load_optional(loader, label, **kwargs):
        """Load an OPTIONAL clifpy table, returning None when the site does not have it.

        Required tables (`patient`, `patient_procedures`) do not go through this -- they
        raise. Optional ones degrade: the caller produces null columns and coverage
        publishes 0%, which is a visibly different result from a clinical zero.

        Catches only the absence of data, never a malformed load: a table that exists but
        fails to parse is a real error and must not be silently downgraded to "this site
        does not chart CRRT".
        """
        try:
            table = loader.from_file(**kwargs)
        except FileNotFoundError as exc:
            print(f"  [{label}] NOT AVAILABLE at this site -- {exc}")
            return None
        if table.df is None or len(table.df) == 0:
            print(f"  [{label}] present but empty")
            return None
        print(f"  [{label}] {len(table.df):,} rows")
        return table.df.copy()

    def exposure_flags(events, source, dttm_col, prefix):
        """One boolean per look-back window, per index event, for one exposure source.

        `events` carries index_paralytic_id, encounter_block and t_dttm.
        `source` carries encounter_block and `dttm_col`; None when the table is absent.

        Returns one row per index_paralytic_id with `{prefix}_{h}h` for each window. When
        `source` is None every column is a typed null -- NOT false (spec §4).

        The join is on encounter_block and nothing else, so an exposure can never be
        attributed across blocks. It fans out to (events x source rows within the block)
        before the group_by collapses it; that is the same accepted quadratic shape as
        sub-analysis A's pairing, bounded here by one patient's charting.
        """
        cols = [f"{prefix}_{h}h" for h in LOOKBACK_HOURS]
        if source is None:
            return events.select(
                "index_paralytic_id",
                *[pl.lit(None, dtype=pl.Boolean).alias(c) for c in cols],
            )
        return (
            events.select("index_paralytic_id", "encounter_block", "t_dttm")
            .join(source.select("encounter_block", dttm_col), on="encounter_block", how="left")
            .group_by("index_paralytic_id")
            .agg(
                *[
                    in_lookback("t_dttm", dttm_col, h).any().alias(f"{prefix}_{h}h")
                    for h in LOOKBACK_HOURS
                ]
            )
            # `.any()` over an all-null group is false in polars, which is the correct
            # reading here: the table exists, this patient has no row in it, so this
            # patient had no exposure. That is a measurement, unlike the absent-table
            # case above.
            .with_columns([pl.col(c).fill_null(False) for c in cols])
        )

    return exposure_flags, load_optional
```

- [ ] **Step 2: Load the three life-support sources**

```python
@app.cell
def _(
    CrrtTherapy,
    DATA_DIR,
    FILETYPE,
    MedicationAdminContinuous,
    Position,
    TIMEZONE,
    VASOPRESSORS,
    bridge,
    bridge_hosp_ids,
    load_optional,
    pl,
    to_site_naive,
):
    def _attach(df_pd, dttm_col):
        """Naive-ify the timestamp, lower-case nothing, and map to encounter_block."""
        df_pd = df_pd.copy()
        df_pd[dttm_col] = to_site_naive(df_pd[dttm_col])
        return pl.from_pandas(df_pd).join(
            bridge.select("hospitalization_id", "encounter_block"),
            on="hospitalization_id",
            how="inner",
        )

    print("optional life-support tables:")

    _vaso_pd = load_optional(
        MedicationAdminContinuous,
        "medication_admin_continuous",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "admin_dttm", "med_category"],
        # P20: casing variants enumerated at the from_file boundary.
        filters={
            "hospitalization_id": bridge_hosp_ids,
            "med_category": VASOPRESSORS + [v.title() for v in VASOPRESSORS] + [v.upper() for v in VASOPRESSORS],
        },
    )
    vasopressor = _attach(_vaso_pd, "admin_dttm") if _vaso_pd is not None else None

    _crrt_pd = load_optional(
        CrrtTherapy,
        "crrt_therapy",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm"],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    # P33 as the study lead specified it: presence of ANY charted CRRT record in the
    # window is the exposure. No filter on modality or on a dose being non-zero.
    crrt = _attach(_crrt_pd, "recorded_dttm") if _crrt_pd is not None else None

    _POSITION_VARIANTS = ["prone", "Prone", "PRONE"]
    _pos_pd = load_optional(
        Position,
        "position",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm", "position_category"],
        filters={
            "hospitalization_id": bridge_hosp_ids,
            "position_category": _POSITION_VARIANTS,
        },
    )
    prone = _attach(_pos_pd, "recorded_dttm") if _pos_pd is not None else None

    return crrt, prone, vasopressor
```

- [ ] **Step 3: Build the exposure frame**

```python
@app.cell
def _(crrt, exposure_flags, prone, spine_resolved, vasopressor):
    _events = spine_resolved.select("index_paralytic_id", "encounter_block", "t_dttm")

    exposures = (
        exposure_flags(_events, vasopressor, "admin_dttm", "vasopressor")
        .join(exposure_flags(_events, crrt, "recorded_dttm", "crrt"), on="index_paralytic_id")
        .join(exposure_flags(_events, prone, "recorded_dttm", "prone"), on="index_paralytic_id")
    )

    assert exposures.height == spine_resolved.height, "exposure join changed the row count"

    for _c in sorted(c for c in exposures.columns if c != "index_paralytic_id"):
        _col = exposures.get_column(_c)
        if _col.null_count() == exposures.height:
            print(f"  {_c:22s} table absent -- all null")
        else:
            print(f"  {_c:22s} {_col.sum():,} of {exposures.height:,}")
    return (exposures,)
```

- [ ] **Step 4: Run the notebook end-to-end**

Run: `uv run python code/04_covariates.py`
Expected: runs to completion. Every optional table either prints a row count or `NOT AVAILABLE at this site`. At MIMIC, `medication_admin_continuous` should load; `position` may not.

- [ ] **Step 5: Commit**

```bash
git add code/04_covariates.py
git commit -m "feat(04): life-support exposure in 1h, 6h and 24h look-backs

Presence tests only -- P32 lets continuous medications supply a flag and nothing
else. An absent optional table yields null columns, never false: a false is
indistinguishable from a clinical zero, and a null is not."
```

---

### Task 4: Physiology, CCI, and writing the frame

**Files:**
- Modify: `code/04_covariates.py` (append cells)

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `output/intermediate_phi/index_covariates.parquet`; `output/final_no_phi/covariate_coverage.csv` (columns `source · required · available · n_rows · n_blocks_with_rows · pct_blocks_covered`).

- [ ] **Step 1: Add the vitals cell**

```python
@app.cell
def _(mo):
    mo.md(
        """
        ## Physiology and comorbidity

        Worst value in each look-back window — lowest SBP, highest HR, lowest SpO₂ — which
        is what makes "was this a crashing patient" answerable. Weight is the most recent
        value at or before `t₀` with no look-back limit: a weight recorded on admission is
        still the patient's weight a week later, and bounding it would null out most of the
        cohort for no gain (spec §3.2).

        CCI comes from clifpy, computed on the hospitalization containing `t₀`.
        """
    )
    return


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    LOOKBACK_HOURS,
    TIMEZONE,
    Vitals,
    bridge,
    bridge_hosp_ids,
    in_lookback,
    load_optional,
    pl,
    spine_resolved,
    to_site_naive,
):
    _VITAL_SPECS = [
        ("sbp", "lowest", "sbp"),
        ("heart_rate", "highest", "hr"),
        ("spo2", "lowest", "spo2"),
    ]
    _VITAL_CATEGORIES = [c for c, _, _ in _VITAL_SPECS] + ["weight_kg"]

    print("optional physiology table:")
    _vit_pd = load_optional(
        Vitals,
        "vitals",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm", "vital_category", "vital_value"],
        filters={
            "hospitalization_id": bridge_hosp_ids,
            "vital_category": _VITAL_CATEGORIES
            + [v.upper() for v in _VITAL_CATEGORIES]
            + [v.title() for v in _VITAL_CATEGORIES],
        },
    )

    _events = spine_resolved.select("index_paralytic_id", "encounter_block", "t_dttm")
    # Bound unconditionally: the coverage cell consumes `vitals` whether or not the
    # table loaded, and a name bound only inside the else branch is a NameError at
    # exactly the sites this degradation path exists for.
    vitals = None
    _physio_cols = [
        f"{direction}_{short}_{h}h"
        for _, direction, short in _VITAL_SPECS
        for h in LOOKBACK_HOURS
    ] + ["weight_kg"]

    if _vit_pd is None:
        physiology = _events.select(
            "index_paralytic_id",
            *[pl.lit(None, dtype=pl.Float64).alias(c) for c in _physio_cols],
        )
    else:
        _vit_pd["recorded_dttm"] = to_site_naive(_vit_pd["recorded_dttm"])
        vitals = (
            pl.from_pandas(_vit_pd)
            .with_columns(pl.col("vital_category").str.to_lowercase())
            .join(
                bridge.select("hospitalization_id", "encounter_block"),
                on="hospitalization_id",
                how="inner",
            )
        )

        _joined = _events.join(
            vitals.select("encounter_block", "recorded_dttm", "vital_category", "vital_value"),
            on="encounter_block",
            how="left",
        )

        _aggs = []
        for _cat, _direction, _short in _VITAL_SPECS:
            for _h in LOOKBACK_HOURS:
                _in = in_lookback("t_dttm", "recorded_dttm", _h) & (
                    pl.col("vital_category") == _cat
                )
                _value = pl.when(_in).then(pl.col("vital_value")).otherwise(None)
                _reduced = _value.min() if _direction == "lowest" else _value.max()
                _aggs.append(_reduced.alias(f"{_direction}_{_short}_{_h}h"))

        # Weight: most recent at or before t0, no look-back limit. `sort_by` then `last`
        # is the deterministic pick -- ties broken by the value itself so a re-run cannot
        # choose differently.
        _weight_mask = (pl.col("vital_category") == "weight_kg") & (
            pl.col("recorded_dttm") <= pl.col("t_dttm")
        )
        _aggs.append(
            pl.when(_weight_mask)
            .then(pl.col("vital_value"))
            .otherwise(None)
            .sort_by(
                pl.when(_weight_mask).then(pl.col("recorded_dttm")).otherwise(None),
                pl.when(_weight_mask).then(pl.col("vital_value")).otherwise(None),
                nulls_last=False,
            )
            .last()
            .alias("weight_kg")
        )

        physiology = _joined.group_by("index_paralytic_id").agg(*_aggs)

    assert physiology.height == spine_resolved.height, "physiology join changed the row count"
    for _c in _physio_cols:
        _col = physiology.get_column(_c)
        print(f"  {_c:22s} {physiology.height - _col.null_count():,} non-null")
    return physiology, vitals
```

- [ ] **Step 2: Add the CCI cell**

```python
@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    HospitalDiagnosis,
    TIMEZONE,
    bridge,
    bridge_hosp_ids,
    load_optional,
    pl,
    spine_resolved,
):
    print("optional comorbidity table:")
    _diag_pd = load_optional(
        HospitalDiagnosis,
        "hospital_diagnosis",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "diagnosis_code", "diagnosis_code_format"],
        filters={"hospitalization_id": bridge_hosp_ids},
    )

    # Bound unconditionally for the same reason `vitals` is: the coverage cell
    # consumes it on both paths.
    diagnosis = None

    if _diag_pd is None:
        comorbidity = spine_resolved.select(
            "index_paralytic_id", pl.lit(None, dtype=pl.Int32).alias("cci")
        )
    else:
        from clifpy.utils.comorbidity import calculate_cci

        _cci_pd = calculate_cci(_diag_pd)
        _cci_col = [c for c in _cci_pd.columns if c.lower() in ("cci_score", "cci")]
        assert _cci_col, (
            f"clifpy's CCI output has no recognisable score column: {list(_cci_pd.columns)}"
        )
        _cci = pl.from_pandas(_cci_pd).select(
            "hospitalization_id", pl.col(_cci_col[0]).cast(pl.Int32).alias("cci")
        )
        # Joined on the hospitalization containing t0 (spec §3.2), which spine_resolved
        # already carries -- not on the block, whose four member stays can have four
        # different diagnosis lists.
        comorbidity = spine_resolved.select(
            "index_paralytic_id", "hospitalization_id"
        ).join(_cci, on="hospitalization_id", how="left").select("index_paralytic_id", "cci")

        diagnosis = pl.from_pandas(_diag_pd).join(
            bridge.select("hospitalization_id", "encounter_block"),
            on="hospitalization_id",
            how="inner",
        )

    assert comorbidity.height == spine_resolved.height, "CCI join changed the row count"
    print(f"  cci non-null : {comorbidity.height - comorbidity.get_column('cci').null_count():,}")
    return comorbidity, diagnosis
```

- [ ] **Step 3: Assemble, assert, and write the frame**

```python
@app.cell
def _(PHI_DIR, comorbidity, exposures, physiology, pl, spine_resolved):
    index_covariates = (
        spine_resolved.join(exposures, on="index_paralytic_id", how="left")
        .join(physiology, on="index_paralytic_id", how="left")
        .join(comorbidity, on="index_paralytic_id", how="left")
        .sort(["encounter_block", "p_num", "index_paralytic_id"])
    )

    assert index_covariates.height == spine_resolved.height, (
        "assembling the covariate frame changed the row count"
    )
    assert index_covariates.get_column("index_paralytic_id").is_unique().all()

    # Block-level columns must be constant within a block -- pinned by
    # tests/test_block_row_contract.py, asserted here so a bad run fails at the write
    # rather than at the next notebook's aggregation.
    _block_cols = [
        "n_index_in_block",
        "los_hospital_days",
        "los_icu_days",
        "hospital_mortality",
        "icu_mortality",
    ]
    _varying = (
        index_covariates.group_by("encounter_block")
        .agg([pl.col(c).n_unique().alias(c) for c in _block_cols])
        .filter(pl.any_horizontal([pl.col(c) > 1 for c in _block_cols]))
    )
    assert _varying.height == 0, (
        f"{_varying.height:,} blocks have a block-level column varying within the block"
    )

    PHI_DIR.mkdir(parents=True, exist_ok=True)
    index_covariates.write_parquet(PHI_DIR / "index_covariates.parquet")

    print(f"index_covariates : {index_covariates.height:,} rows, "
          f"{len(index_covariates.columns)} columns -> {PHI_DIR}")
    print(f"  blocks         : {index_covariates.get_column('encounter_block').n_unique():,}")
    print(f"  p_num == 1     : {index_covariates.filter(pl.col('p_num') == 1).height:,}")
    return (index_covariates,)
```

- [ ] **Step 4: Publish the coverage table**

```python
@app.cell
def _(
    SHARE_DIR,
    SITE,
    crrt,
    diagnosis,
    index_covariates,
    pl,
    prone,
    publish,
    vasopressor,
    vitals,
):
    _n_blocks = index_covariates.get_column("encounter_block").n_unique()

    def _cov(name, required, frame):
        if frame is None:
            return {
                "source": name,
                "required": required,
                "available": False,
                "n_rows": 0,
                "n_blocks_with_rows": 0,
                "pct_blocks_covered": 0.0,
            }
        _b = frame.get_column("encounter_block").n_unique()
        return {
            "source": name,
            "required": required,
            "available": True,
            "n_rows": frame.height,
            "n_blocks_with_rows": _b,
            "pct_blocks_covered": round(100.0 * _b / _n_blocks, 2),
        }

    covariate_coverage = pl.DataFrame(
        [
            _cov("medication_admin_continuous", False, vasopressor),
            _cov("crrt_therapy", False, crrt),
            _cov("position", False, prone),
            _cov("vitals", False, vitals),
            _cov("hospital_diagnosis", False, diagnosis),
        ]
    ).with_columns(pl.lit(SITE).alias("site_name")).sort("source")

    publish(covariate_coverage, SHARE_DIR / "covariate_coverage.csv", "covariate_coverage")
    return (covariate_coverage,)


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 5: Run the notebook and the contract test**

Run: `uv run python code/04_covariates.py && uv run pytest tests/test_block_row_contract.py -v`
Expected: notebook completes; `covariate_coverage.csv` written; all 5 contract tests now PASS (they no longer skip).

- [ ] **Step 6: Commit**

```bash
git add code/04_covariates.py
git commit -m "feat(04): physiology, CCI, and the analytic frame

index_covariates.parquet is the one row every downstream notebook aggregates.
Block-level columns are asserted constant within their block at the write, so a
frame computed per event instead of per block fails here rather than silently
weighting long-stay patients in the index-level table."
```

---

### Task 5: `05_table_one.py` — both Table 1s

**Files:**
- Create: `code/05_table_one.py`

**Interfaces:**
- Consumes: `output/intermediate_phi/index_covariates.parquet` from Task 4.
- Produces: `output/final_no_phi/table1_by_agent_block.csv`, `table1_by_agent_index.csv`. Both long: `statistic · rule · unit · <one column per stratum> · overall · site_name`. Strata columns are `rocuronium`, `succinylcholine`, `vecuronium`, `combination` — emitted even when structurally empty.

- [ ] **Step 1: Create the notebook through the spec cell**

```python
import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import matplotlib.pyplot as plt
    import polars as pl

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return Path, json, mo, pl, plt, publish


@app.cell
def _(mo):
    mo.md(
        """
        # 05 — Table 1

        Published twice from one frame (P34): once per **encounter block**, at its
        `p_num = 1` event, and once per **index paralytic event**. Identical row
        inventory, different unit, so the two are directly comparable and the difference
        between them measures what re-paralysis contributes.

        Every row carries a `rule` and a `unit` (P35). These CSVs are merged across
        consortium sites and pasted into manuscripts, arriving detached from the notebook
        that produced them — every other artifact in this pipeline depends on
        `pipeline_flow.md` being read alongside it, and this is the first that carries its
        own definitions. The `unit` column also defuses the trap P34 creates: block-level
        outcomes repeat down the index-level table, so `los_hospital_days` there states
        "block-level value, repeated per index event" and nobody averages it by accident.

        Continuous variables publish **mean, SD, median, Q1 and Q3** (P36) — mean beside
        median is how a reader detects skew without a figure, and LOS, CCI and the index
        count are all heavily right-skewed. Categoricals publish `n` **and** `pct`: a
        percentage without its numerator cannot be pooled across sites.

        This notebook opens no CLIF table.
        """
    )
    return


@app.cell
def _(Path, json):
    _config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(_config_path, "r") as _f:
        config = json.load(_f)

    SITE = config["site_name"]
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    FIG_DIR = SHARE_DIR / "figures"
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # P34/§6. Every stratum column is emitted even when structurally empty --
    # succinylcholine is absent from MIMIC entirely, and a column present at one site and
    # missing at another is what breaks a multi-site merge. This is P21's published-zero
    # convention applied to columns.
    STRATA = ["rocuronium", "succinylcholine", "vecuronium", "combination"]

    LOOKBACK_HOURS = [1, 6, 24]

    print(f"site   : {SITE}")
    print(f"strata : {' | '.join(STRATA)}")
    return FIG_DIR, LOOKBACK_HOURS, PHI_DIR, SHARE_DIR, SITE, STRATA, config
```

- [ ] **Step 2: Add the statistic builders**

```python
@app.cell
def _(pl):
    def continuous_rows(df, column, rule, unit):
        """P36's five statistics for one continuous column, as (statistic, rule, unit, value).

        Returns five records. Nulls are excluded from every statistic -- a missing SBP is
        not a low SBP -- and `n_nonnull` is emitted as a sixth so the reader knows the
        denominator each statistic was computed on. That denominator differs per variable
        (a site without `position` has null prone flags but real ages) and a Table 1 that
        hides it invites pooling statistics computed on different populations.
        """
        s = df.get_column(column).drop_nulls()
        if s.len() == 0:
            stats = {"mean": None, "sd": None, "median": None, "q1": None, "q3": None}
        else:
            stats = {
                "mean": s.mean(),
                "sd": s.std(),
                "median": s.median(),
                "q1": s.quantile(0.25),
                "q3": s.quantile(0.75),
            }
        rows = [
            {
                "statistic": f"{column}_{k}",
                "rule": rule,
                "unit": unit,
                "value": None if v is None else round(float(v), 3),
            }
            for k, v in stats.items()
        ]
        rows.append(
            {
                "statistic": f"{column}_n_nonnull",
                "rule": f"rows with a non-null {column}",
                "unit": unit,
                "value": float(s.len()),
            }
        )
        return rows

    def binary_rows(df, column, rule, unit):
        """`n` and `pct` for one boolean column, plus its non-null denominator.

        An all-null column (its source table absent at this site) yields n = null and
        pct = null, NOT zero. Publishing 0% for "this site does not chart CRRT" would be
        a clinical claim the data does not support (spec §4).
        """
        s = df.get_column(column)
        nonnull = s.drop_nulls()
        if nonnull.len() == 0:
            n, pct = None, None
        else:
            n = float(nonnull.sum())
            pct = round(100.0 * n / nonnull.len(), 2)
        return [
            {"statistic": f"{column}_n", "rule": rule, "unit": unit, "value": n},
            {"statistic": f"{column}_pct", "rule": rule, "unit": unit, "value": pct},
            {
                "statistic": f"{column}_n_nonnull",
                "rule": f"rows with a non-null {column}",
                "unit": unit,
                "value": float(nonnull.len()),
            },
        ]

    def categorical_rows(df, column, rule, unit, levels):
        """`n` and `pct` per level, over a FIXED level list.

        The level list is fixed rather than observed so a category absent at this site is
        published as an explicit zero instead of a missing row -- the same principle as
        `index_per_block.csv`'s contiguous n_index grid and Figure A.1's baseline
        diamonds. A missing row and a zero row are indistinguishable to a reader; only
        one of them is a measurement.
        """
        total = df.get_column(column).drop_nulls().len()
        counts = dict(
            df.group_by(column).agg(pl.len().alias("n")).drop_nulls(column).iter_rows()
        )
        rows = []
        for level in levels:
            n = float(counts.get(level, 0))
            rows.append({"statistic": f"{column}_{level}_n", "rule": rule, "unit": unit, "value": n})
            rows.append(
                {
                    "statistic": f"{column}_{level}_pct",
                    "rule": rule,
                    "unit": unit,
                    "value": round(100.0 * n / total, 2) if total else None,
                }
            )
        rows.append(
            {
                "statistic": f"{column}_missing_n",
                "rule": f"rows with a null {column}",
                "unit": unit,
                "value": float(df.get_column(column).null_count()),
            }
        )
        return rows

    return binary_rows, categorical_rows, continuous_rows
```

- [ ] **Step 3: Add the row inventory**

```python
@app.cell
def _(LOOKBACK_HOURS, binary_rows, categorical_rows, continuous_rows, pl):
    EVENT = "index event"
    BLOCK = "encounter block; repeated for each index event in the index-level table"

    def table1_rows(df, race_levels, ethnicity_levels, sex_levels, discharge_levels):
        """The full row inventory (spec §6), evaluated over whichever unit `df` carries."""
        rows = []

        rows.append({"statistic": "n_rows", "rule": "rows in this table's unit", "unit": EVENT, "value": float(df.height)})
        rows.append({"statistic": "n_blocks", "rule": "distinct encounter_block", "unit": BLOCK, "value": float(df.get_column("encounter_block").n_unique())})
        rows.append({"statistic": "n_patients", "rule": "distinct patient_id", "unit": BLOCK, "value": float(df.get_column("patient_id").n_unique())})

        rows += continuous_rows(df, "age_at_admission", "hospitalization containing t0", EVENT)
        rows += categorical_rows(df, "sex_category", "patient.sex_category, lower-cased", EVENT, sex_levels)
        rows += categorical_rows(df, "race_category", "patient.race_category, lower-cased, raw mCIDE level", EVENT, race_levels)
        rows += categorical_rows(df, "ethnicity_category", "patient.ethnicity_category, lower-cased", EVENT, ethnicity_levels)

        rows += continuous_rows(df, "cci", "Charlson via clifpy on the hospitalization containing t0", EVENT)

        for _short, _dir in (("sbp", "lowest"), ("hr", "highest"), ("spo2", "lowest")):
            for _h in LOOKBACK_HOURS:
                _c = f"{_dir}_{_short}_{_h}h"
                rows += continuous_rows(df, _c, f"{_dir} vitals {_short} in [t0-{_h}h, t0]", EVENT)
        rows += continuous_rows(df, "weight_kg", "most recent vitals weight at or before t0", EVENT)

        for _prefix, _rule in (
            ("vasopressor", "any medication_admin_continuous vasopressor row in [t0-{h}h, t0]"),
            ("crrt", "any crrt_therapy recorded_dttm in [t0-{h}h, t0]"),
            ("prone", "any position prone row in [t0-{h}h, t0]"),
        ):
            for _h in LOOKBACK_HOURS:
                rows += binary_rows(df, f"{_prefix}_{_h}h", _rule.format(h=_h), EVENT)

        rows += binary_rows(df, "imv_transition", "device change onto imv within +/-60 min of t0 (sub-analysis D)", EVENT)
        rows += binary_rows(df, "any_sedative", "sedative charted within +/-60 min of t0 (sub-analysis E)", EVENT)
        rows += categorical_rows(df, "no_transition_reason", "why sub-analysis D found no transition", EVENT, ["already_on_imv", "no_transition_in_window", "no_device_record"])
        rows += categorical_rows(df, "location_at_index", "adt row where in_dttm <= t0 < out_dttm", EVENT, ["ed", "icu", "other", "unknown"])
        rows += categorical_rows(df, "evidence_tier", "1 index only, 2 +imv transition, 3 +imv +sedation (P31)", EVENT, [1, 2, 3])

        rows += binary_rows(df, "hospital_mortality", "death_dttm inside a member stay, or discharge_category expired", BLOCK)
        rows += binary_rows(df, "icu_mortality", "death_dttm inside an adt icu interval; independent of hospital_mortality (P37 amended)", BLOCK)
        rows += categorical_rows(df, "discharge_category", "hospitalization containing t0", EVENT, discharge_levels)
        rows += continuous_rows(df, "los_hospital_days", "sum of member hospitalization LOS in the block (P38)", BLOCK)
        rows += continuous_rows(df, "los_icu_days", "sum of adt icu intervals in the block", BLOCK)
        rows += continuous_rows(df, "n_index_in_block", "index paralytics in the block", BLOCK)

        return rows

    return BLOCK, EVENT, table1_rows
```

- [ ] **Step 4: Add the assembly cell**

```python
@app.cell
def _(PHI_DIR, SHARE_DIR, SITE, STRATA, pl, publish, table1_rows):
    index_covariates = pl.read_parquet(PHI_DIR / "index_covariates.parquet")

    # Level lists are taken from the WHOLE frame, not per stratum, so every stratum
    # column reports the same rows in the same order and the CSV can be read across.
    _race = sorted(index_covariates.get_column("race_category").drop_nulls().unique().to_list())
    _eth = sorted(index_covariates.get_column("ethnicity_category").drop_nulls().unique().to_list())
    _sex = sorted(index_covariates.get_column("sex_category").drop_nulls().unique().to_list())
    _disch = sorted(
        index_covariates.get_column("discharge_category").drop_nulls().unique().to_list()
    )

    def build_table1(df, label):
        _overall = pl.DataFrame(table1_rows(df, _race, _eth, _sex, _disch)).rename(
            {"value": "overall"}
        )
        out = _overall
        for _stratum in STRATA:
            _sub = df.filter(pl.col("agent_stratum") == _stratum)
            _col = pl.DataFrame(table1_rows(_sub, _race, _eth, _sex, _disch)).select(
                "statistic", pl.col("value").alias(_stratum)
            )
            assert _col.height == out.height, (
                f"stratum {_stratum} produced {_col.height} rows against the overall "
                f"column's {out.height} -- the row inventory is not stratum-invariant"
            )
            out = out.join(_col, on="statistic", how="left")
        out = (
            out.with_columns(pl.lit(SITE).alias("site_name"))
            .select("statistic", "rule", "unit", *STRATA, "overall", "site_name")
            # Full tiebreak so the file is byte-identical across runs (commit 6c70808).
            .sort(["statistic", "unit"])
        )
        publish(out, SHARE_DIR / f"table1_by_agent_{label}.csv", f"table1_by_agent_{label}")
        return out

    table1_index = build_table1(index_covariates, "index")
    table1_block = build_table1(index_covariates.filter(pl.col("p_num") == 1), "block")

    assert table1_block.height == table1_index.height, (
        "the two Table 1s have different row inventories and are not comparable"
    )
    print(f"block table n_rows : {table1_block.filter(pl.col('statistic') == 'n_rows')['overall'][0]:,.0f}")
    print(f"index table n_rows : {table1_index.filter(pl.col('statistic') == 'n_rows')['overall'][0]:,.0f}")
    return build_table1, index_covariates, table1_block, table1_index
```

- [ ] **Step 5: Run and inspect**

Run: `uv run python code/05_table_one.py`
Expected: both CSVs written, `publish()` accepts them (no identifier and no datetime column), block table reports `n_rows = 1547` and index table `n_rows = 2117`.

- [ ] **Step 6: Commit**

```bash
git add code/05_table_one.py
git commit -m "feat(05): Table 1 by encounter block and by index event

One row inventory evaluated over two units (P34), each row carrying its own rule
and unit so the CSV survives leaving the repo. Every stratum column is emitted
even when structurally empty -- succinylcholine is absent at MIMIC, and a column
present at one site and missing at another breaks a multi-site merge."
```

---

### Task 6: `05` figures — life support by window, and source coverage

**Files:**
- Modify: `code/05_table_one.py` (append cells)

**Interfaces:**
- Consumes: `table1_block`, `SHARE_DIR`, `FIG_DIR`, `LOOKBACK_HOURS`, `STRATA`.
- Produces: `figures/T1_life_support_by_window.png`, `figures/T2_source_coverage.png`.

- [ ] **Step 1: Add the mark_zero helper and T.1**

Both figures are drawn from published CSVs and never from an in-memory frame, following `02` and `03`.

```python
@app.cell
def _(plt):
    def mark_zero(ax, x, color):
        """A published, exactly-zero value: a diamond centered on the baseline.

        Placed at y=0 in DATA coordinates, so it has zero data-height by construction and
        can never equal or exceed a bar of any positive height. `clip_on=False` keeps its
        lower half drawn. Copied from `02`/`03` rather than shared -- this project
        duplicates figure helpers deliberately (spec §4).
        """
        ax.plot(
            [x], [0], marker="D", markersize=7, color=color,
            linestyle="None", zorder=5, clip_on=False,
        )

    return (mark_zero,)


@app.cell
def _(FIG_DIR, LOOKBACK_HOURS, SHARE_DIR, mark_zero, pl, plt):
    # Fixed categorical colours, never cycled: one colour per life-support modality
    # wherever it appears.
    _COLORS = {"vasopressor": "#2a78d6", "crrt": "#eb6834", "prone": "#1baf7a"}

    _t1 = pl.read_csv(SHARE_DIR / "table1_by_agent_block.csv")

    _fig, _ax = plt.subplots(figsize=(10, 6))
    _width = 0.26

    for _i, (_modality, _color) in enumerate(_COLORS.items()):
        for _j, _h in enumerate(LOOKBACK_HOURS):
            _row = _t1.filter(pl.col("statistic") == f"{_modality}_{_h}h_pct")
            _v = _row["overall"][0] if _row.height else None
            _x = _j + (_i - 1) * _width
            if _v is None:
                # Source table absent at this site: null, not zero. Drawn as an open
                # marker ABOVE the baseline so it cannot be confused with the filled
                # diamond that means "measured, exactly 0".
                _ax.plot([_x], [0], marker="o", markersize=7, markerfacecolor="none",
                         color=_color, linestyle="None", clip_on=False)
            elif _v > 0:
                _ax.bar([_x], [_v], width=_width, color=_color)
            else:
                mark_zero(_ax, _x, _color)

    _ax.set_xticks(list(range(len(LOOKBACK_HOURS))))
    _ax.set_xticklabels([f"{_h} h before t0" for _h in LOOKBACK_HOURS])
    _ax.set_ylabel("% of encounter blocks")
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)

    _handles = [_ax.plot([], [], color=_c, lw=6, label=_m)[0] for _m, _c in _COLORS.items()]
    _handles.append(_ax.plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                             label="published zero (measured, exactly 0)")[0])
    _handles.append(_ax.plot([], [], marker="o", markersize=7, markerfacecolor="none",
                             color="0.3", linestyle="None",
                             label="source table absent (not measured)")[0])
    _ax.legend(handles=_handles, loc="upper left", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "T.1 — life support before the index paralytic, encounter blocks\n"
        "the 1 h to 24 h ramp is where 'already shocked' separates from 'crashed at intubation'"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "T1_life_support_by_window.png", dpi=150)
    plt.close(_fig)
    print(f"T1_life_support_by_window.png -> {FIG_DIR}")
    return
```

- [ ] **Step 2: Add T.2**

```python
@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _cov = pl.read_csv(SHARE_DIR / "covariate_coverage.csv").sort("source")

    _fig, _ax = plt.subplots(figsize=(9, 4.5))
    for _i, _row in enumerate(_cov.iter_rows(named=True)):
        _color = "#1baf7a" if _row["available"] else "#b0aca2"
        _ax.barh([_i], [_row["pct_blocks_covered"]], color=_color, height=0.6)
        if not _row["available"]:
            _ax.text(1, _i, "table absent at this site", va="center", fontsize=8, color="#0b0b0b")

    _ax.set_yticks(list(range(_cov.height)))
    _ax.set_yticklabels(_cov.get_column("source").to_list(), fontsize=9)
    _ax.set_xlabel("% of encounter blocks with at least one row in the source table")
    _ax.set_xlim(0, 100)
    _ax.invert_yaxis()
    _ax.set_axisbelow(True)
    _ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
    _ax.set_title(
        "T.2 — source-table coverage\n"
        "a covariate's zero means nothing until this figure says the table was there"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "T2_source_coverage.png", dpi=150)
    plt.close(_fig)
    print(f"T2_source_coverage.png -> {FIG_DIR}")
    return


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 3: Run and eyeball both figures**

Run: `uv run python code/05_table_one.py`
Expected: both PNGs written to `output/final_no_phi/figures/`. Open them. T.1 must show open circles (not bars, not diamonds) for any modality whose table is absent.

- [ ] **Step 4: Commit**

```bash
git add code/05_table_one.py
git commit -m "feat(05): figures T.1 life support by window and T.2 source coverage

T.1 distinguishes three states a bar cannot: a positive percentage, a measured
zero (baseline diamond) and an absent source table (open marker above the
baseline). Conflating the last two is what makes a thin extract look like a
clinical finding."
```

---

### Task 7: `06_reference_cpt.py` — the cascade

**Files:**
- Create: `code/06_reference_cpt.py`
- Create: `tests/test_cpt_bridge.py`

**Interfaces:**
- Consumes: `output/intermediate_phi/index_covariates.parquet`, `output/intermediate_phi/cohort_index.parquet`.
- Produces: `cpt_block_flag(procedures, bridge) -> pl.DataFrame` (`encounter_block`, `has_cpt`, `n_cpt_codes`, `first_cpt_date`, `last_cpt_date`); `cpt_cascade.csv`, `cpt_cascade_qc.csv`, `cpt_offset_distribution.csv`.

- [ ] **Step 1: Write the failing bridge test**

```python
"""Pins the CPT-to-block bridge of `06_reference_cpt.py` (spec §4, P29).

CPT rows live on `hospitalization_id`; the analysis lives on `encounter_block`.
A block stitches up to 4 hospitalizations (max_hosp_per_block = 4 at MIMIC), so
"CPT present" means present on ANY member. Two things can go wrong silently:

  * a code on a hospitalization OUTSIDE the block leaking in, which would
    manufacture agreement;
  * a code on a member other than the first being missed, which would
    manufacture disagreement.

Both are checked. The bridge itself is the explode-and-drop of the 2026-08-10
spec §6.1 -- the only sanctioned place `hospitalization_id` may be named.

Run:  uv run pytest tests/test_cpt_bridge.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl

NOTEBOOK = Path(__file__).parent.parent / "code" / "06_reference_cpt.py"
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
    ns = {"pl": pl}
    ns.update(namespace or {})
    exec(compile(ast.Module(body=[found[0]], type_ignores=[]), NOTEBOOK.name, "exec"), ns)
    return ns[name]


cpt_block_flag = _load_from_notebook("cpt_block_flag")

# Block 1 stitches four hospitalizations; block 2 stitches one.
BRIDGE = pl.DataFrame(
    {
        "encounter_block": [1, 1, 1, 1, 2],
        "hospitalization_id": ["h1", "h2", "h3", "h4", "h9"],
    },
    schema={"encounter_block": pl.Int32, "hospitalization_id": pl.String},
)


def _procs(pairs):
    """pairs: list of (hospitalization_id, date)."""
    return pl.DataFrame(
        {
            "hospitalization_id": [h for h, _ in pairs],
            "procedure_date": [d for _, d in pairs],
        },
        schema={"hospitalization_id": pl.String, "procedure_date": pl.Date},
    )


D = datetime.date(2024, 5, 1)


def test_code_on_the_third_member_flags_the_block():
    got = cpt_block_flag(_procs([("h3", D)]), BRIDGE).sort("encounter_block").to_dicts()
    by_block = {r["encounter_block"]: r for r in got}
    assert by_block[1]["has_cpt"] is True
    assert by_block[1]["n_cpt_codes"] == 1


def test_code_on_a_hospitalization_outside_the_block_does_not_leak():
    """h9 belongs to block 2; block 1 must stay negative."""
    got = cpt_block_flag(_procs([("h9", D)]), BRIDGE).sort("encounter_block").to_dicts()
    by_block = {r["encounter_block"]: r for r in got}
    assert by_block[1]["has_cpt"] is False
    assert by_block[1]["n_cpt_codes"] == 0
    assert by_block[2]["has_cpt"] is True


def test_code_on_an_unknown_hospitalization_is_dropped():
    """A procedure row for a hospitalization no block claims contributes nothing."""
    got = cpt_block_flag(_procs([("h_unknown", D)]), BRIDGE).sort("encounter_block").to_dicts()
    assert all(r["has_cpt"] is False for r in got)


def test_multiple_codes_across_members_are_counted_once_per_row():
    got = cpt_block_flag(
        _procs([("h1", D), ("h3", D + datetime.timedelta(days=2))]), BRIDGE
    ).sort("encounter_block").to_dicts()
    by_block = {r["encounter_block"]: r for r in got}
    assert by_block[1]["n_cpt_codes"] == 2
    assert by_block[1]["first_cpt_date"] == D


def test_every_block_in_the_bridge_gets_a_row():
    """A block with no procedure data at all is a published false, not a missing row."""
    got = cpt_block_flag(_procs([]), BRIDGE)
    assert sorted(got.get_column("encounter_block").to_list()) == [1, 2]
    assert got.get_column("has_cpt").to_list() == [False, False]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cpt_bridge.py -v`
Expected: FAIL — `FileNotFoundError` on `code/06_reference_cpt.py`.

- [ ] **Step 3: Create the notebook**

```python
import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import matplotlib.pyplot as plt
    import polars as pl

    from clifpy.tables import PatientProcedures

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return Path, PatientProcedures, json, mo, pl, plt, publish


@app.cell
def _(mo):
    mo.md(
        r"""
        # 06 — the CPT comparator

        For each encounter block with an index paralytic: was a CPT `31500` billed anywhere
        in that block, and does agreement strengthen as the paralytic evidence strengthens?

        **CPT is a comparator, not a reference standard (P26).** An absent code means "no
        IMV was performed, or it was not charted", and the two are indistinguishable in the
        data. No sensitivity, no specificity, no NPV, no kappa is published — the
        denominator is blocks that already have an index paralytic (P27), so the
        false-negative cell is excluded by construction and every statistic needing it
        would be computed on a cell that cannot be observed.

        **The comparison is at block level with no time alignment (P29).** A block flagged
        CPT-positive may have been billed for an intubation days from the index paralytic.
        `cpt_offset_distribution.csv` measures exactly that rather than assuming it away —
        it is the only instrument that recovers what the block-level flag gives up.

        Design: `docs/superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md` §5
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

    CPT_INTUBATION = "31500"

    # P20 casing variants at the from_file boundary. The mCIDE value is `cpt`; sites
    # write it several ways and a filter matching zero rows looks exactly like a site
    # that bills no intubations.
    CPT_FORMAT_VARIANTS = ["cpt", "CPT", "Cpt", "cpt4", "CPT4"]

    # P30. Day bins, signed: `procedure_billed_dttm` is trusted to the day and not to the
    # minute, which is why this is a day distribution and not a minute offset.
    OFFSET_BIN_BREAKS = [-30, -7, -1, 0, 1, 7, 30]
    OFFSET_BIN_LABELS = [
        "<= -30 d", "(-30,-7] d", "(-7,-1] d", "(-1,0] d",
        "(0,1] d", "(1,7] d", "(7,30] d", "> 30 d",
    ]

    TIER_LABELS = {1: "index only", 2: "index + imv transition", 3: "index + imv + sedation"}

    print(f"site : {SITE}")
    print(f"cpt  : {CPT_INTUBATION}  formats {CPT_FORMAT_VARIANTS}")
    return (
        CPT_FORMAT_VARIANTS,
        CPT_INTUBATION,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        OFFSET_BIN_BREAKS,
        OFFSET_BIN_LABELS,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        TIER_LABELS,
        TIMEZONE,
        config,
    )


@app.cell
def _(TIMEZONE, pl):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Defined locally (spec §4).
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)
```

- [ ] **Step 4: Add `cpt_block_flag` and the load cell**

```python
@app.cell
def _(pl):
    def cpt_block_flag(procedures, bridge):
        """One row per encounter_block: does any member hospitalization carry the code?

        `procedures` carries hospitalization_id and procedure_date (already filtered to
        CPT 31500). `bridge` carries encounter_block and hospitalization_id, one row per
        hospitalization.

        The join is INNER on the bridge side, so a procedure row for a hospitalization no
        block claims is dropped rather than creating a phantom block -- the explode-and-
        drop of the 2026-08-10 spec §6.1.

        Every block in the bridge gets a row, including blocks with no procedure data at
        all: a published false, never a missing row. A missing row and a false are
        indistinguishable to a reader and only one of them is a measurement.
        """
        _hits = (
            procedures.join(bridge, on="hospitalization_id", how="inner")
            .group_by("encounter_block")
            .agg(
                pl.len().cast(pl.Int32).alias("n_cpt_codes"),
                pl.col("procedure_date").min().alias("first_cpt_date"),
                pl.col("procedure_date").max().alias("last_cpt_date"),
            )
        )
        return (
            bridge.select("encounter_block")
            .unique()
            .join(_hits, on="encounter_block", how="left")
            .with_columns(
                pl.col("n_cpt_codes").fill_null(0).cast(pl.Int32),
                (pl.col("n_cpt_codes").fill_null(0) > 0).alias("has_cpt"),
            )
            .sort("encounter_block")
        )

    return (cpt_block_flag,)


@app.cell
def _(
    CPT_FORMAT_VARIANTS,
    CPT_INTUBATION,
    DATA_DIR,
    FILETYPE,
    PHI_DIR,
    PatientProcedures,
    TIMEZONE,
    cpt_block_flag,
    pl,
    to_site_naive,
):
    index_covariates = pl.read_parquet(PHI_DIR / "index_covariates.parquet")
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

    # P27: the denominator is the blocks that HAVE an index paralytic, not the cohort.
    blocks = index_covariates.filter(pl.col("p_num") == 1)
    bridge = (
        cohort_index.filter(
            pl.col("encounter_block").is_in(blocks.get_column("encounter_block"))
        )
        .select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    assert bridge.get_column("hospitalization_id").is_unique().all(), (
        "a hospitalization_id appears in more than one encounter_block"
    )

    _hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # REQUIRED table (spec §4). Absent, this fails loudly -- a CPT comparator that
    # silently reports zero agreement because the table was missing is worse than no
    # comparator at all.
    _proc_table = PatientProcedures.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "procedure_code",
            "procedure_code_format",
            "procedure_billed_dttm",
        ],
        filters={
            "hospitalization_id": _hosp_ids,
            "procedure_code_format": CPT_FORMAT_VARIANTS,
        },
    )
    _proc_pd = _proc_table.df.copy()
    _proc_pd["procedure_billed_dttm"] = to_site_naive(_proc_pd["procedure_billed_dttm"])

    procedures_all = pl.from_pandas(_proc_pd).with_columns(
        pl.col("procedure_code").cast(pl.String).str.strip_chars()
    )
    procedures = procedures_all.filter(pl.col("procedure_code") == CPT_INTUBATION).select(
        "hospitalization_id",
        pl.col("procedure_billed_dttm").dt.date().alias("procedure_date"),
    )

    cpt_flags = cpt_block_flag(procedures, bridge)

    print(f"blocks in denominator  : {blocks.height:,}")
    print(f"procedure rows (any)   : {procedures_all.height:,}")
    print(f"procedure rows ({CPT_INTUBATION}) : {procedures.height:,}")
    print(f"blocks with a cpt code : {cpt_flags.get_column('has_cpt').sum():,}")
    return blocks, bridge, cohort_index, cpt_flags, index_covariates, procedures, procedures_all
```

- [ ] **Step 5: Run the bridge test to verify it passes**

Run: `uv run pytest tests/test_cpt_bridge.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Add the cascade, QC and offset cells**

```python
@app.cell
def _(SHARE_DIR, SITE, TIER_LABELS, blocks, cpt_flags, pl, publish):
    _joined = blocks.select("encounter_block", "evidence_tier").join(
        cpt_flags.select("encounter_block", "has_cpt"), on="encounter_block", how="left"
    )
    assert _joined.get_column("has_cpt").null_count() == 0, (
        "a block in the denominator has no CPT flag -- the bridge lost a block"
    )

    # Fixed 1..3 grid: a tier with no blocks is published as an explicit zero rather
    # than being absent from the table (P21's published-zero convention).
    cpt_cascade = (
        pl.DataFrame({"evidence_tier": [1, 2, 3]})
        .with_columns(pl.col("evidence_tier").cast(pl.Int8))
        .join(
            _joined.group_by("evidence_tier").agg(
                pl.len().cast(pl.Int32).alias("n_blocks"),
                pl.col("has_cpt").sum().cast(pl.Int32).alias("n_cpt_yes"),
            ),
            on="evidence_tier",
            how="left",
        )
        .with_columns(
            pl.col("n_blocks").fill_null(0),
            pl.col("n_cpt_yes").fill_null(0),
        )
        .with_columns(
            (pl.col("n_blocks") - pl.col("n_cpt_yes")).alias("n_cpt_no"),
            pl.when(pl.col("n_blocks") > 0)
            .then(100.0 * pl.col("n_cpt_yes") / pl.col("n_blocks"))
            .otherwise(None)
            .round(2)
            .alias("pct_coded"),
        )
        .with_columns(
            pl.col("evidence_tier").replace_strict(TIER_LABELS, default="unknown").alias("tier_label"),
            pl.lit("cpt 31500 on any member hospitalization of the block").alias("rule"),
            pl.lit(SITE).alias("site_name"),
        )
        .select("evidence_tier", "tier_label", "rule", "n_blocks", "n_cpt_yes", "n_cpt_no", "pct_coded", "site_name")
        .sort("evidence_tier")
    )

    assert cpt_cascade.get_column("n_blocks").sum() == blocks.height, (
        "the cascade's tiers do not partition the denominator"
    )

    publish(cpt_cascade, SHARE_DIR / "cpt_cascade.csv", "cpt_cascade")
    return (cpt_cascade,)


@app.cell
def _(SHARE_DIR, SITE, blocks, cpt_flags, pl, procedures_all, publish, bridge):
    # Denominator quality. A site with thin billing extracts is visible HERE rather than
    # being reported as poor agreement in the table above.
    _blocks_with_any_proc = (
        procedures_all.select("hospitalization_id")
        .unique()
        .join(bridge, on="hospitalization_id", how="inner")
        .get_column("encounter_block")
        .n_unique()
    )

    _codes = cpt_flags.get_column("n_cpt_codes")
    cpt_cascade_qc = pl.DataFrame(
        [
            {"stat": "n_blocks_denominator", "value": float(blocks.height)},
            {"stat": "n_blocks_with_any_procedure_row", "value": float(_blocks_with_any_proc)},
            {"stat": "pct_blocks_with_any_procedure_row", "value": round(100.0 * _blocks_with_any_proc / blocks.height, 2)},
            {"stat": "n_blocks_with_cpt_31500", "value": float(_codes.gt(0).sum())},
            {"stat": "max_cpt_codes_in_one_block", "value": float(_codes.max())},
            {"stat": "median_cpt_codes_where_present", "value": float(_codes.filter(_codes > 0).median() or 0)},
        ]
    ).with_columns(pl.lit(SITE).alias("site_name")).sort("stat")

    publish(cpt_cascade_qc, SHARE_DIR / "cpt_cascade_qc.csv", "cpt_cascade_qc")
    return (cpt_cascade_qc,)


@app.cell
def _(
    OFFSET_BIN_BREAKS,
    OFFSET_BIN_LABELS,
    SHARE_DIR,
    SITE,
    blocks,
    cpt_flags,
    pl,
    publish,
):
    # P30. Signed days from t0 to the NEAREST CPT date, so "billed before the paralytic"
    # and "billed after" are separable. Negative means the code predates t0.
    _with_dates = (
        blocks.select("encounter_block", "t_dttm")
        .join(cpt_flags.select("encounter_block", "first_cpt_date", "last_cpt_date"), on="encounter_block", how="left")
        .with_columns(pl.col("t_dttm").dt.date().alias("t_date"))
        .with_columns(
            (pl.col("first_cpt_date") - pl.col("t_date")).dt.total_days().alias("_d_first"),
            (pl.col("last_cpt_date") - pl.col("t_date")).dt.total_days().alias("_d_last"),
        )
        .with_columns(
            pl.when(pl.col("_d_first").abs() <= pl.col("_d_last").abs())
            .then(pl.col("_d_first"))
            .otherwise(pl.col("_d_last"))
            .alias("offset_days")
        )
    )

    _binned = _with_dates.filter(pl.col("offset_days").is_not_null()).with_columns(
        pl.col("offset_days")
        .cut(OFFSET_BIN_BREAKS, labels=OFFSET_BIN_LABELS)
        .cast(pl.String)
        .alias("offset_bin")
    )

    cpt_offset_distribution = (
        pl.DataFrame({"offset_bin": OFFSET_BIN_LABELS})
        .with_row_index("bin_order")
        .join(_binned.group_by("offset_bin").agg(pl.len().cast(pl.Int32).alias("n")), on="offset_bin", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .vstack(
            pl.DataFrame(
                {
                    "bin_order": [len(OFFSET_BIN_LABELS)],
                    "offset_bin": ["no cpt code"],
                    "n": [int(_with_dates.get_column("offset_days").null_count())],
                }
            ).with_columns(pl.col("bin_order").cast(pl.UInt32), pl.col("n").cast(pl.Int32))
        )
        .with_columns(pl.lit(SITE).alias("site_name"))
        .sort(["bin_order", "offset_bin"])
    )

    assert cpt_offset_distribution.get_column("n").sum() == blocks.height, (
        "the offset distribution does not account for every block in the denominator"
    )

    publish(cpt_offset_distribution, SHARE_DIR / "cpt_offset_distribution.csv", "cpt_offset_distribution")
    return (cpt_offset_distribution,)
```

- [ ] **Step 7: Run and verify the totals reconcile**

Run: `uv run python code/06_reference_cpt.py`
Expected: `cpt_cascade.csv`'s `n_blocks` sums to 1547; `cpt_offset_distribution.csv`'s `n` sums to 1547. Both assertions above enforce this.

- [ ] **Step 8: Commit**

```bash
git add code/06_reference_cpt.py tests/test_cpt_bridge.py
git commit -m "feat(06): the CPT comparator cascade

Three mutually exclusive evidence tiers against a block-level CPT 31500 flag,
over the 1,547 blocks that have an index paralytic. No sensitivity, no kappa:
the denominator conditions on our own call, so the false-negative cell cannot be
observed and any such statistic would be computed on a cell that does not exist.
cpt_offset_distribution.csv measures the time alignment the block flag drops."
```

---

### Task 8: `06` figures — the cascade mosaic and the offset distribution

**Files:**
- Modify: `code/06_reference_cpt.py` (append cells)

**Interfaces:**
- Consumes: `cpt_cascade.csv`, `cpt_offset_distribution.csv` (read back from `SHARE_DIR`), `FIG_DIR`, `OFFSET_BIN_LABELS`.
- Produces: `figures/F1_cpt_cascade.png`, `figures/F2_cpt_offset.png`.

- [ ] **Step 1: Add F.1, the mosaic**

```python
@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    # Fixed categorical colours: teal is always "billed", grey always "not billed".
    _CODED = "#1baf7a"
    _NOT = "#b0aca2"

    _c = pl.read_csv(SHARE_DIR / "cpt_cascade.csv").sort("evidence_tier")
    _total = _c.get_column("n_blocks").sum()

    _fig, _ax = plt.subplots(figsize=(10, 5.5))

    # A mosaic, not grouped bars. The tiers are very unequal -- tier 1 in the thousands
    # against tiers 2-3 in the hundreds -- and grouped bars would render the small tiers
    # as hairlines. Row height proportional to n_blocks encodes the size disparity and
    # the split encodes the coded fraction, in one mark.
    _y = 0.0
    for _row in _c.iter_rows(named=True):
        _h = _row["n_blocks"] / _total if _total else 0.0
        if _h == 0:
            # A tier with no blocks: a published zero, drawn as a hairline rule so the
            # row is visibly present and visibly empty rather than absent.
            _ax.plot([0, 1], [_y, _y], color="0.3", linewidth=1.2, linestyle=":")
            _ax.text(0.5, _y, f"{_row['tier_label']} — 0 blocks", ha="center", va="bottom", fontsize=8)
            continue
        _frac = (_row["n_cpt_yes"] / _row["n_blocks"]) if _row["n_blocks"] else 0.0
        _ax.barh([_y + _h / 2], [_frac], height=_h * 0.92, color=_CODED, align="center")
        _ax.barh([_y + _h / 2], [1 - _frac], left=[_frac], height=_h * 0.92, color=_NOT, align="center")
        _ax.text(
            -0.01, _y + _h / 2,
            f"{_row['tier_label']}\nn = {_row['n_blocks']:,}",
            ha="right", va="center", fontsize=9,
        )
        _ax.text(
            _frac / 2 if _frac > 0.12 else _frac + 0.02,
            _y + _h / 2,
            f"{_row['pct_coded']:.1f}%",
            ha="center" if _frac > 0.12 else "left",
            va="center", fontsize=9,
            color="white" if _frac > 0.12 else "#0b0b0b",
        )
        _y += _h

    _ax.set_xlim(0, 1)
    _ax.set_ylim(0, 1)
    _ax.set_yticks([])
    _ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    _ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    _ax.set_xlabel("share of the tier's blocks carrying a CPT 31500")
    for _spine in ("top", "right", "left"):
        _ax.spines[_spine].set_visible(False)

    _handles = [
        _ax.plot([], [], color=_CODED, lw=6, label="CPT 31500 billed in the block")[0],
        _ax.plot([], [], color=_NOT, lw=6, label="no CPT 31500 — not performed, or not charted")[0],
    ]
    _ax.legend(handles=_handles, loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=2, fontsize=8, frameon=False)
    _ax.set_title(
        "F.1 — CPT agreement by paralytic evidence tier\n"
        "row height is the tier's share of blocks; CPT is a comparator, not a reference standard (P26)"
    )
    _fig.tight_layout()
    _fig.subplots_adjust(left=0.24, bottom=0.22)
    _fig.savefig(FIG_DIR / "F1_cpt_cascade.png", dpi=150)
    plt.close(_fig)
    print(f"F1_cpt_cascade.png -> {FIG_DIR}")
    return
```

- [ ] **Step 2: Add F.2, the offset distribution**

```python
@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _AQUA = "#1baf7a"
    _GREY = "#b0aca2"

    _d = pl.read_csv(SHARE_DIR / "cpt_offset_distribution.csv").sort("bin_order")

    _fig, _ax = plt.subplots(figsize=(11, 6))
    for _row in _d.iter_rows(named=True):
        _color = _GREY if _row["offset_bin"] == "no cpt code" else _AQUA
        if _row["n"] > 0:
            _ax.bar([_row["bin_order"]], [_row["n"]], width=0.7, color=_color)
        else:
            _ax.plot([_row["bin_order"]], [0], marker="D", markersize=7, color=_color,
                     linestyle="None", zorder=5, clip_on=False)

    _ax.set_xticks(_d.get_column("bin_order").to_list())
    _ax.set_xticklabels(_d.get_column("offset_bin").to_list(), rotation=45, ha="right")
    _ax.set_xlabel("signed days from t0 to the nearest CPT 31500 (negative = billed before the paralytic)")
    _ax.set_ylabel("encounter blocks")
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)

    _handles = [
        _ax.plot([], [], color=_AQUA, lw=6, label="blocks with a CPT 31500")[0],
        _ax.plot([], [], color=_GREY, lw=6, label="blocks with no CPT 31500")[0],
        _ax.plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                 label="published zero (measured, exactly 0)")[0],
    ]
    _ax.legend(handles=_handles, loc="upper left", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "F.2 — how far the billed intubation sits from the index paralytic\n"
        "the block-level flag carries no time alignment (P29); this is the measurement of what that costs"
    )
    _fig.tight_layout()
    _fig.subplots_adjust(bottom=0.30)
    _fig.savefig(FIG_DIR / "F2_cpt_offset.png", dpi=150)
    plt.close(_fig)
    print(f"F2_cpt_offset.png -> {FIG_DIR}")
    return


if __name__ == "__main__":
    app.run()
```

- [ ] **Step 3: Run and eyeball**

Run: `uv run python code/06_reference_cpt.py`
Expected: both PNGs written. F.1's rows must sum to the full axis height; a tier with zero blocks appears as a dotted rule, not as a gap.

- [ ] **Step 4: Commit**

```bash
git add code/06_reference_cpt.py
git commit -m "feat(06): figures F.1 cascade mosaic and F.2 CPT offset

A mosaic rather than grouped bars: the tiers differ by an order of magnitude in
size, and grouped bars would draw the small ones as hairlines. F.2 is the
evidence for P29's limitation -- mass at day 0 means the block flag is
time-aligned, a long tail means it is not."
```

---

### Task 9: Wire it up — runner, guards, and documentation

**Files:**
- Modify: `run_all.sh:24`
- Modify: `tests/test_clifpy_tz_boundary.py`
- Modify: `tests/test_publish_guard.py`
- Modify: `README.md`
- Modify: `code/README.md`
- Modify: `docs/pipeline_flow.md`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: a pipeline that runs end to end via `./run_all.sh`.

- [ ] **Step 1: Extend the AST timezone check to the new notebooks**

The no-naive-timestamp AST check lives in `tests/test_collapse_agent_events.py`, not in `test_clifpy_tz_boundary.py`. Edit `ALL_NOTEBOOKS` at `tests/test_collapse_agent_events.py:41`:

```python
ALL_NOTEBOOKS = [
    CODE_DIR / name
    for name in ("01_cohort.py", "02_index_paralytic.py", "03_context.py")
]
```

becomes:

```python
ALL_NOTEBOOKS = [
    CODE_DIR / name
    for name in (
        "01_cohort.py",
        "02_index_paralytic.py",
        "03_context.py",
        "04_covariates.py",
        "05_table_one.py",
        "06_reference_cpt.py",
    )
]
```

Run: `uv run pytest tests/test_collapse_agent_events.py -v`
Expected: PASS. If it fails, the failure names the offending call — fix the notebook, not the test.

- [ ] **Step 2: Add the publish-guard case for the new PHI frame**

Append to `tests/test_publish_guard.py`:

```python
def test_index_covariates_column_set_is_refused():
    """The analytic frame is PHI and must never reach final_no_phi.

    It carries four identifier columns and two datetime columns; `publish()` must
    refuse it on the first of them. This is the same construction the docstring of
    utils/suppress.py calls out for index_context.parquet -- dropping the ids alone
    would still leave a row-level frame with timestamps.
    """
    frame = pl.DataFrame(
        {
            "index_paralytic_id": ["b1_P1"],
            "encounter_block": [1],
            "patient_id": ["p1"],
            "p_num": [1],
            "t_dttm": [datetime.datetime(2024, 5, 1, 12, 0)],
            "evidence_tier": [2],
            "los_hospital_days": [4.5],
        }
    )
    with pytest.raises(AssertionError, match="identifier column"):
        publish(frame, Path("/dev/null"), "index_covariates")
```

Match the existing file's import style — if it already imports `datetime`, `pytest`, `pl`, `Path` and `publish`, do not re-import.

Run: `uv run pytest tests/test_publish_guard.py -v`
Expected: PASS.

- [ ] **Step 3: Extend the runner**

In `run_all.sh`, replace line 24:

```bash
STEPS=(01_cohort 02_index_paralytic 03_context)
```

with:

```bash
STEPS=(01_cohort 02_index_paralytic 03_context 04_covariates 05_table_one 06_reference_cpt)
```

- [ ] **Step 4: Update `code/README.md`**

Change the opening line from "Three marimo notebooks" to "Six marimo notebooks" and append three rows to the notebook table:

```markdown
| `04_covariates.py` | The sole owner of the study's analytic row: one row per index paralytic, carrying the evidence tier, demographics, comorbidity, physiology and life support in 1/6/24 h look-backs, and block-level LOS and mortality. Everything downstream aggregates this one frame. | `patient`, `vitals`, `medication_admin_continuous`, `crrt_therapy`, `position`, `hospital_diagnosis`, and re-opens `hospitalization` and `adt` | `output/intermediate_phi/index_covariates.parquet` (PHI); `output/final_no_phi/covariate_coverage.csv` |
| `05_table_one.py` | Table 1, published twice from one row inventory: by encounter block at its first index, and by index event. Every row carries its own rule and unit. | nothing — reads `index_covariates.parquet` | `table1_by_agent_block.csv`, `table1_by_agent_index.csv`, `figures/T1_*.png`, `figures/T2_*.png` |
| `06_reference_cpt.py` | The CPT `31500` comparator: three mutually exclusive evidence tiers against a block-level billing flag, plus the day offset between the index paralytic and the nearest code. | `patient_procedures` | `cpt_cascade.csv`, `cpt_cascade_qc.csv`, `cpt_offset_distribution.csv`, `figures/F1_*.png`, `figures/F2_*.png` |
```

- [ ] **Step 5: Update `README.md`'s required-tables section**

Add seven subsections following the existing format (a `### N. \`table_name\`` heading and a column table). Mark `patient` and `patient_procedures` **required**; mark `medication_admin_continuous`, `crrt_therapy`, `position`, `vitals`, `hospital_diagnosis` **optional — the pipeline runs without them and publishes 0% coverage**.

| table | columns to document |
|---|---|
| `patient` | `patient_id`, `sex_category`, `race_category`, `ethnicity_category`, `death_dttm` |
| `patient_procedures` | `hospitalization_id`, `procedure_code`, `procedure_code_format`, `procedure_billed_dttm` |
| `medication_admin_continuous` | `hospitalization_id`, `admin_dttm`, `med_category` |
| `crrt_therapy` | `hospitalization_id`, `recorded_dttm` |
| `position` | `hospitalization_id`, `recorded_dttm`, `position_category` |
| `vitals` | `hospitalization_id`, `recorded_dttm`, `vital_category`, `vital_value` |
| `hospital_diagnosis` | `hospitalization_id`, `diagnosis_code`, `diagnosis_code_format` |

Add a sentence beneath: "Required procedure code: `31500` (endotracheal intubation). It is a comparator, not a reference standard — see the design's P26."

- [ ] **Step 6: Update `docs/pipeline_flow.md` §2**

Add three rows to the per-notebook table map matching `code/README.md`, and add a short subsection describing the new artifacts, matching the file's existing voice. Note explicitly that `index_covariates.parquet` is PHI and that `04` is the sole owner of the analytic row.

- [ ] **Step 7: Run everything end to end**

```bash
uv run pytest tests/ -q
./run_all.sh
```

Expected: all tests pass. The runner completes six steps. `output/final_no_phi/` gains `covariate_coverage.csv`, `table1_by_agent_block.csv`, `table1_by_agent_index.csv`, `cpt_cascade.csv`, `cpt_cascade_qc.csv`, `cpt_offset_distribution.csv` and four figures.

- [ ] **Step 8: Verify the two N's reconcile**

```bash
python3 -c "
import polars as pl
t1 = pl.read_csv('output/final_no_phi/table1_by_agent_block.csv')
casc = pl.read_csv('output/final_no_phi/cpt_cascade.csv')
ipb = pl.read_csv('output/final_no_phi/index_per_block.csv')
n_t1 = t1.filter(pl.col('statistic') == 'n_rows')['overall'][0]
n_casc = casc['n_blocks'].sum()
n_ipb = ipb['n_blocks'].sum()
print(f'table1 block n_rows = {n_t1:,.0f}')
print(f'cascade n_blocks    = {n_casc:,}')
print(f'index_per_block sum = {n_ipb:,}')
assert n_t1 == n_casc == n_ipb, 'the three denominators disagree'
print('reconciled')
"
```

Expected: three identical numbers and `reconciled`.

- [ ] **Step 9: Commit**

```bash
git add run_all.sh tests/ README.md code/README.md docs/pipeline_flow.md
git commit -m "feat: wire 04-06 into the runner, guards and docs

The AST timezone check and the publish guard both cover the new notebooks --
index_covariates.parquet is PHI by construction and the guard now pins that.
Seven CLIF tables added to the site data contract, two required and five
optional."
```

---

## Verification

The plan is complete when all of the following hold:

- [ ] `uv run pytest tests/ -q` passes with no skips (the contract test requires the pipeline to have been run).
- [ ] `./run_all.sh` completes all six steps.
- [ ] `table1_by_agent_block.csv`'s `n_rows`, `cpt_cascade.csv`'s `n_blocks` sum, and `index_per_block.csv`'s `n_blocks` sum are the same number.
- [ ] `table1_by_agent_block.csv` and `table1_by_agent_index.csv` have identical `statistic` columns.
- [ ] `cpt_offset_distribution.csv`'s `n` sums to that same denominator.
- [ ] Every `*.csv` in `final_no_phi/` was written by `publish()` — no identifier column, no datetime column.
- [ ] Re-running the pipeline produces byte-identical CSVs (`git diff --stat output/` is empty after a second run, for a tracked output directory).
