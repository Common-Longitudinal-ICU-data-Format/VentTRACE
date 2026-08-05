import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from pathlib import Path

    import polars as pl

    import marimo as mo

    return Path, json, mo, pl


@app.cell
def _(mo):
    mo.md(
        """
        # 02 — Index IMV and CONSORT B

        `01` guarantees every cohort encounter has a t0. It does **not** guarantee that t0
        is an intubation we can see happen. Three quite different situations all produce a
        first charted IMV row:

        - the patient was intubated here, and the record documents the airway before and
          after — t0 is a real transition;
        - the patient arrived already intubated, so the record opens mid-ventilation and t0
          is merely where charting started;
        - the record is too thin around t0 to tell the two apart.

        Only the first supports the question this study asks. This notebook applies the M2
        symmetric 2/2 rule at t0 as an **index qualifier**, emits its own CONSORT, and
        writes a class for every cohort encounter.

        ```
        index qualifies  ==  not IMV(i-2) and not IMV(i-1) and IMV(i) and IMV(i+1)
        ```

        Boundary policy is `B_strict`: if row `i-2`, `i-1` or `i+1` does not exist, the
        corresponding term is false and the index does not qualify.

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` §5.9–§5.12
        """
    )
    return


@app.cell
def _(Path, json):
    _config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(_config_path, "r") as _f:
        config = json.load(_f)

    SITE = config["site_name"]
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"site   : {SITE}")
    print(f"inputs : {PHI_DIR}")
    return PHI_DIR, SHARE_DIR, SITE


@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")
    resp_waterfall = pl.read_parquet(PHI_DIR / "cohort_resp_waterfall.parquet")

    COHORT_RUN_ID = cohort_index.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"cohort_index carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    print(f"cohort_run_id      : {COHORT_RUN_ID}")
    print(f"cohort encounters  : {cohort_index.height:,}   (N*)")
    print(f"waterfalled rows   : {resp_waterfall.height:,}")
    return COHORT_RUN_ID, cohort_index, resp_waterfall


@app.cell
def _(mo):
    mo.md(
        """
        ## Assemble the transition sequence per encounter block

        The waterfall ran per `hospitalization_id`, but the sequence evaluated here is
        ordered **within the block** across all its hospitalizations. That is what makes
        stitching effective: an ED presentation and the inpatient admission stitched to it
        form one continuous respiratory record.
        """
    )
    return


@app.cell
def _(pl, resp_waterfall):
    # `hospitalization_id` is included in the sort only to break ties deterministically
    # when two hospitalizations in one block share a timestamp.
    resp_seq = (
        resp_waterfall.sort(["encounter_block", "recorded_dttm", "hospitalization_id"])
        .with_columns(
            row_idx=pl.int_range(pl.len()).over("encounter_block"),
            is_imv=(pl.col("device_category") == "IMV"),
        )
        .with_columns(
            next_is_imv=pl.col("is_imv").shift(-1).over("encounter_block"),
        )
    )

    print(f"rows sequenced : {resp_seq.height:,}")
    print(f"blocks         : {resp_seq.get_column('encounter_block').n_unique():,}")
    return (resp_seq,)


@app.cell
def _(pl, resp_seq):
    # The index row is the FIRST IMV row in the block — the same row whose recorded_dttm
    # 01 published as t0_dttm. Assert that rather than assume it.
    index_row = (
        resp_seq.filter(pl.col("is_imv"))
        .sort(["encounter_block", "row_idx"])
        .group_by("encounter_block")
        .agg(
            index_row_idx=pl.col("row_idx").first(),
            index_dttm=pl.col("recorded_dttm").first(),
            index_next_is_imv=pl.col("next_is_imv").first(),
        )
    )

    print(f"blocks with an IMV row : {index_row.height:,}")
    return (index_row,)


@app.cell
def _(cohort_index, index_row, pl):
    idx = cohort_index.join(index_row, on="encounter_block", how="left")

    _n_missing = idx.get_column("index_row_idx").null_count()
    assert _n_missing == 0, f"{_n_missing} cohort encounters have no IMV row in the waterfall"

    _n_mismatch = idx.filter(pl.col("index_dttm") != pl.col("t0_dttm")).height
    assert _n_mismatch == 0, (
        f"{_n_mismatch} encounters where the first IMV row found here disagrees with "
        "t0_dttm from 01. The two must be the same row."
    )

    print("OK — the index row matches t0_dttm from 01 for every encounter.")
    return (idx,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Why the lookback terms are automatic

        t0 is defined as the **earliest** row with `device_category = 'IMV'`, so no row
        preceding it can be IMV. `not IMV(i-1) and not IMV(i-2)` is therefore satisfied for
        free whenever those rows exist, and the M2 rule reduces to a **lookback-depth test
        plus a sustain test**.

        This is why an earlier draft's `prior_row_imv` failure class was unreachable and
        was removed. The assertion below proves the reduction on the actual data rather
        than leaving it as an argument on paper.
        """
    )
    return


@app.cell
def _(idx, pl, resp_seq):
    # Prove it: no row before the index row is IMV, in any block.
    _violations = (
        resp_seq.join(
            idx.select(["encounter_block", "index_row_idx"]), on="encounter_block", how="inner"
        )
        .filter(pl.col("row_idx") < pl.col("index_row_idx"))
        .filter(pl.col("is_imv"))
        .height
    )

    assert _violations == 0, (
        f"{_violations} rows before t0 are IMV — t0 is not the earliest IMV row and the "
        "taxonomy in §5.10 does not hold."
    )
    print("OK — no IMV row precedes t0 in any block. `prior_row_imv` is unreachable, as designed.")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## The index taxonomy

        Every cohort encounter gets exactly one `index_class`, assigned in this order.
        The first two are **observability** failures — the data needed to see a transition
        is not there. The third is a **judgment** failure under M2 — the data is there and
        the rule declines it.
        """
    )
    return


@app.cell
def _(idx, pl):
    index_imv = idx.with_columns(
        index_class=pl.when(pl.col("index_row_idx") == 0)
        .then(pl.lit("arrived_intubated"))
        .when(pl.col("index_row_idx") == 1)
        .then(pl.lit("insufficient_lookback"))
        .when(pl.col("index_next_is_imv").is_null() | ~pl.col("index_next_is_imv"))
        .then(pl.lit("imv_not_sustained"))
        .otherwise(pl.lit("qualified"))
    ).with_columns(index_qualified=pl.col("index_class") == "qualified")

    index_class_counts = (
        index_imv.get_column("index_class")
        .value_counts()
        .with_columns(pct=100.0 * pl.col("count") / index_imv.height)
        .sort("count", descending=True)
    )

    print(index_class_counts)
    return index_class_counts, index_imv


@app.cell
def _(mo):
    mo.md(
        """
        ## CONSORT B — index

        A headline result, not a preprocessing note. The `arrived_intubated` rate is the
        number to read first: the methods catalog (§9.4) reports roughly 31% across sites,
        so a site landing far from that has either a stitching problem (see `cohort_qc.csv`
        from `01`) or a genuinely different referral pattern — and which one it is must be
        settled before the index set is trusted.
        """
    )
    return


@app.cell
def _(index_imv, pl):
    consort_rows = []

    def _add(step, df, prev_n, note=""):
        consort_rows.append(
            {
                "step": step,
                "n_encounters": df.height,
                "n_patients": df.get_column("patient_id").n_unique(),
                "n_excluded": 0 if prev_n is None else prev_n - df.height,
                "note": note,
            }
        )
        _r = consort_rows[-1]
        print(
            f"{step:<44} encounters={_r['n_encounters']:>10,}  "
            f"patients={_r['n_patients']:>10,}  excluded={_r['n_excluded']:>9,}"
        )
        return df.height

    _n = _add("analytic cohort from 01", index_imv, None, "N*")

    _step1 = index_imv.filter(pl.col("index_class") != "arrived_intubated")
    _n = _add("exclude: arrived_intubated", _step1, _n, "t0 is the block's first respiratory row")

    _step2 = _step1.filter(pl.col("index_class") != "insufficient_lookback")
    _n = _add("exclude: insufficient_lookback", _step2, _n, "fewer than two rows precede t0")

    _step3 = _step2.filter(pl.col("index_class") != "imv_not_sustained")
    _n = _add("exclude: imv_not_sustained", _step3, _n, "row i+1 absent or non-IMV")

    _add("INDEX IMV SET", _step3, None, "N**")

    consort_index_df = pl.DataFrame(consort_rows)
    return (consort_index_df,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Outputs

        `index_imv.parquet` holds **one row per cohort encounter, not per qualified
        encounter.** Keeping the excluded rows is deliberate: `06` runs the specificity
        probe over them, where every method detection is a false positive by construction.
        The methods carry `index_class` through and never filter on it themselves — the
        single subsetting step lives in `06`.
        """
    )
    return


@app.cell
def _(
    COHORT_RUN_ID,
    PHI_DIR,
    SHARE_DIR,
    consort_index_df,
    index_class_counts,
    index_imv,
    pl,
):
    index_imv_out = index_imv.select(
        [
            "encounter_block",
            "patient_id",
            "intubation_episode_id",
            "cohort_run_id",
            "index_class",
            "index_qualified",
            "list_hospitalization_id",
            "n_hospitalizations",
            "admission_dttm",
            "age_at_admission",
            "t0_dttm",
            "window_start",
            "window_end",
        ]
    ).sort("encounter_block")

    assert index_imv_out.height == index_imv.height, "rows lost in the output projection"
    assert index_imv_out.get_column("index_class").null_count() == 0, "unclassified encounters"

    index_imv_out.write_parquet(PHI_DIR / "index_imv.parquet")
    consort_index_df.write_csv(SHARE_DIR / "consort_index.csv")

    index_class_rates = index_class_counts.select(
        pl.lit(COHORT_RUN_ID).alias("cohort_run_id"),
        "index_class",
        pl.col("count").alias("n"),
        pl.col("pct").round(2).alias("pct_of_cohort"),
    )
    index_class_rates.write_csv(SHARE_DIR / "index_class_rates.csv")

    _n_qualified = index_imv_out.filter(pl.col("index_qualified")).height
    print(f"index_imv.parquet       {index_imv_out.height:,} rows -> {PHI_DIR}")
    print(f"  of which qualified    {_n_qualified:,}   (N**)")
    print(f"consort_index.csv       {consort_index_df.height} steps -> {SHARE_DIR}")
    print(f"index_class_rates.csv   {index_class_rates.height} classes")
    print("\nCONSORT B")
    print(consort_index_df)
    print("\nindex class rates")
    print(index_class_rates)
    return


if __name__ == "__main__":
    app.run()
