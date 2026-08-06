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
            is_imv=(pl.col("device_category") == "imv"),
        )
        .with_columns(
            next_is_imv=pl.col("is_imv").shift(-1).over("encounter_block"),
            # Lookback terms. These are live tests again under D23: t0 is the earliest
            # RAW charted IMV row, so a waterfalled row before it CAN be imv -- that is
            # precisely the prior_row_imv class.
            prev1_is_imv=pl.col("is_imv").shift(1).over("encounter_block"),
            prev2_is_imv=pl.col("is_imv").shift(2).over("encounter_block"),
        )
    )

    print(f"rows sequenced : {resp_seq.height:,}")
    print(f"blocks         : {resp_seq.get_column('encounter_block').n_unique():,}")
    return (resp_seq,)


@app.cell
def _(cohort_index, pl, resp_seq):
    # t0 is a RAW charted timestamp (D23), so the index row is located by MATCHING that
    # timestamp in the waterfalled sequence -- not by taking the first waterfalled IMV row,
    # which may be earlier when the device heuristics fired on a null-device row.
    index_row = (
        cohort_index.select(["encounter_block", "t0_dttm"])
        .join(
            resp_seq.select(
                ["encounter_block", "recorded_dttm", "row_idx", "is_imv",
                 "next_is_imv", "prev1_is_imv", "prev2_is_imv"]
            ),
            left_on=["encounter_block", "t0_dttm"],
            right_on=["encounter_block", "recorded_dttm"],
            how="left",
        )
        .unique(subset=["encounter_block"])
        .rename(
            {
                "row_idx": "index_row_idx",
                "is_imv": "index_is_imv",
                "next_is_imv": "index_next_is_imv",
                "prev1_is_imv": "index_prev1_is_imv",
                "prev2_is_imv": "index_prev2_is_imv",
            }
        )
    )

    _unlocated = index_row.get_column("index_row_idx").null_count()
    assert _unlocated == 0, (
        f"{_unlocated:,} encounters have a t0 timestamp with no waterfalled row. The "
        "waterfall drops all-NA rows, so a charted IMV row should always survive."
    )
    print(f"index rows located in the waterfall sequence : {index_row.height:,}")
    return (index_row,)


@app.cell
def _(cohort_index, index_row, pl):
    idx = cohort_index.join(index_row, on="encounter_block", how="left")

    _n_missing = idx.get_column("index_row_idx").null_count()
    assert _n_missing == 0, f"{_n_missing} cohort encounters have no row at t0 in the waterfall"

    # The row we located is the charted IMV row, so the waterfall must agree it is imv.
    # (The converse is not required: the waterfall may call EARLIER rows imv too, and that
    # is the prior_row_imv class.)
    _n_not_imv = idx.filter(~pl.col("index_is_imv")).height
    assert _n_not_imv == 0, (
        f"{_n_not_imv} encounters where the waterfall does not call the charted IMV row "
        "imv. The two frames disagree about the row t0 came from."
    )

    print("OK — the t0 row is located in the sequence and the waterfall agrees it is imv.")
    return (idx,)


@app.cell
def _(mo):
    mo.md(
        """
        ### The lookback terms are live tests (D23)

        While t0 was the earliest *waterfalled* IMV row, `not IMV(i-1) and not IMV(i-2)`
        was satisfied for free — nothing before the earliest IMV row can be IMV — and the
        `prior_row_imv` class was unreachable.

        Anchoring t0 on the earliest *raw charted* IMV row makes it live again. A
        waterfalled row before t0 **can** be `imv`, and when it is, it means the device
        heuristics inferred ventilation from settings before any clinician charted a
        ventilator. Those encounters are exactly the ones whose t0 would have been dragged
        earlier under the old anchor; now they are labelled instead of silently shifted.
        """
    )
    return


@app.cell
def _(idx, pl, resp_seq):
    # Measure it rather than assert it away: how many encounters have ANY waterfalled imv
    # row before the charted t0? Under the old post-waterfall anchor this was 0 by
    # construction. It is now the population D23 exists to stop mis-anchoring.
    _blocks_with_prior_imv = (
        resp_seq.join(
            idx.select(["encounter_block", "index_row_idx"]), on="encounter_block", how="inner"
        )
        .filter(pl.col("row_idx") < pl.col("index_row_idx"))
        .filter(pl.col("is_imv"))
        .get_column("encounter_block")
        .n_unique()
    )
    print(
        f"encounters with a waterfalled imv row BEFORE the charted t0 : "
        f"{_blocks_with_prior_imv:,} ({100 * _blocks_with_prior_imv / idx.height:.1f}%)"
    )
    print("  under the old anchor every one of these had its t0 pulled earlier (D23)")
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
    # B_strict: a term whose row does not exist is false, so the class is assigned by the
    # first condition that holds, in this order.
    index_imv = idx.with_columns(
        index_class=pl.when(pl.col("index_row_idx") == 0)
        .then(pl.lit("arrived_intubated"))
        .when(pl.col("index_row_idx") == 1)
        .then(pl.lit("insufficient_lookback"))
        .when(
            pl.col("index_prev1_is_imv").fill_null(False)
            | pl.col("index_prev2_is_imv").fill_null(False)
        )
        .then(pl.lit("prior_row_imv"))
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

    _step3 = _step2.filter(pl.col("index_class") != "prior_row_imv")
    _n = _add("exclude: prior_row_imv", _step3, _n, "waterfall says imv before the charted row")

    _step4 = _step3.filter(pl.col("index_class") != "imv_not_sustained")
    _n = _add("exclude: imv_not_sustained", _step4, _n, "row i+1 absent or non-IMV")

    _add("INDEX IMV SET", _step4, None, "N**")

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
