"""Pins the row-level disclosure boundary of `utils/suppress.py` (spec P21, P23,
amended 0992a5c).

This is the only shared module in the project and the reason it is shared is
recorded in P23: duplicating *analysis* logic risks correlated errors that look
like agreement; duplicating the *disclosure* check risks one notebook writing a
file the other would have refused, which is a disclosure failure and has to be
impossible rather than merely unlikely.

The rule, stated once: an aggregate count is publishable at its true value,
including counts of 1 to 9 (P21 supersedes the n>=10 cell rule). What may never
leave the site is a row that describes one person -- an identifier column, or a
row carrying a timestamp, since an aggregate has no timestamp and every
row-level artifact in this study does. `publish()` is the single route into
`final_no_phi/` and is a schema guard (column names for identifiers, column
dtypes for datetimes), not a cell-count filter: nothing it writes is ever
altered.

The count-column requirement ("must have a column named `n` or starting with
`n_`") this module originally carried is WITHDRAWN (spec P23, amended
0992a5c): it blocked `cohort_qc.csv` (columns `stat,value`) and did not block
what it was written for -- `index_context.parquet` with its identifier columns
dropped still carries `n_admins`, so it satisfied the count-column check while
being pure row detail with raw timestamps. The datetime guard below replaces
it.

Run:  uv run pytest tests/test_publish_guard.py -v
"""

import datetime

import polars as pl
import pytest

from utils.suppress import publish


def _agg_frame():
    """A frame that clears both guards: no identifier column, no datetime column."""
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
    """cohort_run_id is a provenance stamp, not an identifier -- the one deliberate,
    EXACT-NAME exception to the *_id refusal."""
    path = tmp_path / "out.csv"
    df = pl.DataFrame({"cohort_run_id": ["2026-08-06", "2026-08-06"], "n": [5, 5]})
    written = publish(df, path, "t")
    assert written.equals(df)
    assert pl.read_csv(path).get_column("cohort_run_id").to_list() == [
        "2026-08-06",
        "2026-08-06",
    ]


@pytest.mark.parametrize("run_id_col", ["run_id", "xyz_run_id"])
def test_a_bare_or_prefixed_run_id_column_is_still_refused(run_id_col, tmp_path):
    """The cohort_run_id exemption is an EXACT name, not a `*run_id` suffix pattern --
    narrowing the *_id refusal to `endswith('run_id')` would wrongly admit both of
    these, and both still describe a *_id-shaped column that isn't the one named
    exemption."""
    df = pl.DataFrame({run_id_col: [1, 2], "n": [5, 5]})
    with pytest.raises(AssertionError, match=run_id_col):
        publish(df, tmp_path / "out.csv", "t")


def test_a_frame_with_no_count_column_is_now_accepted(tmp_path):
    """The count-column requirement is withdrawn (spec P23, amended 0992a5c): it
    blocked cohort_qc.csv (columns stat,value) without blocking anything the
    datetime guard doesn't already catch. This is that exact shape."""
    path = tmp_path / "out.csv"
    df = pl.DataFrame({"stat": ["min_age", "stitch_hours"], "value": ["18", "6"]})
    written = publish(df, path, "t")
    assert written.equals(df)
    assert pl.read_csv(path).get_column("stat").to_list() == ["min_age", "stitch_hours"]


def test_a_naive_datetime_column_is_refused(tmp_path):
    df = pl.DataFrame({"t_dttm": [datetime.datetime(2024, 1, 1)], "n": [5]})
    with pytest.raises(AssertionError, match="t_dttm"):
        publish(df, tmp_path / "out.csv", "t")


def test_a_timezone_aware_datetime_column_is_refused(tmp_path):
    """Checked on dtype, not name: a tz-aware Datetime is still `pl.Datetime`."""
    df = pl.DataFrame(
        {"admin_dttm": [datetime.datetime(2024, 1, 1)], "n": [5]}
    ).with_columns(pl.col("admin_dttm").dt.replace_time_zone("US/Eastern"))
    assert isinstance(df.schema["admin_dttm"], pl.Datetime)
    with pytest.raises(AssertionError, match="admin_dttm"):
        publish(df, tmp_path / "out.csv", "t")


def test_a_date_column_is_refused(tmp_path):
    df = pl.DataFrame({"d": [datetime.date(2024, 1, 1)], "n": [5]})
    with pytest.raises(AssertionError, match="d"):
        publish(df, tmp_path / "out.csv", "t")


def test_a_plain_string_or_numeric_column_named_like_a_date_is_not_a_datetime(tmp_path):
    """The guard checks dtype, never column name -- a string column happening to be
    called `admit_date` is not what P23 refuses."""
    df = pl.DataFrame({"admit_date": ["2024-01-01"], "n": [5]})
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
