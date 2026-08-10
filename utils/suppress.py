"""The row-level disclosure boundary, applied to everything written to final_no_phi.

The ONLY shared module in this project. Spec P23 records why this one is shared
when nothing else is: a disclosure bug is a different kind of failure than an
analysis bug, and it has to be impossible rather than merely unlikely.

The rule (spec P21, P23):
  * the disclosure boundary is row-level versus aggregate, not cell size -- an
    aggregate count is published at its true value, including counts of 1 to 9.
    A binned count is a property of a bin, not of a person.
  * what may never leave the site is a row that describes one person: an
    identifier column, or a table of pure row detail with the identifiers
    stripped (still row detail, just anonymised detail).
  * nothing is filtered, nothing is silent: every write is printed.

The n>=10 minimum-cell rule this module used to enforce is retired (P21, P24
withdrawn). It bought deniability for a single cell and paid for it in a
machinery of secondary suppression that produced its own leaks and, even once
those were closed, delivered only a bound on the withheld value rather than the
deniability it advertised. A rule that must be defended by a second rule that
must be defended by a third is not protecting anything. What protects the
patient is the prohibition below, which has never moved: nothing row-level, no
`patient_id`, no record that describes one person, ever leaves the site.
"""

import polars as pl

_EXPLICIT_ID_COLUMNS = {"patient_id", "hospitalization_id", "encounter_block", "p_num"}
_ID_EXCEPTIONS = {"cohort_run_id"}  # a provenance stamp, not an identifier


def publish(df, path, label):
    """Write `df` to `path` as CSV, report what was written, and return it unchanged.

    Every write to final_no_phi goes through this function. Writing a CSV to that
    directory by any other route is a bug.

    Refuses (raises AssertionError) rather than writes when:
      * the frame carries an identifier column -- any of `patient_id`,
        `hospitalization_id`, `encounter_block`, `p_num`, or any column whose name
        ends in `_id`. `cohort_run_id` is a provenance stamp, not an identifier,
        and is exempted.
      * the frame has no aggregate count column at all -- no column named `n` or
        starting with `n_`. A table of pure row detail with the ids stripped is
        still row detail.

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

    has_count_col = any(c == "n" or c.startswith("n_") for c in df.columns)
    assert has_count_col, (
        f"[{label}] refusing to publish: frame has no aggregate count column "
        "(no column named 'n' or starting with 'n_') -- a table of pure row "
        "detail with the ids stripped is still row detail (spec P21/P23)"
    )

    df.write_csv(path)
    print(f"  [{label}] {df.height} row(s) -> {path}")
    return df
