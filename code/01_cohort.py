import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import hashlib
    import inspect
    import json
    import sys
    import uuid
    from importlib.metadata import version
    from pathlib import Path

    import pandas as pd
    import polars as pl

    from clifpy.tables import (
        Adt,
        Hospitalization,
        RespiratorySupport,
    )
    from clifpy.utils.io import fetch_lazy_result, load_data
    from clifpy.utils.stitching_encounters import stitch_encounters
    from clifpy.utils.waterfall import process_resp_support_waterfall

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        Adt,
        Hospitalization,
        Path,
        RespiratorySupport,
        fetch_lazy_result,
        hashlib,
        inspect,
        json,
        load_data,
        mo,
        pd,
        pl,
        process_resp_support_waterfall,
        publish,
        stitch_encounters,
        uuid,
        version,
    )


@app.cell
def _(pl):
    def canonical_category_sql(column):
        """DuckDB expression equivalent to strip + lowercase for pushdown."""
        if not column.isidentifier():
            raise ValueError(f"unsafe SQL identifier: {column!r}")
        whitespace_codepoints = (
            *range(9, 14),
            32,
            133,
            160,
            5760,
            *range(8192, 8203),
            8232,
            8233,
            8239,
            8287,
            12288,
        )
        whitespace_sql = " || ".join(
            f"chr({codepoint})" for codepoint in whitespace_codepoints
        )
        return f"lower(trim({column}, {whitespace_sql}))"

    def normalize_category_columns(df, *columns):
        """Canonicalize source categories once before matching or grouping."""
        return df.with_columns(
            [
                pl.col(column)
                .cast(pl.String)
                .str.strip_chars()
                .str.to_lowercase()
                .alias(column)
                for column in columns
            ]
        )

    def normalize_respiratory_categories(df):
        """Accept CLIF 2.1 labels and CLIF 3.0 tokens without changing outputs."""
        aliases = {
            "device_category": {
                "hfnc": "high flow nc",
                "high_flow_nc": "high flow nc",
                "face_mask": "face mask",
                "trach_collar": "trach collar",
                "t_piece": "t piece",
                "nasal_cannula": "nasal cannula",
                "room_air": "room air",
            },
            "mode_category": {
                "acvc": "assist control-volume control",
                "assist_control_volume_control": "assist control-volume control",
                "pressure_control": "pressure control",
                "prvc": "pressure-regulated volume control",
                "pressure_regulated_volume_control": "pressure-regulated volume control",
                "ps_or_cpap": "pressure support/cpap",
                "pressure_support_cpap": "pressure support/cpap",
                "volume_support": "volume support",
                "t_piece": "t piece",
                "blow_by": "blow by",
            },
        }
        columns = [column for column in aliases if column in df.columns]
        if not columns:
            return df
        normalized = normalize_category_columns(df, *columns)
        return normalized.with_columns(
            [pl.col(column).replace(aliases[column]).alias(column) for column in columns]
        )

    return (
        canonical_category_sql,
        normalize_category_columns,
        normalize_respiratory_categories,
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
    MAR_ACTIONS = ["given"]
    MEDICATION_DOSE_UNITS = config["medication_dose_units"]
    MEDICATION_DOSE_UPPER_BOUNDS = config["medication_dose_upper_bounds"]
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
    assert set(MEDICATION_DOSE_UPPER_BOUNDS) == _expected_meds, (
        "medication_dose_upper_bounds must configure exactly the eight study medications"
    )
    assert all(
        isinstance(bound, (int, float))
        and not isinstance(bound, bool)
        and 0 < bound < float("inf")
        for bound in MEDICATION_DOSE_UPPER_BOUNDS.values()
    ), "medication_dose_upper_bounds values must be finite positive numbers"

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
        MEDICATION_DOSE_UPPER_BOUNDS,
        MEDICATION_DOSE_UNITS,
        PARALYTICS,
        PHI_DIR,
        SHARE_DIR,
        SITE,
        STITCH_HOURS,
        TIMEZONE,
        TRACH_WINDOW_HOURS,
    )


@app.cell
def _(pl):
    def medication_dose_eligible_expr(configured_units, upper_bounds):
        """Match the configured unit and retain only clinically eligible doses."""
        _configured_unit = pl.col("med_category").replace_strict(configured_units)
        _upper_bound = pl.col("med_category").replace_strict(upper_bounds)
        return (
            (pl.col("med_dose_unit") == _configured_unit)
            & pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & (pl.col("med_dose") > 0)
            & (
                _configured_unit.str.ends_with("/kg")
                | (pl.col("med_dose") < _upper_bound)
            )
        )

    return (medication_dose_eligible_expr,)


@app.cell
def _(hashlib, json, pd, uuid):
    def waterfall_input_digests(frame):
        """Content digest per hospitalization for precise cache invalidation."""
        digests = {}
        for hospitalization_id, group in frame.groupby(
            "hospitalization_id", sort=False, dropna=False
        ):
            group = group.reset_index(drop=True)
            digest = hashlib.sha256()
            digest.update(
                json.dumps(
                    [(str(column), str(dtype)) for column, dtype in group.dtypes.items()],
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(
                pd.util.hash_pandas_object(
                    group, index=False, categorize=True
                ).values.tobytes()
            )
            digests[str(hospitalization_id)] = digest.hexdigest()
        return digests

    def file_sha256(path):
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def valid_waterfall_cache_entries(source_digests, entries, valid_shards):
        """Select current, intact cache entries for the required hospitalizations."""
        return {
            hospitalization_id: entry
            for hospitalization_id, digest in source_digests.items()
            if (entry := entries.get(hospitalization_id)) is not None
            and entry.get("digest") == digest
            and entry.get("shard") in valid_shards
        }

    def write_parquet_atomic(frame, path):
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        frame.write_parquet(temporary)
        temporary.replace(path)

    def write_json_atomic(payload, path):
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w") as file:
            json.dump(payload, file, indent=2, sort_keys=True)
            file.write("\n")
        temporary.replace(path)

    return (
        file_sha256,
        valid_waterfall_cache_entries,
        waterfall_input_digests,
        write_json_atomic,
        write_parquet_atomic,
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
    # Collapse, IMV, and sedation window settings are NOT echoed
    # here: they belong to 02 and 03, and echoing a parameter this notebook cannot act on is the "silent
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
    MEDICATION_DOSE_UPPER_BOUNDS,
    MEDICATION_DOSE_UNITS,
    PARALYTICS,
    TIMEZONE,
    canonical_category_sql,
    fetch_lazy_result,
    load_data,
    medication_dose_eligible_expr,
    normalize_category_columns,
    pl,
    to_site_naive,
):
    # This is the only category pushdown before cohort IDs exist. clifpy's regular
    # filter is exact, so use its lazy DuckDB relation to make the pushdown genuinely
    # case-insensitive and whitespace-insensitive without loading the whole MAR table.
    _category_sql = ", ".join(f"'{category}'" for category in PARALYTICS)
    _med_rel = load_data(
        "medication_admin_intermittent",
        DATA_DIR,
        FILETYPE,
        columns=[
            "hospitalization_id",
            "med_category",
            "mar_action_category",
            "med_dose",
            "med_dose_unit",
        ],
        lazy=True,
    )
    _category_expr = canonical_category_sql("med_category")
    _med_pd = fetch_lazy_result(
        _med_rel.filter(f"{_category_expr} IN ({_category_sql})"),
        site_tz=TIMEZONE,
    )
    _med_pl = normalize_category_columns(
        pl.from_pandas(_med_pd), "med_category", "mar_action_category"
    ).with_columns(
        med_dose_unit=pl.col("med_dose_unit").str.strip_chars().str.to_lowercase(),
    )
    _qualifying = _med_pl.filter(
        pl.col("med_category").is_in(PARALYTICS)
        & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        & medication_dose_eligible_expr(
            MEDICATION_DOSE_UNITS, MEDICATION_DOSE_UPPER_BOUNDS
        )
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
    normalize_category_columns,
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
    adt_pl = normalize_category_columns(
        pl.from_pandas(
            _adt.df.assign(
                in_dttm=lambda d: to_site_naive(d["in_dttm"]),
                out_dttm=lambda d: to_site_naive(d["out_dttm"]),
            )
        ),
        "location_category",
    )

    print("canonical location_category:")
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
        "rocuronium/succinylcholine/vecuronium; given; configured dose unit",
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
    normalize_category_columns,
    normalize_respiratory_categories,
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
    _resp_category_columns = [
        column for column in resp_raw_pd.columns if column.endswith("_category")
    ]
    resp_raw_pd = normalize_respiratory_categories(
        normalize_category_columns(pl.from_pandas(resp_raw_pd), *_resp_category_columns)
    ).to_pandas()
    resp_utc_pd = resp_raw_pd.assign(
        recorded_dttm=resp_raw_pd["recorded_dttm"].dt.tz_convert("UTC")
    )
    resp_raw_pd["recorded_dttm"] = to_site_naive(resp_raw_pd["recorded_dttm"])

    resp_raw = (
        normalize_category_columns(
            pl.from_pandas(
                resp_raw_pd[
                    ["hospitalization_id", "recorded_dttm", "device_category", "tracheostomy"]
                ]
            ),
            "device_category",
        )
        .join(encounter_mapping, on="hospitalization_id", how="inner")
    )

    print(f"raw respiratory rows for cohort hospitalizations : {resp_raw.height:,}")
    print("\ncanonical device_category across the cohort:")
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

        `bfill=True` follows the study specification. In CLIFpy, device inference and
        unconditional device-category forward filling finish before this flag reaches only
        numeric ventilator settings. This pipeline retains no numeric waterfall columns, so
        the flag cannot alter the persisted `device_category` timeline.

        The waterfall runs per `hospitalization_id`, but rows are then mapped to
        `encounter_block` and ordered **within the block**, which is what makes stitching
        effective: the transition sequence `03` evaluates is assembled across the whole
        encounter in time order.

        **This is where category normalization on load pays for itself.** CLIF 2.1 labels
        such as `Room Air` and CLIF 3.0 tokens such as `room_air` are converted to the same
        existing lower-case analytic label before the waterfall. This also supplies the
        CLIF 2.1 spellings that `clifpy 0.5.0` still uses in its device and mode heuristics.

        The waterfall lower-cases `device_category` itself (`waterfall.py:147-149`), so the
        normalized input remains unchanged and the same literal `'imv'` is correct on both
        sides of the call.
        """
    )
    return


@app.cell
def _(
    COHORT_RUN_ID,
    PHI_DIR,
    TIMEZONE,
    cohort,
    encounter_mapping,
    file_sha256,
    inspect,
    json,
    normalize_category_columns,
    normalize_respiratory_categories,
    pl,
    process_resp_support_waterfall,
    resp_raw,
    resp_utc_pd,
    version,
    valid_waterfall_cache_entries,
    waterfall_input_digests,
    write_json_atomic,
    write_parquet_atomic,
):
    _cache_dir = PHI_DIR / "resp_waterfall_cache"
    _cache_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path = _cache_dir / "manifest.json"
    _canonical_path = PHI_DIR / "step01__cohort_resp_waterfall.parquet"
    _cache_format_version = 1
    _batch_size = 250

    _cohort_hosp_set = set(
        cohort.select(pl.col("list_hospitalization_id").explode())
        .get_column("list_hospitalization_id")
        .to_list()
    )
    _resp_in = resp_utc_pd[resp_utc_pd["hospitalization_id"].isin(_cohort_hosp_set)].copy()

    _waterfall_source = inspect.getsourcefile(process_resp_support_waterfall)
    assert _waterfall_source is not None
    _cache_signature = {
        "format_version": _cache_format_version,
        "timezone": TIMEZONE,
        "bfill": True,
        "clifpy_version": version("clifpy"),
        "waterfall_sha256": file_sha256(_waterfall_source),
        "projection": ["hospitalization_id", "recorded_dttm", "device_category"],
        "time_basis": "site_local_naive",
        "respiratory_category_compatibility": "clif-2.1-and-3.0-v1",
    }
    _source_digests = waterfall_input_digests(_resp_in)
    _required_resp_ids = set(_source_digests)

    _manifest_existed = _manifest_path.exists()
    if _manifest_existed:
        try:
            with open(_manifest_path) as _file:
                _manifest = json.load(_file)
        except (OSError, ValueError):
            _manifest = {}
    else:
        _manifest = {}
    if _manifest.get("signature") != _cache_signature:
        _manifest = {"signature": _cache_signature, "entries": {}, "shards": {}}
    _entries = _manifest["entries"]
    _shards = _manifest["shards"]

    # One-time migration: the prior canonical waterfall is a valid cache seed when its
    # projected rows still align to the current raw respiratory timestamps. Block and run
    # identifiers are deliberately discarded and rebuilt from the current cohort.
    if not _manifest_existed and _canonical_path.exists() and _required_resp_ids:
        _seed = (
            pl.read_parquet(_canonical_path)
            .select("hospitalization_id", "recorded_dttm", "device_category")
            .filter(pl.col("hospitalization_id").cast(pl.String).is_in(_required_resp_ids))
            .with_columns(pl.col("hospitalization_id").cast(pl.String))
        )
        _seed_real = (
            _seed.filter(pl.col("recorded_dttm").dt.second() != 59)
            .select("hospitalization_id", "recorded_dttm")
            .unique()
        )
        _seed_orphans = _seed_real.join(
            resp_raw.with_columns(pl.col("hospitalization_id").cast(pl.String))
            .select("hospitalization_id", "recorded_dttm")
            .unique(),
            on=["hospitalization_id", "recorded_dttm"],
            how="anti",
        )
        if _seed_orphans.is_empty():
            _seed_ids = set(_seed.get_column("hospitalization_id").unique().to_list())
            _seed_path = _cache_dir / "seed.parquet"
            write_parquet_atomic(_seed, _seed_path)
            _seed_hash = file_sha256(_seed_path)
            _shards[_seed_path.name] = {"sha256": _seed_hash}
            for _hospitalization_id in _seed_ids:
                _entries[_hospitalization_id] = {
                    "digest": _source_digests[_hospitalization_id],
                    "shard": _seed_path.name,
                }
            write_json_atomic(_manifest, _manifest_path)
            print(f"waterfall cache seeded from canonical parquet: {len(_seed_ids):,} hospitalizations")
        else:
            print(
                "existing canonical waterfall was not used as a cache seed: "
                f"{_seed_orphans.height:,} non-scaffold rows do not align to current raw data"
            )

    _valid_shards = set()
    for _shard_name, _shard_meta in _shards.items():
        _shard_path = _cache_dir / _shard_name
        if _shard_path.exists() and file_sha256(_shard_path) == _shard_meta.get("sha256"):
            _valid_shards.add(_shard_name)

    _valid_entries = valid_waterfall_cache_entries(
        _source_digests, _entries, _valid_shards
    )
    _missing_ids = sorted(_required_resp_ids - set(_valid_entries))
    _n_cache_hits = len(_valid_entries)
    _n_missing = len(_missing_ids)
    print(
        f"waterfall cache: {_n_cache_hits:,} hit(s), {_n_missing:,} "
        "hospitalization(s) to process"
    )

    _run_token = COHORT_RUN_ID.replace(":", "").replace("-", "")
    for _batch_number, _start in enumerate(range(0, len(_missing_ids), _batch_size), start=1):
        _batch_ids = _missing_ids[_start : _start + _batch_size]
        _batch_input = _resp_in[
            _resp_in["hospitalization_id"].astype(str).isin(_batch_ids)
        ].copy()
        _waterfalled = process_resp_support_waterfall(
            _batch_input,
            id_col="hospitalization_id",
            # Device inference is complete before bfill reaches numeric settings. The
            # retained projection therefore remains device-category equivalent.
            bfill=True,
            verbose=False,
        )
        _waterfalled["recorded_dttm"] = (
            _waterfalled["recorded_dttm"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
        )
        _batch_frame = normalize_respiratory_categories(
            normalize_category_columns(
                pl.from_pandas(
                    _waterfalled[
                        ["hospitalization_id", "recorded_dttm", "device_category"]
                    ]
                ).with_columns(pl.col("hospitalization_id").cast(pl.String)),
                "device_category",
            )
        )
        _got_batch_ids = set(
            _batch_frame.get_column("hospitalization_id").unique().to_list()
        )
        assert _got_batch_ids == set(_batch_ids), (
            "waterfall batch did not return every requested hospitalization"
        )
        _shard_name = f"batch_{_run_token}_{_batch_number:05d}.parquet"
        _shard_path = _cache_dir / _shard_name
        write_parquet_atomic(_batch_frame, _shard_path)
        _shards[_shard_name] = {"sha256": file_sha256(_shard_path)}
        for _hospitalization_id in _batch_ids:
            _entry = {
                "digest": _source_digests[_hospitalization_id],
                "shard": _shard_name,
            }
            _entries[_hospitalization_id] = _entry
            _valid_entries[_hospitalization_id] = _entry
        write_json_atomic(_manifest, _manifest_path)
        print(
            f"waterfall cache batch {_batch_number}: {_batch_ids[0]} .. "
            f"{_batch_ids[-1]} ({len(_batch_ids):,} hospitalizations)"
        )

    if not _required_resp_ids:
        _cached_waterfall = (
            encounter_mapping.select("hospitalization_id").head(0)
            .with_columns(
                pl.col("hospitalization_id").cast(pl.String),
                pl.lit(None, dtype=pl.Datetime).alias("recorded_dttm"),
                pl.lit(None, dtype=pl.String).alias("device_category"),
            )
        )
    else:
        _ids_by_shard = {}
        for _hospitalization_id in _required_resp_ids:
            _entry = _valid_entries[_hospitalization_id]
            _ids_by_shard.setdefault(_entry["shard"], []).append(_hospitalization_id)
        _cached_waterfall = pl.concat(
            [
                pl.read_parquet(_cache_dir / _shard_name)
                .with_columns(pl.col("hospitalization_id").cast(pl.String))
                .filter(pl.col("hospitalization_id").is_in(_hospitalization_ids))
                .select("hospitalization_id", "recorded_dttm", "device_category")
                for _shard_name, _hospitalization_ids in _ids_by_shard.items()
            ],
            how="vertical_relaxed",
        )
        assert set(
            _cached_waterfall.get_column("hospitalization_id").unique().to_list()
        ) == _required_resp_ids, "assembled waterfall cache does not cover current respiratory IDs"

    resp_waterfall = (
        normalize_respiratory_categories(
            normalize_category_columns(_cached_waterfall, "device_category")
        )
        .join(
            encounter_mapping.with_columns(pl.col("hospitalization_id").cast(pl.String)),
            on="hospitalization_id",
            how="inner",
        )
        .filter(pl.col("hospitalization_id").is_in([str(value) for value in _cohort_hosp_set]))
        .sort(["encounter_block", "recorded_dttm"])
    )

    # The waterfall's device heuristics can invent categories the raw table never had, so
    # assert the vocabulary is the one we expect rather than discovering it downstream.
    _MCIDE_DEVICE_LOWER = {
        "imv", "nippv", "cpap", "high flow nc", "face mask",
        "trach collar", "t piece", "nasal cannula", "room air", "other",
    }
    _seen = set(
        resp_waterfall.get_column("device_category").drop_nulls().unique().to_list()
    )
    assert _seen <= _MCIDE_DEVICE_LOWER, (
        "waterfall emitted unsupported CLIF 2.1/3.0 device_category values: "
        f"{sorted(_seen - _MCIDE_DEVICE_LOWER)}"
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

    # Persist immediately after assembly. Batch shards already make computation resumable;
    # atomic promotion keeps downstream steps from seeing a partially written canonical file.
    write_parquet_atomic(
        resp_waterfall.with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID)),
        _canonical_path,
    )
    print(f"waterfall cache assembled and saved: {_canonical_path}")
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
    print(f"step01__cohort_resp_waterfall.parquet  {resp_waterfall.height:,} rows")
    print(f"step01__cohort_index.parquet           {cohort_index_out.height:,} rows")
    print(f"step01__consort_cohort.csv             {consort_df.height} steps -> {SHARE_DIR}")
    print(f"step01__cohort_qc.csv                  {cohort_qc.height} stats")
    print("\nCONSORT")
    print(consort_df)
    return cohort_index_out, consort_df


if __name__ == "__main__":
    app.run()
