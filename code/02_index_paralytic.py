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
    MAR_ACTIONS = ["given"]
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
    # Clinical plausibility limits for configured absolute-unit dose summaries.
    # only 0 < dose < upper bound contributes. Ketamine is intentionally absent because
    # the study lead supplied no threshold for it.
    DOSE_SUMMARY_UPPER_BOUNDS = {
        "etomidate": 200.0,
        "fentanyl": 500.0,
        "midazolam": 50.0,
        "propofol": 500.0,
        "rocuronium": 400.0,
        "succinylcholine": 400.0,
        "vecuronium": 30.0,
    }
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
    print(f"configured units: {MEDICATION_DOSE_UNITS}")
    print(f"summary bounds : {DOSE_SUMMARY_UPPER_BOUNDS}")
    return (
        COLLAPSE_GAP_MINUTES,
        DATA_DIR,
        DOSE_SUMMARY_UPPER_BOUNDS,
        FIG_DIR,
        FILETYPE,
        GAP_CUT_BREAKS,
        GAP_CUT_LABELS,
        GAP_BIN_LABELS,
        MAR_ACTIONS,
        MAX_TOTAL_PAIRS,
        MEDICATION_DOSE_UNITS,
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
def _():
    def to_site_naive(series):
        """Strip clifpy's configured site timezone while preserving local wall time.

        `from_file(..., timezone=TIMEZONE)` has already normalized every timestamp to the
        site timezone, so converting it again here would duplicate clifpy's work.

        Defined locally, never imported (spec §4): a bug in a shared datetime helper
        corrupts every consumer identically, and identical corruption is the hardest kind
        to see.
        """
        return series.dt.tz_localize(None)

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
    cohort_index = pl.read_parquet(PHI_DIR / "step01__cohort_index.parquet")

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
    MEDICATION_DOSE_UNITS,
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
        # P20's posture, applied to med_dose_unit too: a site charting `MG` beside `mg`
        # would otherwise fail an exact configured-unit match. Normalised once here so
        # every downstream consumer agrees.
        med_dose_unit=pl.col("med_dose_unit").str.strip_chars().str.to_lowercase(),
    )

    # Vocabulary probe: computed on `med_category` alone, BEFORE the mar_action_category
    # filter below. Filtering first and reporting after (the original bug here) makes a
    # site charting an unlisted action -- "administered", "iv push", "new bag", a null --
    # indistinguishable from a genuinely absent agent, and an agent present only under
    # such an action would print as "NOT PRESENT AT THIS SITE", which is wrong. Reporting
    # on the pre-filter frame is the only way a vocabulary mismatch can be told apart from
    # genuine absence (spec §4).
    _paralytic_all = med_all.filter(pl.col("med_category").is_in(PARALYTICS))
    _configured_unit = pl.col("med_category").replace_strict(MEDICATION_DOSE_UNITS)
    _wrong_unit_rows = _paralytic_all.filter(
        ~pl.col("med_dose_unit").eq_missing(_configured_unit)
    )
    _configured_paralytic_all = _paralytic_all.filter(
        pl.col("med_dose_unit") == _configured_unit
    )
    _seen = _paralytic_all.group_by(["med_category", "mar_action_category"]).agg(n=pl.len())
    _missing = sorted(
        set(PARALYTICS) - set(_paralytic_all.get_column("med_category").unique())
    )
    _dropped_by_action_filter = (
        _configured_paralytic_all.group_by("med_category")
        .agg(n_total=pl.len())
        .join(
            _configured_paralytic_all.filter(
                pl.col("mar_action_category").is_in(MAR_ACTIONS)
            )
            .group_by("med_category")
            .agg(n_kept=pl.len()),
            on="med_category",
            how="left",
        )
        .with_columns(n_kept=pl.col("n_kept").fill_null(0))
        .with_columns(n_dropped=pl.col("n_total") - pl.col("n_kept"))
        .sort("n_dropped", descending=True)
    )

    med_admin = (
        _configured_paralytic_all.filter(
            pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # the bridge ends here -- everything below is per block
    )

    assert "hospitalization_id" not in med_admin.columns, "the bridge leaked its key"

    # Post-filter reporting, kept alongside the pre-filter probe above -- this is what
    # actually feeds every downstream distribution, so it stays visible too.
    _found = med_admin.group_by(["med_category", "mar_action_category"]).agg(n=pl.len())

    print(f"intermittent rows loaded : {med_all.height:,}")
    print(f"wrong-unit rows skipped  : {_wrong_unit_rows.height:,}")
    if _wrong_unit_rows.height:
        print(
            _wrong_unit_rows.group_by(["med_category", "med_dose_unit"])
            .agg(n=pl.len())
            .sort("n", descending=True)
        )
    print(f"paralytic administrations: {med_admin.height:,}")
    print(f"  over encounter blocks  : {med_admin.get_column('encounter_block').n_unique():,}")
    print(f"  over patients          : {med_admin.get_column('patient_id').n_unique():,}")
    print("\nvalue_counts seen, by (med_category, mar_action_category), BEFORE the action filter:")
    print(_seen.sort("n", descending=True))
    print("\nrows dropped by the mar_action_category filter, per agent:")
    print(_dropped_by_action_filter)
    print("\nvalue_counts, by (med_category, mar_action_category), AFTER unit/action filters:")
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
        ## A — the paralytic administration gap distribution

        Every **unordered pair** of paralytic administrations inside an `encounter_block`,
        same-agent pairs included (P9). This is the evidence for the fifteen-minute
        boundary, and it is computed here — before the fold — so that it depends on
        nothing the fold decides.

        The same/cross split is the point of the table. `rocuronium → rocuronium` at three
        minutes is a **redose**; `rocuronium → succinylcholine` at three minutes is a
        **co-administration**. The pooled histogram cannot tell them apart, and they
        justify the boundary for different reasons.

        The 7-day cap is a **bin, not a filter** (P10). A filter would make the histogram's
        own denominator depend on the cap, so two sites with different long-stay mixes
        would not be comparable even on the short bins.
        """
    )
    return


@app.cell
def _(GAP_CUT_BREAKS, GAP_CUT_LABELS, pl):
    def gap_bin_expr(col="gap_minutes"):
        """Assign a gap in minutes to one of the 15 named bins.

        Every interval is left-open and right-closed -- (a, b] -- so a gap of exactly 15
        minutes lands in `(10,15]` and 15.0001 lands in `(15,30]`. That edge is the line
        the fold is drawn at, and putting a value on the wrong side of it would make
        Figure A.1 disagree with the boundary it is evidence for.

        An exact zero is carved out of the first cut bin and given its own label: two
        agents charted on the same minute is the single most informative value in this
        distribution and pooling it with "under a minute" would hide it.
        """
        return (
            pl.when(pl.col(col) == 0)
            .then(pl.lit("0"))
            .otherwise(
                pl.col(col).cut(GAP_CUT_BREAKS, labels=GAP_CUT_LABELS).cast(pl.String)
            )
            .alias("gap_bin")
        )

    return (gap_bin_expr,)


@app.cell
def _(epoch_minutes, pl):
    def all_pair_gaps(df, time_col="admin_dttm", agent_col="med_category"):
        """Every unordered pair within each encounter_block. O(n^2) per block, by design.

        Adjacent-only pairing would miss `roc 12:00 ... vec 12:10` whenever anything is
        charted between them, and the sub-15-minute mass is exactly where the threshold
        decision lives (P9).

        The join is on `encounter_block` and nothing else, so a pair can never span two
        blocks. `_i < _i_r` takes each unordered pair once. The agent label is the two
        agents sorted alphabetically and joined with `+`, so one pair is one row rather
        than two orderings of itself.

        Returns encounter_block, gap_minutes, agent_pair, is_same_agent.
        """
        indexed = (
            df.sort(["encounter_block", time_col, agent_col])
            .with_row_index("_i")
            .select(
                "encounter_block",
                "_i",
                _t=epoch_minutes(time_col),
                _a=pl.col(agent_col),
            )
        )
        return (
            indexed.join(indexed, on="encounter_block", how="inner", suffix="_r")
            .filter(pl.col("_i") < pl.col("_i_r"))
            .select(
                "encounter_block",
                gap_minutes=(pl.col("_t_r") - pl.col("_t")).abs().round(3),
                agent_pair=pl.concat_str(
                    pl.min_horizontal("_a", "_a_r"),
                    pl.lit("+"),
                    pl.max_horizontal("_a", "_a_r"),
                ),
                is_same_agent=pl.col("_a") == pl.col("_a_r"),
            )
        )

    return (all_pair_gaps,)


@app.cell
def _(MAX_TOTAL_PAIRS, all_pair_gaps, gap_bin_expr, med_admin, pl):
    _per_block = med_admin.group_by("encounter_block").agg(n=pl.len())
    _expected = (_per_block.get_column("n") * (_per_block.get_column("n") - 1) // 2).sum()

    print(f"administrations per block: max {_per_block.get_column('n').max():,}, "
          f"median {_per_block.get_column('n').median()}")
    print("ten densest blocks:")
    print(_per_block.sort("n", descending=True).head(10))
    print(f"pairs to enumerate       : {_expected:,}")

    # A MEMORY ceiling, not a clinical one. A site that trips this has charting unlike
    # anything this design was checked against; read the densest blocks above and decide
    # deliberately rather than raising the constant.
    assert _expected <= MAX_TOTAL_PAIRS, (
        f"{_expected:,} pairs exceeds MAX_TOTAL_PAIRS ({MAX_TOTAL_PAIRS:,}). This is a "
        "memory guard, not a study parameter -- inspect the densest blocks printed above "
        "before changing it."
    )

    coadmin_pairs = all_pair_gaps(med_admin).with_columns(gap_bin_expr())
    assert coadmin_pairs.height == _expected, (
        f"enumerated {coadmin_pairs.height:,} pairs but expected {_expected:,} -- the join "
        "either crossed an encounter_block boundary or double-counted an unordered pair"
    )
    assert coadmin_pairs.get_column("gap_bin").null_count() == 0, "a gap fell outside every bin"
    return (coadmin_pairs,)


@app.cell
def _(SHARE_DIR, med_admin, pl, publish):
    # n_administrations was dropped by 42cc70f to close a subtraction leak against
    # step02__index_paralytic_dose_summary.csv under the old n>=10 cell rule.
    # P24-withdrawn restores it:
    # under P21 an aggregate count is published at its true value regardless of size, so
    # there is no residual left to be recoverable by subtraction.
    admin_summary = (
        med_admin.group_by(["med_category", "mar_action_category"])
        .agg(
            n_administrations=pl.len(),
            n_blocks=pl.col("encounter_block").n_unique(),
            n_patients=pl.col("patient_id").n_unique(),
        )
        .sort(["med_category", "mar_action_category"])
    )
    publish(
        admin_summary,
        SHARE_DIR / "step02__paralytic_administration_summary.csv",
        "step02__paralytic_administration_summary",
    )
    return (admin_summary,)


@app.cell
def _(GAP_BIN_LABELS, SHARE_DIR, coadmin_pairs, pl, publish):
    # Every bin, at its true count (P21) -- there is no bin-mode partition. The zero bins
    # are published explicitly rather than left absent, exactly as the rest of the
    # pipeline publishes zeros: "this never happened" and "this is missing" are different
    # statements.
    _rows = []
    for _order, _bin in enumerate(GAP_BIN_LABELS):
        _bin_pairs = coadmin_pairs.filter(pl.col("gap_bin") == _bin)
        _n_pooled = _bin_pairs.height
        _n_cross = int((~_bin_pairs.get_column("is_same_agent")).sum()) if _n_pooled else 0
        _n_same = _n_pooled - _n_cross
        _rows.append(
            {
                "bin_order": _order,
                "gap_bin": _bin,
                "n_pooled": _n_pooled,
                "n_same_agent": _n_same,
                "n_cross_agent": _n_cross,
            }
        )

    gap_distribution = pl.DataFrame(_rows)
    publish(
        gap_distribution,
        SHARE_DIR / "fig_A1__paralytic_administration_pair_gaps.csv",
        "fig_A1__paralytic_administration_pair_gaps",
    )

    # Every observed agent_pair, in EVERY bin -- not just the bins it was observed in.
    # A plain group_by only emits observed (agent_pair, gap_bin) combinations, which
    # silently drops a pair's zero bins from the table entirely rather than publishing
    # them (the same principle the sibling table above already follows). Cross-joining
    # the observed pairs against the full bin grid and filling nulls to 0 makes every
    # pair x bin combination present.
    _bin_grid = pl.DataFrame({"gap_bin": GAP_BIN_LABELS}).with_row_index("bin_order")
    _observed_pairs = coadmin_pairs.select("agent_pair").unique()
    gap_by_pair = (
        _observed_pairs.join(_bin_grid, how="cross")
        .join(
            coadmin_pairs.group_by(["agent_pair", "gap_bin"]).agg(n=pl.len()),
            on=["agent_pair", "gap_bin"],
            how="left",
        )
        .with_columns(pl.col("n").fill_null(0))
        .sort(["agent_pair", "bin_order"])
    )
    publish(
        gap_by_pair,
        SHARE_DIR / "step02__paralytic_pair_gaps_by_agent_pair.csv",
        "step02__paralytic_pair_gaps_by_agent_pair",
    )

    return gap_by_pair, gap_distribution


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
        pl.col("_t_min"), pl.col("med_category")
    )

    _rows = []
    for _block, _times, _cats in _grouped.iter_rows():
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
        `offset_minutes` inside `doses`. The assertions below are the partition property
        re-checked on the *rebuilt* frame (`sum(n_admins)` still equals the number of
        administrations loaded), P6's invariant (`span_minutes <= 15`), uniqueness of the
        id, every event having a patient, and `p_num` running contiguously from 1 within
        each block — the ways this frame could be quietly wrong.
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, COLLAPSE_GAP_MINUTES, positioned, cohort_index, fold, med_admin, pl):
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

    # The partition property again, and this time on the frame that is actually written.
    # The identical assertion in the cell above checks the fold's own arithmetic, which is
    # pure Python and already covered by tests/test_collapse_agent_events.py. This one
    # checks the polars RECONSTRUCTION above it -- the join on encounter_block followed by
    # the _pos range filter -- which is where an administration can silently be lost or
    # counted twice. Nothing else in this cell would notice: the span check only bounds
    # spans, is_unique only checks ids, and the p_num check below catches an event that
    # vanished whole, not one that quietly lost half its rows.
    _rebuilt = index_paralytic.get_column("n_admins").sum()
    assert _rebuilt == med_admin.height, (
        f"the reconstruction accounts for {_rebuilt:,} administrations but {med_admin.height:,} "
        "were loaded. The fold itself balanced, so the loss or duplication is in the "
        "positioned/fold join and the _pos range filter above -- every dose count, offset "
        "and agent_label built from those rows is wrong by an unknown amount."
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
    _path = PHI_DIR / "step02__index_paralytic.parquet"
    index_paralytic.write_parquet(_path)
    print(f"step02__index_paralytic.parquet   {index_paralytic.height:,} rows -> {_path}")
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## C — the gap between index paralytics

        The same construction as A, applied to index paralytics instead of raw
        administrations: all unordered pairs within a block, the identical bin grid, the
        identical overflow bin.

        By construction C has **zero mass in every bin up to and including `(10,15]`**, and
        the bound is strict rather than approximate. An anchor at `t` closes at `t + 15`
        inclusive, so the next anchor is the first administration *strictly after* `t + 15`;
        consecutive index paralytics are therefore always more than 15 minutes apart, and
        every non-consecutive pair is wider still.

        The assertion below is the cheapest possible test that P6 was implemented as
        written. A non-zero count in those six bins is a bug in the fold, not a finding.
        """
    )
    return


@app.cell
def _(all_pair_gaps, gap_bin_expr, index_paralytic, pl):
    _EMPTY_BY_CONSTRUCTION = ["0", "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]"]

    index_pairs = all_pair_gaps(
        index_paralytic.select("encounter_block", "t_dttm", "agent_label"),
        time_col="t_dttm",
        agent_col="agent_label",
    ).with_columns(gap_bin_expr())

    _violations = index_pairs.filter(pl.col("gap_bin").is_in(_EMPTY_BY_CONSTRUCTION))
    assert _violations.height == 0, (
        f"{_violations.height:,} pairs of index paralytics are 15 minutes apart or less. "
        "The fold closes at t+15 inclusive, so the next anchor is strictly after it and "
        "these bins cannot be reached. This is a bug in collapse_agent_events, not a finding."
    )

    print(f"index pairs constructed : {index_pairs.height:,}")
    print("P6 floor holds: zero pairs at or below 15 minutes")
    return (index_pairs,)


@app.cell
def _(mo):
    mo.md(
        """
        ### The inter-index gap histogram

        `index_pairs` is counted into the identical 15-bin grid A uses, so the two
        histograms are directly comparable bin-for-bin (Figure C.1 draws exactly this
        comparison). Every bin is published here, including the empty ones -- an explicit
        published zero is what lets the read-back check confirm the floor rather than
        merely imply it from a missing row.
        """
    )
    return


@app.cell
def _(GAP_BIN_LABELS, SHARE_DIR, index_pairs, pl, publish):
    _counts = index_pairs.group_by("gap_bin").agg(n=pl.len())
    index_gap_distribution = (
        pl.DataFrame({"gap_bin": GAP_BIN_LABELS})
        .with_row_index("bin_order")
        .join(_counts, on="gap_bin", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .sort("bin_order")
    )
    publish(
        index_gap_distribution,
        SHARE_DIR / "fig_C1__index_paralytic_pair_gaps.csv",
        "fig_C1__index_paralytic_pair_gaps",
    )
    return (index_gap_distribution,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Index paralytics per block

        A block with two or more index paralytics is a block where the paralytic was
        re-dosed (or a different agent started) more than 15 minutes after the last one --
        the structure C's gap histogram is measuring the spacing of. `index_per_block`
        counts blocks by how many index paralytics they contain.
        """
    )
    return


@app.cell
def _(SHARE_DIR, index_paralytic, pl, publish):
    _observed = (
        index_paralytic.group_by("encounter_block")
        .agg(n_index=pl.len())
        .group_by("n_index")
        .agg(n_blocks=pl.len())
    )
    # Contiguous from 1 to the observed maximum: a value that never occurred (e.g. every
    # block has either 8, 10 or 12 index paralytics but never 9 or 11) is published as an
    # explicit zero rather than being absent from the table -- the same principle every
    # other bin grid in this pipeline follows.
    _max_index = int(_observed.get_column("n_index").max())
    index_per_block = (
        pl.DataFrame({"n_index": list(range(1, _max_index + 1))})
        .with_columns(pl.col("n_index").cast(pl.Int32))
        .join(_observed, on="n_index", how="left")
        .with_columns(pl.col("n_blocks").fill_null(0))
        .sort("n_index")
    )
    publish(
        index_per_block,
        SHARE_DIR / "step02__index_paralytics_per_block.csv",
        "step02__index_paralytics_per_block",
    )
    return (index_per_block,)


@app.cell
def _(mo):
    mo.md(
        """
        ### The index paralytic summary, by agent

        One row per `agent_label` -- the sorted, `+`-joined set of agents folded into an
        index event. At a site where every multi-administration index event is a
        same-agent redose (no cross-agent co-administration survives the fold), this table
        has exactly one row per agent actually charted; that is a site fact, not a defect
        in the aggregation.
        """
    )
    return


@app.cell
def _(SHARE_DIR, index_paralytic, pl, publish):
    index_summary = (
        index_paralytic.group_by("agent_label")
        .agg(
            n_index=pl.len(),
            n_blocks=pl.col("encounter_block").n_unique(),
            n_patients=pl.col("patient_id").n_unique(),
            n_coadmin=pl.col("is_coadmin").sum(),
            median_span_min=pl.col("span_minutes").median(),
            max_span_min=pl.col("span_minutes").max(),
        )
        # agent_label is the tiebreak, not decoration: polars' sort is unstable, so two
        # agents with equal n_index would swap places between runs and the published CSV
        # would stop being byte-identical (spec §6.4). Every published table sorted on a
        # non-unique key carries a tiebreak for this reason.
        .sort(["n_index", "agent_label"], descending=[True, False])
    )
    publish(
        index_summary,
        SHARE_DIR / "step02__index_paralytic_summary.csv",
        "step02__index_paralytic_summary",
    )
    return (index_summary,)


@app.cell
def _(mo):
    mo.md(
        """
        ### The composition of an index event

        `n_admins` and `n_agents` answer two different questions and are published as
        separate columns because at some sites they diverge and at others they do not.

        - `n_admins` is how many pushes the fold absorbed. `n_admins == 1` is a **solo**
          index paralytic; anything above it is a multi-administration event.
        - `n_agents` is how many *distinct* drugs those pushes were. `n_agents > 1` is a
          genuine **co-administration**; `n_agents == 1` with `n_admins > 1` is a
          **redose** of one agent inside the fold window.

        A site can have hundreds of multi-administration events and zero
        co-administrations, and the distinction changes what the fifteen-minute window is
        doing there. Reporting only `is_coadmin` (defined as `n_admins > 1`) would call
        both cases co-administration and hide that.

        Only observed combinations are emitted. Unlike the gap bins and the agent-pair
        grid, `n_admins` has no upper bound to build a grid from, so an absent row means
        no index event had that shape rather than a suppressed count.
        """
    )
    return


@app.cell
def _(SHARE_DIR, index_paralytic, pl, publish):
    # Grouped on (n_admins, n_agents), which are the group keys and therefore jointly
    # unique -- no tiebreak is needed for the sort to be byte-identical across runs.
    index_composition = (
        index_paralytic.group_by(["n_admins", "n_agents"])
        .agg(
            n_index=pl.len(),
            n_administrations=pl.col("n_admins").sum(),
            n_blocks=pl.col("encounter_block").n_unique(),
            n_patients=pl.col("patient_id").n_unique(),
        )
        .sort(["n_admins", "n_agents"])
    )
    publish(
        index_composition,
        SHARE_DIR / "step02__index_paralytic_composition.csv",
        "step02__index_paralytic_composition",
    )

    _solo = index_composition.filter(pl.col("n_admins") == 1).get_column("n_index").sum()
    _multi = index_composition.filter(pl.col("n_admins") > 1).get_column("n_index").sum()
    _coadmin = index_composition.filter(pl.col("n_agents") > 1).get_column("n_index").sum()
    print(f"solo index paralytics   : {_solo:,}")
    print(f"multi-administration    : {_multi:,}")
    print(f"  of which co-administration (2+ distinct agents): {_coadmin:,}")
    return (index_composition,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Configured-unit dose boundary

        Every administration already passed the exact configured-unit filter before it
        could define an event. Dose summaries retain that numeric value and unit without
        conversion or relabeling. Rows without a finite dose remain in administration
        counts and raw-unit QC but cannot contribute a dose statistic.
        """
    )
    return


@app.cell
def _(pl):
    def prepare_configured_doses(df, configured_units):
        """Keep finite doses in their exact configured unit without conversion."""
        _usable = df.filter(
            pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & pl.col("med_dose_unit").is_not_null()
        )
        _dropped = df.height - _usable.height
        if _dropped:
            print(
                f"  [dose summary] {_dropped:,} row(s) excluded for a null or "
                "non-finite med_dose, or a null med_dose_unit"
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

    return (prepare_configured_doses,)


@app.cell
def _(pl):
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

        _checked = df.with_columns(
            _upper_bound.alias("_summary_upper_bound"),
        ).with_columns(
            pl.when(pl.col("med_dose_converted") <= 0)
            .then(pl.lit("non_positive_dose"))
            .when(
                pl.col("_summary_upper_bound").is_not_null()
                & ~_raw_unit.str.ends_with("/kg")
                & (pl.col("med_dose_converted") >= pl.col("_summary_upper_bound"))
            )
            .then(pl.lit("at_or_above_upper_bound"))
            .otherwise(None)
            .alias("_summary_exclusion_reason")
        )

        _excluded = (
            _checked.filter(pl.col("_summary_exclusion_reason").is_not_null())
            .group_by(["med_category", "med_dose_unit", "_summary_exclusion_reason"])
            .agg(n=pl.len())
            .sort(["med_category", "med_dose_unit", "_summary_exclusion_reason"])
        )
        if _excluded.height:
            print("DOSE SUMMARY exclusions (raw QC outputs retain these rows):")
            print(_excluded)

        return _checked.filter(
            pl.col("_summary_exclusion_reason").is_null()
        ).drop(
            "_summary_upper_bound",
            "_summary_exclusion_reason",
        )

    return (filter_doses_for_summary,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Dose statistics in the configured unit

        Each agent contributes only administrations whose normalized charted unit exactly
        matches `config["medication_dose_units"]`. Values and units are not converted or
        relabeled. The companion raw-unit count therefore documents the selected analysis
        population rather than pooling heterogeneous units.
        """
    )
    return


@app.cell
def _(SHARE_DIR, index_paralytic):
    (SHARE_DIR / "step02__paralytic_dose_unit_corrections.csv").unlink(
        missing_ok=True
    )
    raw_doses = index_paralytic.explode("doses").unnest("doses")
    return (raw_doses,)


@app.cell
def _(
    DOSE_SUMMARY_UPPER_BOUNDS,
    filter_doses_for_summary,
    MEDICATION_DOSE_UNITS,
    pl,
    prepare_configured_doses,
    raw_doses,
):
    _before = (
        raw_doses.group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.len(), median_dose=pl.col("med_dose").median())
        .sort(["med_category", "med_dose_unit"])
    )
    print("Configured doses -- n and median per (med_category, med_dose_unit):")
    print(_before)

    dose_converted = prepare_configured_doses(
        raw_doses, MEDICATION_DOSE_UNITS
    )

    dose_summary_clean = filter_doses_for_summary(
        dose_converted,
        DOSE_SUMMARY_UPPER_BOUNDS,
    )

    return dose_converted, dose_summary_clean


@app.cell
def _(SHARE_DIR, dose_summary_clean, pl, publish):
    # interpolation="linear" on both quantiles, explicitly: polars' default is
    # "nearest", which at small n republishes a raw charted dose verbatim as the
    # statistic (n=3 -> p75 IS the largest of the three charted values). Linear
    # interpolation does not avoid that outcome, it only changes when it happens:
    # polars places the q-th quantile of n sorted values at the fractional index
    # (n-1)*q, and whenever that index is a whole number the "interpolated" value
    # IS one of the charted observations -- not a rare edge case, but guaranteed
    # whenever (n-1) is a multiple of 4, since p25, median and p75 then land at
    # indices (n-1)/4, (n-1)/2 and 3(n-1)/4 all at once. That is live in this
    # pipeline: ketamine's sedation dose (n=13, see fig_E2__sedation_dose_summary.csv / 03) publishes
    # p25/median/p75 as three specific charted doses, not synthesised values. Linear
    # interpolation buys smoother behaviour as n changes; it does not buy a guarantee
    # of never equaling an individual observation.
    index_dose = (
        dose_summary_clean.group_by("med_category")
        .agg(
            n=pl.len(),
            n_in_configured_unit=(
                pl.col("med_dose_unit") == pl.col("med_dose_unit_converted")
            ).sum(),
            mean_dose=pl.col("med_dose_converted").mean(),
            sd_dose=pl.col("med_dose_converted").std(),
            median_dose=pl.col("med_dose_converted").median(),
            p25_dose=pl.col("med_dose_converted").quantile(0.25, interpolation="linear"),
            p75_dose=pl.col("med_dose_converted").quantile(0.75, interpolation="linear"),
            med_dose_unit=pl.col("med_dose_unit_converted").first(),
        )
        .sort("med_category")
    )
    publish(
        index_dose,
        SHARE_DIR / "step02__index_paralytic_dose_summary.csv",
        "step02__index_paralytic_dose_summary",
    )
    return (index_dose,)


@app.cell
def _(SHARE_DIR, pl, publish, raw_doses):
    # Counts only, in the one configured unit retained for each medication.
    paralytic_dose_units = (
        raw_doses.group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.len())
        .sort(["med_category", "n"], descending=[False, True])
    )
    publish(
        paralytic_dose_units,
        SHARE_DIR / "step02__paralytic_dose_raw_unit_counts.csv",
        "step02__paralytic_dose_raw_unit_counts",
    )
    return (paralytic_dose_units,)


@app.cell
def _(mo):
    mo.md(
        """
        ### The whole dose distribution, on the unit the site actually charted

        P18/P43 publish mean, SD and three quantiles in the configured unit. The
        three quantiles are thinner than the data supports, and the cell above says why
        in its own margin: polars
        places the q-th quantile at fractional index `(n-1)*q`, so whenever `(n-1)` is
        a multiple of 4 the published p25, median and p75 **are** three charted doses
        rather than statistics computed from them.

        P41 publishes the distribution instead of three points standing in for it: for
        every `(med_category, med_dose_unit)` pair, one row per distinct charted dose,
        carrying how many administrations sat at it, the running count and the
        cumulative proportion. Any quantile, any threshold count and any cross-site
        pooled distribution is recoverable from that, so nobody has to ask a site to
        re-run for a statistic that was not thought of first.

        Keyed on the configured charted unit. Other units were excluded before event
        construction and cannot enter this distribution.

        `n_total` equals `step02__paralytic_dose_raw_unit_counts.csv`'s `n` for fully dosed groups. A
        null-dose group remains in the counts table but has no ECDF position; that
        difference is printed explicitly.
        """
    )
    return


@app.cell
def _(pl):
    def ecdf_by_group(df):
        """Empirical CDF of `med_dose` within each (med_category, med_dose_unit) group.

        `df` needs `med_category`, `med_dose_unit` and `med_dose`; any other column is
        ignored. Returns one row per distinct charted dose with `n_at_dose`, `n_cum`,
        `n_total` and `ecdf`, sorted (med_category, med_dose_unit, dose) ascending.

        The RAW charted unit and dose are read, never `med_dose_unit_converted` /
        `med_dose_converted` -- both pairs are present on the frames this is called
        with, and P41 is defined on the raw pair.

        Rate-charted rows cannot appear here: they are filtered upstream, before the
        bridge join, so every frame reaching this function is amount-only already
        (commit 305de1f). This function must not re-assert that -- a second filter
        would be a second place for the definition of "rate" to live.

        A null or non-finite `med_dose`, or a null `med_dose_unit`, is DROPPED and the
        count printed. `is_not_null()` alone is not enough: polars reports NaN as
        non-null, so a NaN dose would sort last, publish at `ecdf` = 1.0 and inflate
        `n_total` -- a value with no position in a cumulative distribution pinned at
        its 100th percentile, which is the exact failure this guard exists to prevent.
        Dropping changes `n_total`, so it is reported rather than absorbed.

        The sort is applied BEFORE the cumulative sum: `group_by().agg()` returns rows
        in an unspecified order, and `cum_sum().over()` accumulates in whatever order
        it is handed. Sorting after would produce a correctly-ordered frame carrying
        a cumulative column computed down the wrong sequence.
        """
        _group = ["med_category", "med_dose_unit"]

        _clean = df.filter(
            pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & pl.col("med_dose_unit").is_not_null()
        )
        _dropped = df.height - _clean.height
        if _dropped:
            print(
                f"  [ecdf] {_dropped:,} row(s) dropped for a null or non-finite "
                "med_dose, or a null med_dose_unit -- n_total below is net of them"
            )

        return (
            _clean.group_by([*_group, "med_dose"])
            .agg(n_at_dose=pl.len())
            .sort([*_group, "med_dose"])
            .with_columns(
                n_cum=pl.col("n_at_dose").cum_sum().over(_group),
                n_total=pl.col("n_at_dose").sum().over(_group),
            )
            .with_columns(ecdf=(pl.col("n_cum") / pl.col("n_total")).round(6))
            .rename({"med_dose": "dose"})
            .select([*_group, "dose", "n_at_dose", "n_cum", "n_total", "ecdf"])
        )

    return (ecdf_by_group,)


@app.cell
def _(SHARE_DIR, ecdf_by_group, pl, publish, raw_doses):
    # The ECDF and unit-count table consume the same raw frame. The ECDF excludes
    # missing/non-finite doses while the unit table retains them as charting QC.
    paralytic_dose_ecdf = ecdf_by_group(raw_doses)

    # Reconciliation, asserted rather than trusted -- but asserted against the SAME
    # population ecdf_by_group actually counts. n_total is net of the nulls that
    # function drops, so comparing it to the unfiltered row count would turn a
    # documented, REPORTED condition (spec §4) into a fatal error at any site with a
    # single null dose. What must never differ is the count over the rows that DO
    # carry a dose: a mismatch there means the grouping keys drifted apart, which is
    # the bug this assert exists to catch.
    _expected = (
        raw_doses.filter(
            pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & pl.col("med_dose_unit").is_not_null()
        )
        .group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.len())
        .sort(["med_category", "med_dose_unit"])
    )
    _got = (
        paralytic_dose_ecdf.group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.col("n_total").first())
        .sort(["med_category", "med_dose_unit"])
    )
    assert _expected.equals(_got), (
        "paralytic_dose_ecdf n_total does not reconcile with the dosed rows of "
        f"raw_doses:\nexpected:\n{_expected}\ngot:\n{_got}"
    )

    # The gap against step02__paralytic_dose_raw_unit_counts.csv's own count: reported,
    # never fatal (spec §4).
    # That file counts every administration in the group; this one counts only those
    # carrying a dose, so where the two differ the difference IS the null count. A
    # group that is entirely null-dosed vanishes from the ECDF and shows n = 0 here
    # rather than disappearing silently.
    _units = (
        raw_doses.group_by(["med_category", "med_dose_unit"])
        .agg(n_units=pl.len())
        .sort(["med_category", "med_dose_unit"])
    )
    _gap = (
        _units.join(_got, on=["med_category", "med_dose_unit"], how="left")
        .with_columns(n=pl.col("n").fill_null(0))
        .with_columns(n_null_dose=pl.col("n_units") - pl.col("n"))
        .filter(pl.col("n_null_dose") > 0)
    )
    if _gap.height:
        print(
            "  [paralytic_dose_ecdf] n_total sits below "
            "step02__paralytic_dose_raw_unit_counts.csv's n for the "
            "groups below -- the difference is rows carrying a null dose:"
        )
        print(_gap)

    publish(
        paralytic_dose_ecdf,
        SHARE_DIR / "fig_B1__paralytic_dose_ecdf.csv",
        "fig_B1__paralytic_dose_ecdf",
    )
    return (paralytic_dose_ecdf,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Figures A.1 and C.1

        Both are drawn **from the published CSVs and nothing else** (spec P21), so a
        figure cannot disagree with the table beside it. Every bin is published at its
        true count, so there is no withheld state to encode -- the only thing a figure
        must still make legible is a *measured* zero.
        """
    )
    return


@app.cell
def _():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return (plt,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Marking a published zero so it is not invisible

        A count is zero exactly when polars computed zero. A bar's height cannot show
        that on its own: a zero-height bar is indistinguishable from a gap in the axis,
        and on a log axis a zero-height bar cannot be drawn at all. Both figures below
        therefore plot a small **diamond just above the baseline, in the series' own
        color**, for a published, exactly-zero count, and use a linear y-axis rather than
        log -- with roughly half the cells in these tables exactly zero, a log axis cannot
        place zero on it in the first place.
        """
    )
    return


@app.cell
def _(plt):
    def mark_zero(ax, x, color):
        """A published, exactly-zero value: a diamond centered on the baseline.

        Placed at y=0 in DATA coordinates -- not scaled off `y_ref` or any other frame
        statistic. A marker scaled off the frame's max is only guaranteed smaller than a
        real bar while every real bar is at least that tall, which stopped being true the
        moment counts of 1..9 started being drawn (P21): a `y_ref * 0.02` marker on a
        frame whose max is in the hundreds sits well above bars of height 1..3, inverting
        the encoding it exists to make legible. A marker centered exactly at y=0 has zero
        data-height by construction, so it can never equal or exceed a bar of ANY positive
        height, however small. Its center sits exactly on `ylim`'s bottom edge, so its
        lower half falls outside the axes; `clip_on=False` is what keeps that half drawn.
        """
        ax.plot(
            [x], [0], marker="D", markersize=7, color=color,
            linestyle="None", zorder=5, clip_on=False,
        )

    return (mark_zero,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Figure A.1 — paralytic administration gaps, same agent vs. cross agent

        Every bin, at its true count. A colored bar where that series' count is positive,
        a colored diamond on the baseline where it is a *published* zero -- `n_cross_agent`
        is zero in several bins at this site, which is the actual result, and the diamond
        is what lets a reader see that rather than mistake it for a gap in the data.

        `n_cross_agent`'s own peak (5) is under 3% of `n_same_agent`'s (234), so on the
        one shared axis the orange series renders as a near-baseline hairline everywhere
        it is nonzero -- correct, but easy to misread as absent. The corner annotation
        gives each series' true total and peak, read from this same published CSV, so
        the small series' magnitude is on the page even where the bars can't show it.
        """
    )
    return


@app.cell
def _(FIG_DIR, GAP_BIN_LABELS, SHARE_DIR, mark_zero, pl, plt):
    # Fixed categorical color order (dataviz skill), never cycled: blue is always
    # same-agent, orange is always cross-agent, everywhere the pair appears.
    _BLUE = "#2a78d6"
    _ORANGE = "#eb6834"

    figure_a1_df = pl.read_csv(SHARE_DIR / "fig_A1__paralytic_administration_pair_gaps.csv")

    _fig, _ax = plt.subplots(figsize=(11, 6.5))

    for _row in figure_a1_df.iter_rows(named=True):
        _o = _row["bin_order"]
        if _row["n_same_agent"] > 0:
            _ax.bar([_o - 0.2], [_row["n_same_agent"]], width=0.4, color=_BLUE)
        else:
            mark_zero(_ax, _o - 0.2, _BLUE)
        if _row["n_cross_agent"] > 0:
            _ax.bar([_o + 0.2], [_row["n_cross_agent"]], width=0.4, color=_ORANGE)
        else:
            mark_zero(_ax, _o + 0.2, _ORANGE)

    # Same-agent's peak dwarfs cross-agent's (234 vs 5): on this one shared axis the
    # smaller series is a near-baseline hairline wherever it is nonzero. The corner
    # annotation carries each series' true magnitude, read from the same published
    # frame the bars are drawn from -- never recomputed -- so it cannot disagree with
    # the CSV beside it.
    _ax.text(
        0.99, 0.98,
        f"same agent:  n = {figure_a1_df['n_same_agent'].sum():,}, peak = {figure_a1_df['n_same_agent'].max():,}",
        transform=_ax.transAxes, ha="right", va="top", fontsize=8, color=_BLUE,
    )
    _ax.text(
        0.99, 0.94,
        f"cross agent:  n = {figure_a1_df['n_cross_agent'].sum():,}, peak = {figure_a1_df['n_cross_agent'].max():,}",
        transform=_ax.transAxes, ha="right", va="top", fontsize=8, color=_ORANGE,
    )

    _ax.set_xticks(list(range(len(GAP_BIN_LABELS))))
    _ax.set_xticklabels(GAP_BIN_LABELS, rotation=45, ha="right")
    _ax.set_xlabel("gap between paralytic administrations")
    _ax.set_ylabel("pairs")
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)

    _fold_x = GAP_BIN_LABELS.index("(10,15]") + 0.5
    _ax.axvline(_fold_x, color="#0b0b0b", linestyle="--", linewidth=1)
    _ax.text(
        _fold_x + 0.1, _ax.get_ylim()[1] * 0.92,
        "15 min\n(the fold)", fontsize=8, va="top", color="#0b0b0b",
    )

    _handles = [
        _ax.plot([], [], color=_BLUE, lw=6, label="same agent (redose)")[0],
        _ax.plot([], [], color=_ORANGE, lw=6, label="different agents (co-administration)")[0],
        _ax.plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                 label="published zero (measured, exactly 0)")[0],
    ]
    _ax.legend(handles=_handles, loc="upper left", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "A.1 — gaps between paralytic administrations, all pairs within an encounter\n"
        "15 minutes is a clinical definition, not a measured optimum (spec P7)"
    )
    _fig.tight_layout()
    _fig.subplots_adjust(bottom=0.38)
    _fig.savefig(FIG_DIR / "fig_A1__paralytic_administration_pair_gaps.png", dpi=150)
    plt.close(_fig)
    print(f"fig_A1__paralytic_administration_pair_gaps.png -> {FIG_DIR}")
    return (figure_a1_df,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Figure C.1 — how far apart are a block's index paralytics

        One series, one question: inside a hospitalization that has **more than one** index
        paralytic, how much time separates them? Every unordered pair of index paralytics
        within an `encounter_block`, counted into the same 15-bin grid Figure A.1 uses, so
        the two figures can still be read against each other bin-for-bin.

        A block with a single index paralytic forms no pair and is therefore absent by
        definition, not by a filter — the corner annotation names how many blocks actually
        contribute, read from `step02__index_paralytics_per_block.csv`.

        Only the bins **above 15 minutes** are drawn. The six at or below it are empty by
        construction: the fold closes an index event at `t + 15` inclusive, so the next
        index is strictly after that. They are still published as explicit zeros in
        `fig_C1__index_paralytic_pair_gaps.csv`, and the assertion in sub-analysis C is what tests
        the floor. Drawing them here spent a third of the axis on a result that could not
        have come out any other way.
        """
    )
    return


@app.cell
def _(FIG_DIR, GAP_BIN_LABELS, SHARE_DIR, mark_zero, pl, plt):
    # Aqua means "index paralytics" wherever they are drawn, the same way blue always
    # means same-agent and orange always cross-agent in A.1. Fixed, never cycled.
    _AQUA = "#1baf7a"

    # The floor is evidenced in the CSV, not on the axis. `bin_order` is the published
    # column, so slicing on it -- rather than re-deriving positions from a re-read frame
    # -- is what keeps the bars aligned with the labels if the grid ever changes.
    _FIRST_DRAWN = GAP_BIN_LABELS.index("(15,30]")
    _labels = GAP_BIN_LABELS[_FIRST_DRAWN:]

    figure_c1_df = pl.read_csv(SHARE_DIR / "fig_C1__index_paralytic_pair_gaps.csv").filter(
        pl.col("bin_order") >= _FIRST_DRAWN
    )
    _dropped = pl.read_csv(SHARE_DIR / "fig_C1__index_paralytic_pair_gaps.csv").filter(
        pl.col("bin_order") < _FIRST_DRAWN
    )
    assert _dropped.get_column("n").sum() == 0, (
        "a bin at or below 15 minutes carries pairs, so omitting it from this figure "
        "would hide a real count. The fold's floor is broken -- fix that, not the plot."
    )

    # Blocks with exactly one index contribute no pair; this figure's denominator is the
    # rest. Read from the published per-block table so the number on the figure and the
    # number in the CSV cannot drift apart.
    _n_blocks = (
        pl.read_csv(SHARE_DIR / "step02__index_paralytics_per_block.csv")
        .filter(pl.col("n_index") > 1)
        .get_column("n_blocks")
        .sum()
    )

    _fig, _ax = plt.subplots(figsize=(11, 6.5))

    _has_published_zero = False
    for _row in figure_c1_df.iter_rows(named=True):
        _x = _row["bin_order"] - _FIRST_DRAWN
        if _row["n"] > 0:
            _ax.bar([_x], [_row["n"]], width=0.62, color=_AQUA)
        else:
            mark_zero(_ax, _x, _AQUA)
            _has_published_zero = True

    # Upper LEFT, not right: this distribution rises monotonically into the wide bins, so
    # the right shoulder is where the tall bars are and the left is the only reliably
    # empty corner. Both numbers come from published CSVs, never recomputed here.
    _ax.text(
        0.01, 0.98, f"{figure_c1_df['n'].sum():,} pairs",
        transform=_ax.transAxes, ha="left", va="top", fontsize=8, color="#0b0b0b",
    )
    _ax.text(
        0.01, 0.94, f"{_n_blocks:,} encounter blocks with more than one index paralytic",
        transform=_ax.transAxes, ha="left", va="top", fontsize=8, color="#0b0b0b",
    )

    _ax.set_xticks(list(range(len(_labels))))
    _ax.set_xticklabels(_labels, rotation=45, ha="right")
    _ax.set_xlabel("time between two index paralytics in the same encounter block")
    _ax.set_ylabel("pairs")
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)

    if _has_published_zero:
        _ax.legend(
            handles=[
                _ax.plot([], [], marker="D", markersize=7, color=_AQUA, linestyle="None",
                         label="published zero (measured, exactly 0)")[0]
            ],
            loc="upper center", fontsize=8, framealpha=0.9,
        )

    _ax.set_title(
        "C.1 — time between index paralytics, blocks with more than one index\n"
        "bins at or below 15 min are empty by construction (the fold's floor) and are not drawn"
    )
    _fig.tight_layout()
    _fig.subplots_adjust(bottom=0.22)
    _fig.savefig(FIG_DIR / "fig_C1__index_paralytic_pair_gaps.png", dpi=150)
    plt.close(_fig)
    print(f"fig_C1__index_paralytic_pair_gaps.png -> {FIG_DIR}")
    return (figure_c1_df,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"

    # Read the PUBLISHED csv, never the in-memory frame (P21) -- a figure that
    # disagrees with the table beside it is a bug only this convention catches.
    figure_b1_df = pl.read_csv(SHARE_DIR / "fig_B1__paralytic_dose_ecdf.csv")

    _groups = (
        figure_b1_df.select("med_category", "med_dose_unit")
        .unique()
        .sort(["med_category", "med_dose_unit"])
        .rows()
    )

    if not _groups:
        # No paralytic administration carries an amount dose at this site.
        # plt.subplots(0, 1, ...) would raise; skip with a clear message instead.
        print(
            "fig_B1__paralytic_dose_ecdf.png skipped -- its source CSV has zero "
            "rows at this site (no paralytic administration carries an amount dose)"
        )
    else:
        _n_panels = len(_groups)
        _FIG_H = 1.3 + 2.1 * _n_panels
        _fig, _axes = plt.subplots(
            _n_panels, 1, figsize=(9, _FIG_H), squeeze=False,
        )
        _axes = [_a[0] for _a in _axes]

        for _ax, (_cat, _unit) in zip(_axes, _groups):
            _p = figure_b1_df.filter(
                (pl.col("med_category") == _cat) & (pl.col("med_dose_unit") == _unit)
            ).sort("dose")
            _x = _p.get_column("dose").to_list()
            _y = _p.get_column("ecdf").to_list()
            _n_total = _p.get_column("n_total").first()

            # where="post": an ECDF is right-continuous -- F(x) holds from this charted
            # dose until the next one is reached. A plain line, or where="pre", draws
            # mass at doses nobody charted, which is the exact misreading this figure
            # exists to prevent.
            _ax.step(_x, _y, where="post", color=_BLUE, linewidth=1.6)
            # The markers are the observations; the steps between them are the
            # function's definition, not measurement. At n_total = 3 a reader has to
            # be able to count them.
            _ax.plot(
                _x, _y, marker="o", markersize=3.5, linestyle="None", color=_BLUE,
            )

            _ax.set_ylim(0, 1.02)
            _ax.set_xlim(left=0)
            _ax.margins(x=0.04)
            _ax.set_axisbelow(True)
            _ax.grid(axis="x", color=_GRID, linewidth=0.8)
            for _side in ("top", "right"):
                _ax.spines[_side].set_visible(False)
            _ax.tick_params(labelsize=8, colors=_MUTED)
            _ax.set_ylabel("cumulative\nproportion", fontsize=8, color=_MUTED)
            _ax.set_title(
                f"{_cat}  ·  charted in {_unit}  ·  n = {_n_total:,}  ·  "
                f"{_p.height} distinct dose(s)",
                fontsize=9, loc="left", color=_INK,
            )

        _axes[-1].set_xlabel(
            "dose, in the unit the site charted — panels do NOT share an axis (P41)",
            fontsize=9, color=_INK,
        )
        _fig.suptitle(
            "B.1 — index paralytic dose, empirical CDF by agent and charted unit\n"
            "one panel per (agent, raw charted unit); no unit conversion (P41)\n"
            f"{figure_b1_df.height} row(s) published",
            fontsize=11, color=_INK,
        )
        _fig.tight_layout()
        _fig.subplots_adjust(top=1 - 1.5 / _FIG_H, hspace=0.55)
        _fig.savefig(FIG_DIR / "fig_B1__paralytic_dose_ecdf.png", dpi=150)
        plt.close(_fig)
        print(f"fig_B1__paralytic_dose_ecdf.png -> {FIG_DIR}")
    return (figure_b1_df,)


if __name__ == "__main__":
    app.run()
