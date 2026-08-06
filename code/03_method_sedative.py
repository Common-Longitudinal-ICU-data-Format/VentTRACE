import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from pathlib import Path

    import polars as pl

    from clifpy.tables import MedicationAdminIntermittent

    import marimo as mo

    return MedicationAdminIntermittent, Path, json, mo, pl


@app.cell
def _(mo):
    mo.md(
        """
        # 03 — Method `SED`, induction agents

        **The agents used to intubate a patient.** All intermittently dosed, so this reads
        `medication_admin_intermittent` and never the continuous table: an induction bolus
        and a maintenance infusion are the same drug performing two different clinical
        acts, told apart only by which table they are charted in.

        ```
        midazolam | etomidate | ketamine | propofol | fentanyl
        ```

        The method is a **profiler**, not a detector. It reports the ranked medication
        sequence around t0 — agent, dose, unit, signed lag — and the binary `detected` flag
        falls out of that structure rather than being computed beside it, so the two cannot
        disagree.

        It runs on **every cohort encounter**, including the ones `02` excluded. `06` owns
        the single subsetting step; this notebook only carries `index_class` through.

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` §6, §7
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

    METHOD_ID = "SED"
    # Written in lower case to match the lower-cased column (D21).
    MED_CATEGORIES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]

    print(f"site      : {SITE}")
    print(f"method    : {METHOD_ID}")
    print(f"med list  : {' | '.join(MED_CATEGORIES)}")
    return (
        DATA_DIR,
        FILETYPE,
        MED_CATEGORIES,
        METHOD_ID,
        PHI_DIR,
        TIMEZONE,
    )


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. `tz_convert` re-resolves against
        the tz database first. Pinned by `tests/test_clifpy_tz_boundary.py`.
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
    print(f"cohort encounters : {index_imv.height:,}   (N*, the denominator for this method)")
    print(f"  of which qualified : {index_imv.filter(pl.col('index_qualified')).height:,}   (N**)")
    return COHORT_RUN_ID, index_imv


@app.cell
def _(mo):
    mo.md(
        """
        ## The explode-and-drop bridge

        CLIF tables are keyed on `hospitalization_id`; this study is keyed on
        `encounter_block`. The bridge below is the **only** place this notebook may name a
        hospitalization, and `hospitalization_id` is dropped the moment the join lands.

        That drop is a requirement, not tidiness. A sedative given in the ED presentation
        and an IMV row charted after transfer belong to one encounter; if
        `hospitalization_id` survived into the window filter or the ranking, the method
        would quietly revert to the unstitched unit and reintroduce exactly the artifact
        stitching removes. Dropping the column makes that mistake impossible to write
        rather than merely discouraged.
        """
    )
    return


@app.cell
def _(index_imv, pl):
    bridge = (
        index_imv.select(
            [
                "encounter_block",
                "list_hospitalization_id",
                "t0_dttm",
                "window_start",
                "window_end",
            ]
        )
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )

    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    print(f"encounter blocks   : {bridge.get_column('encounter_block').n_unique():,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    MedicationAdminIntermittent,
    TIMEZONE,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    # Filtered on hospitalization_id at load, but deliberately NOT on med_category. The
    # method's list is five values; filtering after lower-casing is both cheaper to reason
    # about and immune to the casing hole D22 exists to patch, since our own filter then
    # runs on a column we normalised ourselves.
    _med = MedicationAdminIntermittent.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "admin_dttm",
            "med_category",
            "mar_action_category",
            "med_dose",
            "med_dose_unit",
        ],
        filters={"hospitalization_id": bridge_hosp_ids},
    )

    med_all = pl.from_pandas(
        _med.df.assign(admin_dttm=lambda d: to_site_naive(d["admin_dttm"]))
    ).with_columns(
        med_category=pl.col("med_category").str.to_lowercase(),
        mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
    )

    print(f"administration rows loaded : {med_all.height:,}")
    print("\nmar_action_category values present (lower-cased):")
    print(med_all.get_column("mar_action_category").value_counts(sort=True).head(10))
    return (med_all,)


@app.cell
def _(MED_CATEGORIES, med_all, pl):
    med_method = med_all.filter(
        pl.col("med_category").is_in(MED_CATEGORIES)
        & (pl.col("mar_action_category") == "given")
    )

    # A category filter that matches nothing looks exactly like a site where the drug is
    # never given. Print what was actually found so the two are distinguishable, and fail
    # only if the whole list came back empty -- an individual agent may genuinely be absent
    # from a site's formulary (MIMIC, for instance, charts no etomidate).
    _found = med_method.get_column("med_category").value_counts(sort=True)
    _missing = sorted(set(MED_CATEGORIES) - set(_found.get_column("med_category").to_list()))

    print(f"rows matching the method list and mar_action_category='given' : {med_method.height:,}")
    print(_found)
    if _missing:
        print(f"\nNOT PRESENT AT THIS SITE: {', '.join(_missing)}")
        print("  -> not an error, but every rate below is computed without them")

    assert med_method.height > 0, (
        "no administration matched the method's med_category list at all. Either the site "
        "charts none of these agents, or the vocabulary differs -- compare the value_counts "
        "printed above against the mCIDE med_category list before trusting a zero."
    )
    return (med_method,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Attach the encounter, then drop the hospitalization
        """
    )
    return


@app.cell
def _(bridge, med_method, pl):
    med_enc = (
        med_method.join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # step 6 of the bridge -- everything below is per block
        .with_columns(
            delta_minutes=(
                (pl.col("admin_dttm") - pl.col("t0_dttm")).dt.total_seconds() / 60.0
            ).round(1)
        )
    )

    assert "hospitalization_id" not in med_enc.columns, "the bridge leaked its key"
    print(f"administrations attached to an encounter : {med_enc.height:,}")
    return (med_enc,)


@app.cell
def _(med_enc, pl):
    # BEFORE is [window_start, t0) and AFTER is (t0, window_end], so an administration
    # landing exactly on t0 belongs to neither. Worth measuring rather than assuming away:
    # this site charts respiratory support on the hour, which is exactly the condition
    # under which an exact collision is plausible.
    med_window = med_enc.filter(
        (pl.col("admin_dttm") >= pl.col("window_start"))
        & (pl.col("admin_dttm") <= pl.col("window_end"))
    )
    _n_at_t0 = med_window.filter(pl.col("delta_minutes") == 0).height

    print(f"administrations inside the window : {med_window.height:,}")
    print(
        f"  exactly at t0 (in neither direction) : {_n_at_t0:,} "
        f"({100 * _n_at_t0 / max(med_window.height, 1):.2f}%)"
    )
    return (med_window,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The ranking rule

        ```
        BEFORE   for each distinct med_category with >=1 administration in [window_start, t0)
                   keep the LAST administration  (the one closest to t0)
                 then rank by proximity to t0 -- rank 1 is nearest

        AFTER    for each distinct med_category with >=1 administration in (t0, window_end]
                   keep the FIRST administration (the one closest to t0)
                 then rank by proximity to t0 -- rank 1 is nearest
        ```

        Deduplication is **by `med_category`**, so repeat doses of one agent collapse to the
        single administration nearest the intubation and no encounter is over-weighted by a
        patient who was redosed. Ties on an identical `admin_dttm` break alphabetically, so
        the output is byte-identical across runs.

        No rank cap: ranks are bounded by the list length — at most 5 here — so a cap of 5
        could never truncate anything and would read as load-bearing when it is not.

        `med_dose` and `med_dose_unit` are the raw charted values. **No unit conversion.**
        Normalising would hide unit heterogeneity that is itself worth measuring.
        """
    )
    return

@app.cell
def _(pl):
    def rank_direction(df, direction):
        """Dedup to one row per (encounter_block, med_category), then rank by proximity.

        "LAST before" and "FIRST after" are two statements of one rule: keep the
        administration nearest t0. Before t0 every delta is negative, so nearest is the
        largest; after t0 every delta is positive, so nearest is the smallest. Both are
        `argmin(|delta|)`, which is why one function serves both directions rather than
        two that could drift apart.
        """
        _nearest = pl.col("abs_delta").arg_min()
        return (
            df.with_columns(abs_delta=pl.col("delta_minutes").abs())
            # sort first so `arg_min` resolves an exact |delta| tie -- the same agent
            # charted twice at one instant -- deterministically rather than by join order
            .sort(["encounter_block", "med_category", "abs_delta", "med_dose"])
            .group_by(["encounter_block", "med_category"], maintain_order=True)
            .agg(
                med_dose=pl.col("med_dose").get(_nearest),
                med_dose_unit=pl.col("med_dose_unit").get(_nearest),
                admin_dttm=pl.col("admin_dttm").get(_nearest),
                delta_minutes=pl.col("delta_minutes").get(_nearest),
                abs_delta=pl.col("abs_delta").get(_nearest),
            )
            # med_category breaks a tie between two DIFFERENT agents sharing an admin_dttm,
            # alphabetically, so the rank ladder is byte-identical across runs
            .sort(["encounter_block", "abs_delta", "med_category"])
            .with_columns(
                rank=pl.int_range(1, pl.len() + 1).over("encounter_block"),
                direction=pl.lit(direction),
            )
            .drop("abs_delta")
        )

    return (rank_direction,)


@app.cell
def _(med_window, pl, rank_direction):
    before_ranked = rank_direction(med_window.filter(pl.col("delta_minutes") < 0), "before")
    after_ranked = rank_direction(med_window.filter(pl.col("delta_minutes") > 0), "after")

    # The ladder must widen: rank 1 is nearest by construction, so median |delta| has to be
    # non-decreasing in rank. A ladder that does not is a ranking bug, and it would show up
    # in Tier B as a nonsense result rather than as an error.
    for _name, _df in (("before", before_ranked), ("after", after_ranked)):
        _ladder = (
            _df.group_by("rank")
            .agg(n=pl.len(), median_abs=pl.col("delta_minutes").abs().median())
            .sort("rank")
        )
        print(f"{_name} ladder")
        print(_ladder)
        _m = _ladder.get_column("median_abs").to_list()
        assert all(a <= b for a, b in zip(_m, _m[1:])), (
            f"{_name} ranks do not widen monotonically: {_m}. Rank 1 is defined as nearest "
            "to t0, so this can only be a bug in the ranking."
        )
    return after_ranked, before_ranked


@app.cell
def _(mo):
    mo.md(
        """
        ## Artifacts

        `method_SED_encounter.parquet` — one row per **cohort** encounter, non-detections
        included. It is the denominator for every rate in `06`.

        `method_SED_ranked.json` — newline-delimited, one object per intubation episode,
        carrying the full rank ladder that the encounter table flattens to rank 1 only.
        Tier B reads this file.
        """
    )
    return


@app.cell
def _(after_ranked, before_ranked, index_imv, METHOD_ID, pl):
    def _rank1(df, prefix):
        return df.filter(pl.col("rank") == 1).select(
            "encounter_block",
            pl.col("med_category").alias(f"nearest_{prefix}_med"),
            pl.col("delta_minutes").alias(f"nearest_{prefix}_min"),
        )

    _counts_before = before_ranked.group_by("encounter_block").agg(n_before=pl.len())
    _counts_after = after_ranked.group_by("encounter_block").agg(n_after=pl.len())

    method_encounter = (
        index_imv.select(
            [
                "encounter_block",
                "patient_id",
                "intubation_episode_id",
                "cohort_run_id",
                "index_class",
                "index_qualified",
                pl.col("t0_dttm").alias("imv_dttm"),
            ]
        )
        .join(_counts_before, on="encounter_block", how="left")
        .join(_counts_after, on="encounter_block", how="left")
        .join(_rank1(before_ranked, "before"), on="encounter_block", how="left")
        .join(_rank1(after_ranked, "after"), on="encounter_block", how="left")
        .with_columns(
            method_id=pl.lit(METHOD_ID),
            n_before=pl.col("n_before").fill_null(0).cast(pl.Int32),
            n_after=pl.col("n_after").fill_null(0).cast(pl.Int32),
        )
        # `detected` is DERIVED from the ranked structure, never computed beside it, so the
        # binary and the profile cannot disagree.
        .with_columns(detected=(pl.col("n_before") > 0) | (pl.col("n_after") > 0))
        .select(
            [
                "encounter_block",
                "patient_id",
                "intubation_episode_id",
                "cohort_run_id",
                "index_class",
                "index_qualified",
                "method_id",
                "imv_dttm",
                "detected",
                "n_before",
                "n_after",
                "nearest_before_med",
                "nearest_before_min",
                "nearest_after_med",
                "nearest_after_min",
            ]
        )
        .sort("encounter_block")
    )

    assert method_encounter.height == index_imv.height, (
        "the encounter table must have exactly one row per cohort encounter"
    )
    assert method_encounter.get_column("intubation_episode_id").n_unique() == index_imv.height
    return (method_encounter,)


@app.cell
def _(after_ranked, before_ranked, index_imv, METHOD_ID, pl):
    def _nest(df, name):
        return (
            df.select(
                "encounter_block",
                pl.struct(
                    rank="rank",
                    med_category="med_category",
                    med_dose="med_dose",
                    med_dose_unit="med_dose_unit",
                    admin_dttm=pl.col("admin_dttm").dt.to_string("%Y-%m-%dT%H:%M:%S"),
                    delta_minutes="delta_minutes",
                ).alias(name),
            )
            .group_by("encounter_block", maintain_order=True)
            .agg(pl.col(name))
        )

    _before_nested = _nest(before_ranked, "before")
    _after_nested = _nest(after_ranked, "after")

    method_ranked = (
        index_imv.select(
            [
                "encounter_block",
                "patient_id",
                "index_class",
                "intubation_episode_id",
                pl.lit(METHOD_ID).alias("method_id"),
                pl.col("t0_dttm").dt.to_string("%Y-%m-%dT%H:%M:%S").alias("imv_dttm"),
            ]
        )
        .join(_before_nested, on="encounter_block", how="left")
        .join(_after_nested, on="encounter_block", how="left")
        # An empty array, not a null: the object is written for every cohort encounter so
        # the file has one record per encounter and non-detections are counted, not absent.
        # A null would make "nothing was given" and "this encounter was not processed"
        # indistinguishable in the file that is meant to be canonical.
        .with_columns(
            before=pl.col("before").fill_null(
                pl.lit([], dtype=_before_nested.schema["before"])
            ),
            after=pl.col("after").fill_null(
                pl.lit([], dtype=_after_nested.schema["after"])
            ),
        )
        .sort("encounter_block")
    )

    assert method_ranked.height == index_imv.height
    return (method_ranked,)


@app.cell
def _(METHOD_ID, PHI_DIR, method_encounter, method_ranked, pl):
    _enc_path = PHI_DIR / f"method_{METHOD_ID}_encounter.parquet"
    _json_path = PHI_DIR / f"method_{METHOD_ID}_ranked.json"

    method_encounter.write_parquet(_enc_path)
    method_ranked.write_ndjson(_json_path)

    _detected = method_encounter.filter(pl.col("detected"))
    _qual = method_encounter.filter(pl.col("index_qualified"))
    _qual_detected = _qual.filter(pl.col("detected"))

    print(f"method_{METHOD_ID}_encounter.parquet   {method_encounter.height:,} rows -> {PHI_DIR}")
    print(f"method_{METHOD_ID}_ranked.json         {method_ranked.height:,} records")
    print()
    print(
        f"detection over ALL cohort encounters : {_detected.height:,} / "
        f"{method_encounter.height:,}  ({100 * _detected.height / method_encounter.height:.1f}%)"
    )
    print(
        f"detection over the INDEX set (N**)   : {_qual_detected.height:,} / "
        f"{_qual.height:,}  ({100 * _qual_detected.height / max(_qual.height, 1):.1f}%)"
    )
    print("\ndetection rate by index_class (the Tier D input):")
    print(
        method_encounter.group_by("index_class")
        .agg(n=pl.len(), rate=pl.col("detected").mean().round(3))
        .sort("n", descending=True)
    )
    print("\nnearest before-rank-1 agent, where one exists:")
    print(
        method_encounter.filter(pl.col("nearest_before_med").is_not_null())
        .group_by("nearest_before_med")
        .agg(n=pl.len(), median_min=pl.col("nearest_before_min").median())
        .sort("n", descending=True)
    )
    return


if __name__ == "__main__":
    app.run()
