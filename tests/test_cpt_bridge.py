"""Pins the CPT-to-block bridge of `06_reference_cpt.py` (spec §4, P29).

CPT rows live on `hospitalization_id`; the analysis lives on `encounter_block`.
A block stitches up to 4 hospitalizations (max_hosp_per_block = 4 at MIMIC), so
"CPT present" means present on ANY member. Two things can go wrong silently:

  * a code on a hospitalization OUTSIDE the block leaking in, which would
    manufacture agreement;
  * a code on a member other than the first being missed, which would
    manufacture disagreement.

Both are checked. The bridge itself is the explode-and-drop of the 2026-08-10
spec §6.1 -- the only sanctioned place `hospitalization_id` may be named.

Run:  uv run pytest tests/test_cpt_bridge.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl

NOTEBOOK = Path(__file__).parent.parent / "code" / "06_reference_cpt.py"
NOTEBOOK_TREE = ast.parse(NOTEBOOK.read_text())


def _load_from_notebook(name, namespace=None):
    found = [
        node
        for node in ast.walk(NOTEBOOK_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one def {name} in {NOTEBOOK.name}, found {len(found)}"
    )
    ns = {"pl": pl}
    ns.update(namespace or {})
    exec(compile(ast.Module(body=[found[0]], type_ignores=[]), NOTEBOOK.name, "exec"), ns)
    return ns[name]


cpt_block_flag = _load_from_notebook("cpt_block_flag")

# Block 1 stitches four hospitalizations; block 2 stitches one.
BRIDGE = pl.DataFrame(
    {
        "encounter_block": [1, 1, 1, 1, 2],
        "hospitalization_id": ["h1", "h2", "h3", "h4", "h9"],
    },
    schema={"encounter_block": pl.Int32, "hospitalization_id": pl.String},
)


def _procs(pairs):
    """pairs: list of (hospitalization_id, date)."""
    return pl.DataFrame(
        {
            "hospitalization_id": [h for h, _ in pairs],
            "procedure_date": [d for _, d in pairs],
        },
        schema={"hospitalization_id": pl.String, "procedure_date": pl.Date},
    )


D = datetime.date(2024, 5, 1)


def test_code_on_the_third_member_flags_the_block():
    got = cpt_block_flag(_procs([("h3", D)]), BRIDGE).sort("encounter_block").to_dicts()
    by_block = {r["encounter_block"]: r for r in got}
    assert by_block[1]["has_cpt"] is True
    assert by_block[1]["n_cpt_codes"] == 1


def test_code_on_a_hospitalization_outside_the_block_does_not_leak():
    """h9 belongs to block 2; block 1 must stay negative."""
    got = cpt_block_flag(_procs([("h9", D)]), BRIDGE).sort("encounter_block").to_dicts()
    by_block = {r["encounter_block"]: r for r in got}
    assert by_block[1]["has_cpt"] is False
    assert by_block[1]["n_cpt_codes"] == 0
    assert by_block[2]["has_cpt"] is True


def test_code_on_an_unknown_hospitalization_is_dropped():
    """A procedure row for a hospitalization no block claims contributes nothing.

    The row-count assertion is the load-bearing half: without it a bug that
    manufactured a phantom block with has_cpt=False would satisfy the `all(...)`
    check and pass.
    """
    got = cpt_block_flag(_procs([("h_unknown", D)]), BRIDGE).sort("encounter_block").to_dicts()
    assert [r["encounter_block"] for r in got] == [1, 2], "a phantom block was created"
    assert all(r["has_cpt"] is False for r in got)


def test_multiple_codes_across_members_are_counted_once_per_row():
    got = cpt_block_flag(
        _procs([("h1", D), ("h3", D + datetime.timedelta(days=2))]), BRIDGE
    ).sort("encounter_block").to_dicts()
    by_block = {r["encounter_block"]: r for r in got}
    assert by_block[1]["n_cpt_codes"] == 2
    assert by_block[1]["first_cpt_date"] == D


def test_every_block_in_the_bridge_gets_a_row():
    """A block with no procedure data at all is a published false, not a missing row."""
    got = cpt_block_flag(_procs([]), BRIDGE)
    assert sorted(got.get_column("encounter_block").to_list()) == [1, 2]
    assert got.get_column("has_cpt").to_list() == [False, False]
