import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from pathlib import Path

    import polars as pl

    from clifpy.tables import PatientProcedures

    import marimo as mo

    return Path, PatientProcedures, json, mo, pl


@app.cell
def _(mo):
    mo.md(
        """
        # 05 — Reference, CPT 31500

        `31500` — *emergency endotracheal intubation*. The single reference in this study,
        and a **partial** one: it is not a peer in the agreement matrix, it is a check
        applied to the methods after they have been compared to each other.

        Two properties bound what it can support, and both are stated here rather than in a
        footnote:

        - **Codes establish presence, never timing.** `procedure_billed_dttm` is read only
          to describe how far the billing date sits from t0, and never used as an event
          time or as a filter. Containment in the encounter comes from the block's
          hospitalization set, not from the clock.
        - **It codes only the emergency case.** Elective and operative airway management is
          not captured at all, and billing completeness varies by site, payer and era. So
          sensitivity computed against it is bounded by *capture*, not by the quality of the
          method under test.

        Which is why **C.1, the capture rate, is computed and printed first.** Where capture
        is low the reference is uninformative at this site and is reported as such rather
        than scored.

        `billing_provider_id` is not read. Neither is `performing_provider_id`.

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` §8
        """
    )
    return


@app.cell
def _(Path, json):
    _config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(_config_path, "r") as _f:
        config = json.load(_f)

    SITE = config["site_name"]
    DATA_DIR = config["data_directory"]
    FILETYPE = config["filetype"]
    TIMEZONE = config["timezone"]
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    REFERENCE_ID = "CPT"
    REFERENCE_CODE = "31500"
    REFERENCE_FORMAT = "cpt"  # compared lower-cased, like every other category (D21)

    print(f"site      : {SITE}")
    print(f"reference : {REFERENCE_ID} {REFERENCE_CODE}")
    return (
        DATA_DIR,
        FILETYPE,
        PHI_DIR,
        REFERENCE_CODE,
        REFERENCE_FORMAT,
        REFERENCE_ID,
        SHARE_DIR,
        TIMEZONE,
    )


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        See `tests/test_clifpy_tz_boundary.py` — `.dt.tz_localize(None)` on a clifpy column
        drops the attached pytz LMT offset rather than the correct one.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(PHI_DIR, pl):
    index_imv = pl.read_parquet(PHI_DIR / "index_imv.parquet")

    COHORT_RUN_ID = index_imv.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"index_imv carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"cohort encounters : {index_imv.height:,}   (N*)")
    return COHORT_RUN_ID, index_imv


@app.cell
def _(index_imv, pl):
    # The same explode-and-drop bridge the methods use (§7): a code billed under ANY
    # hospitalization in the block counts, because the block is what CPT can be resolved to.
    #
    # Block-level, and it stays that way. CPT carries no usable timing (D1), so a code
    # cannot be attributed to one episode of a block rather than another. The fan-out to
    # episodes below is bookkeeping, not a claim.
    bridge = (
        index_imv.select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    print(f"hospitalization ids in the cohort : {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids


@app.cell
def _(DATA_DIR, FILETYPE, PatientProcedures, TIMEZONE, bridge_hosp_ids, pl, to_site_naive):
    _proc = PatientProcedures.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        # Named explicitly so the provider columns are not merely unused but never read.
        columns=[
            "hospitalization_id",
            "procedure_code",
            "procedure_code_format",
            "procedure_billed_dttm",
        ],
        timezone=TIMEZONE,
        filters={"hospitalization_id": bridge_hosp_ids},
    )

    proc = pl.from_pandas(
        _proc.df.assign(
            procedure_billed_dttm=lambda d: to_site_naive(d["procedure_billed_dttm"])
        )
    ).with_columns(
        procedure_code_format=pl.col("procedure_code_format").str.to_lowercase(),
        # Codes are compared as trimmed strings. A leading zero or a trailing space is a
        # formatting difference, not a different procedure, and either would silently
        # produce a capture rate of zero.
        procedure_code=pl.col("procedure_code").str.strip_chars(),
    )

    assert "billing_provider_id" not in proc.columns, "provider column reached the frame"
    print(f"procedure rows loaded : {proc.height:,}")
    print("\nprocedure_code_format values present (lower-cased):")
    print(proc.get_column("procedure_code_format").value_counts(sort=True))
    return (proc,)


@app.cell
def _(REFERENCE_CODE, REFERENCE_FORMAT, bridge, pl, proc):
    hits = (
        proc.filter(
            (pl.col("procedure_code_format") == REFERENCE_FORMAT)
            & (pl.col("procedure_code") == REFERENCE_CODE)
        )
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")
    )

    print(f"{REFERENCE_CODE} rows inside the cohort : {hits.height:,}")
    print(f"distinct blocks carrying it            : {hits.get_column('encounter_block').n_unique():,}")
    return (hits,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Billing date versus t0 — a description, never a filter

        Reported because a reader will ask, and because a distribution centred days away
        from t0 tells you plainly that the billing timestamp is an administrative date
        rather than a clinical one. It is not used for anything: no window, no
        containment test, no tie-break. Presence is the whole signal.

        **Anchored on the block's earliest t0**, because CPT resolves to the block and not
        to an episode (D1 — the code carries no usable timing). A block with two
        intubations has two t0s and the code cannot say which it was billed for; picking
        the earliest is a stated convention rather than an inference, and it is safe here
        precisely because nothing downstream consumes this number.
        """
    )
    return


@app.cell
def _(hits, index_imv, pl):
    _block_t0 = (
        index_imv.filter(pl.col("index_qualified"))
        .group_by("encounter_block")
        .agg(block_first_t0=pl.col("t0_dttm").min())
    )
    _h = hits.join(_block_t0, on="encounter_block", how="inner")
    if _h.height > 0:
        _lag = _h.with_columns(
            lag_days=(
                (pl.col("procedure_billed_dttm") - pl.col("block_first_t0")).dt.total_seconds()
                / 86400.0
            ).round(2)
        ).get_column("lag_days")
        print(
            f"billed_dttm - block's first t0, days   median {_lag.median():+.2f}   "
            f"IQR {_lag.quantile(0.25):+.2f} .. {_lag.quantile(0.75):+.2f}   "
            f"min {_lag.min():+.2f}   max {_lag.max():+.2f}"
        )
    else:
        print("no coded rows in a qualified block — nothing to describe")
    return


@app.cell
def _(COHORT_RUN_ID, PHI_DIR, REFERENCE_ID, hits, index_imv, pl):
    _coded = hits.select("encounter_block").unique().with_columns(cpt_present=True)

    # A code billed anywhere in the block marks EVERY episode of that block. CPT has no
    # usable timing (D1), so it cannot distinguish a block's first intubation from its
    # reintubation, and Tier C therefore reports at block level. Fanning out here keeps the
    # artifact joinable on the study key without implying the code named an episode.
    reference_cpt = (
        index_imv.select(
            ["intubation_episode_id", "encounter_block", "patient_id", "ep_num",
             "cohort_run_id", "index_class", "index_qualified"]
        )
        .join(_coded, on="encounter_block", how="left")
        .with_columns(
            reference_id=pl.lit(REFERENCE_ID),
            cpt_present=pl.col("cpt_present").fill_null(False),
        )
        .sort(["encounter_block", "ep_num"])
    )

    assert reference_cpt.height == index_imv.height, "one row per candidate episode required"
    assert reference_cpt.get_column("intubation_episode_id").is_unique().all()
    assert reference_cpt.get_column("cohort_run_id").unique().to_list() == [COHORT_RUN_ID]

    reference_cpt.write_parquet(PHI_DIR / "reference_cpt.parquet")
    print(f"reference_cpt.parquet   {reference_cpt.height:,} rows -> {PHI_DIR}")
    return (reference_cpt,)


@app.cell
def _(mo):
    mo.md(
        """
        ## C.1 — capture rate

        **Read this before anything in Tier C.** The denominator is the index set `N**`,
        because that is the set every Tier C metric is computed on, and each of those
        encounters has a documented, sustained intubation by construction — so an encounter
        without the code is a *coding* absence, not a clinical one.

        A capture rate near zero does not mean the methods are wrong. It means the reference
        cannot adjudicate them at this site, and `06` suppresses the scoring table rather
        than publishing numbers that would be read as method performance.
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, REFERENCE_CODE, REFERENCE_ID, SHARE_DIR, pl, reference_cpt):
    MIN_CELL = 10  # §9 minimum cell size
    CAPTURE_FLOOR = 0.05  # below this the reference is declared uninformative

    _qual = reference_cpt.filter(pl.col("index_qualified"))
    _n_qual = _qual.height
    _n_coded = _qual.filter(pl.col("cpt_present")).height
    _rate = _n_coded / max(_n_qual, 1)

    reference_capture = pl.DataFrame(
        {
            "cohort_run_id": [COHORT_RUN_ID],
            "reference_id": [REFERENCE_ID],
            "reference_code": [REFERENCE_CODE],
            "n_index_set": [_n_qual],
            "n_with_code": [_n_coded if _n_coded >= MIN_CELL or _n_coded == 0 else None],
            "capture_rate": [round(_rate, 4) if _n_coded >= MIN_CELL else None],
            "informative": [bool(_n_coded >= MIN_CELL and _rate >= CAPTURE_FLOOR)],
            "suppressed": [bool(0 < _n_coded < MIN_CELL)],
        }
    )
    reference_capture.write_csv(SHARE_DIR / "reference_capture_rate.csv")

    print(f"index set (N**), episodes: {_n_qual:,}")
    print(f"carrying {REFERENCE_CODE}            : {_n_coded:,}")
    print(f"  distinct blocks        : {_qual.filter(pl.col('cpt_present')).get_column('encounter_block').n_unique():,}")
    print(f"capture rate             : {_rate:.4f}")
    if 0 < _n_coded < MIN_CELL:
        print(
            f"\nSUPPRESSED — fewer than {MIN_CELL} episodes carry the code, so the count is "
            "withheld from the published table under the minimum cell size rule."
        )
    if _rate < CAPTURE_FLOOR:
        print(
            f"\nREFERENCE IS UNINFORMATIVE AT THIS SITE (capture {_rate:.4f} < {CAPTURE_FLOOR})."
        )
        print(
            "  Tier C will report this fact instead of scoring. Sensitivity and PPV against a\n"
            "  reference this sparse would measure the billing extract, not the methods."
        )
    print()
    print(reference_capture)
    return (MIN_CELL,)


@app.cell
def _(MIN_CELL, pl, reference_cpt):
    # Whole-cohort context, so a reader can see whether the sparsity is specific to the
    # index set or a property of the extract. Same suppression rule.
    _by_class = (
        reference_cpt.group_by("index_class")
        .agg(n=pl.len(), n_coded=pl.col("cpt_present").sum())
        .sort("n", descending=True)
        .with_columns(
            n_coded=pl.when((pl.col("n_coded") > 0) & (pl.col("n_coded") < MIN_CELL))
            .then(None)
            .otherwise(pl.col("n_coded"))
        )
    )
    print("coded encounters by index_class (counts 1..9 suppressed):")
    print(_by_class)
    return


if __name__ == "__main__":
    app.run()
