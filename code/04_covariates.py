import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import polars as pl

    from clifpy import compute_sofa_polars

    from clifpy.tables import (
        Adt,
        CrrtTherapy,
        HospitalDiagnosis,
        Hospitalization,
        MedicationAdminContinuous,
        Patient,
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
        Vitals,
        compute_sofa_polars,
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
        them re-derives a block, re-selects `p_num`, or re-computes a category. That is what
        keeps `table1_by_agent_block.json` and `fig_F1__cpt_cascade.csv` from disagreeing about N.

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

    RESPIRATORY_DEVICES = [
        "imv",
        "nippv",
        "cpap",
        "high flow nc",
        "face mask",
        "trach collar",
        "nasal cannula",
        "room air",
        "other",
    ]

    ICU_TYPES = [
        "general_icu",
        "cardiac_icu",
        "cardiothoracic_surgical_icu",
        "mixed_cardiothoracic_icu",
        "surgical_icu",
        "burn_icu",
        "neuro_icu",
        "neurosurgical_icu",
        "mixed_neuro_icu",
        "medical_icu",
    ]

    MEDICATION_DOSE_UNITS = config["medication_dose_units"]
    _expected_meds = {
        "rocuronium", "succinylcholine", "vecuronium", "midazolam",
        "etomidate", "ketamine", "propofol", "fentanyl",
    }
    assert set(MEDICATION_DOSE_UNITS) == _expected_meds, (
        "medication_dose_units must configure exactly the eight study medications"
    )
    _valid_units = {
        med: ({"mcg", "mcg/kg"} if med == "fentanyl" else {"mg", "mg/kg"})
        for med in _expected_meds
    }
    assert all(
        unit in _valid_units[med] for med, unit in MEDICATION_DOSE_UNITS.items()
    ), "invalid medication_dose_units; use mg[/kg], or mcg[/kg] for fentanyl"
    DOSE_SUMMARY_UPPER_BOUNDS = {
        "etomidate": 200.0,
        "fentanyl": 500.0,
        "midazolam": 50.0,
        "propofol": 500.0,
        "rocuronium": 400.0,
        "succinylcholine": 400.0,
        "vecuronium": 30.0,
    }
    DOSE_WEIGHT_LOOKBACK_DAYS = 28
    DOSE_WEIGHT_MIN_KG = 20.0
    DOSE_WEIGHT_MAX_KG = 300.0

    print(f"site           : {SITE}")
    print(f"lookback hours : {LOOKBACK_HOURS}")
    print(f"vasopressors   : {' | '.join(VASOPRESSORS)}")
    print(f"resp devices   : {' | '.join(RESPIRATORY_DEVICES)}")
    print(f"icu types      : {' | '.join(ICU_TYPES)}")
    print(f"configured units: {MEDICATION_DOSE_UNITS}")
    return (
        DATA_DIR,
        DOSE_SUMMARY_UPPER_BOUNDS,
        DOSE_WEIGHT_LOOKBACK_DAYS,
        DOSE_WEIGHT_MAX_KG,
        DOSE_WEIGHT_MIN_KG,
        FIG_DIR,
        FILETYPE,
        ICU_TYPES,
        LOOKBACK_HOURS,
        MEDICATION_DOSE_UNITS,
        PHI_DIR,
        RESPIRATORY_DEVICES,
        SHARE_DIR,
        SITE,
        TIMEZONE,
        VASOPRESSORS,
        config,
    )


@app.cell
def _(pl):
    def to_site_naive(series):
        """Strip clifpy's configured site timezone while preserving local wall time.

        `from_file(..., timezone=TIMEZONE)` has already normalized every timestamp to the
        site timezone. Defined locally, never imported (spec §4).
        """
        return series.dt.tz_localize(None)

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

        The **evidence category** (P31) is computed here, per event, from that event's own
        D and E flags. The four categories are the complete IMV-transition × sedation
        partition. Category 3 requires both on the *same* event — which is exactly what
        P15 bought by making D and E share one window predicate. The cascade in `06` reads
        this column from the `p_num = 1` row only; the category exists on every row because
        the index-level Table 1 reports it too. The persisted column remains named
        `evidence_tier` for the consortium artifact contract, although the values are
        categorical rather than ordinal.

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
        """The block's evidence category, P31, from one event's own context flags.

        1 = neither an IMV transition nor sedation
        2 = an IMV transition, no sedation
        3 = an IMV transition and sedation
        4 = sedation, no IMV transition

        Tier 3 conjoins D and E on the SAME event rather than on the block. A block whose
        first paralytic had a transition and whose fifth had sedation describes two
        clinical acts days apart, and calling that category 3 would manufacture evidence that
        no single intubation ever produced.
        """
        return (
            pl.when(pl.col(imv_col) & pl.col(sed_col))
            .then(pl.lit(3))
            .when(pl.col(imv_col))
            .then(pl.lit(2))
            .when(pl.col(sed_col))
            .then(pl.lit(4))
            .otherwise(pl.lit(1))
            .cast(pl.Int8)
        )

    index_context = pl.read_parquet(PHI_DIR / "step03__index_context.parquet")

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
        # sorted agent set; step02__index_paralytic_composition.csv already separates that from same-agent
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
    cohort_index = pl.read_parquet(PHI_DIR / "step01__cohort_index.parquet")

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
    cohort_index,
    pl,
    to_site_naive,
):
    _patient_ids = cohort_index.get_column("patient_id").unique().to_list()
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

    # Dose normalisation may fall back to a prior hospitalization within 28 days, so
    # this second frame deliberately spans every hospitalization for cohort patients.
    _hosp_all_table = Hospitalization.from_file(
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
        filters={"patient_id": _patient_ids},
    )
    _hosp_all_pd = _hosp_all_table.df.copy()
    for _c in ("admission_dttm", "discharge_dttm"):
        _hosp_all_pd[_c] = to_site_naive(_hosp_all_pd[_c])
    hospitalization_all = pl.from_pandas(_hosp_all_pd).with_columns(
        pl.col("discharge_category").str.to_lowercase()
    )

    print(f"hospitalizations loaded : {hospitalization.height:,}")
    print(f"patient-history hospitalizations loaded : {hospitalization_all.height:,}")
    print(hospitalization.group_by("discharge_category").agg(n=pl.len()).sort("n", descending=True))
    return hospitalization, hospitalization_all


@app.cell
def _(Adt, DATA_DIR, FILETYPE, TIMEZONE, bridge, bridge_hosp_ids, pl, to_site_naive):
    _adt_table = Adt.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "hospital_id",
            "hospital_type",
            "location_category",
            "location_type",
            "in_dttm",
            "out_dttm",
        ],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    _adt_pd = _adt_table.df.copy()
    for _c in ("in_dttm", "out_dttm"):
        _adt_pd[_c] = to_site_naive(_adt_pd[_c])

    adt = (
        pl.from_pandas(_adt_pd)
        .with_columns(
            pl.col("hospital_type").str.to_lowercase(),
            pl.col("location_category").str.to_lowercase(),
            pl.col("location_type").str.to_lowercase(),
        )
        .join(bridge.select("hospitalization_id", "encounter_block"), on="hospitalization_id", how="inner")
    )

    # 01's cohort inclusion step already requires >=1 ADT row in {ed, icu} for every
    # block in the cohort (see step01__consort_cohort.csv). So a block with ZERO adt rows here
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

        Returns one row per encounter_block with two booleans:

          hospital_mortality  death_dttm inside a member hospitalization's
                              admission -> discharge interval, OR
                              discharge_category == 'expired'
          icu_mortality       death_dttm inside an ADT icu interval

        Two INDEPENDENT measurements, published side by side (P37 as amended
        2026-08-12). Neither is derived from the other and icu_mortality is deliberately
        NOT constrained to be a subset of hospital_mortality: at MIMIC a death_dttm can
        trail its own discharge_dttm by up to 24 hours while the ADT icu interval extends
        past discharge too, so a handful of blocks are icu_mortality without satisfying
        the hospital_mortality bound. That is a recording artifact, and the amended
        decision accepts it rather than papering over it with a grace window fitted to
        one site.

        The bound on death_dttm is retained and is the whole point of the first flag (see
        the module docstring of tests/test_mortality_bound.py): unbounded, it fires for a
        patient discharged alive who died at home months later.
        """
        # NOTE (2026-08-12 final review, left unchanged): a null `discharge_dttm` (an
        # open encounter) makes this whole comparison null in polars, not true, so
        # `_death_in_stay` is silently False for a death recorded during a stay that
        # has not yet been discharged. `hospital_mortality` still catches it when
        # `discharge_category == 'expired'` is charted, but a death in an open
        # encounter with a different discharge_category is missed by this flag.
        # Changing mortality semantics is a spec decision, not an implementation one --
        # P37 was already amended once (see the docstring above) -- so this is recorded
        # rather than silently patched.
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
        return (
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
            .drop("_death_dated_in_stay", "_expired_category")
            .sort("encounter_block")
        )

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
    #
    # Null-propagating, not `pl.col("_days").sum()` directly: polars' `.sum()` over a
    # group that is ALL null returns 0.0, not null. A block whose only hospitalization
    # has a null `discharge_dttm` (an open encounter) would therefore publish
    # `los_hospital_days = 0.0` -- a fabricated measured zero, indistinguishable from a
    # real same-day stay, and invisible to Table 1 because `los_hospital_days_n_nonnull`
    # only counts blocks that got a value at all and this fabricated zero counts as one.
    # If ANY member interval is unmeasurable the block's LOS is null instead -- a
    # partial sum over the measurable members would understate the true LOS just as
    # silently as the all-null zero does.
    los_hospital = (
        hospitalization.with_columns(
            (
                (epoch_minutes("discharge_dttm") - epoch_minutes("admission_dttm")) / 1440.0
            ).alias("_days")
        )
        .group_by("encounter_block")
        .agg(
            pl.when(pl.col("_days").is_null().any())
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("_days").sum())
            .round(3)
            .alias("los_hospital_days")
        )
    )

    # Same null-propagation, same reason, for the ICU sum: a null `out_dttm` (an open
    # final ADT interval) must not silently become a zero or a truncated partial sum.
    # `_has_icu_row` is carried through so the `fill_null(0.0)` below (which is correct
    # for a block with NO icu row at all) cannot also swallow this different case -- a
    # block that DOES have an icu row but one with an unmeasurable interval. "no ICU
    # stay" and "ICU stay of unknown length" are different facts and must stay
    # distinguishable after the join, not collapse into the same null.
    los_icu = (
        adt_icu.with_columns(
            ((epoch_minutes("out_dttm") - epoch_minutes("in_dttm")) / 1440.0).alias("_days")
        )
        .group_by("encounter_block")
        .agg(
            pl.when(pl.col("_days").is_null().any())
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("_days").sum())
            .round(3)
            .alias("los_icu_days"),
            pl.lit(True).alias("_has_icu_row"),
        )
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
        #
        # Only for blocks where `_has_icu_row` is null -- i.e. absent from `los_icu`
        # entirely, which happens only when the block has no icu row at all. A block
        # that DOES have an icu row but an unmeasurable one (`_has_icu_row` is True,
        # `los_icu_days` is null from the agg above) must keep its null, not be
        # collapsed into the same "no ICU stay" zero.
        .with_columns(
            pl.when(pl.col("_has_icu_row").is_null())
            .then(pl.col("los_icu_days").fill_null(0.0))
            .otherwise(pl.col("los_icu_days"))
            .alias("los_icu_days")
        )
        .drop("_has_icu_row")
        .sort("encounter_block")
    )

    print(f"blocks with outcomes : {block_outcomes.height:,}")
    print(f"  hospital mortality : {block_outcomes.get_column('hospital_mortality').sum():,}")
    print(f"  icu mortality      : {block_outcomes.get_column('icu_mortality').sum():,}")
    return block_outcomes, los_hospital, los_icu


@app.cell
def _(ICU_TYPES, adt, block_outcomes, hospitalization, patient, pl, spine):
    # The hospitalization containing t0 (spec §3.2). An interval join, not a "first
    # hospitalization" shortcut: the ED presentation and the inpatient admission carry
    # different ages and different diagnosis lists, and the paralytic belongs to one.
    _hosp_at_t0 = (
        spine.select("index_paralytic_id", "encounter_block", "t_dttm")
        .join(hospitalization, on="encounter_block", how="left")
        .filter(
            (pl.col("t_dttm") >= pl.col("admission_dttm"))
            & (
                pl.col("discharge_dttm").is_null()
                | (pl.col("t_dttm") <= pl.col("discharge_dttm"))
            )
        )
        # A t0 landing in two member hospitalizations would mean overlapping stays, which
        # the stitcher should have merged -- it should not happen, but the tiebreak below
        # is deterministic and complete rather than relying on that: sorted first by
        # admission_dttm (earliest wins) and then by hospitalization_id (a total order on
        # the remaining candidates, so even a same-instant admission_dttm tie resolves the
        # same way on every run) before `.first()` picks the row.
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
            (pl.col("t_dttm") >= pl.col("in_dttm"))
            & (pl.col("out_dttm").is_null() | (pl.col("t_dttm") < pl.col("out_dttm")))
        )
        .sort(["index_paralytic_id", "in_dttm", "location_category", "hospital_id"])
        .group_by("index_paralytic_id", maintain_order=True)
        .first()
        .select(
            "index_paralytic_id",
            pl.col("hospital_id").fill_null("unknown").alias("hospital"),
            pl.when(pl.col("hospital_type").is_null())
            .then(pl.lit("unknown"))
            .when(pl.col("hospital_type") == "academic")
            .then(pl.lit("academic"))
            .otherwise(pl.lit("non-academic"))
            .alias("academic_status"),
            pl.when(
                pl.col("location_category").is_in(["ed", "icu", "ward", "procedural"])
            )
            .then(pl.col("location_category"))
            .otherwise(pl.lit("other"))
            .alias("location_at_index"),
            pl.when(pl.col("location_category") == "icu")
            .then(pl.col("location_type"))
            .otherwise(None)
            .alias("location_type_at_index"),
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
        .with_columns(
            pl.col("hospital").fill_null("unknown"),
            pl.col("academic_status").fill_null("unknown"),
        )
        .with_columns(
            *[
                (
                    (pl.col("location_at_index") == "icu")
                    & (pl.col("location_type_at_index") == _icu_type)
                )
                .fill_null(False)
                .alias(f"icu_type_{_icu_type}")
                for _icu_type in ICU_TYPES
            ],
            (
                (pl.col("location_at_index") == "icu")
                & ~pl.col("location_type_at_index").is_in(ICU_TYPES).fill_null(False)
            ).alias("icu_type_unspecified"),
        )
    )

    assert spine_resolved.height == spine.height, "attribute resolution changed the row count"

    _unresolved = spine_resolved.get_column("hospitalization_id").null_count()
    print(f"events resolved            : {spine_resolved.height:,}")
    print(f"  t0 outside every stay    : {_unresolved:,}")
    print(spine_resolved.group_by("location_at_index").agg(n=pl.len()).sort("n", descending=True))
    return (spine_resolved,)


@app.cell
def _(pl):
    def select_dose_weights(
        events,
        hospitalizations,
        weights,
        lookback_days=28,
        min_weight_kg=20.0,
        max_weight_kg=300.0,
    ):
        """Select one weight for dose normalisation without changing Table 1 weight.

        Current-hospital weights have priority and may come from any time at or before
        the index. If none exists, use the latest prior-hospital weight recorded within
        `lookback_days` before the index. Only finite values in the closed physiological
        range are eligible. The complete sort makes equal-timestamp choices stable.
        """
        _event_cols = [
            "index_paralytic_id",
            "patient_id",
            "current_hospitalization_id",
            "t_dttm",
        ]
        _empty = events.select(
            "index_paralytic_id",
            pl.lit(None, dtype=pl.Float64).alias("dose_weight_kg"),
            pl.lit(None, dtype=pl.String).alias("dose_weight_source"),
            pl.lit(None, dtype=pl.Datetime).alias("dose_weight_recorded_dttm"),
            pl.lit(None, dtype=pl.Float64).alias("dose_weight_age_days"),
        )
        if weights is None or weights.height == 0:
            return _empty

        _current_hosp = hospitalizations.select(
            pl.col("hospitalization_id").alias("current_hospitalization_id"),
            pl.col("admission_dttm").alias("current_admission_dttm"),
        )
        _weight_hosp = hospitalizations.select(
            pl.col("hospitalization_id").alias("weight_hospitalization_id"),
            "patient_id",
            pl.col("admission_dttm").alias("weight_hospital_admission_dttm"),
        )
        _events = events.select(_event_cols).join(
            _current_hosp, on="current_hospitalization_id", how="left"
        )
        _candidates = weights.select(
            pl.col("hospitalization_id").alias("weight_hospitalization_id"),
            "recorded_dttm",
            pl.col("vital_value").alias("weight_kg"),
        ).join(_weight_hosp, on="weight_hospitalization_id", how="inner")

        _is_current = (
            pl.col("weight_hospitalization_id")
            == pl.col("current_hospitalization_id")
        )
        _is_prior = (
            (pl.col("weight_hospital_admission_dttm") < pl.col("current_admission_dttm"))
            & (
                pl.col("recorded_dttm")
                >= pl.col("t_dttm") - pl.duration(days=lookback_days)
            )
        )
        _eligible = (
            _events.join(_candidates, on="patient_id", how="inner")
            .filter(
                pl.col("recorded_dttm").is_not_null()
                & (pl.col("recorded_dttm") <= pl.col("t_dttm"))
                & pl.col("weight_kg").is_not_null()
                & pl.col("weight_kg").is_finite()
                & pl.col("weight_kg").is_between(
                    min_weight_kg, max_weight_kg, closed="both"
                )
                & (_is_current | _is_prior)
            )
            .with_columns(
                pl.when(_is_current)
                .then(pl.lit(0))
                .otherwise(pl.lit(1))
                .alias("_source_order"),
                pl.when(_is_current)
                .then(pl.lit("current_hospitalization"))
                .otherwise(pl.lit("prior_hospitalization_28d"))
                .alias("dose_weight_source"),
            )
            .sort(
                [
                    "index_paralytic_id",
                    "_source_order",
                    "recorded_dttm",
                    "weight_hospitalization_id",
                    "weight_kg",
                ],
                descending=[False, False, True, False, False],
            )
            .group_by("index_paralytic_id", maintain_order=True)
            .first()
            .select(
                "index_paralytic_id",
                pl.col("weight_kg").alias("dose_weight_kg"),
                "dose_weight_source",
                pl.col("recorded_dttm").alias("dose_weight_recorded_dttm"),
                (
                    (pl.col("t_dttm") - pl.col("recorded_dttm")).dt.total_seconds()
                    / 86400.0
                ).alias("dose_weight_age_days"),
            )
        )
        return _empty.select("index_paralytic_id").join(
            _eligible, on="index_paralytic_id", how="left"
        )

    return (select_dose_weights,)


@app.cell
def _(SHARE_DIR, SITE, pl, publish, spine_resolved):
    # One block-first event is the requested intubation-counting unit. This remains an
    # operational VentTRACE definition, not confirmation of an endotracheal procedure.
    intubations_by_hospital_year = (
        spine_resolved.filter(pl.col("p_num") == 1)
        .with_columns(pl.col("t_dttm").dt.year().cast(pl.Int16).alias("calendar_year"))
        .group_by(["hospital", "academic_status", "calendar_year"])
        .agg(n_intubations=pl.len())
        .with_columns(
            pl.lit(SITE).alias("healthcare_system"),
            pl.lit("block-first VentTRACE paralytic-index event").alias("event_definition"),
        )
        .select(
            "healthcare_system",
            "hospital",
            "academic_status",
            "calendar_year",
            "n_intubations",
            "event_definition",
        )
        .sort(["healthcare_system", "hospital", "academic_status", "calendar_year"])
    )
    publish(
        intubations_by_hospital_year,
        SHARE_DIR / "step04__intubations_by_hospital_year.csv",
        "step04__intubations_by_hospital_year",
    )
    assert intubations_by_hospital_year.get_column("n_intubations").sum() == spine_resolved.filter(
        pl.col("p_num") == 1
    ).height
    return (intubations_by_hospital_year,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Life support before the index

        Life-support sources, three windows, one predicate (P33). Every exposure is a **presence
        test** — did any row for this patient land in `[t₀ - Xh, t₀]` — because that is all
        P32 permits continuous medications to supply. No dose, no rate, no infusion-derived
        index event.

        **An absent optional table yields null, never `false`.** "No vasopressor row in 24
        h" is returned identically by a patient on no pressors and by a site that does not
        populate `medication_admin_continuous`. A `false` would make the second look like
        the first; a null cannot be misread, and `fig_T2__source_coverage.csv` is what qualifies
        it.

        The configured intermittent-dose unit filter does not apply here. Every row in
        `medication_admin_continuous` is rate-charted by definition, and filtering by an
        intermittent amount unit would zero the vasopressor column entirely. Presence of
        an infusion **is** the exposure here; no dose or rate is read at all (P32).
        """
    )
    return


@app.cell
def _(LOOKBACK_HOURS, in_lookback, pl):
    def load_optional(loader, label, **kwargs):
        """Load an OPTIONAL clifpy table, returning None when the site does not have it.

        Required tables (`patient`, `patient_procedures`) do not go through this -- they
        raise. Optional ones degrade: the caller produces null columns and coverage
        publishes 0%, which is a visibly different result from a clinical zero.

        Catches only the absence of data, never a malformed load: a table that exists but
        fails to parse is a real error and must not be silently downgraded to "this site
        does not chart CRRT".
        """
        try:
            table = loader.from_file(**kwargs)
        except FileNotFoundError as exc:
            print(f"  [{label}] NOT AVAILABLE at this site -- {exc}")
            return None
        if table.df is None or len(table.df) == 0:
            print(f"  [{label}] present but empty")
            return None
        print(f"  [{label}] {len(table.df):,} rows")
        return table.df.copy()

    def exposure_flags(events, source, dttm_col, prefix):
        """One boolean per look-back window, per index event, for one exposure source.

        `events` carries index_paralytic_id, encounter_block and t_dttm.
        `source` carries encounter_block and `dttm_col`; None when the table is absent.

        Returns one row per index_paralytic_id with `{prefix}_{h}h` for each window. When
        `source` is None every column is a typed null -- NOT false (spec §4).

        The join is on encounter_block and nothing else, so an exposure can never be
        attributed across blocks. It fans out to (events x source rows within the block)
        before the group_by collapses it; that is the same accepted quadratic shape as
        sub-analysis A's pairing, bounded here by one patient's charting.
        """
        cols = [f"{prefix}_{h}h" for h in LOOKBACK_HOURS]
        if source is None:
            return events.select(
                "index_paralytic_id",
                *[pl.lit(None, dtype=pl.Boolean).alias(c) for c in cols],
            )
        return (
            events.select("index_paralytic_id", "encounter_block", "t_dttm")
            .join(source.select("encounter_block", dttm_col), on="encounter_block", how="left")
            .group_by("index_paralytic_id")
            .agg(
                *[
                    in_lookback("t_dttm", dttm_col, h).any().alias(f"{prefix}_{h}h")
                    for h in LOOKBACK_HOURS
                ]
            )
            # Null-handling for "table exists, this patient has no row in it" already
            # happened inside in_lookback: its own `.fill_null(False)` resolves a null
            # dttm_col (the left join's unmatched side) to "not an exposure" before
            # `.any()` ever sees it, so `.any()` over an all-null group already reduces to
            # False. This trailing fill_null is therefore belt-and-braces, not where the
            # semantics live -- kept only as a defensive backstop, not load-bearing.
            .with_columns([pl.col(c).fill_null(False) for c in cols])
        )

    def category_exposure_flags(
        events, source, dttm_col, category_col, prefix, categories
    ):
        """Nonexclusive exposure flags for every category and look-back window."""
        cols = [
            f"{prefix}_{category.replace(' ', '_')}_{h}h"
            for category in categories
            for h in LOOKBACK_HOURS
        ]
        if source is None:
            return events.select(
                "index_paralytic_id",
                *[pl.lit(None, dtype=pl.Boolean).alias(c) for c in cols],
            )

        _joined = events.select(
            "index_paralytic_id", "encounter_block", "t_dttm"
        ).join(
            source.select("encounter_block", dttm_col, category_col),
            on="encounter_block",
            how="left",
        )
        return _joined.group_by("index_paralytic_id").agg(
            *[
                (
                    in_lookback("t_dttm", dttm_col, h)
                    & (pl.col(category_col) == category)
                )
                .any()
                .fill_null(False)
                .alias(f"{prefix}_{category.replace(' ', '_')}_{h}h")
                for category in categories
                for h in LOOKBACK_HOURS
            ]
        )

    return category_exposure_flags, exposure_flags, load_optional


@app.cell
def _(
    DATA_DIR,
    DOSE_WEIGHT_LOOKBACK_DAYS,
    DOSE_WEIGHT_MAX_KG,
    DOSE_WEIGHT_MIN_KG,
    FILETYPE,
    PHI_DIR,
    TIMEZONE,
    Vitals,
    hospitalization_all,
    load_optional,
    pl,
    select_dose_weights,
    spine_resolved,
    to_site_naive,
):
    _all_hosp_ids = hospitalization_all.get_column("hospitalization_id").unique().to_list()
    _weight_pd = load_optional(
        Vitals,
        "vitals weights for dose normalisation",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm", "vital_category", "vital_value"],
        filters={
            "hospitalization_id": _all_hosp_ids,
            "vital_category": [
                "weight_kg",
                "WEIGHT_KG",
                "Weight_Kg",
                "Weight_kg",
                "weightKg",
                "WeightKg",
            ],
        },
    )
    if _weight_pd is None:
        dose_weight_rows = None
    else:
        _weight_pd["recorded_dttm"] = to_site_naive(_weight_pd["recorded_dttm"])
        dose_weight_rows = pl.from_pandas(_weight_pd).filter(
            pl.col("vital_category")
            .str.to_lowercase()
            .str.replace_all("_", "")
            == "weightkg"
        )

    dose_weights = select_dose_weights(
        spine_resolved.select(
            "index_paralytic_id",
            "patient_id",
            pl.col("hospitalization_id").alias("current_hospitalization_id"),
            "t_dttm",
        ),
        hospitalization_all,
        dose_weight_rows,
        lookback_days=DOSE_WEIGHT_LOOKBACK_DAYS,
        min_weight_kg=DOSE_WEIGHT_MIN_KG,
        max_weight_kg=DOSE_WEIGHT_MAX_KG,
    )
    assert dose_weights.height == spine_resolved.height
    dose_weights.write_parquet(PHI_DIR / "step04__dose_weights.parquet")
    print("dose-normalisation weight sources:")
    print(
        dose_weights.with_columns(
            pl.col("dose_weight_source").fill_null("no_eligible_weight")
        )
        .group_by("dose_weight_source")
        .agg(n_events=pl.len())
        .sort("n_events", descending=True)
    )
    return dose_weight_rows, dose_weights


@app.cell
def _(pl):
    def prepare_configured_doses(df, configured_units):
        """Keep finite doses in their exact configured unit without conversion."""
        _usable = df.filter(
            pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & pl.col("med_dose_unit").is_not_null()
        )
        _expected_unit = pl.col("med_category").replace_strict(configured_units)
        assert _usable.filter(pl.col("med_dose_unit") != _expected_unit).height == 0, (
            "a non-configured medication unit reached dose analysis"
        )
        return _usable.with_columns(
            pl.col("med_dose").alias("med_dose_converted"),
            pl.col("med_dose_unit").alias("med_dose_unit_converted"),
            pl.lit("amount").alias("_unit_class"),
            pl.lit("configured_unit").alias("_convert_status"),
        )

    def filter_doses_for_summary(df, upper_bounds):
        """Apply positive-dose checks and absolute-unit clinical upper bounds."""
        _category = pl.col("med_category").str.strip_chars().str.to_lowercase()
        _raw_unit = pl.col("med_dose_unit").str.strip_chars().str.to_lowercase()
        _upper_bound = pl.lit(None, dtype=pl.Float64)
        for _med, _bound in upper_bounds.items():
            _upper_bound = (
                pl.when(_category == _med)
                .then(pl.lit(float(_bound)))
                .otherwise(_upper_bound)
            )
        return (
            df.with_columns(
                _upper_bound.alias("_upper_bound"),
            )
            .filter(
                (pl.col("med_dose_converted") > 0)
                & (
                    _raw_unit.str.ends_with("/kg")
                    | pl.col("_upper_bound").is_null()
                    | (
                        pl.col("med_dose_converted") < pl.col("_upper_bound")
                    )
                )
            )
            .drop("_upper_bound")
        )

    def ecdf_by_dose_per_weight(df):
        """Integer-count ECDF suitable for concatenation across consortium sites."""
        _group = ["med_category", "dose_per_weight_unit"]
        return (
            df.filter(
                pl.col("dose_per_weight").is_not_null()
                & pl.col("dose_per_weight").is_finite()
            )
            .group_by([*_group, "dose_per_weight"])
            .agg(n_at_dose=pl.len())
            .sort([*_group, "dose_per_weight"])
            .with_columns(
                n_cum=pl.col("n_at_dose").cum_sum().over(_group),
                n_total=pl.col("n_at_dose").sum().over(_group),
            )
            .with_columns(ecdf=(pl.col("n_cum") / pl.col("n_total")).round(6))
            .select(
                "med_category",
                "dose_per_weight_unit",
                "dose_per_weight",
                "n_at_dose",
                "n_cum",
                "n_total",
                "ecdf",
            )
        )

    return (
        ecdf_by_dose_per_weight,
        filter_doses_for_summary,
        prepare_configured_doses,
    )


@app.cell
def _(
    CrrtTherapy,
    DATA_DIR,
    FILETYPE,
    MedicationAdminContinuous,
    TIMEZONE,
    VASOPRESSORS,
    bridge,
    bridge_hosp_ids,
    load_optional,
    pl,
    to_site_naive,
):
    def _attach(df_pd, dttm_col, category_col=None):
        """Naive-ify the timestamp, lower-case the category, map to encounter_block.

        The lower-casing is P20 and is not optional even though `exposure_flags` drops
        the category column before comparing anything: these frames are returned whole
        and Task 4's coverage table groups over them. A site charting `Norepinephrine`
        beside `norepinephrine` would split into two buckets there, which is precisely
        the silent failure P20 exists to prevent. Every sibling load in this pipeline
        does the same thing one line after its from_file call.
        """
        df_pd = df_pd.copy()
        df_pd[dttm_col] = to_site_naive(df_pd[dttm_col])
        out = pl.from_pandas(df_pd)
        if category_col is not None:
            out = out.with_columns(pl.col(category_col).str.to_lowercase())
        return out.join(
            bridge.select("hospitalization_id", "encounter_block"),
            on="hospitalization_id",
            how="inner",
        )

    print("optional life-support tables:")

    _vaso_pd = load_optional(
        MedicationAdminContinuous,
        "medication_admin_continuous",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "admin_dttm", "med_category"],
        # P20: casing variants enumerated at the from_file boundary.
        filters={
            "hospitalization_id": bridge_hosp_ids,
            "med_category": VASOPRESSORS + [v.title() for v in VASOPRESSORS] + [v.upper() for v in VASOPRESSORS],
        },
    )
    vasopressor = _attach(_vaso_pd, "admin_dttm", "med_category") if _vaso_pd is not None else None

    _crrt_pd = load_optional(
        CrrtTherapy,
        "crrt_therapy",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm"],
        filters={"hospitalization_id": bridge_hosp_ids},
    )
    # P33 as the study lead specified it: presence of ANY charted CRRT record in the
    # window is the exposure. No filter on modality or on a dose being non-zero.
    crrt = _attach(_crrt_pd, "recorded_dttm") if _crrt_pd is not None else None

    # `position` / prone was withdrawn from this notebook on 2026-08-14 at the study
    # lead's direction: proning is not a covariate of this study. The table is no longer
    # opened, so it is neither a required nor an optional dependency, and its absence at
    # a site is not a fact this pipeline reports.

    return crrt, vasopressor


@app.cell
def _(
    VASOPRESSORS,
    category_exposure_flags,
    crrt,
    exposure_flags,
    spine_resolved,
    vasopressor,
):
    _events = spine_resolved.select("index_paralytic_id", "encounter_block", "t_dttm")

    exposures = (
        exposure_flags(_events, vasopressor, "admin_dttm", "vasopressor")
        .join(
            category_exposure_flags(
                _events,
                vasopressor,
                "admin_dttm",
                "med_category",
                "vasopressor",
                VASOPRESSORS,
            ),
            on="index_paralytic_id",
        )
        .join(
            exposure_flags(_events, crrt, "recorded_dttm", "crrt"),
            on="index_paralytic_id",
        )
    )

    assert exposures.height == spine_resolved.height, "exposure join changed the row count"

    for _c in sorted(c for c in exposures.columns if c != "index_paralytic_id"):
        _col = exposures.get_column(_c)
        if _col.null_count() == exposures.height:
            print(f"  {_c:22s} table absent -- all null")
        else:
            print(f"  {_c:22s} {_col.sum():,} of {exposures.height:,}")
    return (exposures,)


@app.cell
def _(
    PHI_DIR,
    RESPIRATORY_DEVICES,
    category_exposure_flags,
    pl,
    spine_resolved,
):
    resp_waterfall = pl.read_parquet(PHI_DIR / "step01__cohort_resp_waterfall.parquet")
    _run_ids = resp_waterfall.get_column("cohort_run_id").unique().to_list()
    _expected_run_ids = spine_resolved.get_column("cohort_run_id").unique().to_list()
    assert not _run_ids or _run_ids == _expected_run_ids, (
        "cohort_resp_waterfall and the analytic spine carry different cohort_run_ids"
    )

    _events = spine_resolved.select(
        "index_paralytic_id", "encounter_block", "t_dttm"
    )
    respiratory_exposures = category_exposure_flags(
        _events,
        resp_waterfall,
        "recorded_dttm",
        "device_category",
        "respiratory_device",
        RESPIRATORY_DEVICES,
    )
    assert respiratory_exposures.height == spine_resolved.height, (
        "respiratory exposure aggregation changed the event count"
    )
    print("respiratory support before the index:")
    for _c in sorted(c for c in respiratory_exposures.columns if c != "index_paralytic_id"):
        print(f"  {_c:38s} {respiratory_exposures.get_column(_c).sum():,}")
    return respiratory_exposures, resp_waterfall


@app.cell
def _(mo):
    mo.md(
        """
        ## Physiology and comorbidity

        Worst value in each look-back window — lowest SBP, lowest DBP, highest HR, lowest SpO₂ — which
        is what makes "was this a crashing patient" answerable. Weight is the most recent
        value at or before `t₀` with no look-back limit: a weight recorded on admission is
        still the patient's weight a week later, and bounding it would null out most of the
        cohort for no gain (spec §3.2).

        CCI comes from clifpy, computed on the hospitalization containing `t₀`.
        """
    )
    return


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    LOOKBACK_HOURS,
    TIMEZONE,
    Vitals,
    bridge,
    bridge_hosp_ids,
    in_lookback,
    load_optional,
    pl,
    spine_resolved,
    to_site_naive,
):
    _VITAL_SPECS = [
        ("sbp", "lowest", "sbp"),
        ("dbp", "lowest", "dbp"),
        ("heart_rate", "highest", "hr"),
        ("spo2", "lowest", "spo2"),
    ]
    _VITAL_CATEGORIES = [c for c, _, _ in _VITAL_SPECS] + ["weight_kg"]

    # P20 casing variants, enumerated by hand rather than by `.upper()/.title()`.
    # `"spo2".title()` is `"Spo2"` and never `"SpO2"`, which is how most EHRs spell it --
    # a site charting `SpO2` would silently return zero rows for that category while sbp
    # and heart_rate loaded fine, leaving all three lowest_spo2_*h columns null and
    # `covariate_coverage` still reporting vitals at ~100%. Nothing downstream would
    # signal the loss; Table 1 would show an SpO2 row that is 100% missing and read as a
    # charting gap. The post-load check below is the second half of the defence.
    _VITAL_VARIANTS = sorted(
        {v for c in _VITAL_CATEGORIES for v in (c, c.upper(), c.title(), c.capitalize())}
        | {"SpO2", "spO2", "SpO₂", "HeartRate", "heartRate", "weightKg", "WeightKg"}
    )

    print("optional physiology table:")
    _vit_pd = load_optional(
        Vitals,
        "vitals",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm", "vital_category", "vital_value"],
        filters={
            "hospitalization_id": bridge_hosp_ids,
            "vital_category": _VITAL_VARIANTS,
        },
    )

    _events = spine_resolved.select("index_paralytic_id", "encounter_block", "t_dttm")
    # Bound unconditionally: the coverage cell consumes `vitals` whether or not the
    # table loaded, and a name bound only inside the else branch is a NameError at
    # exactly the sites this degradation path exists for.
    vitals = None
    _physio_cols = [
        f"{direction}_{short}_{h}h"
        for _, direction, short in _VITAL_SPECS
        for h in LOOKBACK_HOURS
    ] + ["weight_kg"]

    if _vit_pd is None:
        physiology = _events.select(
            "index_paralytic_id",
            *[pl.lit(None, dtype=pl.Float64).alias(c) for c in _physio_cols],
        )
    else:
        # The raw casings the load actually returned, printed before normalisation, and
        # a loud line for any requested category that came back with zero rows. A filter
        # matching zero rows is indistinguishable from a site that never charts the
        # vital, and only this print separates them. Same posture as the vocabulary
        # probe in `01_cohort.py`.
        print("  vital_category casings returned by the load:")
        for _raw, _n in sorted(_vit_pd["vital_category"].value_counts().items()):
            print(f"    {_raw!r:20s} {_n:,}")
        _seen = {str(v).lower() for v in _vit_pd["vital_category"].unique()}
        for _want in _VITAL_CATEGORIES:
            if _want not in _seen:
                print(
                    f"  WARNING: vital_category {_want!r} returned ZERO rows. Either this "
                    "site does not chart it, or its casing is missing from _VITAL_VARIANTS "
                    "-- every statistic derived from it will be null and coverage will "
                    "still report vitals as available."
                )

        _vit_pd["recorded_dttm"] = to_site_naive(_vit_pd["recorded_dttm"])
        vitals = (
            pl.from_pandas(_vit_pd)
            .with_columns(pl.col("vital_category").str.to_lowercase())
            .join(
                bridge.select("hospitalization_id", "encounter_block"),
                on="hospitalization_id",
                how="inner",
            )
        )

        _joined = _events.join(
            vitals.select("encounter_block", "recorded_dttm", "vital_category", "vital_value"),
            on="encounter_block",
            how="left",
        )

        _aggs = []
        for _cat, _direction, _short in _VITAL_SPECS:
            for _h in LOOKBACK_HOURS:
                _in = in_lookback("t_dttm", "recorded_dttm", _h) & (
                    pl.col("vital_category") == _cat
                )
                _value = pl.when(_in).then(pl.col("vital_value")).otherwise(None)
                _reduced = _value.min() if _direction == "lowest" else _value.max()
                _aggs.append(_reduced.alias(f"{_direction}_{_short}_{_h}h"))

        # Weight: most recent at or before t0, no look-back limit. `sort_by` then `last`
        # is the deterministic pick -- ties broken by the value itself so a re-run cannot
        # choose differently.
        # `vital_value.is_not_null()` is part of the mask, not an afterthought: without
        # it a charted-but-null weight row at the latest timestamp sorts last and
        # `.last()` returns null, discarding an earlier real weight.
        _weight_mask = (
            (pl.col("vital_category") == "weight_kg")
            & (pl.col("recorded_dttm") <= pl.col("t_dttm"))
            & pl.col("vital_value").is_not_null()
        )
        _aggs.append(
            pl.when(_weight_mask)
            .then(pl.col("vital_value"))
            .otherwise(None)
            .sort_by(
                pl.when(_weight_mask).then(pl.col("recorded_dttm")).otherwise(None),
                pl.when(_weight_mask).then(pl.col("vital_value")).otherwise(None),
                nulls_last=False,
            )
            .last()
            .alias("weight_kg")
        )

        physiology = _joined.group_by("index_paralytic_id").agg(*_aggs)

    assert physiology.height == spine_resolved.height, "physiology join changed the row count"
    for _c in _physio_cols:
        _col = physiology.get_column(_c)
        print(f"  {_c:22s} {physiology.height - _col.null_count():,} non-null")
    return physiology, vitals


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    HospitalDiagnosis,
    TIMEZONE,
    bridge,
    bridge_hosp_ids,
    load_optional,
    pl,
    spine_resolved,
):
    print("optional comorbidity table:")
    _diag_pd = load_optional(
        HospitalDiagnosis,
        "hospital_diagnosis",
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "diagnosis_code", "diagnosis_code_format"],
        filters={"hospitalization_id": bridge_hosp_ids},
    )

    # Bound unconditionally for the same reason `vitals` is: the coverage cell
    # consumes it on both paths.
    diagnosis = None

    if _diag_pd is None:
        comorbidity = spine_resolved.select(
            "index_paralytic_id", pl.lit(None, dtype=pl.Int32).alias("cci")
        )
    else:
        from clifpy.utils.comorbidity import calculate_cci

        _cci_pd = calculate_cci(_diag_pd)
        _cci_col = [c for c in _cci_pd.columns if c.lower() in ("cci_score", "cci")]
        assert _cci_col, (
            f"clifpy's CCI output has no recognisable score column: {list(_cci_pd.columns)}"
        )
        _cci = pl.from_pandas(_cci_pd).select(
            "hospitalization_id", pl.col(_cci_col[0]).cast(pl.Int32).alias("cci")
        )
        # Joined on the hospitalization containing t0 (spec §3.2), which spine_resolved
        # already carries -- not on the block, whose four member stays can have four
        # different diagnosis lists.
        comorbidity = spine_resolved.select(
            "index_paralytic_id", "hospitalization_id"
        ).join(_cci, on="hospitalization_id", how="left").select("index_paralytic_id", "cci")

        diagnosis = pl.from_pandas(_diag_pd).join(
            bridge.select("hospitalization_id", "encounter_block"),
            on="hospitalization_id",
            how="inner",
        )

    assert comorbidity.height == spine_resolved.height, "CCI join changed the row count"
    print(f"  cci non-null : {comorbidity.height - comorbidity.get_column('cci').null_count():,}")
    return comorbidity, diagnosis


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    SHARE_DIR,
    SITE,
    TIMEZONE,
    bridge,
    compute_sofa_polars,
    pl,
    publish,
    spine_resolved,
):
    _sofa_cohort = (
        spine_resolved.select(
            "index_paralytic_id", "encounter_block", "t_dttm"
        )
        .join(
            bridge.select("encounter_block", "hospitalization_id"),
            on="encounter_block",
            how="inner",
        )
        .select(
            pl.col("hospitalization_id").cast(pl.String),
            "index_paralytic_id",
            start_dttm=pl.col("t_dttm") - pl.duration(hours=24),
            end_dttm=pl.col("t_dttm"),
        )
    )

    sofa_raw = compute_sofa_polars(
        data_directory=DATA_DIR,
        cohort_df=_sofa_cohort,
        filetype=FILETYPE,
        id_name="index_paralytic_id",
        extremal_type="worst",
        fill_na_scores_with_zero=True,
        remove_outliers=True,
        timezone=TIMEZONE,
    )

    _component_inputs = {
        "sofa_cv_97": [
            "map",
            "norepinephrine_mcg_kg_min",
            "epinephrine_mcg_kg_min",
            "dopamine_mcg_kg_min",
            "dobutamine_mcg_kg_min",
        ],
        "sofa_coag": ["platelet_count"],
        "sofa_liver": ["bilirubin_total"],
        "sofa_resp": ["p_f"],
        "sofa_cns": ["gcs_total"],
        "sofa_renal": ["creatinine"],
    }
    _available_exprs = []
    for _component, _inputs in _component_inputs.items():
        _present = [c for c in _inputs if c in sofa_raw.columns]
        _available_exprs.append(
            (
                pl.any_horizontal([pl.col(c).is_not_null() for c in _present])
                if _present
                else pl.lit(False)
            ).alias(f"{_component}_available")
        )
    sofa_raw = sofa_raw.with_columns(*_available_exprs)

    _score_cols = list(_component_inputs)
    _availability_cols = [f"{c}_available" for c in _score_cols]
    sofa = (
        spine_resolved.select("index_paralytic_id")
        .join(
            sofa_raw.select(
                "index_paralytic_id", *_score_cols, *_availability_cols
            ),
            on="index_paralytic_id",
            how="left",
        )
        .with_columns(
            *[pl.col(c).fill_null(0).cast(pl.Int8) for c in _score_cols],
            *[pl.col(c).fill_null(False) for c in _availability_cols],
        )
        .with_columns(
            pl.sum_horizontal([pl.col(c) for c in _score_cols])
            .cast(pl.Int8)
            .alias("sofa_total")
        )
    )
    assert sofa.height == spine_resolved.height, "SOFA join changed the event count"

    sofa_coverage = pl.DataFrame(
        [
            {
                "component": component,
                "n_events_available": int(sofa.get_column(f"{component}_available").sum()),
                "pct_events_available": round(
                    100.0 * sofa.get_column(f"{component}_available").mean(), 2
                ),
            }
            for component in _score_cols
        ]
    ).with_columns(pl.lit(SITE).alias("site_name"))
    publish(sofa_coverage, SHARE_DIR / "step04__sofa_coverage.csv", "step04__sofa_coverage")
    print("SOFA component coverage:")
    print(sofa_coverage)
    return sofa, sofa_coverage


@app.cell
def _(
    PHI_DIR,
    comorbidity,
    exposures,
    physiology,
    pl,
    respiratory_exposures,
    sofa,
    spine_resolved,
):
    index_covariates = (
        spine_resolved.join(exposures, on="index_paralytic_id", how="left")
        .join(respiratory_exposures, on="index_paralytic_id", how="left")
        .join(physiology, on="index_paralytic_id", how="left")
        .join(comorbidity, on="index_paralytic_id", how="left")
        .join(sofa, on="index_paralytic_id", how="left")
        .sort(["encounter_block", "p_num", "index_paralytic_id"])
    )

    assert index_covariates.height == spine_resolved.height, (
        "assembling the covariate frame changed the row count"
    )
    assert index_covariates.get_column("index_paralytic_id").is_unique().all()

    # Block-level columns must be constant within a block -- pinned by
    # tests/test_block_row_contract.py, asserted here so a bad run fails at the write
    # rather than at the next notebook's aggregation.
    _block_cols = [
        "n_index_in_block",
        "los_hospital_days",
        "los_icu_days",
        "hospital_mortality",
        "icu_mortality",
    ]
    _varying = (
        index_covariates.group_by("encounter_block")
        .agg([pl.col(c).n_unique().alias(c) for c in _block_cols])
        .filter(pl.any_horizontal([pl.col(c) > 1 for c in _block_cols]))
    )
    assert _varying.height == 0, (
        f"{_varying.height:,} blocks have a block-level column varying within the block"
    )

    PHI_DIR.mkdir(parents=True, exist_ok=True)
    index_covariates.write_parquet(PHI_DIR / "step04__index_covariates.parquet")

    print(f"step04__index_covariates.parquet : {index_covariates.height:,} rows, "
          f"{len(index_covariates.columns)} columns -> {PHI_DIR}")
    print(f"  blocks         : {index_covariates.get_column('encounter_block').n_unique():,}")
    print(f"  p_num == 1     : {index_covariates.filter(pl.col('p_num') == 1).height:,}")
    return (index_covariates,)


@app.cell
def _(
    SHARE_DIR,
    SITE,
    crrt,
    diagnosis,
    index_covariates,
    pl,
    publish,
    resp_waterfall,
    vasopressor,
    vitals,
):
    # The denominator is the ANALYTIC population -- the blocks that have an index
    # paralytic -- so the numerator has to be restricted to the same blocks or the
    # ratio is meaningless. `bridge` is built from the full cohort (34,017 blocks at
    # MIMIC), so every source frame spans far more blocks than this frame does;
    # dividing an unrestricted numerator by this denominator produced coverage
    # percentages above 2000%, which is worse than no table at all: this CSV exists
    # to tell a reader whether a covariate's zero is structural or clinical, and a
    # percentage over 100 answers neither question.
    _analytic_blocks = index_covariates.get_column("encounter_block").unique()
    _n_blocks = _analytic_blocks.len()

    def _cov(name, required, frame):
        if frame is None:
            return {
                "source": name,
                "required": required,
                "available": False,
                "n_rows": 0,
                "n_blocks_with_rows": 0,
                "pct_blocks_covered": 0.0,
            }
        # `.implode()` is required, not stylistic: a bare Series argument is deprecated
        # and polars has announced the semantics will flip to element-wise list
        # comparison. pyproject pins `polars>=1.43.2` with no upper bound, so a site
        # resolving a newer polars would get a filter that matches NOTHING -- every
        # source publishing 0% coverage while `available` stays true, with no crash.
        # Matches the five existing uses in `01_cohort.py`.
        _in_scope = frame.filter(pl.col("encounter_block").is_in(_analytic_blocks.implode()))
        _b = _in_scope.get_column("encounter_block").n_unique()
        return {
            "source": name,
            "required": required,
            # `available` is a property of the SITE (did the table load at all), so it
            # stays true even when no analytic block has a row in it -- that
            # combination, available with 0% coverage, is itself informative.
            "available": True,
            # Rows and blocks are both counted within the analytic population, so
            # every column of this table shares one denominator.
            "n_rows": _in_scope.height,
            "n_blocks_with_rows": _b,
            "pct_blocks_covered": round(100.0 * _b / _n_blocks, 2),
        }

    covariate_coverage = pl.DataFrame(
        [
            _cov("medication_admin_continuous", False, vasopressor),
            _cov("crrt_therapy", False, crrt),
            _cov("respiratory_support", True, resp_waterfall),
            _cov("vitals", False, vitals),
            _cov("hospital_diagnosis", False, diagnosis),
        ]
    ).with_columns(pl.lit(SITE).alias("site_name")).sort("source")

    publish(
        covariate_coverage,
        SHARE_DIR / "fig_T2__source_coverage.csv",
        "fig_T2__source_coverage",
    )
    return (covariate_coverage,)


@app.cell
def _(
    DOSE_SUMMARY_UPPER_BOUNDS,
    MEDICATION_DOSE_UNITS,
    SHARE_DIR,
    SITE,
    dose_weights,
    ecdf_by_dose_per_weight,
    filter_doses_for_summary,
    index_context,
    pl,
    prepare_configured_doses,
    publish,
):
    _dose_weight = dose_weights.select("index_paralytic_id", "dose_weight_kg")
    paralytic_source = (
        index_context.select("index_paralytic_id", "doses")
        .join(_dose_weight, on="index_paralytic_id", how="left")
        .explode("doses")
        .unnest("doses")
        .filter(pl.col("med_category").is_not_null())
    )
    sedation_source = (
        index_context.select("index_paralytic_id", "sedatives")
        .join(_dose_weight, on="index_paralytic_id", how="left")
        .explode("sedatives")
        .unnest("sedatives")
        .filter(pl.col("med_category").is_not_null())
    )

    def _usable(frame):
        return frame.filter(
            pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & pl.col("med_dose_unit").is_not_null()
        )

    def _normalised(frame):
        _already_per_kg = pl.col("med_dose_unit_converted").str.ends_with("/kg")
        return (
            frame.filter(_already_per_kg | pl.col("dose_weight_kg").is_not_null())
            .with_columns(
                pl.when(_already_per_kg)
                .then(pl.col("med_dose_converted"))
                .otherwise(pl.col("med_dose_converted") / pl.col("dose_weight_kg"))
                .alias("dose_per_weight"),
                pl.when(_already_per_kg)
                .then(pl.col("med_dose_unit_converted"))
                .otherwise(pl.col("med_dose_unit_converted") + pl.lit("/kg"))
                .alias("dose_per_weight_unit"),
            )
            .filter(
                pl.col("dose_per_weight").is_not_null()
                & pl.col("dose_per_weight").is_finite()
            )
        )

    paralytic_usable = _usable(paralytic_source)
    sedation_usable = _usable(sedation_source)
    paralytic_converted = prepare_configured_doses(
        paralytic_usable, MEDICATION_DOSE_UNITS
    )
    sedation_converted = prepare_configured_doses(
        sedation_usable, MEDICATION_DOSE_UNITS
    )
    paralytic_plausible = filter_doses_for_summary(
        paralytic_converted, DOSE_SUMMARY_UPPER_BOUNDS
    )
    sedation_plausible = filter_doses_for_summary(
        sedation_converted, DOSE_SUMMARY_UPPER_BOUNDS
    )
    paralytic_normalised = _normalised(paralytic_plausible)
    sedation_normalised = _normalised(sedation_plausible)

    paralytic_dose_per_weight_ecdf = ecdf_by_dose_per_weight(
        paralytic_normalised
    ).with_columns(pl.lit(SITE).alias("site_name")).select(
        "site_name",
        "med_category",
        "dose_per_weight_unit",
        "dose_per_weight",
        "n_at_dose",
        "n_cum",
        "n_total",
        "ecdf",
    )
    sedation_dose_per_weight_ecdf = ecdf_by_dose_per_weight(
        sedation_normalised
    ).with_columns(pl.lit(SITE).alias("site_name")).select(
        "site_name",
        "med_category",
        "dose_per_weight_unit",
        "dose_per_weight",
        "n_at_dose",
        "n_cum",
        "n_total",
        "ecdf",
    )
    publish(
        paralytic_dose_per_weight_ecdf,
        SHARE_DIR / "fig_B2__paralytic_dose_per_weight_ecdf.csv",
        "fig_B2__paralytic_dose_per_weight_ecdf",
    )
    publish(
        sedation_dose_per_weight_ecdf,
        SHARE_DIR / "fig_E4__sedation_dose_per_weight_ecdf.csv",
        "fig_E4__sedation_dose_per_weight_ecdf",
    )

    _induction_source = sedation_source.filter(
        pl.col("med_category").is_in(["etomidate", "ketamine"])
    )
    _induction_usable = sedation_usable.filter(
        pl.col("med_category").is_in(["etomidate", "ketamine"])
    )
    _induction_converted = sedation_converted.filter(
        pl.col("med_category").is_in(["etomidate", "ketamine"])
    )
    _induction_plausible = sedation_plausible.filter(
        pl.col("med_category").is_in(["etomidate", "ketamine"])
    )
    _induction_weighted = sedation_normalised.filter(
        pl.col("med_category").is_in(["etomidate", "ketamine"])
    )
    induction_normalised = _induction_weighted

    _percentile_rows = []
    for _drug in ("etomidate", "ketamine"):
        _drug_frame = induction_normalised.filter(pl.col("med_category") == _drug)
        if _drug_frame.height == 0:
            continue
        for _percentile in range(1, 100):
            _value = _drug_frame.select(
                pl.col("dose_per_weight").quantile(
                    _percentile / 100.0, interpolation="linear"
                )
            ).item()
            _percentile_rows.append(
                {
                    "site_name": SITE,
                    "drug": _drug,
                    "percentile": _percentile,
                    "dose_mg_per_kg": _value,
                    "n_admin_windows": _drug_frame.height,
                }
            )
    induction_dose_percentiles = pl.DataFrame(
        _percentile_rows,
        schema={
            "site_name": pl.String,
            "drug": pl.String,
            "percentile": pl.Int64,
            "dose_mg_per_kg": pl.Float64,
            "n_admin_windows": pl.Int64,
        },
    ).sort(["site_name", "drug", "percentile"])
    publish(
        induction_dose_percentiles,
        SHARE_DIR / "step04__combined_induction_dose_distribution_percentiles.csv",
        "step04__combined_induction_dose_distribution_percentiles",
    )

    _tiered = induction_normalised.with_columns(
        pl.when(
            ((pl.col("med_category") == "etomidate") & (pl.col("dose_per_weight") < 0.20))
            | ((pl.col("med_category") == "ketamine") & (pl.col("dose_per_weight") < 1.00))
        )
        .then(pl.lit("reduced"))
        .when(
            (
                (pl.col("med_category") == "etomidate")
                & (pl.col("dose_per_weight") < 0.25)
            )
            | (
                (pl.col("med_category") == "ketamine")
                & (pl.col("dose_per_weight") < 1.50)
            )
        )
        .then(pl.lit("intermediate_reduced"))
        .when(
            (
                (pl.col("med_category") == "etomidate")
                & (pl.col("dose_per_weight") < 0.30)
            )
            | (
                (pl.col("med_category") == "ketamine")
                & (pl.col("dose_per_weight") < 2.00)
            )
        )
        .then(pl.lit("intermediate_full"))
        .otherwise(pl.lit("full"))
        .alias("dose_tier")
    )
    _tier_grid = pl.DataFrame(
        {
            "drug": [drug for drug in ("etomidate", "ketamine") for _ in range(4)],
            "dose_tier": [
                tier
                for _ in range(2)
                for tier in (
                    "reduced",
                    "intermediate_reduced",
                    "intermediate_full",
                    "full",
                )
            ],
            "tier_order": [1, 2, 3, 4] * 2,
        }
    )
    _tier_counts = (
        _tiered.group_by([pl.col("med_category").alias("drug"), "dose_tier"])
        .agg(n_admin_windows=pl.len())
    )
    induction_dose_tiers = (
        _tier_grid.join(_tier_counts, on=["drug", "dose_tier"], how="left")
        .with_columns(pl.col("n_admin_windows").fill_null(0))
        .with_columns(pl.col("n_admin_windows").sum().over("drug").alias("n_total"))
        .with_columns(
            pl.when(pl.col("n_total") > 0)
            .then(100.0 * pl.col("n_admin_windows") / pl.col("n_total"))
            .otherwise(None)
            .alias("pct"),
            pl.lit(SITE).alias("site_name"),
            pl.lit("(index paralytic, administration) pairs within +/-60 min").alias(
                "count_unit"
            ),
        )
        .select(
            "site_name",
            "drug",
            "dose_tier",
            "tier_order",
            "n_admin_windows",
            "n_total",
            "pct",
            "count_unit",
        )
        .sort(["site_name", "drug", "tier_order"])
    )
    publish(
        induction_dose_tiers,
        SHARE_DIR / "fig_E5__induction_dose_tiers.csv",
        "fig_E5__induction_dose_tiers",
    )

    def _flow(population, count_unit, stages):
        _rows = []
        _previous = None
        for _order, (_stage, _count) in enumerate(stages, start=1):
            _rows.append(
                {
                    "site_name": SITE,
                    "population": population,
                    "count_unit": count_unit,
                    "stage_order": _order,
                    "stage": _stage,
                    "n_remaining": _count,
                    "n_excluded": 0 if _previous is None else _previous - _count,
                }
            )
            _previous = _count
        return _rows

    _flow_rows = []
    _flow_rows.extend(
        _flow(
            "paralytic",
            "administrations",
            [
                ("source dose rows", paralytic_source.height),
                ("finite dose and non-null unit", paralytic_usable.height),
                ("positive dose and applicable absolute bound", paralytic_plausible.height),
                ("valid weight or configured per-kg unit", paralytic_normalised.height),
            ],
        )
    )
    _flow_rows.extend(
        _flow(
            "sedation",
            "administration-window pairs",
            [
                ("source dose rows", sedation_source.height),
                ("finite dose and non-null unit", sedation_usable.height),
                ("positive dose and applicable absolute bound", sedation_plausible.height),
                ("valid weight or configured per-kg unit", sedation_normalised.height),
            ],
        )
    )
    _flow_rows.extend(
        _flow(
            "induction tiers",
            "etomidate/ketamine administration-window pairs",
            [
                ("source etomidate/ketamine rows", _induction_source.height),
                ("finite dose and non-null unit", _induction_usable.height),
                ("positive dose and applicable absolute bound", _induction_plausible.height),
                ("valid weight or configured per-kg unit", _induction_weighted.height),
                ("dose/weight calculated", induction_normalised.height),
            ],
        )
    )
    dose_per_weight_consort = pl.DataFrame(_flow_rows).sort(
        ["population", "stage_order"]
    )
    publish(
        dose_per_weight_consort,
        SHARE_DIR / "fig_G1__dose_per_weight_consort.csv",
        "fig_G1__dose_per_weight_consort",
    )
    return (
        dose_per_weight_consort,
        induction_dose_percentiles,
        induction_dose_tiers,
        induction_normalised,
        paralytic_dose_per_weight_ecdf,
        paralytic_normalised,
        sedation_dose_per_weight_ecdf,
        sedation_normalised,
    )


@app.cell
def _():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return (plt,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    def _draw_ecdf(csv_name, png_name, title):
        _df = pl.read_csv(SHARE_DIR / csv_name)
        _groups = (
            _df.select("med_category", "dose_per_weight_unit")
            .unique()
            .sort(["med_category", "dose_per_weight_unit"])
            .rows()
        )
        if not _groups:
            (FIG_DIR / png_name).unlink(missing_ok=True)
            print(f"{png_name} skipped -- source CSV has zero rows")
            return _df
        _height = 1.3 + 2.1 * len(_groups)
        _fig, _axes = plt.subplots(len(_groups), 1, figsize=(9, _height), squeeze=False)
        _axes = [row[0] for row in _axes]
        for _ax, (_drug, _unit) in zip(_axes, _groups):
            _part = _df.filter(
                (pl.col("med_category") == _drug)
                & (pl.col("dose_per_weight_unit") == _unit)
            ).sort("dose_per_weight")
            _x = _part.get_column("dose_per_weight").to_list()
            _y = _part.get_column("ecdf").to_list()
            _ax.step(_x, _y, where="post", color="#2a78d6", linewidth=1.6)
            _ax.plot(_x, _y, "o", color="#2a78d6", markersize=3.2)
            _ax.set_ylim(0, 1.02)
            _ax.set_xlim(left=0)
            _ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
            _ax.set_axisbelow(True)
            for _side in ("top", "right"):
                _ax.spines[_side].set_visible(False)
            _ax.set_ylabel("cumulative\nproportion", fontsize=8)
            _ax.set_title(
                f"{_drug} | {_unit} | n = {_part['n_total'][0]:,}",
                loc="left",
                fontsize=9,
            )
        _axes[-1].set_xlabel("dose divided by selected weight")
        _fig.suptitle(title, fontsize=11)
        _fig.tight_layout()
        _fig.subplots_adjust(top=1 - 0.8 / _height, hspace=0.55)
        _fig.savefig(FIG_DIR / png_name, dpi=150)
        plt.close(_fig)
        print(f"{png_name} -> {FIG_DIR}")
        return _df

    figure_b2_df = _draw_ecdf(
        "fig_B2__paralytic_dose_per_weight_ecdf.csv",
        "fig_B2__paralytic_dose_per_weight_ecdf.png",
        "B.2 - index paralytic dose/weight empirical CDF\n"
        "20-300 kg; current hospitalization first, then prior hospitalization within 28 days",
    )
    figure_e4_df = _draw_ecdf(
        "fig_E4__sedation_dose_per_weight_ecdf.csv",
        "fig_E4__sedation_dose_per_weight_ecdf.png",
        "E.4 - sedation dose/weight empirical CDF\n"
        "all administration-window pairs within +/-60 minutes",
    )
    return figure_b2_df, figure_e4_df


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    figure_e5_df = pl.read_csv(SHARE_DIR / "fig_E5__induction_dose_tiers.csv")
    _tier_order = ["full", "intermediate_full", "intermediate_reduced", "reduced"]
    _labels = {
        "full": "Full",
        "intermediate_full": "Int-Full",
        "intermediate_reduced": "Int-Reduced",
        "reduced": "Reduced",
    }
    _colors = {
        "full": "#b84432",
        "intermediate_full": "#dc8435",
        "intermediate_reduced": "#efca3f",
        "reduced": "#57ad6b",
    }
    _drugs = ["etomidate", "ketamine"]
    _fig, _ax = plt.subplots(figsize=(8.8, 6.8))
    _bottom = [0.0, 0.0]
    for _tier in _tier_order:
        _values = []
        for _drug in _drugs:
            _row = figure_e5_df.filter(
                (pl.col("drug") == _drug) & (pl.col("dose_tier") == _tier)
            )
            _values.append(float(_row["pct"][0] or 0.0))
        _bars = _ax.bar(
            [0, 1], _values, bottom=_bottom, width=0.55,
            color=_colors[_tier], edgecolor="white", label=_labels[_tier],
        )
        for _i, (_bar, _value) in enumerate(zip(_bars, _values)):
            if _value >= 3:
                _ax.text(
                    _bar.get_x() + _bar.get_width() / 2,
                    _bottom[_i] + _value / 2,
                    f"{_value:.1f}%",
                    ha="center", va="center", color="white", fontweight="bold",
                )
        _bottom = [_bottom[i] + _values[i] for i in range(2)]
    for _i, _drug in enumerate(_drugs):
        _n = int(
            figure_e5_df.filter(pl.col("drug") == _drug).get_column("n_total").first()
        )
        _ax.text(_i, -3.0, f"n = {_n:,}", ha="center", color="#555555", fontsize=9)
    _ax.set_xticks([0, 1])
    _ax.set_xticklabels(["Etomidate", "Ketamine"])
    _ax.set_ylim(-5, 105)
    _ax.set_yticks([0, 25, 50, 75, 100])
    _ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    _ax.set_ylabel("Proportion of administration-window pairs (%)")
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)
    _ax.set_axisbelow(True)
    _handles, _legend_labels = _ax.get_legend_handles_labels()
    _ax.legend(
        _handles[::-1],
        _legend_labels[::-1],
        title="Dose tier",
        bbox_to_anchor=(1.02, 0.62),
        loc="center left",
        frameon=False,
    )
    _ax.set_title(
        "E.5 - Local Dose Tier Distribution by Drug\n"
        "Etomidate: reduced <0.20 | int-reduced 0.20-0.24 | int-full 0.25-0.29 | full >=0.30 mg/kg\n"
        "Ketamine: reduced <1.0 | int-reduced 1.0-1.49 | int-full 1.5-1.99 | full >=2.0 mg/kg",
        loc="left", fontsize=11,
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "fig_E5__induction_dose_tiers.png", dpi=150)
    plt.close(_fig)
    print(f"fig_E5__induction_dose_tiers.png -> {FIG_DIR}")
    return (figure_e5_df,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    figure_g1_df = pl.read_csv(SHARE_DIR / "fig_G1__dose_per_weight_consort.csv")
    _populations = ["paralytic", "sedation", "induction tiers"]
    _fig, _axes = plt.subplots(1, 3, figsize=(15, 6.5), squeeze=False)
    for _ax, _population in zip(_axes[0], _populations):
        _part = figure_g1_df.filter(pl.col("population") == _population).sort("stage_order")
        _y = list(range(_part.height))
        _counts = _part.get_column("n_remaining").to_list()
        _ax.barh(_y, _counts, color="#2a78d6", height=0.58)
        _ax.set_yticks(_y)
        _ax.set_yticklabels(_part.get_column("stage").to_list(), fontsize=8)
        _ax.invert_yaxis()
        _ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
        _ax.set_axisbelow(True)
        for _i, _row in enumerate(_part.iter_rows(named=True)):
            _label = f"{_row['n_remaining']:,}"
            if _row["n_excluded"]:
                _label += f"  (-{_row['n_excluded']:,})"
            _ax.text(_row["n_remaining"], _i, f"  {_label}", va="center", fontsize=8)
        _ax.set_title(_population, loc="left", fontweight="bold")
        _ax.set_xlabel(_part.get_column("count_unit").first(), fontsize=8)
        for _side in ("top", "right", "left"):
            _ax.spines[_side].set_visible(False)
    _fig.suptitle(
        "G.1 - Dose/weight eligibility flow\n"
        "Weight-related exclusions affect normalized-dose analyses only, not the analytic cohort",
        fontsize=12,
    )
    _fig.tight_layout()
    _fig.subplots_adjust(top=0.82, wspace=0.9)
    _fig.savefig(FIG_DIR / "fig_G1__dose_per_weight_consort.png", dpi=150)
    plt.close(_fig)
    print(f"fig_G1__dose_per_weight_consort.png -> {FIG_DIR}")
    return (figure_g1_df,)


if __name__ == "__main__":
    app.run()
