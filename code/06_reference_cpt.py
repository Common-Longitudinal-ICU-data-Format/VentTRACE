import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import matplotlib.pyplot as plt
    import polars as pl

    from clifpy.tables import PatientProcedures

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return Path, PatientProcedures, json, mo, pl, plt, publish


@app.cell
def _(mo):
    mo.md(
        r"""
        # 06 — the CPT comparator

        For each encounter block with an index paralytic: was a CPT `31500` billed anywhere
        in that block, and does agreement strengthen as the paralytic evidence strengthens?

        **CPT is a comparator, not a reference standard (P26).** An absent code means "no
        IMV was performed, or it was not charted", and the two are indistinguishable in the
        data. No sensitivity, no specificity, no NPV, no kappa is published — the
        denominator is blocks that already have an index paralytic (P27), so the
        false-negative cell is excluded by construction and every statistic needing it
        would be computed on a cell that cannot be observed.

        **The comparison is at block level with no time alignment (P29).** A block flagged
        CPT-positive may have been billed for an intubation days from the index paralytic.
        `cpt_offset_distribution.csv` measures exactly that rather than assuming it away —
        it is the only instrument that recovers what the block-level flag gives up.

        Design: `docs/superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md` §5
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
    FIG_DIR = SHARE_DIR / "figures"
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    CPT_INTUBATION = "31500"

    # P20 casing variants at the from_file boundary. The mCIDE value is `cpt`; sites
    # write it several ways and a filter matching zero rows looks exactly like a site
    # that bills no intubations.
    CPT_FORMAT_VARIANTS = ["cpt", "CPT", "Cpt", "cpt4", "CPT4"]

    # P30. Day bins, signed: `procedure_billed_dttm` is trusted to the day and not to the
    # minute, which is why this is a day distribution and not a minute offset.
    OFFSET_BIN_BREAKS = [-30, -7, -1, 0, 1, 7, 30]
    OFFSET_BIN_LABELS = [
        "<= -30 d", "(-30,-7] d", "(-7,-1] d", "(-1,0] d",
        "(0,1] d", "(1,7] d", "(7,30] d", "> 30 d",
    ]

    TIER_LABELS = {1: "index only", 2: "index + imv transition", 3: "index + imv + sedation"}

    print(f"site : {SITE}")
    print(f"cpt  : {CPT_INTUBATION}  formats {CPT_FORMAT_VARIANTS}")
    return (
        CPT_FORMAT_VARIANTS,
        CPT_INTUBATION,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        OFFSET_BIN_BREAKS,
        OFFSET_BIN_LABELS,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        TIER_LABELS,
        TIMEZONE,
        config,
    )


@app.cell
def _(TIMEZONE, pl):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Defined locally (spec §4).
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def cpt_block_flag(procedures, bridge):
        """One row per encounter_block: does any member hospitalization carry the code?

        `procedures` carries hospitalization_id and procedure_date (already filtered to
        CPT 31500). `bridge` carries encounter_block and hospitalization_id, one row per
        hospitalization.

        The join is INNER on the bridge side, so a procedure row for a hospitalization no
        block claims is dropped rather than creating a phantom block -- the explode-and-
        drop of the 2026-08-10 spec §6.1.

        Every block in the bridge gets a row, including blocks with no procedure data at
        all: a published false, never a missing row. A missing row and a false are
        indistinguishable to a reader and only one of them is a measurement.
        """
        _hits = (
            procedures.join(bridge, on="hospitalization_id", how="inner")
            .group_by("encounter_block")
            .agg(
                pl.len().cast(pl.Int32).alias("n_cpt_codes"),
                pl.col("procedure_date").min().alias("first_cpt_date"),
                pl.col("procedure_date").max().alias("last_cpt_date"),
            )
        )
        return (
            bridge.select("encounter_block")
            .unique()
            .join(_hits, on="encounter_block", how="left")
            .with_columns(
                pl.col("n_cpt_codes").fill_null(0).cast(pl.Int32),
                (pl.col("n_cpt_codes").fill_null(0) > 0).alias("has_cpt"),
            )
            .sort("encounter_block")
        )

    return (cpt_block_flag,)


@app.cell
def _(
    CPT_FORMAT_VARIANTS,
    CPT_INTUBATION,
    DATA_DIR,
    FILETYPE,
    PHI_DIR,
    PatientProcedures,
    TIMEZONE,
    cpt_block_flag,
    pl,
    to_site_naive,
):
    index_covariates = pl.read_parquet(PHI_DIR / "index_covariates.parquet")
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

    # P27: the denominator is the blocks that HAVE an index paralytic, not the cohort.
    blocks = index_covariates.filter(pl.col("p_num") == 1)
    bridge = (
        cohort_index.filter(
            pl.col("encounter_block").is_in(blocks.get_column("encounter_block"))
        )
        .select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    assert bridge.get_column("hospitalization_id").is_unique().all(), (
        "a hospitalization_id appears in more than one encounter_block"
    )

    _hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # REQUIRED table (spec §4). Absent, this fails loudly -- a CPT comparator that
    # silently reports zero agreement because the table was missing is worse than no
    # comparator at all.
    _proc_table = PatientProcedures.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "procedure_code",
            "procedure_code_format",
            "procedure_billed_dttm",
        ],
        filters={
            "hospitalization_id": _hosp_ids,
            "procedure_code_format": CPT_FORMAT_VARIANTS,
        },
    )
    _proc_pd = _proc_table.df.copy()
    _proc_pd["procedure_billed_dttm"] = to_site_naive(_proc_pd["procedure_billed_dttm"])

    procedures_all = pl.from_pandas(_proc_pd).with_columns(
        pl.col("procedure_code").cast(pl.String).str.strip_chars()
    )
    procedures = procedures_all.filter(pl.col("procedure_code") == CPT_INTUBATION).select(
        "hospitalization_id",
        pl.col("procedure_billed_dttm").dt.date().alias("procedure_date"),
    )

    # patient_procedures is REQUIRED (spec §4): a missing file already raises inside
    # clifpy's from_file. What that does NOT catch is the CPT_FORMAT_VARIANTS filter
    # silently matching nothing -- indistinguishable, from a bare zero, from a site
    # that genuinely bills no CPT at all (see the comment on CPT_FORMAT_VARIANTS
    # above). procedures_all being non-empty proves the format filter is actually
    # doing something at this site; procedures (the code == 31500 filter) is allowed
    # to be legitimately zero and is reported as-is -- that is a finding, not a bug.
    assert procedures_all.height > 0, (
        "patient_procedures loaded but zero rows matched CPT_FORMAT_VARIANTS for "
        "these hospitalizations -- fails loudly rather than silently publishing a "
        "cascade whose zero agreement might just mean the filter never matched "
        "(spec §4: a comparator that silently reports zero agreement because its "
        "input was absent is worse than no comparator)"
    )

    cpt_flags = cpt_block_flag(procedures, bridge)

    print(f"blocks in denominator  : {blocks.height:,}")
    print(f"procedure rows (any)   : {procedures_all.height:,}")
    print(f"procedure rows ({CPT_INTUBATION}) : {procedures.height:,}")
    print(f"blocks with a cpt code : {cpt_flags.get_column('has_cpt').sum():,}")
    return blocks, bridge, cohort_index, cpt_flags, index_covariates, procedures, procedures_all


@app.cell
def _(SHARE_DIR, SITE, TIER_LABELS, blocks, cpt_flags, pl, publish):
    _joined = blocks.select("encounter_block", "evidence_tier").join(
        cpt_flags.select("encounter_block", "has_cpt"), on="encounter_block", how="left"
    )
    assert _joined.get_column("has_cpt").null_count() == 0, (
        "a block in the denominator has no CPT flag -- the bridge lost a block"
    )

    # Fixed 1..3 grid: a tier with no blocks is published as an explicit zero rather
    # than being absent from the table (P21's published-zero convention).
    cpt_cascade = (
        pl.DataFrame({"evidence_tier": [1, 2, 3]})
        .with_columns(pl.col("evidence_tier").cast(pl.Int8))
        .join(
            _joined.group_by("evidence_tier").agg(
                pl.len().cast(pl.Int32).alias("n_blocks"),
                pl.col("has_cpt").sum().cast(pl.Int32).alias("n_cpt_yes"),
            ),
            on="evidence_tier",
            how="left",
        )
        .with_columns(
            pl.col("n_blocks").fill_null(0),
            pl.col("n_cpt_yes").fill_null(0),
        )
        .with_columns(
            (pl.col("n_blocks") - pl.col("n_cpt_yes")).alias("n_cpt_no"),
            pl.when(pl.col("n_blocks") > 0)
            .then(100.0 * pl.col("n_cpt_yes") / pl.col("n_blocks"))
            .otherwise(None)
            .round(2)
            .alias("pct_coded"),
        )
        .with_columns(
            pl.col("evidence_tier").replace_strict(TIER_LABELS, default="unknown").alias("tier_label"),
            pl.lit("cpt 31500 on any member hospitalization of the block").alias("rule"),
            pl.lit(SITE).alias("site_name"),
        )
        .select("evidence_tier", "tier_label", "rule", "n_blocks", "n_cpt_yes", "n_cpt_no", "pct_coded", "site_name")
        .sort("evidence_tier")
    )

    assert cpt_cascade.get_column("n_blocks").sum() == blocks.height, (
        "the cascade's tiers do not partition the denominator"
    )

    publish(cpt_cascade, SHARE_DIR / "cpt_cascade.csv", "cpt_cascade")
    return (cpt_cascade,)


@app.cell
def _(SHARE_DIR, SITE, blocks, cpt_flags, pl, procedures_all, publish, bridge):
    # Denominator quality. A site with thin billing extracts is visible HERE rather than
    # being reported as poor agreement in the table above.
    _blocks_with_any_proc = (
        procedures_all.select("hospitalization_id")
        .unique()
        .join(bridge, on="hospitalization_id", how="inner")
        .get_column("encounter_block")
        .n_unique()
    )

    _codes = cpt_flags.get_column("n_cpt_codes")
    cpt_cascade_qc = pl.DataFrame(
        [
            {"stat": "n_blocks_denominator", "value": float(blocks.height)},
            {"stat": "n_blocks_with_any_procedure_row", "value": float(_blocks_with_any_proc)},
            {"stat": "pct_blocks_with_any_procedure_row", "value": round(100.0 * _blocks_with_any_proc / blocks.height, 2)},
            {"stat": "n_blocks_with_cpt_31500", "value": float(_codes.gt(0).sum())},
            {"stat": "max_cpt_codes_in_one_block", "value": float(_codes.max())},
            {"stat": "median_cpt_codes_where_present", "value": float(_codes.filter(_codes > 0).median() or 0)},
        ]
    ).with_columns(pl.lit(SITE).alias("site_name")).sort("stat")

    publish(cpt_cascade_qc, SHARE_DIR / "cpt_cascade_qc.csv", "cpt_cascade_qc")
    return (cpt_cascade_qc,)


@app.cell
def _(
    OFFSET_BIN_BREAKS,
    OFFSET_BIN_LABELS,
    SHARE_DIR,
    SITE,
    blocks,
    bridge,
    pl,
    procedures,
    publish,
):
    # P30. Signed days from t0 to the NEAREST CPT date, so "billed before the paralytic"
    # and "billed after" are separable. Negative means the code predates t0.
    #
    # Computed against EVERY CPT date in the block, not against the first and last.
    # `cpt_block_flag` aggregates to min/max for its QC columns, and picking the nearer
    # of those two extremes is not the nearest date: a block coded at t0-10, t0-2 and
    # t0+5 has first = t0-10 and last = t0+5, so the extremes comparison returns +5 when
    # the true nearest is -2 -- wrong in magnitude and in sign, in the one table whose
    # whole purpose is establishing whether the billed intubation is time-aligned with
    # the paralytic. Inert wherever a block has at most two CPT dates, which is why it
    # survives a site with sparse billing and misreports at one with real coverage.
    _cpt_dates = procedures.join(
        bridge.select("hospitalization_id", "encounter_block"), on="hospitalization_id", how="inner"
    ).select("encounter_block", "procedure_date")

    _with_dates = (
        blocks.select("encounter_block", "t_dttm")
        .with_columns(pl.col("t_dttm").dt.date().alias("t_date"))
        .join(_cpt_dates, on="encounter_block", how="left")
        .with_columns(
            (pl.col("procedure_date") - pl.col("t_date")).dt.total_days().alias("_d")
        )
        # Nearest by absolute distance; ties broken toward the EARLIER date, so an
        # equidistant pair reports the negative value. Deterministic, and it matches the
        # reading P29 cares about -- a code that predates the paralytic is the case that
        # tells you the block flag is not time-aligned.
        .sort(["encounter_block", pl.col("_d").abs(), "_d"], nulls_last=True)
        .group_by("encounter_block", maintain_order=True)
        .first()
        .select("encounter_block", pl.col("_d").alias("offset_days"))
    )

    # One row per block, still: the group_by collapses the fan-out the date join created.
    assert _with_dates.height == blocks.height, (
        "the nearest-date reduction did not return exactly one row per block"
    )

    _binned = _with_dates.filter(pl.col("offset_days").is_not_null()).with_columns(
        pl.col("offset_days")
        .cut(OFFSET_BIN_BREAKS, labels=OFFSET_BIN_LABELS)
        .cast(pl.String)
        .alias("offset_bin")
    )

    cpt_offset_distribution = (
        pl.DataFrame({"offset_bin": OFFSET_BIN_LABELS})
        .with_row_index("bin_order")
        .join(_binned.group_by("offset_bin").agg(pl.len().cast(pl.Int32).alias("n")), on="offset_bin", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .vstack(
            pl.DataFrame(
                {
                    "bin_order": [len(OFFSET_BIN_LABELS)],
                    "offset_bin": ["no cpt code"],
                    "n": [int(_with_dates.get_column("offset_days").null_count())],
                }
            ).with_columns(pl.col("bin_order").cast(pl.UInt32), pl.col("n").cast(pl.Int32))
        )
        .with_columns(pl.lit(SITE).alias("site_name"))
        .sort(["bin_order", "offset_bin"])
    )

    assert cpt_offset_distribution.get_column("n").sum() == blocks.height, (
        "the offset distribution does not account for every block in the denominator"
    )

    publish(cpt_offset_distribution, SHARE_DIR / "cpt_offset_distribution.csv", "cpt_offset_distribution")
    return (cpt_offset_distribution,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    # Fixed categorical colours: teal is always "billed", grey always "not billed".
    _CODED = "#1baf7a"
    _NOT = "#b0aca2"

    _c = pl.read_csv(SHARE_DIR / "cpt_cascade.csv").sort("evidence_tier")
    _total = _c.get_column("n_blocks").sum()

    _fig, _ax = plt.subplots(figsize=(10, 5.5))

    # A mosaic, not grouped bars. The tiers are very unequal -- tier 1 in the thousands
    # against tiers 2-3 in the hundreds -- and grouped bars would render the small tiers
    # as hairlines. Row height proportional to n_blocks encodes the size disparity and
    # the split encodes the coded fraction, in one mark.
    _y = 0.0
    for _row in _c.iter_rows(named=True):
        _h = _row["n_blocks"] / _total if _total else 0.0
        if _h == 0:
            # A tier with no blocks: a published zero, drawn as a hairline rule so the
            # row is visibly present and visibly empty rather than absent.
            _ax.plot([0, 1], [_y, _y], color="0.3", linewidth=1.2, linestyle=":")
            _ax.text(0.5, _y, f"{_row['tier_label']} — 0 blocks", ha="center", va="bottom", fontsize=8)
            continue
        _frac = (_row["n_cpt_yes"] / _row["n_blocks"]) if _row["n_blocks"] else 0.0
        _ax.barh([_y + _h / 2], [_frac], height=_h * 0.92, color=_CODED, align="center")
        _ax.barh([_y + _h / 2], [1 - _frac], left=[_frac], height=_h * 0.92, color=_NOT, align="center")
        _ax.text(
            -0.01, _y + _h / 2,
            f"{_row['tier_label']}\nn = {_row['n_blocks']:,}",
            ha="right", va="center", fontsize=9,
        )
        _ax.text(
            _frac / 2 if _frac > 0.12 else _frac + 0.02,
            _y + _h / 2,
            f"{_row['pct_coded']:.1f}%",
            ha="center" if _frac > 0.12 else "left",
            va="center", fontsize=9,
            color="white" if _frac > 0.12 else "#0b0b0b",
        )
        _y += _h

    _ax.set_xlim(0, 1)
    _ax.set_ylim(0, 1)
    _ax.set_yticks([])
    _ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    _ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    _ax.set_xlabel("share of the tier's blocks carrying a CPT 31500")
    for _spine in ("top", "right", "left"):
        _ax.spines[_spine].set_visible(False)

    _handles = [
        _ax.plot([], [], color=_CODED, lw=6, label="CPT 31500 billed in the block")[0],
        _ax.plot([], [], color=_NOT, lw=6, label="no CPT 31500 — not performed, or not charted")[0],
    ]
    _ax.legend(handles=_handles, loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=2, fontsize=8, frameon=False)
    _ax.set_title(
        "F.1 — CPT agreement by paralytic evidence tier\n"
        "row height is the tier's share of blocks; CPT is a comparator, not a reference standard (P26)"
    )
    _fig.tight_layout()
    _fig.subplots_adjust(left=0.24, bottom=0.22)
    _fig.savefig(FIG_DIR / "F1_cpt_cascade.png", dpi=150)
    plt.close(_fig)
    print(f"F1_cpt_cascade.png -> {FIG_DIR}")
    return


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _AQUA = "#1baf7a"
    _GREY = "#b0aca2"

    _d = pl.read_csv(SHARE_DIR / "cpt_offset_distribution.csv").sort("bin_order")

    _fig, _ax = plt.subplots(figsize=(11, 6))
    for _row in _d.iter_rows(named=True):
        _color = _GREY if _row["offset_bin"] == "no cpt code" else _AQUA
        if _row["n"] > 0:
            _ax.bar([_row["bin_order"]], [_row["n"]], width=0.7, color=_color)
        else:
            _ax.plot([_row["bin_order"]], [0], marker="D", markersize=7, color=_color,
                     linestyle="None", zorder=5, clip_on=False)

    _ax.set_xticks(_d.get_column("bin_order").to_list())
    _ax.set_xticklabels(_d.get_column("offset_bin").to_list(), rotation=45, ha="right")
    _ax.set_xlabel("signed days from t0 to the nearest CPT 31500 (negative = billed before the paralytic)")
    _ax.set_ylabel("encounter blocks")
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)

    _handles = [
        _ax.plot([], [], color=_AQUA, lw=6, label="blocks with a CPT 31500")[0],
        _ax.plot([], [], color=_GREY, lw=6, label="blocks with no CPT 31500")[0],
        _ax.plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                 label="published zero (measured, exactly 0)")[0],
    ]
    _ax.legend(handles=_handles, loc="upper left", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "F.2 — how far the billed intubation sits from the index paralytic\n"
        "the block-level flag carries no time alignment (P29); this is the measurement of what that costs"
    )
    _fig.tight_layout()
    _fig.subplots_adjust(bottom=0.30)
    _fig.savefig(FIG_DIR / "F2_cpt_offset.png", dpi=150)
    plt.close(_fig)
    print(f"F2_cpt_offset.png -> {FIG_DIR}")
    return


if __name__ == "__main__":
    app.run()
