"""Every figure's dataframe, data file, and PNG carry the same figure ID."""

from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_figure_dataframe_names_match_figure_ids():
    expected = {
        "code/02_index_paralytic.py": ("figure_a1_df", "figure_b1_df", "figure_c1_df"),
        "code/03_context.py": (
            "figure_d1_df",
            "figure_e1_df",
            "figure_e2_df",
            "figure_e3_df",
        ),
        "code/04_covariates.py": (
            "figure_b2_df",
            "figure_e4_df",
            "figure_e5_df",
            "figure_g1_df",
        ),
        "code/05_table_one.py": ("figure_t1_df", "figure_t2_df"),
        "code/06_reference_cpt.py": ("figure_f1_df",),
    }
    for relative_path, names in expected.items():
        source = (ROOT / relative_path).read_text()
        for name in names:
            assert f"{name} =" in source, f"{relative_path} does not define {name}"


def test_figure_data_and_png_stems_match_in_source():
    expected = {
        "code/02_index_paralytic.py": {
            "A1": "paralytic_administration_pair_gaps",
            "B1": "paralytic_dose_ecdf",
            "C1": "index_paralytic_pair_gaps",
        },
        "code/03_context.py": {
            "D1": "imv_transition_offset",
            "E1": "sedation_offset",
            "E2": "sedation_dose_summary",
            "E3": "sedation_dose_ecdf",
        },
        "code/04_covariates.py": {
            "B2": "paralytic_dose_per_weight_ecdf",
            "E4": "sedation_dose_per_weight_ecdf",
            "E5": "induction_dose_tiers",
            "G1": "dose_per_weight_consort",
        },
        "code/05_table_one.py": {
            "T1": "organ_support_by_window",
            "T2": "source_coverage",
        },
        "code/06_reference_cpt.py": {"F1": "cpt_cascade"},
    }
    for relative_path, figures in expected.items():
        source = (ROOT / relative_path).read_text()
        for figure_id, description in figures.items():
            stem = f"fig_{figure_id}__{description}"
            assert f'"{stem}.csv"' in source
            assert f'"{stem}.png"' in source
