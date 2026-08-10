"""The n >= 10 minimum cell rule, applied to everything written to final_no_phi.

The ONLY shared module in this project. Spec P23 records why this one is shared
when nothing else is: a suppression bug is a disclosure failure, not an analysis
failure, and it has to be impossible rather than merely unlikely.

The rule (spec §8):
  * a published count of 1..9 is suppressed
  * suppression drops the WHOLE ROW, not the cell -- a blanked cell in a table
    whose margins are published is often recoverable by subtraction
  * a count of exactly ZERO is published -- it identifies nobody, and dropping it
    would turn "this never happened" into "this is missing"
  * nothing is ever silent: what was dropped is printed
"""

import polars as pl

MIN_CELL = 10


def small_cell_mask(df, count_cols, min_cell=MIN_CELL):
    """True for rows that must not be published."""
    for col in count_cols:
        assert col in df.columns, f"count column {col!r} is not in the frame"
    mask = pl.lit(False)
    for col in count_cols:
        mask = mask | ((pl.col(col) > 0) & (pl.col(col) < min_cell))
    return df.select(mask.alias("_m")).get_column("_m")


def apply_min_cell(df, count_cols, label, min_cell=MIN_CELL):
    """Split a frame into (publishable, suppressed). Neither is written here."""
    mask = small_cell_mask(df, count_cols, min_cell)
    return df.filter(~mask), df.filter(mask)


def publish(df, path, count_cols, label, min_cell=MIN_CELL):
    """Suppress, write the survivors to `path` as CSV, report the loss, return them.

    Every write to final_no_phi goes through this function. Writing a CSV to that
    directory by any other route is a bug.
    """
    kept, dropped = apply_min_cell(df, count_cols, label, min_cell)
    if dropped.height:
        total = sum(dropped.get_column(c).sum() for c in count_cols)
        print(
            f"  [{label}] {dropped.height} row(s) suppressed under the n>={min_cell} "
            f"rule on {count_cols}; {total} observation(s) withheld"
        )
        print(dropped)
    kept.write_csv(path)
    print(f"  [{label}] {kept.height} row(s) -> {path}")
    return kept
