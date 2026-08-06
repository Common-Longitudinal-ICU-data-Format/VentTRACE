import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from pathlib import Path

    import polars as pl

    from clifpy.tables import MedicationAdminContinuous, MedicationAdminIntermittent

    import marimo as mo

    return (
        MedicationAdminContinuous,
        MedicationAdminIntermittent,
        Path,
        json,
        mo,
        pl,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 04 — Method `PARA`, neuromuscular blockade

        ```
        rocuronium | succinylcholine | vecuronium
        ```

        A paralytic is the more **specific** of the two medication signals and the less
        sensitive. Nobody is given rocuronium as ambient ICU care the way they are given
        fentanyl, so a paralytic in the window is close to a statement that an airway was
        secured here — but plenty of real intubations are performed without one, so its
        detection rate should sit below `SED`'s while its Tier D gap sits above it.

        **This notebook is a deliberate copy of `03`, differing only in `MED_CATEGORIES`.**
        Factoring the shared body into a helper module would couple the two methods, and
        the whole point of the comparison is that each can be read, changed and audited
        without touching the other. The duplication is the design, not an oversight.

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

    METHOD_ID = "PARA"
    # Written in lower case to match the lower-cased column (D21).
    MED_CATEGORIES = ["rocuronium", "succinylcholine", "vecuronium"]

    # D40. Read from config rather than resolved upstream for the reason D9 gives about
    # pair_gap_hours: 01 has no administration set in hand and nothing to precompute.
    INFUSION_PREP_MINUTES = config["infusion_prep_minutes"]

    # The sweep grid is an ANALYSIS grid, not a site parameter, so it is a constant here
    # rather than a config key -- a site that changed it would make its sweep curve
    # non-comparable with every other site's, which is the one thing the curve is for.
    PREP_SWEEP_MINUTES = [5, 10, 15, 30, 45, 60, 90, 120, 150, 180]

    print(f"site      : {SITE}")
    print(f"method    : {METHOD_ID}")
    print(f"med list  : {' | '.join(MED_CATEGORIES)}")
    print(f"prep gap  : {INFUSION_PREP_MINUTES} min   (D40)")
    print(f"sweep     : {PREP_SWEEP_MINUTES}")
    return (
        DATA_DIR,
        FILETYPE,
        INFUSION_PREP_MINUTES,
        MED_CATEGORIES,
        METHOD_ID,
        PHI_DIR,
        PREP_SWEEP_MINUTES,
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

        That drop is a requirement, not tidiness. A paralytic given in the ED presentation
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
                "intubation_episode_id",
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

    # A block with several episodes (D35) appears on several bridge rows, so one
    # administration fans out to every episode of its block and the window filter then
    # decides which episodes it actually belongs to. The fan-out is intended: an
    # administration in the overlap of two windows genuinely belongs to both. 02 asserts
    # that overlap stays rare -- one pair in 7,777 at MIMIC.
    print(f"episodes           : {bridge.get_column('intubation_episode_id').n_unique():,}")
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
    # method's list is three values; filtering after lower-casing is both cheaper to reason
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
    # from a site's formulary -- succinylcholine, for instance, is often absent.
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
        r"""
        ## D40 / D41 — the continuous table, as a disqualifier only

        **No detection originates here.** `medication_admin_continuous` is opened solely to
        reclassify intermittent rows that have already been found, which is what leaves D1a's
        removal of `INF` intact: the study still never claims an infusion means a ventilator.

        Two flags, consuming two different subsets of the same table:

        ```
        lag_to_infusion_min   forward as-of to mar_action_category == 'start' only
                              -> D40 needs an infusion BEGINNING

        during_infusion       backward as-of to the FULL event stream
                              start | stop | dose_change | going
                              -> "is a drip running right now" is answered by the most
                                 recent event of ANY kind, not by starts alone
        ```

        Both are properties of an administration and of nothing else, so they are computed
        **here, before the bridge**, while `hospitalization_id` still exists. `infusion_prep`
        is derived later, after `delta_minutes` exists, because it alone needs to know which
        side of t0 the administration fell on.
        """
    )
    return


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    MED_CATEGORIES,
    MedicationAdminContinuous,
    TIMEZONE,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    _cont = MedicationAdminContinuous.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=[
            "hospitalization_id",
            "admin_dttm",
            "med_category",
            "mar_action_category",
        ],
        filters={"hospitalization_id": bridge_hosp_ids},
    )

    cont_method = (
        pl.from_pandas(
            _cont.df.assign(admin_dttm=lambda d: to_site_naive(d["admin_dttm"]))
        )
        .with_columns(
            med_category=pl.col("med_category").str.to_lowercase(),
            mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
        )
        .filter(pl.col("med_category").is_in(MED_CATEGORIES))
    )

    print(f"continuous rows for this method's agents : {cont_method.height:,}")
    print("\nmar_action_category present (lower-cased):")
    print(cont_method.get_column("mar_action_category").value_counts(sort=True))

    # A site that charts continuous rows but never the literal 'start' makes D40 silently
    # inert -- every lag comes back null, nothing is ever reclassified, and the sub-analysis
    # reports a zero effect that is really a vocabulary mismatch. That is indistinguishable
    # from "this site gives no loading doses" unless it is said out loud here.
    _n_start = cont_method.filter(pl.col("mar_action_category") == "start").height
    if _n_start == 0:
        print(
            "\nWARNING: no mar_action_category == 'start' row exists for these agents.\n"
            "  -> D40 cannot fire and every induction_only rate will equal its plain\n"
            "     counterpart. Check the site's action vocabulary before reading Tier F\n"
            "     as evidence that loading doses are not given here."
        )
    return (cont_method,)


@app.cell
def _(cont_method, med_method, pl):
    # join_asof requires the left frame sorted on the as-of key, and it does not preserve
    # that sortedness as a guarantee across a second join, so each is re-sorted rather than
    # assumed. The `by` keys make this a per-(hospitalization, drug) scan, which is the
    # whole point -- a propofol bolus is never matched against a fentanyl drip.
    _starts = (
        cont_method.filter(pl.col("mar_action_category") == "start")
        .select("hospitalization_id", "med_category", inf_start_dttm="admin_dttm")
        .unique()
        .sort("inf_start_dttm")
    )
    _events = (
        cont_method.select(
            "hospitalization_id",
            "med_category",
            _evt_dttm="admin_dttm",
            _evt_action="mar_action_category",
        )
        .sort("_evt_dttm")
    )

    med_flagged = (
        med_method.sort("admin_dttm")
        .join_asof(
            _starts,
            left_on="admin_dttm",
            right_on="inf_start_dttm",
            by=["hospitalization_id", "med_category"],
            strategy="forward",
        )
        .sort("admin_dttm")
        .join_asof(
            _events,
            left_on="admin_dttm",
            right_on="_evt_dttm",
            by=["hospitalization_id", "med_category"],
            strategy="backward",
        )
        .with_columns(
            lag_to_infusion_min=(
                (pl.col("inf_start_dttm") - pl.col("admin_dttm")).dt.total_seconds() / 60.0
            ).round(1),
            # A null `_evt_action` means this drug was never infused before this moment,
            # which is not "running" -- absence is not evidence, the same reading D37
            # applies to devices.
            during_infusion=pl.col("_evt_action").is_not_null()
            & (pl.col("_evt_action") != "stop"),
        )
        .drop(["inf_start_dttm", "_evt_dttm", "_evt_action"])
    )

    assert med_flagged.height == med_method.height, (
        "the as-of joins changed the row count. join_asof must be many-to-one; a duplicated "
        "(hospitalization_id, med_category, dttm) key on the right side would fan out."
    )
    # Forward-only by construction, so a negative lag would mean the join matched backwards.
    _neg = med_flagged.filter(pl.col("lag_to_infusion_min") < 0).height
    assert _neg == 0, f"{_neg:,} administrations carry a negative lag to the next infusion"

    print(f"administrations flagged : {med_flagged.height:,}")
    print(
        f"  with a later same-drug infusion start : "
        f"{med_flagged.get_column('lag_to_infusion_min').is_not_null().sum():,}"
    )
    print(
        f"  given during a running same-drug drip : "
        f"{med_flagged.get_column('during_infusion').sum():,}"
    )
    return (med_flagged,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Attach the encounter, then drop the hospitalization
        """
    )
    return


@app.cell
def _(bridge, med_flagged, pl):
    med_enc = (
        med_flagged.join(bridge, on="hospitalization_id", how="inner")
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
def _(INFUSION_PREP_MINUTES, med_enc, pl):
    # BEFORE is [window_start, t0) and AFTER is (t0, window_end], so an administration
    # landing exactly on t0 belongs to neither. Worth measuring rather than assuming away:
    # this site charts respiratory support on the hour, which is exactly the condition
    # under which an exact collision is plausible.
    med_window = med_enc.filter(
        (pl.col("admin_dttm") >= pl.col("window_start"))
        & (pl.col("admin_dttm") <= pl.col("window_end"))
    ).with_columns(
        # D40. The `delta_minutes > 0` term is the whole rule, not a guard: the pre-t0 half
        # is EXEMPT, and the data is why. 20.7% of pre-t0 administrations are followed by a
        # same-drug infusion start within 15 min against 7.6% after -- a pre-t0 bolus is
        # nearly three times MORE likely to precede a drip, because induction -> intubation
        # -> maintenance is the canonical sequence. Dropping this term would delete 2,669
        # genuine induction boluses to remove 1,909 prep doses.
        infusion_prep=(pl.col("delta_minutes") > 0)
        & pl.col("lag_to_infusion_min").is_not_null()
        & (pl.col("lag_to_infusion_min") <= INFUSION_PREP_MINUTES),
    )
    _n_at_t0 = med_window.filter(pl.col("delta_minutes") == 0).height

    print(f"administrations inside the window : {med_window.height:,}")
    print(
        f"  exactly at t0 (in neither direction) : {_n_at_t0:,} "
        f"({100 * _n_at_t0 / max(med_window.height, 1):.2f}%)"
    )

    # D41 is measured on BOTH halves and this print is the reason it does not act. If the
    # two percentages are close, the flag says "this patient is on sedation" -- a property
    # of the admission -- rather than anything about the airway event.
    for _lab, _f in (("before t0", pl.col("delta_minutes") < 0),
                     ("after  t0", pl.col("delta_minutes") > 0)):
        _s = med_window.filter(_f)
        print(
            f"  {_lab}: {_s.height:>6,} administrations | "
            f"during_infusion {100 * _s.get_column('during_infusion').mean():5.1f}% | "
            f"infusion_prep {100 * _s.get_column('infusion_prep').mean():5.1f}%"
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

        No rank cap: ranks are bounded by the list length — at most 3 here — so the cap of 5
        considered for `SED` could not have truncated anything here either.

        `med_dose` and `med_dose_unit` are the raw charted values. **No unit conversion.**
        Normalising would hide unit heterogeneity that is itself worth measuring.
        """
    )
    return

@app.cell
def _(pl):
    def rank_direction(df, direction):
        """Dedup to one row per (episode, med_category), then rank by proximity.

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
            .sort(["intubation_episode_id", "med_category", "abs_delta", "med_dose"])
            .group_by(["intubation_episode_id", "med_category"], maintain_order=True)
            .agg(
                med_dose=pl.col("med_dose").get(_nearest),
                med_dose_unit=pl.col("med_dose_unit").get(_nearest),
                admin_dttm=pl.col("admin_dttm").get(_nearest),
                delta_minutes=pl.col("delta_minutes").get(_nearest),
                abs_delta=pl.col("abs_delta").get(_nearest),
                # D40/D41 travel with the administration the ladder KEPT, which is the one
                # nearest t0 -- they describe that dose and no other. This is exactly why
                # 07 must not recompute a rate by filtering the ladder (spec 6.4): a drug
                # whose nearest after-dose is prep but whose second dose is not still holds
                # induction evidence, and the ladder no longer carries the second dose.
                infusion_prep=pl.col("infusion_prep").get(_nearest),
                during_infusion=pl.col("during_infusion").get(_nearest),
                lag_to_infusion_min=pl.col("lag_to_infusion_min").get(_nearest),
            )
            # med_category breaks a tie between two DIFFERENT agents sharing an admin_dttm,
            # alphabetically, so the rank ladder is byte-identical across runs
            .sort(["intubation_episode_id", "abs_delta", "med_category"])
            .with_columns(
                rank=pl.int_range(1, pl.len() + 1).over("intubation_episode_id"),
                direction=pl.lit(direction),
            )
            .drop("abs_delta")
        )

    return (rank_direction,)


@app.cell
def _(med_window, pl, rank_direction):
    before_ranked = rank_direction(med_window.filter(pl.col("delta_minutes") < 0), "before")
    after_ranked = rank_direction(med_window.filter(pl.col("delta_minutes") > 0), "after")

    # Rank 1 is defined as nearest to t0, so WITHIN an episode |delta| must be
    # non-decreasing in rank. That is the invariant the ranking actually guarantees, and it
    # is the one asserted.
    #
    # The median-by-rank ladder printed below usually widens too, but it is NOT guaranteed
    # to and must not be asserted on: each rank is a median over a DIFFERENT set of
    # episodes, so a deep rank reached by only a handful of them can sit anywhere. An
    # earlier version of this check asserted ladder monotonicity and failed on a correct
    # ranking the moment rank 4 got down to a single episode.
    for _name, _df in (("before", before_ranked), ("after", after_ranked)):
        _viol = (
            _df.sort(["intubation_episode_id", "rank"])
            .with_columns(
                _prev=pl.col("delta_minutes").abs().shift(1).over("intubation_episode_id")
            )
            .filter(
                pl.col("_prev").is_not_null()
                & (pl.col("delta_minutes").abs() < pl.col("_prev"))
            )
        )
        assert _viol.height == 0, (
            f"{_name}: {_viol.height:,} rows where rank n sits CLOSER to t0 than rank n-1 "
            "inside the same episode. Rank 1 is defined as nearest, so this is a bug in "
            "the ranking itself."
        )
        print(f"{_name} ladder   (per-episode monotonicity verified)")
        print(
            _df.group_by("rank")
            .agg(n=pl.len(), median_abs=pl.col("delta_minutes").abs().median())
            .sort("rank")
        )
    return after_ranked, before_ranked


@app.cell
def _(mo):
    mo.md(
        """
        ## Artifacts

        `method_PARA_encounter.parquet` — one row per **cohort** encounter, non-detections
        included. It is the denominator for every rate in `06`.

        `method_PARA_ranked.json` — newline-delimited, one object per intubation episode,
        carrying the full rank ladder that the encounter table flattens to rank 1 only.
        Tier B reads this file.
        """
    )
    return


@app.cell
def _(after_ranked, before_ranked, index_imv, med_window, METHOD_ID, pl):
    def _rank1(df, prefix):
        return df.filter(pl.col("rank") == 1).select(
            "intubation_episode_id",
            pl.col("med_category").alias(f"nearest_{prefix}_med"),
            pl.col("delta_minutes").alias(f"nearest_{prefix}_min"),
        )

    _counts_before = before_ranked.group_by("intubation_episode_id").agg(n_before=pl.len())
    _counts_after = after_ranked.group_by("intubation_episode_id").agg(n_after=pl.len())

    # FILTER, THEN RANK -- never rank, then filter (spec 6.4). Every count below is taken
    # on the UNRANKED window set as n_unique(med_category), which is what `n_before` and
    # `n_after` also equal, since the ladder holds exactly one row per category. Deriving
    # these from `after_ranked` instead would silently under-count: it keeps only the dose
    # nearest t0 per drug, so a drug whose nearest after-dose is prep would look like it
    # had no induction evidence when a later dose supplied some.
    def _cat_count(pred, name):
        return (
            med_window.filter(pred)
            .group_by("intubation_episode_id")
            .agg(pl.col("med_category").n_unique().alias(name))
        )

    _after = pl.col("delta_minutes") > 0
    _before = pl.col("delta_minutes") < 0
    _counts_after_induction = _cat_count(_after & ~pl.col("infusion_prep"), "n_after_induction")
    _counts_after_prep = _cat_count(_after & pl.col("infusion_prep"), "n_after_prep")
    _counts_before_during = _cat_count(_before & pl.col("during_infusion"), "n_before_during")
    _counts_after_during = _cat_count(_after & pl.col("during_infusion"), "n_after_during")

    method_episode = (
        index_imv.select(
            [
                "intubation_episode_id",
                "encounter_block",
                "patient_id",
                "ep_num",
                "cohort_run_id",
                "index_class",
                "index_qualified",
                pl.col("t0_dttm").alias("imv_dttm"),
            ]
        )
        .join(_counts_before, on="intubation_episode_id", how="left")
        .join(_counts_after, on="intubation_episode_id", how="left")
        .join(_rank1(before_ranked, "before"), on="intubation_episode_id", how="left")
        .join(_rank1(after_ranked, "after"), on="intubation_episode_id", how="left")
        .join(_counts_after_induction, on="intubation_episode_id", how="left")
        .join(_counts_after_prep, on="intubation_episode_id", how="left")
        .join(_counts_before_during, on="intubation_episode_id", how="left")
        .join(_counts_after_during, on="intubation_episode_id", how="left")
        .with_columns(
            method_id=pl.lit(METHOD_ID),
            **{
                _c: pl.col(_c).fill_null(0).cast(pl.Int32)
                for _c in (
                    "n_before",
                    "n_after",
                    "n_after_induction",
                    "n_after_prep",
                    "n_before_during",
                    "n_after_during",
                )
            },
        )
        # `detected` is DERIVED from the ranked structure, never computed beside it, so the
        # binary and the profile cannot disagree. D40's variant shares the before-half
        # untouched, because D40 exempts it -- the two differ only in the after term.
        .with_columns(
            detected=(pl.col("n_before") > 0) | (pl.col("n_after") > 0),
            detected_induction_only=(pl.col("n_before") > 0)
            | (pl.col("n_after_induction") > 0),
        )
        .select(
            [
                "intubation_episode_id",
                "encounter_block",
                "patient_id",
                "ep_num",
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
                "detected_induction_only",
                "n_after_induction",
                "n_after_prep",
                "n_before_during",
                "n_after_during",
            ]
        )
        .sort(["encounter_block", "ep_num"])
    )

    assert method_episode.height == index_imv.height, (
        "the episode table must have exactly one row per candidate episode"
    )
    assert method_episode.get_column("intubation_episode_id").is_unique().all()

    # D40 only ever REMOVES evidence, so its variant is a strict subset. A violation would
    # mean the two columns were computed from different sets rather than one being a
    # filtered form of the other -- the exact drift the shared before-term exists to avoid.
    _impossible = method_episode.filter(
        pl.col("detected_induction_only") & ~pl.col("detected")
    ).height
    assert _impossible == 0, (
        f"{_impossible:,} episodes are induction_only-detected but not detected. "
        "detected_induction_only must be a subset of detected."
    )
    # n_after_induction and n_after_prep are NOT complementary -- a drug with both a prep
    # and a non-prep dose after t0 counts in both -- so their sum can exceed n_after. What
    # cannot happen is either exceeding it on its own.
    assert method_episode.filter(
        (pl.col("n_after_induction") > pl.col("n_after"))
        | (pl.col("n_after_prep") > pl.col("n_after"))
    ).height == 0, "a subset count exceeds n_after"
    return (method_episode,)


@app.cell
def _(after_ranked, before_ranked, index_imv, METHOD_ID, pl):
    def _nest(df, name):
        return (
            df.select(
                "intubation_episode_id",
                pl.struct(
                    rank="rank",
                    med_category="med_category",
                    med_dose="med_dose",
                    med_dose_unit="med_dose_unit",
                    admin_dttm=pl.col("admin_dttm").dt.to_string("%Y-%m-%dT%H:%M:%S"),
                    delta_minutes="delta_minutes",
                    # Written on BOTH arrays even though infusion_prep is always false on a
                    # `before` entry (D40 exempts that half). A consumer can then filter on
                    # one predicate across both directions instead of special-casing which
                    # array it is reading -- and the always-false column is itself the
                    # exemption, made auditable rather than left implicit.
                    infusion_prep="infusion_prep",
                    during_infusion="during_infusion",
                    lag_to_infusion_min="lag_to_infusion_min",
                ).alias(name),
            )
            .group_by("intubation_episode_id", maintain_order=True)
            .agg(pl.col(name))
        )

    _before_nested = _nest(before_ranked, "before")
    _after_nested = _nest(after_ranked, "after")

    method_ranked = (
        index_imv.select(
            [
                "intubation_episode_id",
                "encounter_block",
                "patient_id",
                "ep_num",
                "index_class",
                pl.lit(METHOD_ID).alias("method_id"),
                pl.col("t0_dttm").dt.to_string("%Y-%m-%dT%H:%M:%S").alias("imv_dttm"),
            ]
        )
        .join(_before_nested, on="intubation_episode_id", how="left")
        .join(_after_nested, on="intubation_episode_id", how="left")
        # An empty array, not a null: the object is written for every candidate episode so
        # the file has one record per episode and non-detections are counted, not absent.
        # A null would make "nothing was given" and "this episode was not processed"
        # indistinguishable in the file that is meant to be canonical.
        .with_columns(
            before=pl.col("before").fill_null(
                pl.lit([], dtype=_before_nested.schema["before"])
            ),
            after=pl.col("after").fill_null(
                pl.lit([], dtype=_after_nested.schema["after"])
            ),
        )
        .sort(["encounter_block", "ep_num"])
    )

    assert method_ranked.height == index_imv.height
    return (method_ranked,)


@app.cell
def _(mo):
    mo.md(
        """
        ## F.2 / F.3 — the threshold sweep

        `infusion_prep_minutes` cannot be defended from first principles at a single value.
        A loading bolus precedes its drip by minutes, but charting granularity, order-entry
        lag and pump documentation all widen the observed gap, and they widen it by
        different amounts at different sites. The sweep publishes the whole curve so the cut
        point is chosen against evidence; the configured value is one point on it and gets
        no special treatment in the file.

        A curve that has gone flat has stopped finding prep and started finding coincidence.

        Both frames carry `index_class`, so **the subsetting decision stays in `07`** where
        D20 puts it — this notebook still never decides who is in the analysis.
        """
    )
    return


@app.cell
def _(METHOD_ID, PHI_DIR, PREP_SWEEP_MINUTES, index_imv, med_window, pl):
    _after = pl.col("delta_minutes") > 0
    _before = pl.col("delta_minutes") < 0
    _strata = index_imv.select("intubation_episode_id", "index_class")

    _sweep, _by_drug = [], []
    for _thr in PREP_SWEEP_MINUTES:
        _prep = (
            _after
            & pl.col("lag_to_infusion_min").is_not_null()
            & (pl.col("lag_to_infusion_min") <= _thr)
        )
        # index_class lives in index_imv, not on the administration rows -- the bridge
        # deliberately carries only what the window filter needs (§7).
        _w = med_window.with_columns(_is_prep=_prep).join(
            _strata, on="intubation_episode_id", how="left"
        )

        # Episode-level detection at this threshold, recomputed from the UNRANKED set for
        # the reason spec 6.4 gives: filter, then rank.
        _det = (
            _w.filter(_before | (_after & ~pl.col("_is_prep")))
            .select("intubation_episode_id")
            .unique()
            .with_columns(_det=pl.lit(True))
        )
        _base = (
            med_window.filter(_before | _after)
            .select("intubation_episode_id")
            .unique()
            .with_columns(_base=pl.lit(True))
        )
        _ep = (
            _strata.join(_det, on="intubation_episode_id", how="left")
            .join(_base, on="intubation_episode_id", how="left")
            .with_columns(
                _det=pl.col("_det").fill_null(False), _base=pl.col("_base").fill_null(False)
            )
        )
        _sweep.append(
            _ep.group_by("index_class")
            .agg(
                n_episodes=pl.len(),
                n_detected=pl.col("_det").sum(),
                n_detected_all=pl.col("_base").sum(),
                n_flipped=(pl.col("_base") & ~pl.col("_det")).sum(),
            )
            .join(
                _w.filter(pl.col("_is_prep"))
                .group_by("index_class")
                .agg(n_doses_reclassified=pl.len()),
                on="index_class",
                how="left",
            )
            .with_columns(
                threshold_minutes=pl.lit(_thr, dtype=pl.Int32),
                n_doses_reclassified=pl.col("n_doses_reclassified").fill_null(0),
            )
        )
        _by_drug.append(
            _w.filter(_after)
            .group_by(["index_class", "med_category"])
            .agg(
                n_doses_after=pl.len(),
                n_doses_reclassified=pl.col("_is_prep").sum(),
            )
            .with_columns(threshold_minutes=pl.lit(_thr, dtype=pl.Int32))
        )

    prep_sweep = pl.concat(_sweep).select(
        "threshold_minutes", "index_class", "n_episodes", "n_detected_all",
        "n_detected", "n_flipped", "n_doses_reclassified",
    ).sort(["index_class", "threshold_minutes"])
    prep_by_drug = pl.concat(_by_drug).select(
        "threshold_minutes", "index_class", "med_category",
        "n_doses_after", "n_doses_reclassified",
    ).sort(["index_class", "med_category", "threshold_minutes"])

    # The curve must be monotone in the threshold: widening the window can only reclassify
    # MORE doses, so detections can only fall. A non-monotone curve means the per-threshold
    # recomputation is picking up something other than the threshold.
    _mono = (
        prep_sweep.sort(["index_class", "threshold_minutes"])
        .with_columns(_prev=pl.col("n_detected").shift(1).over("index_class"))
        .filter(pl.col("_prev").is_not_null() & (pl.col("n_detected") > pl.col("_prev")))
    )
    assert _mono.height == 0, (
        f"{_mono.height:,} sweep rows where a WIDER threshold detected MORE episodes. "
        "Reclassification is monotone by construction, so this is a bug in the loop."
    )

    prep_sweep.write_parquet(PHI_DIR / f"method_{METHOD_ID}_prep_sweep.parquet")
    prep_by_drug.write_parquet(PHI_DIR / f"method_{METHOD_ID}_prep_by_drug.parquet")

    print(f"method_{METHOD_ID}_prep_sweep.parquet    {prep_sweep.height:,} rows")
    print(f"method_{METHOD_ID}_prep_by_drug.parquet  {prep_by_drug.height:,} rows")
    print("\nsweep over the qualified stratum:")
    print(
        prep_sweep.filter(pl.col("index_class") == "qualified")
        .with_columns(rate=(pl.col("n_detected") / pl.col("n_episodes")).round(4))
        .select("threshold_minutes", "n_doses_reclassified", "n_detected", "rate", "n_flipped")
    )
    return


@app.cell
def _(METHOD_ID, PHI_DIR, method_episode, method_ranked, pl):
    _ep_path = PHI_DIR / f"method_{METHOD_ID}_episode.parquet"
    _json_path = PHI_DIR / f"method_{METHOD_ID}_ranked.json"

    # A stale _encounter.parquet from before D35 would still load in 07 and would silently
    # supply the wrong denominator, so its absence is asserted rather than assumed.
    _stale = PHI_DIR / f"method_{METHOD_ID}_encounter.parquet"
    assert not _stale.exists(), (
        f"{_stale.name} is present from the pre-D35 design. Delete it -- it holds one row "
        "per encounter and 07 must not find it."
    )

    method_episode.write_parquet(_ep_path)
    method_ranked.write_ndjson(_json_path)

    _detected = method_episode.filter(pl.col("detected"))
    _qual = method_episode.filter(pl.col("index_qualified"))
    _qual_detected = _qual.filter(pl.col("detected"))

    print(f"method_{METHOD_ID}_episode.parquet     {method_episode.height:,} rows -> {PHI_DIR}")
    print(f"method_{METHOD_ID}_ranked.json         {method_ranked.height:,} records")
    print()
    print(
        f"detection over ALL candidate episodes : {_detected.height:,} / "
        f"{method_episode.height:,}  ({100 * _detected.height / method_episode.height:.1f}%)"
    )
    print(
        f"detection over the INDEX set (N**)   : {_qual_detected.height:,} / "
        f"{_qual.height:,}  ({100 * _qual_detected.height / max(_qual.height, 1):.1f}%)"
    )
    _qi = _qual.filter(pl.col("detected_induction_only"))
    print(
        f"  ... of which INDUCTION ONLY (D40)  : {_qi.height:,} / "
        f"{_qual.height:,}  ({100 * _qi.height / max(_qual.height, 1):.1f}%)"
        f"   [gap {(_qual_detected.height - _qi.height):,} episodes]"
    )
    print("\ndetection rate by index_class (the Tier D input):")
    print(
        method_episode.group_by("index_class")
        .agg(n=pl.len(), rate=pl.col("detected").mean().round(3))
        .sort("n", descending=True)
    )
    print("\nnearest before-rank-1 agent, where one exists:")
    print(
        method_episode.filter(pl.col("nearest_before_med").is_not_null())
        .group_by("nearest_before_med")
        .agg(n=pl.len(), median_min=pl.col("nearest_before_min").median())
        .sort("n", descending=True)
    )
    return


if __name__ == "__main__":
    app.run()
