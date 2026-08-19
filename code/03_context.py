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
def _(pl):
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

    return (normalize_category_columns,)


@app.cell
def _(mo):
    mo.md(
        """
        # 03 — what surrounds the index paralytic

        Two questions over independently configured windows, asked with the
        **same inclusive window predicate**:

        | | |
        |---|---|
        | **D** | did the device transition from non-IMV to IMV? |
        | **E** | was a sedative charted, and at what dose? |

        D detects a **transition, not a state** (P12). "Was IMV charted nearby" is
        satisfied by a patient who has been on the ventilator for a week — it reports the
        condition of the airway, not an event. A transition reports an event.

        The predicate is shared between D and E, while each analysis supplies its own
        configured bounds (P15). One implementation keeps both windows inclusive at their
        front and back boundaries without coupling their clinical definitions.

        Design: `docs/superpowers/specs/2026-08-10-paralytic-index-design.md` §7.4–7.5
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Configuration

        Every site-specific value is read from `config/config.json` and nothing is
        hard-coded against this site. `imv_window_before_minutes` and
        `imv_window_after_minutes` set D's asymmetric window, while
        `sedation_window_minutes` sets E's symmetric window. The
        sedative list, MAR actions, and offset bin widths are analysis constants rather than
        site parameters, so they live here in the notebook where a reader can see them.
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

    IMV_WINDOW_BEFORE_MINUTES = float(config["imv_window_before_minutes"])
    IMV_WINDOW_AFTER_MINUTES = float(config["imv_window_after_minutes"])
    SEDATION_WINDOW_MINUTES = float(config["sedation_window_minutes"])
    IMV_EXTENDED_WINDOW_MINUTES = 6 * 60
    IMV_EXTENDED_OFFSET_BIN_WIDTH = 30

    # P16. Sedation is a COVARIATE of the index paralytic, not a detector -- the question
    # is whether the paralytic was given as part of an induction or to a patient already
    # sedated. Benzodiazepine and opioid adjuncts were considered and declined: they blur
    # "induction happened here" with "this patient was comfortable".
    SEDATIVES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
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

    # Every configured bound must divide into a whole number of this shared analysis bin.
    # Bins are left-closed and right-open except the final bin, which includes the positive
    # boundary.
    OFFSET_BIN_WIDTH = 5

    _windows = {
        "imv_window_before_minutes": IMV_WINDOW_BEFORE_MINUTES,
        "imv_window_after_minutes": IMV_WINDOW_AFTER_MINUTES,
        "sedation_window_minutes": SEDATION_WINDOW_MINUTES,
    }
    assert all(_window > 0 for _window in _windows.values()), (
        "configured IMV and sedation window bounds must be positive"
    )
    assert all(
        (_window / OFFSET_BIN_WIDTH).is_integer()
        for _window in _windows.values()
    ), f"configured windows must divide into {OFFSET_BIN_WIDTH}-minute bins"

    print(f"site           : {SITE}")
    print(
        f"imv window     : -{IMV_WINDOW_BEFORE_MINUTES:.0f} / "
        f"+{IMV_WINDOW_AFTER_MINUTES:.0f} min"
    )
    print(f"sedation window: +/- {SEDATION_WINDOW_MINUTES:.0f} min")
    print(f"sedatives      : {' | '.join(SEDATIVES)}")
    print(f"mar actions    : {' | '.join(MAR_ACTIONS)}")
    print(f"configured units: {MEDICATION_DOSE_UNITS}")
    print(f"dose bounds    : {MEDICATION_DOSE_UPPER_BOUNDS}")
    return (
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        IMV_EXTENDED_OFFSET_BIN_WIDTH,
        IMV_EXTENDED_WINDOW_MINUTES,
        IMV_WINDOW_AFTER_MINUTES,
        IMV_WINDOW_BEFORE_MINUTES,
        MAR_ACTIONS,
        MEDICATION_DOSE_UPPER_BOUNDS,
        MEDICATION_DOSE_UNITS,
        OFFSET_BIN_WIDTH,
        PHI_DIR,
        SEDATION_WINDOW_MINUTES,
        SEDATIVES,
        SHARE_DIR,
        TIMEZONE,
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
def _(mo):
    mo.md(
        """
        ## The three helpers this notebook is allowed to use on time

        `to_site_naive` is the only correct way to turn a clifpy timestamp column into a
        naive site-local one. `epoch_minutes` is the only way this notebook may turn a
        timestamp into a number of minutes. `in_window_expr` defines the inclusive
        predicate once; D and E pass their independent configured bounds. The
        first two are defined **locally and never
        imported** (spec §4) — a bug in a shared datetime helper corrupts every consumer
        identically, and identical corruption is the hardest kind to see.
        """
    )
    return


@app.cell
def _():
    def to_site_naive(series):
        """Strip clifpy's configured site timezone while preserving local wall time.

        `from_file(..., timezone=TIMEZONE)` has already normalized every timestamp to the
        site timezone. Defined locally, never imported (spec §4).
        """
        return series.dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def epoch_minutes(column):
        """Minutes since epoch, computed INSIDE polars, consulting no timezone at all.

        `datetime.timestamp()` on a site-naive value re-attaches the machine's zone; ten
        minutes across a DST fall-back would measure as seventy. Spec P19.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    return (epoch_minutes,)


@app.cell
def _(pl):
    def offset_minutes_expr(later_column, earlier_column):
        """Exact signed wall-clock minutes between two site-naive timestamps."""
        return (
            (pl.col(later_column) - pl.col(earlier_column))
            .dt.total_microseconds()
            / 60_000_000.0
        )

    return (offset_minutes_expr,)


@app.cell
def _(pl):
    def in_window_expr(offset_col, before_minutes, after_minutes):
        """An inclusive window, defined once and used by D and E (P15).

        Inclusive at both ends. A null offset means no candidate row was found at all and
        must not pass -- absence of a candidate is not presence at the boundary.
        """
        return (
            pl.col(offset_col).is_not_null()
            & (pl.col(offset_col) >= -before_minutes)
            & (pl.col(offset_col) <= after_minutes)
        )

    return (in_window_expr,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## D — the non-IMV → IMV transition

        ```
        a row is a TRANSITION when
              device_category == 'imv'
          AND ( no preceding row exists in the block
                OR preceding device_category != 'imv' )

        null is not imv     ->  null -> imv  IS a transition
        block opens on imv  ->  that first row IS a transition
        imv -> imv          ->  not a transition
        ```

        Computed on the **waterfalled** timeline, not raw `respiratory_support` (P13). Two
        reasons. *Mechanical:* a transition needs "the row before", and only the
        waterfall's gap-free hourly scaffold makes that well defined. *Clinical:* the
        waterfall relabels a null-device row to `imv` when the ventilator settings on it
        look like a ventilator, and that inference lands at or before the human device
        entry in every case measured — exactly zero delay in 77.3% of episodes, but 55 min
        at p95 and 540 min at p99. An intubation is a high-stress event and nobody stops to
        fill in the device field; the ventilator's settings reach the chart the moment it is
        connected.

        **No de-bouncing (P14).** The hourly scaffold means a brief non-IMV blip
        manufactures a spurious transition. `n_transitions_in_window` is published — as
        `step03__imv_transitions_per_window.csv` — so the size of that effect is measurable from the
        released output rather than merely asserted here, but no suppression rule is applied
        to it: that would be a second threshold with no evidence behind it. The published
        distribution is the evidence a later reader would need in order to argue for one.
        """
    )
    return


@app.cell
def _(pl):
    def is_transition_expr():
        """True where the device changes to IMV. Needs `_pos` and `_prev_device`.

        The `_prev_device.is_null()` term is load-bearing and is the reason this is a named
        function rather than an inline predicate. In polars, `shift(1) != 'imv'` evaluates
        to NULL -- not TRUE -- when the previous device is null, and a filter on NULL keeps
        nothing. Written naively, this rule would silently drop every patient whose record
        begins before anyone charted a device, which is where `null -> imv` transitions
        come from. Pinned by tests/test_imv_transition.py.

        `eq_missing` rather than `==` on the row's OWN device for the same reason at the
        other end: `pl.col('device_category') == 'imv'` is NULL, not FALSE, on a row whose
        device is null, and NULL AND TRUE is NULL -- so `is_transition` would come back
        null for exactly those rows rather than false. `filter(is_transition)` happens to
        drop them either way, which is what makes this the kind of defect that survives:
        the counts are right and the column is wrong, until something reads the column.
        `eq_missing` says the intended thing outright -- a null device is not IMV.
        """
        return (
            pl.col("device_category").eq_missing("imv")
            & (
                (pl.col("_pos") == 0)
                | pl.col("_prev_device").is_null()
                | (pl.col("_prev_device") != "imv")
            )
        )

    return (is_transition_expr,)


@app.cell
def _(is_transition_expr, normalize_category_columns, pl):
    def mark_transitions(waterfall):
        """Add `_pos`, `_prev_device`, `opens_block` and `is_transition` to the timeline.

        Sorted here rather than trusting the caller: the shift is meaningless unless the
        frame is in time order within each block, and `01` writing it sorted is a fact that
        could change without this notebook noticing.

        `opens_block` is recorded separately from `_prev_device` because both the
        block-opens-on-IMV case and the null-predecessor case give a null prior device, and
        the published table has to be able to tell them apart.
        """
        return (
            # maintain_order=True: after to_site_naive, the November DST fall-back
            # collapses two distinct instants onto one naive recorded_dttm, so a handful
            # of (encounter_block, recorded_dttm) keys carry two rows with different
            # device_category in this run. polars' default sort is unstable, which would
            # let _prev_device below -- and therefore transition detection -- differ
            # run to run at those rows. maintain_order makes the tiebreak the frame's own
            # input order, which is deterministic.
            normalize_category_columns(waterfall, "device_category")
            .sort(["encounter_block", "recorded_dttm"], maintain_order=True)
            .with_columns(
                _pos=pl.int_range(pl.len()).over("encounter_block"),
                _prev_device=pl.col("device_category").shift(1).over("encounter_block"),
            )
            .with_columns(
                opens_block=pl.col("_pos") == 0,
                is_transition=is_transition_expr(),
            )
        )

    return (mark_transitions,)


@app.cell
def _(pl):
    def nearest_transition_per_index(candidates):
        """Keep one nearest transition per index; an earlier transition wins a tie."""
        return (
            candidates.with_columns(_distance=pl.col("imv_offset_minutes").abs())
            .sort(
                ["index_paralytic_id", "_distance", "recorded_dttm"],
                maintain_order=True,
            )
            .unique(subset="index_paralytic_id", keep="first", maintain_order=True)
            .drop("_distance")
        )

    return (nearest_transition_per_index,)


@app.cell
def _(in_window_expr, nearest_transition_per_index, pl):
    def nearest_transition_distribution(
        candidates, before_minutes, after_minutes, bin_width, bin_labels
    ):
        """Select one nearest in-window transition per index and bin raw offsets."""
        _nearest = nearest_transition_per_index(
            candidates.filter(
                in_window_expr(
                    "imv_offset_minutes", before_minutes, after_minutes
                )
            )
        )
        _n_bins = len(bin_labels)
        _binned = (
            _nearest.with_columns(
                _b=(
                    ((pl.col("imv_offset_minutes") + before_minutes) // bin_width)
                    .cast(pl.Int32)
                    .clip(0, _n_bins - 1)
                )
            )
            .group_by("_b")
            .agg(n=pl.len())
        )
        _distribution = (
            pl.DataFrame(
                {"_b": list(range(_n_bins)), "offset_bin": bin_labels}
            )
            .with_columns(pl.col("_b").cast(pl.Int32))
            .join(_binned, on="_b", how="left")
            .with_columns(pl.col("n").fill_null(0))
            .sort("_b")
            .rename({"_b": "bin_order"})
        )
        assert _distribution.get_column("n").sum() == _nearest.height
        return _distribution

    return (nearest_transition_distribution,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Loading the two inputs, and refusing to mix cohort runs

        `index_paralytic.parquet` from `02` is the spine; `cohort_resp_waterfall.parquet`
        from `01` is the timeline the transition is read off. Both are keyed on
        `encounter_block`, which is seeded from a row index — so a re-extract renumbers
        every block and joining an index artifact from one run to a waterfall from another
        produces a table that is silently wrong. The embedded `cohort_run_id` makes that
        loud while still permitting a legitimate index block with no respiratory rows.
        """
    )
    return


@app.cell
def _(PHI_DIR, normalize_category_columns, pl):
    index_paralytic = pl.read_parquet(PHI_DIR / "step02__index_paralytic.parquet")
    resp_waterfall = normalize_category_columns(
        pl.read_parquet(PHI_DIR / "step01__cohort_resp_waterfall.parquet"),
        "device_category",
    )

    COHORT_RUN_ID = index_paralytic.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"index_paralytic carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    _waterfall_run_ids = resp_waterfall.get_column("cohort_run_id").unique().to_list()
    assert not _waterfall_run_ids or _waterfall_run_ids == [COHORT_RUN_ID], (
        "index_paralytic and cohort_resp_waterfall carry different cohort_run_ids; "
        "re-run 01 and 02 together"
    )

    # Missing timeline rows are now a valid clinical/data state: cohort entry depends on
    # a paralytic administration, not on IMV charting. Those blocks become
    # `no_device_record` below rather than being treated as stale artifacts.
    _blocks_missing = (
        index_paralytic.join(
            resp_waterfall.select("encounter_block").unique(), on="encounter_block", how="anti"
        )
        .get_column("encounter_block")
        .n_unique()
    )
    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"index paralytics  : {index_paralytic.height:,}")
    print(f"waterfall rows    : {resp_waterfall.height:,}")
    print(f"blocks without respiratory rows: {_blocks_missing:,}")
    return COHORT_RUN_ID, index_paralytic, resp_waterfall


@app.cell
def _(mo):
    mo.md(
        r"""
        ### `context_d` — one row per index paralytic, with its transition or its reason

        The whole timeline is marked, the transitions are pulled out, and each is offset
        against every index paralytic in the same block. Those inside the configured IMV
        window are
        candidates; the **earliest** of them is taken, not the nearest to `t` — "first" is
        what was asked for, and the two differ whenever a transition precedes `t` and
        another follows it.

        An index paralytic with no transition in the window gets a **reason**, and the
        three reasons are different findings rather than one absence:

        | reason | meaning |
        |---|---|
        | `already_on_imv` | the device at `t` was already IMV — the airway was secured earlier |
        | `no_transition_in_window` | the device at `t` was not IMV and nothing changed nearby |
        | `no_device_record` | no waterfall row at or before `t` at all |

        The device state at `t` comes from a backward as-of join keyed on the block, and
        the left frame is sorted on `t_dttm` here rather than trusting sortedness to have
        survived the earlier join.
        """
    )
    return


@app.cell
def _(
    IMV_WINDOW_AFTER_MINUTES,
    IMV_WINDOW_BEFORE_MINUTES,
    epoch_minutes,
    in_window_expr,
    index_paralytic,
    mark_transitions,
    pl,
    resp_waterfall,
):
    _marked = mark_transitions(resp_waterfall)
    imv_transitions = _marked.filter(pl.col("is_transition")).select(
        "encounter_block",
        "recorded_dttm",
        "opens_block",
        prior_device_category="_prev_device",
        _tr_min=epoch_minutes("recorded_dttm"),
    )
    print(f"transitions on the whole timeline : {imv_transitions.height:,}")

    _idx = index_paralytic.select(
        "index_paralytic_id", "encounter_block", "t_dttm", _t_min=epoch_minutes("t_dttm")
    )

    _candidates = (
        _idx.join(imv_transitions, on="encounter_block", how="inner")
        .with_columns(imv_offset_minutes=(pl.col("_tr_min") - pl.col("_t_min")).round(3))
        .filter(
            in_window_expr(
                "imv_offset_minutes",
                IMV_WINDOW_BEFORE_MINUTES,
                IMV_WINDOW_AFTER_MINUTES,
            )
        )
    )

    # The EARLIEST transition in the window, not the nearest to t. "First" is what was
    # asked for and the two differ whenever a transition precedes t and another follows it.
    _first = (
        _candidates.sort(["index_paralytic_id", "recorded_dttm"])
        .group_by("index_paralytic_id", maintain_order=True)
        .agg(
            imv_transition_dttm=pl.col("recorded_dttm").first(),
            imv_offset_minutes=pl.col("imv_offset_minutes").first(),
            prior_device_category=pl.col("prior_device_category").first(),
            transition_opens_block=pl.col("opens_block").first(),
            n_transitions_in_window=pl.len(),
        )
    )

    # Device state at t, for the already_on_imv reason: the most recent waterfall row at or
    # before t, by backward as-of join keyed on the block. Both sides are sorted on their
    # own as-of key here rather than relying on sortedness having survived the select above.
    _state = (
        _idx.sort("t_dttm")
        .join_asof(
            _marked.sort("recorded_dttm").select(
                "encounter_block", "recorded_dttm", _state_device="device_category"
            ),
            left_on="t_dttm",
            right_on="recorded_dttm",
            by="encounter_block",
            strategy="backward",
        )
        .select("index_paralytic_id", "_state_device", _has_row=pl.col("recorded_dttm").is_not_null())
    )

    context_d = (
        index_paralytic.join(_first, on="index_paralytic_id", how="left")
        .join(_state, on="index_paralytic_id", how="left")
        .with_columns(
            imv_transition=pl.col("imv_transition_dttm").is_not_null(),
            n_transitions_in_window=pl.col("n_transitions_in_window").fill_null(0).cast(pl.Int32),
        )
        .with_columns(
            no_transition_reason=pl.when(pl.col("imv_transition"))
            .then(pl.lit(None, dtype=pl.String))
            .when(~pl.col("_has_row").fill_null(False))
            .then(pl.lit("no_device_record"))
            .when(pl.col("_state_device") == "imv")
            .then(pl.lit("already_on_imv"))
            .otherwise(pl.lit("no_transition_in_window"))
        )
        .drop(["_state_device", "_has_row"])
    )

    _bad = context_d.filter(
        pl.col("imv_transition")
        & (
            (pl.col("imv_offset_minutes") < -IMV_WINDOW_BEFORE_MINUTES)
            | (pl.col("imv_offset_minutes") > IMV_WINDOW_AFTER_MINUTES)
        )
    )
    assert _bad.height == 0, f"{_bad.height:,} transitions sit outside the window"
    assert context_d.filter(
        pl.col("imv_transition") & pl.col("no_transition_reason").is_not_null()
    ).height == 0, "a detected transition also carries a no_transition_reason"
    assert context_d.filter(
        ~pl.col("imv_transition") & pl.col("no_transition_reason").is_null()
    ).height == 0, "a non-detection carries no reason"
    assert context_d.height == index_paralytic.height, "the join changed the row count"

    print(f"index paralytics with a transition in -{IMV_WINDOW_BEFORE_MINUTES:.0f}/"
          f"+{IMV_WINDOW_AFTER_MINUTES:.0f} min : "
          f"{context_d.get_column('imv_transition').sum():,} / {context_d.height:,} "
          f"({100 * context_d.get_column('imv_transition').mean():.1f}%)")
    print(context_d.group_by("no_transition_reason").agg(n=pl.len()).sort("n", descending=True))
    return context_d, imv_transitions


@app.cell
def _(mo):
    mo.md(
        """
        ### `step03__imv_transition_summary.csv`

        The transition rate and the full reason breakdown, as a partition of every index
        paralytic. The four categories are laid out as a fixed grid and left-joined onto the
        counts, so a category that never occurred is published as an explicit **zero**
        rather than being absent — "this never happened" and "this is missing" are different
        statements, and `no_device_record` is expected to be rare or absent at a site whose
        cohort requires an IMV row.
        """
    )
    return


@app.cell
def _(SHARE_DIR, context_d, pl, publish):
    # A fixed grid of the four outcomes, so a category that never occurred is published as
    # an explicit zero rather than silently missing. The join key is a filled label because
    # a null key does not match itself in a polars join; the null is restored afterwards.
    _counts = (
        context_d.with_columns(
            _reason=pl.col("no_transition_reason").fill_null("(transition)")
        )
        .group_by(["imv_transition", "_reason"])
        .agg(n=pl.len(), n_blocks=pl.col("encounter_block").n_unique())
    )
    _grid = pl.DataFrame(
        {
            "imv_transition": [True, False, False, False],
            "_reason": [
                "(transition)",
                "already_on_imv",
                "no_transition_in_window",
                "no_device_record",
            ],
        },
        schema={"imv_transition": pl.Boolean, "_reason": pl.String},
    )
    transition_summary = (
        _grid.join(_counts, on=["imv_transition", "_reason"], how="left")
        .with_columns(
            pl.col("n").fill_null(0),
            pl.col("n_blocks").fill_null(0),
            no_transition_reason=pl.when(pl.col("_reason") == "(transition)")
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col("_reason")),
        )
        .select("imv_transition", "no_transition_reason", "n", "n_blocks")
        # Tiebreak so the row order is byte-identical across runs: polars' sort is
        # unstable and two reasons with equal n would otherwise swap between runs.
        .sort(
            ["n", "imv_transition", "no_transition_reason"],
            descending=[True, False, False],
            nulls_last=True,
        )
    )
    publish(
        transition_summary,
        SHARE_DIR / "step03__imv_transition_summary.csv",
        "step03__imv_transition_summary",
    )
    return (transition_summary,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `step03__imv_prior_device.csv` — what the airway was immediately before

        P12: block-opens-on-IMV and a null-device predecessor both give a null prior device.
        The published category names distinguish those cases directly, while
        `transition_opens_block` remains available for machine readers.
        """
    )
    return


@app.cell
def _(SHARE_DIR, context_d, pl, publish):
    # P12: give the two null-predecessor states distinct human-readable labels.
    prior_device = (
        context_d.filter(pl.col("imv_transition"))
        .with_columns(
            prior_device_category=pl.when(pl.col("prior_device_category").is_not_null())
            .then(pl.col("prior_device_category"))
            .when(pl.col("transition_opens_block"))
            .then(pl.lit("(block opens on IMV)"))
            .otherwise(pl.lit("(prior row device not charted)"))
        )
        .group_by(["prior_device_category", "transition_opens_block"])
        .agg(n=pl.len())
        # Tiebreak for byte-identical row order across runs; polars' sort is unstable.
        .sort(
            ["n", "prior_device_category", "transition_opens_block"],
            descending=[True, False, False],
        )
    )
    publish(
        prior_device,
        SHARE_DIR / "step03__imv_prior_device.csv",
        "step03__imv_prior_device",
    )
    return (prior_device,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `fig_D1__imv_transition_offset.csv` — where in the window the transition sat

        Five-minute bins across the configured IMV window, left-closed and right-open
        except the last, which includes the positive boundary. Every bin
        is emitted, including the empty ones — an explicit published zero is what lets a
        reader tell an empty bin from a bin with no observations at all.
        """
    )
    return


@app.cell
def _(
    IMV_N_OFFSET_BINS,
    IMV_OFFSET_BIN_LABELS,
    IMV_WINDOW_BEFORE_MINUTES,
    OFFSET_BIN_WIDTH,
    SHARE_DIR,
    context_d,
    pl,
    publish,
):
    _binned = (
        context_d.filter(pl.col("imv_transition"))
        .with_columns(
            _b=(
                ((pl.col("imv_offset_minutes") + IMV_WINDOW_BEFORE_MINUTES) // OFFSET_BIN_WIDTH)
                .cast(pl.Int32)
                .clip(0, IMV_N_OFFSET_BINS - 1)
            )
        )
        .group_by("_b")
        .agg(n=pl.len())
    )
    offset_distribution = (
        pl.DataFrame(
            {"_b": list(range(IMV_N_OFFSET_BINS)), "offset_bin": IMV_OFFSET_BIN_LABELS}
        )
        .with_columns(pl.col("_b").cast(pl.Int32))
        .join(_binned, on="_b", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .sort("_b")
        .rename({"_b": "bin_order"})
    )
    publish(
        offset_distribution,
        SHARE_DIR / "fig_D1__imv_transition_offset.csv",
        "fig_D1__imv_transition_offset",
    )
    return (offset_distribution,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `step03__imv_transitions_per_window.csv` — how many transitions the window contained

        This is the table P14 rests on. Declining to de-bounce is only defensible if the
        size of the effect being declined is **measurable from the released output**, and
        `n_transitions_in_window` is that measurement: how many distinct non-IMV → IMV
        transitions fell inside the configured IMV window, for the index paralytics
        that had at least one. A count of 1 is an unambiguous airway event. A count of 2 or
        more is either a genuine extubation-and-reintubation inside the hour or the hourly
        scaffold blipping off IMV and back — this table does not distinguish them, and does
        not try to; it bounds how much room there is for the ambiguity to matter.

        The rows run contiguously from 1 to the observed maximum so that a value that never
        occurred is published as an explicit **zero** rather than being absent.
        """
    )
    return


@app.cell
def _(SHARE_DIR, context_d, pl, publish):
    _observed = (
        context_d.filter(pl.col("imv_transition"))
        .group_by("n_transitions_in_window")
        .agg(n=pl.len())
    )
    # Contiguous from 1 to the observed maximum: a value that never occurred is published
    # as an explicit zero rather than being absent from the table. At a site where no
    # index paralytic has a transition in window at all, `_observed` is empty and
    # `.max()` returns None -- `int(None)` would raise TypeError here, after
    # step01__consort_cohort.csv, step01__cohort_qc.csv,
    # step03__imv_transition_summary.csv and fig_D1__imv_transition_offset.csv are
    # already published. Guard it: publish the
    # well-formed, zero-row table instead of crashing partway through the run.
    if _observed.height == 0:
        print("no index paralytic has an IMV transition in window at this site -- "
              "publishing step03__imv_transitions_per_window.csv with zero rows")
        transitions_in_window = _observed.with_columns(
            pl.col("n_transitions_in_window").cast(pl.Int32)
        )
    else:
        _max_in_window = int(
            context_d.filter(pl.col("imv_transition"))
            .get_column("n_transitions_in_window")
            .max()
        )
        transitions_in_window = (
            pl.DataFrame({"n_transitions_in_window": list(range(1, _max_in_window + 1))})
            .with_columns(pl.col("n_transitions_in_window").cast(pl.Int32))
            .join(_observed, on="n_transitions_in_window", how="left")
            .with_columns(pl.col("n").fill_null(0))
            .sort("n_transitions_in_window")
        )
    publish(
        transitions_in_window,
        SHARE_DIR / "step03__imv_transitions_per_window.csv",
        "step03__imv_transitions_per_window",
    )
    return (transitions_in_window,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `fig_D2__imv_transition_offset_6h.csv` — nearest transition across six hours

        D.2 is a sensitivity view and does not change D.1, `imv_transition`, or any downstream
        cohort definition. For each index paralytic it selects the nearest transition on the
        same waterfalled timeline within an inclusive +/-6-hour window. An exact-distance tie
        goes to the earlier transition. One index paralytic therefore contributes to at most
        one 30-minute bin.
        """
    )
    return


@app.cell
def _(
    IMV_EXTENDED_N_OFFSET_BINS,
    IMV_EXTENDED_OFFSET_BIN_LABELS,
    IMV_EXTENDED_OFFSET_BIN_WIDTH,
    IMV_EXTENDED_WINDOW_MINUTES,
    SHARE_DIR,
    imv_transitions,
    index_paralytic,
    nearest_transition_distribution,
    offset_minutes_expr,
    pl,
    publish,
):
    _candidates = (
        index_paralytic.select(
            "index_paralytic_id",
            "encounter_block",
            "t_dttm",
        )
        .join(imv_transitions, on="encounter_block", how="inner")
        .with_columns(
            imv_offset_minutes=offset_minutes_expr(
                "recorded_dttm", "t_dttm"
            )
        )
    )
    d2_offset_distribution = nearest_transition_distribution(
        _candidates,
        IMV_EXTENDED_WINDOW_MINUTES,
        IMV_EXTENDED_WINDOW_MINUTES,
        IMV_EXTENDED_OFFSET_BIN_WIDTH,
        IMV_EXTENDED_OFFSET_BIN_LABELS,
    )
    assert d2_offset_distribution.height == IMV_EXTENDED_N_OFFSET_BINS
    publish(
        d2_offset_distribution,
        SHARE_DIR / "fig_D2__imv_transition_offset_6h.csv",
        "fig_D2__imv_transition_offset_6h",
    )
    return (d2_offset_distribution,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## E — sedation in its configured window

        The same inclusive predicate as D (P15), supplied with E's independent
        `sedation_window_minutes`, is applied to `medication_admin_intermittent` over the
        five induction agents.

        Every `given` administration in the configured unit is kept, not just the nearest
        per agent (P17). The superseded design deduplicated by `med_category` because
        it was building a rank ladder, where one patient redosed six times would have dominated a
        distribution of ranks. This study publishes an offset *histogram*, where every
        administration is a legitimate observation of when sedation was charted —
        deduplicating would delete the redosing pattern the histogram exists to show.

        `med_dose` and `med_dose_unit` are retained exactly. Each agent uses the one unit
        selected in `config["medication_dose_units"]`; no conversion or relabeling occurs.

        ### What E's counts count: PAIRS, not administrations

        The join is on `encounter_block`, and a block holds up to twelve index paralytics
        (`step02__index_paralytics_per_block.csv`). A
        single physical administration that falls inside two index windows therefore
        contributes **two** rows — once to each window. That is correct and intended: the
        administration genuinely happened inside both configured windows, and the
        same fan-out is what `02`'s bridge relies on. Deduplicating would have to pick one
        index paralytic to attribute it to, and there is no principled way to choose.

        Therefore every count E publishes remains a count of **(index paralytic,
        administration) pairs**. Calling that column `n` and its axis "administrations"
        could overstate the number of physical administrations, so the published column is named
        **`n_admin_windows`** and E.1's y-axis and E.2's row labels say the same. A patient
        redosed inside a block with several index paralytics contributes more than once, on
        purpose, and the column name is where a reader finds that out.
        """
    )
    return


@app.cell
def _(
    DATA_DIR,
    FILETYPE,
    MAR_ACTIONS,
    MEDICATION_DOSE_UPPER_BOUNDS,
    MEDICATION_DOSE_UNITS,
    MedicationAdminIntermittent,
    PHI_DIR,
    SEDATION_WINDOW_MINUTES,
    SEDATIVES,
    TIMEZONE,
    context_d,
    epoch_minutes,
    in_window_expr,
    medication_dose_eligible_expr,
    normalize_category_columns,
    pl,
    to_site_naive,
):
    # The bridge again -- 03 reaches the medication table by hospitalization_id and drops
    # the column at the join, exactly as 02 does (P5). cohort_index is re-read here rather
    # than threaded through index_paralytic, which deliberately carries no hospitalization.
    _cohort_index = pl.read_parquet(PHI_DIR / "step01__cohort_index.parquet")
    _bridge = (
        _cohort_index.select(["encounter_block", "list_hospitalization_id"])
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    _hosp_ids = _bridge.get_column("hospitalization_id").unique().to_list()

    _sed = MedicationAdminIntermittent.from_file(
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
        filters={"hospitalization_id": _hosp_ids},
    )

    _sed_lower = normalize_category_columns(
        pl.from_pandas(
            _sed.df.assign(admin_dttm=lambda d: to_site_naive(d["admin_dttm"]))
        ),
        "med_category",
        "mar_action_category",
    ).with_columns(
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
    _sedative_all = _sed_lower.filter(pl.col("med_category").is_in(SEDATIVES))
    _configured_unit = pl.col("med_category").replace_strict(MEDICATION_DOSE_UNITS)
    _wrong_unit_rows = _sedative_all.filter(
        ~pl.col("med_dose_unit").eq_missing(_configured_unit)
    )
    _configured_sedative_all = _sedative_all.filter(
        pl.col("med_dose_unit") == _configured_unit
    )
    _eligible_dose = medication_dose_eligible_expr(
        MEDICATION_DOSE_UNITS, MEDICATION_DOSE_UPPER_BOUNDS
    )
    _ineligible_dose_rows = _configured_sedative_all.filter(~_eligible_dose)
    _eligible_sedative_all = _configured_sedative_all.filter(_eligible_dose)
    _seen = _sedative_all.group_by(["med_category", "mar_action_category"]).agg(n=pl.len())
    _missing = sorted(set(SEDATIVES) - set(_sedative_all.get_column("med_category").unique()))
    _dropped_by_action_filter = (
        _eligible_sedative_all.group_by("med_category")
        .agg(n_total=pl.len())
        .join(
            _eligible_sedative_all.filter(
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

    sed_admin = (
        _eligible_sedative_all.filter(
            pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(_bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")
    )

    assert "hospitalization_id" not in sed_admin.columns, "the bridge leaked its key"

    # Post-filter reporting, kept alongside the pre-filter probe above -- this is what
    # actually feeds every downstream distribution, so it stays visible too.
    print(f"wrong-unit rows skipped  : {_wrong_unit_rows.height:,}")
    if _wrong_unit_rows.height:
        print(
            _wrong_unit_rows.group_by(["med_category", "med_dose_unit"])
            .agg(n=pl.len())
            .sort("n", descending=True)
        )
    print(f"ineligible-dose rows skipped: {_ineligible_dose_rows.height:,}")
    if _ineligible_dose_rows.height:
        print(
            _ineligible_dose_rows.group_by(["med_category", "med_dose_unit"])
            .agg(n=pl.len())
            .sort("n", descending=True)
        )
    print(f"sedative administrations : {sed_admin.height:,}")
    print("\nvalue_counts seen, by (med_category, mar_action_category), BEFORE the action filter:")
    print(_seen.sort("n", descending=True))
    print("\nrows dropped by the mar_action_category filter, per agent:")
    print(_dropped_by_action_filter)
    print("\nvalue_counts, by (med_category, mar_action_category), AFTER unit/action filters:")
    print(
        sed_admin.group_by(["med_category", "mar_action_category"])
        .agg(n=pl.len())
        .sort("n", descending=True)
    )
    if _missing:
        print(f"\nNOT PRESENT AT THIS SITE: {', '.join(_missing)}")
    assert sed_admin.height > 0, (
        "no administration matched the sedative list at all -- compare the value_counts "
        "above against the mCIDE med_category list before trusting a zero."
    )

    # ONE ROW PER (index paralytic, administration) PAIR, not per administration. The join
    # is on encounter_block, and a block holds up to twelve index paralytics
    # (step02__index_paralytics_per_block.csv), so a single physical administration that lies inside two
    # index windows produces two rows. That
    # fan-out is intended -- the administration genuinely belongs to both windows, the same
    # reasoning 02's bridge uses -- but it means every count derived from this frame is a
    # count of PAIRS. The published columns are named `n_admin_windows` for that reason.
    sed_in_window = (
        context_d.select(
            "index_paralytic_id", "encounter_block", _t_min=epoch_minutes("t_dttm")
        )
        .join(
            sed_admin.with_columns(_s_min=epoch_minutes("admin_dttm")),
            on="encounter_block",
            how="inner",
        )
        .with_columns(_offset_minutes_raw=pl.col("_s_min") - pl.col("_t_min"))
        .filter(
            in_window_expr(
                "_offset_minutes_raw",
                SEDATION_WINDOW_MINUTES,
                SEDATION_WINDOW_MINUTES,
            )
        )
        .with_columns(offset_minutes=pl.col("_offset_minutes_raw").round(3))
        .select(
            "index_paralytic_id",
            "encounter_block",
            "med_category",
            "admin_dttm",
            "offset_minutes",
            "med_dose",
            "med_dose_unit",
            "mar_action_category",
        )
    )

    # hospitalization_id is dropped at the bridge (P5), so the finest identity available
    # for a physical administration is the block plus the charted row itself.
    _admin_identity = [
        "encounter_block",
        "admin_dttm",
        "med_category",
        "med_dose",
        "med_dose_unit",
        "mar_action_category",
    ]
    _distinct_admins = sed_in_window.select(_admin_identity).unique().height
    _distinct_pairs = sed_in_window.select(
        "index_paralytic_id", *_admin_identity
    ).unique().height
    print(
        f"(index paralytic, administration) pairs in a window : {sed_in_window.height:,}"
    )
    _window_fanout = _distinct_pairs - _distinct_admins
    _duplicate_source_pairs = sed_in_window.height - _distinct_pairs
    if sed_in_window.height:
        print(
            f"distinct administration identities behind them      : {_distinct_admins:,}\n"
            f"additional pairs from one identity in multiple windows: {_window_fanout:,}\n"
            f"duplicate source rows within the same pair identity   : {_duplicate_source_pairs:,}"
        )
    else:
        print("distinct administration identities behind them      : 0")
    return sed_admin, sed_in_window


@app.cell
def _(mo):
    mo.md(
        r"""
        ### `index_context` — the canonical artifact, one row per index paralytic

        `context_d` gains E's columns and nothing else changes: the row count is asserted
        unchanged, so every index paralytic keeps its record whether or not sedation was
        found.

        `sedatives` and `sedative_agents` are written as **empty arrays, never nulls**, for
        an index paralytic with no sedation in the window. A null in a canonical artifact is
        ambiguous between "nothing was given" and "this was not processed"; an empty array
        says the first and only the first. `n_sedative_admins` is filled to a real `0` for
        the same reason.

        `nearest_sedative_med` is the single nearest administration by |offset|, kept as a
        convenience column beside — not instead of — the full `sedatives` list. Ties on an
        identical |offset| break alphabetically on `med_category` so the column is
        byte-identical across runs.
        """
    )
    return


@app.cell
def _(context_d, pl, sed_in_window):
    _nearest = (
        sed_in_window.with_columns(_abs=pl.col("offset_minutes").abs())
        # med_category breaks a tie on identical |offset| alphabetically, so the column is
        # byte-identical across runs.
        .sort(["index_paralytic_id", "_abs", "med_category"])
        .group_by("index_paralytic_id", maintain_order=True)
        .agg(
            nearest_sedative_med=pl.col("med_category").first(),
            nearest_sedative_offset_min=pl.col("offset_minutes").first(),
        )
    )

    _agg = sed_in_window.group_by("index_paralytic_id").agg(
        n_sedative_admins=pl.len(),
        sedative_agents=pl.col("med_category").unique().sort(),
        sedatives=pl.struct(
            med_category="med_category",
            admin_dttm="admin_dttm",
            offset_minutes="offset_minutes",
            med_dose="med_dose",
            med_dose_unit="med_dose_unit",
            mar_action_category="mar_action_category",
        ),
    )

    index_context = (
        context_d.join(_agg, on="index_paralytic_id", how="left")
        .join(_nearest, on="index_paralytic_id", how="left")
        .with_columns(
            n_sedative_admins=pl.col("n_sedative_admins").fill_null(0).cast(pl.Int32),
            sedative_agents=pl.col("sedative_agents").fill_null([]),
            # An EMPTY array, not a null: the record is written for every index paralytic
            # so "nothing was given" and "this was not processed" stay distinguishable.
            sedatives=pl.col("sedatives").fill_null([]),
        )
        .with_columns(any_sedative=pl.col("n_sedative_admins") > 0)
        .sort(["encounter_block", "p_num"])
    )

    assert index_context.height == context_d.height, "the sedation join changed the row count"
    assert (
        index_context.filter(
            pl.col("any_sedative") & pl.col("nearest_sedative_med").is_null()
        ).height
        == 0
    ), "an index paralytic has sedation but no nearest agent"
    # The empty-array contract, asserted rather than assumed: a null here would be the
    # ambiguity the fill_null above exists to remove.
    assert (
        index_context.filter(
            pl.col("sedatives").is_null() | pl.col("sedative_agents").is_null()
        ).height
        == 0
    ), "an index paralytic carries a NULL sedative list where an empty array was required"

    print(
        f"index paralytics with sedation in window : "
        f"{index_context.get_column('any_sedative').sum():,} / {index_context.height:,} "
        f"({100 * index_context.get_column('any_sedative').mean():.1f}%)"
    )
    return (index_context,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Independent offset grids for D and E

        Each configured D.1/E window gets its own five-minute grid; the fixed D.2 sensitivity
        view gets a 30-minute grid across +/-6 hours. Bins are left-closed and right-open
        except the last, which includes the positive boundary. Labels are exported rather
        than rebuilt inside each figure, so a figure cannot drift from its source table.
        """
    )
    return


@app.cell
def _(
    IMV_EXTENDED_OFFSET_BIN_WIDTH,
    IMV_EXTENDED_WINDOW_MINUTES,
    IMV_WINDOW_AFTER_MINUTES,
    IMV_WINDOW_BEFORE_MINUTES,
    OFFSET_BIN_WIDTH,
    SEDATION_WINDOW_MINUTES,
):
    def offset_bin_grid(before_minutes, after_minutes, bin_width):
        """Build a signed grid whose final bin includes the positive boundary."""
        _n_bins_float = (before_minutes + after_minutes) / bin_width
        assert _n_bins_float.is_integer(), (
            f"-{before_minutes:g}/+{after_minutes:g} minutes does not divide into "
            f"{bin_width:g}-minute bins"
        )
        _n_bins = int(_n_bins_float)
        _edges = [
            -before_minutes + bin_width * i for i in range(_n_bins + 1)
        ]
        _labels = [
            f"[{_edges[i]:.0f},{_edges[i + 1]:.0f})" for i in range(_n_bins)
        ]
        _labels[-1] = f"[{_edges[-2]:.0f},{_edges[-1]:.0f}]"
        return _n_bins, _labels, int(before_minutes / bin_width)

    (
        IMV_N_OFFSET_BINS,
        IMV_OFFSET_BIN_LABELS,
        IMV_ZERO_BIN,
    ) = offset_bin_grid(
        IMV_WINDOW_BEFORE_MINUTES, IMV_WINDOW_AFTER_MINUTES, OFFSET_BIN_WIDTH
    )
    (
        SEDATION_N_OFFSET_BINS,
        SEDATION_OFFSET_BIN_LABELS,
        SEDATION_ZERO_BIN,
    ) = offset_bin_grid(
        SEDATION_WINDOW_MINUTES, SEDATION_WINDOW_MINUTES, OFFSET_BIN_WIDTH
    )
    (
        IMV_EXTENDED_N_OFFSET_BINS,
        IMV_EXTENDED_OFFSET_BIN_LABELS,
        IMV_EXTENDED_ZERO_BIN,
    ) = offset_bin_grid(
        IMV_EXTENDED_WINDOW_MINUTES,
        IMV_EXTENDED_WINDOW_MINUTES,
        IMV_EXTENDED_OFFSET_BIN_WIDTH,
    )
    return (
        IMV_EXTENDED_N_OFFSET_BINS,
        IMV_EXTENDED_OFFSET_BIN_LABELS,
        IMV_EXTENDED_ZERO_BIN,
        IMV_N_OFFSET_BINS,
        IMV_OFFSET_BIN_LABELS,
        IMV_ZERO_BIN,
        SEDATION_N_OFFSET_BINS,
        SEDATION_OFFSET_BIN_LABELS,
        SEDATION_ZERO_BIN,
        offset_bin_grid,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ### Configured-unit dose boundary

        The exact configured unit is enforced before window matching. Dose summaries
        retain the selected numeric value and unit without conversion or relabeling.
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
            print("DOSE exclusions:")
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
        ### Publishing E

        `index_context.parquet` is written first — the canonical artifact, PHI, never
        shared. Then four released tables, each at its true count (P21):
        `step03__sedation_summary.csv`, `fig_E1__sedation_offset.csv`,
        `fig_E2__sedation_dose_summary.csv`, and
        `step03__sedation_dose_raw_unit_counts.csv`.

        Every bin of the offset grid is emitted for every agent, including the empty ones: an
        explicit published zero is what lets a reader tell an empty bin from one with no
        observations at all.

        `n_in_configured_unit` reconciles to `n_admin_windows` by construction.
        """
    )
    return


@app.cell
def _(
    OFFSET_BIN_WIDTH,
    PHI_DIR,
    SEDATION_N_OFFSET_BINS,
    SEDATION_OFFSET_BIN_LABELS,
    SEDATION_WINDOW_MINUTES,
    SHARE_DIR,
    index_context,
    pl,
    publish,
    sed_in_window,
):
    index_context.write_parquet(PHI_DIR / "step03__index_context.parquet")
    print(f"step03__index_context.parquet   {index_context.height:,} rows -> {PHI_DIR}")

    sedation_summary = (
        index_context.with_columns(agent_set=pl.col("sedative_agents").list.join("+"))
        .with_columns(
            agent_set=pl.when(pl.col("agent_set") == "")
            .then(pl.lit("(none)"))
            .otherwise(pl.col("agent_set"))
        )
        .group_by(["any_sedative", "agent_set"])
        .agg(n=pl.len(), median_n_admins=pl.col("n_sedative_admins").median())
        # Tiebreak for byte-identical row order across runs. This table has many ties --
        # eleven of its fourteen agent_set rows have n below 10 -- so without it the
        # published CSV genuinely reorders between runs, which was observed.
        .sort(
            ["n", "any_sedative", "agent_set"], descending=[True, False, False]
        )
    )
    publish(
        sedation_summary,
        SHARE_DIR / "step03__sedation_summary.csv",
        "step03__sedation_summary",
    )

    _grid = (
        pl.DataFrame(
            {
                "bin_order": list(range(SEDATION_N_OFFSET_BINS)),
                "offset_bin": SEDATION_OFFSET_BIN_LABELS,
            }
        )
        .with_columns(pl.col("bin_order").cast(pl.Int32))
        .join(sed_in_window.select("med_category").unique(), how="cross")
    )

    _binned = (
        sed_in_window.with_columns(
            bin_order=(
                ((pl.col("offset_minutes") + SEDATION_WINDOW_MINUTES) // OFFSET_BIN_WIDTH)
                .cast(pl.Int32)
                .clip(0, SEDATION_N_OFFSET_BINS - 1)
            )
        )
        .group_by(["bin_order", "med_category"])
        .agg(n_admin_windows=pl.len())
    )

    # n_admin_windows, not n: this counts (index paralytic, administration) PAIRS, and an
    # administration inside two index windows is in it twice.
    sedation_offsets = (
        _grid.join(_binned, on=["bin_order", "med_category"], how="left")
        .with_columns(pl.col("n_admin_windows").fill_null(0))
        .sort(["med_category", "bin_order"])
    )
    publish(
        sedation_offsets,
        SHARE_DIR / "fig_E1__sedation_offset.csv",
        "fig_E1__sedation_offset",
    )
    return sedation_offsets, sedation_summary


@app.cell
def _(
    filter_doses_for_summary,
    MEDICATION_DOSE_UPPER_BOUNDS,
    MEDICATION_DOSE_UNITS,
    pl,
    prepare_configured_doses,
    SHARE_DIR,
    sed_in_window,
):
    (SHARE_DIR / "step03__sedation_dose_unit_corrections.csv").unlink(
        missing_ok=True
    )
    _before = (
        sed_in_window.group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.len(), median_dose=pl.col("med_dose").median())
        .sort(["med_category", "med_dose_unit"])
    )
    print("Configured doses -- n and median per (med_category, med_dose_unit):")
    print(_before)

    sedation_dose_converted = prepare_configured_doses(
        sed_in_window, MEDICATION_DOSE_UNITS
    )

    sedation_dose_summary_clean = filter_doses_for_summary(
        sedation_dose_converted,
        MEDICATION_DOSE_UPPER_BOUNDS,
    )

    return sedation_dose_converted, sedation_dose_summary_clean


@app.cell
def _(SHARE_DIR, pl, publish, sedation_dose_summary_clean):
    # P18 (amended): keyed on med_category ALONE, in the standardised unit.
    # interpolation="linear" on both quantiles, explicitly: polars' default is
    # "nearest", which at small n republishes a raw charted dose verbatim as the
    # statistic (n=3 -> p75 IS the largest of the three charted values). Linear
    # interpolation does not avoid that outcome, it only changes when it happens:
    # polars places the q-th quantile of n sorted values at the fractional index
    # (n-1)*q, and whenever that index is a whole number the "interpolated" value
    # IS one of the charted observations -- not a rare edge case, but guaranteed
    # whenever (n-1) is a multiple of 4, since p25, median and p75 then land at
    # indices (n-1)/4, (n-1)/2 and 3(n-1)/4 all at once. In those cases the
    # p25/median/p75 are specific charted doses, not synthesised values. Linear interpolation
    # buys smoother behaviour as n changes; it does not buy a guarantee of never
    # equaling an individual observation.
    sedation_dose = (
        sedation_dose_summary_clean.group_by("med_category")
        .agg(
            n_admin_windows=pl.len(),
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
        sedation_dose,
        SHARE_DIR / "fig_E2__sedation_dose_summary.csv",
        "fig_E2__sedation_dose_summary",
    )
    return (sedation_dose,)


@app.cell
def _(SHARE_DIR, pl, publish, sed_in_window):
    # Counts only, in the one configured unit retained for each medication.
    sedation_dose_units = (
        sed_in_window.group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.len())
        .sort(["med_category", "n"], descending=[False, True])
    )
    publish(
        sedation_dose_units,
        SHARE_DIR / "step03__sedation_dose_raw_unit_counts.csv",
        "step03__sedation_dose_raw_unit_counts",
    )
    return (sedation_dose_units,)


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

        Keyed on the configured charted unit. Other units were excluded before window
        matching and cannot enter this distribution.

        `n_total` equals `step03__sedation_dose_raw_unit_counts.csv`'s `n` for fully dosed groups. A
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
def _(SHARE_DIR, ecdf_by_group, pl, publish, sed_in_window):
    # The ECDF and unit-count table consume the same raw frame. A row here is an (index paralytic,
    # administration) pair, not a distinct administration: a sedative charted inside
    # two index paralytics' windows is counted in both, exactly as
    # fig_E2__sedation_dose_summary.csv's
    # n_admin_windows already is.
    sedation_dose_ecdf = ecdf_by_group(sed_in_window)

    # Reconciliation, asserted rather than trusted -- but asserted against the SAME
    # population ecdf_by_group actually counts. n_total is net of the nulls that
    # function drops, so comparing it to the unfiltered row count would turn a
    # documented, REPORTED condition (spec §4) into a fatal error at any site with a
    # single null dose. What must never differ is the count over the rows that DO
    # carry a dose: a mismatch there means the grouping keys drifted apart, which is
    # the bug this assert exists to catch.
    _expected = (
        sed_in_window.filter(
            pl.col("med_dose").is_not_null()
            & pl.col("med_dose").is_finite()
            & pl.col("med_dose_unit").is_not_null()
        )
        .group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.len())
        .sort(["med_category", "med_dose_unit"])
    )
    _got = (
        sedation_dose_ecdf.group_by(["med_category", "med_dose_unit"])
        .agg(n=pl.col("n_total").first())
        .sort(["med_category", "med_dose_unit"])
    )
    assert _expected.equals(_got), (
        "sedation_dose_ecdf n_total does not reconcile with the dosed rows of "
        f"sed_in_window:\nexpected:\n{_expected}\ngot:\n{_got}"
    )

    # The gap against step03__sedation_dose_raw_unit_counts.csv's own count: reported,
    # never fatal (spec §4).
    # That file counts every administration in the group; this one counts only those
    # carrying a dose, so where the two differ the difference IS the null count. A
    # group that is entirely null-dosed vanishes from the ECDF and shows n = 0 here
    # rather than disappearing silently.
    _units = (
        sed_in_window.group_by(["med_category", "med_dose_unit"])
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
            "  [sedation_dose_ecdf] n_total sits below "
            "step03__sedation_dose_raw_unit_counts.csv's n for the "
            "groups below -- the difference is rows carrying a null dose:"
        )
        print(_gap)

    publish(
        sedation_dose_ecdf,
        SHARE_DIR / "fig_E3__sedation_dose_ecdf.csv",
        "fig_E3__sedation_dose_ecdf",
    )
    return (sedation_dose_ecdf,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Figures D.1, E.1 and E.2

        All three read the **published CSVs and nothing else** (P21), so a figure cannot
        disagree with the table beside it.

        Form was chosen before color, and two of the three forms differ from the obvious
        one for reasons the data forced:

        * **E.1 is small multiples, not one multi-line chart.** Faceting one agent per
          panel puts every bin on its own mark and removes color from the identity job
          entirely: the panel title names the agent, so nobody is matching hues. (The
          panel count follows the agents actually charted at the site, not the five-agent
          `SEDATIVES` list -- one line per agent would overlap badly regardless of how
          many are present.)
        * **E.2 is faceted by the configured unit, not one shared axis.** `mg` and `mcg`
          on a single x-axis is the horizontal form of a dual-axis chart: the alignment of
          the two scales is arbitrary and the picture invents a comparison that is not in
          the data. One panel per unit, each with its own axis, is what P18 (amended) looks
          like drawn -- each agent appears exactly once, in its configured-unit panel.

        Color therefore does no identity work in any of the three, so all three use one hue
        (categorical slot 1) for the data and reserve the diamond marker for a published
        zero. Y-axes are **linear**: roughly half these cells are exactly zero, and a log
        axis cannot place zero on it at all.
        """
    )
    return


@app.cell
def _():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patheffects as path_effects
    import matplotlib.pyplot as plt

    return path_effects, plt


@app.cell
def _(mo):
    mo.md(
        """
        ### Marking a published zero, drawn the same way `02` draws it

        A count is zero exactly when polars computed zero. A bar's height cannot show that
        on its own: a zero-height bar is indistinguishable from a gap in the axis. So every
        figure below plots a **diamond** just above the baseline, in the series colour, for
        a published, exactly-zero count.

        This helper is a deliberate duplicate of `02`'s (spec §4 — nothing but
        `utils/suppress.py` is shared). The visual vocabulary is identical on purpose; the
        code is separate on purpose.
        """
    )
    return


@app.cell
def _():
    def mark_zero(ax, x, color):
        """A published, exactly-zero value: a diamond centered on the baseline.

        Placed at y=0 in DATA coordinates -- not scaled off `y_ref` or any other frame
        statistic. A marker scaled off the frame's max is only guaranteed smaller than a
        real bar while every real bar is at least that tall, which stopped being true the
        moment counts of 1..9 started being drawn (P21): a `y_ref * 0.03` marker on a
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
        ### Figure D.1 — where the non-IMV → IMV transition sits

        One series — index paralytics per five-minute bin — so there is no legend of series
        colours to read; the title names what is plotted and the legend carries only the
        zero-marker glyph. The dashed rule sits at `t`, so "the vent came first" is read off
        the rule rather than off a tick label.
        """
    )
    return


@app.cell
def _(
    FIG_DIR,
    IMV_N_OFFSET_BINS,
    IMV_OFFSET_BIN_LABELS,
    IMV_ZERO_BIN,
    SHARE_DIR,
    mark_zero,
    pl,
    plt,
):
    # Categorical slot 1. One series, so colour does no identity work here at all -- it is
    # the same blue that means "a count of index paralytics" in 02's figures.
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"

    figure_d1_df = pl.read_csv(SHARE_DIR / "fig_D1__imv_transition_offset.csv").sort("bin_order")

    _fig, _ax = plt.subplots(figsize=(11, 5.4))

    for _row in figure_d1_df.iter_rows(named=True):
        if _row["n"] > 0:
            _ax.bar([_row["bin_order"]], [_row["n"]], width=0.72, color=_BLUE)
        else:
            mark_zero(_ax, _row["bin_order"], _BLUE)

    _ax.set_xticks(list(range(IMV_N_OFFSET_BINS)))
    _ax.set_xticklabels(IMV_OFFSET_BIN_LABELS, rotation=90, fontsize=7, color=_MUTED)
    _ax.set_xlim(-0.8, IMV_N_OFFSET_BINS - 0.2)
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color=_GRID, linewidth=0.8)
    for _side in ("top", "right"):
        _ax.spines[_side].set_visible(False)
    _ax.set_xlabel(
        "minutes from the index paralytic  (negative = the vent came first)",
        color=_INK, labelpad=12,
    )
    _ax.set_ylabel("index paralytics", color=_INK)

    _ax.axvline(IMV_ZERO_BIN - 0.5, color=_INK, linestyle="--", linewidth=1)
    _ax.text(
        IMV_ZERO_BIN - 0.4, _ax.get_ylim()[1] * 0.96, "t\n(the index paralytic)",
        fontsize=8, va="top", color=_INK,
    )

    _handles = [
        _ax.plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                 label="published zero (measured, exactly 0)")[0],
    ]
    _ax.legend(handles=_handles, loc="upper right", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "D.1 — where the non-IMV to IMV transition sits relative to the index paralytic\n"
        "a transition, not a state: the airway changed here (spec P12)",
        color=_INK,
    )
    _fig.tight_layout()
    _fig.subplots_adjust(bottom=0.28)
    _fig.savefig(FIG_DIR / "fig_D1__imv_transition_offset.png", dpi=150)
    plt.close(_fig)
    print(f"fig_D1__imv_transition_offset.png -> {FIG_DIR}")
    return (figure_d1_df,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Figure D.2 — nearest non-IMV to IMV transition within six hours

        This wider sensitivity view uses the same transition definition as D.1 but selects
        the nearest transition in +/-6 hours and displays 30-minute bins. The dashed rule
        marks the index paralytic; negative offsets mean the transition came first.
        """
    )
    return


@app.cell
def _(
    FIG_DIR,
    IMV_EXTENDED_N_OFFSET_BINS,
    IMV_EXTENDED_OFFSET_BIN_LABELS,
    IMV_EXTENDED_ZERO_BIN,
    SHARE_DIR,
    d2_offset_distribution,
    mark_zero,
    pl,
    plt,
):
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"

    figure_d2_df = pl.read_csv(
        SHARE_DIR / "fig_D2__imv_transition_offset_6h.csv"
    ).sort("bin_order")
    assert figure_d2_df.to_dicts() == d2_offset_distribution.to_dicts()

    _fig, _ax = plt.subplots(figsize=(11, 5.4))
    for _row in figure_d2_df.iter_rows(named=True):
        if _row["n"] > 0:
            _ax.bar([_row["bin_order"]], [_row["n"]], width=0.72, color=_BLUE)
        else:
            mark_zero(_ax, _row["bin_order"], _BLUE)

    _ax.set_xticks(list(range(IMV_EXTENDED_N_OFFSET_BINS)))
    _ax.set_xticklabels(
        IMV_EXTENDED_OFFSET_BIN_LABELS, rotation=90, fontsize=7, color=_MUTED
    )
    _ax.set_xlim(-0.8, IMV_EXTENDED_N_OFFSET_BINS - 0.2)
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color=_GRID, linewidth=0.8)
    for _side in ("top", "right"):
        _ax.spines[_side].set_visible(False)
    _ax.set_xlabel(
        "minutes from the index paralytic  (negative = the vent transition came first)",
        color=_INK,
        labelpad=12,
    )
    _ax.set_ylabel("index paralytics", color=_INK)

    _ax.axvline(
        IMV_EXTENDED_ZERO_BIN - 0.5,
        color=_INK,
        linestyle="--",
        linewidth=1,
    )
    _ax.text(
        IMV_EXTENDED_ZERO_BIN - 0.4,
        _ax.get_ylim()[1] * 0.96,
        "t\n(the index paralytic)",
        fontsize=8,
        va="top",
        color=_INK,
    )
    _handles = [
        _ax.plot(
            [],
            [],
            marker="D",
            markersize=7,
            color="0.3",
            linestyle="None",
            label="published zero (measured, exactly 0)",
        )[0]
    ]
    _ax.legend(handles=_handles, loc="upper right", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "D.2 — nearest non-IMV to IMV transition within 6 hours of the index paralytic\n"
        "one nearest transition per index; 30-minute bins",
        color=_INK,
    )
    _fig.tight_layout()
    _fig.subplots_adjust(bottom=0.28)
    _fig.savefig(FIG_DIR / "fig_D2__imv_transition_offset_6h.png", dpi=150)
    plt.close(_fig)
    print(f"fig_D2__imv_transition_offset_6h.png -> {FIG_DIR}")
    return (figure_d2_df,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Figure E.1 — sedative administrations around the index paralytic

        One panel per agent on a shared bin grid and a **shared y-axis**, so the panels are
        comparable by eye — a per-panel y-scale would make a rare agent look as busy as a
        common one, which is the opposite of what this figure is for.

        Every administration in the window is a bar, not just the nearest per agent (P17):
        the redosing pattern is the thing the histogram exists to show, and deduplicating
        would delete it.

        An agent with a small total renders near the baseline on the shared axis -- at
        this site ketamine's peak bin is 3 against fentanyl's 316, so its real bars are a
        few pixels tall next to a panel of otherwise-visible zero-diamonds. That is the
        shared axis working as intended, not a missing agent, but a panel with no visible
        bar communicates nothing by itself. Each panel's own corner carries its true `n`
        and peak bin, read from this same published CSV, so the magnitude is on the page
        even where the bars can't show it.
        """
    )
    return


@app.cell
def _(
    FIG_DIR,
    SEDATION_N_OFFSET_BINS,
    SEDATION_OFFSET_BIN_LABELS,
    SEDATION_ZERO_BIN,
    SHARE_DIR,
    mark_zero,
    pl,
    plt,
):
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"

    figure_e1_df = pl.read_csv(SHARE_DIR / "fig_E1__sedation_offset.csv")
    _agents = sorted(figure_e1_df.get_column("med_category").unique().to_list())

    if not _agents:
        # No sedative administration falls inside any index paralytic's configured
        # sedation window at this site -- fig_E1__sedation_offset.csv is published with
        # zero rows (see the cross-join that builds it) and there is nothing to plot.
        # plt.subplots(0, 1, ...) below would raise; skip with a clear message instead.
        print(
            "fig_E1__sedation_offset.png skipped -- its source CSV has "
            "zero rows at this site (no sedative administration in any index "
            "paralytic's window)"
        )
    else:
        _fig, _axes = plt.subplots(
            len(_agents), 1, figsize=(11, 1.55 * len(_agents) + 2.6),
            sharex=True, sharey=True, squeeze=False,
        )
        _axes = [_a[0] for _a in _axes]

        for _ax, _agent in zip(_axes, _agents):
            _s = figure_e1_df.filter(pl.col("med_category") == _agent).sort("bin_order")

            for _row in _s.iter_rows(named=True):
                if _row["n_admin_windows"] > 0:
                    _ax.bar(
                        [_row["bin_order"]], [_row["n_admin_windows"]],
                        width=0.72, color=_BLUE,
                    )
                else:
                    mark_zero(_ax, _row["bin_order"], _BLUE)

            _ax.axvline(SEDATION_ZERO_BIN - 0.5, color=_INK, linestyle="--", linewidth=1)
            _ax.set_xlim(-0.8, SEDATION_N_OFFSET_BINS - 0.2)
            _ax.set_ylim(bottom=0)
            _ax.set_axisbelow(True)
            _ax.grid(axis="y", color=_GRID, linewidth=0.8)
            for _side in ("top", "right"):
                _ax.spines[_side].set_visible(False)
            # The panel title is the identity channel -- colour carries none of it.
            _ax.set_title(_agent, fontsize=9, loc="left", color=_INK)
            _ax.tick_params(axis="y", labelsize=8, colors=_MUTED)

            # On the shared y-axis a small-total agent's bars can be a few pixels tall
            # next to fentanyl's or propofol's -- correct, but a panel that shows no
            # visible bar communicates nothing on its own. This annotation carries the
            # panel's true magnitude, read from the same published frame the bars are
            # drawn from -- never recomputed -- so it cannot disagree with
            # fig_E1__sedation_offset.csv.
            _ax.text(
                0.01, 0.90,
                f"n = {_s['n_admin_windows'].sum():,}, peak = {_s['n_admin_windows'].max():,}",
                transform=_ax.transAxes, ha="left", va="top", fontsize=8, color=_INK,
            )

        _axes[-1].set_xticks(list(range(SEDATION_N_OFFSET_BINS)))
        _axes[-1].set_xticklabels(
            SEDATION_OFFSET_BIN_LABELS, rotation=90, fontsize=7, color=_MUTED
        )
        _axes[-1].set_xlabel(
            "minutes from the index paralytic  (dashed rule = t)", color=_INK
        )
        # PAIRS, not administrations -- an administration inside two index windows is
        # counted in both. Saying "administrations" here would overstate the drug given
        # by the fan-out.
        _axes[len(_axes) // 2].set_ylabel(
            "(index paralytic, administration) pairs", color=_INK
        )

        _handles = [
            _axes[0].plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                          label="published zero (measured, exactly 0)")[0],
        ]
        _axes[0].legend(handles=_handles, loc="upper right", fontsize=8, framealpha=0.9)
        _fig.suptitle(
            "E.1 — sedative administrations around the index paralytic, one panel per agent\n"
            "every administration in the window, not just the nearest per agent (P17), counted "
            "once per index window it falls in; shared y-axis",
            fontsize=11, color=_INK,
        )
        _fig.tight_layout()
        _fig.subplots_adjust(
            top=1 - 1.15 / (1.55 * len(_agents) + 2.6), bottom=0.20, hspace=0.62
        )
        _fig.savefig(FIG_DIR / "fig_E1__sedation_offset.png", dpi=150)
        plt.close(_fig)
        print(f"fig_E1__sedation_offset.png -> {FIG_DIR}")
    return (figure_e1_df,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Figure E.2 — sedative dose by agent and configured unit

        One panel per `med_dose_unit`, each with **its own x-axis**. Doses are
        retained only when they match the configured unit, with no conversion.
        Putting `mg` and `mcg` on a single shared axis would still draw a
        comparison that is not meaningful at a glance, so separate panels are kept even
        though standardisation means the units within a panel now genuinely agree.

        Each bar is the median, with a whisker to p25 and p75 and the median printed at the
        tip. `n_admin_windows` rides the row label, so the reader can see how much each row
        rests on — and it is labelled as pairs, not administrations, because that is what it
        counts.
        """
    )
    return


@app.cell
def _(FIG_DIR, SHARE_DIR, path_effects, pl, plt):
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _SECOND = "#52514e"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"
    _SURFACE = "#ffffff"

    figure_e2_df = pl.read_csv(SHARE_DIR / "fig_E2__sedation_dose_summary.csv")

    _units = sorted(figure_e2_df.get_column("med_dose_unit").unique().to_list())

    if not _units:
        # No sedative administration falls inside any index paralytic's window at this
        # site -- fig_E2__sedation_dose_summary.csv is published with zero rows and there is nothing to
        # plot. plt.subplots(0, 1, ...) below would raise; skip with a clear message.
        print(
            "fig_E2__sedation_dose_summary.png skipped -- its source CSV has zero rows at this "
            "site (no sedative administration in any index paralytic's window)"
        )
    else:
        _ratios = [
            max(1, figure_e2_df.filter(pl.col("med_dose_unit") == _u).height) for _u in _units
        ]
        _n_panels = len(_ratios)

        # height_ratios in row counts gives every panel the SAME row pitch, so a bar in
        # the one-row panel is not drawn twice as thick as a bar in the two-row panel --
        # thickness here is chrome and must not vary with how many units a panel holds.
        _FIG_H = 1.2 + 0.45 * sum(_ratios) + 0.78 * _n_panels
        _fig, _axes = plt.subplots(
            _n_panels, 1, figsize=(10, _FIG_H),
            gridspec_kw={"height_ratios": _ratios}, squeeze=False,
        )
        _axes = [_a[0] for _a in _axes]

        for _ax, _unit in zip(_axes, _units):
            _p = figure_e2_df.filter(pl.col("med_dose_unit") == _unit).sort("median_dose")
            _y = list(range(_p.height))
            _ax.barh(_y, _p.get_column("median_dose").to_list(), height=0.4, color=_BLUE)
            # The IQR whisker crosses the bar it belongs to, so it carries a 3px ring in
            # the surface colour -- the dataviz surface-ring rule for overlapping marks.
            # Without it the whisker reads as part of the fill and the bar looks like it
            # reaches p75.
            _ax.errorbar(
                _p.get_column("median_dose").to_list(),
                _y,
                xerr=[
                    (_p.get_column("median_dose") - _p.get_column("p25_dose")).to_list(),
                    (_p.get_column("p75_dose") - _p.get_column("median_dose")).to_list(),
                ],
                fmt="none", ecolor=_SECOND, elinewidth=1.4, capsize=4,
                path_effects=[
                    path_effects.withStroke(linewidth=3.4, foreground=_SURFACE),
                ],
            )
            for _i, _row in enumerate(_p.iter_rows(named=True)):
                # The value rides the bar TIP, set just above it: at the whisker end it
                # would be read as p75, and inside the fill it would be clipped by a
                # short bar.
                _ax.text(
                    _row["median_dose"], _i + 0.24, f"{_row['median_dose']:g}",
                    ha="center", va="bottom", fontsize=8, color=_SECOND,
                )
            _ax.set_yticks(_y)
            _ax.set_yticklabels(
                [
                    f"{_r['med_category']}  ({_r['n_admin_windows']:,} pairs)"
                    for _r in _p.iter_rows(named=True)
                ],
                fontsize=8, color=_INK,
            )
            _ax.set_ylim(-0.5, _p.height - 0.5)
            _ax.margins(x=0.12)
            _ax.set_xlim(left=0)
            _ax.set_axisbelow(True)
            _ax.grid(axis="x", color=_GRID, linewidth=0.8)
            for _side in ("top", "right", "left"):
                _ax.spines[_side].set_visible(False)
            _ax.tick_params(axis="x", labelsize=8, colors=_MUTED)
            _ax.tick_params(axis="y", length=0)
            # The panel title is the standardised unit, and the unit is the reason the
            # panel exists.
            _ax.set_title(
                f"standardised unit: {_unit}   ·   its own axis (P18)",
                fontsize=9, loc="left", color=_INK,
            )

        _axes[-1].set_xlabel(
            "standardised dose — median, with p25–p75 whiskers   ·   row counts are "
            "(index paralytic, administration) pairs",
            color=_INK,
        )

        _fig.suptitle(
            "E.2 — sedative dose by agent and standardised unit\n"
            "one panel per unit; raw units are in step03__sedation_dose_raw_unit_counts.csv (P18)\n"
            f"{figure_e2_df.height} agent row(s) published",
            fontsize=11, color=_INK,
        )
        _fig.tight_layout()
        _fig.subplots_adjust(top=1 - 1.15 / _FIG_H, hspace=1.15)
        _fig.savefig(FIG_DIR / "fig_E2__sedation_dose_summary.png", dpi=150)
        plt.close(_fig)
        print(f"fig_E2__sedation_dose_summary.png -> {FIG_DIR}")
    return (figure_e2_df,)


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"

    # Read the PUBLISHED csv, never the in-memory frame (P21).
    figure_e3_df = pl.read_csv(SHARE_DIR / "fig_E3__sedation_dose_ecdf.csv")

    _groups = (
        figure_e3_df.select("med_category", "med_dose_unit")
        .unique()
        .sort(["med_category", "med_dose_unit"])
        .rows()
    )

    if not _groups:
        # No sedative administration falls inside any index paralytic's window at
        # this site. plt.subplots(0, 1, ...) would raise; skip with a clear message.
        print(
            "fig_E3__sedation_dose_ecdf.png skipped -- its source CSV has zero "
            "rows at this site (no sedative administration in any index window)"
        )
    else:
        _n_panels = len(_groups)
        _FIG_H = 1.3 + 2.1 * _n_panels
        _fig, _axes = plt.subplots(
            _n_panels, 1, figsize=(9, _FIG_H), squeeze=False,
        )
        _axes = [_a[0] for _a in _axes]

        for _ax, (_cat, _unit) in zip(_axes, _groups):
            _p = figure_e3_df.filter(
                (pl.col("med_category") == _cat) & (pl.col("med_dose_unit") == _unit)
            ).sort("dose")
            _x = _p.get_column("dose").to_list()
            _y = _p.get_column("ecdf").to_list()
            _n_total = _p.get_column("n_total").first()

            # where="post": an ECDF is right-continuous -- F(x) holds from this charted
            # dose until the next one is reached. A plain line, or where="pre", draws
            # mass at doses nobody charted.
            _ax.step(_x, _y, where="post", color=_BLUE, linewidth=1.6)
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
            "dose, in the unit the site charted — panels do NOT share an axis (P41)   ·   "
            "n counts (index paralytic, administration) pairs",
            fontsize=9, color=_INK,
        )
        _fig.suptitle(
            "E.3 — sedative dose, empirical CDF by agent and charted unit\n"
            "one panel per (agent, raw charted unit); no unit conversion (P41)\n"
            f"{figure_e3_df.height} row(s) published",
            fontsize=11, color=_INK,
        )
        _fig.tight_layout()
        _fig.subplots_adjust(top=1 - 1.7 / _FIG_H, hspace=0.55)
        _fig.savefig(FIG_DIR / "fig_E3__sedation_dose_ecdf.png", dpi=150)
        plt.close(_fig)
        print(f"fig_E3__sedation_dose_ecdf.png -> {FIG_DIR}")
    return (figure_e3_df,)


if __name__ == "__main__":
    app.run()
