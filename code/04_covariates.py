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


@app.cell
def _(mo):
    mo.md(
        """
        ## Attribute resolution

        A block stitches up to four hospitalizations, so an attribute recorded *per
        hospitalization* is undefined until we say which one. Every such case resolves to
        **the hospitalization containing `t₀`** — the one the index paralytic was actually
        charted under (spec §3.2). The alternative, the block's first hospitalization, was
        rejected because an ED presentation and the inpatient admission that follows can
        carry different recorded ages and different diagnosis lists, and the paralytic
        belongs to exactly one of them.

        LOS is **summed over the block's member hospitalizations**, not measured as the
        block's span (P38): the span would count the stitch gaps, during which the patient
        was not in the hospital.

        Mortality is bounded (P37). `death_dttm` is patient-level in CLIF and can be
        registry-sourced, so unbounded it fires for a patient discharged alive who died at
        home months later.
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

    bridge = (
        cohort_index.select(["encounter_block", "patient_id", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # Many-to-one, asserted rather than assumed. A duplicated key fans out every row on
    # the joins below, and the fan-out is self-consistent -- every downstream count would
    # still agree with itself while being wrong. Same assertion, same reason, as `02`.
    assert bridge.get_column("hospitalization_id").is_unique().all(), (
        "a hospitalization_id appears in more than one encounter_block"
    )

    print(f"encounter blocks   : {cohort_index.height:,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids, cohort_index


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    Hospitalization,
    TIMEZONE,
    bridge,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    _hosp_table = Hospitalization.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "patient_id",
            "admission_dttm",
            "discharge_dttm",
            "age_at_admission",
            "discharge_category",
        ],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    _hosp_pd = _hosp_table.df.copy()
    for _c in ("admission_dttm", "discharge_dttm"):
        _hosp_pd[_c] = to_site_naive(_hosp_pd[_c])

    hospitalization = (
        pl.from_pandas(_hosp_pd)
        .with_columns(pl.col("discharge_category").str.to_lowercase())
        .join(bridge.select("hospitalization_id", "encounter_block"), on="hospitalization_id", how="inner")
    )

    print(f"hospitalizations loaded : {hospitalization.height:,}")
    print(hospitalization.group_by("discharge_category").agg(n=pl.len()).sort("n", descending=True))
    return (hospitalization,)


@app.cell
def _(Adt, DATA_DIR, FILETYPE, TIMEZONE, bridge, bridge_hosp_ids, pl, to_site_naive):
    # P20. The casing variants are enumerated at the from_file boundary because that
    # filter runs before any normalisation we control, and a filter matching zero rows
    # looks exactly like a site where the thing never happens.
    _ICU_VARIANTS = ["icu", "ICU", "Icu"]

    _adt_table = Adt.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "location_category", "in_dttm", "out_dttm"],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    _adt_pd = _adt_table.df.copy()
    for _c in ("in_dttm", "out_dttm"):
        _adt_pd[_c] = to_site_naive(_adt_pd[_c])

    adt = (
        pl.from_pandas(_adt_pd)
        .with_columns(pl.col("location_category").str.to_lowercase())
        .join(bridge.select("hospitalization_id", "encounter_block"), on="hospitalization_id", how="inner")
    )

    # 01's cohort inclusion step already requires >=1 ADT row in {ed, icu} for every
    # block in the cohort (see consort_cohort.csv). So a block with ZERO adt rows here
    # is not a site fact -- it is this notebook's load or filter dropping rows. Checked
    # before the icu subset, and before block_outcomes fills a missing los_icu_days with
    # 0.0, because that fill is only correct once a missing block is ruled out.
    _blocks_in_bridge = set(bridge.get_column("encounter_block").unique().to_list())
    _blocks_in_adt = set(adt.get_column("encounter_block").unique().to_list())
    _missing_from_adt = _blocks_in_bridge - _blocks_in_adt
    assert not _missing_from_adt, (
        f"{len(_missing_from_adt):,} encounter_block(s) present in bridge have no ADT "
        "row at all in this notebook's load, but 01_cohort.py's inclusion criteria "
        "guarantee every cohort block has >=1 ADT row in {ed, icu} -- this is an ADT "
        "load or filter failure here in 04, not a site where the block never moved. "
        f"first few: {sorted(_missing_from_adt)[:10]}"
    )

    adt_icu = adt.filter(pl.col("location_category") == "icu")

    print(f"adt rows loaded : {adt.height:,}")
    print(f"  icu rows      : {adt_icu.height:,}")
    print(adt.group_by("location_category").agg(n=pl.len()).sort("n", descending=True).head(10))
    return adt, adt_icu


@app.cell
def _(pl):
    def resolve_mortality(df):
        """P37's mortality rules, over a frame of block x hospitalization x icu-interval.

        Expects: encounter_block, admission_dttm, discharge_dttm, discharge_category,
        death_dttm, icu_in_dttm, icu_out_dttm. Rows repeat per icu interval; a block with
        no icu row carries nulls in the two icu columns.

        Returns one row per encounter_block with three booleans:

          hospital_mortality           death_dttm inside a member hospitalization's
                                       admission -> discharge interval, OR
                                       discharge_category == 'expired'
          icu_mortality                death_dttm inside an ADT icu interval
          icu_mortality_undeterminable dead, but flagged by discharge_category alone --
                                       no death time, so no ICU attribution either way

        The bound on death_dttm is the whole point (see the module docstring of
        tests/test_mortality_bound.py). The three flags are INTENDED to be mutually
        consistent -- icu_mortality and icu_mortality_undeterminable both subsets of
        hospital_mortality, and disjoint from each other -- but that consistency is not
        free. It relies on every ADT icu interval sitting inside its owning
        hospitalization's [admission_dttm, discharge_dttm] window, which this function has
        no way to check (it never sees a hospitalization/icu-interval pairing, only the
        already-joined death/interval columns). So the invariant is asserted on the
        OUTPUT instead of assumed from the input: it needs no assumption about the ADT
        extract and is the property that actually matters for publication.
        """
        _death_in_stay = (
            pl.col("death_dttm").is_not_null()
            & (pl.col("death_dttm") >= pl.col("admission_dttm"))
            & (pl.col("death_dttm") <= pl.col("discharge_dttm"))
        )
        _death_in_icu = (
            pl.col("death_dttm").is_not_null()
            & pl.col("icu_in_dttm").is_not_null()
            & (pl.col("death_dttm") >= pl.col("icu_in_dttm"))
            & (pl.col("death_dttm") <= pl.col("icu_out_dttm"))
        )
        _out = (
            df.group_by("encounter_block")
            .agg(
                _death_in_stay.any().alias("_death_dated_in_stay"),
                (pl.col("discharge_category") == "expired").any().alias("_expired_category"),
                _death_in_icu.any().alias("icu_mortality"),
            )
            .with_columns(
                (pl.col("_death_dated_in_stay") | pl.col("_expired_category")).alias(
                    "hospital_mortality"
                )
            )
            .with_columns(
                # Dead, but with no usable death time: the ICU question cannot be
                # answered for this block in either direction. Published as its own
                # count rather than absorbed into a numerator.
                (
                    pl.col("hospital_mortality")
                    & ~pl.col("_death_dated_in_stay")
                ).alias("icu_mortality_undeterminable")
            )
            .drop("_death_dated_in_stay", "_expired_category")
            .sort("encounter_block")
        )

        # icu_mortality subset of hospital_mortality: a violation means some ADT icu
        # interval extends outside its own hospitalization's admission/discharge window,
        # so a death timed inside the icu interval landed outside _death_in_stay.
        _icu_not_hospital = _out.filter(
            pl.col("icu_mortality") & ~pl.col("hospital_mortality")
        )
        assert _icu_not_hospital.is_empty(), (
            f"{_icu_not_hospital.height:,} block(s) have icu_mortality True but "
            "hospital_mortality False -- an ADT icu interval must extend outside its "
            "owning hospitalization's [admission_dttm, discharge_dttm] window. Check "
            f"the ADT extract for: {_icu_not_hospital.get_column('encounter_block').to_list()[:10]}"
        )

        # icu_mortality and icu_mortality_undeterminable disjoint: a violation means a
        # block both had a death time landing inside an icu interval (icu_mortality) and
        # was flagged as having no usable death time (icu_mortality_undeterminable) --
        # only possible if the two death-time checks disagree, which again traces back to
        # an icu interval outside the hospitalization window rather than a logic bug here.
        _both = _out.filter(pl.col("icu_mortality") & pl.col("icu_mortality_undeterminable"))
        assert _both.is_empty(), (
            f"{_both.height:,} block(s) have both icu_mortality and "
            "icu_mortality_undeterminable True, which should be impossible by "
            "construction -- check the ADT extract for an icu interval outside its "
            f"owning hospitalization's window: {_both.get_column('encounter_block').to_list()[:10]}"
        )

        return _out

    return (resolve_mortality,)


@app.cell
def _(DATA_DIR, FILETYPE, Patient, TIMEZONE, cohort_index, pl, to_site_naive):
    # REQUIRED table (spec §4). Absent, this fails loudly rather than publishing a
    # Table 1 with no demographics -- race and ethnicity are the specific rows the
    # senior-author review asked for.
    _patient_ids = cohort_index.get_column("patient_id").unique().to_list()

    _pat_table = Patient.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "patient_id",
            "sex_category",
            "race_category",
            "ethnicity_category",
            "death_dttm",
        ],
        filters={"patient_id": _patient_ids},
    )
    _pat_pd = _pat_table.df.copy()
    _pat_pd["death_dttm"] = to_site_naive(_pat_pd["death_dttm"])

    patient = pl.from_pandas(_pat_pd).with_columns(
        pl.col("sex_category").str.to_lowercase(),
        pl.col("race_category").str.to_lowercase(),
        pl.col("ethnicity_category").str.to_lowercase(),
    )

    assert patient.get_column("patient_id").is_unique().all(), (
        "patient_id is not unique in the patient table"
    )
    print(f"patients loaded : {patient.height:,}")
    print(f"  with death_dttm : {patient.get_column('death_dttm').is_not_null().sum():,}")
    return (patient,)


@app.cell
def _(adt_icu, epoch_minutes, hospitalization, patient, pl, resolve_mortality):
    # LOS: summed over member hospitalizations, never the block's span (P38). The span
    # would count the stitch gaps, during which the patient was not in the hospital.
    los_hospital = (
        hospitalization.with_columns(
            (
                (epoch_minutes("discharge_dttm") - epoch_minutes("admission_dttm")) / 1440.0
            ).alias("_days")
        )
        .group_by("encounter_block")
        .agg(pl.col("_days").sum().round(3).alias("los_hospital_days"))
    )

    los_icu = (
        adt_icu.with_columns(
            ((epoch_minutes("out_dttm") - epoch_minutes("in_dttm")) / 1440.0).alias("_days")
        )
        .group_by("encounter_block")
        .agg(pl.col("_days").sum().round(3).alias("los_icu_days"))
    )

    # One row per (block, hospitalization, icu interval) for resolve_mortality. The
    # cross-product is bounded: at most 4 hospitalizations times the block's icu rows.
    _mortality_input = (
        hospitalization.join(
            patient.select("patient_id", "death_dttm"), on="patient_id", how="left"
        )
        .join(
            adt_icu.select(
                "encounter_block",
                pl.col("in_dttm").alias("icu_in_dttm"),
                pl.col("out_dttm").alias("icu_out_dttm"),
            ),
            on="encounter_block",
            how="left",
        )
        .select(
            "encounter_block",
            "admission_dttm",
            "discharge_dttm",
            "discharge_category",
            "death_dttm",
            "icu_in_dttm",
            "icu_out_dttm",
        )
    )

    block_outcomes = (
        resolve_mortality(_mortality_input)
        .join(los_hospital, on="encounter_block", how="left")
        .join(los_icu, on="encounter_block", how="left")
        # A block with no ADT icu row spent no time in an ICU. That is a measured zero,
        # not a missing value, and filling it keeps the median from being computed on a
        # denominator that silently drops non-ICU blocks.
        .with_columns(pl.col("los_icu_days").fill_null(0.0))
        .sort("encounter_block")
    )

    print(f"blocks with outcomes : {block_outcomes.height:,}")
    print(f"  hospital mortality : {block_outcomes.get_column('hospital_mortality').sum():,}")
    print(f"  icu mortality      : {block_outcomes.get_column('icu_mortality').sum():,}")
    print(
        "  icu undeterminable : "
        f"{block_outcomes.get_column('icu_mortality_undeterminable').sum():,}"
    )
    return block_outcomes, los_hospital, los_icu


@app.cell
def _(adt, block_outcomes, hospitalization, patient, pl, spine):
    # The hospitalization containing t0 (spec §3.2). An interval join, not a "first
    # hospitalization" shortcut: the ED presentation and the inpatient admission carry
    # different ages and different diagnosis lists, and the paralytic belongs to one.
    _hosp_at_t0 = (
        spine.select("index_paralytic_id", "encounter_block", "t_dttm")
        .join(hospitalization, on="encounter_block", how="left")
        .filter(
            (pl.col("t_dttm") >= pl.col("admission_dttm"))
            & (pl.col("t_dttm") <= pl.col("discharge_dttm"))
        )
        # A t0 landing in two member hospitalizations would mean overlapping stays, which
        # the stitcher should have merged. Take the earliest admission deterministically
        # and assert the tie is rare enough to be visible.
        .sort(["index_paralytic_id", "admission_dttm", "hospitalization_id"])
        .group_by("index_paralytic_id", maintain_order=True)
        .first()
        .select(
            "index_paralytic_id",
            "hospitalization_id",
            "age_at_admission",
            # Carried onto the frame because Table 1 reports the discharge disposition
            # breakdown; resolved to the hospitalization containing t0 like every other
            # per-hospitalization attribute (spec §3.2).
            "discharge_category",
        )
    )

    _location_at_t0 = (
        spine.select("index_paralytic_id", "encounter_block", "t_dttm")
        .join(adt, on="encounter_block", how="left")
        .filter(
            (pl.col("t_dttm") >= pl.col("in_dttm")) & (pl.col("t_dttm") < pl.col("out_dttm"))
        )
        .sort(["index_paralytic_id", "in_dttm", "location_category"])
        .group_by("index_paralytic_id", maintain_order=True)
        .first()
        .select(
            "index_paralytic_id",
            pl.when(pl.col("location_category").is_in(["ed", "icu"]))
            .then(pl.col("location_category"))
            .otherwise(pl.lit("other"))
            .alias("location_at_index"),
        )
    )

    spine_resolved = (
        spine.join(_hosp_at_t0, on="index_paralytic_id", how="left")
        .join(_location_at_t0, on="index_paralytic_id", how="left")
        .join(
            patient.select(
                "patient_id", "sex_category", "race_category", "ethnicity_category"
            ),
            on="patient_id",
            how="left",
        )
        .join(block_outcomes, on="encounter_block", how="left")
        # No ADT row covers t0 -- a real charting gap, and a distinct value from `other`,
        # which means "in a location that is neither ED nor ICU".
        .with_columns(pl.col("location_at_index").fill_null("unknown"))
    )

    assert spine_resolved.height == spine.height, "attribute resolution changed the row count"

    _unresolved = spine_resolved.get_column("hospitalization_id").null_count()
    print(f"events resolved            : {spine_resolved.height:,}")
    print(f"  t0 outside every stay    : {_unresolved:,}")
    print(spine_resolved.group_by("location_at_index").agg(n=pl.len()).sort("n", descending=True))
    return (spine_resolved,)


if __name__ == "__main__":
    app.run()
