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
    from utils.suppress import MIN_CELL, publish, small_cell_mask

    return (
        MIN_CELL,
        MedicationAdminIntermittent,
        Path,
        json,
        mo,
        pl,
        publish,
        small_cell_mask,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # 03 — what surrounds the index paralytic

        Two questions over the same ±60 minutes, asked with the **same window predicate**:

        | | |
        |---|---|
        | **D** | did the device transition from non-IMV to IMV? |
        | **E** | was a sedative charted, and at what dose? |

        D detects a **transition, not a state** (P12). "Was IMV charted in ±60 min" is
        satisfied by a patient who has been on the ventilator for a week — it reports the
        condition of the airway, not an event. A transition reports an event.

        The window predicate is shared between D and E and is the single exception to this
        project's duplicate-don't-share posture (P15). Two implementations of an interval
        test drift at the boundary, and a one-row disagreement between "IMV was near" and
        "sedation was near" is invisible in aggregate and fatal to the joint reading.

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
        hard-coded against this site. `context_window_minutes` is the ±window both D and E
        measure against; the sedative list, the MAR actions and the offset bin width are
        analysis constants rather than site parameters, so they live here in the notebook
        where a reader can see them.
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

    CONTEXT_WINDOW_MINUTES = float(config["context_window_minutes"])

    # P16. Sedation is a COVARIATE of the index paralytic, not a detector -- the question
    # is whether the paralytic was given as part of an induction or to a patient already
    # sedated. Benzodiazepine and opioid adjuncts were considered and declined: they blur
    # "induction happened here" with "this patient was comfortable".
    SEDATIVES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
    MAR_ACTIONS = ["given", "bolus"]

    # 5-minute bins across the full 120 minutes: 24 bins, left-closed and right-open
    # except the last, which is closed so an offset of exactly +60 has a home.
    OFFSET_BIN_WIDTH = 5

    print(f"site           : {SITE}")
    print(f"window         : +/- {CONTEXT_WINDOW_MINUTES:.0f} min   (P15)")
    print(f"sedatives      : {' | '.join(SEDATIVES)}")
    print(f"mar actions    : {' | '.join(MAR_ACTIONS)}")
    return (
        CONTEXT_WINDOW_MINUTES,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        MAR_ACTIONS,
        OFFSET_BIN_WIDTH,
        PHI_DIR,
        SEDATIVES,
        SHARE_DIR,
        TIMEZONE,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ## The three helpers this notebook is allowed to use on time

        `to_site_naive` is the only correct way to turn a clifpy timestamp column into a
        naive site-local one. `epoch_minutes` is the only way this notebook may turn a
        timestamp into a number of minutes. `in_window_expr` is the ±window itself, defined
        once and used by both D and E. The first two are defined **locally and never
        imported** (spec §4) — a bug in a shared datetime helper corrupts every consumer
        identically, and identical corruption is the hardest kind to see.
        """
    )
    return


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Pinned by
        `tests/test_clifpy_tz_boundary.py`. Defined locally, never imported (spec §4).
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

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
    def in_window_expr(offset_col, window_minutes):
        """The +/- window, defined ONCE and used by both D and E (P15).

        Inclusive at both ends. A null offset means no candidate row was found at all and
        must not pass -- absence of a candidate is not presence at the boundary.
        """
        return (
            pl.col(offset_col).is_not_null()
            & (pl.col(offset_col) >= -window_minutes)
            & (pl.col(offset_col) <= window_minutes)
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
        manufactures a spurious transition. `n_transitions_in_window` is published so the
        size of that effect is measurable, but no suppression rule is applied — it would be
        a second threshold with no evidence behind it.
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
def _(is_transition_expr, pl):
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
            waterfall.sort(["encounter_block", "recorded_dttm"])
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
def _(mo):
    mo.md(
        """
        ## Loading the two inputs, and refusing to mix cohort runs

        `index_paralytic.parquet` from `02` is the spine; `cohort_resp_waterfall.parquet`
        from `01` is the timeline the transition is read off. Both are keyed on
        `encounter_block`, which is seeded from a row index — so a re-extract renumbers
        every block and joining an index artifact from one run to a waterfall from another
        produces a table that is silently wrong. The anti-join below is what makes that
        loud instead.
        """
    )
    return


@app.cell
def _(PHI_DIR, pl):
    index_paralytic = pl.read_parquet(PHI_DIR / "index_paralytic.parquet")
    resp_waterfall = pl.read_parquet(PHI_DIR / "cohort_resp_waterfall.parquet")

    COHORT_RUN_ID = index_paralytic.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"index_paralytic carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    # encounter_block is seeded from a row index, so a re-extract renumbers everything.
    # Joining an index artifact from one run to a waterfall from another produces a table
    # that is silently wrong: the ids match, the rows are real, and they describe different
    # patients. §8.
    _blocks_missing = (
        index_paralytic.join(
            resp_waterfall.select("encounter_block").unique(), on="encounter_block", how="anti"
        )
        .get_column("encounter_block")
        .n_unique()
    )
    assert _blocks_missing == 0, (
        f"{_blocks_missing:,} encounter_blocks in index_paralytic have no waterfall rows. "
        "The two artifacts are almost certainly from different cohort runs -- check "
        "cohort_run_id and re-run 01 and 02 together."
    )

    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"index paralytics  : {index_paralytic.height:,}")
    print(f"waterfall rows    : {resp_waterfall.height:,}")
    return COHORT_RUN_ID, index_paralytic, resp_waterfall


@app.cell
def _(mo):
    mo.md(
        r"""
        ### `context_d` — one row per index paralytic, with its transition or its reason

        The whole timeline is marked, the transitions are pulled out, and each is offset
        against every index paralytic in the same block. Those inside ±60 minutes are
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
    CONTEXT_WINDOW_MINUTES,
    epoch_minutes,
    in_window_expr,
    index_paralytic,
    mark_transitions,
    pl,
    resp_waterfall,
):
    _marked = mark_transitions(resp_waterfall)
    _transitions = _marked.filter(pl.col("is_transition")).select(
        "encounter_block",
        "recorded_dttm",
        "opens_block",
        prior_device_category="_prev_device",
        _tr_min=epoch_minutes("recorded_dttm"),
    )
    print(f"transitions on the whole timeline : {_transitions.height:,}")

    _idx = index_paralytic.select(
        "index_paralytic_id", "encounter_block", "t_dttm", _t_min=epoch_minutes("t_dttm")
    )

    _candidates = (
        _idx.join(_transitions, on="encounter_block", how="inner")
        .with_columns(imv_offset_minutes=(pl.col("_tr_min") - pl.col("_t_min")).round(3))
        .filter(in_window_expr("imv_offset_minutes", CONTEXT_WINDOW_MINUTES))
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
        pl.col("imv_transition") & (pl.col("imv_offset_minutes").abs() > CONTEXT_WINDOW_MINUTES)
    )
    assert _bad.height == 0, f"{_bad.height:,} transitions sit outside the window"
    assert context_d.filter(
        pl.col("imv_transition") & pl.col("no_transition_reason").is_not_null()
    ).height == 0, "a detected transition also carries a no_transition_reason"
    assert context_d.filter(
        ~pl.col("imv_transition") & pl.col("no_transition_reason").is_null()
    ).height == 0, "a non-detection carries no reason"
    assert context_d.height == index_paralytic.height, "the join changed the row count"

    print(f"index paralytics with a transition in +/-{CONTEXT_WINDOW_MINUTES:.0f} min : "
          f"{context_d.get_column('imv_transition').sum():,} / {context_d.height:,} "
          f"({100 * context_d.get_column('imv_transition').mean():.1f}%)")
    print(context_d.group_by("no_transition_reason").agg(n=pl.len()).sort("n", descending=True))
    return (context_d,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ### A partition hazard the row-level n≥10 rule does not close

        `index_paralytic_summary.csv` publishes `n_index` per `agent_label`, so the **total**
        number of index paralytics is already effectively public. Every table below
        partitions either that total (`imv_transition_summary.csv`) or the transition count
        inside it (`imv_prior_device.csv`, `imv_offset_distribution.csv`). When a partition
        of a public total has exactly **one** row withheld under the n≥10 rule, that row's
        value is recoverable as *total minus the published rows* — publishing it whole and
        withholding it are the same act.

        `withhold_second_row` therefore checks, after row-level suppression, whether exactly
        one row was withheld, and if so withholds a **second** — the smallest surviving row
        with a non-zero count — so the residual can no longer be attributed to a single
        cell. A published **zero** is never chosen as that second row: withholding a zero
        removes nothing from the residual and would leave the leak open while looking
        closed.

        This is the third instance of the P24 defect class in this pipeline. It is written
        as a few explicit lines per table rather than a framework, because each table's
        public total is a different fact about a different file and the reasoning has to be
        re-done, not inherited.
        """
    )
    return


@app.cell
def _(pl, small_cell_mask):
    def withhold_second_row(df, count_cols, label):
        """Close the single-withheld-row leak in a partition of a public total.

        Returns `df` with one extra row removed when -- and only when -- row-level
        suppression would withhold exactly one row. The extra row is the smallest
        SURVIVING row with a non-zero primary count: a zero row contributes nothing to the
        residual, so withholding one would look like protection while leaving the withheld
        value recoverable exactly as before.

        Prints what it did either way; nothing about suppression is allowed to be silent.
        """
        _mask = small_cell_mask(df, count_cols)
        _n_withheld = int(_mask.sum())
        if _n_withheld != 1:
            print(
                f"  [{label}] partition check: {_n_withheld} row(s) withheld by the row-level "
                "rule; no second withholding needed"
            )
            return df
        _victim = (
            df.with_row_index("_r")
            .filter(~_mask)
            .filter(pl.col(count_cols[0]) > 0)
            .sort(count_cols[0])
            .head(1)
        )
        if _victim.height == 0:
            print(
                f"  [{label}] partition check: exactly one row withheld, but no non-zero row "
                "survives to withhold alongside it -- nothing further to do"
            )
            return df
        print(
            f"  [{label}] partition check: exactly ONE row withheld by the row-level rule, so "
            "its count is recoverable as (public total - published rows). Withholding a "
            "second row -- the smallest surviving non-zero one -- so the residual cannot be "
            "attributed to a single cell:"
        )
        print(_victim.drop("_r"))
        return df.with_row_index("_r").filter(pl.col("_r") != _victim.item(0, "_r")).drop("_r")

    return (withhold_second_row,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `imv_transition_summary.csv`

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
def _(SHARE_DIR, context_d, pl, publish, withhold_second_row):
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
        .sort("n", descending=True)
    )
    print("imv_transition_summary, unsuppressed (run log only, never written):")
    print(transition_summary)

    # This table partitions the total number of index paralytics, which
    # index_paralytic_summary.csv already makes public through n_index per agent_label.
    publish(
        withhold_second_row(transition_summary, ["n", "n_blocks"], "imv_transition_summary"),
        SHARE_DIR / "imv_transition_summary.csv",
        ["n", "n_blocks"],
        "imv_transition_summary",
    )
    return (transition_summary,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `imv_prior_device.csv` — what the airway was immediately before

        P12: block-opens-on-IMV and a null-device predecessor both give a null prior device,
        so `transition_opens_block` is what separates them in the published table. This
        table partitions the transition count, so it carries the same single-withheld-row
        check.
        """
    )
    return


@app.cell
def _(SHARE_DIR, context_d, pl, publish, withhold_second_row):
    # P12: block-opens-on-IMV and a null-device predecessor both give a null prior device,
    # so transition_opens_block is what separates them in the published table.
    prior_device = (
        context_d.filter(pl.col("imv_transition"))
        .with_columns(
            prior_device_category=pl.col("prior_device_category").fill_null("(none charted)")
        )
        .group_by(["prior_device_category", "transition_opens_block"])
        .agg(n=pl.len())
        .sort("n", descending=True)
    )
    print("imv_prior_device, unsuppressed (run log only, never written):")
    print(prior_device)

    # This table partitions the transition count, which imv_transition_summary.csv
    # publishes.
    publish(
        withhold_second_row(prior_device, ["n"], "imv_prior_device"),
        SHARE_DIR / "imv_prior_device.csv",
        ["n"],
        "imv_prior_device",
    )
    return (prior_device,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `imv_offset_distribution.csv` — where in the window the transition sat

        Twenty-four five-minute bins across the full 120 minutes, left-closed and right-open
        except the last, which is closed so an offset of exactly +60 has a home. Every bin
        is emitted, including the empty ones — an explicit published zero is what lets a
        reader tell an empty bin from a withheld one. This is a third partition of the
        transition count, so it gets the same check.
        """
    )
    return


@app.cell
def _(
    CONTEXT_WINDOW_MINUTES,
    OFFSET_BIN_WIDTH,
    SHARE_DIR,
    context_d,
    pl,
    publish,
    withhold_second_row,
):
    # 24 five-minute bins across the full 120 minutes, left-closed and right-open except
    # the last, which is closed so an offset of exactly +60 has a home.
    _n_bins = int(2 * CONTEXT_WINDOW_MINUTES // OFFSET_BIN_WIDTH)
    _edges = [
        -CONTEXT_WINDOW_MINUTES + OFFSET_BIN_WIDTH * i for i in range(_n_bins + 1)
    ]
    _labels = [f"[{_edges[i]:.0f},{_edges[i + 1]:.0f})" for i in range(_n_bins)]
    _labels[-1] = f"[{_edges[-2]:.0f},{_edges[-1]:.0f}]"

    _binned = (
        context_d.filter(pl.col("imv_transition"))
        .with_columns(
            _b=(
                ((pl.col("imv_offset_minutes") + CONTEXT_WINDOW_MINUTES) // OFFSET_BIN_WIDTH)
                .cast(pl.Int32)
                .clip(0, _n_bins - 1)
            )
        )
        .group_by("_b")
        .agg(n=pl.len())
    )
    offset_distribution = (
        pl.DataFrame({"_b": list(range(_n_bins)), "offset_bin": _labels})
        .with_columns(pl.col("_b").cast(pl.Int32))
        .join(_binned, on="_b", how="left")
        .with_columns(pl.col("n").fill_null(0))
        .sort("_b")
        .rename({"_b": "bin_order"})
    )
    print("imv_offset_distribution, unsuppressed (run log only, never written):")
    print(offset_distribution)

    # A third partition of the transition count, so the same single-withheld-row check.
    publish(
        withhold_second_row(offset_distribution, ["n"], "imv_offset_distribution"),
        SHARE_DIR / "imv_offset_distribution.csv",
        ["n"],
        "imv_offset_distribution",
    )
    return (offset_distribution,)


if __name__ == "__main__":
    app.run()
