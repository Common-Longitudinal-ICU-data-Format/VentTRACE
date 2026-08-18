"""Pins the complete IMV-transition x sedation context partition in notebook 04."""

import ast
from pathlib import Path

import polars as pl


NOTEBOOK = Path(__file__).parent.parent / "code" / "04_covariates.py"


def _load_evidence_tier():
    tree = ast.parse(NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "evidence_tier"
    ]
    assert len(found) == 1
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"pl": pl}
    exec(compile(module, str(NOTEBOOK), "exec"), namespace)
    return namespace["evidence_tier"]


def test_evidence_categories_cover_all_four_context_combinations():
    evidence_tier = _load_evidence_tier()
    df = pl.DataFrame(
        {
            "imv_transition": [False, True, True, False],
            "any_sedative": [False, False, True, True],
        }
    ).with_columns(
        evidence_tier("imv_transition", "any_sedative").alias("evidence_tier")
    )

    assert df.get_column("evidence_tier").to_list() == [1, 2, 3, 4]
