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
    print(f"min cell       : {MIN_CELL}")
    return (
        BASES,
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
        "encounter_block": pl.Int32,
        "patient_id": pl.String,
        "intubation_episode_id": pl.String,
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
    }
    _INDEX_PAIR_FIELDS = [
        "pair_id", "first_class", "sed_med_category", "sed_med_dose", "sed_med_dose_unit",
        "para_med_category", "para_med_dose", "para_med_dose_unit", "gap_minutes",
        "pair_to_t0_min",
    ]
    _PAIR_TAIL = (
        ["n_pairs", "n_unpaired_sed", "n_unpaired_para", "detected_in_window", "first_is_nearest"]
        + [f"first_{c}" for c in _INDEX_PAIR_FIELDS]
        + [f"near_{c}" for c in _INDEX_PAIR_FIELDS]
    )

    ENCOUNTER_SCHEMA = {
        "SED": (list(_CORE) + list(_RANKED_TAIL), {**_CORE, **_RANKED_TAIL}),
        "PARA": (list(_CORE) + list(_RANKED_TAIL), {**_CORE, **_RANKED_TAIL}),
        "PAIR": (list(_CORE) + _PAIR_TAIL, _CORE),
    }

    method_tables = {}
    for _m in METHODS:
        _df = pl.read_parquet(PHI_DIR / f"method_{_m}_encounter.parquet")
        _cols, _types = ENCOUNTER_SCHEMA[_m]

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
def _(METHODS, method_tables, pl, reference):
    _keys = ["intubation_episode_id", "encounter_block", "index_class", "index_qualified"]
    joined = method_tables[METHODS[0]].select(_keys)

    for _m in ("SED", "PARA"):
        joined = joined.join(
            method_tables[_m].select(
                "intubation_episode_id",
                pl.col("detected").alias(f"{_m.lower()}_detected"),
                pl.col("nearest_before_min").alias(f"{_m.lower()}_bef"),
                pl.col("nearest_after_min").alias(f"{_m.lower()}_aft"),
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
    )

    assert joined.height == method_tables[METHODS[0]].height, (
        "the join lost or duplicated encounters; every cohort encounter must appear exactly once"
    )
    # A window hit is a property of a pair, so it cannot exist without one.
    assert joined.filter(
        pl.col("pair_detected_in_window") & ~pl.col("pair_detected")
    ).height == 0, "detected_in_window is true where no pair exists"

    print(f"joined analytic table : {joined.height:,} rows (one per cohort encounter)")
    print(joined.head(6))
    return (joined,)


@app.cell
def _(joined, pl):
    analytic = joined.filter(pl.col("index_class") == "qualified")
    N_INDEX = analytic.height

    print(f"N*  cohort encounters : {joined.height:,}")
    print(f"N** index set         : {N_INDEX:,}   <- the denominator for Tiers A, B, C and E")
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

    return apply_min_cell, detected_expr


@app.cell
def _(mo):
    mo.md("""## Tier A — do the methods find the same patients?""")
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
def _(analytic, method_tables, pairs, pl):
    # The PARA x PAIR `only_b` cell -- PAIR+ and PARA- on the matched basis -- is the design's
    # cross-notebook integrity check, so a non-zero count is decomposed here rather than left
    # for someone to dig out by hand. Two boundary effects put a legitimate floor under it,
    # and anything NOT explained by them is the bug the check exists to catch.
    _susp = (
        analytic.filter(pl.col("pair_detected_in_window") & ~pl.col("para_detected"))
        .select("encounter_block")
    )
    print(f"PARA x PAIR, only_b (PAIR+ & PARA-) on in_window : {_susp.height}")

    if _susp.height:
        _idx = method_tables["PAIR"].select("encounter_block", "imv_dttm")
        _bounds = (
            method_tables["SED"].select("encounter_block").join(_idx, on="encounter_block")
        )
        _d = (
            pairs.join(_susp, on="encounter_block", how="inner")
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
        _explained = _d.filter(pl.col("para_at_t0") | pl.col("para_outside"))
        print(
            f"  explained by D25 (paralytic exactly on t0)      : "
            f"{_d.filter(pl.col('para_at_t0')).height}"
        )
        print(
            f"  explained by §6.5 (in_window is on pair_dttm)   : "
            f"{_d.filter(~pl.col('para_at_t0') & pl.col('para_outside')).height}"
        )
        _unexplained = _d.height - _explained.height
        assert _unexplained == 0, (
            f"{_unexplained} PAIR+/PARA- pairs are explained by NEITHER boundary rule. That is "
            "the list-or-window disagreement this check exists to catch: 05 and 04 are not "
            "reading the paralytic list the same way.\n"
            + str(_d.filter(~pl.col("para_at_t0") & ~pl.col("para_outside")))
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
        ## Tier D — specificity probe on the excluded strata

        The one place the non-qualified encounters are used, and the only stratum in the
        study where the truth is known without a gold standard.

        **`arrived_intubated` is the row with a known answer.** Those patients were intubated
        before they arrived, so nothing in the window around their first charted IMV row can
        be an induction. Every detection there is a false positive **by construction** — no
        reference, no adjudication, no assumption about coding.
        """
    )
    return


@app.cell
def _(BASES, COHORT_RUN_ID, METHODS, SHARE_DIR, apply_min_cell, detected_expr, joined, pl):
    _aggs = {}
    for _basis in BASES:
        for _m in METHODS:
            if _m != "PAIR" and _basis != BASES[0]:
                continue
            _name = f"{_m}_{_basis}" if _m == "PAIR" else _m
            _aggs[f"n_detected_{_name}"] = detected_expr(_m, _basis).sum()

    d1 = (
        joined.group_by("index_class")
        .agg(n=pl.len(), **_aggs)
        .with_columns(
            **{
                f"rate_{_k[len('n_detected_'):]}": (pl.col(_k) / pl.col("n")).round(4)
                for _k in _aggs
            }
        )
        .sort("n", descending=True)
        .with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID))
        .select(
            ["cohort_run_id", "index_class", "n"]
            + list(_aggs)
            + [f"rate_{_k[len('n_detected_'):]}" for _k in _aggs]
        )
    )

    d1_pub = apply_min_cell(d1, ["n"] + list(_aggs), "D.1")
    d1_pub.write_csv(SHARE_DIR / "specificity_by_index_class.csv")
    print("D.1 detection rate by index_class")
    print(d1_pub)

    SERIES = [_k[len("n_detected_"):] for _k in _aggs]
    return SERIES, d1, d1_pub


@app.cell
def _(COHORT_RUN_ID, SERIES, SHARE_DIR, d1_pub, pl):
    _lookup = {r["index_class"]: r for r in d1_pub.to_dicts()}
    _rows = []
    for _s in SERIES:
        _q = _lookup.get("qualified", {}).get(f"rate_{_s}")
        _a = _lookup.get("arrived_intubated", {}).get(f"rate_{_s}")
        _rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "series": _s,
                "rate_qualified": _q,
                "rate_arrived_intubated": _a,
                "gap": round(_q - _a, 4) if _q is not None and _a is not None else None,
                # Reported alongside the difference because at low absolute rates the
                # difference collapses toward zero for arithmetic reasons rather than for want
                # of specificity. 0.016 vs 0.004 is a gap of 0.012, which looks like nothing,
                # and a ratio of 4, which is the statement a gap of 0.43 makes at high rates.
                "ratio": round(_q / _a, 2) if _q is not None and _a else None,
            }
        )

    gap = pl.DataFrame(_rows)
    gap.write_csv(SHARE_DIR / "specificity_gap.csv")
    print("D.1 gap table")
    print(gap)
    print(
        "\n  The strata differ clinically, not only in observability — arrived-intubated\n"
        "  patients are transfers, and transfers differ in acuity and sedation practice. The\n"
        "  gap is therefore a BOUND on specificity, not an unconfounded estimate. It is still\n"
        "  the strongest specificity evidence available without chart review."
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
    enc_q = analytic.select(
        "encounter_block", "n_pairs", "first_is_nearest",
        "first_pair_to_t0_min", "near_pair_to_t0_min",
    )
    # The index pairs of each encounter, used by E.2 and E.3.
    first_pairs_q = (
        pairs_q.sort(["encounter_block", "pair_seq"])
        .group_by("encounter_block", maintain_order=True)
        .first()
    )

    print(f"pairs on the index set  : {pairs_q.height:,}")
    print(f"encounters contributing : {pairs_q.get_column('encounter_block').n_unique():,}")
    return enc_q, first_pairs_q, pairs_q


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, enc_q, pl):
    e1 = (
        enc_q.with_columns(
            pairs_bucket=pl.when(pl.col("n_pairs") >= 3)
            .then(pl.lit("3+"))
            .otherwise(pl.col("n_pairs").cast(pl.String))
        )
        .group_by("pairs_bucket")
        .agg(n=pl.len())
        .sort("pairs_bucket")
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            pct=(100.0 * pl.col("n") / enc_q.height).round(2),
        )
        .select(["cohort_run_id", "pairs_bucket", "n", "pct"])
    )
    e1_pub = apply_min_cell(e1, ["n"], "E.1")
    e1_pub.write_csv(SHARE_DIR / "pair_count_distribution.csv")
    print("E.1 pairs per encounter")
    print(e1_pub)
    print(
        "\n  The 3+ row bounds how much of the free_running / in_window gap in A.1 is\n"
        "  reintubation activity rather than a mis-placed t0. Episode labelling is out of\n"
        "  scope, so this reports that the activity exists without claiming what it was."
    )
    return


@app.cell
def _(
    COHORT_RUN_ID,
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
                       _summarise(first_pairs_q, "index pairs (first)")])
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
        "  means a re-run, not a filter (D29) — but the table tells you whether it is worth it."
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
    print("E.3 which agents pair with which, over index pairs")
    print(e3_pub)
    print(
        "\n  This is the clinical output the method exists to produce, and it is NOT derivable\n"
        "  from SED and PARA run separately — those report their marginals, never the joint.\n"
        "  Rows with long median gaps are the ones most likely to be co-occurrence rather than\n"
        "  a deliberate induction pair, and their share is a direct read on SED's list breadth."
    )
    return (e3_pub,)


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, enc_q, pl):
    _det = enc_q.filter(pl.col("n_pairs") > 0)
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
    print("E.4 index pair offsets, signed minutes from t0")
    print(e4_pub)
    print(
        f"\n  first_is_nearest : {_det.get_column('first_is_nearest').mean():.4f}  "
        f"(n={_det.height:,})"
    )
    return


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, apply_min_cell, enc_q, pl):
    _det = enc_q.filter(pl.col("n_pairs") > 0)
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
    print(f"E.5 device-vs-medication timing concordance   (n detected = {_det.height:,})")
    print(e5_pub)
    print(
        "\n  Read the `beyond +/-180 min` row against A.1's free_running/in_window gap — they\n"
        "  are two views of the same encounters. Every one is a case where the earliest\n"
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
    for _ax, _df, _title, _color in (
        (_axes[0], _a, "CONSORT A — cohort", GREY),
        (_axes[1], _b, "CONSORT B — index", COLORS["SED"]),
    ):
        _steps = _df.get_column("step").to_list()
        _n = [
            v if v is not None else _df.get_column("n_patients").to_list()[i]
            for i, v in enumerate(_df.get_column("n_encounters").to_list())
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
        "Only `qualified` (highlighted) feeds Tiers A-C and E. The other four are "
        "observability failures, and `arrived_intubated` is the Tier D stratum whose truth "
        "is known.",
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
def _(COLORS, SERIES, SITE, d1, finish, gap, pl, plt):
    # F6 -- Tier D. The one figure where a small bar is the good result.
    _order = ["qualified", "arrived_intubated", "prior_row_imv", "insufficient_lookback",
              "imv_not_sustained"]
    _d = d1.filter(pl.col("index_class").is_in(_order))
    _present = [c for c in _order if c in _d.get_column("index_class").to_list()]
    _lookup = {r["index_class"]: r for r in _d.to_dicts()}
    _color = {"SED": COLORS["SED"], "PARA": COLORS["PARA"],
              "PAIR_free_running": "#9ed4ab", "PAIR_in_window": COLORS["PAIR"]}

    _fig, _ax = plt.subplots(figsize=(12, 5.0))
    _w = 0.8 / len(SERIES)
    for _k, _s in enumerate(SERIES):
        _x = [i + (_k - (len(SERIES) - 1) / 2) * _w for i in range(len(_present))]
        _vals = [_lookup[c][f"rate_{_s}"] for c in _present]
        _ax.bar(_x, _vals, width=_w, color=_color.get(_s, "#999999"), label=_s)
        for _xx, _vv in zip(_x, _vals):
            _ax.text(_xx, _vv, f"{_vv:.3f}", ha="center", va="bottom", fontsize=7, rotation=90)

    _ax.set_xticks(range(len(_present)))
    _ax.set_xticklabels([f"{c}\nn={_lookup[c]['n']:,}" for c in _present], fontsize=8.5)
    _ax.set_ylabel("detection rate")
    _ax.set_ylim(top=_ax.get_ylim()[1] * 1.18)
    _ax.legend(frameon=False, fontsize=8)

    # Ratio alongside the difference: at PAIR's absolute rates a gap of 0.012 and a gap of
    # 0.000 look alike on the axis, and they are not alike.
    _gaps = "   ".join(
        f"{r['series']} {r['gap']:.3f} ({r['ratio']}x)"
        for r in gap.to_dicts() if r["gap"] is not None
    )
    _ax.set_title(f"Tier D — specificity probe — {SITE}\n{_gaps}", loc="left",
                  fontweight="bold", fontsize=10)
    finish(
        _fig,
        "specificity_gap.png",
        "Every detection in `arrived_intubated` is a false positive by construction. The gap "
        "between it and `qualified` bounds specificity; a gap near zero means the method is "
        "detecting ICU residence, not intubation.",
    )
    return


@app.cell
def _(COLORS, MIN_CELL, SITE, enc_q, finish, pl, plt):
    # F7 -- E.6. Out-of-range mass is STATED, never clipped into the edge bins: those
    # encounters are the `beyond +/-180` row of E.5, and a clipped bin reads as "just outside
    # the window" when they are the study's most interesting cases.
    _det = enc_q.filter(pl.col("n_pairs") > 0)
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
    _ax.set_xlabel("first_pair_to_t0_min — minutes from t0 to the FIRST pair of the stay")
    _ax.set_ylabel("encounters")
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
        f"{_bin}-minute bins; bins holding 1..{MIN_CELL - 1} encounters are dropped ({_sup}). "
        f"{_out:,} encounters fall beyond ±{_lim} min and are NOT shown — they are the E.5 "
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

    _fig, _ax = plt.subplots(figsize=(1.9 * max(len(_paras), 2) + 3, 0.8 * len(_seds) + 2.8))
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
    _ax.set_xticks(range(len(_paras)), _paras)
    _ax.set_yticks(range(len(_seds)), _seds)
    _ax.grid(False)
    _ax.set_xlabel("paralytic")
    _ax.set_ylabel("sedative")
    _fig.colorbar(_im, ax=_ax, shrink=0.8, label="index pairs")
    _ax.set_title(f"E.3  which agents pair with which — {SITE}", loc="left",
                  fontweight="bold", fontsize=10)
    finish(
        _fig,
        "pair_agent_combinations.png",
        "Cell shows the number of index pairs and the median gap between the two members. "
        "Combinations with fewer than 10 pairs are absent, not zero. This joint distribution "
        "is not derivable from SED and PARA run separately.",
    )
    return


@app.cell
def _(CAPTURE_RATE, N_INDEX, REFERENCE_INFORMATIVE, SHARE_DIR, a1, gap, joined):
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"cohort N*                  {joined.height:,}")
    print(f"index set N**              {N_INDEX:,}")
    for _r in a1.to_dicts():
        print(
            f"  {_r['method_id']:<5} {_r['pair_basis']:<13} rate {_r['rate']:.4f}  "
            f"(n={_r['n_detected']:,})"
        )
    print("  specificity, qualified vs arrived_intubated:")
    for _r in gap.to_dicts():
        print(f"    {_r['series']:<20} gap {_r['gap']}   ratio {_r['ratio']}x")
    print(f"CPT 31500 capture          {CAPTURE_RATE:.4f}  informative={REFERENCE_INFORMATIVE}")
    print()
    print(f"artifacts in {SHARE_DIR}:")
    for _p in sorted(SHARE_DIR.iterdir()):
        print(f"  {_p.name}")
    return


if __name__ == "__main__":
    app.run()
