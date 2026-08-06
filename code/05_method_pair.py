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

    # Re-declared literally, not imported from 03 or 04 (D8). They must stay identical to
    # §7.1 and §7.2; the assertion block at the end checks the declared lists against the
    # values actually present in the output.
    SED_CATEGORIES = ["midazolam", "etomidate", "ketamine", "propofol", "fentanyl"]
    PARA_CATEGORIES = ["rocuronium", "succinylcholine", "vecuronium"]
    MED_CATEGORIES = SED_CATEGORIES + PARA_CATEGORIES

    print(f"site           : {SITE}")
    print(f"method         : {METHOD_ID}")
    print(f"pair_gap_hours : {PAIR_GAP_HOURS}   ({PAIR_GAP_MINUTES:.0f} min)")
    print(f"class SED      : {' | '.join(SED_CATEGORIES)}")
    print(f"class PARA     : {' | '.join(PARA_CATEGORIES)}")
    return (
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
    bridge = (
        index_imv.select(
            ["encounter_block", "list_hospitalization_id", "t0_dttm", "window_start", "window_end"]
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
def _(PAIR_GAP_MINUTES, pl, scan_encounter, scan_rows):
    _cols = ["encounter_block", "admin_dttm", "med_category", "med_dose", "med_dose_unit",
             "drug_class"]
    _by_block = scan_rows.select(_cols).partition_by("encounter_block", as_dict=True)

    _rows = []
    _unpaired = []
    for _key, _blk in _by_block.items():
        _eb = _key[0]
        _t = _blk.get_column("admin_dttm").to_list()
        _tmin = [x.timestamp() / 60.0 for x in _t]
        _cls = _blk.get_column("drug_class").to_list()
        _cat = _blk.get_column("med_category").to_list()
        _dose = _blk.get_column("med_dose").to_list()
        _unit = _blk.get_column("med_dose_unit").to_list()

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
                    "para_med_category": _cat[_pi],
                    "para_med_dose": _dose[_pi],
                    "para_med_dose_unit": _unit[_pi],
                    "para_admin_dttm": _t[_pi],
                    "pair_dttm": _t[_i],  # the earlier of the two, by scan order
                    "gap_minutes": round(_gap, 1),
                }
            )
        _n_sed = sum(1 for _k2 in range(len(_cls)) if _cls[_k2] == "SED" and _k2 not in _consumed)
        _unpaired.append(
            {
                "encounter_block": _eb,
                "n_unpaired_sed": _n_sed,
                "n_unpaired_para": len(_cls) - len(_consumed) - _n_sed,
            }
        )

    pairs_raw = pl.DataFrame(_rows) if _rows else None
    unpaired_counts = pl.DataFrame(_unpaired)

    print(f"encounters scanned : {len(_by_block):,}")
    print(f"pairs formed       : {0 if pairs_raw is None else pairs_raw.height:,}")
    print(f"encounters with >=1 pair : {0 if pairs_raw is None else pairs_raw.get_column('encounter_block').n_unique():,}")
    return pairs_raw, unpaired_counts


@app.cell
def _(PAIR_GAP_MINUTES, index_imv, pairs_raw, pl):
    assert pairs_raw is not None, "the scan formed no pairs at all"

    pairs = (
        pairs_raw.join(
            index_imv.select(
                ["encounter_block", "patient_id", "intubation_episode_id", "cohort_run_id",
                 "index_class", "index_qualified", "t0_dttm", "window_start", "window_end"]
            ),
            on="encounter_block",
            how="inner",
        )
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
                "encounter_block", "patient_id", "intubation_episode_id", "cohort_run_id",
                "index_class", "index_qualified", "pair_id", "pair_seq", "first_class",
                "sed_med_category", "sed_med_dose", "sed_med_dose_unit", "sed_admin_dttm",
                "para_med_category", "para_med_dose", "para_med_dose_unit", "para_admin_dttm",
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

    print(f"pairs : {pairs.height:,}")
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
    INDEX_PAIR_FIELDS = [
        "pair_id", "first_class", "sed_med_category", "sed_med_dose", "sed_med_dose_unit",
        "para_med_category", "para_med_dose", "para_med_dose_unit", "gap_minutes",
        "pair_to_t0_min",
    ]

    def _index_pair(prefix, sort_by, descending):
        return (
            pairs.sort(["encounter_block"] + sort_by, descending=[False] + descending)
            .group_by("encounter_block", maintain_order=True)
            .first()
            .select(
                ["encounter_block"]
                + [pl.col(c).alias(f"{prefix}_{c}") for c in INDEX_PAIR_FIELDS]
            )
        )

    # first: earliest pair_seq, which is scan order and therefore chronological.
    first_pair = _index_pair("first", ["pair_seq"], [False])
    # near: smallest |pair_to_t0_min|; ties to the earlier pair, hence pair_seq as tiebreak.
    near_pair = _index_pair(
        "near", [pl.col("pair_to_t0_min").abs().alias("_abs"), "pair_seq"], [False, False]
    )

    print(f"encounters with an index pair : {first_pair.height:,}")
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
    _agg = pairs.group_by("encounter_block").agg(
        n_pairs=pl.len(),
        detected_in_window=pl.col("in_window").any(),
    )

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
        .join(_agg, on="encounter_block", how="left")
        .join(unpaired_counts, on="encounter_block", how="left")
        .join(first_pair, on="encounter_block", how="left")
        .join(near_pair, on="encounter_block", how="left")
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
                "encounter_block", "patient_id", "intubation_episode_id", "cohort_run_id",
                "index_class", "index_qualified", "method_id", "imv_dttm", "detected",
                "n_pairs", "n_unpaired_sed", "n_unpaired_para", "detected_in_window",
                "first_is_nearest",
            ]
            + [c for c in first_pair.columns if c != "encounter_block"]
            + [c for c in near_pair.columns if c != "encounter_block"]
        )
        .sort("encounter_block")
    )

    assert method_encounter.height == index_imv.height, "one row per cohort encounter required"
    assert method_encounter.filter(
        pl.col("detected") & pl.col("first_pair_id").is_null()
    ).height == 0, "a detected encounter is missing its first index pair"
    assert method_encounter.filter(
        ~pl.col("detected") & pl.col("first_pair_id").is_not_null()
    ).height == 0, "an undetected encounter carries an index pair"
    # detected_in_window can only be true where detected is -- the window flag is computed
    # per pair, so a window hit without a pair is impossible.
    assert method_encounter.filter(
        pl.col("detected_in_window") & ~pl.col("detected")
    ).height == 0, "detected_in_window without a pair"
    return (method_encounter,)


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
    _sed_seen = set(pairs.get_column("sed_med_category").unique().to_list())
    _para_seen = set(pairs.get_column("para_med_category").unique().to_list())

    _sed_extra = sorted(_sed_seen - set(SED_CATEGORIES))
    _para_extra = sorted(_para_seen - set(PARA_CATEGORIES))
    assert not _sed_extra, f"sedative members not in the declared SED list: {_sed_extra}"
    assert not _para_extra, f"paralytic members not in the declared PARA list: {_para_extra}"

    print(f"SED  declared {len(SED_CATEGORIES)}, paired {len(_sed_seen)}: "
          f"{', '.join(sorted(_sed_seen))}")
    print(f"  never paired: {', '.join(sorted(set(SED_CATEGORIES) - _sed_seen)) or '—'}")
    print(f"PARA declared {len(PARA_CATEGORIES)}, paired {len(_para_seen)}: "
          f"{', '.join(sorted(_para_seen))}")
    print(f"  never paired: {', '.join(sorted(set(PARA_CATEGORIES) - _para_seen)) or '—'}")

    _mixed = (
        pairs.filter(pl.col("sed_med_dose_unit") != pl.col("para_med_dose_unit")).height
    )
    print(
        f"\npairs whose two members carry different dose units : {_mixed:,} "
        f"({100 * _mixed / pairs.height:.1f}%)  — reportable, not reconciled (§7.3)"
    )
    return


@app.cell
def _(METHOD_ID, PAIR_GAP_HOURS, PHI_DIR, method_encounter, pairs, pl):
    pairs.write_parquet(PHI_DIR / f"method_{METHOD_ID}_pairs.parquet")
    method_encounter.write_parquet(PHI_DIR / f"method_{METHOD_ID}_encounter.parquet")

    # No _ranked.json: PAIR is exempt from the §6.2 ranking rule (D30). Writing an empty one
    # would invite 07 to read it.
    assert not (PHI_DIR / f"method_{METHOD_ID}_ranked.json").exists(), (
        "a stale method_PAIR_ranked.json is present from an earlier design. Delete it — "
        "PAIR emits no ranked artifact (D30) and 07 must not find one."
    )

    _qual = method_encounter.filter(pl.col("index_qualified"))
    print(f"method_{METHOD_ID}_pairs.parquet       {pairs.height:,} pairs -> {PHI_DIR}")
    print(f"method_{METHOD_ID}_encounter.parquet   {method_encounter.height:,} rows")
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
        method_encounter.group_by("index_class")
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
