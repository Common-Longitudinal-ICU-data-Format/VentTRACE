"""Contracts for same-medication dose merging within formed index events."""

import ast
import json
from pathlib import Path

import polars as pl
import pytest


NOTEBOOK = Path(__file__).parent.parent / "code" / "02_index_paralytic.py"


def _load_function(name):
    tree = ast.parse(NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"pl": pl}
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace[name]


MERGE = _load_function("merge_formed_index_doses")
DOSE_TYPE = pl.Struct(
    {
        "med_category": pl.String,
        "med_dose": pl.Float64,
        "med_dose_unit": pl.String,
        "mar_action_category": pl.String,
        "offset_minutes": pl.Float64,
    }
)


def _dose(medication, dose, offset, unit="mg", action="given"):
    return {
        "med_category": medication,
        "med_dose": dose,
        "med_dose_unit": unit,
        "mar_action_category": action,
        "offset_minutes": offset,
    }


def _frame(events):
    return pl.DataFrame(
        {
            "index_paralytic_id": [event[0] for event in events],
            "n_admins": [len(event[1]) for event in events],
            "n_agents": [len({dose["med_category"] for dose in event[1]}) for event in events],
            "doses": [event[1] for event in events],
        },
        schema={
            "index_paralytic_id": pl.String,
            "n_admins": pl.Int32,
            "n_agents": pl.Int32,
            "doses": pl.List(DOSE_TYPE),
        },
    )


def _doses(frame, event_id):
    return (
        frame.filter(pl.col("index_paralytic_id") == event_id)
        .select("doses")
        .explode("doses", empty_as_null=True)
        .unnest("doses")
        .sort("med_category")
    )


def test_single_medication_is_unchanged():
    out = MERGE(_frame([("P1", [_dose("rocuronium", 50.0, 0.0)])]))

    assert out["n_before_merge_admin"].to_list() == [1]
    assert out["n_admins"].to_list() == [1]
    assert out["is_coadmin"].to_list() == [False]
    assert _doses(out, "P1").row(0, named=True) == _dose("rocuronium", 50.0, 0.0)


def test_repeated_medication_sums_to_one_entry_with_earliest_metadata():
    out = MERGE(
        _frame(
            [
                (
                    "P1",
                    [
                        _dose("rocuronium", 20.0, 5.0, action="late"),
                        _dose("rocuronium", 30.0, 0.0, action="early"),
                    ],
                )
            ]
        )
    )

    row = _doses(out, "P1").row(0, named=True)
    assert row == _dose("rocuronium", 50.0, 0.0, action="early")
    assert out["n_before_merge_admin"].to_list() == [2]
    assert out["n_admins"].to_list() == [1]
    assert out["is_coadmin"].to_list() == [False]


def test_only_duplicates_merge_in_a_mixed_index():
    out = MERGE(
        _frame(
            [
                (
                    "P1",
                    [
                        _dose("rocuronium", 40.0, 0.0),
                        _dose("succinylcholine", 100.0, 1.0),
                        _dose("rocuronium", 10.0, 2.0),
                    ],
                )
            ]
        )
    )

    doses = _doses(out, "P1")
    assert doses.select("med_category", "med_dose").rows() == [
        ("rocuronium", 50.0),
        ("succinylcholine", 100.0),
    ]
    assert out["n_before_merge_admin"].to_list() == [3]
    assert out["n_admins"].to_list() == [2]
    assert out["is_coadmin"].to_list() == [True]


def test_same_medication_in_different_formed_indexes_never_merges():
    out = MERGE(
        _frame(
            [
                ("P1", [_dose("rocuronium", 20.0, 0.0)]),
                ("P2", [_dose("rocuronium", 30.0, 0.0)]),
            ]
        )
    )

    assert out.height == 2
    assert _doses(out, "P1")["med_dose"].to_list() == [20.0]
    assert _doses(out, "P2")["med_dose"].to_list() == [30.0]


def test_known_doses_are_used_when_other_components_are_missing_or_nonfinite():
    out = MERGE(
        _frame(
            [
                (
                    "P1",
                    [
                        _dose("rocuronium", 20.0, 0.0),
                        _dose("rocuronium", None, 1.0),
                        _dose("rocuronium", float("nan"), 2.0),
                        _dose("rocuronium", float("inf"), 3.0),
                    ],
                ),
                (
                    "P2",
                    [
                        _dose("vecuronium", None, 0.0),
                        _dose("vecuronium", float("nan"), 1.0),
                    ],
                ),
            ]
        )
    )

    assert _doses(out, "P1")["med_dose"].to_list() == [20.0]
    assert _doses(out, "P2")["med_dose"].to_list() == [None]


def test_output_order_is_deterministic_and_counts_match_agents():
    doses = [
        _dose("vecuronium", 5.0, 2.0),
        _dose("rocuronium", 20.0, 0.0),
        _dose("vecuronium", 5.0, 1.0),
    ]
    forward = MERGE(_frame([("P1", doses)]))
    reverse = MERGE(_frame([("P1", list(reversed(doses)))]))

    assert _doses(forward, "P1").equals(_doses(reverse, "P1"))
    assert forward["n_admins"].to_list() == forward["n_agents"].to_list() == [2]


def test_different_units_for_one_medication_are_rejected():
    frame = _frame(
        [
            (
                "P1",
                [
                    _dose("rocuronium", 20.0, 0.0, unit="mg"),
                    _dose("rocuronium", 20_000.0, 1.0, unit="mcg"),
                ],
            )
        ]
    )

    with pytest.raises(AssertionError, match="multiple units"):
        MERGE(frame)


def test_merge_is_called_only_after_the_index_is_formed():
    source = NOTEBOOK.read_text()
    formed = source.index("_formed_index = (")
    merge_call = source.index("merge_formed_index_doses(_formed_index)")

    assert formed < merge_call


def test_generated_outputs_reconcile_to_the_merged_index_inventory():
    config_path = NOTEBOOK.parent.parent / "config" / "config.json"
    if not config_path.exists():
        pytest.skip("config/config.json absent; pipeline has not been set up")
    with open(config_path) as file:
        output = Path(json.load(file)["output_directory"])
    if not output.is_absolute():
        output = NOTEBOOK.parent.parent / output

    phi = output / "intermediate_phi"
    share = output / "final_no_phi"
    required = [
        phi / "step02__index_paralytic.parquet",
        phi / "step03__index_context.parquet",
        share / "step02__paralytic_dose_raw_unit_counts.csv",
        share / "fig_B1__paralytic_dose_ecdf.csv",
        share / "fig_G1__dose_per_weight_consort.csv",
    ]
    if not all(path.exists() for path in required):
        pytest.skip("merged index outputs absent; run pipeline steps 02-04")

    index = pl.read_parquet(required[0])
    context = pl.read_parquet(required[1])
    doses = index.explode("doses", empty_as_null=True).unnest("doses")

    assert index.filter(
        (pl.col("n_before_merge_admin") < pl.col("n_admins"))
        | (pl.col("n_admins") != pl.col("n_agents"))
        | (pl.col("n_admins") != pl.col("doses").list.len())
    ).is_empty()
    assert doses.group_by(["index_paralytic_id", "med_category"]).len().filter(
        pl.col("len") != 1
    ).is_empty()
    assert doses.height == index["n_admins"].sum()

    propagated = context.select("index_paralytic_id", "doses").sort("index_paralytic_id")
    expected = index.select("index_paralytic_id", "doses").sort("index_paralytic_id")
    assert propagated.equals(expected)

    unit_counts = pl.read_csv(required[2])
    assert unit_counts["n"].sum() == doses.height

    finite_doses = doses.filter(
        pl.col("med_dose").is_not_null()
        & pl.col("med_dose").is_finite()
        & pl.col("med_dose_unit").is_not_null()
    ).height
    ecdf = pl.read_csv(required[3])
    ecdf_total = ecdf.group_by(["med_category", "med_dose_unit"]).agg(
        n=pl.col("n_total").first()
    )["n"].sum()
    assert ecdf_total == finite_doses

    flow = pl.read_csv(required[4]).filter(pl.col("population") == "paralytic")
    assert flow["count_unit"].unique().to_list() == ["formed-index medication doses"]
    assert flow.filter(pl.col("stage_order") == 1)["n_remaining"].item() == doses.height
