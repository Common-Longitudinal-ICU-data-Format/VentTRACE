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
    from utils.suppress import MIN_CELL, publish

    return (
        MIN_CELL,
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
    # P4. 'bolus' is how many EHRs chart a one-time IV push, which is exactly what an
    # intubating paralytic is. Keeping 'given' alone risks a site reporting zero
    # paralytics, and zero is indistinguishable from a site that gives none.
    MAR_ACTIONS = ["given", "bolus"]

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
    return (
        COLLAPSE_GAP_MINUTES,
        DATA_DIR,
        FIG_DIR,
        FILETYPE,
        GAP_CUT_BREAKS,
        GAP_CUT_LABELS,
        GAP_BIN_LABELS,
        MAR_ACTIONS,
        MAX_TOTAL_PAIRS,
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
def _(TIMEZONE):
    def to_site_naive(series):
        """The only correct way to get a naive site-local timestamp out of clifpy.

        clifpy hands back a pytz tzinfo still in its LMT state, so `.dt.tz_localize(None)`
        drops the offset that is *attached* rather than the offset that is *correct* and
        silently shifts every timestamp by about an hour. `tz_convert` re-resolves against
        the tz database first. Pinned by `tests/test_clifpy_tz_boundary.py`.

        Defined locally, never imported (spec §4): a bug in a shared datetime helper
        corrupts every consumer identically, and identical corruption is the hardest kind
        to see.
        """
        return series.dt.tz_convert(TIMEZONE).dt.tz_localize(None)

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
    cohort_index = pl.read_parquet(PHI_DIR / "cohort_index.parquet")

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
    )

    med_admin = (
        med_all.filter(
            pl.col("med_category").is_in(PARALYTICS)
            & pl.col("mar_action_category").is_in(MAR_ACTIONS)
        )
        .join(bridge, on="hospitalization_id", how="inner")
        .drop("hospitalization_id")  # the bridge ends here -- everything below is per block
    )

    assert "hospitalization_id" not in med_admin.columns, "the bridge leaked its key"

    # A category filter that matches nothing looks exactly like a site where the drug is
    # never given. Print what was actually found so the two are distinguishable, and fail
    # only if the whole list came back empty -- an individual agent may genuinely be absent
    # from a formulary; succinylcholine often is.
    _found = med_admin.group_by(["med_category", "mar_action_category"]).agg(n=pl.len())
    _missing = sorted(set(PARALYTICS) - set(med_admin.get_column("med_category").unique()))

    print(f"intermittent rows loaded : {med_all.height:,}")
    print(f"paralytic administrations: {med_admin.height:,}")
    print(f"  over encounter blocks  : {med_admin.get_column('encounter_block').n_unique():,}")
    print(f"  over patients          : {med_admin.get_column('patient_id').n_unique():,}")
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
        ## A — the co-administration gap distribution

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
        SHARE_DIR / "paralytic_admin_summary.csv",
        ["n_administrations", "n_blocks", "n_patients"],
        "paralytic_admin_summary",
    )
    return (admin_summary,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ### Secondary suppression across the three A tables

        `coadmin_gap_distribution.csv` publishes `n_same_agent` per bin; `coadmin_gap_by_pair.csv`
        publishes the per-`agent_pair` components that sum to it. Row-level suppression applied to
        each file separately is not enough when two files share a bin key: publishing `n_same_agent`
        whole while withholding one `agent_pair` row lets a reader recover the withheld value by
        subtraction. At this site, `(5,10]` published `n_same_agent = 18` and
        `rocuronium+rocuronium = 12` in the same run; the withheld `vecuronium+vecuronium = 6` is
        `18 − 12`, no different from publishing it outright.

        Every bin is classified into exactly one of three modes **before anything is written**:

        * **FULL** — `n_cross_agent` and every individual `agent_pair` count in the bin are each
          exactly 0 or at least `MIN_CELL`. No subtraction across the two files can then land on a
          value in 1..9. Published in both `coadmin_gap_distribution.csv` and
          `coadmin_gap_by_pair.csv`.
        * **POOLED_ONLY** — `n_pooled` itself clears `MIN_CELL`, but at least one component does
          not. Published as `n_pooled` alone, in a new `coadmin_gap_pooled.csv`, and withheld from
          the other two files entirely — with no decomposition published for the bin, nothing about
          it is recoverable.
        * **NONE** — `n_pooled` itself is in 1..9. Nothing about the bin is published anywhere.

        The three published files must **partition** the bins by mode: a bin cannot carry a
        decomposition in one file and also appear pooled-only in another. That partition is asserted
        below rather than left to a later reconciliation to catch.
        """
    )
    return


@app.cell
def _(MIN_CELL):
    def classify_bin_mode(n_pooled, n_cross_agent, pair_counts, min_cell=MIN_CELL):
        """Classify one gap_bin into FULL / POOLED_ONLY / NONE for secondary suppression.

        `n_pooled` is the bin's total pair count; `n_cross_agent` is the aggregate
        cross-agent count published in `coadmin_gap_distribution.csv`; `pair_counts` is
        every individual `agent_pair` count (same-agent and cross-agent alike) that would
        be published for this bin in `coadmin_gap_by_pair.csv`.

        FULL requires every one of those components to be exactly 0 or >= `min_cell` --
        not just `n_pooled`. A bin can clear the pooled total and still leak a withheld
        component by subtraction if only ONE component is checked (the defect this
        function exists to close): `n_same_agent` published whole alongside one
        `agent_pair` row lets a reader recover the other by `n_same_agent - published`.

        Order of checks matters only for NONE, which is decided on `n_pooled` alone --
        a bin with `n_pooled` in 1..9 cannot be POOLED_ONLY (nothing would satisfy
        `n_pooled >= min_cell`) and every one of its components is necessarily smaller
        than `n_pooled`, so checking components first would reach the same answer by a
        longer path.
        """
        if 0 < n_pooled < min_cell:
            return "NONE"
        _components = [n_cross_agent, *pair_counts]
        if all(_c == 0 or _c >= min_cell for _c in _components):
            return "FULL"
        return "POOLED_ONLY"

    return (classify_bin_mode,)


@app.cell
def _(mo):
    mo.md(
        """
        ### Classifying every bin

        One pass per bin: the pooled total, the cross-agent aggregate, and the list of
        individual `agent_pair` counts are computed directly from `coadmin_pairs` --
        unsuppressed -- and handed to `classify_bin_mode`. The result is printed in full
        here, in the run log only; nothing on this page is written to `final_no_phi`.
        """
    )
    return


@app.cell
def _(GAP_BIN_LABELS, classify_bin_mode, coadmin_pairs, pl):
    _pair_counts_by_bin = coadmin_pairs.group_by(["gap_bin", "agent_pair"]).agg(n=pl.len())

    _rows = []
    for _order, _bin in enumerate(GAP_BIN_LABELS):
        _bin_pairs = coadmin_pairs.filter(pl.col("gap_bin") == _bin)
        _n_pooled = _bin_pairs.height
        _n_cross = int((~_bin_pairs.get_column("is_same_agent")).sum()) if _n_pooled else 0
        _n_same = _n_pooled - _n_cross
        _counts = _pair_counts_by_bin.filter(pl.col("gap_bin") == _bin).get_column("n").to_list()
        _rows.append(
            {
                "bin_order": _order,
                "gap_bin": _bin,
                "n_pooled": _n_pooled,
                "n_same_agent": _n_same,
                "n_cross_agent": _n_cross,
                "mode": classify_bin_mode(_n_pooled, _n_cross, _counts),
            }
        )

    bin_modes = pl.DataFrame(_rows)
    print("bin mode classification (unsuppressed -- run log only, never written):")
    print(bin_modes)

    print("\nsub-15-minute mass, the boundary evidence (unsuppressed, run log only):")
    print(
        bin_modes.filter(
            pl.col("gap_bin").is_in(["0", "(0,1]", "(1,2]", "(2,5]", "(5,10]", "(10,15]"])
        )
    )
    return (bin_modes,)


@app.cell
def _(GAP_BIN_LABELS, SHARE_DIR, bin_modes, coadmin_pairs, pl, publish):
    _full_bins = bin_modes.filter(pl.col("mode") == "FULL").get_column("gap_bin").to_list()
    _pooled_only_bins = bin_modes.filter(pl.col("mode") == "POOLED_ONLY").get_column("gap_bin").to_list()
    _none_bins = bin_modes.filter(pl.col("mode") == "NONE").get_column("gap_bin").to_list()

    # The three published files must partition the bins by mode. A bin classified into
    # more than one mode is the exact disclosure failure secondary suppression exists to
    # prevent, so this fails loudly here rather than waiting for the reconciliation cell
    # below to catch it.
    assert not (set(_full_bins) & set(_pooled_only_bins)), (
        "a bin is classified both FULL and POOLED_ONLY -- it would appear decomposed in "
        "coadmin_gap_distribution.csv/coadmin_gap_by_pair.csv AND pooled in "
        "coadmin_gap_pooled.csv"
    )
    assert not (set(_full_bins) & set(_none_bins)), "a bin is classified both FULL and NONE"
    assert not (set(_pooled_only_bins) & set(_none_bins)), (
        "a bin is classified both POOLED_ONLY and NONE"
    )
    assert set(_full_bins) | set(_pooled_only_bins) | set(_none_bins) == set(GAP_BIN_LABELS), (
        "every gap_bin must land in exactly one of FULL / POOLED_ONLY / NONE"
    )

    # FULL bins carry the same/cross decomposition, exactly as before -- restricted to
    # the bins cleared for it.
    gap_distribution = (
        bin_modes.filter(pl.col("mode") == "FULL")
        .select("bin_order", "gap_bin", "n_pooled", "n_same_agent", "n_cross_agent")
        .sort("bin_order")
    )
    gap_distribution_published = publish(
        gap_distribution,
        SHARE_DIR / "coadmin_gap_distribution.csv",
        ["n_pooled", "n_same_agent", "n_cross_agent"],
        "coadmin_gap_distribution",
    )

    gap_by_pair = (
        coadmin_pairs.filter(pl.col("gap_bin").is_in(_full_bins))
        .group_by(["agent_pair", "gap_bin"])
        .agg(n=pl.len())
        .join(
            pl.DataFrame({"gap_bin": GAP_BIN_LABELS}).with_row_index("bin_order"),
            on="gap_bin",
            how="left",
        )
        .sort(["agent_pair", "bin_order"])
    )
    gap_by_pair_published = publish(
        gap_by_pair,
        SHARE_DIR / "coadmin_gap_by_pair.csv",
        ["n"],
        "coadmin_gap_by_pair",
    )

    # POOLED_ONLY bins carry n_pooled alone; no decomposition is published anywhere for
    # them, in either of the two files above.
    gap_pooled = (
        bin_modes.filter(pl.col("mode") == "POOLED_ONLY")
        .select("bin_order", "gap_bin", "n_pooled")
        .sort("bin_order")
    )
    gap_pooled_published = publish(
        gap_pooled,
        SHARE_DIR / "coadmin_gap_pooled.csv",
        ["n_pooled"],
        "coadmin_gap_pooled",
    )

    return gap_by_pair_published, gap_distribution_published, gap_pooled_published


@app.cell
def _(mo):
    mo.md(
        """
        ### Reconciliation: proving the leak is closed

        For every bin published in `coadmin_gap_distribution.csv`, the `agent_pair` rows
        published for that same bin in `coadmin_gap_by_pair.csv` must sum to **exactly**
        `n_same_agent + n_cross_agent`. A non-zero residual means a withheld component is
        recoverable from the two published files by subtraction -- the defect that
        motivated secondary suppression. Checked mechanically, on the frames `publish()`
        actually wrote, and printed so it is visible in the run log.
        """
    )
    return


@app.cell
def _(gap_by_pair_published, gap_distribution_published, pl):
    _pair_totals = gap_by_pair_published.group_by("gap_bin").agg(n_from_pairs=pl.col("n").sum())

    reconciliation = (
        gap_distribution_published.select("gap_bin", "n_same_agent", "n_cross_agent")
        .with_columns(n_expected=pl.col("n_same_agent") + pl.col("n_cross_agent"))
        .join(_pair_totals, on="gap_bin", how="left")
        .with_columns(pl.col("n_from_pairs").fill_null(0))
        .with_columns(residual=pl.col("n_expected") - pl.col("n_from_pairs"))
    )
    print("reconciliation -- published distribution vs. published by-pair components:")
    print(reconciliation)

    assert (reconciliation.get_column("residual") == 0).all(), (
        "a bin in coadmin_gap_distribution.csv does not reconcile exactly against its "
        "agent_pair rows in coadmin_gap_by_pair.csv -- a withheld component is "
        "recoverable by subtraction"
    )
    print("reconciliation OK: zero residual on every published bin")
    return (reconciliation,)


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
        pl.col("_t_min"), pl.col("med_category"), _row=pl.int_range(pl.len())
    )

    _rows = []
    for _block, _times, _cats, _ in _grouped.iter_rows():
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
    _path = PHI_DIR / "index_paralytic.parquet"
    index_paralytic.write_parquet(_path)
    print(f"index_paralytic.parquet   {index_paralytic.height:,} rows -> {_path}")
    return


if __name__ == "__main__":
    app.run()
