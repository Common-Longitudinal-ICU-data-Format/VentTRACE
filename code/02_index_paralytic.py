import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import polars as pl

    from clifpy.tables import MedicationAdminIntermittent

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return (
        MedicationAdminIntermittent,
        Path,
        json,
        mo,
        pl,
        publish,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 02 — the index paralytic

        ```
        rocuronium | succinylcholine | vecuronium
        ```

        The paralytic is the study's index event. This notebook does three things and
        touches exactly one CLIF table while doing them:

        | | |
        |---|---|
        | **A** | the distribution of gaps between paralytic administrations |
        | **B** | the 15-minute fold that turns administrations into **index paralytics** |
        | **C** | the distribution of gaps between index paralytics |

        A is published **before** B and depends on nothing B computes, so it reads as
        evidence for the 15-minute boundary rather than as a consequence of it. Fifteen
        minutes is a clinical definition and no empirical valley supports it — see spec P7,
        and read Figure A.1 rather than taking the number on trust.

        Design: `docs/superpowers/specs/2026-08-10-paralytic-index-design.md` §6, §7.1–7.3
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
    PHI_DIR.mkdir(parents=True, exist_ok=True)
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # P3. Lower case to match the lower-cased column (P20).
    PARALYTICS = ["rocuronium", "succinylcholine", "vecuronium"]
    # P4. 'bolus' is how many EHRs chart a one-time IV push, which is exactly what an
    # intubating paralytic is. Keeping 'given' alone risks a site reporting zero
    # paralytics, and zero is indistinguishable from a site that gives none.
    MAR_ACTIONS = ["given", "bolus"]

    COLLAPSE_GAP_MINUTES = config["collapse_gap_minutes"]

    # P11. An ANALYSIS grid, not a site parameter -- a site that changed its bins would
    # make its histogram non-comparable with every other site's, which is the one thing a
    # multi-site distribution is for. Constants here, deliberately not config keys.
    #
    # 13 breaks -> 14 cut bins; the exact-zero bin is carved out of the first, giving 15.
    # An exact zero gets its own bin because two agents charted on the same minute is the
    # single most informative value in the distribution and must not be pooled with
    # "under a minute".
    GAP_CUT_BREAKS = [1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 4320, 10080]
    GAP_CUT_LABELS = [
        "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]", "(15,30]", "(30,60]",
        "(1,2]h", "(2,6]h", "(6,12]h", "(12,24]h", "(1,3]d", "(3,7]d", ">7d",
    ]
    GAP_BIN_LABELS = ["0"] + GAP_CUT_LABELS

    # P9/P10 memory ceiling, NOT a clinical parameter. Ten million pairs of two floats and
    # two labels is roughly a 300 MB polars frame, about three orders of magnitude above
    # what MIMIC's paralytic density implies. A site that trips this has charting unlike
    # anything this design was checked against; the right response is to read the densest
    # blocks printed alongside and decide deliberately, not to raise the constant.
    MAX_TOTAL_PAIRS = 10_000_000

    print(f"site           : {SITE}")
    print(f"paralytics     : {' | '.join(PARALYTICS)}")
    print(f"mar actions    : {' | '.join(MAR_ACTIONS)}")
    print(f"collapse gap   : {COLLAPSE_GAP_MINUTES} min   (P6, P7)")
    print(f"gap bins       : {len(GAP_BIN_LABELS)}  {GAP_BIN_LABELS}")
    print(f"max pairs      : {MAX_TOTAL_PAIRS:,}")
    return (
        COLLAPSE_GAP_MINUTES,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        GAP_CUT_BREAKS,
        GAP_CUT_LABELS,
        GAP_BIN_LABELS,
        MAR_ACTIONS,
        MAX_TOTAL_PAIRS,
        PARALYTICS,
        PHI_DIR,
        SHARE_DIR,
        TIMEZONE,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ## Two timestamp helpers, and a guard against the old design's leftovers

        `to_site_naive` is the only correct way to turn a clifpy timestamp column into a
        naive site-local one. `epoch_minutes` is the only way this notebook is allowed to
        turn a timestamp into a number of minutes. Between them they are the whole timezone
        story, and the cell after them refuses to run if the superseded IMV-anchored
        design's artifacts are still sitting on disk waiting to be misread.
        """
    )
    return


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. `tz_convert` re-resolves against
        the tz database first. Pinned by `tests/test_clifpy_tz_boundary.py`.

        Defined locally, never imported (spec §4): a bug in a shared datetime helper
        corrupts every consumer identically, and identical corruption is the hardest kind
        to see.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def epoch_minutes(column="admin_dttm"):
        """Minutes since epoch, computed INSIDE polars, consulting no timezone at all.

        `datetime.timestamp()` on a site-naive value re-attaches the *machine's* zone. On
        a host set to US/Central holding US/Eastern data, ten minutes of wall clock across
        the November fall-back measures as seventy -- and seventy against a fifteen-minute
        fold splits one push of drug into two index paralytics, moving `t` for everything
        downstream. The answer would then depend on the laptop. Spec P19; pinned by
        `tests/test_collapse_agent_events.py`.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    return (epoch_minutes,)


@app.cell
def _(PHI_DIR):
    # A stale artifact from the superseded design still loads, still joins, and supplies
    # the wrong denominator without raising. Spec §12.
    _stale = [
        "index_imv.parquet",
        "method_SED_episode.parquet",
        "method_PARA_episode.parquet",
        "method_SED_ranked.json",
        "method_PARA_ranked.json",
        "method_PAIR_pairs.parquet",
    ]
    _present = [_n for _n in _stale if (PHI_DIR / _n).exists()]
    assert not _present, (
        f"artifacts from the superseded method-comparison design are present in "
        f"{PHI_DIR}: {_present}. Delete them -- they describe an IMV-anchored study and "
        "nothing in this pipeline should be able to read them."
    )
    print("no stale pre-overhaul artifacts present")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## The explode-and-drop bridge

        CLIF tables are keyed on `hospitalization_id`; this study is keyed on
        `encounter_block`. The bridge below is the **only** place this notebook may name a
        hospitalization, and the column is dropped the moment the join lands.

        That drop is a requirement, not tidiness (P5). If `hospitalization_id` survived
        into the gap computation, sub-analysis A would silently revert to the unstitched
        unit and a paralytic charted in the ED would never pair with one charted on the
        floor. Dropping the column makes that mistake impossible to write rather than
        merely discouraged.
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

    COHORT_RUN_ID = cohort_index.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"cohort_index carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    bridge = (
        cohort_index.select(["encounter_block", "patient_id", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    # The map must be many-to-one: one hospitalization belongs to exactly one block.
    # Asserted rather than assumed -- a duplicated key here fans out every administration
    # on the join below, and the fan-out is self-consistent, so every downstream count
    # would still agree with itself while being wrong.
    assert bridge.get_column("hospitalization_id").is_unique().all(), (
        "a hospitalization_id appears in more than one encounter_block"
    )

    print(f"cohort_run_id      : {COHORT_RUN_ID}")
    print(f"encounter blocks   : {cohort_index.height:,}")
    print(f"hospitalization ids: {len(bridge_hosp_ids):,}")
    return COHORT_RUN_ID, bridge, bridge_hosp_ids, cohort_index


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    MAR_ACTIONS,
    MedicationAdminIntermittent,
    PARALYTICS,
    TIMEZONE,
    bridge,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    # Filtered on hospitalization_id at load, but deliberately NOT on med_category. The
    # list is three values; filtering after lower-casing is both cheaper to reason about
    # and immune to the casing hole P20 exists to patch, since our own filter then runs on
    # a column we normalised ourselves.
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

    med_admin = (
        med_all.filter(
            pl.col("med_category").is_in(PARALYTICS)
            & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # the bridge ends here -- everything below is per block
    )

    assert "hospitalization_id" not in med_admin.columns, "the bridge leaked its key"

    # A category filter that matches nothing looks exactly like a site where the drug is
    # never given. Print what was actually found so the two are distinguishable, and fail
    # only if the whole list came back empty -- an individual agent may genuinely be absent
    # from a formulary; succinylcholine often is.
    _found = med_admin.group_by(["med_category", "mar_action_category"]).agg(n=pl.len())
    _missing = sorted(set(PARALYTICS) - set(med_admin.get_column("med_category").unique()))

    print(f"intermittent rows loaded : {med_all.height:,}")
    print(f"paralytic administrations: {med_admin.height:,}")
    print(f"  over encounter blocks  : {med_admin.get_column('encounter_block').n_unique():,}")
    print(f"  over patients          : {med_admin.get_column('patient_id').n_unique():,}")
    print(_found.sort("n", descending=True))
    if _missing:
        print(f"\nNOT PRESENT AT THIS SITE: {', '.join(_missing)}")
        print("  -> not an error, but every distribution below is computed without them")

    assert med_admin.height > 0, (
        "no administration matched the paralytic list at all. Either the site charts none "
        "of these agents, or the vocabulary differs -- compare the value_counts printed "
        "above against the mCIDE med_category list before trusting a zero."
    )
    return med_admin, med_all


@app.cell
def _(mo):
    mo.md(
        r"""
        ## B — the fold: anchor and close at 15 minutes

        ```
        first unconsumed row            ->  ANCHOR.  t := its admin_dttm
        every row within 15 min OF THE ANCHOR   ->  joins this index event
        first row beyond that           ->  new ANCHOR
        ```

        **Anchored, never chained (P6).** Chaining has no bound: an agent redosed every
        fourteen minutes walks one event forward indefinitely, and its timestamp then sits
        hours from most of its own doses — which destroys the clock sub-analyses C, D and E
        all measure against. Anchoring makes `span_minutes <= 15` an *assertable
        invariant* rather than a hope.

        Worked example:

        ```
         12:00  rocuronium        ANCHOR      index #1, t = 12:00
         12:10  vecuronium        <= 12:15    joins #1
         12:20  succinylcholine   >  12:15    ANCHOR   index #2, t = 12:20
         12:32  rocuronium        <= 12:35    joins #2
        ```

        The 12:20 row is within 15 minutes of the 12:10 row, and a transitive rule would
        have merged all four into one event spanning 32 minutes. Under P6 it does not.
        """
    )
    return


@app.cell
def _(COLLAPSE_GAP_MINUTES):
    def collapse_agent_events(times, categories, gap_limit_min):
        """Fold administrations into index events. Returns [[i, ...], ...] in time order.

        `times` is minutes-since-epoch as floats, ascending, all from one encounter. The
        invariant is that **no event spans more than `gap_limit_min`**: a row joins the
        current event only while it is within the limit of that event's FIRST row, and the
        moment it is strictly past it the row opens a new event and becomes the new anchor.
        Anchored, never chained -- the comparison is against `times[event[0]]` and never
        against `times[i - 1]`, so a steady drip of closely-spaced doses cannot walk an
        event forward without bound.

        Strictly greater, not greater-or-equal: a row exactly `gap_limit_min` past the
        anchor still merges, so the parameter reads as "within 15 minutes" inclusively.

        `categories` takes no part in the decision and is only length-checked. That is the
        point rather than an oversight: a repeat of one agent and a co-administration of
        two are the same clinical fact -- one push of paralytic -- and must fold the same
        way. Which agents were involved is recorded on the event afterwards by the caller,
        as `agent_label`.
        """
        n = len(times)
        assert len(categories) == n, "times and categories are not the same length"
        if n == 0:
            return []
        events = []
        current = [0]
        for i in range(1, n):
            if times[i] - times[current[0]] > gap_limit_min:
                events.append(current)
                current = [i]
            else:
                current.append(i)
        events.append(current)
        return events

    print(f"collapse window: {COLLAPSE_GAP_MINUTES:.0f} min")
    return (collapse_agent_events,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Driving the fold across the cohort

        One pass per encounter block, in the one sort order this notebook ever uses. The
        fold returns positions within the block; `positioned` carries the matching position
        back onto the administration rows so the two can be joined without sorting twice.

        The assertion at the end is the partition property: every administration that was
        loaded belongs to exactly one index paralytic, so the index set is a *partition* of
        the administration set rather than a filter on it.
        """
    )
    return


@app.cell
def _(COLLAPSE_GAP_MINUTES, collapse_agent_events, epoch_minutes, med_admin, pl):
    # Sorted by (admin_dttm, med_category): med_category breaks an exact-timestamp tie
    # alphabetically, so the fold -- and therefore every offset downstream -- is
    # byte-identical across runs.
    _sorted = med_admin.sort(["encounter_block", "admin_dttm", "med_category"]).with_columns(
        _t_min=epoch_minutes("admin_dttm")
    )

    _grouped = _sorted.group_by("encounter_block", maintain_order=True).agg(
        pl.col("_t_min"), pl.col("med_category"), _row=pl.int_range(pl.len())
    )

    _rows = []
    for _block, _times, _cats, _ in _grouped.iter_rows():
        for _n, _event in enumerate(
            collapse_agent_events(_times, _cats, COLLAPSE_GAP_MINUTES), start=1
        ):
            _rows.append(
                {
                    "encounter_block": _block,
                    "p_num": _n,
                    "_first_pos": _event[0],
                    "_last_pos": _event[-1],
                    "n_admins": len(_event),
                }
            )

    # A row index within the block lets the fold's positional output be joined back to the
    # administration rows without a second sort. The sort key above is the only ordering
    # this notebook ever uses.
    positioned = _sorted.with_columns(_pos=pl.int_range(pl.len()).over("encounter_block"))

    fold = pl.DataFrame(_rows).with_columns(
        index_paralytic_id=pl.concat_str(
            pl.col("encounter_block").cast(pl.String), pl.lit("_P"), pl.col("p_num").cast(pl.String)
        )
    )

    # Every administration belongs to exactly ONE index event: the index set is a partition
    # of the administration set, not a filter on it.
    assert fold.get_column("n_admins").sum() == med_admin.height, (
        f"the fold accounts for {fold.get_column('n_admins').sum():,} administrations but "
        f"{med_admin.height:,} were loaded -- the partition property is broken"
    )

    print(f"index paralytics : {fold.height:,}")
    print(f"  over blocks    : {fold.get_column('encounter_block').n_unique():,}")
    return fold, positioned


@app.cell
def _(mo):
    mo.md(
        """
        ### `index_paralytic` — one row per index event

        Each administration is attached to its event, the event's first administration
        supplies `t_dttm`, and every other administration is recorded relative to it as an
        `offset_minutes` inside `doses`. The three assertions below are P6's invariant
        (`span_minutes <= 15`), uniqueness of the id, and `p_num` running contiguously from
        1 within each block — the three ways this frame could be quietly wrong.
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, COLLAPSE_GAP_MINUTES, positioned, cohort_index, fold, pl):
    # Attach every administration to its index event, then aggregate.
    _members = (
        positioned.join(
            fold.select("encounter_block", "index_paralytic_id", "p_num", "_first_pos", "_last_pos"),
            on="encounter_block",
            how="inner",
        )
        .filter(
            (pl.col("_pos") >= pl.col("_first_pos")) & (pl.col("_pos") <= pl.col("_last_pos"))
        )
    )

    _anchor = _members.filter(pl.col("_pos") == pl.col("_first_pos")).select(
        "index_paralytic_id", t_dttm="admin_dttm", _t0_min="_t_min"
    )

    index_paralytic = (
        _members.join(_anchor, on="index_paralytic_id", how="inner")
        .with_columns(offset_minutes=(pl.col("_t_min") - pl.col("_t0_min")).round(3))
        .group_by(["encounter_block", "index_paralytic_id", "p_num", "t_dttm"], maintain_order=True)
        .agg(
            n_admins=pl.len(),
            span_minutes=(pl.col("_t_min").max() - pl.col("_t_min").min()).round(3),
            agents=pl.col("med_category").unique().sort(),
            doses=pl.struct(
                med_category="med_category",
                med_dose="med_dose",
                med_dose_unit="med_dose_unit",
                mar_action_category="mar_action_category",
                offset_minutes="offset_minutes",
            ),
        )
        .with_columns(
            n_agents=pl.col("agents").list.len().cast(pl.Int32),
            is_coadmin=pl.col("n_admins") > 1,
            agent_label=pl.col("agents").list.join("+"),
            cohort_run_id=pl.lit(COHORT_RUN_ID),
        )
        .join(cohort_index.select("encounter_block", "patient_id"), on="encounter_block", how="left")
        .select(
            "index_paralytic_id",
            "encounter_block",
            "patient_id",
            "cohort_run_id",
            "p_num",
            "t_dttm",
            "n_admins",
            "span_minutes",
            "is_coadmin",
            "agents",
            "n_agents",
            "agent_label",
            "doses",
        )
        .sort(["encounter_block", "p_num"])
    )

    # P6's invariant, asserted rather than hoped for. A violation means the fold chained.
    _over = index_paralytic.filter(pl.col("span_minutes") > COLLAPSE_GAP_MINUTES)
    assert _over.height == 0, (
        f"{_over.height:,} index paralytics span more than {COLLAPSE_GAP_MINUTES} min. "
        "collapse_agent_events anchors on the event's first row; a violation here means it "
        "chained off the previous row instead."
    )
    assert index_paralytic.get_column("index_paralytic_id").is_unique().all()
    assert index_paralytic.get_column("patient_id").null_count() == 0, (
        "an index paralytic has no patient -- a block in med_admin is absent from cohort_index"
    )
    _gap = index_paralytic.filter(
        pl.col("p_num") != pl.col("p_num").cum_count().over("encounter_block")
    )
    assert _gap.height == 0, "p_num is not contiguous from 1 within a block"

    print(f"index paralytics : {index_paralytic.height:,}")
    print(f"  co-administrations : {index_paralytic.get_column('is_coadmin').sum():,} "
          f"({100 * index_paralytic.get_column('is_coadmin').mean():.1f}%)")
    print(f"  max span (min)     : {index_paralytic.get_column('span_minutes').max()}")
    print(index_paralytic.group_by("agent_label").agg(n=pl.len()).sort("n", descending=True))
    return (index_paralytic,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Output

        `index_paralytic.parquet` is the spine every later notebook joins to. It carries
        PHI — `t_dttm` is a real timestamp — so it is written to `intermediate_phi` and
        never published.
        """
    )
    return


@app.cell
def _(PHI_DIR, index_paralytic):
    _path = PHI_DIR / "index_paralytic.parquet"
    index_paralytic.write_parquet(_path)
    print(f"index_paralytic.parquet   {index_paralytic.height:,} rows -> {_path}")
    return


if __name__ == "__main__":
    app.run()
