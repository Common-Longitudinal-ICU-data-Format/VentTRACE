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
        # 05 — Method `PAIR`, sedative–paralytic co-administration

        **The question is not "was a drug given near the intubation" but "were the two drug
        classes given together, and where in the stay".**

        `PAIR` is **free-running** (D27): the scan runs over every qualifying administration
        in the stitched encounter, not over the ±3 h window. t₀ is joined *afterwards*, only
        to locate each pair on the timeline, and plays no part in which pairs form.

        That is what makes it a third method rather than a restatement of the `SED` ✓ ∧
        `PARA` ✓ cell of the 2×2. It can find a co-administration the device signal missed
        entirely, and it produces an **independent intubation timestamp** — `pair_dttm` —
        which `07` scores against t₀ in Tier E.

        Two consequences follow and both are handled rather than hidden:

        - the denominator is not comparable to `SED` and `PARA`, so every pair carries an
          `in_window` flag and `07` reports both bases (D33);
        - a pair has no before/after ladder around a fixed anchor, so `PAIR` is **exempt
          from the §6.2 ranking rule and emits no `_ranked.json`** (D30). Its canonical
          artifact is pair-level.

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md`
        §6.5, §7.3, D27–D33
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

    METHOD_ID = "PAIR"

    # The one detection parameter D9 does not cover: 01 has no pair scan to run and nothing
    # to precompute, so 05 reads the scalar from config directly and echoes it here. That
    # echo is the "no silent defaults" requirement doing the work D9 does elsewhere.
    PAIR_GAP_HOURS = config["pair_gap_hours"]
    PAIR_GAP_MINUTES = PAIR_GAP_HOURS * 60.0

    # D43. The scan is handed clinical agent EVENTS, not raw administration rows: repeat
    # and co-administered doses inside this window are one push of drug, and charting them
    # as several rows is a documentation artefact, not several airways. Same argument as
    # above -- 01 precomputes nothing for it, so it is read here and echoed here.
    COLLAPSE_GAP_MINUTES = float(config["collapse_gap_minutes"])

    # Re-declared literally, not imported from 03 or 04 (D8). They must stay identical to
    # §7.1 and §7.2; the assertion block at the end checks the declared lists against the
    # values actually present in the output.
    SED_CATEGORIES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
    PARA_CATEGORIES = ["rocuronium", "succinylcholine", "vecuronium"]
    MED_CATEGORIES = SED_CATEGORIES + PARA_CATEGORIES

    print(f"site           : {SITE}")
    print(f"method         : {METHOD_ID}")
    print(f"pair_gap_hours : {PAIR_GAP_HOURS}   ({PAIR_GAP_MINUTES:.0f} min)")
    print(f"collapse_gap   : {COLLAPSE_GAP_MINUTES:.0f} min   (agent-event fold, D43)")
    print(f"class SED      : {' | '.join(SED_CATEGORIES)}")
    print(f"class PARA     : {' | '.join(PARA_CATEGORIES)}")
    return (
        COLLAPSE_GAP_MINUTES,
        DATA_DIR,
        FILETYPE,
        MED_CATEGORIES,
        METHOD_ID,
        PAIR_GAP_HOURS,
        PAIR_GAP_MINUTES,
        PARA_CATEGORIES,
        PHI_DIR,
        SED_CATEGORIES,
        TIMEZONE,
    )


@app.cell
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. Pinned by
        `tests/test_clifpy_tz_boundary.py`.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

    return (to_site_naive,)


@app.cell
def _(pl):
    def epoch_minutes(column="admin_dttm"):
        """The only correct way to turn a site-naive timestamp into float minutes.

        Sibling trap to `to_site_naive`, and the one that bites on the way back out.
        `datetime.timestamp()` on a NAIVE datetime does not treat it as the wall clock it
        is -- it silently interprets it in the **operating system's** zone and converts.
        On a machine set to US/Central, with data in US/Eastern:

            2023-11-05 01:55 -> 02:05   is 10 minutes of Eastern wall clock
            naive .timestamp() makes it 70, because it re-applies Chicago's fall-back hour

        A 60-minute artefact decides a 15-minute collapse window outright: two doses that
        are one push of drug split into two agent events. Worse, the answer changes with the
        machine, which is exactly what the §6.2 byte-identical-across-runs rule forbids.

        `dt.epoch` reads the stored wall-clock value and consults no zone at all, so it
        agrees with the naive subtraction the rest of the file already uses for
        `window_start`/`window_end` and `pair_to_t0_min`.

        NEVER "simplify" this back to `x.timestamp() / 60.0`. Pinned by
        `tests/test_collapse_agent_events.py`.
        """
        return pl.col(column).dt.epoch("s") / 60.0

    return (epoch_minutes,)


@app.cell
def _(PHI_DIR, pl):
    index_imv = pl.read_parquet(PHI_DIR / "index_imv.parquet")

    COHORT_RUN_ID = index_imv.get_column("cohort_run_id").unique().to_list()
    assert len(COHORT_RUN_ID) == 1, f"index_imv carries {len(COHORT_RUN_ID)} run ids"
    COHORT_RUN_ID = COHORT_RUN_ID[0]

    print(f"cohort_run_id     : {COHORT_RUN_ID}")
    print(f"cohort encounters : {index_imv.height:,}   (N*)")
    print(f"  of which qualified : {index_imv.filter(pl.col('index_qualified')).height:,}   (N**)")
    return COHORT_RUN_ID, index_imv


@app.cell
def _(index_imv, pl):
    # The same explode-and-drop bridge as every other method (§7) — the only place this
    # notebook may name a hospitalization. It carries t0 and the window bounds, but note
    # that neither filters anything here: they are joined so the pair table can report
    # `pair_to_t0_min` and `in_window` after the scan has already run (D27).
    _bridge_exploded = (
        index_imv.select(
            ["encounter_block", "list_hospitalization_id"]
        )
        .explode("list_hospitalization_id")
        .rename({"list_hospitalization_id": "hospitalization_id"})
    )
    _bridge_rows_before = _bridge_exploded.height

    # Block-level, deliberately -- and this is the ONE bridge in the pipeline that must
    # not carry intubation_episode_id. The scan is free-running over the whole block (D27),
    # so fanning the administrations out to episodes here would run the forward pass once
    # per episode and break D28's consumption across the boundary. Episodes rejoin below,
    # after the pairs exist (D39).
    #
    # Dropping the episode key is exactly why this must be de-duplicated: index_imv is at
    # episode grain (D35), so exploding `list_hospitalization_id` yields one row per
    # (episode, hospitalization), not one per (block, hospitalization). Only the block
    # mapping is wanted here, so collapse back to it with `.unique()`. Skipping this step
    # would carry every hospitalization once per episode in its block into the inner join
    # below, replicating each medication administration that many times and pairing clones
    # with clones in the scan.
    bridge = _bridge_exploded.unique()
    bridge_hosp_ids = bridge.get_column("hospitalization_id").unique().to_list()

    assert bridge.get_column("hospitalization_id").is_duplicated().sum() == 0, (
        "a hospitalization maps to more than one encounter_block; the inner join below "
        "would replicate every administration and the scan would pair clones with clones."
    )

    print(f"bridge rows        : {_bridge_rows_before:,} -> {bridge.height:,}   (exploded -> deduped)")
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
    return (med_all,)


@app.cell
def _(MED_CATEGORIES, PARA_CATEGORIES, SED_CATEGORIES, bridge, med_all, pl):
    # NO window filter. The scan is free-running over the whole stitched encounter (D27);
    # window membership is computed per pair, afterwards, as a descriptive flag.
    scan_rows = (
        med_all.filter(
            pl.col("med_category").is_in(MED_CATEGORIES)
            & (pl.col("mar_action_category") == "given")
        )
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # step 6 of the bridge
        .with_columns(
            drug_class=pl.when(pl.col("med_category").is_in(SED_CATEGORIES))
            .then(pl.lit("SED"))
            .otherwise(pl.lit("PARA"))
        )
        # Ties broken alphabetically by med_category (§6.2 convention), so the scan order --
        # and therefore every pair it forms -- is byte-identical across runs.
        .sort(["encounter_block", "admin_dttm", "med_category"])
    )

    assert "hospitalization_id" not in scan_rows.columns, "the bridge leaked its key"

    _found = scan_rows.get_column("med_category").value_counts(sort=True)
    _missing = sorted(set(MED_CATEGORIES) - set(_found.get_column("med_category").to_list()))
    print(f"administrations entering the scan : {scan_rows.height:,}")
    print(_found)
    if _missing:
        print(f"\nNOT PRESENT AT THIS SITE: {', '.join(_missing)}")

    _classes = set(scan_rows.get_column("drug_class").unique().to_list())
    assert _classes == {"SED", "PARA"}, (
        f"only these drug classes reached the scan: {_classes or '{}'}. PAIR requires both; "
        "with one absent its detection rate is structurally zero and means nothing. "
        f"SED list: {SED_CATEGORIES}. PARA list: {PARA_CATEGORIES}."
    )
    return (scan_rows,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## The collapse — administrations become agent events

        The scan below counts *pairings*, so what it is handed decides what a pair means. A
        raw administration row is not a clinical event: a rapid-sequence induction is
        charted as fentanyl at 08:14, propofol at 08:14, rocuronium at 08:15, and a repeat
        push of the same agent two minutes later is still the same push of drug. Handed
        those rows, the scan forms one pair per sedative row it can match and reports four
        intubations where the chart describes one.

        So before the scan runs, administrations within `collapse_gap_minutes` of each other
        are folded into one **agent event**, separately within each drug class of each
        encounter (D43).

        ```
        for each (encounter_block, drug_class), rows already in time order:
            start a new event at the first row
            each next row joins the event  if  t[row] - t[event's FIRST row] <= gap
            otherwise it opens a new event and becomes the new anchor
        ```

        The window is **anchored on the event's first row, not chained off the previous
        one**. Chaining would let a maintenance infusion charted every ten minutes grow into
        a single event spanning the whole stay, which would erase the second intubation of
        a re-intubated patient. Anchoring bounds every event at `collapse_gap_minutes` end
        to end, which the cell after next asserts.

        The fold is *within* a class, never across it — a sedative and a paralytic must stay
        separate rows or there is nothing left for the scan to pair. It is also blind to
        which agents are involved: a repeat of one agent and a co-administration of two are
        the same clinical fact, one push of that class of drug, and merge identically. The
        surviving event is labelled with every agent it contains (`fentanyl+propofol`,
        D43.5) so nothing is thrown away, and it carries `n_admin` and `span_min` so the
        collapse is auditable from the pair table.
        """
    )
    return


@app.cell
def _(COLLAPSE_GAP_MINUTES):
    def collapse_agent_events(times, categories, gap_limit_min):
        """Fold administrations into agent events. Returns [[i, ...], ...] in time order.

        `times` is minutes-since-epoch as floats, ascending, all from one drug class of one
        encounter. The invariant is that **no event spans more than `gap_limit_min`**: a row
        joins the current event only while it is within the limit of that event's FIRST row,
        and the moment it is strictly past it the row opens a new event and becomes the new
        anchor. Anchored, never chained — the comparison is against `times[event[0]]` and
        never against `times[i - 1]`, so a steady drip of closely-spaced doses cannot walk
        an event forward without bound.

        Strictly greater, not greater-or-equal: a row exactly `gap_limit_min` past the
        anchor still merges, so the parameter reads as "within 15 minutes" inclusively.

        `categories` takes no part in the decision and is only length-checked. That is the
        point rather than an oversight: a repeat of one agent and a co-administration of
        two are the same clinical fact — one push of this class of drug — and must fold the
        same way. Which agents were involved is recorded on the event afterwards, by the
        caller, in the D43.5 label.
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
def _(collapse_agent_events):
    def _self_test():
        """The D43 worked examples, run as assertions before any real data is touched."""
        _X = "x"  # the grouping is blind to the agent; one filler category is enough
        cases = [
            # (a) same-instant co-administration merges
            ([0, 0], [[0, 1]]),
            # (b) exactly at the limit still merges (`>`, not `>=`)
            ([0, 15], [[0, 1]]),
            # (c) one minute past the limit splits
            ([0, 16], [[0], [1]]),
            # (d) ANCHORED, not chained: 20 is 20 min past the event start, so it splits
            #     even though it is only 10 min past its predecessor
            ([0, 10, 20], [[0, 1], [2]]),
            # (e) a run inside one window stays one event
            ([0, 5, 10, 15], [[0, 1, 2, 3]]),
            # (f) singleton
            ([0], [[0]]),
        ]
        for _k, (_t, _want) in enumerate(cases):
            _got = collapse_agent_events(
                [float(x) for x in _t], [_X] * len(_t), 15.0
            )
            assert _got == _want, f"worked example {'abcdef'[_k]}: expected {_want}, got {_got}"
        print("D43 collapse worked examples (a)-(f) pass")

    _self_test()
    return


@app.cell
def _(COLLAPSE_GAP_MINUTES, collapse_agent_events, epoch_minutes, pl, scan_rows):
    _cols = ["encounter_block", "admin_dttm", "med_category", "med_dose", "med_dose_unit",
             "drug_class"]
    # Partitioned by class as well as encounter: the fold must never reach across SED/PARA
    # or there would be nothing left to pair. `maintain_order` keeps the §6.2 sort
    # (encounter_block, admin_dttm, med_category) inside each partition, which is what makes
    # `times` ascending and the label's lead agent reproducible.
    # admin_min is derived in polars, before the rows leave the frame, because
    # `datetime.timestamp()` on these naive values would read the OS zone -- see
    # `epoch_minutes`.
    _parts = (
        scan_rows.select(_cols)
        .with_columns(admin_min=epoch_minutes())
        .partition_by(["encounter_block", "drug_class"], as_dict=True, maintain_order=True)
    )

    _events = []
    for (_eb, _cls), _blk in _parts.items():
        _t = _blk.get_column("admin_dttm").to_list()
        _tmin = _blk.get_column("admin_min").to_list()
        _cat = _blk.get_column("med_category").to_list()
        _dose = _blk.get_column("med_dose").to_list()
        _unit = _blk.get_column("med_dose_unit").to_list()

        for _idx in collapse_agent_events(_tmin, _cat, COLLAPSE_GAP_MINUTES):
            _agents = sorted(set(_cat[_k] for _k in _idx))
            # D43.6. Dose and unit come from the earliest administration of the FIRST agent
            # named in the label -- alphabetically first, matching the label itself, so the
            # dose always belongs to a named agent and stays numeric (E.3 takes a median of
            # it). `_idx` is ascending, so the first match IS the earliest.
            _lead = next(_k for _k in _idx if _cat[_k] == _agents[0])
            _events.append(
                {
                    "encounter_block": _eb,
                    "admin_dttm": _t[_idx[0]],  # the earliest administration in the event
                    "med_category": "+".join(_agents),  # D43.5
                    "med_dose": _dose[_lead],
                    "med_dose_unit": _unit[_lead],
                    "drug_class": _cls,
                    "n_admin": len(_idx),
                    "span_min": round(_tmin[_idx[-1]] - _tmin[_idx[0]], 1),
                }
            )

    agent_events = pl.DataFrame(
        _events,
        schema={
            "encounter_block": scan_rows.schema["encounter_block"],
            "admin_dttm": scan_rows.schema["admin_dttm"],
            "med_category": pl.String,
            "med_dose": pl.Float64,
            "med_dose_unit": pl.String,
            "drug_class": pl.String,
            "n_admin": pl.Int32,
            "span_min": pl.Float64,
        },
    ).sort(["encounter_block", "admin_dttm", "med_category"])  # §6.2, carried through

    # The three things that can go wrong, each asserted rather than assumed.
    assert agent_events.get_column("span_min").max() <= COLLAPSE_GAP_MINUTES, (
        f"an event spans {agent_events.get_column('span_min').max()} min against a "
        f"{COLLAPSE_GAP_MINUTES:.0f} min limit -- the window chained off the previous row "
        "instead of anchoring on the event's first."
    )
    assert agent_events.height <= scan_rows.height, "the collapse invented rows"
    assert agent_events.get_column("n_admin").sum() == scan_rows.height, (
        f"n_admin sums to {agent_events.get_column('n_admin').sum():,} against "
        f"{scan_rows.height:,} administrations -- the fold lost or duplicated rows."
    )

    _merged = agent_events.filter(pl.col("n_admin") > 1)
    _multi = agent_events.filter(pl.col("med_category").str.contains("+", literal=True))
    print(f"administrations in : {scan_rows.height:,}")
    print(f"agent events out   : {agent_events.height:,}")
    print(agent_events.group_by("drug_class").agg(
        n_events=pl.len(),
        n_admin=pl.col("n_admin").sum(),
        max_n_admin=pl.col("n_admin").max(),
        max_span_min=pl.col("span_min").max(),
    ).sort("drug_class"))
    print(f"\nmerged events (n_admin > 1) : {_merged.height:,}")
    print(f"multi-agent events          : {_multi.height:,}")
    print("\ntop merged labels:")
    print(_merged.get_column("med_category").value_counts(sort=True).head(10))
    return (agent_events,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ### The evidence for the 15 minutes (D43.2)

        The window above is a **clinical** definition — the span over which a charted run of
        pushes is one induction — and it is *not* fitted to a valley in the data, because
        there is no valley to fit. That claim has to be publishable rather than asserted, so
        the distribution behind it is computed here and published by `07` as
        `pair_collapse_deltas.csv` / `.png`.

        It is computed **here** and not there for the same reason the collapse itself is
        here: the distribution is over raw *administrations*, and `07` never opens the
        medication table — its inputs are the method artifacts. So `05`, which already holds
        every row, emits an **aggregated counts-only** table (one `n` per Δ-minute per
        same/different-agent), and `07` suppresses, writes and draws it. No row-level record
        and no identifier crosses over.

        The measure is the gap between **consecutive same-class administrations** inside a
        block's ±`window_hours` peri-intubation window, split by whether the two rows name
        the same agent (a redose) or different agents (a co-administration). Those are the
        two things the fold merges, and they behave differently: co-administration is a
        Δ ≤ 1 min phenomenon, while redosing is flat. Where the co-administration curve
        meets the redose curve is where the collapse stops buying anything — and that
        happens far below 15 minutes.
        """
    )
    return


@app.cell
def _(
    COHORT_RUN_ID,
    COLLAPSE_GAP_MINUTES,
    PHI_DIR,
    epoch_minutes,
    index_imv,
    pl,
    scan_rows,
):
    # D43.2's evidence table. COUNTS ONLY -- one row per (Δ minute, same_agent), no
    # patient, no encounter, no timestamp. 07 applies the n >= 10 rule to it and draws the
    # figure from what it publishes (D26).
    COLLAPSE_DELTA_MAX_MIN = 45  # three collapse windows; past it the two series are flat

    # Peri-intubation context, deliberately -- unlike the scan itself, which is
    # free-running (D27). Over a whole stay the count is dominated by maintenance dosing on
    # the ward and in the ICU, which is not the behaviour the fold is defined against. The
    # question "does 15 minutes separate one induction from the next" is only meaningful
    # near an intubation.
    #
    # `.unique()` first: index_imv is at episode grain (D35), so a block contributes one
    # window per episode. Rows are marked in-window if they fall inside ANY of them, then
    # de-duplicated back to one row per administration -- an administration inside two
    # overlapping windows is still one administration and must not count twice.
    _windows = index_imv.select(["encounter_block", "window_start", "window_end"]).unique()

    _rows = scan_rows.select(
        ["encounter_block", "admin_dttm", "med_category", "drug_class"]
    ).with_row_index("_rid")

    _peri_ids = (
        _rows.join(_windows, on="encounter_block", how="inner")
        .filter(
            (pl.col("admin_dttm") >= pl.col("window_start"))
            & (pl.col("admin_dttm") <= pl.col("window_end"))
        )
        .select("_rid")
        .unique()
    )

    # Partitioned exactly as the fold is -- (encounter_block, drug_class) -- so the interval
    # being measured is the interval the fold decides on. admin_min via `epoch_minutes`,
    # never `datetime.timestamp()`; see that helper for why the difference is an hour.
    #
    # KNOWN AND LEFT ALONE: the shift runs within (encounter_block, drug_class) AFTER the
    # peri-intubation filter, so in a block holding two episodes whose +/-3 h windows are
    # disjoint, the last row of window A and the first of window B form one interval that
    # spans administrations nobody measured. It is a real artifact of measuring on a
    # filtered series, and it does not touch what this table is for: it affects the
    # same-agent and different-agent series identically, and a cross-window interval is
    # necessarily longer than a window gap, so it can only land in the delta >= 2 tail where
    # D43.2 already reports the two series running at the same rate. The finding -- that the
    # co-administration excess is confined to delta <= 1 -- does not rest on it.
    _intervals = (
        _rows.join(_peri_ids, on="_rid", how="semi")
        .sort(["encounter_block", "drug_class", "admin_dttm", "med_category"])
        .with_columns(admin_min=epoch_minutes())
        .with_columns(
            _prev_min=pl.col("admin_min").shift(1).over(["encounter_block", "drug_class"]),
            _prev_cat=pl.col("med_category").shift(1).over(["encounter_block", "drug_class"]),
        )
        .drop_nulls("_prev_min")  # the first row of each partition opens no interval
        .with_columns(
            delta_min=(pl.col("admin_min") - pl.col("_prev_min")).round(0).cast(pl.Int32),
            same_agent=pl.col("med_category") == pl.col("_prev_cat"),
        )
    )
    _beyond = _intervals.filter(pl.col("delta_min") > COLLAPSE_DELTA_MAX_MIN).height

    # The full 0..MAX x {same, different} grid, zeros included. A cell of exactly zero is
    # publishable and MEANS something ("this never happened"); leaving it as an absent row
    # would be indistinguishable from a row the n >= 10 rule removed.
    _grid = pl.DataFrame(
        {"delta_min": pl.int_range(0, COLLAPSE_DELTA_MAX_MIN + 1, eager=True).cast(pl.Int32)}
    ).join(pl.DataFrame({"same_agent": [False, True]}), how="cross")

    collapse_deltas = (
        _grid.join(
            _intervals.filter(pl.col("delta_min") <= COLLAPSE_DELTA_MAX_MIN)
            .group_by(["delta_min", "same_agent"])
            .agg(n=pl.len()),
            on=["delta_min", "same_agent"],
            how="left",
        )
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            n=pl.col("n").fill_null(0).cast(pl.Int32),
            max_delta_min=pl.lit(COLLAPSE_DELTA_MAX_MIN, dtype=pl.Int32),
            # Carried so the figure can state its truncated mass without reopening a PHI
            # frame. It is a whole-cohort margin, not a cell, and 07 withholds it if it
            # ever lands in the disclosive range.
            n_beyond_max_delta=pl.lit(_beyond, dtype=pl.Int32),
        )
        .select(
            ["cohort_run_id", "delta_min", "same_agent", "n", "max_delta_min",
             "n_beyond_max_delta"]
        )
        .sort(["delta_min", "same_agent"])
    )

    assert collapse_deltas.height == 2 * (COLLAPSE_DELTA_MAX_MIN + 1), (
        f"the grid is {collapse_deltas.height} rows, not "
        f"{2 * (COLLAPSE_DELTA_MAX_MIN + 1)}. 07 derives the suppressed-cell count by "
        "subtracting the published height from this, so a ragged grid would report "
        "suppression that never happened."
    )
    assert collapse_deltas.get_column("n").sum() + _beyond == _intervals.height, (
        "the binned counts and the beyond-max count do not add up to the intervals "
        "measured; the table would understate its own denominator."
    )
    assert not set(collapse_deltas.columns) & {"patient_id", "encounter_block",
                                              "hospitalization_id", "admin_dttm"}, (
        "an identifier reached the collapse-evidence table. It is published by 07 and must "
        "stay counts-only."
    )

    collapse_deltas.write_parquet(PHI_DIR / "pair_collapse_deltas.parquet")

    _d = {(r["delta_min"], r["same_agent"]): r["n"] for r in collapse_deltas.to_dicts()}
    _diff_le1 = _d[(0, False)] + _d[(1, False)]
    _same_le1 = _d[(0, True)] + _d[(1, True)]
    _diff_ge2 = sum(v for (k, s), v in _d.items() if k >= 2 and not s)
    _same_ge2 = sum(v for (k, s), v in _d.items() if k >= 2 and s)
    print(f"peri-intubation intervals measured : {_intervals.height:,}")
    print(f"  within 0..{COLLAPSE_DELTA_MAX_MIN} min                    : "
          f"{collapse_deltas.get_column('n').sum():,}")
    print(f"  beyond {COLLAPSE_DELTA_MAX_MIN} min (not tabulated)      : {_beyond:,}")
    print(f"\n            different agent   same agent")
    print(f"  delta 0   {_d[(0, False)]:>13,}   {_d[(0, True)]:>10,}")
    print(f"  delta 1   {_d[(1, False)]:>13,}   {_d[(1, True)]:>10,}")
    print(f"  <= 1 min  {_diff_le1:>13,}   {_same_le1:>10,}")
    print(f"  >= 2 min  {_diff_ge2:>13,}   {_same_ge2:>10,}")
    print(
        f"\nThe co-administration signal is spent by delta 1; from delta 2 the two series "
        f"run at the same rate.\nThe fold nevertheless uses "
        f"{COLLAPSE_GAP_MINUTES:.0f} min -- a clinical induction sequence, NOT a valley in "
        "this distribution (D43.2).\npair_collapse_deltas.parquet -> 07"
    )
    return (collapse_deltas,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## The scan — one forward pass with consumption

        ```
        available[0..n-1] = True
        seq = 0

        for i in 0 .. n-1:
            if not available[i]:  continue
            j = smallest index > i  where  available[j]  and  class(j) != class(i)
            if j exists  and  (t[j] - t[i]) < pair_gap_hours:
                seq += 1
                emit pair (i, j) as pair_seq = seq
                available[i] = False
                available[j] = False
            # advance to i+1 either way — never look back
        ```

        Three properties are load-bearing, and each is a place this could plausibly go wrong:

        1. **Same-class administrations are stepped over, not stopped at.** `j` is the first
           *opposite-class* row, not the adjacent one. A fentanyl charted ahead of the
           midazolam still reaches the rocuronium — real charting routinely puts an
           analgesic first.
        2. **Rows stepped over are not consumed.** They stay available and get their own
           turn as `i` advances, which is how a second sedative pairs with a second
           paralytic.
        3. **A consumed row is never reconsidered**, in either direction. Each
           administration belongs to at most one pair, so `pair_id` is countable.

        Because a rejected pair consumes **nothing**, a tighter `pair_gap_hours` leaves rows
        available that a looser one had removed — so a tighter threshold yields a *different*
        pair set, not a subset of this one. That is why D29 requires a re-run and forbids
        filtering `gap_minutes` on the emitted table.
        """
    )
    return


@app.cell
def _(PAIR_GAP_MINUTES):
    def scan_encounter(times, classes, gap_limit_min):
        """One forward pass with consumption. Returns [(i, j), ...] in scan order.

        `times` is minutes-since-epoch as floats, ascending. The forward search stops once
        the elapsed gap reaches the limit: the rows are sorted, so if the first *available*
        opposite-class row within the limit does not exist, the true "first available
        opposite-class row" is at or beyond the limit and the pair would be rejected anyway.
        That early stop is what keeps the pass linear-ish instead of quadratic on a long
        stay, and it changes no result.
        """
        n = len(times)
        available = [True] * n
        pairs = []
        for i in range(n):
            if not available[i]:
                continue
            ci, ti = classes[i], times[i]
            for j in range(i + 1, n):
                if times[j] - ti >= gap_limit_min:
                    break
                if available[j] and classes[j] != ci:
                    pairs.append((i, j))
                    available[i] = False
                    available[j] = False
                    break
        return pairs

    def _self_test():
        """The §7.3 worked examples, run as assertions before any real data is touched."""
        S, P = "SED", "PARA"
        cases = [
            # (a) analgesic ahead of the induction agent
            ([0, 1, 2, 40], [S, S, P, S], [(0, 2)]),
            # (b) consumption frees the next pairing
            ([0, 1, 2, 3], [S, S, P, P], [(0, 2), (1, 3)]),
            # (c) paralytic first
            ([0, 1], [P, S], [(0, 1)]),
            # (d) same minute
            ([0, 0], [S, P], [(0, 1)]),
            # (e) gap exceeds threshold — no pair, nothing consumed
            ([0, 240], [S, P], []),
            # (f) no opposite class at all
            ([0, 5, 360], [S, S, S], []),
        ]
        for _k, (_t, _c, _want) in enumerate(cases):
            _got = scan_encounter([float(x) for x in _t], _c, 180.0)
            assert _got == _want, f"worked example {'abcdef'[_k]}: expected {_want}, got {_got}"
        print("§7.3 worked examples (a)–(f) pass")

    _self_test()
    print(f"scan threshold: {PAIR_GAP_MINUTES:.0f} min")
    return (scan_encounter,)


@app.cell
def _(PAIR_GAP_MINUTES, agent_events, epoch_minutes, pl, scan_encounter):
    # AGENT EVENTS, not administration rows (D43). The scan below is unchanged -- what
    # changed is what it is handed.
    _cols = ["encounter_block", "admin_dttm", "med_category", "med_dose", "med_dose_unit",
             "drug_class", "n_admin", "span_min"]
    # Same `epoch_minutes` as the collapse: one conversion idiom for both stages, and
    # neither of them may ask the OS what timezone it is in.
    _by_block = (
        agent_events.select(_cols)
        .with_columns(admin_min=epoch_minutes())
        .partition_by("encounter_block", as_dict=True)
    )

    _rows = []
    _unpaired = []
    for _key, _blk in _by_block.items():
        _eb = _key[0]
        _t = _blk.get_column("admin_dttm").to_list()
        _tmin = _blk.get_column("admin_min").to_list()
        _cls = _blk.get_column("drug_class").to_list()
        _cat = _blk.get_column("med_category").to_list()
        _dose = _blk.get_column("med_dose").to_list()
        _unit = _blk.get_column("med_dose_unit").to_list()
        _nadm = _blk.get_column("n_admin").to_list()
        _span = _blk.get_column("span_min").to_list()

        _pairs = scan_encounter(_tmin, _cls, PAIR_GAP_MINUTES)
        _consumed = set()
        for _seq, (_i, _j) in enumerate(_pairs, start=1):
            _consumed.add(_i)
            _consumed.add(_j)
            _si, _pi = (_i, _j) if _cls[_i] == "SED" else (_j, _i)
            _gap = abs(_tmin[_j] - _tmin[_i])
            _rows.append(
                {
                    "encounter_block": _eb,
                    "pair_seq": _seq,
                    # SIMULTANEOUS rather than an arbitrary order: a same-minute charting
                    # carries no ordering information and should not be assigned one.
                    "first_class": "SIMULTANEOUS" if _gap == 0 else _cls[_i],
                    "sed_med_category": _cat[_si],
                    "sed_med_dose": _dose[_si],
                    "sed_med_dose_unit": _unit[_si],
                    "sed_admin_dttm": _t[_si],
                    # How much charting the collapse folded into this member, kept on the
                    # pair so the fold is auditable without re-running it.
                    "n_sed_admin": _nadm[_si],
                    "sed_span_min": _span[_si],
                    "para_med_category": _cat[_pi],
                    "para_med_dose": _dose[_pi],
                    "para_med_dose_unit": _unit[_pi],
                    "para_admin_dttm": _t[_pi],
                    "n_para_admin": _nadm[_pi],
                    "para_span_min": _span[_pi],
                    "pair_dttm": _t[_i],  # the earlier of the two, by scan order
                    "gap_minutes": round(_gap, 1),
                }
            )
        # Unpaired EVENTS now, not unpaired administration rows -- one unpaired event may
        # stand for several charted doses (its n_admin).
        _n_sed = sum(1 for _k2 in range(len(_cls)) if _cls[_k2] == "SED" and _k2 not in _consumed)
        _unpaired.append(
            {
                "encounter_block": _eb,
                "n_unpaired_sed": _n_sed,
                "n_unpaired_para": len(_cls) - len(_consumed) - _n_sed,
            }
        )

    pairs_raw = (
        # The Python round-trip above widens the fold counts to Int64; put them back to the
        # Int32 `agent_events` declares, so the artifact's schema matches the intent.
        pl.DataFrame(_rows).with_columns(
            pl.col(["n_sed_admin", "n_para_admin"]).cast(pl.Int32)
        )
        if _rows
        else None
    )
    unpaired_counts = pl.DataFrame(_unpaired)

    print(f"encounters scanned : {len(_by_block):,}")
    print(f"agent events fed   : {agent_events.height:,}")
    print(f"pairs formed       : {0 if pairs_raw is None else pairs_raw.height:,}")
    print(f"blocks with >=1 pair : {0 if pairs_raw is None else pairs_raw.get_column('encounter_block').n_unique():,}")
    return pairs_raw, unpaired_counts


@app.cell
def _(PAIR_GAP_MINUTES, index_imv, pairs_raw, pl):
    assert pairs_raw is not None, "the scan formed no pairs at all"

    pairs = (
        pairs_raw.join(
            index_imv.select(
                ["encounter_block", "intubation_episode_id", "patient_id", "ep_num",
                 "cohort_run_id", "index_class", "index_qualified", "t0_dttm",
                 "window_start", "window_end"]
            ),
            on="encounter_block",
            how="inner",
        )
        # D39. Under D35 a block holds several episodes, so the join above fans each pair
        # out to every episode of its block. Keep the episode whose t0 is NEAREST to
        # pair_dttm, ties to the earlier episode via ep_num. Nearest-t0 needs no new
        # concept -- every pair already carries a distance to a t0 -- and it PARTITIONS
        # rather than overlaps, which the next cell asserts.
        .with_columns(
            _dist=(pl.col("pair_dttm") - pl.col("t0_dttm")).dt.total_seconds().abs()
        )
        .sort(["encounter_block", "pair_seq", "_dist", "ep_num"])
        .group_by(["encounter_block", "pair_seq"], maintain_order=True)
        .first()
        .drop("_dist")
        .with_columns(
            pair_id=pl.col("encounter_block").cast(pl.String)
            + "_P"
            + pl.col("pair_seq").cast(pl.String),
            imv_dttm=pl.col("t0_dttm"),
            pair_to_t0_min=(
                (pl.col("pair_dttm") - pl.col("t0_dttm")).dt.total_seconds() / 60.0
            ).round(1),
            in_window=(pl.col("pair_dttm") >= pl.col("window_start"))
            & (pl.col("pair_dttm") <= pl.col("window_end")),
        )
        .select(
            [
                "intubation_episode_id", "encounter_block", "patient_id", "ep_num",
                "cohort_run_id", "index_class", "index_qualified",
                "pair_id", "pair_seq", "first_class",
                "sed_med_category", "sed_med_dose", "sed_med_dose_unit", "sed_admin_dttm",
                "n_sed_admin", "sed_span_min",
                "para_med_category", "para_med_dose", "para_med_dose_unit", "para_admin_dttm",
                "n_para_admin", "para_span_min",
                "pair_dttm", "gap_minutes", "imv_dttm", "pair_to_t0_min", "in_window",
            ]
        )
        .sort(["encounter_block", "pair_seq"])
    )

    assert pairs.get_column("pair_id").is_duplicated().sum() == 0, "pair_id is not unique"
    assert pairs.filter(pl.col("gap_minutes") < 0).height == 0, "gap_minutes must be >= 0"
    assert pairs.filter(pl.col("gap_minutes") >= PAIR_GAP_MINUTES).height == 0, (
        "a pair exceeded the threshold; the scan admitted something it should have rejected"
    )
    # pair_dttm is the EARLIER of the two members, by definition.
    assert pairs.filter(
        pl.col("pair_dttm")
        > pl.min_horizontal("sed_admin_dttm", "para_admin_dttm")
    ).height == 0, "pair_dttm is not the earlier administration"

    # D39 is a PARTITION, not a labelling: summing over a block's episodes must recover
    # the block's pair count. A pair scored into two episodes would inflate every rate in
    # Tier E and would not show up anywhere else.
    assert pairs.height == pairs_raw.height, (
        f"the episode assignment changed the pair count: {pairs_raw.height:,} scanned, "
        f"{pairs.height:,} assigned. D39 must partition -- a pair kept against two "
        "episodes is double-counted, one dropped is lost."
    )
    assert pairs.get_column("intubation_episode_id").null_count() == 0, (
        "some pairs were not assigned to an episode. Every pair is in a block and every "
        "block in index_imv has at least one candidate episode, so the join key is wrong."
    )
    print(f"pairs : {pairs.height:,}   (D39 assignment conserved every one)")
    print(pairs.get_column("first_class").value_counts(sort=True))
    print(f"\nin_window pairs : {pairs.get_column('in_window').sum():,} "
          f"({100 * pairs.get_column('in_window').mean():.1f}%)")
    print(pairs.get_column("gap_minutes").describe())
    return (pairs,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The two index pairs

        The **first** pair is chosen without reference to t₀ — it is the medication signal's
        own candidate for the intubation and is free to disagree with the device. The
        **nearest** pair is tied to the IMV episode this study is about, so its offset is
        small by construction and measures charting proximity instead.

        Reporting one alone discards what the other measures. `first_is_nearest` turns the
        overlap into a result: the fraction of encounters where the earliest
        sedative–paralytic co-administration of the stay *is* the one at the index
        intubation.

        Ties for the nearest pair are broken by taking the earlier one, so output is
        deterministic.
        """
    )
    return


@app.cell
def _(pairs, pl):
    # D43. n_*_admin and *_span_min are the fold's audit trail (how much charting the
    # collapse folded into this member) and travel with the rest of that member's columns
    # rather than being appended at the end. Column ORDER here is a contract: 07's schema
    # gate asserts exact column-list equality against method_PAIR_episode.parquet, so this
    # list must be mirrored there, not just matched by name.
    INDEX_PAIR_FIELDS = [
        "pair_id", "first_class",
        "sed_med_category", "sed_med_dose", "sed_med_dose_unit", "n_sed_admin", "sed_span_min",
        "para_med_category", "para_med_dose", "para_med_dose_unit", "n_para_admin", "para_span_min",
        "gap_minutes", "pair_to_t0_min",
    ]

    def _index_pair(prefix, sort_by, descending):
        return (
            pairs.sort(["intubation_episode_id"] + sort_by, descending=[False] + descending)
            .group_by("intubation_episode_id", maintain_order=True)
            .first()
            .select(
                ["intubation_episode_id"]
                + [pl.col(c).alias(f"{prefix}_{c}") for c in INDEX_PAIR_FIELDS]
            )
        )

    # first: earliest pair_seq, which is scan order and therefore chronological.
    first_pair = _index_pair("first", ["pair_seq"], [False])
    # near: smallest |pair_to_t0_min|; ties to the earlier pair, hence pair_seq as tiebreak.
    near_pair = _index_pair(
        "near", [pl.col("pair_to_t0_min").abs().alias("_abs"), "pair_seq"], [False, False]
    )

    print(f"episodes with an index pair : {first_pair.height:,}")
    return first_pair, near_pair


@app.cell
def _(
    METHOD_ID,
    first_pair,
    index_imv,
    near_pair,
    pairs,
    pl,
    unpaired_counts,
):
    # Aggregated per EPISODE, over the pairs D39 assigned to it -- not per block.
    _agg = pairs.group_by("intubation_episode_id").agg(
        n_pairs=pl.len(),
        detected_in_window=pl.col("in_window").any(),
    )

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
        .join(_agg, on="intubation_episode_id", how="left")
        # unpaired_counts is a BLOCK-level quantity: the scan never paired those rows, so
        # there is no pair_dttm to assign them by (D32, D39). They are joined on the block
        # and therefore repeat across a block's episodes -- read them per block, not summed.
        .join(unpaired_counts, on="encounter_block", how="left")
        .join(first_pair, on="intubation_episode_id", how="left")
        .join(near_pair, on="intubation_episode_id", how="left")
        .with_columns(
            method_id=pl.lit(METHOD_ID),
            n_pairs=pl.col("n_pairs").fill_null(0).cast(pl.Int32),
            n_unpaired_sed=pl.col("n_unpaired_sed").fill_null(0).cast(pl.Int32),
            n_unpaired_para=pl.col("n_unpaired_para").fill_null(0).cast(pl.Int32),
            detected_in_window=pl.col("detected_in_window").fill_null(False),
        )
        # `detected` is n_pairs > 0 -- derived from the canonical pair table, never computed
        # beside it, so the binary and the pairs cannot disagree (§6.5).
        .with_columns(
            detected=pl.col("n_pairs") > 0,
            # null, not false, when there are no pairs: "the two index pairs differ" and
            # "there are no index pairs" are different statements.
            first_is_nearest=pl.when(pl.col("n_pairs") > 0)
            .then(pl.col("first_pair_id") == pl.col("near_pair_id"))
            .otherwise(None),
        )
        .select(
            # §6.4 core, minus the ranked columns PAIR has no analogue for, plus the §6.5
            # pair extension.
            [
                "intubation_episode_id", "encounter_block", "patient_id", "ep_num",
                "cohort_run_id", "index_class", "index_qualified", "method_id",
                "imv_dttm", "detected",
                "n_pairs", "n_unpaired_sed", "n_unpaired_para", "detected_in_window",
                "first_is_nearest",
            ]
            + [c for c in first_pair.columns if c != "intubation_episode_id"]
            + [c for c in near_pair.columns if c != "intubation_episode_id"]
        )
        .sort(["encounter_block", "ep_num"])
    )

    assert method_episode.height == index_imv.height, "one row per candidate episode required"
    assert method_episode.get_column("intubation_episode_id").is_unique().all()
    # The pairs table is canonical, so the counts on this table must add back up to it.
    assert method_episode.get_column("n_pairs").sum() == pairs.height, (
        f"n_pairs sums to {method_episode.get_column('n_pairs').sum():,} against "
        f"{pairs.height:,} pair rows -- the episode aggregation lost or duplicated pairs."
    )
    assert method_episode.filter(
        pl.col("detected") & pl.col("first_pair_id").is_null()
    ).height == 0, "a detected episode is missing its first index pair"
    assert method_episode.filter(
        ~pl.col("detected") & pl.col("first_pair_id").is_not_null()
    ).height == 0, "an undetected episode carries an index pair"
    # detected_in_window can only be true where detected is -- the window flag is computed
    # per pair, so a window hit without a pair is impossible.
    assert method_episode.filter(
        pl.col("detected_in_window") & ~pl.col("detected")
    ).height == 0, "detected_in_window without a pair"
    return (method_episode,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The declared lists must match what came out

        D8 duplicates the medication lists into every method deliberately, so that each can
        be changed without touching the others. The cost of that choice is that the lists
        can silently drift apart. This block pays the cost back: it checks the values the
        scan actually emitted against the lists declared at the top, in both directions.

        A value in the output that is not in the declaration means the filter is not doing
        what it says. A declared value absent from the output is *not* an error — a site may
        simply not stock the agent — but it is printed, because the same silence is what a
        typo produces.
        """
    )
    return


@app.cell
def _(PARA_CATEGORIES, SED_CATEGORIES, pairs, pl):
    # Under D43.5 a member's med_category is the event's LABEL, so it may name several
    # agents ("fentanyl+propofol"). Split it back apart before checking against the declared
    # lists -- the check is about which agents reached the output, not which labels did.
    def _agents_in(col):
        return {
            _a
            for _label in pairs.get_column(col).unique().to_list()
            for _a in _label.split("+")
        }

    _sed_seen = _agents_in("sed_med_category")
    _para_seen = _agents_in("para_med_category")

    _sed_extra = sorted(_sed_seen - set(SED_CATEGORIES))
    _para_extra = sorted(_para_seen - set(PARA_CATEGORIES))
    assert not _sed_extra, f"sedative members not in the declared SED list: {_sed_extra}"
    assert not _para_extra, f"paralytic members not in the declared PARA list: {_para_extra}"

    print(f"distinct SED  event labels paired : "
          f"{pairs.get_column('sed_med_category').n_unique()}")
    print(f"distinct PARA event labels paired : "
          f"{pairs.get_column('para_med_category').n_unique()}")
    print(pairs.get_column("para_med_category").value_counts(sort=True))
    print(f"SED  declared {len(SED_CATEGORIES)}, paired {len(_sed_seen)}: "
          f"{', '.join(sorted(_sed_seen))}")
    print(f"  never paired: {', '.join(sorted(set(SED_CATEGORIES) - _sed_seen)) or '—'}")
    print(f"PARA declared {len(PARA_CATEGORIES)}, paired {len(_para_seen)}: "
          f"{', '.join(sorted(_para_seen))}")
    print(f"  never paired: {', '.join(sorted(set(PARA_CATEGORIES) - _para_seen)) or '—'}")

    # Under D43.6 a member's dose/unit come from the lead agent (alphabetically first in a
    # combined label), not from every agent folded into the event, so this compares the two
    # members' LEAD-AGENT units -- still a legitimate "do the two sides of this pair carry
    # comparable units" signal, it just no longer promises to have inspected every agent
    # named on either side.
    _mixed = (
        pairs.filter(pl.col("sed_med_dose_unit") != pl.col("para_med_dose_unit")).height
    )
    print(
        f"\npairs whose two members carry different dose units : {_mixed:,} "
        f"({100 * _mixed / pairs.height:.1f}%)  — reportable, not reconciled (§7.3)"
    )
    return


@app.cell
def _(METHOD_ID, PAIR_GAP_HOURS, PHI_DIR, method_episode, pairs, pl):
    pairs.write_parquet(PHI_DIR / f"method_{METHOD_ID}_pairs.parquet")
    method_episode.write_parquet(PHI_DIR / f"method_{METHOD_ID}_episode.parquet")

    # No _ranked.json: PAIR is exempt from the §6.2 ranking rule (D30). Writing an empty one
    # would invite 07 to read it.
    assert not (PHI_DIR / f"method_{METHOD_ID}_ranked.json").exists(), (
        "a stale method_PAIR_ranked.json is present from an earlier design. Delete it — "
        "PAIR emits no ranked artifact (D30) and 07 must not find one."
    )
    assert not (PHI_DIR / f"method_{METHOD_ID}_encounter.parquet").exists(), (
        f"method_{METHOD_ID}_encounter.parquet is present from the pre-D35 design. Delete "
        "it -- it holds one row per encounter and 07 must not find it."
    )

    _qual = method_episode.filter(pl.col("index_qualified"))
    print(f"method_{METHOD_ID}_pairs.parquet       {pairs.height:,} pairs -> {PHI_DIR}")
    print(f"method_{METHOD_ID}_episode.parquet     {method_episode.height:,} rows")
    print(f"pair_gap_hours written into the run    {PAIR_GAP_HOURS}")
    print()
    print(
        f"free-running detection on N**  : {_qual.filter(pl.col('detected')).height:,} / "
        f"{_qual.height:,}  ({100 * _qual.get_column('detected').mean():.2f}%)"
    )
    print(
        f"in-window detection on N**     : {_qual.filter(pl.col('detected_in_window')).height:,} / "
        f"{_qual.height:,}  ({100 * _qual.get_column('detected_in_window').mean():.2f}%)"
    )
    _d = _qual.filter(pl.col("detected"))
    if _d.height:
        print(f"first_is_nearest on N**        : {_d.get_column('first_is_nearest').mean():.3f}")
        print("\nfirst-pair offset from t0 (min):")
        print(_d.get_column("first_pair_to_t0_min").describe())
    print("\ndetection by index_class (free-running | in-window):")
    print(
        method_episode.group_by("index_class")
        .agg(
            n=pl.len(),
            rate_free=pl.col("detected").mean().round(4),
            rate_win=pl.col("detected_in_window").mean().round(4),
        )
        .sort("n", descending=True)
    )
    return


if __name__ == "__main__":
    app.run()
