import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from pathlib import Path

    import matplotlib

    matplotlib.use("Agg")  # notebooks run headless from the CLI
    import matplotlib.pyplot as plt
    import polars as pl
    from matplotlib.ticker import NullFormatter

    import marimo as mo

    return NullFormatter, Path, json, mo, pl, plt


@app.cell
def _(mo):
    mo.md(
        """
        # 06 — Agreement, timing, reference and specificity

        The only notebook that sees more than one method. It is also the **schema
        gatekeeper**: every input is validated against §6.4 before a single number is
        computed, because the failure this guards against is silent. Two artifacts from
        different cohort runs join cleanly — the ids match, the rows are real — and describe
        different patients. `cohort_run_id` is the column that makes that detectable.

        **The single subsetting step in the whole pipeline lives here.** Tiers A, B and C
        are computed on `index_class = 'qualified'` only. Tier D is the one place the
        excluded strata are used. A reader can see in one filter which denominator every
        rate below uses.

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
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    METHODS = ["SED", "PARA"]
    MIN_CELL = 10  # §9 minimum cell size for anything published

    print(f"site        : {SITE}")
    print(f"methods     : {', '.join(METHODS)}")
    print(f"window      : +/- {WINDOW_HOURS} h")
    print(f"min cell    : {MIN_CELL}")
    return METHODS, MIN_CELL, PHI_DIR, SHARE_DIR, SITE, WINDOW_HOURS


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 0 — the schema gatekeeper

        `§6.4` is a contract, so it is checked as one. An extra column is as much a
        violation as a missing one: it means a method invented a field the agreement layer
        does not know how to interpret, and silently ignoring it would let two methods drift
        into reporting different things under the same name.
        """
    )
    return


@app.cell
def _(METHODS, PHI_DIR, pl):
    ENCOUNTER_SCHEMA = {
        "encounter_block": pl.Int32,
        "patient_id": pl.String,
        "intubation_episode_id": pl.String,
        "cohort_run_id": pl.String,
        "index_class": pl.String,
        "index_qualified": pl.Boolean,
        "method_id": pl.String,
        "imv_dttm": pl.Datetime,
        "detected": pl.Boolean,
        "n_before": pl.Int32,
        "n_after": pl.Int32,
        "nearest_before_med": pl.String,
        "nearest_before_min": pl.Float64,
        "nearest_after_med": pl.String,
        "nearest_after_min": pl.Float64,
    }

    method_tables = {}
    for _m in METHODS:
        _df = pl.read_parquet(PHI_DIR / f"method_{_m}_encounter.parquet")

        _expected = list(ENCOUNTER_SCHEMA)
        assert list(_df.columns) == _expected, (
            f"method {_m}: columns do not match the §6.4 contract.\n"
            f"  missing : {sorted(set(_expected) - set(_df.columns))}\n"
            f"  extra   : {sorted(set(_df.columns) - set(_expected))}"
        )
        for _col, _dtype in ENCOUNTER_SCHEMA.items():
            _actual = _df.schema[_col]
            assert _actual.base_type() == _dtype.base_type() if hasattr(_dtype, "base_type") \
                else _actual == _dtype, f"method {_m}: {_col} is {_actual}, expected {_dtype}"

        assert _df.get_column("method_id").unique().to_list() == [_m], (
            f"method {_m}: the file's method_id column disagrees with its filename"
        )
        # `detected` must be the derived quantity, not an independent one. Recompute it and
        # compare -- if a method ever computes the binary separately from the ranked
        # structure, this is where the two are caught disagreeing.
        _mismatch = _df.filter(
            pl.col("detected") != ((pl.col("n_before") > 0) | (pl.col("n_after") > 0))
        ).height
        assert _mismatch == 0, (
            f"method {_m}: {_mismatch:,} rows where detected != (n_before>0 or n_after>0). "
            "The binary flag and the ranked structure disagree."
        )
        assert _df.get_column("intubation_episode_id").is_duplicated().sum() == 0

        method_tables[_m] = _df
        print(f"{_m:<5} {_df.height:,} rows   schema OK   detected-derivation OK")

    reference = pl.read_parquet(PHI_DIR / "reference_cpt.parquet")
    print(f"CPT   {reference.height:,} rows")
    return ENCOUNTER_SCHEMA, method_tables, reference


@app.cell
def _(METHODS, method_tables, reference):
    _run_ids = {m: method_tables[m].get_column("cohort_run_id").unique().to_list() for m in METHODS}
    _run_ids["CPT"] = reference.get_column("cohort_run_id").unique().to_list()

    for _k, _v in _run_ids.items():
        assert len(_v) == 1, f"{_k} carries {len(_v)} cohort_run_ids: {_v}"

    _distinct = {v[0] for v in _run_ids.values()}
    assert len(_distinct) == 1, (
        "inputs come from different cohort runs and MUST NOT be joined:\n"
        + "\n".join(f"  {k:<5} {v[0]}" for k, v in _run_ids.items())
        + "\nencounter_block is a row position, so the same id means different patients "
        "across runs. Re-run 01 through 05 from one cohort."
    )
    COHORT_RUN_ID = _distinct.pop()
    print(f"all inputs share cohort_run_id = {COHORT_RUN_ID}")
    return (COHORT_RUN_ID,)


@app.cell
def _(METHODS, method_tables, pl, reference):
    _keys = ["intubation_episode_id", "encounter_block", "index_class", "index_qualified"]

    joined = method_tables[METHODS[0]].select(_keys)
    for _m in METHODS:
        _lo = _m.lower()
        joined = joined.join(
            method_tables[_m].select(
                "intubation_episode_id",
                pl.col("detected").alias(f"{_lo}_detected"),
                pl.col("n_before").alias(f"{_lo}_n_before"),
                pl.col("n_after").alias(f"{_lo}_n_after"),
                pl.col("nearest_before_min").alias(f"{_lo}_bef"),
                pl.col("nearest_after_min").alias(f"{_lo}_aft"),
            ),
            on="intubation_episode_id",
            how="inner",
        )

    joined = joined.join(
        reference.select("intubation_episode_id", "cpt_present"),
        on="intubation_episode_id",
        how="inner",
    )

    assert joined.height == method_tables[METHODS[0]].height, (
        "the join lost or duplicated encounters; every cohort encounter must appear exactly once"
    )
    print(f"joined analytic table : {joined.height:,} rows (one per cohort encounter)")
    print(joined.head(6))
    return (joined,)


@app.cell
def _(mo):
    mo.md(
        """
        ### The one subsetting step
        """
    )
    return


@app.cell
def _(joined, pl):
    analytic = joined.filter(pl.col("index_class") == "qualified")
    N_INDEX = analytic.height

    print(f"N*  cohort encounters : {joined.height:,}")
    print(f"N** index set         : {N_INDEX:,}   <- the denominator for Tiers A, B and C")
    return N_INDEX, analytic


@app.cell
def _(MIN_CELL, pl):
    def apply_min_cell(df, count_cols, label):
        """Drop any row where a published count falls in 1..MIN_CELL-1.

        A count of exactly zero is kept: it identifies nobody, and dropping it would turn
        "this never happened" into "this is missing", which is a different and worse
        statement in a multi-site study. Counts of 1..9 are the disclosive range and those
        rows are removed from the published table entirely rather than blanked, since a
        blanked cell in a table whose margins are published is often recoverable by
        subtraction.

        Never silent: what was dropped is always printed.
        """
        _mask = pl.lit(False)
        for _c in count_cols:
            _mask = _mask | ((pl.col(_c) > 0) & (pl.col(_c) < MIN_CELL))
        kept = df.filter(~_mask)
        dropped = df.filter(_mask)
        if dropped.height:
            print(
                f"  [{label}] {dropped.height} row(s) suppressed under the n>={MIN_CELL} rule "
                f"on {count_cols}"
            )
            print(dropped)
        return kept

    return (apply_min_cell,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier A — do the methods find the same patients?
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, METHODS, N_INDEX, SHARE_DIR, analytic, apply_min_cell, pl):
    a1 = pl.DataFrame(
        {
            "cohort_run_id": [COHORT_RUN_ID] * len(METHODS),
            "method_id": METHODS,
            "n_detected": [
                analytic.filter(pl.col(f"{m.lower()}_detected")).height for m in METHODS
            ],
            "n_index_set": [N_INDEX] * len(METHODS),
        }
    ).with_columns(rate=(pl.col("n_detected") / pl.col("n_index_set")).round(4))

    a1_pub = apply_min_cell(a1, ["n_detected"], "A.1")
    a1_pub.write_csv(SHARE_DIR / "agreement_detection_rates.csv")
    print("A.1 detection rate per method")
    print(a1_pub)
    return (a1,)


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, analytic, apply_min_cell, pl):
    _s = pl.col("sed_detected")
    _p = pl.col("para_detected")

    _both = analytic.filter(_s & _p).height
    _only_sed = analytic.filter(_s & ~_p).height
    _only_para = analytic.filter(~_s & _p).height
    _neither = analytic.filter(~_s & ~_p).height
    _n = analytic.height

    # Cohen's kappa from the 2x2. Written out rather than imported so a reader can check it
    # against the published cells by hand -- the whole point of publishing the full table.
    _po = (_both + _neither) / _n
    _pe = (
        (_both + _only_sed) * (_both + _only_para) + (_only_para + _neither) * (_only_sed + _neither)
    ) / (_n * _n)
    _kappa = (_po - _pe) / (1 - _pe) if _pe != 1 else float("nan")
    _jaccard = _both / max(_both + _only_sed + _only_para, 1)

    a2 = pl.DataFrame(
        {
            "cohort_run_id": [COHORT_RUN_ID],
            "pair": ["SED x PARA"],
            "both": [_both],
            "only_SED": [_only_sed],
            "only_PARA": [_only_para],
            "neither": [_neither],
            "n": [_n],
            "jaccard": [round(_jaccard, 4)],
            "cohen_kappa": [round(_kappa, 4)],
            "pct_agreement": [round(_po, 4)],
        }
    )

    a2_pub = apply_min_cell(a2, ["both", "only_SED", "only_PARA", "neither"], "A.2")
    a2_pub.write_csv(SHARE_DIR / "agreement_pairwise.csv")

    print("A.2 the 2x2")
    print(f"                PARA+      PARA-      total")
    print(f"  SED+     {_both:>9,}  {_only_sed:>9,}  {_both + _only_sed:>9,}")
    print(f"  SED-     {_only_para:>9,}  {_neither:>9,}  {_only_para + _neither:>9,}")
    print(f"  total    {_both + _only_para:>9,}  {_only_sed + _neither:>9,}  {_n:>9,}")
    print(f"\n  Jaccard {_jaccard:.4f}   Cohen kappa {_kappa:.4f}   raw agreement {_po:.4f}")
    print(
        "\n  The two off-diagonals read differently. 'only SED' is expected to be large --\n"
        "  sedation without paralysis is a real and common technique. 'only PARA' should be\n"
        "  small; a paralytic charted with no induction agent is closer to a documentation\n"
        "  gap than a clinical choice, which is why it is reported as its own cell."
    )
    return (a2,)


@app.cell
def _(COHORT_RUN_ID, SHARE_DIR, analytic, apply_min_cell, pl):
    a3 = (
        analytic.with_columns(
            n_methods=pl.col("sed_detected").cast(pl.Int32) + pl.col("para_detected").cast(pl.Int32)
        )
        .group_by("n_methods")
        .agg(n=pl.len())
        .sort("n_methods")
        .with_columns(
            cohort_run_id=pl.lit(COHORT_RUN_ID),
            pct=(100.0 * pl.col("n") / analytic.height).round(2),
        )
        .select(["cohort_run_id", "n_methods", "n", "pct"])
    )

    a3_pub = apply_min_cell(a3, ["n"], "A.3")
    a3_pub.write_csv(SHARE_DIR / "agreement_concordance.csv")

    print("A.3 concordance histogram")
    print(a3_pub)
    print(
        "\n  Read the n_methods=0 row first. Every encounter here has a documented, sustained\n"
        "  intubation -- 02 guaranteed that much, and the arrived-intubated group is already\n"
        "  gone -- so this count cannot be explained away as 'the patient came in on a vent'.\n"
        "  It is a direct measure of intubations performed here whose medications were never\n"
        "  charted in the window."
    )
    return (a3,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier B — how is charting distributed in time?

        Read from `method_*_ranked.json`, not from the encounter table: the encounter table
        flattens the ladder to rank 1, and B.2 and B.3 need the whole thing. Each episode
        contributes at most one entry per medication per direction (§6.2), so a patient
        redosed six times weighs the same as one dosed once.
        """
    )
    return


@app.cell
def _(METHODS, PHI_DIR, analytic, pl):
    # The §6.3 schema is declared rather than inferred. Inference reads the first records
    # and an encounter with no detection carries `[]`, from which polars infers List(Null)
    # and then fails on the first real object -- but the failure mode that matters is the
    # quiet one: a file whose leading records happen to be non-empty would infer a schema
    # from whatever those records contain. Declaring it makes the JSON a checked contract
    # like the parquet, not a shape discovered at read time.
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
    for _m in METHODS:
        _raw = pl.read_ndjson(PHI_DIR / f"method_{_m}_ranked.json", schema=RANKED_SCHEMA)
        for _dir in ("before", "after"):
            _frames.append(
                _raw.select(["intubation_episode_id", "method_id", _dir])
                .explode(_dir)
                .filter(pl.col(_dir).is_not_null())
                .unnest(_dir)
                .with_columns(direction=pl.lit(_dir))
            )

    ranked_long = (
        pl.concat(_frames, how="vertical")
        .join(analytic.select("intubation_episode_id"), on="intubation_episode_id", how="inner")
        .with_columns(delta_minutes=pl.col("delta_minutes").cast(pl.Float64))
    )

    print(f"ranked entries on the index set : {ranked_long.height:,}")
    print(ranked_long.head(5))
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
    return (b1,)


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
    print("B.2 offset by rank -- the ladder must widen monotonically or the ranking is buggy")
    print(b2_pub)
    return (b2,)


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

    # The n>=10 rule bites hardest here. A rare agent is dropped from the published table
    # rather than pooled into an "other" bucket: pooling across agents with different units
    # and dose scales would produce a median that means nothing.
    b3_pub = apply_min_cell(b3, ["n"], "B.3")
    b3_pub.write_csv(SHARE_DIR / "timing_by_medication.csv")
    print("B.3 per-medication breakdown -- doses are RAW charted values, so read `units` with them")
    print(b3_pub)

    _multi = b3_pub.filter(pl.col("n_units") > 1)
    if _multi.height:
        print(
            f"\n  {_multi.height} medication/direction cell(s) carry more than one dose unit. "
            "That is itself a finding, not a defect to normalise away."
        )
    return (b3,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier C — reference check
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, METHODS, SHARE_DIR, analytic, pl):
    CAPTURE_FLOOR = 0.05
    _n_coded = analytic.filter(pl.col("cpt_present")).height
    CAPTURE_RATE = _n_coded / max(analytic.height, 1)
    REFERENCE_INFORMATIVE = bool(_n_coded >= 10 and CAPTURE_RATE >= CAPTURE_FLOOR)

    print(f"C.1 capture rate on the index set : {CAPTURE_RATE:.4f}")

    _rows = []
    for _m in METHODS:
        _lo = _m.lower()
        _tp = analytic.filter(pl.col(f"{_lo}_detected") & pl.col("cpt_present")).height
        _fp = analytic.filter(pl.col(f"{_lo}_detected") & ~pl.col("cpt_present")).height
        _fn = analytic.filter(~pl.col(f"{_lo}_detected") & pl.col("cpt_present")).height
        _tn = analytic.filter(~pl.col(f"{_lo}_detected") & ~pl.col("cpt_present")).height
        _sens = _tp / max(_tp + _fn, 1)
        _ppv = _tp / max(_tp + _fp, 1)
        _rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "method_id": _m,
                "reference_id": "CPT",
                "capture_rate": round(CAPTURE_RATE, 4),
                "informative": REFERENCE_INFORMATIVE,
                "tp": _tp if REFERENCE_INFORMATIVE else None,
                "fp": _fp if REFERENCE_INFORMATIVE else None,
                "fn": _fn if REFERENCE_INFORMATIVE else None,
                "tn": _tn if REFERENCE_INFORMATIVE else None,
                "sensitivity": round(_sens, 4) if REFERENCE_INFORMATIVE else None,
                "ppv": round(_ppv, 4) if REFERENCE_INFORMATIVE else None,
                "f1": round(2 * _sens * _ppv / max(_sens + _ppv, 1e-12), 4)
                if REFERENCE_INFORMATIVE
                else None,
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
            "  not the performance of the methods, and would be read as the latter.\n"
            "  reference_scoring.csv records the fact and the empty columns."
        )
    return CAPTURE_RATE, REFERENCE_INFORMATIVE, c2


@app.cell
def _(mo):
    mo.md(
        """
        ## Tier D — specificity probe on the excluded strata

        The one place the non-qualified encounters are used, and the only stratum in the
        study where the truth is known without a gold standard.

        **`arrived_intubated` is the row with a known answer.** Those patients were
        intubated before they arrived, so nothing in the window around their first charted
        IMV row can be an induction. Every detection there is a false positive **by
        construction** — no reference, no adjudication, no assumption about coding.

        The gap between a method's `qualified` rate and its `arrived_intubated` rate is the
        sharpest single-number specificity summary this design can produce. A gap
        approaching zero means the method is not detecting intubation at all; it is
        detecting being in an ICU.
        """
    )
    return


@app.cell
def _(COHORT_RUN_ID, METHODS, SHARE_DIR, apply_min_cell, joined, pl):
    d1 = (
        joined.group_by("index_class")
        .agg(
            n=pl.len(),
            **{
                f"n_detected_{m}": pl.col(f"{m.lower()}_detected").sum() for m in METHODS
            },
        )
        .with_columns(
            **{
                f"rate_{m}": (pl.col(f"n_detected_{m}") / pl.col("n")).round(4) for m in METHODS
            }
        )
        .sort("n", descending=True)
        .with_columns(cohort_run_id=pl.lit(COHORT_RUN_ID))
        .select(
            ["cohort_run_id", "index_class", "n"]
            + [f"n_detected_{m}" for m in METHODS]
            + [f"rate_{m}" for m in METHODS]
        )
    )

    d1_pub = apply_min_cell(d1, ["n"] + [f"n_detected_{m}" for m in METHODS], "D.1")
    d1_pub.write_csv(SHARE_DIR / "specificity_by_index_class.csv")
    print("D.1 detection rate by index_class")
    print(d1_pub)
    return d1, d1_pub


@app.cell
def _(COHORT_RUN_ID, METHODS, SHARE_DIR, d1_pub, pl):
    _rates = {
        (r["index_class"], m): r[f"rate_{m}"] for r in d1_pub.to_dicts() for m in METHODS
    }

    _gap_rows = []
    for _m in METHODS:
        _q = _rates.get(("qualified", _m))
        _a = _rates.get(("arrived_intubated", _m))
        _gap_rows.append(
            {
                "cohort_run_id": COHORT_RUN_ID,
                "method_id": _m,
                "rate_qualified": _q,
                "rate_arrived_intubated": _a,
                "gap": round(_q - _a, 4) if _q is not None and _a is not None else None,
            }
        )

    gap = pl.DataFrame(_gap_rows)
    gap.write_csv(SHARE_DIR / "specificity_gap.csv")
    print("D.1 gap table")
    print(gap)
    print(
        "\n  The strata differ clinically, not only in observability -- arrived-intubated\n"
        "  patients are transfers, and transfers differ in acuity and sedation practice. The\n"
        "  gap is therefore a BOUND on specificity, not an unconfounded estimate. It is still\n"
        "  the strongest specificity evidence available without chart review."
    )
    return (gap,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Figures

        Every figure is drawn from a published table, so the n >= 10 rule applies to the
        pictures exactly as it does to the CSVs — a suppressed row is absent from the plot
        too, and where a histogram bin falls in the disclosive range the bin is dropped and
        the dropped mass is stated in the caption rather than quietly folded into a
        neighbour.
        """
    )
    return


@app.cell
def _(SHARE_DIR, plt):
    FIG_BG = "white"
    COLORS = {"SED": "#2c6fbb", "PARA": "#d1495b"}
    GREY = "#555555"

    def finish(fig, path, caption=None):
        if caption:
            fig.text(0.01, 0.005, caption, ha="left", va="bottom", fontsize=7.5, color=GREY)
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
    # F1 -- the two CONSORTs side by side. Drawn from the published CSVs rather than
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
        # Log scale, because CONSORT A spans 223,452 down to 34,017 and a linear axis
        # collapses the last five steps into one indistinguishable stub. Minor tick labels
        # are silenced -- matplotlib writes 3x10^4, 4x10^4, 6x10^4 between the decades and
        # they collide with each other long before they inform anyone.
        _ax.set_xscale("log")
        _ax.xaxis.set_minor_formatter(NullFormatter())
        _ax.set_xlabel("n (log scale)")
        _ax.set_title(_title, loc="left", fontweight="bold")
        _excl = _df.get_column("n_excluded").to_list()
        for _yy, _nn, _ee in zip(_y, _n, _excl):
            _label = f"{_nn:,}" + (f"   (−{_ee:,})" if _ee else "")
            _ax.text(_nn * 1.12, _yy, _label, va="center", fontsize=8, color="#222222")
        _ax.set_xlim(right=max(_n) * 3.2)

    _fig.suptitle(f"VentTRACE cohort and index flow — {SITE}", x=0.01, ha="left", fontweight="bold")
    _fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    finish(
        _fig,
        "consort_flow.png",
        "Bars are cumulative survivors at each step; parenthesised figures are the exclusion at "
        "that step. Panel A counts patients until stitching defines an encounter.",
    )
    return


@app.cell
def _(COLORS, SHARE_DIR, SITE, finish, joined, pl, plt):
    # F2 -- the index strata. The headline of 02, and the denominator map for everything
    # downstream: only the leftmost bar feeds Tiers A-C.
    _cnt = (
        joined.group_by("index_class")
        .agg(n=pl.len())
        .sort("n", descending=True)
        .with_columns(pct=100.0 * pl.col("n") / joined.height)
    )
    _labels = _cnt.get_column("index_class").to_list()
    _vals = _cnt.get_column("n").to_list()
    _pcts = _cnt.get_column("pct").to_list()
    _colors = [COLORS["SED"] if lab == "qualified" else "#b9c4d2" for lab in _labels]

    _fig, _ax = plt.subplots(figsize=(9, 4.4))
    _bars = _ax.bar(_labels, _vals, color=_colors, width=0.62)
    for _b, _v, _p in zip(_bars, _vals, _pcts):
        _ax.text(
            _b.get_x() + _b.get_width() / 2,
            _v,
            f"{_v:,}\n{_p:.1f}%",
            ha="center",
            va="bottom",
            fontsize=8.5,
        )
    _ax.set_ylabel("encounters")
    _ax.set_ylim(top=max(_vals) * 1.22)
    _ax.set_title(
        f"Index classes across the cohort — {SITE}   (N* = {joined.height:,})",
        loc="left",
        fontweight="bold",
    )
    _ax.set_xticks(range(len(_labels)))
    _ax.set_xticklabels(_labels, rotation=16, ha="right", fontsize=9)
    _fig.subplots_adjust(bottom=0.30)
    finish(
        _fig,
        "index_class_strata.png",
        "Only `qualified` (highlighted) feeds Tiers A-C. The other four are observability "
        "failures, and `arrived_intubated` is the Tier D stratum whose truth is known.",
    )
    return


@app.cell
def _(COLORS, MIN_CELL, SHARE_DIR, SITE, WINDOW_HOURS, finish, pl, plt, ranked_long):
    # F3 -- B.4. Plotted as % of each method's OWN entries, not as raw counts. The two
    # methods differ by more than an order of magnitude in volume here, and on a shared
    # count axis PARA is a flat line against the axis -- which reads as "PARA has no timing
    # signal" when what it actually has is a smaller denominator. Shape is the question
    # this figure asks; the counts behind it are published in B.1 and B.2.
    _lim = 180
    _bin = 10
    _edges = list(range(-_lim, _lim + _bin, _bin))

    _fig, _ax = plt.subplots(figsize=(11, 4.8))
    _suppressed = 0
    _totals = {}
    for _m in ("SED", "PARA"):
        _v = (
            ranked_long.filter(
                (pl.col("method_id") == _m) & (pl.col("delta_minutes").abs() <= _lim)
            )
            .get_column("delta_minutes")
            .to_list()
        )
        _counts = [0] * (len(_edges) - 1)
        for _x in _v:
            _i = min(int((_x + _lim) // _bin), len(_counts) - 1)
            _counts[_i] += 1
        # Bins in the disclosive range are dropped, never merged into a neighbour: merging
        # would move mass the reader cannot see move.
        _kept = []
        for _c in _counts:
            if 0 < _c < MIN_CELL:
                _suppressed += _c
                _kept.append(0)
            else:
                _kept.append(_c)
        _totals[_m] = len(_v)
        _pct = [100.0 * _c / max(len(_v), 1) for _c in _kept]
        _centers = [(_edges[i] + _edges[i + 1]) / 2 for i in range(len(_pct))]
        _ax.step(
            _centers,
            _pct,
            where="mid",
            color=COLORS[_m],
            linewidth=1.7,
            label=f"{_m}  (n={len(_v):,} entries)",
        )
        _ax.fill_between(_centers, _pct, step="mid", color=COLORS[_m], alpha=0.16)

    _ax.axvline(0, color="#111111", linewidth=1.2)
    _ax.text(0, _ax.get_ylim()[1] * 0.97, "  t0", va="top", fontsize=9, fontweight="bold")
    _ax.set_xlabel(f"minutes relative to t0   (detection window is ±{WINDOW_HOURS} h)")
    _ax.set_ylabel("% of that method's ranked entries")
    _ax.set_xlim(-_lim, _lim)
    _ax.set_xticks(range(-_lim, _lim + 1, 30))
    _ax.legend(frameon=False)
    _ax.set_title(f"Medication timing around t0 — {SITE}", loc="left", fontweight="bold")
    finish(
        _fig,
        "timing_offset_distribution.png",
        f"{_bin}-minute bins, each series normalised to its own total so the shapes are "
        f"comparable. Bins holding 1..{MIN_CELL - 1} entries are dropped ({_suppressed} "
        "entries). Both methods should peak just LEFT of t0; mass to the right means either "
        "post-intubation dosing or that t0 is landing early.",
    )
    return


@app.cell
def _(COLORS, SHARE_DIR, SITE, finish, pl, plt):
    # F4 -- B.3, read off the published table so suppression is inherited automatically.
    _b3 = pl.read_csv(SHARE_DIR / "timing_by_medication.csv")

    _fig, _axes = plt.subplots(1, 2, figsize=(12, 4.4), sharey=False)
    for _ax, _dir in zip(_axes, ("before", "after")):
        _d = _b3.filter(pl.col("direction") == _dir).sort("n")
        if _d.height == 0:
            _ax.text(0.5, 0.5, "nothing published at n >= 10", ha="center", transform=_ax.transAxes)
            _ax.set_title(_dir, loc="left", fontweight="bold")
            continue
        _labels = [
            f"{r['med_category']}  (n={r['n']:,})" for r in _d.to_dicts()
        ]
        _y = list(range(_d.height))
        _ax.barh(
            _y,
            _d.get_column("median_min").to_list(),
            color=[COLORS[m] for m in _d.get_column("method_id").to_list()],
            height=0.6,
        )
        _ax.set_yticks(_y)
        _ax.set_yticklabels(_labels, fontsize=8.5)
        _ax.axvline(0, color="#111111", linewidth=1.0)
        _ax.set_xlabel("median minutes from t0")
        _ax.set_title(_dir, loc="left", fontweight="bold")

    _fig.suptitle(
        f"Median offset by medication — {SITE}", x=0.01, ha="left", fontweight="bold"
    )
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
    # F5 -- Tier A in one frame: the marginals, the four-cell agreement, the concordance.
    _a1 = pl.read_csv(SHARE_DIR / "agreement_detection_rates.csv")
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
    _row = a2.to_dicts()[0]
    _grid = [[_row["both"], _row["only_SED"]], [_row["only_PARA"], _row["neither"]]]
    _im = _ax.imshow(_grid, cmap="Blues")
    for _i in range(2):
        for _j in range(2):
            _v = _grid[_i][_j]
            _ax.text(_j, _i, f"{_v:,}", ha="center", va="center", fontsize=12,
                     color="white" if _v > max(map(max, _grid)) * 0.55 else "#111111")
    _ax.set_xticks([0, 1], ["PARA +", "PARA −"])
    _ax.set_yticks([0, 1], ["SED +", "SED −"])
    _ax.grid(False)
    _ax.set_title(
        f"A.2  2×2   J={_row['jaccard']:.2f}  κ={_row['cohen_kappa']:.2f}",
        loc="left",
        fontweight="bold",
    )

    _ax = _axes[2]
    _c = a3.sort("n_methods")
    _ax.bar(
        [str(x) for x in _c.get_column("n_methods").to_list()],
        _c.get_column("pct").to_list(),
        color=["#b9c4d2", "#8fa6bf", COLORS["SED"]],
        width=0.55,
    )
    for _x, (_p, _n) in enumerate(zip(_c.get_column("pct").to_list(), _c.get_column("n").to_list())):
        _ax.text(_x, _p, f"{_p:.1f}%\nn={_n:,}", ha="center", va="bottom", fontsize=8.5)
    _ax.set_xlabel("methods firing")
    _ax.set_ylabel("% of index set")
    _ax.set_ylim(0, max(_c.get_column("pct").to_list()) * 1.35)
    _ax.set_title("A.3  concordance", loc="left", fontweight="bold")

    _fig.suptitle(f"Tier A — method agreement — {SITE}", x=0.01, ha="left", fontweight="bold")
    _fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    finish(
        _fig,
        "agreement_overview.png",
        "The `0 methods firing` bar counts documented, sustained intubations where neither "
        "medication signal appeared in the window.",
    )
    return


@app.cell
def _(COLORS, SHARE_DIR, SITE, d1, finish, gap, pl, plt):
    # F6 -- Tier D. The one figure where a small bar is the good result.
    _order = ["qualified", "arrived_intubated", "prior_row_imv", "insufficient_lookback",
              "imv_not_sustained"]
    _d = d1.filter(pl.col("index_class").is_in(_order))
    _present = [c for c in _order if c in _d.get_column("index_class").to_list()]
    _lookup = {r["index_class"]: r for r in _d.to_dicts()}

    _fig, _ax = plt.subplots(figsize=(10, 4.6))
    _w = 0.38
    for _k, _m in enumerate(("SED", "PARA")):
        _x = [i + (_k - 0.5) * _w for i in range(len(_present))]
        _vals = [_lookup[c][f"rate_{_m}"] for c in _present]
        _ax.bar(_x, _vals, width=_w, color=COLORS[_m], label=_m)
        for _xx, _vv in zip(_x, _vals):
            _ax.text(_xx, _vv, f"{_vv:.3f}", ha="center", va="bottom", fontsize=8)

    _ax.set_xticks(range(len(_present)))
    _ax.set_xticklabels(
        [f"{c}\nn={_lookup[c]['n']:,}" for c in _present], fontsize=8.5
    )
    _ax.set_ylabel("detection rate")
    _ax.legend(frameon=False)

    _gaps = "   ".join(
        f"{r['method_id']} gap={r['gap']:.3f}" for r in gap.to_dicts() if r["gap"] is not None
    )
    _ax.set_title(
        f"Tier D — specificity probe — {SITE}      {_gaps}", loc="left", fontweight="bold"
    )
    finish(
        _fig,
        "specificity_gap.png",
        "Every detection in `arrived_intubated` is a false positive by construction. The gap "
        "between it and `qualified` bounds specificity; a gap near zero means the method is "
        "detecting ICU residence, not intubation.",
    )
    return


@app.cell
def _(
    CAPTURE_RATE,
    METHODS,
    N_INDEX,
    REFERENCE_INFORMATIVE,
    SHARE_DIR,
    a1,
    a2,
    gap,
    joined,
    pl,
):
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"cohort N*                  {joined.height:,}")
    print(f"index set N**              {N_INDEX:,}")
    for _r in a1.to_dicts():
        print(f"  {_r['method_id']:<5} detection rate     {_r['rate']:.4f}  (n={_r['n_detected']:,})")
    _row = a2.to_dicts()[0]
    print(f"  Jaccard {_row['jaccard']:.4f}   Cohen kappa {_row['cohen_kappa']:.4f}")
    for _r in gap.to_dicts():
        print(f"  {_r['method_id']:<5} specificity gap    {_r['gap']}")
    print(f"CPT 31500 capture          {CAPTURE_RATE:.4f}  informative={REFERENCE_INFORMATIVE}")
    print()
    print(f"artifacts in {SHARE_DIR}:")
    for _p in sorted(SHARE_DIR.iterdir()):
        print(f"  {_p.name}")
    return


if __name__ == "__main__":
    app.run()
