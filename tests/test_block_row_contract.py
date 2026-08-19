"""Pins the analytic-row contract of `04_covariates.py` (spec P28, P34).

Three notebooks consume one frame and the whole no-drift argument rests on them
agreeing about which rows exist. What can go wrong without announcing itself:

  * the p_num = 1 subset drifting from the number of blocks that have an index
    paralytic, which would make the CPT denominator disagree with
    step02__index_paralytics_per_block.csv;
  * Table 1 including an index without both an IMV transition and sedation, or
    selecting anything other than a block's first valid index;
  * a block-level column (LOS, mortality) varying WITHIN a block, which would
    mean it was computed per event instead of per block and would make the
    index-level table's outcome rows meaningless;
  * the evidence category failing to partition the IMV/sedation combinations.

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
    path = phi / "step04__index_covariates.parquet"
    if not path.exists():
        pytest.skip("step04__index_covariates.parquet absent; run code/04_covariates.py first")
    return pl.read_parquet(path)


@pytest.fixture(scope="module")
def index_context():
    phi, _ = _dirs()
    path = phi / "step03__index_context.parquet"
    if not path.exists():
        pytest.skip("step03__index_context.parquet absent; run code/03_context.py first")
    return pl.read_parquet(path)


@pytest.fixture(scope="module")
def index_per_block():
    _, share = _dirs()
    path = share / "step02__index_paralytics_per_block.csv"
    if not path.exists():
        pytest.skip("step02__index_paralytics_per_block.csv absent; run code/02_index_paralytic.py first")
    return pl.read_csv(path)


def _read_table1(label):
    """The long Table 1 as a frame, out of the published JSON.

    The long form lost its own CSV on 2026-08-14 (P39 amended): the JSON's `rows`
    array is that CSV's content exactly, so this reads the same table through the
    only file that still carries it. `meta` is deliberately not returned -- these
    tests check the numbers, and a fixture that handed back the envelope too would
    invite a test that asserts on provenance strings instead of on the study's N.
    """
    _, share = _dirs()
    path = share / f"table1_by_agent_{label}.json"
    if not path.exists():
        pytest.skip(f"table1_by_agent_{label}.json absent; run code/05_table_one.py first")
    with open(path, "r") as f:
        return pl.DataFrame(json.load(f)["rows"])


@pytest.fixture(scope="module")
def table1_block():
    return _read_table1("block")


@pytest.fixture(scope="module")
def table1_index():
    return _read_table1("index")


@pytest.fixture(scope="module")
def cpt_cascade():
    _, share = _dirs()
    path = share / "fig_F1__cpt_cascade.csv"
    if not path.exists():
        pytest.skip("fig_F1__cpt_cascade.csv absent; run code/06_reference_cpt.py first")
    return pl.read_csv(path)


@pytest.fixture(scope="module")
def table1_block_readable():
    _, share = _dirs()
    path = share / "table1_by_agent_block_readable.csv"
    if not path.exists():
        pytest.skip("table1_by_agent_block_readable.csv absent; run code/05_table_one.py first")
    return pl.read_csv(path)


@pytest.fixture(scope="module")
def consort_cohort():
    _, share = _dirs()
    return pl.read_csv(share / "step01__consort_cohort.csv")


@pytest.fixture(scope="module")
def imv_prior_device():
    _, share = _dirs()
    return pl.read_csv(share / "step03__imv_prior_device.csv")


@pytest.fixture(scope="module")
def sofa_coverage():
    _, share = _dirs()
    return pl.read_csv(share / "step04__sofa_coverage.csv")


def test_p_num_one_subset_matches_index_per_block(frame, index_per_block):
    """The block table's N must equal the blocks that have at least one index."""
    expected = index_per_block.get_column("n_blocks").sum()
    got = frame.filter(pl.col("p_num") == 1).height
    assert got == expected, (
        f"the p_num = 1 subset has {got:,} rows but step02__index_paralytics_per_block.csv reports "
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
        (
            (pl.col("evidence_tier") == 1)
            & (pl.col("imv_transition") | pl.col("any_sedative"))
        )
        | (
            (pl.col("evidence_tier") == 2)
            & ~(pl.col("imv_transition") & ~pl.col("any_sedative"))
        )
        | (
            (pl.col("evidence_tier") == 3)
            & ~(pl.col("imv_transition") & pl.col("any_sedative"))
        )
        | (
            (pl.col("evidence_tier") == 4)
            & ~(~pl.col("imv_transition") & pl.col("any_sedative"))
        )
        | ~pl.col("evidence_tier").is_in([1, 2, 3, 4])
    )
    assert bad.height == 0, f"{bad.height:,} rows have a tier inconsistent with D/E"


def test_full_block_artifacts_and_valid_table1_denominators(
    frame, table1_block, table1_index, cpt_cascade, index_per_block
):
    """The CPT cohort stays full while both Table 1s use valid index events only.

    The full-cohort block counts remain identical:

      * fig_F1__cpt_cascade.csv's n_blocks, summed across the four evidence categories
      * step02__index_paralytics_per_block.csv's n_blocks, summed across the >=1-index grid
      * step04__index_covariates.parquet's distinct encounter blocks

    Table 1 is narrower by design: its index denominator is every event carrying both
    contextual signals, and its block denominator is every block with at least one such
    event. This deliberately no longer reconciles to the full CPT denominator.
    """
    _t1_block_n_rows = table1_block.filter(pl.col("statistic") == "n_rows").get_column("overall")[0]
    _cpt_cascade_n = cpt_cascade.get_column("n_blocks").sum()
    _index_per_block_n = index_per_block.get_column("n_blocks").sum()
    _all_blocks_n = frame.get_column("encounter_block").n_unique()

    assert _cpt_cascade_n == _index_per_block_n == _all_blocks_n, (
        "the full-cohort block counts disagree: "
        f"fig_F1__cpt_cascade.csv sum(n_blocks)={_cpt_cascade_n}, "
        f"step02__index_paralytics_per_block.csv sum(n_blocks)={_index_per_block_n}, "
        f"step04__index_covariates.parquet distinct blocks={_all_blocks_n}"
    )

    _valid = frame.filter(pl.col("imv_transition") & pl.col("any_sedative"))
    _t1_index_n_rows = table1_index.filter(pl.col("statistic") == "n_rows").get_column("overall")[0]
    assert _t1_index_n_rows == _valid.height, (
        f"table1_by_agent_index.json reports n_rows={_t1_index_n_rows} but "
        f"the valid-index frame has {_valid.height:,} rows"
    )
    assert _t1_block_n_rows == _valid.get_column("encounter_block").n_unique(), (
        f"table1_by_agent_block.json reports n_rows={_t1_block_n_rows} but "
        "the valid-index frame has a different number of encounter blocks"
    )


def test_table1_imv_eligibility_remains_in_primary_sixty_minute_window(
    frame, index_context
):
    with open(CONFIG) as file:
        imv_window_minutes = float(json.load(file)["imv_window_minutes"])
    assert imv_window_minutes == 60.0

    valid_offsets = (
        frame.filter(pl.col("imv_transition") & pl.col("any_sedative"))
        .select("index_paralytic_id")
        .join(
            index_context.select("index_paralytic_id", "imv_offset_minutes"),
            on="index_paralytic_id",
            how="left",
            validate="1:1",
        )
    )
    outside_primary_window = valid_offsets.filter(
        pl.col("imv_offset_minutes").is_null()
        | (pl.col("imv_offset_minutes").abs() > imv_window_minutes)
    )
    assert outside_primary_window.height == 0, (
        "Table 1 eligibility includes an IMV transition from the +/-6-hour D.2 "
        "sensitivity view rather than the primary +/-60-minute detector"
    )


def test_table1_contains_only_valid_indexes(table1_block, table1_index):
    for _label, _table in (("block", table1_block), ("index", table1_index)):
        _values = dict(
            _table.select("statistic", "overall").iter_rows()
        )
        _n = _values["n_rows"]
        assert _values["imv_transition_n"] == _n, _label
        assert _values["any_sedative_n"] == _n, _label
        assert _values["evidence_tier[3]_n"] == _n, _label
        for _tier in (1, 2, 4):
            assert _values[f"evidence_tier[{_tier}]_n"] == 0, _label


def test_block_table_uses_first_valid_index_and_valid_counts(frame, table1_block):
    _valid = (
        frame.filter(pl.col("imv_transition") & pl.col("any_sedative"))
        .sort(["encounter_block", "p_num", "index_paralytic_id"])
        .with_columns(pl.len().over("encounter_block").alias("n_valid_in_block"))
    )
    _first_valid = _valid.unique(
        subset="encounter_block", keep="first", maintain_order=True
    )
    _n_row = table1_block.filter(pl.col("statistic") == "n_rows").row(
        0, named=True
    )
    _stratum_counts = dict(
        _first_valid.group_by("agent_stratum").len().iter_rows()
    )
    for _stratum in ("rocuronium", "succinylcholine", "vecuronium", "combination"):
        assert _n_row[_stratum] == _stratum_counts.get(_stratum, 0)

    _published_mean = table1_block.filter(
        pl.col("statistic") == "n_index_in_block_mean"
    ).get_column("overall")[0]
    assert _published_mean == round(
        float(_first_valid.get_column("n_valid_in_block").mean()), 3
    )


def test_agent_stratum_collapses_only_combinations(frame):
    combo = frame.filter(pl.col("agent_stratum") == "combination")
    assert combo.filter(~pl.col("agent_label").str.contains(r"\+")).height == 0, (
        "a single-agent label was collapsed into 'combination'"
    )
    single = frame.filter(pl.col("agent_stratum") != "combination")
    assert single.filter(pl.col("agent_label").str.contains(r"\+")).height == 0, (
        "a co-administration label was not collapsed into 'combination'"
    )


def test_paralytic_cohort_and_index_blocks_reconcile(frame, consort_cohort):
    analytic_n = consort_cohort.filter(pl.col("step") == "ANALYTIC COHORT").get_column(
        "n_encounters"
    )[0]
    assert analytic_n == frame.get_column("encounter_block").n_unique()
    assert consort_cohort.filter(
        pl.col("step") == "include: >=1 qualifying paralytic administration"
    ).height == 1


def test_added_covariates_obey_their_contract(frame):
    for _h in (1, 6, 24):
        assert f"lowest_dbp_{_h}h" in frame.columns

    sofa_parts = [
        "sofa_cv_97",
        "sofa_coag",
        "sofa_liver",
        "sofa_resp",
        "sofa_cns",
        "sofa_renal",
    ]
    assert frame.filter(
        pl.col("sofa_total") != pl.sum_horizontal([pl.col(c) for c in sofa_parts])
    ).height == 0

    icu_cols = [
        c for c in frame.columns
        if c.startswith("icu_type_") and not c.endswith("_available")
    ]
    assert frame.filter(
        pl.sum_horizontal([pl.col(c).cast(pl.Int8) for c in icu_cols])
        != (pl.col("location_at_index") == "icu").cast(pl.Int8)
    ).height == 0

    agents = ["norepinephrine", "vasopressin", "epinephrine", "phenylephrine", "dopamine"]
    for _h in (1, 6, 24):
        any_col = f"vasopressor_{_h}h"
        agent_cols = [f"vasopressor_{agent}_{_h}h" for agent in agents]
        if frame.get_column(any_col).null_count() < frame.height:
            assert frame.filter(
                pl.col(any_col)
                != pl.any_horizontal([pl.col(c) for c in agent_cols])
            ).height == 0

    devices = [
        "imv", "nippv", "cpap", "high_flow_nc", "face_mask",
        "trach_collar", "nasal_cannula", "room_air", "other",
    ]
    for device in devices:
        assert frame.filter(
            pl.col(f"respiratory_device_{device}_1h")
            & ~pl.col(f"respiratory_device_{device}_6h")
        ).height == 0
        assert frame.filter(
            pl.col(f"respiratory_device_{device}_6h")
            & ~pl.col(f"respiratory_device_{device}_24h")
        ).height == 0


def test_sofa_coverage_is_complete_component_inventory(sofa_coverage):
    assert set(sofa_coverage.get_column("component")) == {
        "sofa_cv_97",
        "sofa_coag",
        "sofa_liver",
        "sofa_resp",
        "sofa_cns",
        "sofa_renal",
    }
    assert sofa_coverage.filter(
        ~pl.col("pct_events_available").is_between(0, 100)
    ).height == 0


def test_prior_device_null_states_have_distinct_labels(imv_prior_device):
    labels = set(imv_prior_device.get_column("prior_device_category"))
    assert "(none charted)" not in labels
    assert "(block opens on IMV)" in labels
    assert "(prior row device not charted)" in labels


def test_readable_table_contains_requested_rows(table1_block_readable):
    variables = table1_block_readable.get_column("variable")
    for text in (
        "Charlson comorbidity index",
        "Lowest diastolic blood pressure",
        "SOFA score",
        "Any vasopressor",
        "Respiratory support: room air",
        "Location at the index paralytic — hospital ward",
        "ICU type: medical_icu",
        "Intubation context category",
    ):
        assert variables.str.contains(text, literal=True).any(), text


def test_table1_contains_cci_statistics(table1_block, table1_index):
    expected = {
        f"cci_{suffix}"
        for suffix in ("mean", "sd", "median", "q1", "q3", "n_nonnull")
    }
    for label, table in (("block", table1_block), ("index", table1_index)):
        missing = expected - set(table.get_column("statistic"))
        assert not missing, f"{label} Table 1 is missing CCI statistics: {sorted(missing)}"


def test_the_readable_table_restates_the_long_table(table1_block, table1_block_readable):
    """P39: the readable CSV is a RENDERING of the long table, not a second computation.

    Checked on the one number both files state in a form a string comparison can
    reach -- the table's own N. If the readable table were ever rebuilt from the
    analytic frame instead of formatted from the same frame the JSON serializes, this
    is the first place the two would part company, and nothing else in the suite would
    notice: they are published side by side and read by different people.

    This is also the only test that crosses the two published Table 1 files, which
    matters more since 2026-08-14: they are now the only two, and they are in
    different formats.
    """
    _long_n = table1_block.filter(pl.col("statistic") == "n_rows").get_column("overall")[0]
    _row = table1_block_readable.filter(pl.col("variable").str.starts_with("Total encounter block"))
    assert _row.height == 1, (
        f"expected exactly one 'Total encounter blocks' line in the readable table, "
        f"found {_row.height}"
    )
    assert _row.get_column("overall")[0] == f"{_long_n:,.0f}"


def test_the_readable_table_never_prints_a_bare_python_none(table1_block_readable):
    """`NA` is the published claim "not measured"; `None` is a formatting bug.

    A `None` reaching the CSV means a display line's value fell through
    `format_stat` unformatted, which a reader would parse as a missing cell rather
    than as the deliberate NA it was supposed to be.
    """
    _value_cols = [
        c for c in table1_block_readable.columns
        if c not in ("row_order", "group", "variable", "rule", "unit", "site_name")
    ]
    assert _value_cols, "the readable table has no value columns"
    for _c in _value_cols:
        _bad = table1_block_readable.filter(
            pl.col(_c).is_null() | (pl.col(_c) == "None") | (pl.col(_c) == "nan")
        )
        assert _bad.height == 0, (
            f"column {_c} has {_bad.height} unformatted cell(s): "
            f"{_bad.get_column('variable').to_list()[:5]}"
        )
