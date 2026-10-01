"""Contracts for exact-agent-set sedation dose and selected-weight ECDFs."""

import ast
import json
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
CONTEXT = ROOT / "code" / "03_context.py"
COVARIATES = ROOT / "code" / "04_covariates.py"


def _load_function(path, name):
    tree = ast.parse(path.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"pl": pl}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


COMBINATION_ECDF = _load_function(CONTEXT, "ecdf_by_sedative_combination")
COMBINATION_SUMMARY = _load_function(
    CONTEXT, "summarize_doses_by_sedative_combination"
)
GENERIC_ECDF = _load_function(COVARIATES, "ecdf_by_columns")
WEIGHT_ADJUSTED_COMBINATION_SUMMARY = _load_function(
    COVARIATES, "summarize_weight_adjusted_doses_by_sedative_combination"
)
BUILD_WEIGHT_SOURCE = _load_function(
    COVARIATES, "build_sedation_combination_weight_source"
)


def _share_dir():
    with open(ROOT / "config" / "config.json") as file:
        output = Path(json.load(file)["output_directory"])
    if not output.is_absolute():
        output = ROOT / output
    return output / "final_no_phi"


def test_exact_agent_sets_and_agents_have_independent_ecdfs():
    frame = pl.DataFrame(
        {
            "agent_set": [
                "ketamine",
                "ketamine",
                "ketamine+propofol",
                "ketamine+propofol",
                "ketamine+propofol",
            ],
            "med_category": [
                "ketamine",
                "ketamine",
                "ketamine",
                "ketamine",
                "propofol",
            ],
            "med_dose_unit": ["mg"] * 5,
            "med_dose": [50.0, 50.0, 20.0, 30.0, 40.0],
        }
    )

    out = COMBINATION_ECDF(frame)

    ketamine_alone = out.filter(pl.col("agent_set") == "ketamine")
    assert ketamine_alone.select("dose", "n_at_dose", "n_total").rows() == [
        (50.0, 2, 2)
    ]
    combination = out.filter(pl.col("agent_set") == "ketamine+propofol")
    assert combination.filter(pl.col("med_category") == "ketamine").select(
        "dose", "n_cum", "n_total", "ecdf"
    ).rows() == [(20.0, 1, 2, 0.5), (30.0, 2, 2, 1.0)]
    assert combination.filter(pl.col("med_category") == "propofol").select(
        "dose", "n_cum", "n_total", "ecdf"
    ).rows() == [(40.0, 1, 1, 1.0)]


def test_combination_ecdf_drops_missing_values_and_sorts_deterministically():
    frame = pl.DataFrame(
        {
            "agent_set": ["ketamine+propofol"] * 4,
            "med_category": ["propofol", "ketamine", "ketamine", "ketamine"],
            "med_dose_unit": ["mg"] * 4,
            "med_dose": [40.0, 30.0, None, 20.0],
        }
    )

    out = COMBINATION_ECDF(frame)

    assert out.select("med_category", "dose").rows() == [
        ("ketamine", 20.0),
        ("ketamine", 30.0),
        ("propofol", 40.0),
    ]
    assert out.group_by("med_category").agg(
        pl.col("n_at_dose").sum().alias("count"),
        pl.col("n_total").first().alias("total"),
    ).filter(pl.col("count") != pl.col("total")).is_empty()


def test_combination_summary_compares_solo_and_coadministered_doses():
    frame = pl.DataFrame(
        {
            "agent_set": [
                "fentanyl",
                "fentanyl",
                "fentanyl+propofol",
                "fentanyl+propofol",
                "fentanyl+propofol",
            ],
            "med_category": [
                "fentanyl",
                "fentanyl",
                "fentanyl",
                "fentanyl",
                "propofol",
            ],
            "med_dose_converted": [50.0, 100.0, 20.0, 30.0, 40.0],
        }
    )

    out = COMBINATION_SUMMARY(
        frame,
        ["fentanyl", "fentanyl+propofol"],
        ["fentanyl", "propofol"],
        {"fentanyl": "mcg", "propofol": "mg"},
    )

    solo = out.filter(pl.col("agent_set") == "fentanyl").row(0, named=True)
    assert solo["fentanyl_n_admin_windows"] == 2
    assert solo["fentanyl_mean_dose"] == 75.0
    assert solo["fentanyl_sd_dose"] == pytest.approx(35.3553390593)
    assert solo["fentanyl_median_dose"] == 75.0
    assert solo["fentanyl_p25_dose"] == 62.5
    assert solo["fentanyl_p75_dose"] == 87.5
    assert solo["fentanyl_iqr_dose"] == 25.0
    assert solo["propofol_n_admin_windows"] == 0
    assert solo["propofol_mean_dose"] is None

    combination = out.filter(
        pl.col("agent_set") == "fentanyl+propofol"
    ).row(0, named=True)
    assert combination["fentanyl_mean_dose"] == 25.0
    assert combination["propofol_n_admin_windows"] == 1
    assert combination["propofol_mean_dose"] == 40.0
    assert combination["propofol_sd_dose"] is None
    assert combination["fentanyl_dose_unit"] == "mcg"
    assert combination["propofol_dose_unit"] == "mg"


def test_generic_ecdf_supports_combination_normalized_dose_groups():
    frame = pl.DataFrame(
        {
            "agent_set": ["ketamine+propofol"] * 3,
            "med_category": ["ketamine", "ketamine", "propofol"],
            "dose_per_weight_unit": ["mg/kg"] * 3,
            "dose_per_weight": [0.5, 1.0, 0.5],
        }
    )

    out = GENERIC_ECDF(
        frame,
        ["agent_set", "med_category", "dose_per_weight_unit"],
        "dose_per_weight",
        "dose_per_weight",
    )

    assert out.filter(pl.col("med_category") == "ketamine")["n_total"].to_list() == [
        2,
        2,
    ]
    assert out.filter(pl.col("med_category") == "propofol")["n_total"].to_list() == [
        1
    ]


def test_weight_adjusted_summary_compares_solo_and_coadministered_doses():
    frame = pl.DataFrame(
        {
            "agent_set": [
                "fentanyl",
                "fentanyl",
                "fentanyl+propofol",
                "fentanyl+propofol",
                "fentanyl+propofol",
            ],
            "med_category": [
                "fentanyl",
                "fentanyl",
                "fentanyl",
                "fentanyl",
                "propofol",
            ],
            "dose_per_weight": [1.0, 2.0, 0.5, 0.75, 1.0],
        }
    )

    out = WEIGHT_ADJUSTED_COMBINATION_SUMMARY(
        frame,
        ["fentanyl", "fentanyl+propofol"],
        ["fentanyl", "propofol"],
        {"fentanyl": "mcg", "propofol": "mg"},
    )

    solo = out.filter(pl.col("agent_set") == "fentanyl").row(0, named=True)
    assert solo["fentanyl_n_admin_windows"] == 2
    assert solo["fentanyl_mean_dose_per_weight"] == 1.5
    assert solo["fentanyl_sd_dose_per_weight"] == pytest.approx(0.7071067812)
    assert solo["fentanyl_median_dose_per_weight"] == 1.5
    assert solo["fentanyl_p25_dose_per_weight"] == 1.25
    assert solo["fentanyl_p75_dose_per_weight"] == 1.75
    assert solo["fentanyl_iqr_dose_per_weight"] == 0.5
    assert solo["propofol_n_admin_windows"] == 0
    assert solo["propofol_mean_dose_per_weight"] is None

    combination = out.filter(
        pl.col("agent_set") == "fentanyl+propofol"
    ).row(0, named=True)
    assert combination["fentanyl_mean_dose_per_weight"] == 0.625
    assert combination["propofol_n_admin_windows"] == 1
    assert combination["propofol_mean_dose_per_weight"] == 1.0
    assert combination["propofol_sd_dose_per_weight"] is None
    assert combination["fentanyl_dose_per_weight_unit"] == "mcg/kg"
    assert combination["propofol_dose_per_weight_unit"] == "mg/kg"


def test_selected_weight_source_counts_each_index_once_per_population():
    index_context = pl.DataFrame(
        {
            "index_paralytic_id": ["a", "b", "c"],
            "sedative_agents": [
                ["ketamine", "propofol"],
                ["ketamine"],
                [],
            ],
        },
        schema={
            "index_paralytic_id": pl.String,
            "sedative_agents": pl.List(pl.String),
        },
    )
    dose_weights = pl.DataFrame(
        {
            "index_paralytic_id": ["a", "b", "c"],
            "dose_weight_kg": [80.0, 70.0, None],
        }
    )

    out = BUILD_WEIGHT_SOURCE(
        index_context,
        dose_weights,
        ["ketamine", "ketamine+propofol"],
    )

    assert out.filter(pl.col("population") == "all_indexes").height == 3
    assert out.filter(pl.col("population") == "ketamine").height == 1
    assert out.filter(pl.col("population") == "ketamine+propofol").height == 1
    assert out.filter(pl.col("population") == "").is_empty()


def test_selected_weight_ecdf_uses_index_counts():
    source = pl.DataFrame(
        {
            "population": ["ketamine+propofol"] * 3,
            "dose_weight_kg": [70.0, 70.0, 80.0],
        }
    )

    out = GENERIC_ECDF(
        source,
        ["population"],
        "dose_weight_kg",
        "weight_kg",
    )

    assert out.select("weight_kg", "n_at_value", "n_cum", "n_total", "ecdf").rows() == [
        (70.0, 2, 2, 3, 0.666667),
        (80.0, 1, 3, 3, 1.0),
    ]


def test_generated_combination_outputs_reconcile_when_present():
    share = _share_dir()
    combination_dir = share / "sedation_combination_ecdf"
    absolute_inventory_path = combination_dir / "step03__absolute_dose_inventory.csv"
    weight_inventory_path = combination_dir / "step04__dose_weight_inventory.csv"
    if not absolute_inventory_path.exists() or not weight_inventory_path.exists():
        pytest.skip("combination outputs absent; run steps 03 and 04 first")

    absolute_inventory = pl.read_csv(absolute_inventory_path)
    weight_inventory = pl.read_csv(weight_inventory_path)
    expected_agent_sets = set(
        pl.read_csv(share / "step03__sedation_summary.csv")
        .filter(pl.col("any_sedative"))
        .get_column("agent_set")
    )
    assert set(absolute_inventory.get_column("agent_set")) == expected_agent_sets

    for row in absolute_inventory.iter_rows(named=True):
        frame = pl.read_csv(share / row["csv_file"])
        assert set(frame.get_column("med_category")) == set(row["agent_set"].split("+"))
        assert frame.group_by(["med_category", "med_dose_unit"]).agg(
            pl.col("n_at_dose").sum().alias("count"),
            pl.col("n_total").first().alias("total"),
            pl.col("ecdf").last().alias("last_ecdf"),
        ).filter(
            (pl.col("count") != pl.col("total")) | (pl.col("last_ecdf") != 1.0)
        ).is_empty()
        for medication in (
            "etomidate",
            "fentanyl",
            "ketamine",
            "midazolam",
            "propofol",
        ):
            n_doses = row[f"{medication}_n_admin_windows"]
            if medication not in row["agent_set"].split("+"):
                assert n_doses == 0
            if n_doses == 0:
                assert row[f"{medication}_mean_dose"] is None
                assert row[f"{medication}_median_dose"] is None
                assert row[f"{medication}_iqr_dose"] is None
                continue
            assert row[f"{medication}_mean_dose"] is not None
            assert row[f"{medication}_median_dose"] is not None
            assert row[f"{medication}_p25_dose"] is not None
            assert row[f"{medication}_p75_dose"] is not None
            assert row[f"{medication}_iqr_dose"] == pytest.approx(
                row[f"{medication}_p75_dose"]
                - row[f"{medication}_p25_dose"]
            )

    eligibility = pl.read_csv(
        combination_dir / "step04__selected_weight_eligibility_qc.csv"
    )
    normalized = weight_inventory.filter(
        pl.col("artifact_type") == "dose_per_weight"
    )
    assert set(normalized.get_column("agent_set")) == expected_agent_sets
    for row in normalized.iter_rows(named=True):
        frame = pl.read_csv(share / row["csv_file"])
        if frame.is_empty():
            assert row["n_observations"] == 0
            continue
        assert set(frame.get_column("med_category")).issubset(
            set(row["agent_set"].split("+"))
        )
        totals = frame.group_by(
            ["med_category", "dose_per_weight_unit"]
        ).agg(
            pl.col("n_at_dose").sum().alias("count"),
            pl.col("n_total").first().alias("total"),
            pl.col("ecdf").last().alias("last_ecdf"),
        )
        assert totals.filter(
            (pl.col("count") != pl.col("total")) | (pl.col("last_ecdf") != 1.0)
        ).is_empty()
        assert totals.get_column("total").sum() == row["n_observations"]
        for medication in (
            "etomidate",
            "fentanyl",
            "ketamine",
            "midazolam",
            "propofol",
        ):
            n_doses = row[f"{medication}_n_admin_windows"]
            med_total = totals.filter(
                pl.col("med_category") == medication
            ).get_column("total").sum()
            assert n_doses == med_total
            if n_doses == 0:
                assert row[f"{medication}_mean_dose_per_weight"] is None
                assert row[f"{medication}_median_dose_per_weight"] is None
                assert row[f"{medication}_iqr_dose_per_weight"] is None
                continue
            assert row[f"{medication}_mean_dose_per_weight"] is not None
            assert row[f"{medication}_median_dose_per_weight"] is not None
            assert row[f"{medication}_p25_dose_per_weight"] is not None
            assert row[f"{medication}_p75_dose_per_weight"] is not None
            assert row[f"{medication}_iqr_dose_per_weight"] == pytest.approx(
                row[f"{medication}_p75_dose_per_weight"]
                - row[f"{medication}_p25_dose_per_weight"]
            )

    overall_normalized = pl.read_csv(
        share / "fig_E4__sedation_dose_per_weight_ecdf.csv"
    )
    for medication in (
        "etomidate",
        "fentanyl",
        "ketamine",
        "midazolam",
        "propofol",
    ):
        expected = (
            overall_normalized.filter(pl.col("med_category") == medication)
            .group_by("med_category")
            .agg(pl.col("n_total").first())
            .get_column("n_total")
            .sum()
        )
        assert normalized.get_column(f"{medication}_n_admin_windows").sum() == expected

    selected_weights = weight_inventory.filter(
        pl.col("artifact_type") == "selected_weight"
    )
    assert selected_weights.get_column("fentanyl_n_admin_windows").null_count() == (
        selected_weights.height
    )
    assert selected_weights.height == absolute_inventory.height + 1
    for row in selected_weights.iter_rows(named=True):
        population = (
            "all_indexes" if row["agent_set"] == "(all indexes)" else row["agent_set"]
        )
        available = eligibility.filter(
            pl.col("population") == population
        ).get_column("n_weight_available").item()
        frame = pl.read_csv(share / row["csv_file"])
        assert frame.get_column("n_at_weight").sum() == available
        if available:
            assert frame.get_column("ecdf")[-1] == 1.0
