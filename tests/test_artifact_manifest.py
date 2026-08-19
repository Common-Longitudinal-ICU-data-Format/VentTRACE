"""Audit controls for the generated shareable artifact inventory."""

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config" / "config.json"


def _share_dir():
    with open(CONFIG) as file:
        config = json.load(file)
    output = Path(config["output_directory"])
    if not output.is_absolute():
        output = ROOT / output
    return output / "final_no_phi"


@pytest.fixture(scope="module")
def manifest():
    path = _share_dir() / "artifact_manifest.csv"
    if not path.exists():
        pytest.skip("artifact_manifest.csv absent; run the full pipeline first")
    return pl.read_csv(path)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_manifest_has_unique_complete_inventory(manifest):
    assert manifest.get_column("filename").is_unique().all()
    assert manifest.get_column("artifact_id").is_unique().all()
    assert manifest.filter(pl.col("status") == "missing").height == 0
    assert manifest.height == 54


def test_declared_source_artifacts_exist(manifest):
    output = _share_dir().parent
    for source_files in manifest.get_column("source_files"):
        for source in source_files.split("|"):
            assert (output / source).exists(), source


def test_generated_artifact_hashes_match(manifest):
    share = _share_dir()
    for row in manifest.filter(pl.col("status") == "generated").iter_rows(named=True):
        path = share / row["filename"]
        assert path.exists(), row["filename"]
        assert path.stat().st_size == row["byte_size"]
        assert _sha256(path) == row["sha256"]


def test_every_figure_has_same_stem_data(manifest):
    generated_figures = manifest.filter(
        (pl.col("kind") == "figure") & (pl.col("status") == "generated")
    )
    for row in generated_figures.iter_rows(named=True):
        png_stem = Path(row["filename"]).stem
        data = manifest.filter(pl.col("filename") == f"{png_stem}.csv")
        assert data.height == 1, png_stem
        assert data["figure_id"][0] == row["figure_id"]
        assert data["primary_dataframe"][0] == row["primary_dataframe"]


def test_output_names_follow_contract(manifest):
    stable_table1 = {
        "table1_by_agent_block_readable.csv",
        "table1_by_agent_block.json",
        "table1_by_agent_index_readable.csv",
        "table1_by_agent_index.json",
    }
    for filename in manifest.get_column("filename"):
        name = Path(filename).name
        assert name in stable_table1 or name.startswith(("fig_", "step")), filename
