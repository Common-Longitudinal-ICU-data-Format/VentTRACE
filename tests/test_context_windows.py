"""Independent config-driven windows for IMV transition and sedation context."""

import ast
import json
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
CONTEXT_NOTEBOOK = ROOT / "code" / "03_context.py"


def _load_function(name, namespace=None):
    tree = ast.parse(CONTEXT_NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {} if namespace is None else dict(namespace)
    exec(compile(module, str(CONTEXT_NOTEBOOK), "exec"), scope)
    return scope[name]


IN_WINDOW = _load_function("in_window_expr", {"pl": pl})
OFFSET_BIN_GRID = _load_function("offset_bin_grid")


def test_template_has_explicit_study_windows():
    config = json.loads((ROOT / "config" / "config_template.json").read_text())
    assert config["imv_window_minutes"] == 60
    assert config["sedation_window_minutes"] == 5
    assert "context_window_minutes" not in config


@pytest.mark.parametrize(
    ("offset", "inside"),
    [
        (-5.001, False),
        (-5.0, True),
        (0.0, True),
        (5.0, True),
        (5.001, False),
    ],
)
def test_sedation_window_is_inclusive_at_five_minutes(offset, inside):
    got = (
        pl.DataFrame({"offset_minutes": [offset]})
        .select(IN_WINDOW("offset_minutes", 5.0).alias("inside"))
        .item()
    )
    assert got is inside


def test_imv_and_sedation_have_independent_bin_grids():
    assert OFFSET_BIN_GRID(60.0, 5) == (
        24,
        [f"[{start},{start + 5})" for start in range(-60, 55, 5)] + ["[55,60]"],
        12,
    )
    assert OFFSET_BIN_GRID(5.0, 5) == (2, ["[-5,0)", "[0,5]"], 1)


def test_production_filters_use_their_own_configured_windows():
    source = CONTEXT_NOTEBOOK.read_text()
    assert 'in_window_expr("imv_offset_minutes", IMV_WINDOW_MINUTES)' in source
    assert 'in_window_expr("_offset_minutes_raw", SEDATION_WINDOW_MINUTES)' in source
    assert source.index('in_window_expr("_offset_minutes_raw"') < source.index(
        'offset_minutes=pl.col("_offset_minutes_raw").round(3)'
    )
