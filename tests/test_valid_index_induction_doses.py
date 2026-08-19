"""Contracts for valid-index induction-dose summaries and requested dose bins."""

import ast
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
NOTEBOOK = ROOT / "code" / "04_covariates.py"


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


BUILD_EVENT_DOSES = _load_function("build_valid_index_induction_doses")
BUILD_SUMMARY = _load_function("build_induction_dose_summary")
BUILD_BINS = _load_function("build_induction_dose_bins")
BUILD_ADMINISTRATION_BINS = _load_function("build_induction_administration_dose_bins")


def _index_covariates():
    return pl.DataFrame(
        {
            "index_paralytic_id": ["e1", "e2", "e3", "e4", "e5", "e6"],
            "imv_transition": [True, True, True, False, True, True],
            "any_sedative": [True] * 6,
            "location_at_index": ["ed", "icu", "icu", "ed", "other", "unknown"],
            "vasopressor_1h": [True, False, None, True, False, False],
            "sex_category": ["female", "male", "unknown", "female", None, "nonbinary"],
            "ethnicity_category": [
                "hispanic",
                "non-hispanic",
                "unknown",
                "hispanic",
                None,
                "missing",
            ],
            "race_category": ["white", "black", "unknown", "white", None, "asian"],
            "cci": [0, 1, 3, 5, None, 6],
            "sofa_total": [0, 1, 2, 3, 4, 24],
        },
        schema_overrides={"vasopressor_1h": pl.Boolean, "cci": pl.Int32},
    )


def test_valid_gate_sums_split_doses_and_includes_crossover_in_each_drug():
    source = pl.DataFrame(
        {
            "index_paralytic_id": ["e1", "e1", "e2", "e3", "e3", "e4", "e6"],
            "med_category": [
                "etomidate",
                "etomidate",
                "ketamine",
                "etomidate",
                "ketamine",
                "etomidate",
                "etomidate",
            ],
        }
    )
    normalised = pl.DataFrame(
        {
            "index_paralytic_id": ["e1", "e1", "e2", "e3", "e3", "e4"],
            "med_category": [
                "etomidate",
                "etomidate",
                "ketamine",
                "etomidate",
                "ketamine",
                "etomidate",
            ],
            "dose_per_weight": [0.10, 0.15, 1.0, 0.36, 2.5, 0.2],
        }
    )

    event_doses = BUILD_EVENT_DOSES(_index_covariates(), source, normalised)

    assert event_doses.get_column("index_paralytic_id").unique().sort().to_list() == [
        "e1",
        "e2",
        "e3",
        "e6",
    ]
    assert event_doses.filter(
        (pl.col("index_paralytic_id") == "e1") & (pl.col("drug") == "etomidate")
    )["dose_mg_per_kg"][0] == pytest.approx(0.25)
    assert event_doses.filter(pl.col("index_paralytic_id") == "e3")[
        "medication_group"
    ].sort().to_list() == ["etomidate", "ketamine"]
    assert event_doses.filter(pl.col("index_paralytic_id") == "e6")[
        "dose_mg_per_kg"
    ][0] is None

    summary = BUILD_SUMMARY(_index_covariates(), event_doses, "test")
    overall_etomidate = summary.filter(
        (pl.col("stratum") == "overall")
        & (pl.col("medication_group") == "etomidate")
        & (pl.col("drug") == "etomidate")
    ).row(0, named=True)
    assert overall_etomidate["n_valid_indexes_in_stratum"] == 5
    assert overall_etomidate["n_indexes_in_medication_group"] == 3
    assert overall_etomidate["n_dose_available"] == 2
    assert overall_etomidate["n_dose_missing"] == 1
    assert overall_etomidate["median_mg_per_kg"] == pytest.approx(0.305)

    location_counts = (
        summary.filter(
            (pl.col("stratum") == "location_at_index")
            & (pl.col("medication_group") == "etomidate")
            & (pl.col("drug") == "etomidate")
        )
        .select("stratum_level", "n_valid_indexes_in_stratum")
        .sort("stratum_level")
    )
    assert location_counts["stratum_level"].to_list() == ["ed", "icu"]
    assert location_counts["n_valid_indexes_in_stratum"].sum() == 3
    assert summary.filter(pl.col("stratum") == "sofa_total")[
        "stratum_level"
    ].n_unique() == 25
    assert set(
        summary.filter(pl.col("stratum") == "sex")["stratum_level"].unique()
    ) == {"female", "male", "other"}
    ethnicity = summary.filter(pl.col("stratum") == "ethnicity")
    assert ethnicity.group_by("stratum_level").len().filter(
        pl.col("len") != 2
    ).is_empty()
    assert set(ethnicity["stratum_level"].unique()) == {
        "hispanic",
        "non-hispanic",
    }
    assert set(summary.filter(pl.col("stratum") == "race")["stratum_level"].unique()) == {
        "white",
        "non_white",
    }
    assert set(
        summary.filter(pl.col("stratum") == "vasopressor_1h")["stratum_level"].unique()
    ) == {"on", "not_on"}
    assert summary.filter(pl.col("stratum") == "cci").is_empty()
    assert summary.height == 74

    bins = BUILD_BINS(event_doses, "test")
    etomidate_rows = bins.filter(
        (pl.col("medication_group") == "etomidate")
        & (pl.col("drug") == "etomidate")
    )
    assert etomidate_rows["n_indexes_in_medication_group"].unique().to_list() == [3]
    assert etomidate_rows["n_total"].unique().to_list() == [2]
    assert etomidate_rows["n_dose_missing"].unique().to_list() == [1]


def test_requested_bin_boundaries_are_complete_and_nonoverlapping():
    etomidate = [0.19, 0.20, 0.25, 0.30, 0.35, 0.3501]
    ketamine = [0.9, 1.0, 1.5, 2.0, 2.5, 2.5001]
    event_doses = pl.DataFrame(
        {
            "index_paralytic_id": [f"e{i}" for i in range(12)],
            "medication_group": ["etomidate"] * 6 + ["ketamine"] * 6,
            "drug": ["etomidate"] * 6 + ["ketamine"] * 6,
            "dose_mg_per_kg": etomidate + ketamine,
        }
    )

    bins = BUILD_BINS(event_doses, "test")

    assert bins.height == 10
    for drug, group in [
        ("etomidate", "etomidate"),
        ("ketamine", "ketamine"),
    ]:
        rows = bins.filter(
            (pl.col("drug") == drug) & (pl.col("medication_group") == group)
        ).sort("bin_order")
        assert rows["n_indexes"].to_list() == [1, 1, 1, 2, 1]
        assert rows["n_indexes"].sum() == rows["n_total"][0] == 6
        assert rows["pct"].sum() == pytest.approx(100.0, abs=0.02)


def test_e5_plot_2_uses_requested_administration_dose_boundaries():
    frame = pl.DataFrame(
        {
            "med_category": ["etomidate"] * 6 + ["ketamine"] * 6,
            "dose_per_weight": [
                0.19,
                0.20,
                0.25,
                0.30,
                0.35,
                0.3501,
                0.9,
                1.0,
                1.5,
                2.0,
                2.5,
                2.5001,
            ],
        }
    )

    bins = BUILD_ADMINISTRATION_BINS(frame, "test")

    assert bins.height == 10
    assert bins.filter(pl.col("drug") == "etomidate")["dose_bin"].to_list() == [
        "<0.2",
        "0.2-0.249",
        "0.25-0.299",
        "0.3-0.35",
        ">0.35",
    ]
    assert bins.filter(pl.col("drug") == "ketamine")["dose_bin"].to_list() == [
        "<1",
        "1-1.49",
        "1.5-1.99",
        "2-2.5",
        ">2.5",
    ]
    for drug in ("etomidate", "ketamine"):
        rows = bins.filter(pl.col("drug") == drug)
        assert rows["n_admin_windows"].to_list() == [1, 1, 1, 2, 1]
        assert rows["n_admin_windows"].sum() == rows["n_total"][0] == 6
