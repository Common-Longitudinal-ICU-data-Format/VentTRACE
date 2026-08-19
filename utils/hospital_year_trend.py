"""Render the shareable hospital-level yearly event trend."""

from pathlib import Path

import polars as pl


def render_hospital_year_trend(frame: pl.DataFrame, destination: Path) -> bool:
    """Write Figure H.1, returning false when an empty source has no figure."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if frame.is_empty():
        destination.unlink(missing_ok=True)
        return False

    colors = {
        "academic": "#2a78d6",
        "non-academic": "#d56b2a",
        "unknown": "#777777",
    }
    markers = ["o", "s", "^", "D", "v", "P", "X", "<", ">"]
    years = list(
        range(
            int(frame.get_column("calendar_year").min()),
            int(frame.get_column("calendar_year").max()) + 1,
        )
    )
    groups = (
        frame.select("hospital", "academic_status")
        .unique()
        .sort(["academic_status", "hospital"])
        .rows()
    )
    figure, axis = plt.subplots(figsize=(11.5, max(5.8, 4.8 + 0.18 * len(groups))))
    for index, (hospital, status) in enumerate(groups):
        part = frame.filter(
            (pl.col("hospital") == hospital) & (pl.col("academic_status") == status)
        )
        counts = dict(
            zip(
                part.get_column("calendar_year").to_list(),
                part.get_column("n_intubations").to_list(),
            )
        )
        axis.plot(
            years,
            [counts.get(year, 0) for year in years],
            color=colors.get(status, colors["unknown"]),
            marker=markers[index % len(markers)],
            linewidth=2,
            markersize=5,
            label=f"{hospital} ({status})",
        )

    site = frame.get_column("healthcare_system").first()
    total = int(frame.get_column("n_intubations").sum())
    axis.set_title(
        f"H.1 - Yearly intubation-adjacent events by hospital | {site}\n"
        f"One block-first VentTRACE paralytic-index event per encounter block; N = {total:,}\n"
        "Latest displayed year may be incomplete based on local extract coverage",
        loc="left",
        fontsize=11,
    )
    axis.set_xlabel("Calendar year")
    axis.set_ylabel("Block-first events")
    axis.set_xticks(years)
    axis.set_ylim(bottom=0)
    axis.grid(axis="y", color="#e1e0d9", linewidth=0.8)
    axis.set_axisbelow(True)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    axis.legend(
        title="Event-time hospital (ADT type)",
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
        frameon=False,
        fontsize=8,
    )
    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    plt.close(figure)
    return True
