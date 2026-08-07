"""Pins the E.7 / F11 MIN_CELL suppression path in `code/07_agreement.py` (§9, D43.2).

E.7 publishes `pair_collapse_deltas.csv` and F11 draws `pair_collapse_deltas.png` from
that published frame and nothing else (D26). The price of drawing only from the published
frame is that **any cell may be absent**, and every read of one has to degrade instead of
assuming it is there. At MIMIC the smallest cell in that table holds 29 intervals, so none
of the degradation ever fires on the site that developed it — which is exactly why it has
to be tested somewhere other than by running the pipeline.

It was not. The path was defended only by a one-off scaffold that was never committed, and
the final whole-branch review found two live defects in it:

  * F11 read `max_delta_min` and `n_beyond_max_delta` straight off `e7_pub`, so a fully
    suppressed table raised `IndexError` before any degradation ran;
  * F11's Δ≥2 totals were sums over published cells with no incompleteness marker, under a
    title asserting the two series run at "the same rate".

Both are caught below. The rule under test, from §9: a published count of **1..9** is
suppressed, suppression drops the **whole row**, and a count of exactly **zero** is
published — because "this never happened" and "this is missing" are different statements
and a multi-site table may not confuse them.

The shipped source is lifted out of the marimo notebook **by AST**, the way
`tests/test_collapse_agent_events.py` does it: `07_agreement` is not an importable module
name, and importing it would run the whole publishing pipeline against real PHI. The two
cells are executed with synthetic frames and stubbed collaborators, so what runs here is
the code that ships, with no second copy to drift.

Run:  uv run pytest tests/test_e7_suppression.py -v
"""

import ast
import re
from pathlib import Path

import matplotlib
import polars as pl
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NOTEBOOK = Path(__file__).parent.parent / "code" / "07_agreement.py"
SOURCE = NOTEBOOK.read_text()
TREE = ast.parse(SOURCE)

MIN_CELL = 10  # §9, mirrored from the notebook and asserted against it below
MAX_DELTA = 45  # 05's COLLAPSE_DELTA_MAX_MIN, the grid E.7 is handed
GAP = 15.0


# --------------------------------------------------------------------------------------
# Lifting the shipped source out of the notebook
# --------------------------------------------------------------------------------------


def _load_function(name, namespace):
    """Compile one named `def` out of the notebook, wherever it is nested."""
    found = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one def {name} in {NOTEBOOK.name}, found {len(found)}"
    )
    module = ast.Module(body=[found[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = dict(namespace)
    exec(compile(module, str(NOTEBOOK), "exec"), ns)
    return ns[name]


def _load_cell(marker):
    """Compile one `@app.cell` function, identified by a marker comment in its body.

    Returns `(callable, [parameter names])`. The parameter list is returned rather than
    hidden because it is the cell's declared dependency set: if a cell grows an argument
    the test has no value for, the call below fails with the name rather than silently
    testing something else.
    """
    cells = [n for n in TREE.body if isinstance(n, ast.FunctionDef)]
    found = [n for n in cells if marker in (ast.get_source_segment(SOURCE, n) or "")]
    assert len(found) == 1, (
        f"expected exactly one @app.cell containing {marker!r}, found {len(found)}"
    )
    node = found[0]
    params = [a.arg for a in node.args.args]
    # Round-tripped through unparse so the clone can be renamed and stripped of its
    # `@app.cell` decorator without mutating the shared tree the other loader walks.
    clone = ast.parse(ast.unparse(node)).body[0]
    clone.decorator_list = []
    clone.name = "cell"
    module = ast.Module(body=[clone], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {}
    exec(compile(module, str(NOTEBOOK), "exec"), ns)
    return ns["cell"], params


def _run_cell(marker, available):
    """Call a lifted cell with the values it declares, and nothing else."""
    fn, params = _load_cell(marker)
    missing = [p for p in params if p not in available]
    assert not missing, (
        f"the cell containing {marker!r} now takes {missing}, which this test does not "
        "supply — the fixture has drifted from the notebook, fix it rather than the cell"
    )
    return fn(**{p: available[p] for p in params})


E7_MARKER = "# E.7 -- the evidence for collapse_gap_minutes"
F11_MARKER = "# F11 -- E.7, the picture"

apply_min_cell = _load_function("apply_min_cell", {"pl": pl, "MIN_CELL": MIN_CELL})


def test_min_cell_is_ten_in_the_notebook():
    """Guards the guard: everything below is calibrated to §9's 1..9 range."""
    assert re.search(r"^\s*MIN_CELL = 10\b", SOURCE, re.M), (
        "MIN_CELL is no longer 10 in the notebook; re-derive the synthetic frames below "
        "before trusting anything they assert"
    )


# --------------------------------------------------------------------------------------
# Synthetic `collapse_deltas` frames — the shape 05 emits, with cells placed in 1..9
# --------------------------------------------------------------------------------------


# The real table has a charting-grid pile-up on the collapse boundary -- 1,164 intervals
# at Δ = 15 at MIMIC against ~200 either side -- and that pile-up is the whole premise of
# the "largest in its neighbourhood" clause. The default frame reproduces it, so the
# control test below exercises the clause firing; `spike=False` flattens it, which is the
# other site the clause has to be honest at.
SPIKE = {(15, False): 500, (15, True): 600}


def _deltas(overrides=None, base=40, beyond=5897, spike=True):
    """A complete 0..MAX x {different, same} grid, as 05 emits and asserts.

    `overrides` maps (delta_min, same_agent) -> n and is applied last, so a test can
    suppress or flatten the boundary spike. Anything not set holds `base`, which is
    comfortably above MIN_CELL, so the suppression under test is only ever the suppression
    the test asked for.
    """
    overrides = {**(SPIKE if spike else {}), **(overrides or {})}
    rows = []
    for _delta in range(MAX_DELTA + 1):
        for _same in (False, True):
            rows.append(
                {
                    "cohort_run_id": "TEST",
                    "delta_min": _delta,
                    "same_agent": _same,
                    "n": int(overrides.get((_delta, _same), base)),
                    "max_delta_min": MAX_DELTA,
                    "n_beyond_max_delta": beyond,
                }
            )
    return pl.DataFrame(rows).with_columns(
        pl.col("delta_min").cast(pl.Int32),
        pl.col("n").cast(pl.Int32),
        pl.col("max_delta_min").cast(pl.Int32),
        pl.col("n_beyond_max_delta").cast(pl.Int32),
    )


# The cells deliberately pushed into the disclosive range. One in each of the four places
# the figure reads differently: a cell the TITLE names, a cell only the CAPTION names, a
# cell inside the Δ≥2 span that only a SUM touches, and the Δ=15 boundary cell the M-8
# sensitivity clause needs.
SUPPRESSED = {
    (0, True): 5,  # named by title and caption
    (1, False): 7,  # named by caption
    (3, False): 4,  # inside the Δ>=2 span — reachable only through a total
    (15, True): 6,  # the inclusive-boundary cell
}
ZERO_CELL = {(44, True): 0}  # exactly zero is PUBLISHED, never suppressed


@pytest.fixture
def figures():
    """Captures what `finish` would have written, instead of writing a PNG."""
    written = []

    def finish(fig, path, caption=None):
        # F11 sets its title with loc="left", which matplotlib stores separately from the
        # centre title -- read all three or the assertions below test an empty string.
        _ax = fig.axes[0] if fig.axes else None
        _title = (
            " ".join(_ax.get_title(loc=_l) for _l in ("left", "center", "right")).strip()
            if _ax is not None
            else ""
        )
        written.append({"path": path, "caption": caption or "", "title": _title})
        plt.close(fig)

    return written, finish


def _render(deltas, tmp_path, figures):
    """Run the real E.7 cell then the real F11 cell over one synthetic frame."""
    written, finish = figures
    e7, e7_pub = _run_cell(
        E7_MARKER,
        {
            "COLLAPSE_GAP_MINUTES": GAP,
            "MIN_CELL": MIN_CELL,
            "SHARE_DIR": tmp_path,
            "apply_min_cell": apply_min_cell,
            "collapse_deltas": deltas,
            "pl": pl,
        },
    )
    _run_cell(
        F11_MARKER,
        {
            "COLLAPSE_GAP_MINUTES": GAP,
            "COLORS": {"SED": "#2c6fbb", "PARA": "#d1495b", "PAIR": "#4a9d5f"},
            "GREY": "#555555",
            "MIN_CELL": MIN_CELL,
            "SITE": "synthetic",
            "WINDOW_HOURS": 3,
            "e7": e7,
            "e7_pub": e7_pub,
            "finish": finish,
            "plt": plt,
        },
    )
    assert len(written) == 1, "F11 did not draw exactly one figure"
    return e7_pub, written[0]


# --------------------------------------------------------------------------------------
# The suppression rule itself
# --------------------------------------------------------------------------------------


def test_apply_min_cell_drops_only_the_disclosive_range():
    """1..9 goes, 0 stays, 10 stays — §9's rule in one assertion."""
    frame = pl.DataFrame({"n": [0, 1, 9, 10, 4000]})
    assert apply_min_cell(frame, ["n"], "T").get_column("n").to_list() == [0, 10, 4000]


def test_suppressed_rows_leave_the_published_frame(tmp_path, figures):
    e7_pub, _ = _render(_deltas({**SUPPRESSED, **ZERO_CELL}), tmp_path, figures)
    published = {(r["delta_min"], r["same_agent"]) for r in e7_pub.to_dicts()}
    for key in SUPPRESSED:
        assert key not in published, f"{key} holds 1..9 and was published anyway"
    for key in ZERO_CELL:
        assert key in published, f"{key} is exactly zero and must be published, not dropped"
    assert e7_pub.height == 2 * (MAX_DELTA + 1) - len(SUPPRESSED)


# --------------------------------------------------------------------------------------
# The rendering path: degrade, never raise, never guess
# --------------------------------------------------------------------------------------


def test_partially_suppressed_table_renders_without_raising(tmp_path, figures):
    """The whole point: a KeyError or IndexError here is a failed publishing run."""
    _, fig = _render(_deltas({**SUPPRESSED, **ZERO_CELL}), tmp_path, figures)
    assert fig["path"] == "pair_collapse_deltas.png"
    assert fig["title"] and fig["caption"]


def test_a_withheld_named_cell_is_never_rendered_as_zero(tmp_path, figures):
    """(0, same) and (1, different) are withheld; both are named on the figure.

    The failure this forbids is the quiet one: a `.get(key, 0)` that turns "we are not
    allowed to tell you" into "it never happened".
    """
    _, fig = _render(_deltas({**SUPPRESSED, **ZERO_CELL}), tmp_path, figures)
    text = fig["title"] + " " + fig["caption"]
    # Two withheld cells are named outright (Δ=0 same-agent, Δ=1 different-agent), and the
    # Δ=0 one is named twice — once in the title, once in the caption.
    assert text.count(f"withheld (<{MIN_CELL})") == 3, text
    assert re.search(r"\b0 same-agent\b", text) is None, (
        "a withheld cell was printed as 0 — see the title"
    )
    assert re.search(r"\b0 vs\b|\bvs 0\b", text) is None, text


def test_a_short_span_total_is_starred_and_claims_no_rate(tmp_path, figures):
    """(3, different) is withheld, so the Δ≥2 different-agent total is a lower bound.

    Without the marker the figure prints a smaller number under a title that calls the two
    totals "the same rate", which is the M-2 defect: silently short, and asserted equal.
    """
    _, fig = _render(_deltas({**SUPPRESSED, **ZERO_CELL}), tmp_path, figures)
    title, caption = fig["title"], fig["caption"]
    assert re.search(r"Δ≥2\s+[\d,]+\*", title), (
        f"the incomplete Δ≥2 total carries no incompleteness marker: {title!r}"
    )
    assert "the same rate)" not in title, (
        "a rate was claimed between a complete total and one missing a cell"
    )
    assert "absent, not zero" in caption.lower(), (
        "the caption does not tell the reader the missing cells are absent rather than zero"
    )
    assert "lower bound" in caption.lower()


DEGRADED = "No count is put on that here"


def test_the_boundary_sensitivity_clause_degrades(tmp_path, figures):
    """(15, same) is withheld, so the Δ=15 spike cannot be sized and must not be guessed."""
    _, fig = _render(_deltas({**SUPPRESSED, **ZERO_CELL}), tmp_path, figures)
    caption = fig["caption"]
    assert DEGRADED in caption, caption
    assert "largest in its neighbourhood" not in caption, (
        "the spike was sized from a span containing a withheld cell"
    )


def test_a_flat_neighbourhood_is_not_called_a_spike(tmp_path, figures):
    """Nothing is suppressed and every Δ holds the same count — so there is no spike.

    `collapse_gap_minutes` is per-site config. At a site whose value is not a multiple of
    the charting grid the boundary bin has no pile-up on it, and a caption that says
    "the largest in its neighbourhood" is then a measured claim that is false — published,
    to the consortium, exactly the failure I-1 blocked the merge over. The clause has to
    be conditional on the comparison it makes, not merely on the cells being published.
    """
    _, fig = _render(_deltas(spike=False), tmp_path, figures)
    caption = fig["caption"]
    assert "largest in its neighbourhood" not in caption, (
        "a flat neighbourhood was published as a spike: " + caption
    )
    assert DEGRADED in caption, caption
    # ...and no measured size is smuggled in by another route.
    assert "% of all" not in caption, caption
    assert "turns on a measured" not in caption, caption
    # The sentence one clause earlier makes the same claim in prose and is gated on the
    # same comparison: with no spike on the boundary there is no spike to call grid.
    assert "sitting on the boundary" not in caption, caption
    assert "does not sit on one of them here" in caption, caption


@pytest.mark.parametrize(
    ("label", "spike_at_edge"),
    [
        ("ties its lower neighbour", {(15, False): 40, (15, True): 40}),
        ("ties its upper neighbour", {(15, False): 45, (15, True): 35}),
        ("sits below its neighbours", {(15, False): 10, (15, True): 10}),
    ],
)
def test_a_boundary_that_does_not_exceed_both_neighbours_is_not_a_spike(
    label, spike_at_edge, tmp_path, figures
):
    """Strictly greater than BOTH sides, or the clause says nothing.

    A tie is not a spike, and at `base = 40` per cell the neighbours total 80 each — so
    the first two cases sum to exactly 80 at the boundary and the third to 20.
    """
    _, fig = _render(_deltas(spike_at_edge, spike=False), tmp_path, figures)
    assert "largest in its neighbourhood" not in fig["caption"], (label, fig["caption"])
    assert DEGRADED in fig["caption"], (label, fig["caption"])


def test_a_withheld_whole_table_margin_says_so(tmp_path, figures):
    """`n_beyond_max_delta` is a margin, not a cell, so it is blanked rather than dropped."""
    _, fig = _render(_deltas(beyond=4), tmp_path, figures)
    assert f"withheld under the n>={MIN_CELL} rule" in fig["caption"], fig["caption"]
    assert "4 intervals longer than" not in fig["caption"]


def test_every_cell_suppressed_still_renders(tmp_path, figures):
    """The case M-1 raised IndexError on: nothing at all survives publication.

    `max_delta_min` is a constant of the input contract and comes off the unsuppressed
    frame; `n_beyond_max_delta` is a count and comes off a height-guarded published frame.
    Neither may be indexed blind.
    """
    e7_pub, fig = _render(_deltas(base=5, beyond=3, spike=False), tmp_path, figures)
    assert e7_pub.height == 0
    text = fig["title"] + " " + fig["caption"]
    assert f"withheld (<{MIN_CELL})" in text
    assert f"{2 * (MAX_DELTA + 1)} cell(s)" in fig["caption"], fig["caption"]
    assert "the same rate)" not in fig["title"]
    # The x axis still spans the input's declared range rather than collapsing to nothing.
    assert f"longer than {MAX_DELTA} min" in fig["caption"]


@pytest.mark.parametrize(
    ("label", "deltas"),
    [
        ("none suppressed", _deltas()),
        ("some suppressed", _deltas({**SUPPRESSED, **ZERO_CELL})),
        ("all suppressed", _deltas(base=5, beyond=3, spike=False)),
        ("margin suppressed", _deltas(beyond=4)),
        ("flat, no boundary spike", _deltas(spike=False)),
    ],
)
def test_no_figure_text_ever_contains_a_bare_nan(label, deltas, tmp_path, figures):
    """A missing number must read as "withheld", never leak through as a float nan."""
    _, fig = _render(deltas, tmp_path, figures)
    text = fig["title"] + " " + fig["caption"]
    assert not re.search(r"\bnan\b", text, re.I), (label, text)
    assert "None" not in text, (label, text)


def test_the_unsuppressed_case_still_makes_its_claim(tmp_path, figures):
    """Guards the guards: if the complete table also refused to claim a rate, the

    assertions above would pass on a figure that had simply stopped saying anything.
    """
    _, fig = _render(_deltas(), tmp_path, figures)
    assert "the same rate)" in fig["title"], fig["title"]
    assert "withheld" not in fig["title"]
    assert "*" not in fig["title"]
    # The boundary spike (500 + 600 = 1,100) genuinely stands above both neighbours (80
    # each), so the clause fires AND names all three counts. Without this the tests above
    # would all pass on a clause that had simply been switched off.
    caption = fig["caption"]
    assert "largest in its neighbourhood" in caption, caption
    assert "1,100 intervals sit exactly on Δ = 15" in caption, caption
    assert "against 80 at Δ = 14 and 80 at Δ = 16" in caption, caption
    assert "the one sitting on the boundary at Δ = 15 is grid, not boundary-induced" in caption
    assert DEGRADED not in caption, caption
