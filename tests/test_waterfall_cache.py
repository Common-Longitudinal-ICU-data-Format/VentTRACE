"""Regression tests for the resumable respiratory-waterfall cache."""

import ast
import hashlib
import json
import uuid
from pathlib import Path

import pandas as pd
import polars as pl
from clifpy.tables import RespiratorySupport
from clifpy.utils.waterfall import process_resp_support_waterfall


ROOT = Path(__file__).parent.parent
COHORT_NOTEBOOK = ROOT / "code" / "01_cohort.py"
CONFIG = json.loads((ROOT / "config" / "config.json").read_text())


def _load_function(name):
    tree = ast.parse(COHORT_NOTEBOOK.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, f"expected one {name}"
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "hashlib": hashlib,
        "json": json,
        "pd": pd,
        "uuid": uuid,
    }
    exec(compile(module, str(COHORT_NOTEBOOK), "exec"), namespace)
    return namespace[name]


waterfall_input_digests = _load_function("waterfall_input_digests")
valid_waterfall_cache_entries = _load_function("valid_waterfall_cache_entries")
write_parquet_atomic = _load_function("write_parquet_atomic")


def test_input_digest_invalidates_only_changed_hospitalization():
    frame = pd.DataFrame(
        {
            "hospitalization_id": ["a", "a", "b"],
            "recorded_dttm": pd.to_datetime(
                ["2026-01-01 00:00Z", "2026-01-01 01:00Z", "2026-01-02 00:00Z"],
                utc=True,
            ),
            "device_category": ["room air", "imv", "room air"],
        }
    )
    before = waterfall_input_digests(frame)
    frame.loc[0, "device_category"] = "nasal cannula"
    after = waterfall_input_digests(frame)

    assert before["a"] != after["a"]
    assert before["b"] == after["b"]


def test_cache_entry_requires_current_digest_and_intact_shard():
    source = {"a": "digest-a", "b": "digest-b", "c": "digest-c"}
    entries = {
        "a": {"digest": "digest-a", "shard": "valid.parquet"},
        "b": {"digest": "stale", "shard": "valid.parquet"},
        "c": {"digest": "digest-c", "shard": "corrupt.parquet"},
        "old": {"digest": "digest-old", "shard": "valid.parquet"},
    }
    assert valid_waterfall_cache_entries(
        source, entries, {"valid.parquet"}
    ) == {"a": entries["a"]}


def test_atomic_parquet_write_leaves_only_completed_destination(tmp_path):
    destination = tmp_path / "cache.parquet"
    expected = pl.DataFrame({"hospitalization_id": ["a"], "value": [1]})
    write_parquet_atomic(expected, destination)

    assert pl.read_parquet(destination).equals(expected)
    assert list(tmp_path.iterdir()) == [destination]


def test_partitioned_waterfall_preserves_device_category_projection():
    sample = RespiratorySupport.from_file(
        data_directory=CONFIG["data_directory"],
        filetype=CONFIG["filetype"],
        timezone=CONFIG["timezone"],
        columns=["hospitalization_id"],
        sample_size=100,
    )
    hospitalization_ids = sample.df["hospitalization_id"].dropna().unique()[:2].tolist()
    assert len(hospitalization_ids) == 2
    table = RespiratorySupport.from_file(
        data_directory=CONFIG["data_directory"],
        filetype=CONFIG["filetype"],
        timezone=CONFIG["timezone"],
        filters={"hospitalization_id": hospitalization_ids},
    ).df
    table = table.assign(recorded_dttm=table["recorded_dttm"].dt.tz_convert("UTC"))

    monolithic = process_resp_support_waterfall(
        table.copy(), id_col="hospitalization_id", bfill=True, verbose=False
    )
    partitioned = pd.concat(
        [
            process_resp_support_waterfall(
                group.copy(), id_col="hospitalization_id", bfill=True, verbose=False
            )
            for _, group in table.groupby("hospitalization_id", sort=False)
        ],
        ignore_index=True,
    )
    columns = ["hospitalization_id", "recorded_dttm", "device_category"]
    monolithic = monolithic[columns].sort_values(columns, kind="stable").reset_index(drop=True)
    partitioned = partitioned[columns].sort_values(columns, kind="stable").reset_index(drop=True)
    pd.testing.assert_frame_equal(monolithic, partitioned)
