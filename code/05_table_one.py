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

    def table1_rows(df, race_levels, ethnicity_levels, sex_levels, discharge_levels, table_unit):
        """The full row inventory (spec §6), evaluated over whichever unit `df` carries.

        `table_unit` is the unit of THIS table's rows -- "encounter block" for the
        p_num = 1 view, "index event" for the full view. It is a parameter rather than a
        constant because `n_rows` counts exactly those rows, so hard-coding it labels the
        block table's 1,547 as index events. That is the one failure the `unit` column
        exists to prevent, so getting it wrong on the row that reports the table's own
        size would undermine every other row's label.
        """
        rows = []

        rows.append({"statistic": "n_rows", "rule": "rows in this table's unit", "unit": table_unit, "value": float(df.height)})
        rows.append({"statistic": "n_blocks", "rule": "distinct encounter_block", "unit": "encounter block", "value": float(df.get_column("encounter_block").n_unique())})
        # Patient granularity, not block: a patient can span more than one block, so this
        # is neither a block count nor repeated per index event.
        rows.append({"statistic": "n_patients", "rule": "distinct patient_id", "unit": "patient", "value": float(df.get_column("patient_id").n_unique())})

        rows += continuous_rows(df, "age_at_admission", "hospitalization containing t0", EVENT)
        rows += categorical_rows(df, "sex_category", "patient.sex_category, lower-cased", EVENT, sex_levels)
        rows += categorical_rows(df, "race_category", "patient.race_category, lower-cased, raw mCIDE level", EVENT, race_levels)
        rows += categorical_rows(df, "ethnicity_category", "patient.ethnicity_category, lower-cased", EVENT, ethnicity_levels)

        rows += continuous_rows(df, "cci", "Charlson via clifpy on the hospitalization containing t0", EVENT)

        for _short, _dir in (("sbp", "lowest"), ("hr", "highest"), ("spo2", "lowest")):
            for _h in LOOKBACK_HOURS:
                _c = f"{_dir}_{_short}_{_h}h"
                rows += continuous_rows(df, _c, f"{_dir} vitals {_short} in [t0-{_h}h, t0]", EVENT)
        rows += continuous_rows(df, "weight_kg", "most recent vitals weight at or before t0", EVENT)

        for _prefix, _rule in (
            ("vasopressor", "any medication_admin_continuous vasopressor row in [t0-{h}h, t0]"),
            ("crrt", "any crrt_therapy recorded_dttm in [t0-{h}h, t0]"),
            ("prone", "any position prone row in [t0-{h}h, t0]"),
        ):
            for _h in LOOKBACK_HOURS:
                rows += binary_rows(df, f"{_prefix}_{_h}h", _rule.format(h=_h), EVENT)

        rows += binary_rows(df, "imv_transition", "device change onto imv within +/-60 min of t0 (sub-analysis D)", EVENT)
        rows += binary_rows(df, "any_sedative", "sedative charted within +/-60 min of t0 (sub-analysis E)", EVENT)
        rows += categorical_rows(df, "no_transition_reason", "why sub-analysis D found no transition", EVENT, ["already_on_imv", "no_transition_in_window", "no_device_record"])
        rows += categorical_rows(df, "location_at_index", "adt row where in_dttm <= t0 < out_dttm", EVENT, ["ed", "icu", "other", "unknown"])
        rows += categorical_rows(df, "evidence_tier", "1 index only, 2 +imv transition, 3 +imv +sedation (P31)", EVENT, [1, 2, 3])

        rows += binary_rows(df, "hospital_mortality", "death_dttm inside a member stay, or discharge_category expired", BLOCK)
        rows += binary_rows(df, "icu_mortality", "death_dttm inside an adt icu interval; independent of hospital_mortality (P37 amended)", BLOCK)
        rows += categorical_rows(df, "discharge_category", "hospitalization containing t0", EVENT, discharge_levels)
        rows += continuous_rows(df, "los_hospital_days", "sum of member hospitalization LOS in the block (P38)", BLOCK)
        rows += continuous_rows(df, "los_icu_days", "sum of adt icu intervals in the block", BLOCK)
        rows += continuous_rows(df, "n_index_in_block", "index paralytics in the block", BLOCK)

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

    def build_table1(df, label):
        _unit = _TABLE_UNIT[label]
        _overall = pl.DataFrame(
            table1_rows(df, _race, _eth, _sex, _disch, _unit)
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
                table1_rows(_sub, _race, _eth, _sex, _disch, _unit)
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


if __name__ == "__main__":
    app.run()
