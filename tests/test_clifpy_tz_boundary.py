"""Regression tests for the clifpy and respiratory-waterfall timezone boundaries.

clifpy normalizes every `*_dttm` column to the configured site timezone. The analytic
pipeline then strips that timezone without another conversion so calculations use the
site-local wall clock. The respiratory waterfall is the deliberate exception: its input
contract is UTC, it creates UTC scaffold rows, and its output remains UTC. Notebook 01
therefore converts to UTC before the call, then converts back to the site timezone before
stripping.

Run:  uv run pytest tests/test_clifpy_tz_boundary.py
"""

import json
from pathlib import Path

import pandas as pd

from clifpy.tables import RespiratorySupport
from clifpy.utils.waterfall import process_resp_support_waterfall

CONFIG = json.loads((Path(__file__).parent.parent / "config" / "config.json").read_text())
TIMEZONE = CONFIG["timezone"]


def to_site_naive(series: pd.Series) -> pd.Series:
    """Strip clifpy's configured site timezone without shifting wall time."""
    return series.dt.tz_localize(None)


def test_clifpy_strip_and_waterfall_utc_roundtrip():
    fixture = RespiratorySupport.from_file(
        data_directory=CONFIG["data_directory"],
        filetype=CONFIG["filetype"],
        timezone=TIMEZONE,
        columns=["hospitalization_id"],
        sample_size=1,
    )
    assert not fixture.df.empty, "configured respiratory_support table is empty"
    fixture_hospitalization_id = fixture.df["hospitalization_id"].iloc[0]

    table = RespiratorySupport.from_file(
        data_directory=CONFIG["data_directory"],
        filetype=CONFIG["filetype"],
        timezone=TIMEZONE,
        filters={"hospitalization_id": [fixture_hospitalization_id]},
    )
    local = table.df["recorded_dttm"]
    assert len(local) > 0, "fixture hospitalization returned no rows"
    assert str(local.dt.tz) == TIMEZONE, (
        f"clifpy returned {local.dt.tz!s}, expected configured site timezone {TIMEZONE}"
    )

    local_naive = to_site_naive(local)
    assert local_naive.dt.strftime("%Y-%m-%d %H:%M:%S.%f").equals(
        local.dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    ), "stripping the timezone changed clifpy's site-local wall clock"

    resp_utc = table.df.copy()
    resp_utc["recorded_dttm"] = resp_utc["recorded_dttm"].dt.tz_convert("UTC")
    waterfalled = process_resp_support_waterfall(resp_utc, verbose=False)
    assert str(waterfalled["recorded_dttm"].dt.tz) == "UTC", (
        "the respiratory waterfall did not preserve its documented UTC time base"
    )

    waterfall_local_naive = (
        waterfalled["recorded_dttm"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
    )
    waterfall_real = pd.DataFrame(
        {
            "hospitalization_id": waterfalled["hospitalization_id"],
            "recorded_dttm": waterfall_local_naive,
        }
    )
    waterfall_real = waterfall_real.loc[
        waterfall_real["recorded_dttm"].dt.second != 59
    ].drop_duplicates()
    raw = pd.DataFrame(
        {
            "hospitalization_id": table.df["hospitalization_id"],
            "recorded_dttm": local_naive,
        }
    ).drop_duplicates()
    orphans = waterfall_real.merge(
        raw,
        on=["hospitalization_id", "recorded_dttm"],
        how="left",
        indicator=True,
    )
    orphans = orphans.loc[orphans["_merge"] == "left_only"]
    assert orphans.empty, (
        f"{len(orphans):,} non-scaffold waterfall rows failed the UTC-to-site round trip"
    )


if __name__ == "__main__":
    test_clifpy_strip_and_waterfall_utc_roundtrip()
    print("PASS")
