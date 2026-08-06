import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import textwrap
    from itertools import combinations, product
    from pathlib import Path

    import matplotlib

    matplotlib.use("Agg")  # notebooks run headless from the CLI
    import matplotlib.pyplot as plt
    import polars as pl
    from matplotlib.ticker import NullFormatter

    import marimo as mo

    return NullFormatter, Path, combinations, json, mo, pl, plt, product, textwrap


@app.cell
def _(mo):
    mo.md(
        """
        # 07 — Agreement, timing, reference and specificity

        The only notebook that sees more than one method. It is also the **schema
        gatekeeper**: every input is validated against §6.4 / §6.5 before a single number is
        computed, because the failure this guards against is silent. Two artifacts from
        different cohort runs join cleanly — the ids match, the rows are real — and describe
        different patients. `cohort_run_id` is the column that makes that detectable.

        **The single subsetting step in the whole pipeline lives here.** Tiers A, B, C and E
        are computed on `index_class = 'qualified'` only. Tier D is the one place the
        excluded strata are used.

        **`PAIR` is reported on two bases and every Tier A table is computed twice.**
        `PAIR`'s `detected` is free-running over the whole encounter while `SED` and `PARA`
        are window-restricted (D27), so a naive three-way table would compare signals
        measured over different spans. `in_window` is the matched-denominator reading and is
        the one to quote head to head; `free_running` shows what the method finds when
        allowed to look everywhere. `SED` and `PARA` are identical across the two bases by
        construction, so they are emitted once rather than duplicated as rows a reader would
        have to check are copies.

        Design: `docs/superpowers/specs/2026-08-04-intubation-method-comparison-design.md` §8
        """
    )
    return


@app.cell
def _(Path, json):
    _config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(_config_path, "r") as _f:
        config = json.load(_f)

    SITE = config["site_name"]
    WINDOW_HOURS = config["window_hours"]
    PAIR_GAP_HOURS = config["pair_gap_hours"]
    INFUSION_PREP_MINUTES = config["infusion_prep_minutes"]  # D40, Tier F only
    # D43. Named here only so the published captions can state the fold's width: 05 does the
    # collapsing, but E.2's gap distribution is now measured between agent EVENTS, and a
    # reader cannot interpret that number without knowing how wide an event may be.
    COLLAPSE_GAP_MINUTES = float(config["collapse_gap_minutes"])
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    METHODS = ["SED", "PARA", "PAIR"]
    RANKED_METHODS = ["SED", "PARA"]  # PAIR emits no ranked artifact (D30)
    BASES = ["free_running", "in_window"]
    MIN_CELL = 10  # §9 minimum cell size for anything published

    print(f"site           : {SITE}")
    print(f"methods        : {', '.join(METHODS)}")
    print(f"window         : +/- {WINDOW_HOURS} h")
    print(f"pair_gap_hours : {PAIR_GAP_HOURS}")
    print(f"prep gap       : {INFUSION_PREP_MINUTES} min   (D40, Tier F only)")
    print(f"collapse_gap   : {COLLAPSE_GAP_MINUTES:.0f} min   (agent-event fold, D43)")
    print(f"min cell       : {MIN_CELL}")
    return (
        BASES,
        COLLAPSE_GAP_MINUTES,
        INFUSION_PREP_MINUTES,
        METHODS,
        MIN_CELL,
        PAIR_GAP_HOURS,
        PHI_DIR,
        RANKED_METHODS,
        SHARE_DIR,
        SITE,
        WINDOW_HOURS,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 0 — the schema gatekeeper

        The artifact contracts are checked as contracts. `SED` and `PARA` carry the §6.4
        ranked schema; `PAIR` carries the §6.5 pair schema, which **replaces** the ranked
        columns rather than extending them. An undeclared column is as much a violation as a
        missing one — it means a method invented a field the agreement layer does not know
        how to interpret, and ignoring it silently would let two methods drift into
        reporting different things under the same name.
        """
    )
    return


@app.cell
def _(METHODS, PHI_DIR, pl):
    _CORE = {
        "intubation_episode_id": pl.String,
        "encounter_block": pl.Int32,
        "patient_id": pl.String,
        "ep_num": pl.Int32,
        "cohort_run_id": pl.String,
        "index_class": pl.String,
        "index_qualified": pl.Boolean,
        "method_id": pl.String,
        "imv_dttm": pl.Datetime,
        "detected": pl.Boolean,
    }
    _RANKED_TAIL = {
        "n_before": pl.Int32,
        "n_after": pl.Int32,
        "nearest_before_med": pl.String,
        "nearest_before_min": pl.Float64,
        "nearest_after_med": pl.String,
        "nearest_after_min": pl.Float64,
        # D40 / D41. Tier F reads these and nothing else does -- Tiers A-E stay on
        # `detected` (D42), so every number in them is comparable across the change.
        "detected_induction_only": pl.Boolean,
        "n_after_induction": pl.Int32,
        "n_after_prep": pl.Int32,
        "n_before_during": pl.Int32,
        "n_after_during": pl.Int32,
    }
    # D43. Mirrors INDEX_PAIR_FIELDS in 05 EXACTLY, order included -- the assert below is a
    # list-equality check, so a column in the right set but the wrong place fails the run.
    # n_*_admin and *_span_min are the fold's audit trail (how many administration rows the
    # 15-minute anchored collapse merged into that member, and how far apart the first and
    # last of them were), so they sit with the rest of their member's columns rather than
    # being appended at the end.
    _INDEX_PAIR_FIELDS = [
        "pair_id", "first_class",
        "sed_med_category", "sed_med_dose", "sed_med_dose_unit", "n_sed_admin", "sed_span_min",
        "para_med_category", "para_med_dose", "para_med_dose_unit", "n_para_admin",
        "para_span_min",
        "gap_minutes", "pair_to_t0_min",
    ]
    _PAIR_TAIL = (
        ["n_pairs", "n_unpaired_sed", "n_unpaired_para", "detected_in_window", "first_is_nearest"]
        + [f"first_{c}" for c in _INDEX_PAIR_FIELDS]
        + [f"near_{c}" for c in _INDEX_PAIR_FIELDS]
    )

    EPISODE_SCHEMA = {
        "SED": (list(_CORE) + list(_RANKED_TAIL), {**_CORE, **_RANKED_TAIL}),
        "PARA": (list(_CORE) + list(_RANKED_TAIL), {**_CORE, **_RANKED_TAIL}),
        "PAIR": (list(_CORE) + _PAIR_TAIL, _CORE),
    }

    method_tables = {}
    for _m in METHODS:
        _stale = PHI_DIR / f"method_{_m}_encounter.parquet"
        assert not _stale.exists(), (
            f"{_stale.name} is present from the pre-D35 design. It holds one row per "
            "encounter and would supply the wrong denominator silently. Delete it and "
            f"re-run 0{'345'[METHODS.index(_m)]}."
        )
        _df = pl.read_parquet(PHI_DIR / f"method_{_m}_episode.parquet")
        _cols, _types = EPISODE_SCHEMA[_m]

        assert list(_df.columns) == _cols, (
            f"method {_m}: columns do not match its contract.\n"
            f"  missing : {sorted(set(_cols) - set(_df.columns))}\n"
            f"  extra   : {sorted(set(_df.columns) - set(_cols))}"
        )
        for _col, _dtype in _types.items():
            _actual = _df.schema[_col]
            assert _actual.base_type() == _dtype.base_type(), (
                f"method {_m}: {_col} is {_actual}, expected {_dtype}"
            )
        assert _df.get_column("method_id").unique().to_list() == [_m], (
            f"method {_m}: the file's method_id column disagrees with its filename"
        )
        assert _df.get_column("intubation_episode_id").is_duplicated().sum() == 0

        # `detected` must be DERIVED, never computed beside the structure it summarises. For
        # SED and PARA that structure is the rank ladder; for PAIR it is the pair table.
        # This is where the two would be caught disagreeing.
        _derived = (
            (pl.col("n_pairs") > 0)
            if _m == "PAIR"
            else ((pl.col("n_before") > 0) | (pl.col("n_after") > 0))
        )
        _mismatch = _df.filter(pl.col("detected") != _derived).height
        assert _mismatch == 0, (
            f"method {_m}: {_mismatch:,} rows where `detected` disagrees with the structure "
            "it is supposed to be derived from."
        )

        # Same contract for D40's variant. It shares the before-term untouched (D40 exempts
        # the pre-t0 half) and can only ever be a subset, so a violation means the two
        # columns were computed from different sets rather than one being a filtered form
        # of the other -- exactly the drift the shared term exists to prevent.
        if _m != "PAIR":
            _io = (pl.col("n_before") > 0) | (pl.col("n_after_induction") > 0)
            _bad = _df.filter(pl.col("detected_induction_only") != _io).height
            assert _bad == 0, (
                f"method {_m}: {_bad:,} rows where `detected_induction_only` disagrees with "
                "(n_before > 0) | (n_after_induction > 0)."
            )
            _super = _df.filter(
                pl.col("detected_induction_only") & ~pl.col("detected")
            ).height
            assert _super == 0, (
                f"method {_m}: {_super:,} rows detected under D40 but not without it. "
                "The variant must be a subset."
            )
        method_tables[_m] = _df
        print(f"{_m:<5} {_df.height:,} rows   schema OK   detected-derivation OK")

    # D30: PAIR emits no ranked artifact, and a stale one from an earlier design would be
    # picked up by Tier B as if it were current.
    assert not (PHI_DIR / "method_PAIR_ranked.json").exists(), (
        "method_PAIR_ranked.json exists. PAIR is exempt from the ranking rule (D30); delete "
        "the stale file rather than letting Tier B read it."
    )

    pairs = pl.read_parquet(PHI_DIR / "method_PAIR_pairs.parquet")
    reference = pl.read_parquet(PHI_DIR / "reference_cpt.parquet")
    print(f"PAIR pairs table : {pairs.height:,} pairs")
    print(f"CPT              : {reference.height:,} rows")
    return method_tables, pairs, reference


@app.cell
def _(METHODS, method_tables, pairs, reference):
    _run_ids = {m: method_tables[m].get_column("cohort_run_id").unique().to_list() for m in METHODS}
    _run_ids["PAIRS"] = pairs.get_column("cohort_run_id").unique().to_list()
    _run_ids["CPT"] = reference.get_column("cohort_run_id").unique().to_list()

    for _k, _v in _run_ids.items():
        assert len(_v) == 1, f"{_k} carries {len(_v)} cohort_run_ids: {_v}"

    _distinct = {v[0] for v in _run_ids.values()}
    assert len(_distinct) == 1, (
        "inputs come from different cohort runs and MUST NOT be joined:\n"
        + "\n".join(f"  {k:<6} {v[0]}" for k, v in _run_ids.items())
        + "\nencounter_block is a row position, so the same id means different patients "
        "across runs. Re-run 01 through 06 from one cohort."
    )
    COHORT_RUN_ID = _distinct.pop()
    print(f"all inputs share cohort_run_id = {COHORT_RUN_ID}")
    return (COHORT_RUN_ID,)


@app.cell
def _(PHI_DIR, pl):
    # 02's index artifact, read for its STRATA only -- the labels it attaches without
    # excluding on (§5.10). The methods do not carry these and should not: they are
    # properties of the index event, and a method copying a column it neither computes nor
    # can validate is exactly the silent-drift risk D14 warns about.
    index_strata = pl.read_parquet(PHI_DIR / "index_imv.parquet").select(
        ["intubation_episode_id", "no_lookback", "imv_charted", "charting_delay_min"]
    )
    assert index_strata.get_column("intubation_episode_id").is_unique().all()
    print(f"index strata loaded : {index_strata.height:,} episodes")
    print(f"  no_lookback true  : {index_strata.get_column('no_lookback').sum():,}")
    return (index_strata,)


@app.cell
def _(METHODS, index_strata, method_tables, pl, reference):
    _keys = ["intubation_episode_id", "encounter_block", "patient_id", "ep_num",
             "index_class", "index_qualified"]
    joined = method_tables[METHODS[0]].select(_keys)

    for _m in ("SED", "PARA"):
        joined = joined.join(
            method_tables[_m].select(
                "intubation_episode_id",
                pl.col("detected").alias(f"{_m.lower()}_detected"),
                pl.col("nearest_before_min").alias(f"{_m.lower()}_bef"),
                pl.col("nearest_after_min").alias(f"{_m.lower()}_aft"),
                # D40, read by Tier F alone. Carried here rather than re-read from the
                # method table so Tier F joins nothing the other tiers have not already
                # validated through the §6.4 schema gate.
                pl.col("detected_induction_only").alias(
                    f"{_m.lower()}_detected_induction_only"
                ),
                pl.col("n_after_prep").alias(f"{_m.lower()}_n_after_prep"),
            ),
            on="intubation_episode_id",
            how="inner",
        )

    joined = joined.join(
        method_tables["PAIR"].select(
            "intubation_episode_id",
            pl.col("detected").alias("pair_detected"),
            pl.col("detected_in_window").alias("pair_detected_in_window"),
            "n_pairs",
            "first_is_nearest",
            "first_pair_to_t0_min",
            "near_pair_to_t0_min",
        ),
        on="intubation_episode_id",
        how="inner",
    ).join(
        reference.select("intubation_episode_id", "cpt_present"),
        on="intubation_episode_id",
        how="inner",
    ).join(
        # Index strata, joined from 02's own artifact rather than carried through every
        # method table. `no_lookback` is a property of the index event, not a method
        # output, so putting it in the §6.4 core would make three notebooks copy a column
        # none of them computes or can check.
        index_strata,
        on="intubation_episode_id",
        how="inner",
    )

    assert joined.height == method_tables[METHODS[0]].height, (
        "the join lost or duplicated rows; every candidate episode must appear exactly once"
    )
    assert joined.get_column("intubation_episode_id").is_unique().all()
    # A window hit is a property of a pair, so it cannot exist without one.
    assert joined.filter(
        pl.col("pair_detected_in_window") & ~pl.col("pair_detected")
    ).height == 0, "detected_in_window is true where no pair exists"

    print(f"joined analytic table : {joined.height:,} rows (one per candidate episode)")
    print(f"  distinct blocks     : {joined.get_column('encounter_block').n_unique():,}")
    print(f"  distinct patients   : {joined.get_column('patient_id').n_unique():,}")
    print(joined.head(6))
    return (joined,)


@app.cell
def _(joined, pl):
    analytic = joined.filter(pl.col("index_class") == "qualified")
    N_INDEX = analytic.height

    print(f"candidate episodes    : {joined.height:,}")
    print(f"N** index set         : {N_INDEX:,}   <- the denominator for Tiers A, B, C and E")
    print(f"  blocks              : {analytic.get_column('encounter_block').n_unique():,}")
    print(f"  patients            : {analytic.get_column('patient_id').n_unique():,}")
    return N_INDEX, analytic


@app.cell
def _(MIN_CELL, pl):
    def apply_min_cell(df, count_cols, label):
        """Drop any row where a published count falls in 1..MIN_CELL-1.

        A count of exactly zero is kept: it identifies nobody, and dropping it would turn
        "this never happened" into "this is missing", which is a different and worse
        statement in a multi-site study. Counts of 1..9 are the disclosive range and those
        rows are removed entirely rather than blanked, since a blanked cell in a table whose
        margins are published is often recoverable by subtraction.

        Never silent: what was dropped is always printed.
        """
        _mask = pl.lit(False)
        for _c in count_cols:
            _mask = _mask | ((pl.col(_c) > 0) & (pl.col(_c) < MIN_CELL))
        kept, dropped = df.filter(~_mask), df.filter(_mask)
        if dropped.height:
            print(
                f"  [{label}] {dropped.height} row(s) suppressed under the n>={MIN_CELL} rule "
                f"on {count_cols}"
            )
            print(dropped)
        return kept

    def detected_expr(method, basis):
        """The detection column for a method on a given basis.

        SED and PARA are window-restricted by construction, so their column is the same on
        both bases. That is why they are emitted once in the published tables and why a
        difference there would be a bug rather than a finding.
        """
        if method != "PAIR":
            return pl.col(f"{method.lower()}_detected")
        return pl.col("pair_detected" if basis == "free_running" else "pair_detected_in_window")

    def unit_counts(df):
        """Episodes, blocks and patients for one frame.

        Reported on every rate table under D35: a block may contribute several episodes, so
        an episode rate and an encounter rate are different numbers and a table naming
        neither is ambiguous. It also makes the dependence visible where it matters --
        kappa assumes independent units, and a block contributing seven episodes violates
        that quietly.
        """
        return {
            "n_episodes": df.height,
            "n_blocks": df.get_column("encounter_block").n_unique(),
            "n_patients": df.get_column("patient_id").n_unique(),
        }

    return apply_min_cell, detected_expr, unit_counts


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier A — do the methods find the same episodes?

        **Read this tier as conditional, not marginal (D38).** An episode qualifies only if
        one of the eight method medication categories was charted `given` in the window, and
        `SED` and `PARA` read those same eight categories over that same window in that same
        table. So `SED ∨ PARA` is true for every episode in the denominator **by
        construction**, and the question is narrower than the heading: not *do the methods
        find the same intubations*, but **given that an induction agent was charted, do the
        methods catalog it the same way**.

        The `SED−/PARA−` cell of A.2 and the concordance-0 row of A.3 are therefore near-
        empty by definition. What lands in them is the **D25 on-t₀ population** — an
        administration falling exactly on t₀ belongs to neither half-open direction, so the
        episode passes the filter and still scores `detected = false`. Both are labelled as
        such rather than reported as agreement evidence.

        `PAIR` is exempt: it is free-running (D27), so it can fire on an episode the window
        filter rejected and its cells are not constrained.
        """
    )
    return


@app.cell
def _(
    BASES,
    COHORT_RUN_ID,
    METHODS,
    N_INDEX,
    SHARE_DIR,
    analytic,
    apply_min_cell,
    detected_expr,
    pl,
):
    _rows = []
    for _basis in BASES:
        for _m in METHODS:
            if _m != "PAIR" and _basis != BASES[0]:
                continue
            _rows.append(
                {
                    "cohort_run_id": COHORT_RUN_ID,
                    "method_id": _m,
                    "pair_basis": "—" if _m != "PAIR" else _basis,
                    "n_detected": analytic.filter(detected_expr(_m, _basis)).height,
                    "n_index_set": N_INDEX,
                }
            )
    a1 = pl.DataFrame(_rows).with_columns(
        rate=(pl.col("n_detected") / pl.col("n_index_set")).round(4)
    )

    a1_pub = apply_min_cell(a1, ["n_detected"], "A.1")
    a1_pub.write_csv(SHARE_DIR / "agreement_detection_rates.csv")
    print("A.1 detection rate per method")
    print(a1_pub)

    _f = a1.filter((pl.col("method_id") == "PAIR") & (pl.col("pair_basis") == "free_running"))
    _w = a1.filter((pl.col("method_id") == "PAIR") & (pl.col("pair_basis") == "in_window"))
    print(
        f"\n  PAIR free_running {_f.item(0, 'rate'):.4f} vs in_window {_w.item(0, 'rate'):.4f} "
        f"— a difference of {_f.item(0, 'n_detected') - _w.item(0, 'n_detected'):,} encounters.\n"
        "  Those are stays where a sedative-paralytic co-administration exists but NOT near\n"
        "  the index IMV. A large gap means either reintubation activity the study is not\n"
        "  labelling, or an index t0 that is landing away from the real intubation."
    )
    return (a1,)


@app.cell
def _(
    BASES,
    COHORT_RUN_ID,
    METHODS,
    SHARE_DIR,
    analytic,
    apply_min_cell,
    combinations,
    detected_expr,
    pl,
):
    _rows = []
    for _basis in BASES:
        for _m1, _m2 in combinations(METHODS, 2):
            if "PAIR" not in (_m1, _m2) and _basis != BASES[0]:
                continue
            _c1, _c2 = detected_expr(_m1, _basis), detected_expr(_m2, _basis)

            _both = analytic.filter(_c1 & _c2).height
            _only_a = analytic.filter(_c1 & ~_c2).height
            _only_b = analytic.filter(~_c1 & _c2).height
            _neither = analytic.filter(~_c1 & ~_c2).height
            _n = analytic.height

            # Cohen's kappa written out rather than imported, so a reader can recompute it
            # from the four published cells by hand. That auditability is the reason the full
            # table is published and not just the coefficient.
            _po = (_both + _neither) / _n
            _pe = (
                (_both + _only_a) * (_both + _only_b)
                + (_only_b + _neither) * (_only_a + _neither)
            ) / (_n * _n)
            _rows.append(
                {
                    "cohort_run_id": COHORT_RUN_ID,
                    "method_a": _m1,
                    "method_b": _m2,
                    "pair_basis": "—" if "PAIR" not in (_m1, _m2) else _basis,
                    "both": _both,
                    "only_a": _only_a,
                    "only_b": _only_b,
                    "neither": _neither,
                    "n": _n,
                    "jaccard": round(_both / max(_both + _only_a + _only_b, 1), 4),
                    "cohen_kappa": round((_po - _pe) / (1 - _pe), 4) if _pe != 1 else None,
                    "pct_agreement": round(_po, 4),
                }
            )

    a2 = pl.DataFrame(_rows)
    a2_pub = apply_min_cell(a2, ["both", "only_a", "only_b", "neither"], "A.2")
    a2_pub.write_csv(SHARE_DIR / "agreement_pairwise.csv")

    for _r in a2.to_dicts():
        _a, _b = _r["method_a"], _r["method_b"]
        print(f"\nA.2  {_a} x {_b}   basis={_r['pair_basis']}")
        print(f"{'':>12}{_b + '+':>10}{_b + '-':>11}{'total':>11}")
        print(f"  {_a + '+':<9}{_r['both']:>10,}{_r['only_a']:>11,}{_r['both'] + _r['only_a']:>11,}")
        print(f"  {_a + '-':<9}{_r['only_b']:>10,}{_r['neither']:>11,}{_r['only_b'] + _r['neither']:>11,}")
        print(
            f"  Jaccard {_r['jaccard']:.4f}   kappa {_r['cohen_kappa']}   "
            f"raw agreement {_r['pct_agreement']:.4f}"
        )

    print(
        "\n  The off-diagonals each read differently:\n"
        "    only SED  — expected to be the majority; sedation without paralysis is a real\n"
        "                and common technique.\n"
        "    only PARA — should be small; a paralytic with no induction agent charted is\n"
        "                closer to a documentation gap than a clinical choice.\n"
        "\n  PARA x PAIR on the in_window basis should be the TIGHTEST of the three, and if it\n"
        "  is not, something is wrong: a PAIR detection requires a paralytic by definition,\n"
        "  so PAIR+ & PARA- ought to be near-empty there. A non-trivial count means the two\n"
        "  notebooks disagree about the paralytic list or about window membership — a bug,\n"
        "  not a finding. This is the closest thing the design has to a cross-notebook\n"
        "  integrity check, and D8's deliberate duplication is what makes it meaningful."
    )
    return (a2,)


@app.cell
def _(analytic, pairs, pl):
    # The PARA x PAIR `only_b` cell -- PAIR+ and PARA- on the matched basis -- is the design's
    # cross-notebook integrity check, so a non-zero count is decomposed here rather than left
    # for someone to dig out by hand. Two boundary effects put a legitimate floor under it,
    # and anything NOT explained by them is the bug the check exists to catch.
    #
    # Keyed on intubation_episode_id, NOT encounter_block. Under D35 a block holds several
    # episodes and D39 assigns each pair to one of them, so joining on the block pulls in
    # pairs belonging to a DIFFERENT episode and scores them against the wrong t0. That
    # fans the frame out and makes the explained counts exceed the count being explained --
    # which is how this was caught.
    _susp = analytic.filter(
        pl.col("pair_detected_in_window") & ~pl.col("para_detected")
    ).select("intubation_episode_id")
    print(f"PARA x PAIR, only_b (PAIR+ & PARA-) on in_window : {_susp.height}")

    if _susp.height:
        # `pairs` already carries imv_dttm -- the t0 of the episode D39 assigned it to --
        # so no join to a method table is needed to get the right anchor.
        _d = (
            pairs.join(_susp, on="intubation_episode_id", how="semi")
            .filter(pl.col("in_window"))
            .with_columns(
                # (1) D25: a paralytic charted exactly on t0 is in neither half-open
                #     direction, so PARA never ranks it -- while PAIR fires on the pair.
                para_at_t0=pl.col("para_admin_dttm") == pl.col("imv_dttm"),
                # (2) §6.5: `in_window` is evaluated on pair_dttm, the EARLIER member. A pair
                #     whose sedative is inside the window and whose paralytic is outside it
                #     is in-window by that definition and invisible to PARA.
                para_outside=(pl.col("para_admin_dttm") - pl.col("imv_dttm"))
                .dt.total_seconds()
                .abs()
                .truediv(60)
                > 180,
            )
        )
        # Per EPISODE, not per pair: the cell being decomposed counts episodes, so an
        # episode is explained when at least one of its in-window pairs is.
        _by_ep = _d.group_by("intubation_episode_id").agg(
            any_at_t0=pl.col("para_at_t0").any(),
            any_outside=pl.col("para_outside").any(),
        )
        _n_t0 = _by_ep.filter(pl.col("any_at_t0")).height
        _n_out = _by_ep.filter(~pl.col("any_at_t0") & pl.col("any_outside")).height
        print(f"  explained by D25 (paralytic exactly on t0)      : {_n_t0}")
        print(f"  explained by §6.5 (in_window is on pair_dttm)   : {_n_out}")

        _bad = _by_ep.filter(~pl.col("any_at_t0") & ~pl.col("any_outside"))
        assert _bad.height == 0, (
            f"{_bad.height} PAIR+/PARA- episodes are explained by NEITHER boundary rule. "
            "That is the list-or-window disagreement this check exists to catch: 05 and 04 "
            "are not reading the paralytic list the same way.\n"
            + str(_d.join(_bad.select("intubation_episode_id"), on="intubation_episode_id"))
        )
        print("  unexplained                                    : 0  — integrity check passes")
    return


@app.cell
def _(
    BASES,
    COHORT_RUN_ID,
    METHODS,
    SHARE_DIR,
    analytic,
    apply_min_cell,
    detected_expr,
    pl,
):
    _frames = []
    for _basis in BASES:
        _n_methods = pl.sum_horizontal(
            *[detected_expr(_m, _basis).cast(pl.Int32) for _m in METHODS]
        )
        _frames.append(
            analytic.with_columns(n_methods=_n_methods)
            .group_by("n_methods")
            .agg(n=pl.len())
            .with_columns(pair_basis=pl.lit(_basis))
        )

    a3 = (
        pl.concat(_frames)
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            pct=(100.0 * pl.col("n") / analytic.height).round(2),
        )
        .select(["cohort_run_id", "pair_basis", "n_methods", "n", "pct"])
        .sort(["pair_basis", "n_methods"])
    )

    a3_pub = apply_min_cell(a3, ["n"], "A.3")
    a3_pub.write_csv(SHARE_DIR / "agreement_concordance.csv")
    print("A.3 concordance histogram")
    print(a3_pub)
    print(
        "\n  Read the n_methods=0 row first. Every encounter here has a documented, sustained\n"
        "  intubation — 02 guaranteed that much, and the arrived-intubated group is already\n"
        "  gone — so this count cannot be explained away as 'the patient came in on a vent'.\n"
        "  It is a direct measure of intubations performed here whose medications were never\n"
        "  charted in the window."
    )
    return (a3,)


@app.cell
def _(mo):
    mo.md(
        """
        ### A.4 — the combination table

        Three sets have eight combinations, which no single 2×2 can show (D33). One row per
        combination, both bases.

        Three rows are structurally near-impossible on the `in_window` basis and are the ones
        to inspect if they are not near zero: `✗ ✗ ✓` (a pair with neither member detected),
        `✗ ✓ ✓` and `✓ ✗ ✓` (a pair whose sedative or paralytic member went undetected by the
        corresponding method). All three imply a list or window disagreement between
        notebooks. On the `free_running` basis they are expected to be non-zero and mean
        something entirely different — a pair outside the window — which is why the basis
        column is not optional.

        > **No upset plot.** This table carries exactly the information an upset plot over
        > three sets would, stays a CSV subject to the n ≥ 10 rule, and needs no figure.
        """
    )
    return


@app.cell
def _(
    BASES,
    COHORT_RUN_ID,
    METHODS,
    SHARE_DIR,
    analytic,
    apply_min_cell,
    detected_expr,
    pl,
    product,
):
    _rows = []
    for _basis in BASES:
        for _combo in product([True, False], repeat=len(METHODS)):
            _mask = pl.lit(True)
            for _m, _want in zip(METHODS, _combo):
                _e = detected_expr(_m, _basis)
                _mask = _mask & (_e if _want else ~_e)
            _n = analytic.filter(_mask).height
            _rows.append(
                {
                    "cohort_run_id": COHORT_RUN_ID,
                    "pair_basis": _basis,
                    **{_m: _w for _m, _w in zip(METHODS, _combo)},
                    "n": _n,
                    "pct": round(100.0 * _n / analytic.height, 2),
                }
            )

    a4 = pl.DataFrame(_rows)
    assert (
        a4.group_by("pair_basis").agg(t=pl.col("n").sum()).get_column("t").to_list()
        == [analytic.height] * len(BASES)
    ), "the eight combinations do not partition the index set"

    a4_pub = apply_min_cell(a4, ["n"], "A.4")
    a4_pub.write_csv(SHARE_DIR / "agreement_combinations.csv")
    print("A.4 combination table")
    print(a4_pub)

    print("\n  the structurally near-impossible rows, in_window basis:")
    print(
        a4.filter(
            (pl.col("pair_basis") == "in_window")
            & pl.col("PAIR")
            & ~(pl.col("SED") & pl.col("PARA"))
        )
    )
    return (a4,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier B — how is charting distributed in time?

        `SED` and `PARA` only. `PAIR` is exempt from the ranking rule and emits no ranked
        artifact (D30) — its timing lives in Tier E, computed from the pair table.

        Read from `method_*_ranked.json`, not from the encounter table: the encounter table
        flattens the ladder to rank 1, and B.2 and B.3 need the whole thing. Each episode
        contributes at most one entry per medication per direction (§6.2), so a patient
        redosed six times weighs the same as one dosed once.
        """
    )
    return


@app.cell
def _(PHI_DIR, RANKED_METHODS, analytic, pl):
    RANKED_ENTRY = pl.Struct(
        {
            "rank": pl.Int64,
            "med_category": pl.String,
            "med_dose": pl.Float64,
            "med_dose_unit": pl.String,
            "admin_dttm": pl.String,
            "delta_minutes": pl.Float64,
            # D40 / D41, per-administration. B.5 decomposes on these. They describe the
            # single dose the ladder kept -- the one nearest t0 -- so a RATE must never be
            # recomputed from them (spec §6.4); that is what Tier F's own tables are for.
            "infusion_prep": pl.Boolean,
            "during_infusion": pl.Boolean,
            "lag_to_infusion_min": pl.Float64,
        }
    )
    RANKED_SCHEMA = {
        "encounter_block": pl.Int32,
        "patient_id": pl.String,
        "index_class": pl.String,
        "intubation_episode_id": pl.String,
        "method_id": pl.String,
        "imv_dttm": pl.String,
        "before": pl.List(RANKED_ENTRY),
        "after": pl.List(RANKED_ENTRY),
    }

    _frames = []
    for _m in RANKED_METHODS:
        # The schema is declared, not inferred. Inference reads the leading records, and an
        # encounter with no detection carries `[]` — from which polars infers List(Null) and
        # then fails on the first real object. Declaring it makes the JSON a checked contract
        # like the parquet rather than a shape discovered at read time.
        _raw = pl.read_ndjson(PHI_DIR / f"method_{_m}_ranked.json", schema=RANKED_SCHEMA)
        for _dir in ("before", "after"):
            _frames.append(
                _raw.select(["intubation_episode_id", "method_id", _dir])
                .explode(_dir)
                .filter(pl.col(_dir).is_not_null())
                .unnest(_dir)
                .with_columns(direction=pl.lit(_dir))
            )

    ranked_long = pl.concat(_frames, how="vertical").join(
        analytic.select("intubation_episode_id"), on="intubation_episode_id", how="inner"
    )
    print(f"ranked entries on the index set : {ranked_long.height:,}")
    return (ranked_long,)


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, pl, ranked_long):
    b1 = (
        ranked_long.group_by(["method_id", "direction"])
        .agg(
            n_entries=pl.len(),
            n_episodes=pl.col("intubation_episode_id").n_unique(),
            median_min=pl.col("delta_minutes").median().round(1),
            q1_min=pl.col("delta_minutes").quantile(0.25).round(1),
            q3_min=pl.col("delta_minutes").quantile(0.75).round(1),
            pct_within_30=(100.0 * (pl.col("delta_minutes").abs() <= 30).mean()).round(1),
        )
        .sort(["method_id", "direction"], descending=[False, True])
        .with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID))
        .select(
            ["cohort_run_id", "method_id", "direction", "n_entries", "n_episodes",
             "median_min", "q1_min", "q3_min", "pct_within_30"]
        )
    )
    b1_pub = apply_min_cell(b1, ["n_entries", "n_episodes"], "B.1")
    b1_pub.write_csv(SHARE_DIR / "timing_offset_summary.csv")
    print("B.1 offset summary, minutes relative to t0")
    print(b1_pub)
    return


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, pl, ranked_long):
    b2 = (
        ranked_long.group_by(["method_id", "direction", "rank"])
        .agg(n=pl.len(), median_min=pl.col("delta_minutes").median().round(1))
        .sort(["method_id", "direction", "rank"], descending=[False, True, False])
        .with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID))
        .select(["cohort_run_id", "method_id", "direction", "rank", "n", "median_min"])
    )
    b2_pub = apply_min_cell(b2, ["n"], "B.2")
    b2_pub.write_csv(SHARE_DIR / "timing_offset_by_rank.csv")
    print("B.2 offset by rank")
    print(b2_pub)
    return


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, pl, ranked_long):
    b3 = (
        ranked_long.group_by(["method_id", "med_category", "direction"])
        .agg(
            n=pl.len(),
            median_min=pl.col("delta_minutes").median().round(1),
            median_dose=pl.col("med_dose").median().round(2),
            n_units=pl.col("med_dose_unit").n_unique(),
            units=pl.col("med_dose_unit").unique().sort().str.join(" | "),
        )
        .sort(["method_id", "direction", "n"], descending=[False, True, True])
        .with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID))
        .select(
            ["cohort_run_id", "method_id", "med_category", "direction", "n",
             "median_min", "median_dose", "n_units", "units"]
        )
    )
    # The n>=10 rule bites hardest here. A rare agent is dropped rather than pooled into an
    # "other" bucket: pooling across agents with different units and dose scales would
    # produce a median that means nothing.
    b3_pub = apply_min_cell(b3, ["n"], "B.3")
    b3_pub.write_csv(SHARE_DIR / "timing_by_medication.csv")
    print("B.3 per-medication breakdown — doses are RAW charted values, read `units` with them")
    print(b3_pub)
    return


@app.cell
def _(mo):
    mo.md("""## Tier C — reference check""")
    return


@app.cell
def _(BASES, COHORT_RUN_ID, METHODS, SHARE_DIR, analytic, detected_expr, pl):
    CAPTURE_FLOOR = 0.05
    _n_coded = analytic.filter(pl.col("cpt_present")).height
    CAPTURE_RATE = _n_coded / max(analytic.height, 1)
    REFERENCE_INFORMATIVE = bool(_n_coded >= 10 and CAPTURE_RATE >= CAPTURE_FLOOR)

    print(f"C.1 capture rate on the index set : {CAPTURE_RATE:.4f}")

    _rows = []
    for _basis in BASES:
        for _m in METHODS:
            if _m != "PAIR" and _basis != BASES[0]:
                continue
            _d = detected_expr(_m, _basis)
            _tp = analytic.filter(_d & pl.col("cpt_present")).height
            _fp = analytic.filter(_d & ~pl.col("cpt_present")).height
            _fn = analytic.filter(~_d & pl.col("cpt_present")).height
            _tn = analytic.filter(~_d & ~pl.col("cpt_present")).height
            _sens = _tp / max(_tp + _fn, 1)
            _ppv = _tp / max(_tp + _fp, 1)
            _ok = REFERENCE_INFORMATIVE
            _rows.append(
                {
                    "cohort_run_id": COHORT_RUN_ID,
                    "method_id": _m,
                    "pair_basis": "—" if _m != "PAIR" else _basis,
                    "reference_id": "CPT",
                    "capture_rate": round(CAPTURE_RATE, 4),
                    "informative": _ok,
                    "tp": _tp if _ok else None,
                    "fp": _fp if _ok else None,
                    "fn": _fn if _ok else None,
                    "tn": _tn if _ok else None,
                    "sensitivity": round(_sens, 4) if _ok else None,
                    "ppv": round(_ppv, 4) if _ok else None,
                    "f1": round(2 * _sens * _ppv / max(_sens + _ppv, 1e-12), 4) if _ok else None,
                }
            )

    c2 = pl.DataFrame(_rows)
    c2.write_csv(SHARE_DIR / "reference_scoring.csv")

    if REFERENCE_INFORMATIVE:
        print(c2)
        print(
            "\n  Read PPV against the capture rate, not on its own. Every encounter here has a\n"
            "  documented intubation by construction, so an encounter the reference failed to\n"
            "  code shows up as a false positive for a method that was right. PPV is bounded\n"
            "  above by capture; sensitivity is the interpretable column.\n"
            "  Codes establish presence, never timing."
        )
    else:
        print(
            f"\n  REFERENCE UNINFORMATIVE — capture {CAPTURE_RATE:.4f} is below the "
            f"{CAPTURE_FLOOR} floor.\n"
            "  Scoring is withheld rather than published. Sensitivity and PPV computed against\n"
            "  a reference this sparse would measure the completeness of the billing extract,\n"
            "  not the performance of the methods, and would be read as the latter."
        )
    return CAPTURE_RATE, REFERENCE_INFORMATIVE


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier D — specificity

        Same methods, same window, same code — only the stratum changes.

        **This tier was weakened by D37 and says so.** It used to rest on
        `arrived_intubated`: those patients were intubated before arrival, so any `SED`
        firing around their first charted IMV row was a false positive *by construction* —
        the one stratum in the study whose answer was known without a gold standard.

        D37 admits that group to the primary analysis, on the argument that an empty
        pre-period usually means nobody charted room air rather than that ventilation
        predates the record. That argument is sound and the group is worth analysing, but it
        costs the study its known-answer stratum. The four contrasts below are the best
        available replacement and **each names its own confounder**. None is a
        false-positive count by construction.

        **D.4 is the salvage.** `SED`, `PARA` and `PAIR`'s windowed reading are identically
        zero on the `no_induction_med` stratum, because D38 built that stratum out of their
        own medication list. `PAIR` on the free-running basis is not constrained — its scan
        covers the whole block — so its rate there measures ambient sedative–paralytic
        pairing on the largest stratum in the study.
        """
    )
    return


@app.cell
def _(BASES, COHORT_RUN_ID, METHODS, detected_expr, pl, unit_counts):
    # One shape for D.1-D.3: group a frame by a column, emit counts and rates for every
    # method-basis series. Defined once here and taken as an argument by the three cells
    # below -- the alternative is three copies of the same eight-line aggregation, which is
    # the duplication D8 wants BETWEEN notebooks, not within one cell block.
    SERIES = []
    for _basis in BASES:
        for _m in METHODS:
            if _m != "PAIR" and _basis != BASES[0]:
                continue
            SERIES.append((_m, _basis, f"{_m}_{_basis}" if _m == "PAIR" else _m))

    def strat_rates(df, group_col, label_col):
        _rows = []
        for _key, _sub in df.group_by(group_col, maintain_order=True):
            _v = _key[0] if isinstance(_key, tuple) else _key
            _r = {
                "cohort_run_id": COHORT_RUN_ID,
                label_col: str(_v),
                **unit_counts(_sub),
            }
            for _m, _basis, _name in SERIES:
                _n = int(_sub.select(detected_expr(_m, _basis)).to_series().sum())
                _r[f"n_detected_{_name}"] = _n
                _r[f"rate_{_name}"] = round(_n / _sub.height, 4) if _sub.height else None
            _rows.append(_r)
        return pl.DataFrame(_rows)

    def count_cols(df):
        return [c for c in df.columns if c.startswith("n_")]

    return SERIES, count_cols, strat_rates


@app.cell
def _(SHARE_DIR, analytic, apply_min_cell, count_cols, strat_rates):
    d1 = strat_rates(analytic.sort("no_lookback"), "no_lookback", "no_lookback")
    d1_pub = apply_min_cell(d1, count_cols(d1), "D.1")
    d1_pub.write_csv(SHARE_DIR / "specificity_by_lookback.csv")
    print("D.1 detection rate by no_lookback, within the index set")
    print("  no_lookback = t0 is the block's first respiratory row -- the old")
    print("  arrived_intubated group, now included (D37) rather than excluded.")
    print("  CONFOUNDER: case mix. These patients are disproportionately transfers.")
    print(d1_pub)
    return (d1_pub,)


@app.cell
def _(SHARE_DIR, analytic, apply_min_cell, count_cols, pl, strat_rates):
    _binned = analytic.with_columns(
        ep_group=pl.when(pl.col("ep_num") == 1).then(pl.lit("1")).otherwise(pl.lit(">1"))
    ).sort("ep_group")
    d2 = strat_rates(_binned, "ep_group", "ep_num")
    d2_pub = apply_min_cell(d2, count_cols(d2), "D.2")
    d2_pub.write_csv(SHARE_DIR / "specificity_by_ep_num.csv")
    print("D.2 detection rate by episode number -- new under D35")
    print("  CONFOUNDER: illness trajectory. A reintubation happens deep in an ICU stay,")
    print("  where the ambient rate of sedative charting is far higher than at admission.")
    print(d2_pub)
    return (d2_pub,)


@app.cell
def _(SHARE_DIR, apply_min_cell, count_cols, joined, pl, strat_rates):
    _probe = joined.filter(
        pl.col("index_class").is_in(["qualified", "not_sustained"])
    ).sort("index_class")
    d3 = strat_rates(_probe, "index_class", "index_class")
    d3_pub = apply_min_cell(d3, count_cols(d3), "D.3")
    d3_suppressed = set(d3.get_column("index_class").to_list()) - set(
        d3_pub.get_column("index_class").to_list()
    )
    d3_pub.write_csv(SHARE_DIR / "specificity_not_sustained.csv")
    print("D.3 qualified vs not_sustained -- the residual probe")
    print("  An IMV row followed within episode_gap_hours by a different device is a")
    print("  charting blip. Neither should carry an induction.")
    print("  CONFOUNDER: a not_sustained episode adjacent to a real intubation elsewhere")
    print("  in the same block can borrow its medications.")
    print(d3_pub)
    if d3_suppressed:
        print(f"  NOTE: {sorted(d3_suppressed)} withheld entirely under the n>=10 rule.")
        print("  The D summary below reports that as `suppressed`, not as a missing value.")
    return d3_pub, d3_suppressed


@app.cell
def _(COHORT_RUN_ID, SERIES, SHARE_DIR, detected_expr, joined, pl):
    _nim = joined.filter(pl.col("index_class") == "no_induction_med")

    _rows = []
    for _m, _basis, _name in SERIES:
        _interp = _m == "PAIR" and _basis == "free_running"
        _n = int(_nim.select(detected_expr(_m, _basis)).to_series().sum())
        _rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "series": _name,
                "n_stratum": _nim.height,
                "n_detected": _n,
                "rate": round(_n / _nim.height, 4) if _nim.height else None,
                "interpretable": _interp,
                "note": ""
                if _interp
                else "0 by construction (D38) -- this reports the filter, not a result",
            }
        )
    d4 = pl.DataFrame(_rows)

    # The three degenerate rows MUST be zero. If one is not, 02's INDUCTION_CATEGORIES and
    # this method's own MED_CATEGORIES have drifted apart -- and that drift is otherwise
    # SILENT: the cohort simply stops being the cohort the methods measure, and Tier A's
    # denominator is wrong with nothing in any output to show it. This is the one place it
    # is observable, so it is asserted here rather than trusted.
    _nonzero = d4.filter(~pl.col("interpretable") & (pl.col("n_detected") > 0))
    assert _nonzero.height == 0, (
        f"{_nonzero.to_dicts()} fired on the no_induction_med stratum. Those episodes were "
        "rejected by 02 for containing none of the eight induction agents in the window, so "
        "a windowed method cannot detect one there. 02's INDUCTION_CATEGORIES and this "
        "method's MED_CATEGORIES have drifted apart (D38)."
    )

    d4.write_csv(SHARE_DIR / "specificity_pair_free_running.csv")
    print(f"D.4 the no_induction_med stratum, n = {_nim.height:,}")
    print("  PAIR free_running is the only interpretable row: its scan covers the whole")
    print("  block, so it is not constrained by the window filter that built this stratum.")
    print(d4)
    return (d4,)


@app.cell
def _(COHORT_RUN_ID, SERIES, SHARE_DIR, d3_pub, d3_suppressed, d4, pl):
    _d3 = {r["index_class"]: r for r in d3_pub.to_dicts()}
    _d4 = {r["series"]: r for r in d4.to_dicts()}

    _rows = []
    for _m, _basis, _name in SERIES:
        if _name == "PAIR_free_running":
            _contrast = "D.4 no_induction_med"
            _comp = _d4[_name]["rate"]
            _status = "ok" if _comp is not None else "not_available"
        else:
            _contrast = "D.3 not_sustained"
            _comp = _d3.get("not_sustained", {}).get(f"rate_{_name}")
            # A null comparator is NOT the same statement as a withheld one, and a bare
            # null in the headline specificity table reads as "not computed". The rate
            # itself stays unpublished: the stratum size is public in consort_index.csv,
            # so a rate would make the suppressed count recoverable by multiplication --
            # which is the whole reason the row was withheld.
            if _comp is not None:
                _status = "ok"
            elif "not_sustained" in d3_suppressed:
                _status = "suppressed_n_below_10"
            else:
                _status = "not_available"
        _q = _d3.get("qualified", {}).get(f"rate_{_name}")
        _rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "series": _name,
                "contrast": _contrast,
                "rate_qualified": _q,
                "rate_comparator": _comp,
                "comparator_status": _status,
                "gap": round(_q - _comp, 4) if _q is not None and _comp is not None else None,
                # Reported alongside the difference because at low absolute rates the
                # difference collapses toward zero for arithmetic reasons rather than for want
                # of specificity. 0.016 vs 0.004 is a gap of 0.012, which looks like nothing,
                # and a ratio of 4, which is the statement a gap of 0.43 makes at high rates.
                "ratio": round(_q / _comp, 2) if _q is not None and _comp else None,
                "known_answer": False,
            }
        )

    gap = pl.DataFrame(_rows)
    gap.write_csv(SHARE_DIR / "specificity_gap.csv")
    print("D summary")
    print(gap)
    _sup = [r["series"] for r in _rows if r["comparator_status"].startswith("suppressed")]
    if _sup:
        print(
            f"\n  {len(_sup)} of {len(_rows)} contrasts have NO published gap: the "
            "not_sustained row was withheld\n"
            "  entirely under the n>=10 rule because one of its counts fell in the 1-9 "
            "range.\n"
            "  Suppression here is row-level by design -- blanking one cell in a table "
            "whose margins\n"
            "  are published is often recoverable by subtraction. The gap is withheld, "
            "not missing."
        )
    print(
        "\n  A method whose gap approaches zero is not detecting intubation -- it is\n"
        "  detecting being in an ICU. That reading survives D37 intact.\n"
        "  What does NOT survive is the claim that the comparator is false-positive by\n"
        "  construction: `known_answer` is false on every row, and each contrast's\n"
        "  confounder is printed with its own table above."
    )
    return (gap,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier E — pair structure and independent timing

        Computed from `method_PAIR_pairs.parquet`, filtered to `index_class = 'qualified'`
        like Tiers A–C. This is the tier that uses `PAIR`'s distinguishing property: it
        carries its own intubation timestamp, so it can be **scored against t₀** rather than
        merely measured near it.
        """
    )
    return


@app.cell
def _(analytic, pairs, pl):
    pairs_q = pairs.filter(pl.col("index_class") == "qualified")
    # One row per QUALIFIED EPISODE, not per encounter -- `analytic` has been episode-keyed
    # since D35 and the name now says so.
    ep_q = analytic.select(
        "intubation_episode_id", "encounter_block", "n_pairs", "first_is_nearest",
        "first_pair_to_t0_min", "near_pair_to_t0_min",
    )
    # The index pair of each EPISODE -- the basis for E.1's fold statistics, E.2 and E.3.
    #
    # Grouped on intubation_episode_id, NOT encounter_block. Under D35 a block may hold
    # several episodes and D39 assigns every pair to exactly one of them; grouping on the
    # block therefore kept only the earliest episode's pair and silently dropped every
    # later episode's index pair from the basis. Sorting by pair_seq (block scan order,
    # hence chronological) and taking the first per episode reproduces `_index_pair` in
    # 05, so E.2 and E.3 read the same pair that the episode table publishes as `first_`.
    first_pairs_q = (
        pairs_q.sort(["intubation_episode_id", "pair_seq"])
        .group_by("intubation_episode_id", maintain_order=True)
        .first()
    )
    assert first_pairs_q.height == pairs_q.get_column("intubation_episode_id").n_unique()

    print(f"pairs on the index set     : {pairs_q.height:,}")
    print(f"episodes contributing      : "
          f"{pairs_q.get_column('intubation_episode_id').n_unique():,}")
    print(f"  spread over blocks       : {pairs_q.get_column('encounter_block').n_unique():,}")
    print(f"index pairs (1 per episode): {first_pairs_q.height:,}")
    return ep_q, first_pairs_q, pairs_q


@app.cell
def _(
    COHORT_RUN_ID,
    COLLAPSE_GAP_MINUTES,
    SHARE_DIR,
    apply_min_cell,
    ep_q,
    first_pairs_q,
    pl,
):
    # D43. The fold's size is carried into the published table rather than left in a
    # notebook print: a pair is now between two agent EVENTS, and a reader who cannot see
    # how many administration rows an event absorbed cannot tell a single push from an
    # infusion charted every few minutes. A left join, so the n_pairs=0 bucket keeps its
    # row with null fold columns instead of vanishing from the distribution.
    _fold = first_pairs_q.select("intubation_episode_id", "n_sed_admin", "n_para_admin")
    e1 = (
        ep_q.join(_fold, on="intubation_episode_id", how="left")
        .with_columns(
            pairs_bucket=pl.when(pl.col("n_pairs") >= 3)
            .then(pl.lit("3+"))
            .otherwise(pl.col("n_pairs").cast(pl.String))
        )
        .group_by("pairs_bucket")
        .agg(
            n=pl.len(),
            # Over the episode's INDEX pair only -- one number per episode, so a stay that
            # pairs seven times does not outvote six single-pair stays.
            median_n_sed_admin=pl.col("n_sed_admin").median(),
            median_n_para_admin=pl.col("n_para_admin").median(),
            pct_index_pair_folded=(
                100.0 * ((pl.col("n_sed_admin") > 1) | (pl.col("n_para_admin") > 1)).mean()
            ).round(1),
        )
        .sort("pairs_bucket")
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            pct=(100.0 * pl.col("n") / ep_q.height).round(2),
        )
        .select(["cohort_run_id", "pairs_bucket", "n", "pct",
                 "median_n_sed_admin", "median_n_para_admin", "pct_index_pair_folded"])
    )
    e1_pub = apply_min_cell(e1, ["n"], "E.1")
    e1_pub.write_csv(SHARE_DIR / "pair_count_distribution.csv")
    print("E.1 pairs per EPISODE, with how much charting the agent-event fold merged")
    print(e1_pub)
    print(
        "\n  The 3+ row bounds how much of the free_running / in_window gap in A.1 is\n"
        "  reintubation activity rather than a mis-placed t0. Episode labelling is out of\n"
        "  scope, so this reports that the activity exists without claiming what it was.\n"
        f"  The three fold columns are D43's audit trail at collapse_gap_minutes = "
        f"{COLLAPSE_GAP_MINUTES:.0f}:\n"
        "  administrations of the same agent within that gap of each other are one clinical\n"
        "  event, and these say how many rows a typical index pair absorbed. They are null\n"
        "  on the n_pairs = 0 row, which by definition has no index pair."
    )
    return


@app.cell
def _(
    COHORT_RUN_ID,
    COLLAPSE_GAP_MINUTES,
    PAIR_GAP_HOURS,
    SHARE_DIR,
    apply_min_cell,
    first_pairs_q,
    pairs_q,
    pl,
):
    def _summarise(df, label):
        _g = df.get_column("gap_minutes")
        return {
            "cohort_run_id": COHORT_RUN_ID,
            "basis": label,
            "pair_gap_hours": PAIR_GAP_HOURS,
            "n_pairs": df.height,
            "median": _g.median(),
            "q1": _g.quantile(0.25),
            "q3": _g.quantile(0.75),
            "pct_le_5": round(100.0 * (_g <= 5).mean(), 1) if df.height else None,
            "pct_le_30": round(100.0 * (_g <= 30).mean(), 1) if df.height else None,
        }

    e2 = pl.DataFrame([_summarise(pairs_q, "all pairs"),
                       _summarise(first_pairs_q, "index pairs (first, per episode)")])
    e2_pub = apply_min_cell(e2, ["n_pairs"], "E.2")
    e2_pub.write_csv(SHARE_DIR / "pair_gap_distribution.csv")
    print("E.2 gap between the two members of a pair")
    print(e2_pub)
    print(
        "\n  The 5-min and 30-min columns are directly comparable to the sibling\n"
        "  Induction_Variability_RSI study (5 min cohort threshold, 30 min timing analysis).\n"
        f"  THIS IS THE EMPIRICAL TEST OF pair_gap_hours = {PAIR_GAP_HOURS}: if the mass sits\n"
        "  under 30 minutes, a 3-hour threshold is admitting a long tail of coincidental\n"
        "  co-occurrence, and the size of that tail is what this table exposes. Acting on it\n"
        "  means a re-run, not a filter (D29) — but the table tells you whether it is worth it.\n"
        f"  Under D43 the gap is measured between agent EVENTS, not between administration\n"
        f"  rows: 05 first collapses same-agent administrations lying within\n"
        f"  collapse_gap_minutes = {COLLAPSE_GAP_MINUTES:.0f} of each other into one anchored "
        f"event and dates that\n"
        "  event by its FIRST administration. So a gap here is the distance between the two\n"
        "  agents' first charted doses, and repeated charting of one infusion no longer\n"
        "  contributes a cloud of near-zero gaps that made the distribution look tighter\n"
        "  than the clinical behaviour it describes."
    )
    return


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, first_pairs_q, pl):
    e3 = (
        first_pairs_q.group_by(["sed_med_category", "para_med_category"])
        .agg(
            n=pl.len(),
            median_gap=pl.col("gap_minutes").median(),
            median_sed_dose=pl.col("sed_med_dose").median().round(2),
            sed_units=pl.col("sed_med_dose_unit").unique().sort().str.join(" | "),
        )
        .sort("n", descending=True)
        .with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID))
        .select(["cohort_run_id", "sed_med_category", "para_med_category", "n",
                 "median_gap", "median_sed_dose", "sed_units"])
    )
    e3_pub = apply_min_cell(e3, ["n"], "E.3")
    e3_pub.write_csv(SHARE_DIR / "pair_agent_combinations.csv")
    print("E.3 which agents pair with which, over index pairs (one per episode)")
    print(f"  grid before suppression : {e3.height} cells "
          f"({e3.get_column('sed_med_category').n_unique()} sedative labels x "
          f"{e3.get_column('para_med_category').n_unique()} paralytic)")
    print(f"  published               : {e3_pub.height} cells")
    print(e3_pub)
    print(
        "\n  This is the clinical output the method exists to produce, and it is NOT derivable\n"
        "  from SED and PARA run separately — those report their marginals, never the joint.\n"
        "  Rows with long median gaps are the ones most likely to be co-occurrence rather than\n"
        "  a deliberate induction pair, and their share is a direct read on SED's list breadth.\n"
        "  D43.5: a category may now be a COMBINATION — `fentanyl+propofol` is one agent event\n"
        "  whose fold window caught both agents, and it is a distinct row from either alone,\n"
        "  because giving both together is a different induction from giving either. That is\n"
        "  why the grid is wider than the agent lists are long.\n"
        "  D43.6: median_sed_dose is the dose of the label's LEAD agent (the alphabetically\n"
        "  first one named), not a total across a combination, and sed_units is that agent's\n"
        "  unit. On a combined row it therefore describes one component, not the event."
    )
    return (e3_pub,)


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, ep_q, pl):
    _det = ep_q.filter(pl.col("n_pairs") > 0)
    _rows = []
    for _which in ("first", "near"):
        _v = _det.get_column(f"{_which}_pair_to_t0_min")
        _rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "index_pair": _which,
                "n": _det.height,
                "median": _v.median(),
                "q1": _v.quantile(0.25),
                "q3": _v.quantile(0.75),
                "pct_within_30": round(100.0 * (_v.abs() <= 30).mean(), 1) if _det.height else None,
            }
        )
    e4 = pl.DataFrame(_rows)
    e4_pub = apply_min_cell(e4, ["n"], "E.4")
    e4_pub.write_csv(SHARE_DIR / "pair_index_offsets.csv")
    print("E.4 index pair offsets, signed minutes from t0   (unit: episodes)")
    print(e4_pub)
    print(
        f"\n  first_is_nearest : {_det.get_column('first_is_nearest').mean():.4f}  "
        f"(n={_det.height:,})"
    )
    return


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, ep_q, pl):
    _det = ep_q.filter(pl.col("n_pairs") > 0)
    # Computed on first_pair_to_t0_min — the pair chosen WITHOUT reference to t0, so the
    # comparison is not circular. near_pair_to_t0_min is small by construction (D31), and
    # scoring on it would report the selection rule rather than the data.
    _v = _det.get_column("first_pair_to_t0_min")
    e5 = pl.DataFrame(
        [
            {
                "cohort_run_id": COHORT_RUN_ID,
                "tolerance": _label,
                "n_within": int(_n),
                "pct_of_detected": round(100.0 * _n / max(_det.height, 1), 1),
            }
            for _label, _n in [
                ("+/-5 min", (_v.abs() <= 5).sum()),
                ("+/-15 min", (_v.abs() <= 15).sum()),
                ("+/-30 min", (_v.abs() <= 30).sum()),
                ("+/-60 min", (_v.abs() <= 60).sum()),
                ("beyond +/-180 min", (_v.abs() > 180).sum()),
            ]
        ]
    )
    e5_pub = apply_min_cell(e5, ["n_within"], "E.5")
    e5_pub.write_csv(SHARE_DIR / "pair_t0_concordance.csv")
    print(f"E.5 device-vs-medication timing concordance   "
          f"(n detected = {_det.height:,} episodes)")
    print(e5_pub)
    print(
        "\n  Read the `beyond +/-180 min` row against A.1's free_running/in_window gap — they\n"
        "  are two views of the same episodes. Every one is a case where the earliest\n"
        "  sedative-paralytic co-administration of the stay is not near the index IMV. Three\n"
        "  explanations compete and this design cannot separate them: the patient was\n"
        "  intubated where device charting did not follow, t0 landed on a later ventilation\n"
        "  episode, or the pair was coincidental. Sizing the disagreement without adjudicating\n"
        "  it is the correct move."
    )
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        ## Tier F — how much of the medication signal is maintenance sedation?

        The D40 sub-analysis. **This is the only tier that reads `detected_induction_only`.**
        Tiers A–E stay on `detected` (D42), so every number above is comparable against runs
        that predate D40, and the denominator here is the same N\*\* they use.

        D38's eligibility filter is deliberately *not* refined. If an episode qualified only
        when a non-prep induction agent were charted, every surviving episode would have one
        by definition and `SED`'s refined rate would snap straight back to 1.000 — the same
        circularity D38 already records, reintroduced one layer down. Leaving the filter
        alone is what makes this measurement readable at all.
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, RANKED_METHODS, SHARE_DIR, analytic, apply_min_cell, pl):
    _rows = []
    for _m in RANKED_METHODS:
        _d = pl.col(f"{_m.lower()}_detected")
        _i = pl.col(f"{_m.lower()}_detected_induction_only")
        _n = analytic.height
        _nd = analytic.filter(_d).height
        _ni = analytic.filter(_i).height
        _rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "method_id": _m,
                "n": _n,
                "n_detected": _nd,
                "rate": round(_nd / _n, 4),
                "n_detected_induction_only": _ni,
                "rate_induction_only": round(_ni / _n, 4),
                "rate_gap": round((_nd - _ni) / _n, 4),
                "n_flipped": _nd - _ni,
            }
        )
    f1 = pl.DataFrame(_rows)

    # `n` is identical across both columns by construction (D42 holds the denominator
    # fixed), so the gap is a pure reclassification effect and never a cohort effect. If
    # this ever fails, D40 has leaked into the eligibility filter.
    assert f1.get_column("n").n_unique() == 1, (
        "the two variants are being computed on different denominators; D42 is violated"
    )
    f1_pub = apply_min_cell(
        f1, ["n_detected", "n_detected_induction_only", "n_flipped"], "F.1"
    )
    f1_pub.write_csv(SHARE_DIR / "induction_only_comparison.csv")
    print("F.1  detection with and without D40")
    print(f1_pub)
    return


@app.cell
def _(COHORT_RUN_ID, PHI_DIR, RANKED_METHODS, SHARE_DIR, apply_min_cell, pl):
    _sw, _bd = [], []
    for _m in RANKED_METHODS:
        _sw.append(
            pl.read_parquet(PHI_DIR / f"method_{_m}_prep_sweep.parquet")
            .filter(pl.col("index_class") == "qualified")
            .with_columns(method_id=pl.lit(_m))
        )
        _bd.append(
            pl.read_parquet(PHI_DIR / f"method_{_m}_prep_by_drug.parquet")
            .filter(pl.col("index_class") == "qualified")
            .with_columns(method_id=pl.lit(_m))
        )

    f2 = (
        pl.concat(_sw)
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            rate=(pl.col("n_detected") / pl.col("n_episodes")).round(4),
            rate_all=(pl.col("n_detected_all") / pl.col("n_episodes")).round(4),
        )
        .select(
            "cohort_run_id", "method_id", "threshold_minutes", "n_episodes",
            "n_detected_all", "rate_all", "n_detected", "rate", "n_flipped",
            "n_doses_reclassified",
        )
        .sort(["method_id", "threshold_minutes"])
    )
    f3 = (
        pl.concat(_bd)
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            share=(pl.col("n_doses_reclassified") / pl.col("n_doses_after")).round(4),
        )
        .select(
            "cohort_run_id", "method_id", "med_category", "threshold_minutes",
            "n_doses_after", "n_doses_reclassified", "share",
        )
        .sort(["method_id", "med_category", "threshold_minutes"])
    )

    f2_pub = apply_min_cell(f2, ["n_detected", "n_flipped", "n_doses_reclassified"], "F.2")
    f3_pub = apply_min_cell(f3, ["n_doses_after", "n_doses_reclassified"], "F.3")
    f2_pub.write_csv(SHARE_DIR / "infusion_prep_sweep.csv")
    f3_pub.write_csv(SHARE_DIR / "infusion_prep_by_drug.csv")

    print("F.2  threshold sweep")
    print(f2_pub)
    print(
        "\nF.3  by medication -- fentanyl infusions are analgesia and propofol infusions are\n"
        "     sedation, so the two have no reason to share a bolus-to-drip lag. A pooled\n"
        "     number would be an average of two different clinical behaviours."
    )
    print(f3_pub.filter(pl.col("threshold_minutes") == 60))
    return (f2_pub,)


@app.cell
def _(
    COHORT_RUN_ID,
    RANKED_METHODS,
    SHARE_DIR,
    analytic,
    apply_min_cell,
    index_strata,
    pl,
):
    # F.4. This table exists to EXPOSE a confound in D40, not to confirm it. The only thing
    # separating "induction bolus then maintenance drip" from "maintenance loading dose then
    # drip" is which side of t0 the bolus falls on -- and under D34 t0 is the waterfalled
    # IMV row, which arrives LATE under exactly the high-stress conditions that produce an
    # intubation. If the prep rate climbs with charting_delay_min, D40 is partly deleting
    # the signal it was built to protect. Reported whichever way it comes out; the primary
    # rates do not depend on D40 at all (D42), which is what makes that safe.
    _strata = (
        pl.when(pl.col("charting_delay_min").is_null()).then(pl.lit("not_charted"))
        .when(pl.col("charting_delay_min") == 0).then(pl.lit("0"))
        .when(pl.col("charting_delay_min") <= 30).then(pl.lit("1-30"))
        .when(pl.col("charting_delay_min") <= 60).then(pl.lit("31-60"))
        .when(pl.col("charting_delay_min") <= 180).then(pl.lit("61-180"))
        .otherwise(pl.lit(">180"))
        .alias("delay_stratum")
    )
    _ORDER = ["0", "1-30", "31-60", "61-180", ">180", "not_charted"]

    _base = analytic.join(index_strata, on="intubation_episode_id", how="left").with_columns(
        _strata
    )
    _rows = []
    for _m in RANKED_METHODS:
        _rows.append(
            _base.group_by("delay_stratum")
            .agg(
                n_episodes=pl.len(),
                n_with_prep=(pl.col(f"{_m.lower()}_n_after_prep") > 0).sum(),
                n_flipped=(
                    pl.col(f"{_m.lower()}_detected")
                    & ~pl.col(f"{_m.lower()}_detected_induction_only")
                ).sum(),
            )
            .with_columns(method_id=pl.lit(_m), cohort_run_id=pl.lit(COHORT_RUN_ID))
        )
    f4 = (
        pl.concat(_rows)
        .with_columns(
            prep_rate=(pl.col("n_with_prep") / pl.col("n_episodes")).round(4),
            _ord=pl.col("delay_stratum").replace_strict(
                {_s: _i for _i, _s in enumerate(_ORDER)}, default=99, return_dtype=pl.Int32
            ),
        )
        .sort(["method_id", "_ord"])
        .drop("_ord")
        .select(
            "cohort_run_id", "method_id", "delay_stratum", "n_episodes",
            "n_with_prep", "prep_rate", "n_flipped",
        )
    )
    f4_pub = apply_min_cell(f4, ["n_episodes", "n_with_prep", "n_flipped"], "F.4")
    f4_pub.write_csv(SHARE_DIR / "prep_by_charting_delay.csv")
    print("F.4  prep rate by charting-delay stratum")
    print(f4_pub)
    print(
        "\n  A rate that RISES with the delay stratum means D40 is reclassifying induction\n"
        "  agents that were charted before a late vent row. A flat rate means the two are\n"
        "  independent and D40 is measuring what it claims."
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Figures

        Every figure is drawn from a published table, so the n ≥ 10 rule applies to the
        pictures exactly as it does to the CSVs (D26) — a suppressed row is absent from the
        plot too, and where a histogram bin falls in the disclosive range the bin is dropped
        and the dropped mass is stated in the caption rather than folded into a neighbour.
        """
    )
    return


@app.cell
def _(SHARE_DIR, plt, textwrap):
    FIG_BG = "white"
    COLORS = {"SED": "#2c6fbb", "PARA": "#d1495b", "PAIR": "#4a9d5f"}
    GREY = "#555555"

    def finish(fig, path, caption=None):
        if caption:
            # Wrapped rather than left as one long line: an unwrapped caption runs under the
            # x-axis label and the two collide, which is worse than a two-line caption.
            _w = max(int(fig.get_size_inches()[0] * 20), 80)
            fig.text(
                0.01, 0.005, "\n".join(textwrap.wrap(caption, _w)),
                ha="left", va="top", fontsize=7.5, color=GREY,
                transform=fig.transFigure,
            )
        fig.savefig(SHARE_DIR / path, dpi=160, bbox_inches="tight", facecolor=FIG_BG)
        plt.close(fig)
        print(f"  wrote {path}")

    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.6,
            "figure.facecolor": FIG_BG,
            "axes.facecolor": FIG_BG,
        }
    )
    return COLORS, GREY, finish


@app.cell
def _(COLORS, GREY, NullFormatter, SHARE_DIR, SITE, finish, pl, plt):
    # F1 -- the two CONSORTs side by side, drawn from the published CSVs rather than
    # recomputed, so the figure cannot disagree with the tables.
    _a = pl.read_csv(SHARE_DIR / "consort_cohort.csv")
    _b = pl.read_csv(SHARE_DIR / "consort_index.csv")

    _fig, _axes = plt.subplots(1, 2, figsize=(13, 5.5))
    # The two CONSORTs count DIFFERENT units and the column names say so: A is per
    # encounter block, B is per episode (D35). Reading both through one hardcoded column
    # name is what broke when the unit changed, so the unit is looked up per panel.
    for _ax, _df, _title, _color, _unit in (
        (_axes[0], _a, "CONSORT A — cohort (blocks)", GREY, "n_encounters"),
        (_axes[1], _b, "CONSORT B — index (episodes)", COLORS["SED"], "n_episodes"),
    ):
        assert _unit in _df.columns, (
            f"{_title} has no {_unit} column; it has {_df.columns}. The CONSORT unit "
            "changed without this figure being told."
        )
        _steps = _df.get_column("step").to_list()
        _n = [
            v if v is not None else _df.get_column("n_patients").to_list()[i]
            for i, v in enumerate(_df.get_column(_unit).to_list())
        ]
        _y = list(range(len(_steps)))[::-1]
        _ax.barh(_y, _n, color=_color, alpha=0.85, height=0.62)
        _ax.set_yticks(_y)
        _ax.set_yticklabels([s if len(s) < 44 else s[:41] + "..." for s in _steps], fontsize=8)
        # Log scale: CONSORT A spans 223,452 down to 34,017 and a linear axis collapses the
        # last five steps into one stub. Minor tick labels are silenced -- matplotlib writes
        # 3x10^4, 4x10^4, 6x10^4 between decades and they collide before they inform.
        _ax.set_xscale("log")
        _ax.xaxis.set_minor_formatter(NullFormatter())
        _ax.set_xlabel("n (log scale)")
        _ax.set_title(_title, loc="left", fontweight="bold")
        for _yy, _nn, _ee in zip(_y, _n, _df.get_column("n_excluded").to_list()):
            _ax.text(_nn * 1.12, _yy, f"{_nn:,}" + (f"   (−{_ee:,})" if _ee else ""),
                     va="center", fontsize=8, color="#222222")
        _ax.set_xlim(right=max(_n) * 3.2)

    _fig.suptitle(f"VentTRACE cohort and index flow — {SITE}", x=0.01, ha="left",
                  fontweight="bold")
    _fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    finish(
        _fig,
        "consort_flow.png",
        "Left panel counts encounter blocks, right panel counts intubation episodes — a "
        "block may contribute several (D35), so the two axes are not the same unit. "
        "Bars are cumulative survivors at each step; parenthesised figures are the exclusion "
        "at that step. Panel A counts patients until stitching defines an encounter.",
    )
    return


@app.cell
def _(COLORS, SITE, finish, joined, pl, plt):
    # F2 -- the index strata: the headline of 02 and the denominator map for everything
    # downstream. Only the highlighted bar feeds Tiers A-C and E.
    _cnt = (
        joined.group_by("index_class")
        .agg(n=pl.len())
        .sort("n", descending=True)
        .with_columns(pct=100.0 * pl.col("n") / joined.height)
    )
    _labels = _cnt.get_column("index_class").to_list()
    _vals = _cnt.get_column("n").to_list()

    _fig, _ax = plt.subplots(figsize=(9, 4.4))
    _bars = _ax.bar(
        _labels, _vals,
        color=[COLORS["SED"] if lab == "qualified" else "#b9c4d2" for lab in _labels],
        width=0.62,
    )
    for _b, _v, _p in zip(_bars, _vals, _cnt.get_column("pct").to_list()):
        _ax.text(_b.get_x() + _b.get_width() / 2, _v, f"{_v:,}\n{_p:.1f}%",
                 ha="center", va="bottom", fontsize=8.5)
    _ax.set_ylabel("encounters")
    _ax.set_ylim(top=max(_vals) * 1.22)
    _ax.set_title(f"Index classes across the cohort — {SITE}   (N* = {joined.height:,})",
                  loc="left", fontweight="bold")
    _ax.set_xticks(range(len(_labels)))
    _ax.set_xticklabels(_labels, rotation=16, ha="right", fontsize=9)
    _fig.subplots_adjust(bottom=0.30)
    finish(
        _fig,
        "index_class_strata.png",
        "Only `qualified` (highlighted) feeds Tiers A-C and E. `not_sustained` is the "
        "residual Tier D probe; `no_induction_med` is method-negative by construction for "
        "the two windowed methods (D38) and informative only for PAIR free-running.",
    )
    return


@app.cell
def _(COLORS, MIN_CELL, RANKED_METHODS, SITE, WINDOW_HOURS, finish, pl, plt, ranked_long):
    # F3 -- B.4. Normalised per method: SED and PARA differ by more than an order of
    # magnitude in entry volume, and on a shared count axis the smaller one is a flat line
    # against the axis -- which reads as "no timing signal" when what it has is a smaller
    # denominator. Shape is the question; the counts are published in B.1 and B.2.
    _lim, _bin = 180, 10
    _edges = list(range(-_lim, _lim + _bin, _bin))

    _fig, _ax = plt.subplots(figsize=(11, 4.8))
    _suppressed = 0
    for _m in RANKED_METHODS:
        _v = (
            ranked_long.filter(
                (pl.col("method_id") == _m) & (pl.col("delta_minutes").abs() <= _lim)
            ).get_column("delta_minutes").to_list()
        )
        _counts = [0] * (len(_edges) - 1)
        for _x in _v:
            _counts[min(int((_x + _lim) // _bin), len(_counts) - 1)] += 1
        _suppressed += sum(_c for _c in _counts if 0 < _c < MIN_CELL)
        _counts = [0 if 0 < _c < MIN_CELL else _c for _c in _counts]
        _pct = [100.0 * _c / max(len(_v), 1) for _c in _counts]
        _centers = [(_edges[i] + _edges[i + 1]) / 2 for i in range(len(_pct))]
        _ax.step(_centers, _pct, where="mid", color=COLORS[_m], linewidth=1.7,
                 label=f"{_m}  (n={len(_v):,} entries)")
        _ax.fill_between(_centers, _pct, step="mid", color=COLORS[_m], alpha=0.16)

    _ax.axvline(0, color="#111111", linewidth=1.2)
    _ax.text(0, _ax.get_ylim()[1] * 0.97, "  t0", va="top", fontsize=9, fontweight="bold")
    _ax.set_xlabel(f"minutes relative to t0   (detection window is ±{WINDOW_HOURS} h)")
    _ax.set_ylabel("% of that method's ranked entries")
    _ax.set_xlim(-_lim, _lim)
    _ax.set_xticks(range(-_lim, _lim + 1, 30))
    _ax.legend(frameon=False)
    _ax.set_title(f"B.4  medication timing around t0 — {SITE}", loc="left", fontweight="bold")
    finish(
        _fig,
        "timing_offset_distribution.png",
        f"{_bin}-minute bins, each series normalised to its own total so the shapes are "
        f"comparable. Bins holding 1..{MIN_CELL - 1} entries are dropped ({_suppressed} "
        "entries). PAIR is absent by design — it has no rank ladder (D30); its timing is "
        "Tier E.",
    )
    return


@app.cell
def _(COLORS, MIN_CELL, RANKED_METHODS, SITE, finish, pl, plt, ranked_long):
    # F8 -- B.5. A NEW figure beside B.4 rather than a replacement for it, so B.4 stays
    # byte-comparable against runs that predate D40.
    #
    # The three bands are mutually exclusive and `during_infusion` takes precedence, because
    # "a drip was already running" is the stronger and less inferential statement. Reading
    # the figure, follow the induction band across t0: it should peak in the last half-hour
    # before zero and fall away immediately after.
    _lim, _bin = 180, 10
    _edges = list(range(-_lim, _lim + _bin, _bin))
    _centers = [(_edges[_i] + _edges[_i + 1]) / 2 for _i in range(len(_edges) - 1)]
    _BANDS = [
        ("induction", "#2c6fbb", "induction agent"),
        ("prep", "#e8a33d", "infusion prep — bolus, then same-drug drip (D40)"),
        ("during", "#b03b4e", "given during a running same-drug infusion (D41)"),
    ]

    _lab = (
        pl.when(pl.col("during_infusion")).then(pl.lit("during"))
        .when(pl.col("infusion_prep")).then(pl.lit("prep"))
        .otherwise(pl.lit("induction"))
        .alias("band")
    )
    _src = ranked_long.filter(pl.col("delta_minutes").abs() <= _lim).with_columns(_lab)

    _fig, _axes = plt.subplots(len(RANKED_METHODS), 1, figsize=(11, 7.6), sharex=True)
    _suppressed = 0
    for _ax, _m in zip(_axes, RANKED_METHODS):
        _sub = _src.filter(pl.col("method_id") == _m)
        _tot = _sub.height
        _stack = [0.0] * len(_centers)
        for _key, _colour, _legend in _BANDS:
            _v = _sub.filter(pl.col("band") == _key).get_column("delta_minutes").to_list()
            _counts = [0] * len(_centers)
            for _x in _v:
                _counts[min(int((_x + _lim) // _bin), len(_counts) - 1)] += 1
            _suppressed += sum(_c for _c in _counts if 0 < _c < MIN_CELL)
            _counts = [0 if 0 < _c < MIN_CELL else _c for _c in _counts]
            _pct = [100.0 * _c / max(_tot, 1) for _c in _counts]
            _top = [_stack[_i] + _pct[_i] for _i in range(len(_pct))]
            _ax.fill_between(_centers, _stack, _top, step="mid", color=_colour,
                             alpha=0.88, linewidth=0, label=_legend)
            _stack = _top
        _ax.step(_centers, _stack, where="mid", color="#222222", linewidth=1.0)
        _ax.axvline(0, color="#111111", linewidth=1.2)
        _ax.set_ylabel(f"% of {_m} entries")
        _ax.set_title(f"{_m}  (n={_tot:,} ranked entries)", loc="left",
                      fontsize=9.5, fontweight="bold", color=COLORS[_m])
        _ax.set_xlim(-_lim, _lim)

    _axes[0].legend(frameon=False, fontsize=8.5, loc="upper right")
    _axes[-1].set_xlabel("minutes relative to t0")
    _axes[-1].set_xticks(range(-_lim, _lim + 1, 30))
    # suptitle, not set_title on axes[0] -- that would overwrite the per-method label the
    # loop just set and leave the top panel unidentified.
    _fig.suptitle(
        f"B.5  medication timing around t0, decomposed — {SITE}",
        x=0.085, ha="left", fontweight="bold", fontsize=11,
    )
    _fig.tight_layout(rect=[0, 0, 1, 0.97])
    finish(
        _fig,
        "timing_offset_decomposed.png",
        f"{_bin}-minute bins, each method normalised to its own total. Bands are mutually "
        "exclusive and `during_infusion` wins a tie. `infusion_prep` is zero before t0 by "
        f"construction — D40 exempts that half. Bins holding 1..{MIN_CELL - 1} entries are "
        f"dropped ({_suppressed} entries).",
    )
    return


@app.cell
def _(SHARE_DIR, COLORS, INFUSION_PREP_MINUTES, SITE, f2_pub, finish, pl, plt):
    # F9 -- F.2, drawn off the published table so suppression is inherited (D26).
    _fig, _ax = plt.subplots(figsize=(9, 4.4))
    for _m in f2_pub.get_column("method_id").unique(maintain_order=True).to_list():
        _s = f2_pub.filter(pl.col("method_id") == _m).sort("threshold_minutes")
        _base = _s.get_column("rate_all").to_list()[0]
        # Each method is drawn as a FRACTION of its own unrefined rate. On a shared absolute
        # axis PARA (0.043) is a flat line against the floor next to SED (0.977), which
        # reads as "no effect" when what it has is a smaller denominator -- the same reason
        # B.4 is normalised per method.
        _ax.plot(
            _s.get_column("threshold_minutes").to_list(),
            [100.0 * _r / _base for _r in _s.get_column("rate").to_list()],
            marker="o", markersize=4, linewidth=1.7, color=COLORS[_m],
            label=f"{_m}  (unrefined rate {_base:.4f} = 100%)",
        )
    _ax.axvline(INFUSION_PREP_MINUTES, color="#111111", linewidth=1.0, linestyle="--")
    _ax.text(INFUSION_PREP_MINUTES + 2, _ax.get_ylim()[0] + 0.4,
             f"configured\n{INFUSION_PREP_MINUTES} min", fontsize=8, va="bottom")
    _ax.set_xlabel("infusion_prep_minutes — how long after a dose the same-drug drip may start")
    _ax.set_ylabel("detection retained, % of unrefined")
    _ax.set_xticks(f2_pub.get_column("threshold_minutes").unique().sort().to_list())
    _ax.legend(frameon=False, fontsize=8.5)
    _ax.grid(alpha=0.25)
    _ax.set_title(f"F.2  infusion-prep threshold sweep — {SITE}", loc="left",
                  fontweight="bold")
    finish(
        _fig,
        "infusion_prep_sweep.png",
        "A curve that has gone flat has stopped finding prep and started finding "
        "coincidence. The configured value is one point on the grid and carries no special "
        "status in the underlying table.",
    )
    return


@app.cell
def _(COLORS, SHARE_DIR, SITE, finish, pl, plt):
    # F4 -- B.3, read off the published table so suppression is inherited automatically.
    _b3 = pl.read_csv(SHARE_DIR / "timing_by_medication.csv")

    _fig, _axes = plt.subplots(1, 2, figsize=(12, 4.4))
    for _ax, _dir in zip(_axes, ("before", "after")):
        _d = _b3.filter(pl.col("direction") == _dir).sort("n")
        if _d.height == 0:
            _ax.text(0.5, 0.5, "nothing published at n >= 10", ha="center",
                     transform=_ax.transAxes)
            _ax.set_title(_dir, loc="left", fontweight="bold")
            continue
        _y = list(range(_d.height))
        _ax.barh(_y, _d.get_column("median_min").to_list(),
                 color=[COLORS[m] for m in _d.get_column("method_id").to_list()], height=0.6)
        _ax.set_yticks(_y)
        _ax.set_yticklabels([f"{r['med_category']}  (n={r['n']:,})" for r in _d.to_dicts()],
                            fontsize=8.5)
        _ax.axvline(0, color="#111111", linewidth=1.0)
        _ax.set_xlabel("median minutes from t0")
        _ax.set_title(_dir, loc="left", fontweight="bold")

    _fig.suptitle(f"B.3  median offset by medication — {SITE}", x=0.01, ha="left",
                  fontweight="bold")
    _fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    finish(
        _fig,
        "timing_by_medication.png",
        "Blue = SED, red = PARA. Bar length is the median lag, not a dose. Agents with fewer "
        "than 10 entries are absent, not zero.",
    )
    return


@app.cell
def _(COLORS, N_INDEX, SHARE_DIR, SITE, a2, a3, finish, pl, plt):
    # F5 -- Tier A in one frame, on the in_window basis: the matched-denominator reading is
    # the one to quote head to head (D33).
    _BASIS = "in_window"
    _a1 = pl.read_csv(SHARE_DIR / "agreement_detection_rates.csv").filter(
        pl.col("pair_basis").is_in(["—", _BASIS])
    )
    _fig, _axes = plt.subplots(1, 3, figsize=(13.5, 4.2))

    _ax = _axes[0]
    _m = _a1.get_column("method_id").to_list()
    _r = _a1.get_column("rate").to_list()
    _bars = _ax.bar(_m, _r, color=[COLORS[x] for x in _m], width=0.5)
    for _b, _v, _n in zip(_bars, _r, _a1.get_column("n_detected").to_list()):
        _ax.text(_b.get_x() + _b.get_width() / 2, _v, f"{_v:.3f}\nn={_n:,}",
                 ha="center", va="bottom", fontsize=8.5)
    _ax.set_ylim(0, max(_r) * 1.45 if _r else 1)
    _ax.set_ylabel("detection rate")
    _ax.set_title(f"A.1  marginals   (N** = {N_INDEX:,})", loc="left", fontweight="bold")

    _ax = _axes[1]
    _row = [r for r in a2.to_dicts() if r["method_a"] == "SED" and r["method_b"] == "PARA"][0]
    _grid = [[_row["both"], _row["only_a"]], [_row["only_b"], _row["neither"]]]
    _ax.imshow(_grid, cmap="Blues")
    for _i in range(2):
        for _j in range(2):
            _v = _grid[_i][_j]
            _ax.text(_j, _i, f"{_v:,}", ha="center", va="center", fontsize=12,
                     color="white" if _v > max(map(max, _grid)) * 0.55 else "#111111")
    _ax.set_xticks([0, 1], ["PARA +", "PARA −"])
    _ax.set_yticks([0, 1], ["SED +", "SED −"])
    _ax.grid(False)
    _ax.set_title(f"A.2  SED×PARA   J={_row['jaccard']:.2f}  κ={_row['cohen_kappa']:.2f}",
                  loc="left", fontweight="bold")

    _ax = _axes[2]
    _c = a3.filter(pl.col("pair_basis") == _BASIS).sort("n_methods")
    _pcts = _c.get_column("pct").to_list()
    _ax.bar([str(x) for x in _c.get_column("n_methods").to_list()], _pcts,
            color=["#b9c4d2", "#9db0c6", "#6f8bab", COLORS["PAIR"]][: _c.height], width=0.55)
    for _x, (_p, _n) in enumerate(zip(_pcts, _c.get_column("n").to_list())):
        _ax.text(_x, _p, f"{_p:.1f}%\nn={_n:,}", ha="center", va="bottom", fontsize=8.5)
    _ax.set_xlabel("methods firing")
    _ax.set_ylabel("% of index set")
    _ax.set_ylim(0, max(_pcts) * 1.35)
    _ax.set_title("A.3  concordance", loc="left", fontweight="bold")

    _fig.suptitle(f"Tier A — method agreement — {SITE}   (basis: {_BASIS})", x=0.01,
                  ha="left", fontweight="bold")
    _fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    finish(
        _fig,
        "agreement_overview.png",
        "Matched-denominator basis: PAIR is restricted to pairs inside the ±3 h window so all "
        "three methods are measured over the same span. The `0 methods firing` bar counts "
        "documented, sustained intubations where no medication signal appeared.",
    )
    return


@app.cell
def _(COLORS, SITE, finish, gap, plt):
    # F6 -- Tier D. The one figure where a small bar is the good result.
    #
    # Drawn from the SUMMARY table rather than from a stratum table, because after the D37
    # rewrite the four series no longer share one comparator: SED, PARA and PAIR-in-window
    # are contrasted against not_sustained (D.3) and PAIR-free-running against
    # no_induction_med (D.4). Each bar pair carries its own contrast in the tick label.
    _rows = [r for r in gap.to_dicts() if r["rate_qualified"] is not None]
    _color = {"SED": COLORS["SED"], "PARA": COLORS["PARA"],
              "PAIR_free_running": "#9ed4ab", "PAIR_in_window": COLORS["PAIR"]}

    _fig, _ax = plt.subplots(figsize=(11, 5.0))
    _w = 0.38
    _x = list(range(len(_rows)))
    _ax.bar(
        [i - _w / 2 for i in _x], [r["rate_qualified"] for r in _rows], _w,
        color=[_color.get(r["series"], "#999999") for r in _rows], label="qualified",
    )
    # A withheld comparator is drawn as NO bar, never as a zero-height one: a 0.0 bar is a
    # claim that the rate is zero, which is a different and much stronger statement than
    # "this was suppressed under the n>=10 rule".
    _have = [(i, r) for i, r in enumerate(_rows) if r["rate_comparator"] is not None]
    if _have:
        _ax.bar(
            [i + _w / 2 for i, _ in _have], [r["rate_comparator"] for _, r in _have], _w,
            color=[_color.get(r["series"], "#999999") for _, r in _have], alpha=0.45,
            hatch="//", label="comparator",
        )
    for _i, _r in enumerate(_rows):
        _ax.text(_i - _w / 2, _r["rate_qualified"], f"{_r['rate_qualified']:.3f}",
                 ha="center", va="bottom", fontsize=7, rotation=90)
        if _r["rate_comparator"] is not None:
            _ax.text(_i + _w / 2, _r["rate_comparator"], f"{_r['rate_comparator']:.3f}",
                     ha="center", va="bottom", fontsize=7, rotation=90)
        else:
            _ax.text(_i + _w / 2, 0, " withheld\n n<10", ha="center", va="bottom",
                     fontsize=6.5, color="#888888", rotation=90)

    _ax.set_xticks(_x)
    _ax.set_xticklabels([f"{r['series']}\n{r['contrast']}" for r in _rows], fontsize=8.5)
    _n_sup = sum(1 for r in _rows if r["rate_comparator"] is None)
    _ax.set_ylabel("detection rate")
    _ax.set_ylim(top=_ax.get_ylim()[1] * 1.20)
    _ax.legend(frameon=False, fontsize=8)

    # Ratio alongside the difference: at PAIR's absolute rates a gap of 0.012 and a gap of
    # 0.000 look alike on the axis, and they are not alike.
    _gaps = "   ".join(
        f"{r['series']} {r['gap']:.3f} ({r['ratio']}x)"
        for r in _rows if r["gap"] is not None
    )
    _ax.set_title(f"Tier D — specificity — {SITE}\n{_gaps}", loc="left",
                  fontweight="bold", fontsize=10)
    _fig.subplots_adjust(bottom=0.28)
    finish(
        _fig,
        "specificity_gap.png",
        "Detection rate in the index set against each method's comparator stratum. A gap "
        "near zero means the method is detecting ICU residence, not intubation. NO bar "
        "here is a false-positive count by construction: D37 admitted arrived_intubated to "
        "the primary analysis, and it was the only stratum whose answer was known. Each "
        "contrast's confounder is named in Tier D."
        + (
            f" {_n_sup} comparator bar(s) are absent because the stratum was withheld "
            "entirely under the n>=10 rule -- absent, not zero."
            if _n_sup
            else ""
        ),
    )
    return


@app.cell
def _(COLORS, MIN_CELL, SITE, ep_q, finish, pl, plt):
    # F7 -- E.6. Out-of-range mass is STATED, never clipped into the edge bins: those
    # episodes are the `beyond +/-180` row of E.5, and a clipped bin reads as "just outside
    # the window" when they are the study's most interesting cases.
    _det = ep_q.filter(pl.col("n_pairs") > 0)
    _lim, _bin = 180, 10
    _v = _det.get_column("first_pair_to_t0_min").to_list()
    _out = sum(1 for _x in _v if abs(_x) > _lim)

    _edges = list(range(-_lim, _lim + _bin, _bin))
    _counts = [0] * (len(_edges) - 1)
    for _x in _v:
        if abs(_x) <= _lim:
            _counts[min(int((_x + _lim) // _bin), len(_counts) - 1)] += 1
    _sup = sum(_c for _c in _counts if 0 < _c < MIN_CELL)
    _counts = [0 if 0 < _c < MIN_CELL else _c for _c in _counts]

    _fig, _ax = plt.subplots(figsize=(11, 4.6))
    _ax.bar([(_edges[i] + _edges[i + 1]) / 2 for i in range(len(_counts))], _counts,
            width=_bin * 0.92, color=COLORS["PAIR"])
    _ax.axvline(0, color="#111111", linewidth=1.2)
    _ax.text(0, _ax.get_ylim()[1] * 0.97, "  t0", va="top", fontsize=9, fontweight="bold")
    _ax.set_xlabel("first_pair_to_t0_min — minutes from t0 to the FIRST pair of the episode")
    _ax.set_ylabel("episodes")
    _ax.set_xlim(-_lim, _lim)
    _ax.set_xticks(range(-_lim, _lim + 1, 30))
    _ax.set_title(
        f"E.6  independent pair timing vs the device anchor — {SITE}   "
        f"(n detected = {_det.height:,})",
        loc="left", fontweight="bold", fontsize=10,
    )
    finish(
        _fig,
        "pair_offset_distribution.png",
        f"{_bin}-minute bins; bins holding 1..{MIN_CELL - 1} episodes are dropped ({_sup}). "
        f"{_out:,} episodes fall beyond ±{_lim} min and are NOT shown — they are the E.5 "
        "`beyond ±180` row, and clipping them into the edge bins would disguise them as near "
        "misses. The first pair is chosen without reference to t0, so this is a genuine test "
        "of the device anchor.",
    )
    return


@app.cell
def _(SITE, e3_pub, finish, plt):
    # F8 -- E.3 as a heatmap, from the published (already suppressed) table.
    _seds = sorted(set(e3_pub.get_column("sed_med_category").to_list()))
    _paras = sorted(set(e3_pub.get_column("para_med_category").to_list()))
    _lookup = {(r["sed_med_category"], r["para_med_category"]): r for r in e3_pub.to_dicts()}
    _grid = [[_lookup.get((_s, _p), {}).get("n", 0) for _p in _paras] for _s in _seds]

    # D43.5 widened this from a 3x2 grid of single agents to a dozen-plus rows of possibly
    # COMBINED sedative labels (`fentanyl+propofol`), which are both more numerous and much
    # longer than the old ones. Height scales with the row count so the cells stay square-ish
    # instead of turning into slivers, and the extra width is for the y labels, which are now
    # long enough to be clipped by bbox_inches="tight" at the old size.
    _fig, _ax = plt.subplots(
        figsize=(2.6 * max(len(_paras), 2) + 4.5, 0.62 * max(len(_seds), 3) + 3.0)
    )
    _im = _ax.imshow(_grid, cmap="Greens", aspect="auto")
    _peak = max(max(_r) for _r in _grid) if _grid else 1
    for _i, _s in enumerate(_seds):
        for _j, _p in enumerate(_paras):
            _r = _lookup.get((_s, _p))
            _ax.text(
                _j, _i,
                f"{_r['n']:,}\n{_r['median_gap']:.0f} min" if _r else "—",
                ha="center", va="center", fontsize=9,
                color="white" if _r and _r["n"] > _peak * 0.55 else "#111111",
            )
    _ax.set_xticks(range(len(_paras)), _paras, fontsize=9)
    _ax.set_yticks(range(len(_seds)), _seds, fontsize=8.5)
    _ax.grid(False)
    _ax.set_xlabel("paralytic")
    _ax.set_ylabel("sedative")
    _fig.colorbar(_im, ax=_ax, shrink=0.8, label="index pairs")
    _ax.set_title(f"E.3  which agents pair with which — {SITE}", loc="left",
                  fontweight="bold", fontsize=10)
    finish(
        _fig,
        "pair_agent_combinations.png",
        "Cell shows the number of index pairs (one per episode) and the median gap between "
        "the two members. Combinations with fewer than 10 pairs are absent, not zero. This "
        "joint distribution is not derivable from SED and PARA run separately. A row label "
        "joined by `+` is a single agent event whose 15-minute fold caught more than one "
        "agent (D43.5) — it is a distinct induction, not a double-count of its components.",
    )
    return


@app.cell
def _(SHARE_DIR, finish, pl, plt):
    # F9 -- CONSORT B as a funnel. Drawn from the published CSV, never from the PHI frames
    # (D26): a figure recomputed from the source could disagree with the table beside it and
    # the reader has no way to tell which is right.
    _c = pl.read_csv(SHARE_DIR / "consort_index.csv")
    _fig, _ax = plt.subplots(figsize=(9.5, 4.6))
    _steps = _c.get_column("step").to_list()
    _eps = _c.get_column("n_episodes").to_list()
    _y = list(range(len(_steps)))
    _ax.barh(_y, _eps, color="#4C72B0")
    _ax.set_yticks(_y)
    _ax.set_yticklabels(_steps, fontsize=9)
    _ax.invert_yaxis()
    _ax.set_xlabel("episodes")
    for _i, (_e, _b, _p) in enumerate(
        zip(_eps, _c.get_column("n_blocks"), _c.get_column("n_patients"))
    ):
        _ax.text(_e, _i, f"  {_e:,} ep / {_b:,} blk / {_p:,} pt", va="center", fontsize=8)
    _ax.set_xlim(0, max(_eps) * 1.55)
    finish(
        _fig,
        "episode_funnel.png",
        "CONSORT B. Three units on every step: under D35 a block may contribute several "
        "episodes, so an episode count and an encounter count are different quantities and "
        "a reader tracking blocks through 01 needs the bridge.",
    )
    return


@app.cell
def _(SHARE_DIR, finish, pl, plt):
    # F10 -- the charting delay, the quantity D34 was decided on. Published rather than
    # avoided: under D23 this was a hazard to be designed around, and D34 makes it a result.
    _d = pl.read_csv(SHARE_DIR / "charting_delay.csv")
    _sup = int(_d.get_column("n_suppressed_bins")[0]) if _d.height else 0
    _order = ["0", "1-4", "5-14", "15-29", "30-59", "60-119", "120-239", "240-479",
              "480-1439", "1440+"]
    _present = [b for b in _order if b in _d.get_column("bin").to_list()]
    _lookup = {r["bin"]: r["n"] for r in _d.to_dicts()}

    _fig, _ax = plt.subplots(figsize=(9.5, 4.4))
    _ax.bar(range(len(_present)), [_lookup[b] for b in _present], color="#DD8452")
    _ax.set_xticks(range(len(_present)))
    _ax.set_xticklabels(_present, rotation=16, ha="right", fontsize=9)
    _ax.set_xlabel("first charted IMV row minus t0  (minutes)")
    _ax.set_ylabel("episodes")
    _ax.set_yscale("log")
    for _i, _b in enumerate(_present):
        _ax.text(_i, _lookup[_b], f"{_lookup[_b]:,}", ha="center", va="bottom", fontsize=7)
    _fig.subplots_adjust(bottom=0.30)
    finish(
        _fig,
        "charting_delay.png",
        "How late the device field is filled in relative to the settings-based inference "
        "that anchors t0 (D34). Zero for most episodes, but the p99 is nine hours -- a "
        "charting delay, not a settings-reading error, which is the argument for the "
        f"anchor. {_sup} bin(s) suppressed below n = 10 and dropped rather than merged (D26).",
    )
    return


@app.cell
def _(CAPTURE_RATE, N_INDEX, REFERENCE_INFORMATIVE, SHARE_DIR, a1, gap, joined):
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"candidate episodes         {joined.height:,}")
    print(f"index set N**              {N_INDEX:,} episodes / "
          f"{analytic.get_column('encounter_block').n_unique():,} blocks / "
          f"{analytic.get_column('patient_id').n_unique():,} patients")
    for _r in a1.to_dicts():
        print(
            f"  {_r['method_id']:<5} {_r['pair_basis']:<13} rate {_r['rate']:.4f}  "
            f"(n={_r['n_detected']:,})"
        )
    print("  specificity, qualified vs each comparator (no known-answer stratum, D37):")
    for _r in gap.to_dicts():
        print(f"    {_r['series']:<20} vs {_r['contrast']:<22} "
              f"gap {_r['gap']}   ratio {_r['ratio']}x")
    print(f"CPT 31500 capture          {CAPTURE_RATE:.4f}  informative={REFERENCE_INFORMATIVE}")
    print()
    print(f"artifacts in {SHARE_DIR}:")
    for _p in sorted(SHARE_DIR.iterdir()):
        print(f"  {_p.name}")
    return



@app.cell
def _(SHARE_DIR):
    # §8's "Outputs written by 07" plus the two CONSORTs and 02's tables. Declared here so a
    # table added without a spec entry -- or promised in the spec and never written -- fails
    # loudly at the end of the run instead of being noticed months later by its absence.
    _expected = {
        "consort_cohort.csv", "cohort_qc.csv",
        "consort_index.csv", "index_class_rates.csv", "charting_delay.csv",
        "agreement_detection_rates.csv", "agreement_pairwise.csv",
        "agreement_concordance.csv", "agreement_combinations.csv",
        "timing_offset_summary.csv", "timing_offset_by_rank.csv", "timing_by_medication.csv",
        "reference_capture_rate.csv", "reference_scoring.csv",
        "specificity_by_lookback.csv", "specificity_by_ep_num.csv",
        "specificity_not_sustained.csv", "specificity_pair_free_running.csv",
        "specificity_gap.csv",
        "pair_count_distribution.csv", "pair_gap_distribution.csv",
        "pair_agent_combinations.csv", "pair_index_offsets.csv", "pair_t0_concordance.csv",
        # Tier F -- D40/D41
        "induction_only_comparison.csv", "infusion_prep_sweep.csv",
        "infusion_prep_by_drug.csv", "prep_by_charting_delay.csv",
        "infusion_prep_sweep.png", "timing_offset_decomposed.png",
        "consort_flow.png", "index_class_strata.png", "episode_funnel.png",
        "charting_delay.png", "timing_offset_distribution.png", "timing_by_medication.png",
        "agreement_overview.png", "specificity_gap.png",
        "pair_offset_distribution.png", "pair_agent_combinations.png",
    }
    _actual = {p.name for p in SHARE_DIR.iterdir() if p.suffix in (".csv", ".png")}
    assert not (_expected - _actual), f"declared but MISSING: {sorted(_expected - _actual)}"
    assert not (_actual - _expected), f"present but UNDECLARED: {sorted(_actual - _expected)}"
    print(f"output manifest conforms to §8: {len(_actual)} artifacts")
    return


if __name__ == "__main__":
    app.run()
