import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import sys
    from pathlib import Path

    import matplotlib.pyplot as plt
    import polars as pl

    import marimo as mo

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.suppress import publish

    return Path, json, mo, pl, plt, publish


@app.cell
def _(mo):
    mo.md(
        """
        # 05 — Table 1

        Published twice from one frame (P34): once per **encounter block**, at its
        `p_num = 1` event, and once per **index paralytic event**. Identical row
        inventory, different unit, so the two are directly comparable and the difference
        between them measures what re-paralysis contributes.

        Every row carries a `rule` and a `unit` (P35). These CSVs are merged across
        consortium sites and pasted into manuscripts, arriving detached from the notebook
        that produced them — every other artifact in this pipeline depends on
        `pipeline_flow.md` being read alongside it, and this is the first that carries its
        own definitions. The `unit` column also defuses the trap P34 creates: block-level
        outcomes repeat down the index-level table, so `los_hospital_days` there states
        "block-level value, repeated per index event" and nobody averages it by accident.

        Continuous variables publish **mean, SD, median, Q1 and Q3** (P36) — mean beside
        median is how a reader detects skew without a figure, and LOS, CCI and the index
        count are all heavily right-skewed. Categoricals publish `n` **and** `pct`: a
        percentage without its numerator cannot be pooled across sites.

        This notebook opens no CLIF table.
        """
    )
    return


@app.cell
def _(Path, json):
    _config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(_config_path, "r") as _f:
        config = json.load(_f)

    SITE = config["site_name"]
    OUTPUT_DIR = Path(config["output_directory"])
    PHI_DIR = OUTPUT_DIR / "intermediate_phi"
    SHARE_DIR = OUTPUT_DIR / "final_no_phi"
    FIG_DIR = SHARE_DIR / "figures"
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # P34/§6. Every stratum column is emitted even when structurally empty --
    # succinylcholine is absent from MIMIC entirely, and a column present at one site and
    # missing at another is what breaks a multi-site merge. This is P21's published-zero
    # convention applied to columns.
    STRATA = ["rocuronium", "succinylcholine", "vecuronium", "combination"]

    LOOKBACK_HOURS = [1, 6, 24]

    print(f"site   : {SITE}")
    print(f"strata : {' | '.join(STRATA)}")
    return FIG_DIR, LOOKBACK_HOURS, PHI_DIR, SHARE_DIR, SITE, STRATA, config


@app.cell
def _(pl):
    def continuous_rows(df, column, rule, unit):
        """P36's five statistics for one continuous column, as (statistic, rule, unit, value).

        Returns five records. Nulls are excluded from every statistic -- a missing SBP is
        not a low SBP -- and `n_nonnull` is emitted as a sixth so the reader knows the
        denominator each statistic was computed on. That denominator differs per variable
        (a site without `position` has null prone flags but real ages) and a Table 1 that
        hides it invites pooling statistics computed on different populations.
        """
        s = df.get_column(column).drop_nulls()
        if s.len() == 0:
            stats = {"mean": None, "sd": None, "median": None, "q1": None, "q3": None}
        else:
            stats = {
                "mean": s.mean(),
                "sd": s.std(),
                "median": s.median(),
                "q1": s.quantile(0.25),
                "q3": s.quantile(0.75),
            }
        rows = [
            {
                "statistic": f"{column}_{k}",
                "rule": rule,
                "unit": unit,
                "value": None if v is None else round(float(v), 3),
            }
            for k, v in stats.items()
        ]
        rows.append(
            {
                "statistic": f"{column}_n_nonnull",
                "rule": f"rows with a non-null {column}",
                "unit": unit,
                "value": float(s.len()),
            }
        )
        return rows

    def binary_rows(df, column, rule, unit):
        """`n` and `pct` for one boolean column, plus its non-null denominator.

        An all-null column (its source table absent at this site) yields n = null and
        pct = null, NOT zero. Publishing 0% for "this site does not chart CRRT" would be
        a clinical claim the data does not support (spec §4).
        """
        s = df.get_column(column)
        nonnull = s.drop_nulls()
        if nonnull.len() == 0:
            n, pct = None, None
        else:
            n = float(nonnull.sum())
            pct = round(100.0 * n / nonnull.len(), 2)
        return [
            {"statistic": f"{column}_n", "rule": rule, "unit": unit, "value": n},
            {"statistic": f"{column}_pct", "rule": rule, "unit": unit, "value": pct},
            {
                "statistic": f"{column}_n_nonnull",
                "rule": f"rows with a non-null {column}",
                "unit": unit,
                "value": float(nonnull.len()),
            },
        ]

    def categorical_rows(df, column, rule, unit, levels):
        """`n` and `pct` per level, over a FIXED level list.

        The level list is fixed rather than observed so a category absent at this site is
        published as an explicit zero instead of a missing row -- the same principle as
        `index_per_block.csv`'s contiguous n_index grid and Figure A.1's baseline
        diamonds. A missing row and a zero row are indistinguishable to a reader; only
        one of them is a measurement.

        Level names are bracketed -- `discharge_category[expired]_n` -- rather than
        joined with an underscore. That is not cosmetic. MIMIC's discharge_category
        vocabulary contains a level literally named `missing` AND one literally named
        `null`, so an underscore-joined `{column}_{level}_n` collides head-on with this
        function's own `{column}_missing_n` summary row: two different rows with one
        name, which then fans out the join on `statistic` in `build_table1` and
        silently corrupts every stratum column. Renaming the summary row would only
        move the problem, because any magic word can also be a category value. Brackets
        make the collision structurally impossible instead of merely unlikely.

        The same vocabulary makes the distinction worth preserving: this site charts the
        *string* `null` as a category value AND has genuinely absent values, and the two
        must stay separable in the published table.
        """
        total = df.get_column(column).drop_nulls().len()
        counts = dict(
            df.group_by(column).agg(pl.len().alias("n")).drop_nulls(column).iter_rows()
        )
        rows = []
        for level in levels:
            n = float(counts.get(level, 0))
            rows.append({"statistic": f"{column}[{level}]_n", "rule": rule, "unit": unit, "value": n})
            rows.append(
                {
                    "statistic": f"{column}[{level}]_pct",
                    "rule": rule,
                    "unit": unit,
                    "value": round(100.0 * n / total, 2) if total else None,
                }
            )
        rows.append(
            {
                "statistic": f"{column}_missing_n",
                "rule": f"rows with an absent (null) {column}, not the literal string",
                "unit": unit,
                "value": float(df.get_column(column).null_count()),
            }
        )
        return rows

    return binary_rows, categorical_rows, continuous_rows


@app.cell
def _(LOOKBACK_HOURS, binary_rows, categorical_rows, continuous_rows, pl):
    EVENT = "index event"
    BLOCK = "encounter block; repeated for each index event in the index-level table"

    def table1_rows(df, race_levels, ethnicity_levels, sex_levels, discharge_levels, table_unit, event_unit):
        """The full row inventory (spec §6), evaluated over whichever unit `df` carries.

        `table_unit` is the unit of THIS table's rows -- "encounter block" for the
        p_num = 1 view, "index event" for the full view. It is a parameter rather than a
        constant because `n_rows` counts exactly those rows, so hard-coding it labels the
        block table's 1,547 as index events. That is the one failure the `unit` column
        exists to prevent, so getting it wrong on the row that reports the table's own
        size would undermine every other row's label.

        `event_unit` is P35's whole purpose (FIX 3 of the 2026-08-12 final review): the
        unit stamped on the *substantive* per-event rows -- demographics, physiology,
        life support, evidence tier. It used to be the module constant EVENT
        unconditionally, which is correct for the index table (each row IS an index
        event) but wrong for the block table, where each row is measured at the block's
        p_num = 1 event and stands for the block. Publishing "index event" there made
        `table1_by_agent_block.csv`'s evidence_tier[1]_n = 1084 carry a unit that
        contradicts both `cpt_cascade.csv` (the identical 1,084 published as n_blocks)
        and this same file's own n_rows row (which already said "encounter block"). A
        unit column that is wrong is worse than no unit column at all, because a reader
        trusts it exactly where it lies.

        Block-level rows (LOS, mortality, n_index_in_block) are the mirror case: they
        keep BLOCK's "repeated for each index event" caveat in the index table, where
        it is exactly right, but in the block table they are not repeated -- one row IS
        one block -- so they take table_unit ("encounter block") there instead.
        """
        rows = []

        rows.append({"statistic": "n_rows", "rule": "rows in this table's unit", "unit": table_unit, "value": float(df.height)})
        rows.append({"statistic": "n_blocks", "rule": "distinct encounter_block", "unit": "encounter block", "value": float(df.get_column("encounter_block").n_unique())})
        # Patient granularity, not block: a patient can span more than one block, so this
        # is neither a block count nor repeated per index event.
        rows.append({"statistic": "n_patients", "rule": "distinct patient_id", "unit": "patient", "value": float(df.get_column("patient_id").n_unique())})

        # BLOCK in the index table (repeated per index event, as BLOCK's own string
        # says); table_unit in the block table, where these rows are not repeated.
        _block_unit = table_unit if table_unit == "encounter block" else BLOCK

        rows += continuous_rows(df, "age_at_admission", "hospitalization containing t0", event_unit)
        rows += categorical_rows(df, "sex_category", "patient.sex_category, lower-cased", event_unit, sex_levels)
        rows += categorical_rows(df, "race_category", "patient.race_category, lower-cased, raw mCIDE level", event_unit, race_levels)
        rows += categorical_rows(df, "ethnicity_category", "patient.ethnicity_category, lower-cased", event_unit, ethnicity_levels)

        rows += continuous_rows(df, "cci", "Charlson via clifpy on the hospitalization containing t0", event_unit)

        for _short, _dir in (("sbp", "lowest"), ("hr", "highest"), ("spo2", "lowest")):
            for _h in LOOKBACK_HOURS:
                _c = f"{_dir}_{_short}_{_h}h"
                rows += continuous_rows(df, _c, f"{_dir} vitals {_short} in [t0-{_h}h, t0]", event_unit)
        rows += continuous_rows(df, "weight_kg", "most recent vitals weight at or before t0", event_unit)

        for _prefix, _rule in (
            ("vasopressor", "any medication_admin_continuous vasopressor row in [t0-{h}h, t0]"),
            ("crrt", "any crrt_therapy recorded_dttm in [t0-{h}h, t0]"),
            ("prone", "any position prone row in [t0-{h}h, t0]"),
        ):
            for _h in LOOKBACK_HOURS:
                rows += binary_rows(df, f"{_prefix}_{_h}h", _rule.format(h=_h), event_unit)

        rows += binary_rows(df, "imv_transition", "device change onto imv within +/-60 min of t0 (sub-analysis D)", event_unit)
        rows += binary_rows(df, "any_sedative", "sedative charted within +/-60 min of t0 (sub-analysis E)", event_unit)
        rows += categorical_rows(df, "no_transition_reason", "why sub-analysis D found no transition", event_unit, ["already_on_imv", "no_transition_in_window", "no_device_record"])
        rows += categorical_rows(df, "location_at_index", "adt row where in_dttm <= t0 < out_dttm", event_unit, ["ed", "icu", "other", "unknown"])
        rows += categorical_rows(df, "evidence_tier", "1 index only, 2 +imv transition, 3 +imv +sedation (P31)", event_unit, [1, 2, 3])

        rows += binary_rows(df, "hospital_mortality", "death_dttm inside a member stay, or discharge_category expired", _block_unit)
        rows += binary_rows(df, "icu_mortality", "death_dttm inside an adt icu interval; independent of hospital_mortality (P37 amended)", _block_unit)
        rows += categorical_rows(df, "discharge_category", "hospitalization containing t0", event_unit, discharge_levels)
        rows += continuous_rows(df, "los_hospital_days", "sum of member hospitalization LOS in the block (P38)", _block_unit)
        rows += continuous_rows(df, "los_icu_days", "sum of adt icu intervals in the block", _block_unit)
        rows += continuous_rows(df, "n_index_in_block", "index paralytics in the block", _block_unit)

        return rows

    return BLOCK, EVENT, table1_rows


@app.cell
def _(PHI_DIR, SHARE_DIR, SITE, STRATA, pl, publish, table1_rows):
    index_covariates = pl.read_parquet(PHI_DIR / "index_covariates.parquet")

    # Level lists are taken from the WHOLE frame, not per stratum, so every stratum
    # column reports the same rows in the same order and the CSV can be read across.
    _race = sorted(index_covariates.get_column("race_category").drop_nulls().unique().to_list())
    _eth = sorted(index_covariates.get_column("ethnicity_category").drop_nulls().unique().to_list())
    _sex = sorted(index_covariates.get_column("sex_category").drop_nulls().unique().to_list())
    _disch = sorted(
        index_covariates.get_column("discharge_category").drop_nulls().unique().to_list()
    )

    _TABLE_UNIT = {"block": "encounter block", "index": "index event"}
    # FIX 3: the substantive per-event rows' unit. The block table's rows are measured
    # at the block's first index paralytic (p_num = 1), never repeated within the row --
    # so "index event" alone would understate what the row actually represents.
    _EVENT_UNIT = {
        "block": "encounter block (measured at the block's first index paralytic, p_num = 1)",
        "index": "index event",
    }

    def build_table1(df, label):
        _unit = _TABLE_UNIT[label]
        _event_unit = _EVENT_UNIT[label]
        _overall = pl.DataFrame(
            table1_rows(df, _race, _eth, _sex, _disch, _unit, _event_unit)
        ).rename({"value": "overall"})
        # `statistic` is the join key for every stratum column below, so a duplicate in
        # it fans the join out and corrupts the table rather than raising. Checked here,
        # with the offending names in the message, because the height assertion further
        # down reports only that something is wrong and not what.
        _dupes = (
            _overall.group_by("statistic")
            .agg(pl.len().alias("n"))
            .filter(pl.col("n") > 1)
            .sort("statistic")
        )
        assert _dupes.height == 0, (
            f"[{label}] the row inventory emits duplicate statistic names, which would "
            f"fan out the join on `statistic` and silently corrupt every stratum "
            f"column: {_dupes.to_dicts()}"
        )
        out = _overall
        for _stratum in STRATA:
            _sub = df.filter(pl.col("agent_stratum") == _stratum)
            _col = pl.DataFrame(
                table1_rows(_sub, _race, _eth, _sex, _disch, _unit, _event_unit)
            ).select("statistic", pl.col("value").alias(_stratum))
            assert _col.height == out.height, (
                f"stratum {_stratum} produced {_col.height} rows against the overall "
                f"column's {out.height} -- the row inventory is not stratum-invariant"
            )
            out = out.join(_col, on="statistic", how="left")
        out = (
            out.with_columns(pl.lit(SITE).alias("site_name"))
            .select("statistic", "rule", "unit", *STRATA, "overall", "site_name")
            # Full tiebreak so the file is byte-identical across runs (commit 6c70808).
            .sort(["statistic", "unit"])
        )
        publish(out, SHARE_DIR / f"table1_by_agent_{label}.csv", f"table1_by_agent_{label}")
        return out

    table1_index = build_table1(index_covariates, "index")
    table1_block = build_table1(index_covariates.filter(pl.col("p_num") == 1), "block")

    assert table1_block.height == table1_index.height, (
        "the two Table 1s have different row inventories and are not comparable"
    )
    print(f"block table n_rows : {table1_block.filter(pl.col('statistic') == 'n_rows')['overall'][0]:,.0f}")
    print(f"index table n_rows : {table1_index.filter(pl.col('statistic') == 'n_rows')['overall'][0]:,.0f}")
    return build_table1, index_covariates, table1_block, table1_index


@app.cell
def _(plt):
    def mark_zero(ax, x, color):
        """A published, exactly-zero value: a diamond centered on the baseline.

        Placed at y=0 in DATA coordinates, so it has zero data-height by construction and
        can never equal or exceed a bar of any positive height. `clip_on=False` keeps its
        lower half drawn. Copied from `02`/`03` rather than shared -- this project
        duplicates figure helpers deliberately (spec §4).
        """
        ax.plot(
            [x], [0], marker="D", markersize=7, color=color,
            linestyle="None", zorder=5, clip_on=False,
        )

    return (mark_zero,)


@app.cell
def _(FIG_DIR, LOOKBACK_HOURS, SHARE_DIR, mark_zero, pl, plt):
    # Fixed categorical colours, never cycled: one colour per life-support modality
    # wherever it appears.
    _COLORS = {"vasopressor": "#2a78d6", "crrt": "#eb6834", "prone": "#1baf7a"}

    _t1 = pl.read_csv(SHARE_DIR / "table1_by_agent_block.csv")

    _fig, _ax = plt.subplots(figsize=(10, 6))
    _width = 0.26

    for _i, (_modality, _color) in enumerate(_COLORS.items()):
        for _j, _h in enumerate(LOOKBACK_HOURS):
            _row = _t1.filter(pl.col("statistic") == f"{_modality}_{_h}h_pct")
            _v = _row["overall"][0] if _row.height else None
            _x = _j + (_i - 1) * _width
            if _v is None:
                # Source table absent at this site: null, not zero. Drawn as an open
                # marker ABOVE the baseline so it differs from the filled diamond that
                # means "measured, exactly 0" in POSITION as well as in shape -- shape
                # alone is a thin distinction to hang a structural-versus-clinical
                # reading on.
                #
                # The offset is in AXES coordinates via `get_xaxis_transform()` (x stays
                # in data coordinates, y becomes a 0-1 axes fraction), never a fraction
                # of the data range. A marker offset by a fraction of the frame's max is
                # the exact bug `mark_zero`'s docstring in `02_index_paralytic.py`
                # warns about: it stops being small relative to real bars as soon as
                # small bars exist. An axes-fraction offset is derived from no data at
                # all and so cannot drift with the frame.
                _ax.plot([_x], [0.03], marker="o", markersize=7, markerfacecolor="none",
                         color=_color, linestyle="None", clip_on=False,
                         transform=_ax.get_xaxis_transform())
            elif _v > 0:
                _ax.bar([_x], [_v], width=_width, color=_color)
            else:
                mark_zero(_ax, _x, _color)

    _ax.set_xticks(list(range(len(LOOKBACK_HOURS))))
    _ax.set_xticklabels([f"{_h} h before t0" for _h in LOOKBACK_HOURS])
    _ax.set_ylabel("% of encounter blocks")
    _ax.set_ylim(bottom=0)
    _ax.set_axisbelow(True)
    _ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)

    _handles = [_ax.plot([], [], color=_c, lw=6, label=_m)[0] for _m, _c in _COLORS.items()]
    _handles.append(_ax.plot([], [], marker="D", markersize=7, color="0.3", linestyle="None",
                             label="published zero (measured, exactly 0)")[0])
    _handles.append(_ax.plot([], [], marker="o", markersize=7, markerfacecolor="none",
                             color="0.3", linestyle="None",
                             label="source table absent (not measured)")[0])
    _ax.legend(handles=_handles, loc="upper left", fontsize=8, framealpha=0.9)
    _ax.set_title(
        "T.1 — life support before the index paralytic, encounter blocks\n"
        "the 1 h to 24 h ramp is where 'already shocked' separates from 'crashed at intubation'"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "T1_life_support_by_window.png", dpi=150)
    plt.close(_fig)
    print(f"T1_life_support_by_window.png -> {FIG_DIR}")
    return


@app.cell
def _(FIG_DIR, SHARE_DIR, pl, plt):
    _cov = pl.read_csv(SHARE_DIR / "covariate_coverage.csv").sort("source")

    _fig, _ax = plt.subplots(figsize=(9, 4.5))
    for _i, _row in enumerate(_cov.iter_rows(named=True)):
        _color = "#1baf7a" if _row["available"] else "#b0aca2"
        _ax.barh([_i], [_row["pct_blocks_covered"]], color=_color, height=0.6)
        # Three states here too, for the same reason T.1 has three. A zero-length bar
        # renders as nothing, so "table absent" and "table present but no analytic block
        # has a row in it" would otherwise be told apart only by what is NOT drawn --
        # and this is the one figure whose entire job is separating a structural zero
        # from a clinical one.
        if not _row["available"]:
            _ax.text(1, _i, "table absent at this site", va="center", fontsize=8, color="#0b0b0b")
        elif _row["pct_blocks_covered"] == 0:
            _ax.text(
                1, _i, "table present, no rows for these blocks",
                va="center", fontsize=8, color="#0b0b0b",
            )

    _ax.set_yticks(list(range(_cov.height)))
    _ax.set_yticklabels(_cov.get_column("source").to_list(), fontsize=9)
    _ax.set_xlabel("% of encounter blocks with at least one row in the source table")
    _ax.set_xlim(0, 100)
    _ax.invert_yaxis()
    _ax.set_axisbelow(True)
    _ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
    _ax.set_title(
        "T.2 — source-table coverage\n"
        "a covariate's zero means nothing until this figure says the table was there"
    )
    _fig.tight_layout()
    _fig.savefig(FIG_DIR / "T2_source_coverage.png", dpi=150)
    plt.close(_fig)
    print(f"T2_source_coverage.png -> {FIG_DIR}")
    return


if __name__ == "__main__":
    app.run()
