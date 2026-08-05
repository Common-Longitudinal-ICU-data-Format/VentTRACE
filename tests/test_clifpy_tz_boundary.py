"""Regression test for the clifpy timezone boundary.

clifpy returns timestamp columns carrying a **pytz** tzinfo object that is still in
its LMT (Local Mean Time) state:

    <DstTzInfo 'US/Eastern' LMT-1 day, 19:04:00 STD>

This is the classic pytz footgun. Calling `.dt.tz_localize(None)` on such a series
drops the offset that is *attached* rather than the offset that is *correct*, and the
resulting naive wall time is off by roughly an hour. `.dt.tz_convert(tz)` first
re-resolves the instant against the real tz database, so the naive value it produces
is right.

The two paths do not error, do not warn, and differ by exactly one hour — so mixing
them inside one pipeline silently misaligns every window computed across the two
frames. `01_cohort.py` did exactly that: `resp_raw` used path A while the waterfall
path used path B, which put the raw-vs-waterfall QC comparison an hour out.

RULE: never call `.dt.tz_localize(None)` directly on a clifpy column.
Always `.dt.tz_convert(TIMEZONE).dt.tz_localize(None)`.

Run:  uv run python tests/test_clifpy_tz_boundary.py
"""

import json
from pathlib import Path

import pandas as pd

from clifpy.tables import RespiratorySupport

CONFIG = json.loads((Path(__file__).parent.parent / "config" / "config.json").read_text())
TIMEZONE = CONFIG["timezone"]


def to_site_naive(series: pd.Series, timezone: str = TIMEZONE) -> pd.Series:
    """The only correct way to get a naive site-local timestamp out of clifpy."""
    return series.dt.tz_convert(timezone).dt.tz_localize(None)


def test_naive_paths_disagree_and_convert_is_correct():
    """Pin the bug: the two paths differ, and tz_convert is the one that matches UTC."""
    table = RespiratorySupport.from_file(
        data_directory=CONFIG["data_directory"],
        filetype=CONFIG["filetype"],
        timezone=TIMEZONE,
        columns=["hospitalization_id", "recorded_dttm", "device_category"],
        filters={"hospitalization_id": ["25598069"]},
    )
    s = table.df["recorded_dttm"]
    assert len(s) > 0, "fixture hospitalization returned no rows"

    path_a = s.dt.tz_localize(None)          # WRONG — drops the pytz LMT offset
    path_b = to_site_naive(s)                # RIGHT — re-resolves against the tz database

    # 1. The two paths disagree. If this ever stops being true, clifpy fixed its
    #    tzinfo handling and the workaround below can be simplified.
    delta_hours = (path_b - path_a).dt.total_seconds().div(3600).unique()
    assert len(delta_hours) == 1 and delta_hours[0] != 0, (
        f"expected a constant nonzero offset between the two paths, got {delta_hours}"
    )
    print(f"paths differ by {delta_hours[0]:+.0f} h  (tz object: {s.dt.tz!r})")

    # 2. tz_convert is the correct one: reinterpreting its output in the site
    #    timezone must reproduce the original UTC instant exactly.
    utc = s.dt.tz_convert("UTC")
    roundtrip = path_b.dt.tz_localize(TIMEZONE).dt.tz_convert("UTC")
    assert roundtrip.equals(utc), "tz_convert path does not round-trip to the original instant"

    # 3. ...and tz_localize(None) is not.
    bad_roundtrip = path_a.dt.tz_localize(TIMEZONE).dt.tz_convert("UTC")
    assert not bad_roundtrip.equals(utc), (
        "tz_localize(None) unexpectedly round-tripped; the bug may be fixed upstream"
    )
    print("confirmed: tz_convert round-trips, tz_localize(None) does not")


if __name__ == "__main__":
    test_naive_paths_disagree_and_convert_is_correct()
    print("PASS")
