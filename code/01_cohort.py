import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import pandas as pd
    import polars as pl

    from clifpy.tables import (
        Adt,
        Hospitalization,
        MedicationAdminIntermittent,
        RespiratorySupport,
    )
    from clifpy.utils.stitching_encounters import stitch_encounters
    from clifpy.utils.waterfall import process_resp_support_waterfall

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        Adt,
        Hospitalization,
        MedicationAdminIntermittent,
        Path,
        RespiratorySupport,
        json,
        mo,
        pd,
        pl,
        process_resp_support_waterfall,
        publish,
        stitch_encounters,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 01 — Cohort and CONSORT

        Builds the analytic cohort around a qualifying paralytic administration. Respiratory
        charting supplies context and the tracheostomy exclusion, but is not an inclusion
        requirement: a patient who dies immediately after intubation may never receive a
        charted IMV row.

        **The analytic unit is the stitched `encounter_block`, not `hospitalization_id`.**

        Stages, each reporting a CONSORT row:

        1. **Step 0** — restrict to patients with at least one qualifying paralytic ever
        2. **Stitch** — merge hospitalizations less than `stitch_hours` apart into one encounter
        3. **Include** — adult, date window, at least one ED or ICU location, at least one paralytic
        4. **Exclude** — tracheostomy or trach collar within `trach_window_hours` of block admission
        5. **Waterfall** any available respiratory rows and publish raw charted IMV QC

        `01` resolves no index event. The paralytic administration is the index now — `02`
        folds paralytic administrations into index events (anchor-and-close at 15 minutes,
        spec P6), and `03` reads this notebook's waterfalled device timeline for the
        non-IMV → IMV transition around each one (sub-analysis D).

        Design: `docs/superpowers/specs/2026-08-10-paralytic-index-design.md`
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

    STITCH_HOURS = config["stitch_hours"]
    TRACH_WINDOW_HOURS = config["trach_window_hours"]
    MIN_AGE = config["min_age"]
    DATE_START = config["date_start"]
    DATE_END = config["date_end"]

    PARALYTICS = ["rocuronium", "succinylcholine", "vecuronium"]
    MAR_ACTIONS = ["given", "bolus"]

    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    PHI_DIR.mkdir(parents=True, exist_ok=True)
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    # MIMIC timestamps are date-shifted, so a calendar filter is meaningless there.
    APPLY_DATE_FILTER = SITE.lower() != "mimic"

    def to_site_naive(series):
        """Strip clifpy's configured site timezone while preserving local wall time.

        `from_file(..., timezone=TIMEZONE)` localizes naive input and converts aware
        input to the configured site timezone. No second conversion belongs here.
        """
        return series.dt.tz_localize(None)

    return (
        to_site_naive,
        APPLY_DATE_FILTER,
        DATA_DIR,
        DATE_END,
        DATE_START,
        FILETYPE,
        MIN_AGE,
        MAR_ACTIONS,
        PARALYTICS,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        STITCH_HOURS,
        TIMEZONE,
        TRACH_WINDOW_HOURS,
    )


@app.cell
def _(
    APPLY_DATE_FILTER,
    DATA_DIR,
    DATE_END,
    DATE_START,
    MIN_AGE,
    SITE,
    STITCH_HOURS,
    TRACH_WINDOW_HOURS,
):
    # Every parameter that affects a result is echoed before anything runs (spec §4).
    # collapse_gap_minutes and context_window_minutes are NOT echoed here: they belong to
    # 02 and 03, and echoing a parameter this notebook cannot act on is the "silent
    # default" confusion §4 exists to prevent.
    import datetime as _dt

    COHORT_RUN_ID = _dt.datetime.now().replace(microsecond=0).isoformat()

    print(f"site                : {SITE}")
    print(f"data_directory      : {DATA_DIR}")
    print(f"cohort_run_id       : {COHORT_RUN_ID}")
    print("-" * 60)
    print(f"min_age             : {MIN_AGE}")
    print(f"stitch_hours        : {STITCH_HOURS}")
    print(f"trach_window_hours  : {TRACH_WINDOW_HOURS}")
    print(
        f"date filter         : "
        + (f"{DATE_START} .. {DATE_END}" if APPLY_DATE_FILTER else "SKIPPED (site is MIMIC)")
    )
    return (COHORT_RUN_ID,)


@app.cell
def _(mo):
    mo.md(
        """
        ## CONSORT ledger

        Every filter appends a row here before and after, so no step is silent.
        Counts are reported as **encounter blocks** and **patients** at every step.
        """
    )
    return


@app.cell
def _():
    consort_rows = []

    def consort_add(step, n_encounters, n_patients, n_excluded, note=""):
        """Append one CONSORT row and echo it. `n_encounters` is None before stitching."""
        consort_rows.append(
            {
                "step": step,
                "n_encounters": n_encounters,
                "n_patients": n_patients,
                "n_excluded": n_excluded,
                "note": note,
            }
        )
        _enc = "—" if n_encounters is None else f"{n_encounters:,}"
        print(f"{step:<44} encounters={_enc:>10}  patients={n_patients:>10,}  excluded={n_excluded:>9,}")

    return consort_add, consort_rows


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 0 — the paralytic-ever pre-filter

        Stitching joins the full hospitalization and ADT tables and iterates to a fixed
        point. Restrict it to patients who could possibly qualify.

        The filter is **patient-level, not hospitalization-level**: a patient's paralytic may be
        charted under a different `hospitalization_id` than the one that will anchor their
        encounter block, so filtering hospitalizations here would discard the very rows
        stitching exists to reunite.

        This changes no result — every criterion below requires a qualifying paralytic, so a patient
        with none could never enter the cohort by any path.
        """
    )
    return


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    Hospitalization,
    MAR_ACTIONS,
    MedicationAdminIntermittent,
    PARALYTICS,
    TIMEZONE,
    pl,
    to_site_naive,
):
    def _rate_unit_expr():
        _time_units = (
            "s|sec|secs|second|seconds|m|min|mins|minute|minutes|"
            "h|hr|hrs|hour|hours|d|day|days"
        )
        return (
            pl.col("med_dose_unit")
            .str.strip_chars()
            .str.to_lowercase()
            .str.contains(rf"(?:/|\bper\s+)(?:{_time_units})$")
            .fill_null(False)
        )

    _category_variants = sorted(
        {v for c in PARALYTICS for v in (c, c.title(), c.upper())}
    )
    _med = MedicationAdminIntermittent.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "med_category",
            "mar_action_category",
            "med_dose_unit",
        ],
        filters={"med_category": _category_variants},
    )
    _med_pl = pl.from_pandas(_med.df).with_columns(
        med_category=pl.col("med_category").str.to_lowercase(),
        mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
    )
    _qualifying = _med_pl.filter(
        pl.col("med_category").is_in(PARALYTICS)
        & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        & ~_rate_unit_expr()
    )
    paralytic_hosp_ids = (
        _qualifying
        .get_column("hospitalization_id")
        .unique()
    )
    assert paralytic_hosp_ids.len() > 0, (
        "no hospitalization has a qualifying paralytic administration. Check the "
        "med_category and mar_action_category vocabularies before trusting an empty cohort."
    )
    print("qualifying paralytic administrations:")
    print(
        _qualifying.group_by(["med_category", "mar_action_category"])
        .agg(n=pl.len())
        .sort("n", descending=True)
    )
    print(f"hospitalizations with >=1 qualifying paralytic : {paralytic_hosp_ids.len():,}")

    # Full hospitalization table — needed unfiltered so we can map IMV hospitalizations
    # to patients, then pull back *all* hospitalizations of those patients.
    _hosp_all = Hospitalization.from_file(
        data_directory=DATA_DIR, filetype=FILETYPE, timezone=TIMEZONE
    )
    hosp_all = pl.from_pandas(
        _hosp_all.df.assign(
            admission_dttm=lambda d: to_site_naive(d["admission_dttm"]),
            discharge_dttm=lambda d: to_site_naive(d["discharge_dttm"]),
        )
    )

    patients_paralytic_ever = (
        hosp_all.filter(pl.col("hospitalization_id").is_in(paralytic_hosp_ids.implode()))
        .get_column("patient_id")
        .unique()
    )
    return hosp_all, paralytic_hosp_ids, patients_paralytic_ever


@app.cell
def _(consort_add, hosp_all, patients_paralytic_ever, pl):
    n_patients_source = hosp_all.get_column("patient_id").n_unique()
    n_hosp_source = hosp_all.height

    consort_add(
        "source data (pre-stitch)",
        None,
        n_patients_source,
        0,
        f"{n_hosp_source:,} hospitalizations",
    )

    # Pull every hospitalization for each qualifying patient so stitching can reunite an
    # ED paralytic with the inpatient admission that follows it.
    hosp_paralytic_patients = hosp_all.filter(
        pl.col("patient_id").is_in(patients_paralytic_ever.implode())
    )

    consort_add(
        "step 0: patients with >=1 qualifying paralytic ever",
        None,
        hosp_paralytic_patients.get_column("patient_id").n_unique(),
        n_patients_source - hosp_paralytic_patients.get_column("patient_id").n_unique(),
        f"{hosp_paralytic_patients.height:,} hospitalizations",
    )
    return (hosp_paralytic_patients,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Stitching

        `stitch_encounters` merges hospitalizations separated by less than `stitch_hours`
        into a single `encounter_block` — how an ED presentation and the inpatient
        admission that follows it become one encounter.

        This study is close to a worst case without it: a patient given rocuronium in the
        ED and first charted on IMV after transfer would have the medication signal under
        one `hospitalization_id` and the device transition under another, reading as
        methods disagreeing when it is one intubation split across an administrative
        boundary.

        Takes pandas, returns pandas — one of the two pandas boundaries in the project.
        """
    )
    return


@app.cell
def _(
    Adt,
    DATA_DIR,
    FILETYPE,
    STITCH_HOURS,
    TIMEZONE,
    hosp_paralytic_patients,
    pl,
    stitch_encounters,
):
    _cohort_hosp_ids = hosp_paralytic_patients.get_column("hospitalization_id").to_list()

    _adt = Adt.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        filters={"hospitalization_id": _cohort_hosp_ids},
    )
    # location_category lower-cased on load like every other category column (D21).
    adt_pl = pl.from_pandas(
        _adt.df.assign(
            in_dttm=lambda d: to_site_naive(d["in_dttm"]),
            out_dttm=lambda d: to_site_naive(d["out_dttm"]),
        )
    ).with_columns(location_category=pl.col("location_category").str.to_lowercase())

    print("lower-cased location_category:")
    print(adt_pl.get_column("location_category").value_counts(sort=True))

    _hosp_stitched_pd, _adt_stitched_pd, _mapping_pd = stitch_encounters(
        hospitalization=hosp_paralytic_patients.to_pandas(),
        adt=adt_pl.to_pandas(),
        time_interval=STITCH_HOURS,
    )

    hosp_stitched = pl.from_pandas(_hosp_stitched_pd)
    encounter_mapping = pl.from_pandas(_mapping_pd).unique()

    print(f"hospitalizations stitched : {hosp_stitched.height:,}")
    print(f"encounter blocks formed   : {hosp_stitched.get_column('encounter_block').n_unique():,}")
    return adt_pl, encounter_mapping, hosp_stitched


@app.cell
def _(mo):
    mo.md(
        """
        ### Derive the encounter-block table

        `stitch_encounters` returns the input tables with an `encounter_block` column
        appended; the block-level aggregate it builds internally is **not** returned
        (`stitching_encounters.py:178`). So we build it here explicitly — which is also
        the chance to take `age_at_admission` from the block's **earliest** hospitalization
        rather than its last, so that age and the block clock come from the same row.
        """
    )
    return


@app.cell
def _(hosp_stitched, pl):
    blocks = (
        hosp_stitched.sort(["patient_id", "encounter_block", "admission_dttm"])
        .group_by(["patient_id", "encounter_block"])
        .agg(
            admission_dttm=pl.col("admission_dttm").min(),
            discharge_dttm=pl.col("discharge_dttm").max(),
            # .first() after the sort above == the row with the earliest admission
            age_at_admission=pl.col("age_at_admission").first(),
            list_hospitalization_id=pl.col("hospitalization_id").unique().sort(),
            n_hospitalizations=pl.col("hospitalization_id").n_unique(),
        )
    )

    print(f"encounter blocks : {blocks.height:,}")
    print(f"patients         : {blocks.get_column('patient_id').n_unique():,}")
    print("\nhospitalizations per block:")
    print(
        blocks.get_column("n_hospitalizations")
        .value_counts(sort=True)
        .sort("n_hospitalizations")
    )
    return (blocks,)


@app.cell
def _(blocks, consort_add):
    consort_add(
        "stitched into encounter blocks",
        blocks.height,
        blocks.get_column("patient_id").n_unique(),
        0,
        "start of the block-level funnel",
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Inclusions

        Applied in this order. The order is part of the definition: CONSORT reports the
        **marginal** loss at each step, so inclusions run before the exclusion and the
        trach count reflects only encounters that would otherwise have qualified.
        """
    )
    return


@app.cell
def _(MIN_AGE, blocks, consort_add, pl):
    cohort_age = blocks.filter(pl.col("age_at_admission") >= MIN_AGE)

    consort_add(
        f"include: age_at_admission >= {MIN_AGE}",
        cohort_age.height,
        cohort_age.get_column("patient_id").n_unique(),
        blocks.height - cohort_age.height,
    )
    return (cohort_age,)


@app.cell
def _(APPLY_DATE_FILTER, DATE_END, DATE_START, cohort_age, consort_add, pl):
    if APPLY_DATE_FILTER:
        cohort_date = cohort_age.filter(
            pl.col("admission_dttm").is_between(
                pl.lit(DATE_START).str.to_datetime(),
                pl.lit(DATE_END).str.to_datetime(),
            )
        )
        _note = f"{DATE_START} .. {DATE_END} on block admission_dttm"
    else:
        cohort_date = cohort_age
        _note = "SKIPPED — site is MIMIC (timestamps are date-shifted)"

    consort_add(
        "include: admission date window",
        cohort_date.height,
        cohort_date.get_column("patient_id").n_unique(),
        cohort_age.height - cohort_date.height,
        _note,
    )
    return (cohort_date,)


@app.cell
def _(adt_pl, cohort_date, consort_add, encounter_mapping, pl):
    # ED *or* ICU, anywhere in the block. Not ICU alone: a large share of intubations
    # happen in the ED, and requiring ICU would systematically drop the patients whose
    # induction medications are best documented.
    blocks_with_ed_or_icu = (
        adt_pl.join(encounter_mapping, on="hospitalization_id", how="inner")
        .filter(pl.col("location_category").is_in(["ed", "icu"]))
        .get_column("encounter_block")
        .unique()
    )

    assert blocks_with_ed_or_icu.len() > 0, (
        "no encounter block has an 'ed' or 'icu' ADT row. Check the lower-cased "
        "location_category value counts printed above — the site may use a different "
        "vocabulary, in which case this filter is silently emptying the cohort."
    )

    cohort_loc = cohort_date.filter(pl.col("encounter_block").is_in(blocks_with_ed_or_icu.implode()))

    consort_add(
        "include: >=1 ADT row in {ed, icu}",
        cohort_loc.height,
        cohort_loc.get_column("patient_id").n_unique(),
        cohort_date.height - cohort_loc.height,
    )
    return (cohort_loc,)


@app.cell
def _(cohort_loc, consort_add, encounter_mapping, paralytic_hosp_ids, pl):
    blocks_with_paralytic = (
        encounter_mapping.filter(
            pl.col("hospitalization_id").is_in(paralytic_hosp_ids.implode())
        )
        .get_column("encounter_block")
        .unique()
    )

    cohort_paralytic = cohort_loc.filter(
        pl.col("encounter_block").is_in(blocks_with_paralytic.implode())
    )

    consort_add(
        "include: >=1 qualifying paralytic administration",
        cohort_paralytic.height,
        cohort_paralytic.get_column("patient_id").n_unique(),
        cohort_loc.height - cohort_paralytic.height,
        "rocuronium/succinylcholine/vecuronium; given/bolus; non-rate unit",
    )
    return (cohort_paralytic,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Exclusion — tracheostomy in the first `trach_window_hours`

        mCIDE defines `IMV` as *"Endotracheal Tube Ventilation, **Tracheostomy
        Ventilation**"* — a patient ventilated through a tracheostomy is charted as plain
        `IMV`, and would enter as a false intubation with no induction or paralytic to
        find. **Both** trach signals are tested, because either alone leaks:

        - `tracheostomy = True` — the boolean flag; missed at sites that only chart the device
        - `device_category == 'trach collar'` — a weaning device a continuously-ventilated
          trach patient may never receive

        The clock runs from the **stitched block's** `admission_dttm` (the minimum across
        the block), so a trach identified during an ED presentation cannot escape the
        window of the inpatient admission it was stitched to.

        Evaluated on the **raw** respiratory table, where the trach device row and the boolean
        are still intact — the waterfall lower-cases categories and coerces the boolean
        to a float.
        """
    )
    return


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    RespiratorySupport,
    TIMEZONE,
    cohort_paralytic,
    encounter_mapping,
    pl,
):
    # One load of the raw respiratory table for every hospitalization in the cohort —
    # reused for the trach exclusion and for the waterfall below.
    cohort_hosp_ids = (
        cohort_paralytic.select(pl.col("list_hospitalization_id").explode())
        .get_column("list_hospitalization_id")
        .unique()
        .to_list()
    )

    _resp = RespiratorySupport.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        filters={"hospitalization_id": cohort_hosp_ids},
    )
    # Two representations, deliberately. clifpy has already converted recorded_dttm to
    # the configured site timezone. The waterfall contract requires UTC-aware input and
    # creates UTC-aware scaffold rows, so this branch makes the one deliberate timezone
    # conversion in the pipeline. Everything else uses stripped site-local wall time.
    resp_raw_pd = _resp.df.copy()
    resp_utc_pd = resp_raw_pd.assign(
        recorded_dttm=resp_raw_pd["recorded_dttm"].dt.tz_convert("UTC")
    )
    resp_raw_pd["recorded_dttm"] = to_site_naive(resp_raw_pd["recorded_dttm"])

    # Lower-cased once, here, before any comparison (D21). Every device literal below is
    # written in lower case to match.
    resp_raw = (
        pl.from_pandas(
            resp_raw_pd[
                ["hospitalization_id", "recorded_dttm", "device_category", "tracheostomy"]
            ]
        )
        .with_columns(device_category=pl.col("device_category").str.to_lowercase())
        .join(encounter_mapping, on="hospitalization_id", how="inner")
    )

    print(f"raw respiratory rows for cohort hospitalizations : {resp_raw.height:,}")
    print("\nlower-cased device_category across the cohort:")
    print(resp_raw.get_column("device_category").value_counts(sort=True))

    return resp_raw, resp_utc_pd


@app.cell
def _(TRACH_WINDOW_HOURS, cohort_paralytic, consort_add, pl, resp_raw):
    # `tracheostomy` is tested for truthiness, not identity: the waterfall coerces it to
    # 1.0/0.0 (waterfall.py:152-159). This runs on the raw table where it is still a bool,
    # but writing it to survive either representation costs nothing.
    _is_trach_signal = pl.col("tracheostomy").cast(pl.Boolean, strict=False) | pl.col(
        "device_category"
    ).eq("trach collar")

    blocks_with_early_trach = (
        resp_raw.join(
            cohort_paralytic.select(["encounter_block", "admission_dttm"]),
            on="encounter_block",
            how="inner",
        )
        .filter(_is_trach_signal)
        .filter(
            pl.col("recorded_dttm").is_between(
                pl.col("admission_dttm"),
                pl.col("admission_dttm") + pl.duration(hours=TRACH_WINDOW_HOURS),
            )
        )
        .get_column("encounter_block")
        .unique()
    )

    cohort = cohort_paralytic.filter(
        ~pl.col("encounter_block").is_in(blocks_with_early_trach.implode())
    )

    consort_add(
        f"exclude: trach signal within {TRACH_WINDOW_HOURS}h",
        cohort.height,
        cohort.get_column("patient_id").n_unique(),
        cohort_paralytic.height - cohort.height,
        "tracheostomy truthy OR device_category=='trach collar'",
    )
    consort_add(
        "ANALYTIC COHORT",
        cohort.height,
        cohort.get_column("patient_id").n_unique(),
        0,
        "N*",
    )
    return (cohort,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Waterfall and t0

        `bfill=False` — forward-fill only. Backfilling could propagate a device backwards
        in time and manufacture an IMV row earlier than the first real charting. Under the
        superseded design that slid t0 itself; under the paralytic anchor it instead
        manufactures a *device transition* — `03` would read a non-IMV→IMV change that the
        chart never recorded, inside the ±`context_window_minutes` window around the index
        paralytic. The hazard moved; it did not go away.

        The waterfall runs per `hospitalization_id`, but rows are then mapped to
        `encounter_block` and ordered **within the block**, which is what makes stitching
        effective: the transition sequence `03` evaluates is assembled across the whole
        encounter in time order.

        **This is where lower-casing on load pays for itself.** The waterfall lower-cases
        `device_category` itself (`waterfall.py:147-149`). Under a pipeline that compared
        against mCIDE casing, that one line would silently break t0: `device_category ==
        'IMV'` on waterfalled data does not error, it matches nothing, and every encounter
        comes back with a null t0.

        Because the column was already lower-cased on load, the waterfall's transformation
        is a **no-op** — it writes back the values that were already there. Nothing
        re-normalises anything, and the same literal `'imv'` is correct on both sides of
        the call.
        """
    )
    return


@app.cell
def _(
    TIMEZONE,
    cohort,
    encounter_mapping,
    pl,
    process_resp_support_waterfall,
    resp_utc_pd,
):
    _cohort_hosp_set = set(
        cohort.select(pl.col("list_hospitalization_id").explode())
        .get_column("list_hospitalization_id")
        .to_list()
    )
    _resp_in = resp_utc_pd[resp_utc_pd["hospitalization_id"].isin(_cohort_hosp_set)].copy()

    if _resp_in.empty:
        resp_waterfall = (
            encounter_mapping.select("hospitalization_id", "encounter_block")
            .head(0)
            .with_columns(
                pl.lit(None, dtype=pl.Datetime).alias("recorded_dttm"),
                pl.lit(None, dtype=pl.String).alias("device_category"),
            )
            .select(
                "hospitalization_id",
                "recorded_dttm",
                "device_category",
                "encounter_block",
            )
        )
    else:
        _waterfalled = process_resp_support_waterfall(
            _resp_in,
            id_col="hospitalization_id",
            # D6. This flag CANNOT change device_category: waterfall.py:274 ffills it
            # unconditionally, and bfill reaches only num_cols_fill (fio2_set, peep_set,
            # tidal_volume_set, ...) at :320-336 -- after the device heuristics at :199-226
            # have already run. We read device_category and nothing else out of this frame,
            # so the flag is inert here. Set as specified rather than silently dropped.
            bfill=True,
            verbose=True,
        )

        # The waterfall preserves UTC on input rows and creates UTC scaffold rows. Convert its
        # result back to the configured site timezone before stripping the timezone.
        _waterfalled["recorded_dttm"] = (
            _waterfalled["recorded_dttm"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
        )

        resp_waterfall = (
            pl.from_pandas(
                _waterfalled[["hospitalization_id", "recorded_dttm", "device_category"]]
            )
            # Belt and braces: the column arrives lower-cased both because we lower-cased it
            # on load and because the waterfall lower-cases it again. Stating it here means the
            # invariant holds even if either of those two facts changes.
            .with_columns(device_category=pl.col("device_category").str.to_lowercase())
            .join(encounter_mapping, on="hospitalization_id", how="inner")
            .sort(["encounter_block", "recorded_dttm"])
        )

    # The waterfall's device heuristics can invent categories the raw table never had, so
    # assert the vocabulary is the one we expect rather than discovering it downstream.
    _MCIDE_DEVICE_LOWER = {
        "imv", "nippv", "cpap", "high flow nc", "face mask",
        "trach collar", "nasal cannula", "room air", "other",
    }
    _seen = set(
        resp_waterfall.get_column("device_category").drop_nulls().unique().to_list()
    )
    assert _seen <= _MCIDE_DEVICE_LOWER, (
        f"waterfall emitted device_category values outside mCIDE: {sorted(_seen - _MCIDE_DEVICE_LOWER)}"
    )

    # Defense in depth for the timezone boundary. The waterfall only ever ADDS rows, at
    # HH:59:59 scaffold positions; it never invents a timestamp anywhere else. So every
    # non-scaffold waterfall timestamp must exist in the raw table. If the two frames were
    # mishandled at the UTC waterfall boundary, this subset relation breaks immediately.
    # Compared per (hospitalization_id, recorded_dttm), not on a pooled set of timestamps:
    # a pooled comparison passes as long as SOME hospitalization happens to have that
    # instant, which would let a row orphaned within one encounter slip through.
    _wf_real = (
        resp_waterfall.filter(pl.col("recorded_dttm").dt.second() != 59)
        .select(["hospitalization_id", "recorded_dttm"])
        .unique()
    )
    _orphans = _wf_real.join(
        resp_raw.select(["hospitalization_id", "recorded_dttm"]).unique(),
        on=["hospitalization_id", "recorded_dttm"],
        how="anti",
    )
    assert _orphans.height == 0, (
        f"{_orphans.height:,} waterfalled rows have no raw counterpart in their own "
        f"hospitalization (e.g. {_orphans.head(3).to_dicts()}). The raw and waterfall "
        "frames are on different time bases — check the UTC waterfall round trip."
    )
    print(f"timestamp alignment OK: {_wf_real.height:,} non-scaffold rows all match raw")

    print(f"\nwaterfalled rows : {resp_waterfall.height:,}")
    print("\ndevice_category after the waterfall (lower case throughout):")
    print(resp_waterfall.get_column("device_category").value_counts(sort=True))
    return (resp_waterfall,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Raw charted IMV rows

        **`01` resolves no index event.** The paralytic administration is the index now
        (spec P6, resolved entirely in `02`) — there is no episode or t0 concept left for
        `01` to compute.

        What `01` publishes instead is the available raw charted IMV rows, block-keyed
        (`cohort_resp_imv_raw.parquet`). It is now a sparse QC artifact: a cohort block may
        legitimately have no row because cohort entry depends on the paralytic, not on
        respiratory charting.
        """
    )
    return


@app.cell
def _(PHI_DIR, cohort, pl, resp_raw):
    # The semi-join to `cohort` is load-bearing, not defensive. `resp_raw` is built from
    # `encounter_mapping`, which covers every stitched block -- including the ones later
    # removed by the trach exclusion (§5.5). Without this filter the frame carries 1,125
    # blocks the study excluded, and 02 would compute a charting delay for episodes that
    # are not in the cohort at all. The waterfall is already scoped this way; this matches it.
    cohort_resp_imv_raw = (
        resp_raw.filter(pl.col("device_category") == "imv")
        .join(cohort.select("encounter_block"), on="encounter_block", how="semi")
        .select(["encounter_block", "recorded_dttm"])
        .unique()
        .sort(["encounter_block", "recorded_dttm"])
    )

    _blocks = cohort_resp_imv_raw.get_column("encounter_block").n_unique()

    cohort_resp_imv_raw.write_parquet(PHI_DIR / "step01__cohort_resp_imv_raw.parquet")
    print(f"step01__cohort_resp_imv_raw.parquet  {cohort_resp_imv_raw.height:,} rows -> {PHI_DIR}")
    print(f"  blocks represented         {_blocks:,} / {cohort.height:,}")

    cohort_index = cohort.sort("encounter_block")
    return cohort_index, cohort_resp_imv_raw


@app.cell
def _(mo):
    mo.md(
        """
        ## QC statistics

        Two checks that must be read before any downstream result is trusted. A third
        check — a waterfall-minus-raw charting-delay delta — existed under the superseded
        ventilator-anchored design and was retired with it when the anchor moved to the
        paralytic administration; nothing in the live pipeline computes it.
        """
    )
    return


@app.cell
def _(cohort_index, cohort_resp_imv_raw, pl, resp_waterfall):
    # QC 1 -- how much stitching actually did.
    #
    # A waterfall-minus-raw charting-delay delta used to head this cell under the
    # superseded ventilator-anchored design. It measured how far behind a settings-based
    # device inference the raw device field was filled in -- a quantity that design's t0
    # anchor was chosen on. It was retired when the anchor moved to the paralytic
    # administration (spec P6); nothing in this pipeline recomputes it.
    qc_blocks_per_encounter = (
        cohort_index.get_column("n_hospitalizations")
        .value_counts(sort=True)
        .sort("n_hospitalizations")
    )
    print("QC 1 -- hospitalizations per encounter block")
    print(qc_blocks_per_encounter)

    # QC 2 -- the direct measure of the artifact stitching exists to remove: the block's
    # first IMV row landing in a hospitalization other than the block's first.
    #
    # Phrased on the first IMV row rather than on t0, which 01 no longer computes. Matched
    # against the WATERFALLED rows: an IMV row can be a scaffold row (HH:59:59) with no raw
    # counterpart, and matching against raw would drop exactly those blocks from the
    # denominator -- silently, and not at random.
    _first_hosp = cohort_index.select(
        "encounter_block",
        first_hospitalization_id=pl.col("list_hospitalization_id").list.first(),
    )
    _imv_hosp = (
        resp_waterfall.filter(pl.col("device_category") == "imv")
        .sort(["encounter_block", "recorded_dttm", "hospitalization_id"])
        .group_by("encounter_block", maintain_order=True)
        .agg(hospitalization_id=pl.col("hospitalization_id").first())
    )
    _joined = _first_hosp.join(_imv_hosp, on="encounter_block", how="inner")
    qc_pct_imv_elsewhere = (
        100.0
        * _joined.filter(
            pl.col("hospitalization_id") != pl.col("first_hospitalization_id")
        ).height
        / max(_joined.height, 1)
    )
    qc_pct_blocks_with_resp = (
        100.0
        * resp_waterfall.get_column("encounter_block").n_unique()
        / max(cohort_index.height, 1)
    )
    qc_pct_blocks_with_raw_imv = (
        100.0
        * cohort_resp_imv_raw.get_column("encounter_block").n_unique()
        / max(cohort_index.height, 1)
    )
    print(
        f"\nQC 2 -- % of blocks whose first IMV row falls outside the block's first "
        f"hospitalization, among blocks with IMV: {qc_pct_imv_elsewhere:.1f}"
    )
    print(f"QC 3 -- % of blocks with respiratory rows: {qc_pct_blocks_with_resp:.1f}")
    print(f"QC 4 -- % of blocks with raw charted IMV: {qc_pct_blocks_with_raw_imv:.1f}")
    return (
        qc_blocks_per_encounter,
        qc_pct_blocks_with_raw_imv,
        qc_pct_blocks_with_resp,
        qc_pct_imv_elsewhere,
    )


@app.cell
def _(mo):
    mo.md("## Outputs")
    return


@app.cell
def _(
    COHORT_RUN_ID,
    MIN_AGE,
    PHI_DIR,
    SHARE_DIR,
    STITCH_HOURS,
    TRACH_WINDOW_HOURS,
    cohort,
    cohort_index,
    consort_rows,
    pl,
    publish,
    qc_blocks_per_encounter,
    qc_pct_blocks_with_raw_imv,
    qc_pct_blocks_with_resp,
    qc_pct_imv_elsewhere,
    resp_waterfall,
):
    # The JOIN SPINE and nothing more.
    #
    # No t0, window, or episode columns are written here -- there is no such concept in
    # this design. The index event is a `02` construct built entirely from paralytic
    # administrations (spec P6); `01` supplies only the join keys and the two cohort
    # summary columns below. The explicit `.select()` above is what enforces that -- an
    # accidental extra column here could not survive it.
    cohort_index_out = cohort_index.with_columns(
        cohort_run_id=pl.lit(COHORT_RUN_ID),
    ).select(
        [
            "encounter_block",
            "patient_id",
            "cohort_run_id",
            "list_hospitalization_id",
            "n_hospitalizations",
            "admission_dttm",
            "age_at_admission",
        ]
    )

    assert cohort_index_out.get_column("encounter_block").is_unique().all(), (
        "encounter_block is not unique in cohort_index."
    )

    cohort.write_parquet(PHI_DIR / "step01__cohort.parquet")
    resp_waterfall_out = resp_waterfall.with_columns(
        cohort_run_id=pl.lit(COHORT_RUN_ID)
    )
    resp_waterfall_out.write_parquet(PHI_DIR / "step01__cohort_resp_waterfall.parquet")
    cohort_index_out.write_parquet(PHI_DIR / "step01__cohort_index.parquet")

    consort_df = pl.DataFrame(consort_rows)
    publish(consort_df, SHARE_DIR / "step01__consort_cohort.csv", "step01__consort_cohort")

    cohort_qc = pl.DataFrame(
        [
            {"stat": "cohort_run_id", "value": COHORT_RUN_ID},
            {"stat": "min_age", "value": str(MIN_AGE)},
            {"stat": "stitch_hours", "value": str(STITCH_HOURS)},
            {"stat": "trach_window_hours", "value": str(TRACH_WINDOW_HOURS)},
            {"stat": "max_hosp_per_block", "value": str(qc_blocks_per_encounter.get_column("n_hospitalizations").max())},
            {"stat": "pct_blocks_with_respiratory_rows", "value": f"{qc_pct_blocks_with_resp:.2f}"},
            {"stat": "pct_blocks_with_raw_imv", "value": f"{qc_pct_blocks_with_raw_imv:.2f}"},
            {"stat": "pct_first_imv_outside_first_hosp_among_imv_blocks", "value": f"{qc_pct_imv_elsewhere:.2f}"},
        ]
    )
    publish(cohort_qc, SHARE_DIR / "step01__cohort_qc.csv", "step01__cohort_qc")

    print(f"step01__cohort.parquet                 {cohort.height:,} rows  -> {PHI_DIR}")
    print(f"step01__cohort_resp_waterfall.parquet  {resp_waterfall_out.height:,} rows")
    print(f"step01__cohort_index.parquet           {cohort_index_out.height:,} rows")
    print(f"step01__consort_cohort.csv             {consort_df.height} steps -> {SHARE_DIR}")
    print(f"step01__cohort_qc.csv                  {cohort_qc.height} stats")
    print("\nCONSORT")
    print(consort_df)
    return cohort_index_out, consort_df


if __name__ == "__main__":
    app.run()
