"""Pins P37's mortality rules in `04_covariates.py`.

`death_dttm` in the CLIF `patient` table is a PATIENT-level date and can be
registry-sourced. Unbounded, "death_dttm is not null OR discharge_category is
expired" fires for someone discharged alive who died months later at home, and
publishes it as in-hospital mortality. The bound is therefore part of the
definition, not a refinement of it.

ICU attribution is by death TIME inside an ADT icu interval (P37, chosen over
last-known-location). Its cost is that a block flagged dead by discharge_category
alone cannot be attributed either way; that count is published as its own row
rather than being absorbed into either numerator, which is the same reasoning
that put `no_device_record` beside `no_transition_in_window` in sub-analysis D.

Run:  uv run pytest tests/test_mortality_bound.py -v
"""

import ast
import datetime
from pathlib import Path

import polars as pl

NOTEBOOK = Path(__file__).parent.parent / "code" / "04_covariates.py"
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


resolve_mortality = _load_from_notebook("resolve_mortality")

ADMIT = datetime.datetime(2024, 1, 1, 8, 0)
DISCH = datetime.datetime(2024, 1, 10, 8, 0)


def _block(death_dttm, discharge_category, icu_in=None, icu_out=None):
    """One block, one member hospitalization, optionally one ADT icu interval."""
    return pl.DataFrame(
        {
            "encounter_block": [1],
            "admission_dttm": [ADMIT],
            "discharge_dttm": [DISCH],
            "discharge_category": [discharge_category],
            "death_dttm": [death_dttm],
            "icu_in_dttm": [icu_in],
            "icu_out_dttm": [icu_out],
        },
        schema={
            "encounter_block": pl.Int32,
            "admission_dttm": pl.Datetime,
            "discharge_dttm": pl.Datetime,
            "discharge_category": pl.String,
            "death_dttm": pl.Datetime,
            "icu_in_dttm": pl.Datetime,
            "icu_out_dttm": pl.Datetime,
        },
    )


def test_death_after_discharge_is_not_in_hospital_mortality():
    """The registry-linked case the bound exists for."""
    later = DISCH + datetime.timedelta(days=90)
    got = resolve_mortality(_block(later, "home")).to_dicts()[0]
    assert got["hospital_mortality"] is False
    assert got["icu_mortality"] is False
    assert got["icu_mortality_undeterminable"] is False


def test_death_before_admission_is_not_in_hospital_mortality():
    earlier = ADMIT - datetime.timedelta(days=1)
    got = resolve_mortality(_block(earlier, "home")).to_dicts()[0]
    assert got["hospital_mortality"] is False


def test_death_inside_the_stay_is_in_hospital_mortality():
    inside = ADMIT + datetime.timedelta(days=3)
    got = resolve_mortality(_block(inside, "expired")).to_dicts()[0]
    assert got["hospital_mortality"] is True


def test_expired_category_alone_is_in_hospital_mortality():
    """No death_dttm at all, but the encounter says expired."""
    got = resolve_mortality(_block(None, "expired")).to_dicts()[0]
    assert got["hospital_mortality"] is True


def test_expired_category_alone_is_icu_undeterminable():
    """P37's stated cost: no death time means no ICU attribution either way."""
    got = resolve_mortality(_block(None, "expired")).to_dicts()[0]
    assert got["icu_mortality"] is False
    assert got["icu_mortality_undeterminable"] is True


def test_death_inside_an_icu_interval_is_icu_mortality():
    inside = ADMIT + datetime.timedelta(days=3)
    got = resolve_mortality(
        _block(
            inside,
            "expired",
            icu_in=ADMIT + datetime.timedelta(days=2),
            icu_out=ADMIT + datetime.timedelta(days=4),
        )
    ).to_dicts()[0]
    assert got["icu_mortality"] is True
    assert got["icu_mortality_undeterminable"] is False


def test_death_outside_every_icu_interval_is_not_icu_mortality():
    """Died on the floor after an ICU stay: in-hospital, not ICU."""
    inside = ADMIT + datetime.timedelta(days=6)
    got = resolve_mortality(
        _block(
            inside,
            "expired",
            icu_in=ADMIT + datetime.timedelta(days=2),
            icu_out=ADMIT + datetime.timedelta(days=4),
        )
    ).to_dicts()[0]
    assert got["hospital_mortality"] is True
    assert got["icu_mortality"] is False
    assert got["icu_mortality_undeterminable"] is False


def test_survivor_is_not_dead_by_any_route():
    got = resolve_mortality(_block(None, "home")).to_dicts()[0]
    assert got["hospital_mortality"] is False
    assert got["icu_mortality"] is False
    assert got["icu_mortality_undeterminable"] is False
