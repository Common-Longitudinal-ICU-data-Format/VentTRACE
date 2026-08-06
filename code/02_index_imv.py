import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import datetime as dt
    import json
    from datetime import timedelta
    from pathlib import Path

    import polars as pl

    import marimo as mo

    return Path, dt, json, mo, pl, timedelta


@app.cell
def _(mo):
    mo.md(
        """
        # 02 — Episode detection and CONSORT B

        `01` says which blocks are in the study. It does not say how many intubations a
        block holds, when each began, or whether any of them is one we can see happen.
        This notebook answers all three, and its CONSORT is a headline result rather than
        a preprocessing note.

        Three rules, in order:

        ```
        1  an imv row starts an episode iff no imv row precedes it
           within episode_gap_hours in the same block          (D36)

        2  reject if a non-null non-imv device appears within
           episode_gap_hours after the start                   (sustained)

        t0 = the episode's first WATERFALLED imv row            (D34)

        3  reject unless one of the eight induction agents is
           charted `given` within t0 +/- window_hours           (D38)
        ```

        A null device, and an empty window, pass rules 1 and 2 — absence of charting is
        not evidence of ventilation (D37). That is what retires the `arrived_intubated`
        and `insufficient_lookback` exclusions of the previous design.

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` §5.9–§5.13
        """
    )
    return


@app.cell
def _(Path, json, timedelta):
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
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    EPISODE_GAP_HOURS = config["episode_gap_hours"]
    WINDOW_HOURS = config["window_hours"]
    EPISODE_GAP = timedelta(hours=EPISODE_GAP_HOURS)
    WINDOW = timedelta(hours=WINDOW_HOURS)

    # The union of the SED and PARA lists (D38). Written out rather than imported: this
    # notebook must be readable on its own, and D8 wants the duplication visible.
    #
    # This list is COUPLED to 03 and 04. If it drifts from their MED_CATEGORIES the cohort
    # silently stops being the cohort the methods measure. 07's Tier D.4 asserts the
    # coupling holds, which is the one place the drift is observable.
    SED_CATEGORIES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
    PARA_CATEGORIES = ["rocuronium", "succinylcholine", "vecuronium"]
    INDUCTION_CATEGORIES = SED_CATEGORIES + PARA_CATEGORIES

    print(f"site               : {SITE}")
    print(f"episode_gap_hours  : {EPISODE_GAP_HOURS}")
    print(f"window_hours       : {WINDOW_HOURS}")
    print(f"induction agents   : {', '.join(INDUCTION_CATEGORIES)}")
    return (
        DATA_DIR,
        EPISODE_GAP,
        EPISODE_GAP_HOURS,
        FILETYPE,
        INDUCTION_CATEGORIES,
        PHI_DIR,
        SHARE_DIR,
        TIMEZONE,
        WINDOW,
        WINDOW_HOURS,
    )


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy returns tz-aware columns whose tzinfo carries the pytz LMT offset --
        `DstTzInfo 'US/Eastern' LMT-1 day, 19:04:00 STD`. `.dt.tz_localize(None)` alone
        drops the ATTACHED offset rather than the correct one and shifts every timestamp
        by about an hour, silently. See §5.13.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Rules 1 and 2 as one function

        Written as a function so the §5.9 worked examples test the code that runs on the
        data, not a paraphrase of it.
        """
    )
    return


@app.cell
def _(pl, timedelta):
    def find_episode_starts(df, gap):
        """Rules 1 and 2. `df` is waterfalled rows with `encounter_block`,
        `recorded_dttm`, `device_category`. Returns one row per candidate start with a
        `sustained` flag.

        Rule 1 is a shift(1) over IMV-ONLY rows, which is what makes this short. A
        mid-episode imv row has imv within `gap` behind it and disqualifies itself, so the
        same predicate that tests the pre-period also segments the timeline -- there is no
        episode loop and no in-episode state to carry (D36).
        """
        _imv = (
            df.filter(pl.col("device_category") == "imv")
            .select(["encounter_block", "recorded_dttm"])
            .unique()
            .sort(["encounter_block", "recorded_dttm"])
            .with_columns(prev_imv=pl.col("recorded_dttm").shift(1).over("encounter_block"))
        )
        # `>= gap` and not `> gap`: exactly `gap` of no imv qualifies -- worked example (e).
        _cand = _imv.filter(
            pl.col("prev_imv").is_null()
            | ((pl.col("recorded_dttm") - pl.col("prev_imv")) >= gap)
        ).select(["encounter_block", "recorded_dttm"])

        _other = (
            df.filter(
                pl.col("device_category").is_not_null()
                & (pl.col("device_category") != "imv")
            )
            .select(["encounter_block", "recorded_dttm"])
            .unique()
            .sort(["encounter_block", "recorded_dttm"])
        )
        if _other.height == 0:
            return _cand.with_columns(sustained=pl.lit(True))

        # Rule 2. join_asof forward matches right >= left, but the window is STRICTLY after
        # the start, so the probe key is nudged by one microsecond. A non-imv device charted
        # at the very same instant as the start (possible across two hospitalizations in one
        # block) is then not treated as landing inside a window that begins after it.
        _probe = _cand.with_columns(
            _probe_dttm=pl.col("recorded_dttm") + timedelta(microseconds=1)
        ).sort("_probe_dttm")
        _joined = _probe.join_asof(
            _other.rename({"recorded_dttm": "next_other_dttm"}).sort("next_other_dttm"),
            left_on="_probe_dttm",
            right_on="next_other_dttm",
            by="encounter_block",
            strategy="forward",
        )
        return _joined.select(
            "encounter_block",
            "recorded_dttm",
            sustained=pl.col("next_other_dttm").is_null()
            | ((pl.col("next_other_dttm") - pl.col("recorded_dttm")) > gap),
        )

    return (find_episode_starts,)


@app.cell
def _(dt, find_episode_starts, pl, timedelta):
    def _self_test():
        """The §5.9 worked examples, run as assertions before any real data is touched."""
        _gap = timedelta(hours=3)
        _base = dt.datetime(2130, 1, 1)

        def _mk(seq):
            return pl.DataFrame(
                {
                    "encounter_block": pl.Series([1] * len(seq), dtype=pl.Int32),
                    "recorded_dttm": [_base + timedelta(minutes=m) for m, _ in seq],
                    "device_category": pl.Series([d for _, d in seq], dtype=pl.String),
                }
            ).sort("recorded_dttm")

        _cases = [
            ("a", [(0, "nasal cannula"), (60, "imv"), (90, "imv"), (120, "imv")], [60]),
            ("b", [(0, "imv"), (30, "nasal cannula"), (400, "imv")], [400]),
            ("c", [(0, "imv"), (400, "imv")], [0, 400]),
            ("d", [(0, "imv"), (179, "imv")], [0]),
            ("e", [(0, "imv"), (180, "imv")], [0, 180]),
            ("f", [(0, None), (30, None), (60, "imv"), (160, "imv")], [60]),
            ("g", [(0, "imv")], [0]),
        ]
        for _label, _seq, _want in _cases:
            _got_df = find_episode_starts(_mk(_seq), _gap).filter("sustained")
            _got = sorted(
                int((_r - _base).total_seconds() // 60)
                for _r in _got_df.get_column("recorded_dttm").to_list()
            )
            assert _got == _want, (
                f"worked example ({_label}): expected {_want}, got {_got}"
            )
        print("§5.9 worked examples (a)-(g) pass")

    _self_test()
    return


@app.cell
def _(mo):
    mo.md("## Load")
    return


@app.cell
def _(PHI_DIR, pl):
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")
    resp_waterfall = pl.read_parquet(PHI_DIR / "cohort_resp_waterfall.parquet")

    COHORT_RUN_ID = cohort_index.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"cohort_index carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    assert "t0_dttm" not in cohort_index.columns, (
        "cohort_index still carries t0_dttm. 01 must be re-run: under D34 t0 belongs to "
        "an episode and this notebook resolves it, so a block-level t0 here is stale."
    )

    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"cohort blocks     : {cohort_index.height:,}")
    print(f"waterfalled rows  : {resp_waterfall.height:,}")
    return COHORT_RUN_ID, cohort_index, resp_waterfall


@app.cell
def _(mo):
    mo.md(
        """
        ## Rules 1 and 2 applied

        The sequence is ordered **within the block**, across all its hospitalizations.
        That is what makes stitching effective: an ED intubation and the ventilation that
        follows upstairs are one episode rather than two.
        """
    )
    return


@app.cell
def _(EPISODE_GAP, WINDOW, find_episode_starts, pl, resp_waterfall):
    # The window is fixed here, for EVERY candidate -- including the ones rule 2 rejects.
    # D20 runs the methods over the rejected rows so Tier D has a probe, and a rejected
    # candidate with a null window silently detects nothing: the methods filter on
    # `admin_dttm >= window_start`, which is false against null. Tier D.3 would then compare
    # a real rate against a fabricated 0.0 and read it as perfect specificity.
    candidates = (
        find_episode_starts(
            resp_waterfall.sort(["encounter_block", "recorded_dttm"]), EPISODE_GAP
        )
        .rename({"recorded_dttm": "t0_dttm"})
        .with_columns(
            window_start=pl.col("t0_dttm") - WINDOW,
            window_end=pl.col("t0_dttm") + WINDOW,
        )
    )

    assert candidates.get_column("window_start").null_count() == 0, (
        "a candidate episode has no window. Every candidate must carry one -- the methods "
        "run over the rejected rows too (D20) and a null window makes them silently blind."
    )

    n_candidates = candidates.height
    n_sustained = candidates.filter("sustained").height
    print(f"candidate episode starts (rule 1) : {n_candidates:,}")
    print(f"  blocks represented              : {candidates.get_column('encounter_block').n_unique():,}")
    print(f"sustained (rule 2)                : {n_sustained:,}   (-{n_candidates - n_sustained:,})")
    return candidates, n_candidates, n_sustained


@app.cell
def _(mo):
    mo.md(
        """
        ## t0, episode numbering and the window

        **t0 is the episode's first waterfalled IMV row (D34)**, not the first raw charted
        one. Intubation is a high-stress event and the device field is filled in late,
        while the ventilator's settings reach the record the moment it is connected — so
        the settings-based inference at `waterfall.py:199-215` lands closer to the event
        than the manual entry does. The gap is measured below rather than assumed.
        """
    )
    return


@app.cell
def _(candidates, pl):
    # ep_num is assigned over the SUSTAINED set only, so the ids a reader sees are the ones
    # the study uses. Numbering candidates instead would leave a gap in the sequence for
    # every rejected row, which reads as missing data rather than as a rejection.
    episodes_numbered = (
        candidates.filter("sustained")
        .sort(["encounter_block", "t0_dttm"])
        .with_columns(
            ep_num=pl.int_range(1, pl.len() + 1).over("encounter_block").cast(pl.Int32),
        )
    )

    print(f"episodes numbered : {episodes_numbered.height:,}")
    # ep_num counts SUSTAINED episodes, not qualified ones. A no_induction_med episode is
    # still a real ventilation episode -- it just had no induction charted -- so an
    # intubation that follows one genuinely is the block's second. Numbering only qualified
    # episodes would call it the first, and would make Tier D.2's stratum circular: "an
    # earlier episode also had induction charted" is a statement about the filter, not the
    # patient.
    print(f"reintubations     : {episodes_numbered.filter(pl.col('ep_num') > 1).height:,}"
          "   (ep_num > 1 over the SUSTAINED set)")
    print("\nepisodes per block:")
    print(
        episodes_numbered.group_by("encounter_block")
        .len()
        .get_column("len")
        .value_counts()
        .sort("len")
    )
    return (episodes_numbered,)


@app.cell
def _(WINDOW, episodes_numbered, pl):
    # Two episodes in one block are at least episode_gap_hours apart by rule 1, but the
    # medication window is window_hours EITHER SIDE, so windows can in principle overlap and
    # one administration be ranked into two episodes. Measured on MIMIC the minimum observed
    # gap is 346 min against a 360 min overlap threshold, so this happens exactly once.
    # Reported rather than designed around -- but asserted, so a site where it is common
    # finds out here instead of in Tier A.
    _gaps = episodes_numbered.sort(["encounter_block", "t0_dttm"]).with_columns(
        gap_min=(
            pl.col("t0_dttm") - pl.col("t0_dttm").shift(1).over("encounter_block")
        ).dt.total_minutes()
    )
    _overlap_min = 2 * WINDOW.total_seconds() / 60.0
    _n_overlap = _gaps.filter(pl.col("gap_min") < _overlap_min).height
    _n_pairs = _gaps.filter(pl.col("gap_min").is_not_null()).height
    _pct = 100.0 * _n_overlap / _n_pairs if _n_pairs else 0.0

    print(f"consecutive episode pairs in a block : {_n_pairs:,}")
    print(f"  with overlapping windows           : {_n_overlap:,} ({_pct:.2f}%)")
    assert _pct < 5.0, (
        f"{_pct:.1f}% of consecutive episode pairs have overlapping medication windows. "
        "An administration in the overlap is ranked into BOTH episodes, so Tier A's "
        "denominator double-counts it. At this rate that is no longer negligible -- either "
        "episode_gap_hours is too small for this site or window_hours is too large."
    )
    return


@app.cell
def _(PHI_DIR, episodes_numbered, pl):
    imv_raw = pl.read_parquet(PHI_DIR / "cohort_resp_imv_raw.parquet")

    # Bounded to the episode's own stretch, so a charted row belonging to the NEXT episode
    # cannot be attributed to this one.
    _bounded = episodes_numbered.sort(["encounter_block", "t0_dttm"]).with_columns(
        _next_t0=pl.col("t0_dttm").shift(-1).over("encounter_block")
    )
    _charted = (
        _bounded.join(imv_raw, on="encounter_block", how="left")
        .filter(
            (pl.col("recorded_dttm") >= pl.col("t0_dttm"))
            & (pl.col("_next_t0").is_null() | (pl.col("recorded_dttm") < pl.col("_next_t0")))
        )
        .group_by(["encounter_block", "t0_dttm"])
        .agg(first_charted_imv_dttm=pl.col("recorded_dttm").min())
    )

    episodes_labelled = episodes_numbered.join(
        _charted, on=["encounter_block", "t0_dttm"], how="left"
    ).with_columns(
        imv_charted=pl.col("first_charted_imv_dttm").is_not_null(),
        charting_delay_min=(
            pl.col("first_charted_imv_dttm") - pl.col("t0_dttm")
        ).dt.total_seconds()
        / 60.0,
    )

    # D34. The waterfall relabels null-device rows to imv and never deletes a charted row,
    # so its imv set is a superset of the raw one IN TIME and its first element cannot be
    # later than the raw first element. A negative delay is therefore impossible unless the
    # two frames are on different time bases -- see §5.13. This is the third independent
    # frame-pair check for that bug, after 01's timestamp alignment.
    _neg = episodes_labelled.filter(pl.col("charting_delay_min") < 0)
    assert _neg.height == 0, (
        f"{_neg.height:,} episodes have a NEGATIVE charting delay, e.g. "
        f"{_neg.head(3).select(['encounter_block', 't0_dttm', 'first_charted_imv_dttm']).to_dicts()}. "
        "That is impossible by construction: the raw charted imv rows are a subset of the "
        "waterfalled ones. The two frames are on different time bases -- check that both "
        "went through to_site_naive (§5.13)."
    )

    # Printed over the SUSTAINED set, which is what exists at this point in the notebook.
    # charting_delay.csv is written over the QUALIFIED set, so the two differ and the
    # labels say so -- an unlabelled p99 here would be quietly compared against a published
    # p99 computed on a different denominator.
    _d = episodes_labelled.get_column("charting_delay_min").drop_nulls()
    print("charting delay (first charted imv - t0), minutes -- over the SUSTAINED set")
    print(f"  never charted : {episodes_labelled.get_column('charting_delay_min').null_count():,}")
    print(f"  exactly 0     : {(_d == 0).sum():,} ({100 * (_d == 0).mean():.1f}%)")
    for _pc in (0.5, 0.75, 0.9, 0.95, 0.99):
        print(f"  p{int(_pc * 100):<3}          : {_d.quantile(_pc):,.0f}")
    print(f"  max           : {_d.max():,.0f}")
    return (episodes_labelled,)


@app.cell
def _(episodes_labelled, pl, resp_waterfall):
    # The old `arrived_intubated` class, kept as a label rather than an exclusion (D37).
    # It is the first number §5.11 says to read, and Tier D stratifies on it.
    _block_first = resp_waterfall.group_by("encounter_block").agg(
        _block_first_dttm=pl.col("recorded_dttm").min()
    )
    episodes = (
        episodes_labelled.join(_block_first, on="encounter_block", how="left")
        .with_columns(no_lookback=pl.col("t0_dttm") == pl.col("_block_first_dttm"))
        .drop(["_block_first_dttm", "_next_t0"], strict=False)
    )

    _n = episodes.filter("no_lookback").height
    print(
        f"no_lookback (t0 is the block's first respiratory row) : {_n:,} "
        f"({100 * _n / episodes.height:.1f}% of the SUSTAINED set)"
    )
    return (episodes,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The explode-and-drop bridge

        CLIF tables are keyed on `hospitalization_id`; this study is keyed on
        `encounter_block` and then on the episode. The bridge below is the **only** place
        this notebook names a hospitalization, and the column is dropped the moment the
        join lands. An induction agent given in the ED presentation and an IMV row charted
        after transfer belong to one block; if `hospitalization_id` survived into the
        window filter, rule 3 would quietly revert to the unstitched unit.
        """
    )
    return


@app.cell
def _(cohort_index, pl):
    bridge = (
        cohort_index.select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    print(f"blocks              : {bridge.get_column('encounter_block').n_unique():,}")
    print(f"hospitalization ids : {len(bridge_hosp_ids):,}")
    return bridge, bridge_hosp_ids


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    INDUCTION_CATEGORIES,
    TIMEZONE,
    bridge_hosp_ids,
    pl,
    to_site_naive,
):
    from clifpy.tables import MedicationAdminIntermittent

    # D22 -- the load-time filter runs on raw site data, before any lower-casing we control,
    # so every casing variant must be passed or a site that writes 'Propofol' silently
    # yields an empty frame and an empty cohort with no error at all.
    _variants = sorted(
        {c for m in INDUCTION_CATEGORIES for c in (m, m.upper(), m.capitalize())}
    )
    _tbl = MedicationAdminIntermittent.from_file(
        data_directory=DATA_DIR,
        filetype=FILETYPE,
        timezone=TIMEZONE,
        columns=["hospitalization_id", "med_category", "admin_dttm", "mar_action_category"],
        filters={"hospitalization_id": bridge_hosp_ids, "med_category": _variants},
    )
    _pdf = _tbl.df.copy()
    _pdf["admin_dttm"] = to_site_naive(_pdf["admin_dttm"])

    med_induction = pl.from_pandas(
        _pdf[["hospitalization_id", "med_category", "admin_dttm", "mar_action_category"]]
    ).with_columns(
        med_category=pl.col("med_category").str.to_lowercase(),
        mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
    )

    _seen = set(med_induction.get_column("med_category").unique().to_list())
    _missing = sorted(set(INDUCTION_CATEGORIES) - _seen)
    assert _seen <= set(INDUCTION_CATEGORIES), (
        "the load-time filter let through categories outside the list: "
        f"{sorted(_seen - set(INDUCTION_CATEGORIES))}"
    )
    assert med_induction.height > 0, (
        "no induction agent rows loaded at all. Either the filter's casing variants miss "
        "this site's spelling (D22) or the extract has no intermittent medications."
    )
    if _missing:
        print(f"NOT PRESENT at this site: {', '.join(_missing)}")
        print("  (rule 3 still runs -- it needs any ONE of the list, not all of them)")
    print(f"induction agent rows loaded : {med_induction.height:,}")
    print(med_induction.get_column("med_category").value_counts(sort=True))
    return (med_induction,)


@app.cell
def _(bridge, episodes, med_induction, pl):
    _given = (
        med_induction.filter(pl.col("mar_action_category") == "given")
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # the drop is the point of the bridge
        .select(["encounter_block", "admin_dttm"])
    )

    _hit = (
        episodes.select(["encounter_block", "t0_dttm", "window_start", "window_end"])
        .join(_given, on="encounter_block", how="inner")
        .filter(
            (pl.col("admin_dttm") >= pl.col("window_start"))
            & (pl.col("admin_dttm") <= pl.col("window_end"))
        )
        .select(["encounter_block", "t0_dttm"])
        .unique()
        .with_columns(has_induction_med=pl.lit(True))
    )

    episodes_gated = episodes.join(
        _hit, on=["encounter_block", "t0_dttm"], how="left"
    ).with_columns(has_induction_med=pl.col("has_induction_med").fill_null(False))

    _n = episodes_gated.filter("has_induction_med").height
    print(
        f"episodes with an induction agent in the window : {_n:,} "
        f"(-{episodes_gated.height - _n:,})"
    )
    return (episodes_gated,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The index taxonomy

        Three classes, assigned over the **candidate** set. The rejections are kept (D20):
        the methods run over every row and `07` is the single place that splits primary
        from probe.
        """
    )
    return


@app.cell
def _(candidates, cohort_index, episodes_gated, pl):
    # The window comes through with them: a rejected candidate is still scored by the
    # methods (D20), so it needs the same window a qualified one has.
    _rejected = (
        candidates.filter(~pl.col("sustained"))
        .select(["encounter_block", "t0_dttm", "window_start", "window_end"])
        .with_columns(index_class=pl.lit("not_sustained"))
    )
    _evaluated = episodes_gated.with_columns(
        index_class=pl.when(pl.col("has_induction_med"))
        .then(pl.lit("qualified"))
        .otherwise(pl.lit("no_induction_med"))
    )

    index_imv_all = (
        pl.concat([_evaluated, _rejected], how="diagonal")
        .with_columns(index_qualified=pl.col("index_class") == "qualified")
        .sort(["encounter_block", "t0_dttm"])
        # ep_num was assigned over the SUSTAINED set only, so rejected candidates arrive
        # null and are numbered here -- CONTINUING after the block's real episodes rather
        # than being interleaved chronologically with them.
        #
        # Interleaving would be wrong twice over. It would renumber a real intubation to
        # E2 because a charting blip happened to precede it, which is a claim that a blip
        # is a reintubation. And because ep_num is already fixed for the sustained rows, a
        # chronological rank over the combined set collides with it -- a block whose
        # rejected candidate sorts first would emit two rows numbered E1 and the episode id
        # would not be unique. The assertion below would catch that; this avoids it.
        .with_columns(
            _max_sustained=pl.col("ep_num").max().over("encounter_block").fill_null(0)
        )
        .with_columns(
            _rejected_rank=pl.when(pl.col("ep_num").is_null())
            .then(1)
            .otherwise(0)
            .cum_sum()
            .over("encounter_block")
        )
        .with_columns(
            ep_num=pl.coalesce(
                pl.col("ep_num"), pl.col("_max_sustained") + pl.col("_rejected_rank")
            ).cast(pl.Int32)
        )
        .drop(["_max_sustained", "_rejected_rank"])
        .join(
            cohort_index.select(
                ["encounter_block", "patient_id", "cohort_run_id", "list_hospitalization_id"]
            ),
            on="encounter_block",
            how="left",
        )
        .with_columns(
            intubation_episode_id=pl.format(
                "{}_E{}", pl.col("encounter_block"), pl.col("ep_num")
            )
        )
    )

    assert index_imv_all.height == candidates.height, (
        f"index_imv has {index_imv_all.height:,} rows against {candidates.height:,} "
        "candidates -- every candidate must survive with a class (D20)"
    )
    assert index_imv_all.get_column("intubation_episode_id").is_unique().all(), (
        "intubation_episode_id is not unique. ep_num is not contiguous within a block."
    )
    assert index_imv_all.get_column("index_class").null_count() == 0, "unclassified episodes"
    assert index_imv_all.get_column("patient_id").null_count() == 0, (
        "some candidate episodes have no patient -- a block in the waterfall is absent "
        "from cohort_index"
    )
    # Every row the methods will run over must carry a window, whatever its class.
    for _c in ("t0_dttm", "window_start", "window_end"):
        _nulls = index_imv_all.get_column(_c).null_count()
        assert _nulls == 0, (
            f"{_nulls:,} candidate episodes have a null {_c}, broken down as "
            f"{index_imv_all.filter(pl.col(_c).is_null()).get_column('index_class').value_counts().to_dicts()}. "
            "The methods filter on the window, so a null one makes them silently detect "
            "nothing and Tier D reads the artifact as specificity."
        )

    index_class_counts = (
        index_imv_all.get_column("index_class")
        .value_counts()
        .with_columns(pct=100.0 * pl.col("count") / index_imv_all.height)
        .sort("count", descending=True)
    )
    print(index_class_counts)
    return index_class_counts, index_imv_all


@app.cell
def _(mo):
    mo.md(
        """
        ## CONSORT B — index

        A headline result, not a preprocessing note. **Three counts on every step** —
        episodes, blocks and patients — because the unit changed at the top of this stage
        and a reader tracking blocks through `01` needs the bridge.
        """
    )
    return


@app.cell
def _(index_imv_all, pl):
    consort_rows = []

    def _add(step, df, prev_n, note=""):
        consort_rows.append(
            {
                "step": step,
                "n_episodes": df.height,
                "n_blocks": df.get_column("encounter_block").n_unique(),
                "n_patients": df.get_column("patient_id").n_unique(),
                "n_excluded": 0 if prev_n is None else prev_n - df.height,
                "note": note,
            }
        )
        _r = consort_rows[-1]
        print(
            f"{_r['step']:<32} episodes={_r['n_episodes']:>9,}  "
            f"blocks={_r['n_blocks']:>9,}  patients={_r['n_patients']:>9,}  "
            f"excluded={_r['n_excluded']:>9,}"
        )
        return df.height

    _n = _add(
        "candidate episode starts",
        index_imv_all,
        None,
        "rule 1: no imv within episode_gap_hours before",
    )

    _s1 = index_imv_all.filter(pl.col("index_class") != "not_sustained")
    _n = _add(
        "exclude: not_sustained",
        _s1,
        _n,
        "non-IMV device within episode_gap_hours after",
    )

    _s2 = _s1.filter(pl.col("index_class") != "no_induction_med")
    _n = _add(
        "exclude: no_induction_med",
        _s2,
        _n,
        "no induction agent in t0 +/- window_hours",
    )

    _add("INDEX IMV EPISODE SET", _s2, None, "N**")

    consort_index_df = pl.DataFrame(consort_rows)
    return (consort_index_df,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Outputs

        `index_imv.parquet` holds **one row per candidate episode, not per qualified
        episode** (D20). It is the only file in the pipeline that knows what an episode is;
        everything downstream receives episodes as given and never re-derives one.
        """
    )
    return


@app.cell
def _(
    COHORT_RUN_ID,
    PHI_DIR,
    SHARE_DIR,
    consort_index_df,
    index_class_counts,
    index_imv_all,
    pl,
):
    index_imv_out = index_imv_all.select(
        [
            "intubation_episode_id",
            "encounter_block",
            "patient_id",
            "cohort_run_id",
            "ep_num",
            "index_class",
            "index_qualified",
            "t0_dttm",
            "window_start",
            "window_end",
            "list_hospitalization_id",
            "no_lookback",
            "imv_charted",
            "first_charted_imv_dttm",
            "charting_delay_min",
        ]
    ).sort(["encounter_block", "ep_num"])

    index_imv_out.write_parquet(PHI_DIR / "index_imv.parquet")
    consort_index_df.write_csv(SHARE_DIR / "consort_index.csv")

    index_class_rates = index_class_counts.select(
        pl.lit(COHORT_RUN_ID).alias("cohort_run_id"),
        "index_class",
        pl.col("count").alias("n"),
        pl.col("pct").round(2).alias("pct_of_candidates"),
    )
    index_class_rates.write_csv(SHARE_DIR / "index_class_rates.csv")

    # charting_delay.csv -- binned, with every bin in the 1-9 range dropped rather than
    # merged into a neighbour (D26). Merging would move mass the reader cannot see move.
    _edges = [1, 5, 15, 30, 60, 120, 240, 480, 1440]
    _labels = ["0", "1-4", "5-14", "15-29", "30-59", "60-119", "120-239",
               "240-479", "480-1439", "1440+"]
    _q = index_imv_out.filter(pl.col("index_qualified"))
    _binned = (
        _q.filter(pl.col("charting_delay_min").is_not_null())
        .with_columns(bin=pl.col("charting_delay_min").cut(_edges, labels=_labels))
        .group_by("bin")
        .len()
        .rename({"len": "n"})
    )
    _kept = _binned.filter((pl.col("n") == 0) | (pl.col("n") >= 10))
    _dropped = _binned.height - _kept.height
    charting_delay_df = (
        _kept.with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            n_suppressed_bins=pl.lit(_dropped, dtype=pl.Int64),
        )
        .select(["cohort_run_id", "bin", "n", "n_suppressed_bins"])
        .with_columns(bin=pl.col("bin").cast(pl.String))
        .sort("bin")
    )
    charting_delay_df.write_csv(SHARE_DIR / "charting_delay.csv")

    print(f"index_imv.parquet      {index_imv_out.height:,} rows -> {PHI_DIR}")
    print(f"  of which qualified   {_q.height:,}   (N**)")
    print(f"  blocks               {_q.get_column('encounter_block').n_unique():,}")
    print(f"  patients             {_q.get_column('patient_id').n_unique():,}")
    print(f"consort_index.csv      {consort_index_df.height} steps -> {SHARE_DIR}")
    print(f"index_class_rates.csv  {index_class_rates.height} classes")
    print(f"charting_delay.csv     {charting_delay_df.height} bins, {_dropped} suppressed")
    print("\nCONSORT B")
    print(consort_index_df)
    print("\nindex class rates")
    print(index_class_rates)
    return


if __name__ == "__main__":
    app.run()
