"""ADT anchor attribution and procedural-location exclusion contracts."""

import ast
from datetime import datetime
from pathlib import Path

import polars as pl


ROOT = Path(__file__).parent.parent
INDEX_NOTEBOOK = ROOT / "code" / "02_index_paralytic.py"


def _load_function(name):
    tree = ast.parse(INDEX_NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {"pl": pl}
    exec(compile(module, str(INDEX_NOTEBOOK), "exec"), scope)
    return scope[name]


RESOLVE_INDEX_LOCATIONS = _load_function("resolve_index_locations")
RETAIN_NONPROCEDURAL_INDEXES = _load_function("retain_nonprocedural_indexes")


def _dt(hour, minute=0):
    return datetime(2024, 1, 1, hour, minute)


def test_location_resolution_uses_half_open_intervals_and_keeps_unknown():
    indexes = pl.DataFrame(
        {
            "index_paralytic_id": ["A_P1", "B_P1", "C_P1", "D_P1"],
            "encounter_block": ["A", "B", "C", "D"],
            "t_dttm": [_dt(10), _dt(12), _dt(10), _dt(10)],
        }
    )
    adt = pl.DataFrame(
        {
            "encounter_block": ["A", "A", "B", "C", "C"],
            "hospital_id": ["H1", "H1", "H1", "H1", "H2"],
            "location_category": ["icu", "procedural", "ward", "icu", "procedural"],
            "in_dttm": [_dt(8), _dt(10), _dt(8), _dt(8), _dt(9)],
            "out_dttm": [_dt(10), _dt(11), None, _dt(11), _dt(11)],
        }
    )

    resolved = RESOLVE_INDEX_LOCATIONS(indexes, adt).sort("index_paralytic_id")

    assert resolved.get_column("_location_category_at_index").to_list() == [
        "procedural",  # exact out_dttm is excluded; exact in_dttm is included
        "ward",  # null out_dttm is open-ended
        "icu",  # earliest-starting interval wins when ADT rows overlap
        "unknown",  # absence of a covering interval is retained explicitly
    ]


def test_procedural_exclusion_renumbers_retained_indexes_within_each_block():
    located = pl.DataFrame(
        {
            "index_paralytic_id": ["A_P1", "A_P2", "A_P3", "B_P1"],
            "encounter_block": ["A", "A", "A", "B"],
            "p_num": [1, 2, 3, 1],
            "t_dttm": [_dt(8), _dt(9), _dt(10), _dt(11)],
            "_location_category_at_index": [
                "procedural",
                "unknown",
                "icu",
                "procedural",
            ],
        }
    )

    retained = RETAIN_NONPROCEDURAL_INDEXES(located).sort(
        ["encounter_block", "p_num"]
    )

    assert retained.select("encounter_block", "p_num", "index_paralytic_id").rows() == [
        ("A", 1, "A_P1"),
        ("A", 2, "A_P2"),
    ]
    assert retained.get_column("t_dttm").to_list() == [_dt(9), _dt(10)]
