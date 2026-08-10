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
        manufactures a spurious transition. `n_transitions_in_window` is published — as
        `imv_transitions_in_window.csv` — so the size of that effect is measurable from the
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
        .sort("n", descending=True)
    )
    publish(
        transition_summary,
        SHARE_DIR / "imv_transition_summary.csv",
        "imv_transition_summary",
    )
    return (transition_summary,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `imv_prior_device.csv` — what the airway was immediately before

        P12: block-opens-on-IMV and a null-device predecessor both give a null prior device,
        so `transition_opens_block` is what separates them in the published table.
        """
    )
    return


@app.cell
def _(SHARE_DIR, context_d, pl, publish):
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
    publish(
        prior_device,
        SHARE_DIR / "imv_prior_device.csv",
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
        reader tell an empty bin from a bin with no observations at all.
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
    publish(
        offset_distribution,
        SHARE_DIR / "imv_offset_distribution.csv",
        "imv_offset_distribution",
    )
    return (offset_distribution,)


@app.cell
def _(mo):
    mo.md(
        """
        ### `imv_transitions_in_window.csv` — how many transitions the window contained

        This is the table P14 rests on. Declining to de-bounce is only defensible if the
        size of the effect being declined is **measurable from the released output**, and
        `n_transitions_in_window` is that measurement: how many distinct non-IMV → IMV
        transitions fell inside ±60 minutes of the index paralytic, for the index paralytics
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
    # as an explicit zero rather than being absent from the table.
    _max_in_window = int(
        context_d.filter(pl.col("imv_transition")).get_column("n_transitions_in_window").max()
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
        SHARE_DIR / "imv_transitions_in_window.csv",
        "imv_transitions_in_window",
    )
    return (transitions_in_window,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## E — sedation in the same window

        The **identical** window predicate as D (P15), applied to
        `medication_admin_intermittent` over the five induction agents.

        **Every** administration in the window is kept, not just the nearest per agent
        (P17). The superseded design deduplicated by `med_category` because it was building
        a rank ladder, where one patient redosed six times would have dominated a
        distribution of ranks. This study publishes an offset *histogram*, where every
        administration is a legitimate observation of when sedation was charted —
        deduplicating would delete the redosing pattern the histogram exists to show.

        `med_dose` and `med_dose_unit` are the raw charted values and are **never
        converted** (P18). Dose statistics are keyed on `(med_category, med_dose_unit)`, so
        a site charting propofol in both `mg` and `mg/kg` produces two rows a reader can
        see rather than one number that is silently wrong.

        ### What E's counts count: PAIRS, not administrations

        The join is on `encounter_block`, and a block holds up to five index paralytics. A
        single physical administration that falls inside two index windows therefore
        contributes **two** rows — once to each window. That is correct and intended: the
        administration genuinely happened within ±60 minutes of both paralytics, and the
        same fan-out is what `02`'s bridge relies on. Deduplicating would have to pick one
        index paralytic to attribute it to, and there is no principled way to choose.

        But it means every count E publishes is a count of **(index paralytic,
        administration) pairs**, and at this site the two numbers differ:

        | | |
        |---|---|
        | pairs inside a window | **3,570** |
        | distinct administrations behind them | **3,297** |
        | pairs that are a re-count of an administration already seen | **273 — 7.6% of the total** |

        Calling that column `n` and its axis "administrations" would overstate the number of
        drug administrations by that margin, so the published column is named
        **`n_admin_windows`** and E.1's y-axis and E.2's row labels say the same. A patient
        redosed inside a block with several index paralytics contributes more than once, on
        purpose, and the column name is where a reader finds that out.
        """
    )
    return


@app.cell
def _(
    CONTEXT_WINDOW_MINUTES,
    DATA_DIR,
    FILETYPE,
    MAR_ACTIONS,
    MedicationAdminIntermittent,
    PHI_DIR,
    SEDATIVES,
    TIMEZONE,
    context_d,
    epoch_minutes,
    in_window_expr,
    pl,
    to_site_naive,
):
    # The bridge again -- 03 reaches the medication table by hospitalization_id and drops
    # the column at the join, exactly as 02 does (P5). cohort_index is re-read here rather
    # than threaded through index_paralytic, which deliberately carries no hospitalization.
    _cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")
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

    sed_admin = (
        pl.from_pandas(_sed.df.assign(admin_dttm=lambda d: to_site_naive(d["admin_dttm"])))
        .with_columns(
            med_category=pl.col("med_category").str.to_lowercase(),
            mar_action_category=pl.col("mar_action_category").str.to_lowercase(),
        )
        .filter(
            pl.col("med_category").is_in(SEDATIVES)
            & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(_bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")
    )

    assert "hospitalization_id" not in sed_admin.columns, "the bridge leaked its key"

    _found = sed_admin.get_column("med_category").unique().to_list()
    _missing = sorted(set(SEDATIVES) - set(_found))
    print(f"sedative administrations : {sed_admin.height:,}")
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
    # is on encounter_block, and a block holds up to five index paralytics, so a single
    # physical administration that lies inside two index windows produces two rows. That
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
        .with_columns(offset_minutes=(pl.col("_s_min") - pl.col("_t_min")).round(3))
        .filter(in_window_expr("offset_minutes", CONTEXT_WINDOW_MINUTES))
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
    _distinct_admins = sed_in_window.select(
        "encounter_block",
        "admin_dttm",
        "med_category",
        "med_dose",
        "med_dose_unit",
        "mar_action_category",
    ).unique().height
    print(
        f"(index paralytic, administration) pairs in a window : {sed_in_window.height:,}"
    )
    print(
        f"distinct administrations behind them                : {_distinct_admins:,}  "
        f"({sed_in_window.height - _distinct_admins:,} pairs, "
        f"{100 * (sed_in_window.height - _distinct_admins) / sed_in_window.height:.1f}% of "
        "the total, are an administration counted again in a second index window)"
    )
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
        ### The offset bin grid, defined once for E's table and E's figure

        Twenty-four five-minute bins across the full 120 minutes, on exactly the same edges
        D's distribution uses: left-closed and right-open except the last, which is closed
        so an offset of exactly +60 has a home. The labels are exported rather than rebuilt
        inside each figure, because a figure that reconstructs its own bin grid can drift
        from the table it is drawing.
        """
    )
    return


@app.cell
def _(CONTEXT_WINDOW_MINUTES, OFFSET_BIN_WIDTH):
    N_OFFSET_BINS = int(2 * CONTEXT_WINDOW_MINUTES // OFFSET_BIN_WIDTH)
    _edges = [
        -CONTEXT_WINDOW_MINUTES + OFFSET_BIN_WIDTH * i for i in range(N_OFFSET_BINS + 1)
    ]
    OFFSET_BIN_LABELS = [
        f"[{_edges[i]:.0f},{_edges[i + 1]:.0f})" for i in range(N_OFFSET_BINS)
    ]
    OFFSET_BIN_LABELS[-1] = f"[{_edges[-2]:.0f},{_edges[-1]:.0f}]"

    # The bin whose left edge is t itself -- the dashed rule in every offset figure sits
    # immediately to its left, so "before" and "after" are never read off a tick label.
    ZERO_BIN = N_OFFSET_BINS // 2
    return N_OFFSET_BINS, OFFSET_BIN_LABELS, ZERO_BIN


@app.cell
def _(mo):
    mo.md(
        """
        ### Publishing E

        `index_context.parquet` is written first — the canonical artifact, PHI, never
        shared. Then three released tables, each at its true count (P21):
        `sedation_summary.csv`, `sedation_offset_distribution.csv` and `sedation_dose.csv`.

        Every bin of the offset grid is emitted for every agent, including the empty ones: an
        explicit published zero is what lets a reader tell an empty bin from one with no
        observations at all.
        """
    )
    return


@app.cell
def _(
    CONTEXT_WINDOW_MINUTES,
    N_OFFSET_BINS,
    OFFSET_BIN_LABELS,
    OFFSET_BIN_WIDTH,
    PHI_DIR,
    SHARE_DIR,
    index_context,
    pl,
    publish,
    sed_in_window,
):
    index_context.write_parquet(PHI_DIR / "index_context.parquet")
    print(f"index_context.parquet   {index_context.height:,} rows -> {PHI_DIR}")

    sedation_summary = (
        index_context.with_columns(agent_set=pl.col("sedative_agents").list.join("+"))
        .with_columns(
            agent_set=pl.when(pl.col("agent_set") == "")
            .then(pl.lit("(none)"))
            .otherwise(pl.col("agent_set"))
        )
        .group_by(["any_sedative", "agent_set"])
        .agg(n=pl.len(), median_n_admins=pl.col("n_sedative_admins").median())
        .sort("n", descending=True)
    )
    publish(
        sedation_summary,
        SHARE_DIR / "sedation_summary.csv",
        "sedation_summary",
    )

    _grid = (
        pl.DataFrame(
            {"bin_order": list(range(N_OFFSET_BINS)), "offset_bin": OFFSET_BIN_LABELS}
        )
        .with_columns(pl.col("bin_order").cast(pl.Int32))
        .join(sed_in_window.select("med_category").unique(), how="cross")
    )

    _binned = (
        sed_in_window.with_columns(
            bin_order=(
                ((pl.col("offset_minutes") + CONTEXT_WINDOW_MINUTES) // OFFSET_BIN_WIDTH)
                .cast(pl.Int32)
                .clip(0, N_OFFSET_BINS - 1)
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
        SHARE_DIR / "sedation_offset_distribution.csv",
        "sedation_offset_distribution",
    )

    # P18: keyed on the unit, never converted. interpolation="linear" on both
    # quantiles, explicitly: polars' default is "nearest", which at small n
    # republishes a raw charted dose verbatim as the statistic.
    sedation_dose = (
        sed_in_window.group_by(["med_category", "med_dose_unit"])
        .agg(
            n_admin_windows=pl.len(),
            median_dose=pl.col("med_dose").median(),
            p25_dose=pl.col("med_dose").quantile(0.25, interpolation="linear"),
            p75_dose=pl.col("med_dose").quantile(0.75, interpolation="linear"),
        )
        .sort(["med_category", "n_admin_windows"], descending=[False, True])
    )
    publish(
        sedation_dose,
        SHARE_DIR / "sedation_dose.csv",
        "sedation_dose",
    )
    return sedation_dose, sedation_offsets, sedation_summary


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
        * **E.2 is faceted by charted unit, not one shared axis.** `mg` and `mcg/kg/min` on
          a single x-axis is the horizontal form of a dual-axis chart: the alignment of the
          two scales is arbitrary and the picture invents a comparison that is not in the
          data. One panel per unit, each with its own axis, is what P18 looks like drawn.

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
        height, however small. `clip_on=False` keeps its upper half from being clipped by
        the x-axis spine, since its center sits exactly on `ylim`'s bottom edge.
        """
        ax.plot(
            [x], [0], marker="D", markersize=5, color=color,
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
    N_OFFSET_BINS,
    OFFSET_BIN_LABELS,
    SHARE_DIR,
    ZERO_BIN,
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

    _d1 = pl.read_csv(SHARE_DIR / "imv_offset_distribution.csv").sort("bin_order")

    _fig, _ax = plt.subplots(figsize=(11, 5.4))

    for _row in _d1.iter_rows(named=True):
        if _row["n"] > 0:
            _ax.bar([_row["bin_order"]], [_row["n"]], width=0.72, color=_BLUE)
        else:
            mark_zero(_ax, _row["bin_order"], _BLUE)

    _ax.set_xticks(list(range(N_OFFSET_BINS)))
    _ax.set_xticklabels(OFFSET_BIN_LABELS, rotation=90, fontsize=7, color=_MUTED)
    _ax.set_xlim(-0.8, N_OFFSET_BINS - 0.2)
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

    _ax.axvline(ZERO_BIN - 0.5, color=_INK, linestyle="--", linewidth=1)
    _ax.text(
        ZERO_BIN - 0.4, _ax.get_ylim()[1] * 0.96, "t\n(the index paralytic)",
        fontsize=8, va="top", color=_INK,
    )

    _handles = [
        _ax.plot([], [], marker="D", markersize=5, color="0.3", linestyle="None",
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
    _fig.savefig(FIG_DIR / "D1_imv_offset.png", dpi=150)
    plt.close(_fig)
    print(f"D1_imv_offset.png -> {FIG_DIR}")
    return


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
    N_OFFSET_BINS,
    OFFSET_BIN_LABELS,
    SHARE_DIR,
    ZERO_BIN,
    mark_zero,
    pl,
    plt,
):
    _BLUE = "#2a78d6"
    _INK = "#0b0b0b"
    _MUTED = "#898781"
    _GRID = "#e1e0d9"

    _e1 = pl.read_csv(SHARE_DIR / "sedation_offset_distribution.csv")
    _agents = sorted(_e1.get_column("med_category").unique().to_list())

    _fig, _axes = plt.subplots(
        len(_agents), 1, figsize=(11, 1.55 * len(_agents) + 2.6),
        sharex=True, sharey=True, squeeze=False,
    )
    _axes = [_a[0] for _a in _axes]

    for _ax, _agent in zip(_axes, _agents):
        _s = _e1.filter(pl.col("med_category") == _agent).sort("bin_order")

        for _row in _s.iter_rows(named=True):
            if _row["n_admin_windows"] > 0:
                _ax.bar(
                    [_row["bin_order"]], [_row["n_admin_windows"]],
                    width=0.72, color=_BLUE,
                )
            else:
                mark_zero(_ax, _row["bin_order"], _BLUE)

        _ax.axvline(ZERO_BIN - 0.5, color=_INK, linestyle="--", linewidth=1)
        _ax.set_xlim(-0.8, N_OFFSET_BINS - 0.2)
        _ax.set_ylim(bottom=0)
        _ax.set_axisbelow(True)
        _ax.grid(axis="y", color=_GRID, linewidth=0.8)
        for _side in ("top", "right"):
            _ax.spines[_side].set_visible(False)
        # The panel title is the identity channel -- colour carries none of it.
        _ax.set_title(_agent, fontsize=9, loc="left", color=_INK)
        _ax.tick_params(axis="y", labelsize=8, colors=_MUTED)

        # On the shared y-axis a small-total agent's bars can be a few pixels tall next
        # to fentanyl's or propofol's -- correct, but a panel that shows no visible bar
        # communicates nothing on its own. This annotation carries the panel's true
        # magnitude, read from the same published frame the bars are drawn from -- never
        # recomputed -- so it cannot disagree with sedation_offset_distribution.csv.
        _ax.text(
            0.01, 0.90,
            f"n = {_s['n_admin_windows'].sum():,}, peak = {_s['n_admin_windows'].max():,}",
            transform=_ax.transAxes, ha="left", va="top", fontsize=8, color=_INK,
        )

    _axes[-1].set_xticks(list(range(N_OFFSET_BINS)))
    _axes[-1].set_xticklabels(OFFSET_BIN_LABELS, rotation=90, fontsize=7, color=_MUTED)
    _axes[-1].set_xlabel(
        "minutes from the index paralytic  (dashed rule = t)", color=_INK
    )
    # PAIRS, not administrations -- an administration inside two index windows is counted
    # in both. Saying "administrations" here would overstate the drug given by the fan-out.
    _axes[len(_axes) // 2].set_ylabel(
        "(index paralytic, administration) pairs", color=_INK
    )

    _handles = [
        _axes[0].plot([], [], marker="D", markersize=5, color="0.3", linestyle="None",
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
    _fig.savefig(FIG_DIR / "E1_sedation_offset.png", dpi=150)
    plt.close(_fig)
    print(f"E1_sedation_offset.png -> {FIG_DIR}")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ### Figure E.2 — sedative dose by agent and charted unit

        One panel per `med_dose_unit`, each with **its own x-axis**. Doses are the raw
        charted values and are never converted (P18); putting `mg` and `mcg/kg/min` on a
        single shared axis would draw a comparison that does not exist, which is the whole
        defect P18 was written against. Separate panels make the heterogeneity the subject
        of the figure instead of hiding it.

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

    _e2 = pl.read_csv(SHARE_DIR / "sedation_dose.csv")

    _units = sorted(_e2.get_column("med_dose_unit").unique().to_list())
    _ratios = [
        max(1, _e2.filter(pl.col("med_dose_unit") == _u).height) for _u in _units
    ]
    _n_panels = len(_ratios)

    # height_ratios in row counts gives every panel the SAME row pitch, so a bar in the
    # one-row panel is not drawn twice as thick as a bar in the two-row panel -- thickness
    # here is chrome and must not vary with how many units a panel happens to hold.
    _FIG_H = 1.2 + 0.45 * sum(_ratios) + 0.78 * _n_panels
    _fig, _axes = plt.subplots(
        _n_panels, 1, figsize=(10, _FIG_H),
        gridspec_kw={"height_ratios": _ratios}, squeeze=False,
    )
    _axes = [_a[0] for _a in _axes]

    for _ax, _unit in zip(_axes, _units):
        _p = _e2.filter(pl.col("med_dose_unit") == _unit).sort("median_dose")
        _y = list(range(_p.height))
        _ax.barh(_y, _p.get_column("median_dose").to_list(), height=0.4, color=_BLUE)
        # The IQR whisker crosses the bar it belongs to, so it carries a 3px ring in the
        # surface colour -- the dataviz surface-ring rule for overlapping marks. Without
        # it the whisker reads as part of the fill and the bar looks like it reaches p75.
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
            # The value rides the bar TIP, set just above it: at the whisker end it would
            # be read as p75, and inside the fill it would be clipped by a short bar.
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
        # The panel title is the unit, and the unit is the reason the panel exists.
        _ax.set_title(
            f"charted unit: {_unit}   ·   its own axis, never converted (P18)",
            fontsize=9, loc="left", color=_INK,
        )

    _axes[-1].set_xlabel(
        "charted dose — median, with p25–p75 whiskers   ·   row counts are "
        "(index paralytic, administration) pairs",
        color=_INK,
    )

    _fig.suptitle(
        "E.2 — sedative dose by agent and charted unit\n"
        "one panel per unit: the heterogeneity is shown, never normalised away (P18)\n"
        f"{_e2.height} (agent, unit) row(s) published",
        fontsize=11, color=_INK,
    )
    _fig.tight_layout()
    _fig.subplots_adjust(top=1 - 1.15 / _FIG_H, hspace=1.15)
    _fig.savefig(FIG_DIR / "E2_sedation_dose.png", dpi=150)
    plt.close(_fig)
    print(f"E2_sedation_dose.png -> {FIG_DIR}")
    return


if __name__ == "__main__":
    app.run()
