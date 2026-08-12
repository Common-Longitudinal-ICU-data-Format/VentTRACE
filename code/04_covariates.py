import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import polars as pl

    from clifpy.tables import (
        Adt,
        CrrtTherapy,
        HospitalDiagnosis,
        Hospitalization,
        MedicationAdminContinuous,
        Patient,
        Position,
        Vitals,
    )

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        Adt,
        CrrtTherapy,
        HospitalDiagnosis,
        Hospitalization,
        MedicationAdminContinuous,
        Patient,
        Path,
        Position,
        Vitals,
        json,
        mo,
        pl,
        publish,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 04 — covariates of the index paralytic

        The sole owner of this study's analytic row. Everything downstream — both Table 1s
        and the CPT cascade — aggregates the single frame this notebook writes, and none of
        them re-derives a block, re-selects `p_num`, or re-computes a tier. That is what
        keeps `table1_by_agent_block.csv` and `cpt_cascade.csv` from disagreeing about N.

        One row per index paralytic event. Block-level attributes (LOS, mortality, the
        block's index count) are constant within a block and repeat down its rows; the
        `unit` column of Table 1 is what keeps that legible downstream (P35).

        Design: `docs/superpowers/specs/2026-08-12-block-summary-and-cpt-comparator-design.md`
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

    # P33. An ANALYSIS grid, not a site parameter -- a site that changed these windows
    # would make its Table 1 non-comparable with every other site's, which is the one
    # thing a multi-site Table 1 exists for. Same reasoning as P11's gap bins.
    # 1h is the senior author's "at the time of intubation"; 6h and 24h are the study
    # lead's. The trio also aligns column-for-column with the RSI reference table.
    LOOKBACK_HOURS = [1, 6, 24]

    # P32. Continuous medications supply a PRESENCE FLAG and nothing else -- no dose,
    # no rate, no infusion-derived index event. A module constant, not a config key,
    # for the reason P11 gives about the gap bins.
    VASOPRESSORS = [
        "norepinephrine",
        "vasopressin",
        "epinephrine",
        "phenylephrine",
        "dopamine",
    ]

    print(f"site           : {SITE}")
    print(f"lookback hours : {LOOKBACK_HOURS}")
    print(f"vasopressors   : {' | '.join(VASOPRESSORS)}")
    return (
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        LOOKBACK_HOURS,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        TIMEZONE,
        VASOPRESSORS,
        config,
    )


@app.cell
def _(TIMEZONE, pl):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Pinned by
        `tests/test_clifpy_tz_boundary.py`. Defined locally, never imported (spec §4).
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    def epoch_minutes(column):
        """Minutes since epoch, computed INSIDE polars, consulting no timezone at all.

        `datetime.timestamp()` on a site-naive value re-attaches the machine's zone; ten
        minutes across a DST fall-back would measure as seventy. Spec P19.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    def in_lookback(t0_col, dttm_col, hours):
        """True when `dttm_col` falls in the window `[t0 - hours, t0]`, closed at both ends.

        The ONE implementation every exposure source calls (P33). Twelve interval tests
        written independently -- four sources times three windows -- will disagree about a
        row landing exactly on the far edge, and that disagreement is invisible in
        aggregate while being fatal to a joint reading of "already shocked" versus
        "crashed at intubation".

        Closed at `t0` as well as at `t0 - hours`: a vasopressor charted on the index
        minute is an exposure at the index. Closed at the far edge so the parameter reads
        as "within 24 hours", matching how P6's fold closes inclusively at `t + 15`.

        Arithmetic is done on epoch seconds inside polars, which reads the stored naive
        wall-clock value and consults no timezone at all (P19).

        A null timestamp is NOT in the window: `null <= x` is null in polars, and a null
        exposure flag would later be filled or summed as if it were a measurement. The
        explicit `fill_null(False)` makes "we have no timestamp" resolve to "not an
        exposure in this window", which is what the source-coverage table (T2) exists to
        qualify.
        """
        _t0 = pl.col(t0_col).dt.epoch("s")
        _dttm = pl.col(dttm_col).dt.epoch("s")
        return (
            (_dttm <= _t0) & (_dttm >= _t0 - int(hours * 3600))
        ).fill_null(False)

    return epoch_minutes, in_lookback, to_site_naive


@app.cell
def _(mo):
    mo.md(
        """
        ## The event spine

        `index_context.parquet` is read alone. It already carries every column
        `index_paralytic.parquet` has, plus D's transition result and E's sedation result,
        so reading both would be a redundant join on the same key.

        The **evidence tier** (P31) is computed here, per event, from that event's own D
        and E flags. Tier 3 requires both on the *same* event — which is exactly what P15
        bought by making D and E share one window predicate. The cascade in `06` reads
        this column from the `p_num = 1` row only; the tier exists on every row because the
        index-level Table 1 reports it too.

        `agent_stratum` collapses `agent_label` into the Table 1 columns: any label
        containing `+` is a co-administration and becomes `combination`; everything else
        keeps its agent name. A rocuronium redose has `agent_label == 'rocuronium'` and is
        therefore `rocuronium`, not `combination` (spec §3.2).
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    def evidence_tier(imv_col, sed_col):
        """The block's evidence tier, P31, computed per event from that event's own flags.

        3 = an IMV device transition AND a sedative in this event's own +/-60 min window
        2 = an IMV device transition, no sedative
        1 = neither

        Tier 3 conjoins D and E on the SAME event rather than on the block. A block whose
        first paralytic had a transition and whose fifth had sedation describes two
        clinical acts days apart, and calling that tier 3 would manufacture evidence that
        no single intubation ever produced.
        """
        return (
            pl.when(pl.col(imv_col) & pl.col(sed_col))
            .then(pl.lit(3))
            .when(pl.col(imv_col))
            .then(pl.lit(2))
            .otherwise(pl.lit(1))
            .cast(pl.Int8)
        )

    index_context = pl.read_parquet(PHI_DIR / "index_context.parquet")

    spine = index_context.select(
        "index_paralytic_id",
        "encounter_block",
        "patient_id",
        "cohort_run_id",
        "p_num",
        "t_dttm",
        "agent_label",
        "imv_transition",
        "no_transition_reason",
        "any_sedative",
    ).with_columns(
        evidence_tier("imv_transition", "any_sedative").alias("evidence_tier"),
        # Table 1 stratum. `+` is the co-administration marker `02` builds by joining the
        # sorted agent set; index_composition.csv already separates that from same-agent
        # redose, and this collapse keeps the two consistent.
        pl.when(pl.col("agent_label").str.contains(r"\+", literal=False))
        .then(pl.lit("combination"))
        .otherwise(pl.col("agent_label"))
        .alias("agent_stratum"),
        pl.len().over("encounter_block").cast(pl.Int32).alias("n_index_in_block"),
    )

    # The frame this notebook owns is the event frame; every consumer subsets it. A
    # height that has drifted from 03's output means an upstream re-run that this
    # notebook's inputs no longer match, and every count below would be silently off.
    assert spine.height == index_context.height, "the spine lost or duplicated events"
    assert spine.get_column("index_paralytic_id").is_unique().all(), (
        "index_paralytic_id is not unique in the spine"
    )
    assert spine.get_column("p_num").min() == 1, "p_num does not start at 1"

    _blocks = spine.get_column("encounter_block").n_unique()
    print(f"index events        : {spine.height:,}")
    print(f"encounter blocks    : {_blocks:,}")
    print(spine.group_by("evidence_tier").agg(n=pl.len()).sort("evidence_tier"))
    print(spine.group_by("agent_stratum").agg(n=pl.len()).sort("n", descending=True))
    return evidence_tier, index_context, spine


if __name__ == "__main__":
    app.run()
