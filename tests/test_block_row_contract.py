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
    path = share / "cpt_cascade.csv"
    if not path.exists():
        pytest.skip("cpt_cascade.csv absent; run code/06_reference_cpt.py first")
    return pl.read_csv(path)


@pytest.fixture(scope="module")
def table1_block_readable():
    _, share = _dirs()
    path = share / "table1_by_agent_block_readable.csv"
    if not path.exists():
        pytest.skip("table1_by_agent_block_readable.csv absent; run code/05_table_one.py first")
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


def test_block_and_index_artifacts_agree_on_n(
    frame, table1_block, table1_index, cpt_cascade, index_per_block
):
    """FIX 10 (2026-08-12 final review): automates the reconciliation spec §8 already
    claims this file performs.

    Three independently-computed block counts must be identical:

      * table1_by_agent_block.json's own n_rows row
      * cpt_cascade.csv's n_blocks, summed across the three evidence tiers
      * index_per_block.csv's n_blocks, summed across the >=1-index grid

    A fourth, cpt_offset_distribution.csv, was checked here until 2026-08-14, when
    P30 was withdrawn and that artifact with it.

    Before this test existed, that agreement was checked by hand once and never pinned
    -- exactly the kind of cross-notebook drift `04`'s single analytic frame exists to
    prevent, left unguarded at the one point three separately-published CSVs are
    supposed to restate the same number.

    table1_by_agent_index.json's n_rows is checked separately against the analytic
    frame's own height, since the index-level table's unit is the event, not the
    block, and has no equivalent in the other three artifacts.
    """
    _t1_block_n_rows = table1_block.filter(pl.col("statistic") == "n_rows").get_column("overall")[0]
    _cpt_cascade_n = cpt_cascade.get_column("n_blocks").sum()
    _index_per_block_n = index_per_block.get_column("n_blocks").sum()

    assert _t1_block_n_rows == _cpt_cascade_n == _index_per_block_n, (
        "the three block counts disagree: table1_by_agent_block.json n_rows="
        f"{_t1_block_n_rows}, cpt_cascade.csv sum(n_blocks)={_cpt_cascade_n}, "
        f"index_per_block.csv sum(n_blocks)={_index_per_block_n}"
    )

    _t1_index_n_rows = table1_index.filter(pl.col("statistic") == "n_rows").get_column("overall")[0]
    assert _t1_index_n_rows == frame.height, (
        f"table1_by_agent_index.json reports n_rows={_t1_index_n_rows} but "
        f"index_covariates.parquet has {frame.height:,} rows"
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
