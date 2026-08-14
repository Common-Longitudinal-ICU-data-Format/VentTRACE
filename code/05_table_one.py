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
    from utils.suppress import publish, publish_json

    return Path, json, mo, pl, plt, publish, publish_json


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

        Each unit is published in **three** forms from one row inventory (P39):

        | file | for | shape |
        |---|---|---|
        | `table1_by_agent_{unit}.csv` | the pipeline and its tests | long, one statistic per row, numeric |
        | `table1_by_agent_{unit}_readable.csv` | a human, a manuscript | one variable per row, `63.2 (16.4)` |
        | `table1_by_agent_{unit}.json` | pooling with other sites | the long form plus a provenance header |

        The readable CSV is formatted **from** the long one and never recomputed, so the
        three can restate a number but cannot disagree about it. The JSON keeps the
        numbers as numbers: a partner pooling `63.2 (16.4)` would have to parse the
        string back apart first, and string parsing is where sites diverge.

        Proning was withdrawn from the covariate set on 2026-08-14 at the study lead's
        direction, so no `position` row appears here and `04` no longer opens the table.

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
        (a site without `crrt_therapy` has null CRRT flags but real ages) and a Table 1 that
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

        Returns `(rows, display)` (P39). `rows` is the long numeric inventory that the
        machine-readable CSV and the aggregation JSON both carry. `display` is the
        human layout: one entry per printed line, naming the group it belongs to, the
        label a reader sees, and the `rows` statistics that line is formatted FROM.

        The two are built together, in one pass, at one call site per variable --
        never as two independent lists that happen to describe the same variables.
        A display list maintained separately from the row inventory drifts the first
        time a variable is added to one and not the other, and the failure is silent:
        the readable table simply omits a row nobody notices is missing. Here a
        variable that is not emitted cannot be displayed, and a display line whose
        statistic does not exist raises in `build_readable`.
        """
        rows, display = [], []

        COHORT = "cohort"
        DEMOG = "demographics"
        COMORB = "comorbidity"
        PHYS = "physiology before the index paralytic"
        LIFE = "life support before the index paralytic"
        CONTEXT = "intubation context"
        OUTCOME = "outcomes"

        def _row(statistic, rule, unit, value):
            rows.append({"statistic": statistic, "rule": rule, "unit": unit, "value": value})

        def _show(group, variable, fmt, keys, rule, unit, digits=1):
            display.append(
                {
                    "group": group,
                    "variable": variable,
                    "fmt": fmt,
                    "keys": keys,
                    "digits": digits,
                    "rule": rule,
                    "unit": unit,
                }
            )

        def _count(statistic, group, label, rule, unit, value):
            _row(statistic, rule, unit, value)
            _show(group, f"{label}, n", "count", [statistic], rule, unit, digits=0)

        def _cont(column, group, label, rule, unit, digits=1):
            rows.extend(continuous_rows(df, column, rule, unit))
            _show(group, f"{label} — mean (SD)", "mean_sd",
                  [f"{column}_mean", f"{column}_sd"], rule, unit, digits)
            _show(group, f"{label} — median [Q1, Q3]", "median_iqr",
                  [f"{column}_median", f"{column}_q1", f"{column}_q3"], rule, unit, digits)
            _show(group, f"{label} — missing, n", "missing",
                  ["n_rows", f"{column}_n_nonnull"],
                  f"rows with no {column}", unit, digits=0)

        def _bin(column, group, label, rule, unit):
            rows.extend(binary_rows(df, column, rule, unit))
            _show(group, f"{label} — n (%)", "n_pct",
                  [f"{column}_n", f"{column}_pct"], rule, unit, digits=0)
            _show(group, f"{label} — missing, n", "missing",
                  ["n_rows", f"{column}_n_nonnull"],
                  f"rows with no {column}", unit, digits=0)

        def _cat(column, group, label, rule, unit, levels):
            rows.extend(categorical_rows(df, column, rule, unit, levels))
            for _level in levels:
                # The level is printed exactly as it is stored, never prettified. A
                # displayed label that does not match the mCIDE value it counts is how a
                # reader ends up unable to find the level in the data, and the casing
                # rules here are P20's, not English's.
                _show(group, f"{label} — {_level}, n (%)", "n_pct",
                      [f"{column}[{_level}]_n", f"{column}[{_level}]_pct"], rule, unit, digits=0)
            _show(group, f"{label} — missing, n", "count", [f"{column}_missing_n"],
                  f"rows with an absent (null) {column}, not the literal string", unit, digits=0)

        _count("n_rows", COHORT, f"Total {table_unit}s", "rows in this table's unit", table_unit, float(df.height))
        _count("n_blocks", COHORT, "Distinct encounter blocks", "distinct encounter_block", "encounter block", float(df.get_column("encounter_block").n_unique()))
        # Patient granularity, not block: a patient can span more than one block, so this
        # is neither a block count nor repeated per index event.
        _count("n_patients", COHORT, "Distinct patients", "distinct patient_id", "patient", float(df.get_column("patient_id").n_unique()))

        # BLOCK in the index table (repeated per index event, as BLOCK's own string
        # says); table_unit in the block table, where these rows are not repeated.
        _block_unit = table_unit if table_unit == "encounter block" else BLOCK

        _cont("age_at_admission", DEMOG, "Age at admission, years", "hospitalization containing t0", event_unit)
        _cat("sex_category", DEMOG, "Sex", "patient.sex_category, lower-cased", event_unit, sex_levels)
        _cat("race_category", DEMOG, "Race", "patient.race_category, lower-cased, raw mCIDE level", event_unit, race_levels)
        _cat("ethnicity_category", DEMOG, "Ethnicity", "patient.ethnicity_category, lower-cased", event_unit, ethnicity_levels)

        _cont("cci", COMORB, "Charlson comorbidity index", "Charlson via clifpy on the hospitalization containing t0", event_unit)

        for _short, _dir, _label, _units in (
            ("sbp", "lowest", "Lowest systolic blood pressure", "mmHg"),
            ("hr", "highest", "Highest heart rate", "bpm"),
            ("spo2", "lowest", "Lowest SpO2", "%"),
        ):
            for _h in LOOKBACK_HOURS:
                _c = f"{_dir}_{_short}_{_h}h"
                _cont(_c, PHYS, f"{_label} within {_h} h before, {_units}",
                      f"{_dir} vitals {_short} in [t0-{_h}h, t0]", event_unit)
        _cont("weight_kg", PHYS, "Weight, kg", "most recent vitals weight at or before t0", event_unit)

        for _prefix, _label, _rule in (
            ("vasopressor", "Vasopressor", "any medication_admin_continuous vasopressor row in [t0-{h}h, t0]"),
            ("crrt", "CRRT", "any crrt_therapy recorded_dttm in [t0-{h}h, t0]"),
        ):
            for _h in LOOKBACK_HOURS:
                _bin(f"{_prefix}_{_h}h", LIFE, f"{_label} within {_h} h before",
                     _rule.format(h=_h), event_unit)

        _bin("imv_transition", CONTEXT, "New transition onto IMV at the index paralytic", "device change onto imv within +/-60 min of t0 (sub-analysis D)", event_unit)
        _bin("any_sedative", CONTEXT, "Sedative within +/-60 min of the index paralytic", "sedative charted within +/-60 min of t0 (sub-analysis E)", event_unit)
        _cat("no_transition_reason", CONTEXT, "Reason no IMV transition was found", "why sub-analysis D found no transition", event_unit, ["already_on_imv", "no_transition_in_window", "no_device_record"])
        _cat("location_at_index", CONTEXT, "Location at the index paralytic", "adt row where in_dttm <= t0 < out_dttm", event_unit, ["ed", "icu", "other", "unknown"])
        _cat("evidence_tier", CONTEXT, "Evidence tier", "1 index only, 2 +imv transition, 3 +imv +sedation (P31)", event_unit, [1, 2, 3])

        _bin("hospital_mortality", OUTCOME, "Hospital mortality", "death_dttm inside a member stay, or discharge_category expired", _block_unit)
        _bin("icu_mortality", OUTCOME, "ICU mortality", "death_dttm inside an adt icu interval; independent of hospital_mortality (P37 amended)", _block_unit)
        _cat("discharge_category", OUTCOME, "Discharge disposition", "hospitalization containing t0", event_unit, discharge_levels)
        _cont("los_hospital_days", OUTCOME, "Hospital length of stay, days", "sum of member hospitalization LOS in the block (P38)", _block_unit)
        _cont("los_icu_days", OUTCOME, "ICU length of stay, days", "sum of adt icu intervals in the block", _block_unit)
        _cont("n_index_in_block", OUTCOME, "Index paralytics in the block", "index paralytics in the block", _block_unit)

        return rows, display

    return BLOCK, EVENT, table1_rows


@app.cell
def _(pl):
    def format_stat(fmt, values, digits):
        """One display line's numbers -> the string a human reads (P39).

        `NA` means *not measured*: the statistic is null because the column is null,
        which at this site means the source table was absent. It is never a zero. A
        measured zero prints as `0` or `0 (0.0%)`, and keeping the two typographically
        distinct in the readable table is the same distinction `covariate_coverage.csv`
        and Figure T.2 exist to make -- a reader who cannot tell "this site does not
        chart CRRT" from "no patient had CRRT" has been handed a clinical finding that
        is really a data-availability one.

        Thousands separators throughout: these tables are read at a glance and `1547`
        and `15470` are one keystroke apart by eye.
        """
        def _f(v, d):
            return f"{v:,.{d}f}"

        if fmt == "count":
            _v = values[0]
            return "NA" if _v is None else _f(_v, 0)
        if fmt == "mean_sd":
            _m, _sd = values
            if _m is None:
                return "NA"
            # A single non-null observation has a mean and no SD. Printing the mean with
            # `(NA)` beside it says exactly that; dropping the whole line would hide a
            # real measurement, and printing `(0.0)` would invent a dispersion.
            return f"{_f(_m, digits)} ({'NA' if _sd is None else _f(_sd, digits)})"
        if fmt == "median_iqr":
            _md, _q1, _q3 = values
            # All three come from the same `drop_nulls` pass, so they are null together
            # or present together -- checked rather than assumed, because a partial
            # triple would otherwise crash here with a TypeError three files from the
            # statistic that produced it.
            if _md is None or _q1 is None or _q3 is None:
                return "NA"
            return f"{_f(_md, digits)} [{_f(_q1, digits)}, {_f(_q3, digits)}]"
        if fmt == "n_pct":
            _n, _pct = values
            if _n is None:
                return "NA"
            # A count with no percentage is a real and separate state: `categorical_rows`
            # returns pct = null when the level's denominator is zero, which is what an
            # empty stratum column looks like -- succinylcholine is absent from MIMIC
            # entirely, so every one of its levels is 0 out of 0. `0 (NA)` says that the
            # count was measured and the proportion is undefined. `0 (0.0%)` would claim
            # a proportion computed on no one.
            if _pct is None:
                return f"{_f(_n, 0)} (NA)"
            return f"{_f(_n, 0)} ({_f(_pct, 1)}%)"
        if fmt == "missing":
            _total, _nonnull = values
            if _total is None or _nonnull is None:
                return "NA"
            return _f(_total - _nonnull, 0)
        raise ValueError(f"unknown display format {fmt!r}")

    def build_readable(long_df, display, value_columns):
        """The human table, formatted FROM the published long table (P39).

        `long_df` is exactly what `table1_by_agent_{unit}.csv` carries; every number
        here is looked up out of it and formatted, never recomputed from the analytic
        frame. Two tables that recompute the same quantity can disagree; two tables
        where one is a rendering of the other cannot.

        A display line naming a statistic the inventory did not emit raises rather than
        printing `NA`. `NA` is a published claim -- "this was not measured" -- and a
        typo in a key is not that claim.
        """
        lookup = {r["statistic"]: r for r in long_df.to_dicts()}
        out = []
        for _i, _d in enumerate(display):
            _absent = [k for k in _d["keys"] if k not in lookup]
            assert not _absent, (
                f"display line {_d['variable']!r} reads statistic(s) {_absent} that the "
                f"row inventory never emitted"
            )
            _rec = {"row_order": _i, "group": _d["group"], "variable": _d["variable"]}
            for _c in value_columns:
                _rec[_c] = format_stat(
                    _d["fmt"], [lookup[k][_c] for k in _d["keys"]], _d["digits"]
                )
            _rec["rule"] = _d["rule"]
            _rec["unit"] = _d["unit"]
            out.append(_rec)
        return pl.DataFrame(out)

    return build_readable, format_stat


@app.cell
def _(
    PHI_DIR,
    SHARE_DIR,
    SITE,
    STRATA,
    build_readable,
    pl,
    publish,
    publish_json,
    table1_rows,
):
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

    # The readable table's columns, overall first: a reader compares each drug against
    # the whole cohort, so the reference column belongs on the left. The long CSV keeps
    # its existing order (strata, then overall) -- it is a join target with a pinned
    # column list and reordering it would churn every consumer for no reader's benefit.
    _VALUE_COLUMNS = ["overall", *STRATA]

    def build_table1(df, label):
        _unit = _TABLE_UNIT[label]
        _event_unit = _EVENT_UNIT[label]
        _rows, _display = table1_rows(df, _race, _eth, _sex, _disch, _unit, _event_unit)
        _overall = pl.DataFrame(_rows).rename({"value": "overall"})
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
            # The display layout is stratum-invariant by construction, so only the
            # overall pass's copy is kept; a stratum's would be identical.
            _stratum_rows, _ = table1_rows(_sub, _race, _eth, _sex, _disch, _unit, _event_unit)
            _col = pl.DataFrame(_stratum_rows).select(
                "statistic", pl.col("value").alias(_stratum)
            )
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

        # The same table for a person. `row_order` is the layout, so the file survives a
        # spreadsheet's re-sort: without it the only ordering is alphabetical by label,
        # which interleaves the groups and puts "Age" between "ICU mortality" and
        # "Location". It is also the tiebreak that keeps the file byte-identical across
        # runs (commit 6c70808), since `variable` alone is unique but not stable to edit.
        _readable = (
            build_readable(out, _display, _VALUE_COLUMNS)
            .with_columns(pl.lit(SITE).alias("site_name"))
            .select("row_order", "group", "variable", *_VALUE_COLUMNS, "rule", "unit", "site_name")
            .sort("row_order")
        )
        publish(
            _readable,
            SHARE_DIR / f"table1_by_agent_{label}_readable.csv",
            f"table1_by_agent_{label}_readable",
        )

        # The same table for another site's merge script. `cohort_run_id` travels with
        # it so a pooled file can be traced back to the run that produced each part, and
        # `unit` travels with it so a block-level table can never be silently stacked on
        # an index-level one -- the two have identical row inventories and different
        # denominators, which is exactly the pair that merges without complaint and
        # produces a wrong number.
        _run_ids = df.get_column("cohort_run_id").unique().to_list()
        assert len(_run_ids) == 1, (
            f"[{label}] the analytic frame carries {len(_run_ids)} cohort_run_ids; a "
            f"provenance stamp that is not single-valued cannot be published as one"
        )
        publish_json(
            out,
            SHARE_DIR / f"table1_by_agent_{label}.json",
            f"table1_by_agent_{label}_json",
            {
                "schema": "venttrace/table1/1",
                "site_name": SITE,
                "cohort_run_id": _run_ids[0],
                "table": f"table1_by_agent_{label}",
                "unit": _unit,
                "event_unit": _event_unit,
                "source": "index_covariates.parquet",
                "strata": STRATA,
                "value_columns": ["overall", *STRATA],
                "n_rows": float(df.height),
            },
        )
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
    # Proning was withdrawn from the covariate set on 2026-08-14; two modalities remain.
    _COLORS = {"vasopressor": "#2a78d6", "crrt": "#eb6834"}

    _t1 = pl.read_csv(SHARE_DIR / "table1_by_agent_block.csv")

    _fig, _ax = plt.subplots(figsize=(10, 6))
    _width = 0.26

    for _i, (_modality, _color) in enumerate(_COLORS.items()):
        for _j, _h in enumerate(LOOKBACK_HOURS):
            _row = _t1.filter(pl.col("statistic") == f"{_modality}_{_h}h_pct")
            _v = _row["overall"][0] if _row.height else None
            # Centred on the tick for however many modalities there are, rather than
            # the literal -1 that only centred three. Dropping proning would otherwise
            # have shifted both remaining bars a third of a slot to the left of their
            # own tick, with nothing on the figure to say it had happened.
            _x = _j + (_i - (len(_COLORS) - 1) / 2) * _width
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
