"""Pins the row-level disclosure boundary of `utils/suppress.py` (spec P21, P23).

This is the only shared module in the project and the reason it is shared is
recorded in P23: duplicating *analysis* logic risks correlated errors that look
like agreement; duplicating the *disclosure* check risks one notebook writing a
file the other would have refused, which is a disclosure failure and has to be
impossible rather than merely unlikely.

The rule, stated once: an aggregate count is publishable at its true value,
including counts of 1 to 9 (P21 supersedes the n>=10 cell rule). What may never
leave the site is a row that describes one person -- an identifier column, or a
table of pure row detail with the identifiers stripped, which is still row
detail. `publish()` is the single route into `final_no_phi/` and is a
column-name guard, not a cell-count filter: nothing it writes is ever altered.

Run:  uv run pytest tests/test_publish_guard.py -v
"""

import polars as pl
import pytest

from utils.suppress import publish


def _agg_frame():
    """A frame that clears both guards: no identifier column, has a count column."""
    return pl.DataFrame({"bin": ["a", "b", "c"], "n": [0, 3, 50]})


@pytest.mark.parametrize(
    "id_col",
    ["patient_id", "hospitalization_id", "encounter_block", "p_num"],
)
def test_each_explicit_identifier_column_is_refused(id_col, tmp_path):
    df = pl.DataFrame({id_col: [1, 2], "n": [5, 5]})
    with pytest.raises(AssertionError, match=id_col):
        publish(df, tmp_path / "out.csv", "t")


def test_an_arbitrary_id_suffix_column_is_refused_even_off_the_explicit_list(tmp_path):
    """The explicit names are examples, not the whole rule: any `*_id` column is a
    disclosure risk, named or not."""
    df = pl.DataFrame({"provider_id": [1, 2], "n": [5, 5]})
    with pytest.raises(AssertionError, match="provider_id"):
        publish(df, tmp_path / "out.csv", "t")


def test_cohort_run_id_is_accepted(tmp_path):
    """cohort_run_id is a provenance stamp, not an identifier -- the one deliberate
    exception to the *_id refusal."""
    path = tmp_path / "out.csv"
    df = pl.DataFrame({"cohort_run_id": ["2026-08-06", "2026-08-06"], "n": [5, 5]})
    written = publish(df, path, "t")
    assert written.equals(df)
    assert pl.read_csv(path).get_column("cohort_run_id").to_list() == [
        "2026-08-06",
        "2026-08-06",
    ]


def test_a_frame_with_no_count_column_is_refused(tmp_path):
    """No column named `n` or starting with `n_` -- a table of pure row detail with
    the ids already stripped is still row detail."""
    df = pl.DataFrame({"bin": ["a", "b"], "median_dose": [10.0, 20.0]})
    with pytest.raises(AssertionError):
        publish(df, tmp_path / "out.csv", "t")


def test_an_n_prefixed_column_other_than_n_itself_satisfies_the_guard(tmp_path):
    df = pl.DataFrame({"bin": ["a"], "n_blocks": [5]})
    written = publish(df, tmp_path / "out.csv", "t")
    assert written.height == 1


def test_an_accepted_frame_is_written_byte_for_byte_including_1_to_9_and_zero(tmp_path):
    """Nothing is filtered: a row with n = 3 is written, a row with n = 0 is written."""
    path = tmp_path / "out.csv"
    df = _agg_frame()
    publish(df, path, "t")
    written = pl.read_csv(path)
    assert written.get_column("n").to_list() == [0, 3, 50]
    assert written.get_column("bin").to_list() == ["a", "b", "c"]


def test_the_returned_frame_equals_the_input(tmp_path):
    df = _agg_frame()
    returned = publish(df, tmp_path / "out.csv", "t")
    assert returned.equals(df)


def test_publish_reports_what_it_wrote(tmp_path, capsys):
    publish(_agg_frame(), tmp_path / "out.csv", "gap_distribution")
    out = capsys.readouterr().out
    assert "gap_distribution" in out
    assert "3 row" in out
