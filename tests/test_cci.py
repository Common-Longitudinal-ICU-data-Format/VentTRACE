"""Pins diagnosis-format normalization before clifpy CCI calculation."""

import ast
from pathlib import Path

import polars as pl
from clifpy import calculate_cci

NOTEBOOK = Path(__file__).parent.parent / "code" / "04_covariates.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())


def _load_from_notebook(name):
    found = [
        node
        for node in ast.walk(NOTEBOOK_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1
    namespace = {"pl": pl}
    exec(compile(ast.Module(body=[found[0]], type_ignores=[]), NOTEBOOK.name, "exec"), namespace)
    return namespace[name]


normalize_diagnosis_code_format = _load_from_notebook("normalize_diagnosis_code_format")


def test_diagnosis_formats_are_normalized_without_filtering_rows():
    diagnosis = pl.DataFrame(
        {
            "hospitalization_id": ["upper", "lower", "spaced", "other"],
            "diagnosis_code": ["I21.9", "I21.9", "I21.9", "410.9"],
            "diagnosis_code_format": ["ICD10CM", "icd10cm", " ICD10CM ", "ICD9CM"],
        }
    )

    normalized = normalize_diagnosis_code_format(diagnosis)

    assert normalized.get_column("diagnosis_code_format").to_list() == [
        "icd10cm",
        "icd10cm",
        "icd10cm",
        "icd9cm",
    ]
    assert normalized.height == diagnosis.height


def test_clifpy_cci_accepts_all_normalized_icd10cm_casing_variants():
    diagnosis = pl.DataFrame(
        {
            "hospitalization_id": ["upper", "lower", "spaced", "other"],
            "diagnosis_code": ["I21.9", "I21.9", "I21.9", "410.9"],
            "diagnosis_code_format": ["ICD10CM", "icd10cm", " ICD10CM ", "ICD9CM"],
        }
    )

    cci = calculate_cci(normalize_diagnosis_code_format(diagnosis))

    assert set(cci["hospitalization_id"]) == {"upper", "lower", "spaced"}
    assert cci["myocardial_infarction"].tolist() == [1, 1, 1]
