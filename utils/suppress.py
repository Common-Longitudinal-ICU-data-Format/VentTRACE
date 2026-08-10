"""The row-level disclosure boundary, applied to everything written to final_no_phi.

The ONLY shared module in this project. Spec P23 records why this one is shared
when nothing else is: a disclosure bug is a different kind of failure than an
analysis bug, and it has to be impossible rather than merely unlikely.

The rule (spec P21, P23, amended 0992a5c):
  * the disclosure boundary is row-level versus aggregate, not cell size -- an
    aggregate count is published at its true value, including counts of 1 to 9.
    A binned count is a property of a bin, not of a person.
  * what may never leave the site is a row that describes one person: an
    identifier column, or a table carrying a timestamp -- an aggregate has no
    timestamp, and every row-level artifact in this study does.
  * nothing is filtered, nothing is silent: every write is printed.

The n>=10 minimum-cell rule this module used to enforce is retired (P21, P24
withdrawn). It bought deniability for a single cell and paid for it in a
machinery of secondary suppression that produced its own leaks and, even once
those were closed, delivered only a bound on the withheld value rather than the
deniability it advertised. A rule that must be defended by a second rule that
must be defended by a third is not protecting anything. What protects the
patient is the prohibition below, which has never moved: nothing row-level, no
`patient_id`, no record that describes one person, ever leaves the site.

The count-column requirement this module originally carried alongside the
identifier check is also gone (spec P23, amended 0992a5c). It was wrong in both
directions: it blocked `cohort_qc.csv` (columns `stat,value`, no `n`/`n_*`
column, plainly shareable) and it did not block what it was written for --
dropping the four identifier columns from `index_context.parquet` leaves a
2,117-row row-level frame that still carries `n_admins`, so it satisfied "has a
column starting with `n_`" while being pure row detail with raw timestamps and
dose lists. The datetime guard below catches that construction via `t_dttm` and
cannot be satisfied by adding a column.
"""

import polars as pl

_EXPLICIT_ID_COLUMNS = {"patient_id", "hospitalization_id", "encounter_block", "p_num"}
_ID_EXCEPTIONS = {"cohort_run_id"}  # a provenance stamp, not an identifier
_DATETIME_DTYPES = (pl.Datetime, pl.Date)  # pl.Datetime covers naive AND tz-aware


def publish(df, path, label):
    """Write `df` to `path` as CSV, report what was written, and return it unchanged.

    Every write to final_no_phi goes through this function. Writing a CSV to that
    directory by any other route is a bug.

    Refuses (raises AssertionError) rather than writes when:
      * the frame carries an identifier column -- any of `patient_id`,
        `hospitalization_id`, `encounter_block`, `p_num`, or any column whose name
        ends in `_id`. `cohort_run_id` is a provenance stamp, not an identifier,
        and is exempted.
      * the frame carries a datetime column -- checked on dtype (`pl.Datetime`,
        naive or timezone-aware, and `pl.Date`), never on column name. An
        aggregate has no timestamp; every row-level artifact in this study does.

    Nothing is filtered: a row with n = 3 is written, a row with n = 0 is written.
    """
    id_cols = sorted(
        c
        for c in df.columns
        if c not in _ID_EXCEPTIONS
        and (c in _EXPLICIT_ID_COLUMNS or c.endswith("_id"))
    )
    assert not id_cols, (
        f"[{label}] refusing to publish: frame carries identifier column(s) "
        f"{id_cols} -- nothing row-level may leave the site (spec P21/P23)"
    )

    datetime_cols = sorted(
        c for c, dtype in df.schema.items() if isinstance(dtype, _DATETIME_DTYPES)
    )
    assert not datetime_cols, (
        f"[{label}] refusing to publish: frame carries datetime column(s) "
        f"{datetime_cols} -- an aggregate has no timestamp, and every row-level "
        "artifact in this study does (spec P21/P23)"
    )

    df.write_csv(path)
    print(f"  [{label}] {df.height} row(s) -> {path}")
    return df
