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

        **The comparison is presence, at block level (P29; P30 withdrawn 2026-08-14).**
        A block is CPT-positive if `31500` appears on any member hospitalization of that
        block, at any time within it. Nothing is aligned to `t₀` and no offset is
        computed. The question is whether the block was billed for an intubation at all;
        a date comparison answers a different question and was withdrawn by the study
        lead rather than reduced.

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

    TIER_LABELS = {1: "index only", 2: "index + imv transition", 3: "index + imv + sedation"}

    print(f"site : {SITE}")
    print(f"cpt  : {CPT_INTUBATION}  formats {CPT_FORMAT_VARIANTS}")
    return (
        CPT_FORMAT_VARIANTS,
        CPT_INTUBATION,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        TIER_LABELS,
        TIMEZONE,
        config,
    )


@app.cell
def _(pl):
    def to_site_naive(series):
        """Strip clifpy's configured site timezone while preserving local wall time.

        `from_file(..., timezone=TIMEZONE)` has already normalized every timestamp to the
        site timezone. Defined locally (spec §4).

        Still here although this notebook computes nothing from a timestamp:
        `procedure_billed_dttm` is a REQUIRED column of the CLIF 2.1 patient_procedures
        schema, so it is read, and P19 binds on every clifpy datetime the moment it
        lands -- including one that is about to be dropped.
        """
        return series.dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def cpt_block_flag(procedures, bridge):
        """One row per encounter_block: does any member hospitalization carry the code?

        `procedures` carries hospitalization_id, one row per CPT 31500 charge (already
        filtered to that code). `bridge` carries encounter_block and hospitalization_id,
        one row per hospitalization.

        Presence, not timing (P29; P30 withdrawn 2026-08-14). All the codes for all the
        hospitalizations in the block are pooled, and one code anywhere in that pool
        makes the block CPT-positive. No date is read, kept or compared -- the study
        lead's rule is "if it is there at all, that block has the intubation", and any
        date arithmetic here would be answering a question nobody asked. `n_cpt_codes`
        survives only as a QC column: it says how thick the billing is, never when.

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
            .agg(pl.len().cast(pl.Int32).alias("n_cpt_codes"))
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
            # `.implode()` is required, not stylistic: a bare Series argument is
            # deprecated and polars has announced the semantics will flip to element-wise
            # list comparison. pyproject pins `polars>=1.43.2` with no upper bound, so a
            # site resolving a newer polars would get a filter matching NOTHING -- an
            # empty bridge, every block reported CPT-negative, and no crash to say so.
            # Matches the five uses in `01_cohort.py` and the one in `04_covariates.py`.
            pl.col("encounter_block").is_in(blocks.get_column("encounter_block").implode())
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
    # Read because the CLIF 2.1 schema marks it required, stripped because P19 binds on
    # every clifpy datetime the moment it lands, dropped because the comparator is
    # presence and nothing downstream may reach for a date it is not entitled to use.
    _proc_pd["procedure_billed_dttm"] = to_site_naive(_proc_pd["procedure_billed_dttm"])

    procedures_all = (
        pl.from_pandas(_proc_pd)
        .drop("procedure_billed_dttm")
        .with_columns(pl.col("procedure_code").cast(pl.String).str.strip_chars())
    )
    procedures = procedures_all.filter(
        pl.col("procedure_code") == CPT_INTUBATION
    ).select("hospitalization_id")

    # patient_procedures is REQUIRED (spec §4): a missing file already raises inside
    # clifpy's from_file -- that is what "fail loudly" means for a genuinely absent
    # table, and no further check is needed for it here.
    #
    # What from_file's raise does NOT catch is CPT_FORMAT_VARIANTS matching zero rows
    # for this cohort. That case is NOT a hard failure: `procedures_all` is already
    # filtered at the from_file boundary to CPT-format rows AND to this cohort's
    # hospitalizations, so a zero here just as easily means "this site does not bill
    # CPT for its analytic cohort" as it means a broken extract, and the two are
    # indistinguishable from inside this notebook. Spec §5 is explicit that a site in
    # that position must be able to see it as a site fact, not have the pipeline die
    # before publishing the QC table that names it -- "a site reporting
    # pct_blocks_with_any_cpt_format_row near zero should treat F as not run rather
    # than as a null result" cannot be read by an operator whose notebook already
    # aborted. At MIMIC this passed with exactly one row. A loud print, not an assert:
    # the empty result is what cpt_cascade_qc.csv exists to publish.
    if procedures_all.height == 0:
        print(
            "\n"
            "WARNING: zero rows matched CPT_FORMAT_VARIANTS for this cohort's "
            "hospitalizations.\n"
            "  Sub-analysis F cannot answer its question at this site -- every tier of "
            "the cascade\n"
            "  below will show 0% coded, and that 0% is indistinguishable from a "
            "broken CPT extract\n"
            "  from inside this notebook. See cpt_cascade_qc.csv "
            "(pct_blocks_with_any_cpt_format_row)\n"
            "  before reading cpt_cascade.csv as a measurement of agreement.\n"
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
            # Named for what `procedures_all` actually is: CPT-FORMAT rows (P20's casing
            # variants at the from_file boundary), not "any procedure of any kind". MIMIC
            # has 1,045,729 procedure rows covering essentially every block but publishes
            # this stat at 0.06% -- under the old "any_procedure" name that reads as a
            # broken extract; under this name it correctly reads as "this cohort's
            # billing is CPT-format-thin", which is the site fact sub-analysis F needs.
            {"stat": "n_blocks_with_any_cpt_format_row", "value": float(_blocks_with_any_proc)},
            {"stat": "pct_blocks_with_any_cpt_format_row", "value": round(100.0 * _blocks_with_any_proc / blocks.height, 2)},
            {"stat": "n_blocks_with_cpt_31500", "value": float(_codes.gt(0).sum())},
            {"stat": "max_cpt_codes_in_one_block", "value": float(_codes.max())},
            # A median over an empty set is not zero -- null, not `or 0` (FIX 6).
            {"stat": "median_cpt_codes_where_present", "value": _codes.filter(_codes > 0).median()},
        ]
    ).with_columns(pl.lit(SITE).alias("site_name")).sort("stat")

    publish(cpt_cascade_qc, SHARE_DIR / "cpt_cascade_qc.csv", "cpt_cascade_qc")
    return (cpt_cascade_qc,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    # Fixed categorical colours: teal is always "billed", grey always "not billed".
    _CODED = "#1baf7a"
    _NOT = "#b0aca2"

    _c = pl.read_csv(SHARE_DIR / "cpt_cascade.csv").sort("evidence_tier")
    _total = _c.get_column("n_blocks").sum()

    # FIX 4 (2026-08-12 final review). Standing alone in a slide, the mosaic below reads
    # as "the paralytic index agrees with billing X% of the time" with no defence against
    # X being near zero for a site-level reason rather than a clinical one. Every other
    # artifact in sub-analysis F carries that defence -- the module docstring, P26, the
    # QC table itself -- except the one artifact most likely to be shown without any of
    # them attached. The number comes from cpt_cascade_qc.csv, never recomputed here, so
    # nothing appears on the figure that is not already in a published CSV (spec §7).
    _qc = pl.read_csv(SHARE_DIR / "cpt_cascade_qc.csv")
    _coverage_pct = _qc.filter(pl.col("stat") == "pct_blocks_with_any_cpt_format_row")["value"][0]

    # 5% chosen as the threshold: MIMIC's observed value is 0.06%, two orders of
    # magnitude below it, and a site with reasonable CPT billing for its ICU cohort
    # should clear it easily. Below it, "thin billing extract" is a better explanation
    # for a low pct_coded than "the index disagrees with truth", so the subtitle says so
    # explicitly rather than leaving that inference to the reader.
    #
    # Split across two lines unconditionally, not left to wrap: a one-line subtitle at
    # this font size ran past the right edge of the canvas and was clipped by
    # `savefig` (no `bbox_inches="tight"` is used, so text outside the figure's bbox is
    # silently cut rather than shrunk) -- checked by measuring the rendered PNG's ink
    # extent, not by eye.
    _COVERAGE_THRESHOLD = 5.0
    _coverage_line1 = (
        f"CPT coverage at this site: {_coverage_pct:.2f}% of blocks carry any "
        "CPT-format procedure row"
    )
    if _coverage_pct < _COVERAGE_THRESHOLD:
        _coverage_line2 = (
            f"below {_COVERAGE_THRESHOLD:.0f}%, sub-analysis F cannot answer its question "
            "here (see cpt_cascade_qc.csv)"
        )
    else:
        _coverage_line2 = "(see cpt_cascade_qc.csv)"

    _fig, _ax = plt.subplots(figsize=(10, 6.8))

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
        "row height is the tier's share of blocks; CPT is a comparator, not a reference standard (P26)\n"
        f"{_coverage_line1}\n"
        f"{_coverage_line2}",
        fontsize=10,
    )
    _fig.tight_layout()
    _fig.subplots_adjust(left=0.24, bottom=0.20, top=0.78)
    _fig.savefig(FIG_DIR / "F1_cpt_cascade.png", dpi=150)
    plt.close(_fig)
    print(f"F1_cpt_cascade.png -> {FIG_DIR}")
    return


if __name__ == "__main__":
    app.run()
