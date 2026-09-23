"""
The six single-column figures of FIGURE_SPEC.md, from RESULTS_PACK.md only.

    python experiments\\make_figures.py      (from the project root)

The set is orthogonal: cost and makespan, each against deadline factor,
interruption scenario and bag size (owner, 2026-09-23). Every figure plots
absolute values -- three real series, seconds and dollars, y axis from zero.
Percentage changes against HADS live in the tables (T1, T27), never in a
chart, so HADS is a plotted series here and not a zero line; `zero_line` is
no longer used by this script.

No simulation and no result file other than RESULTS_PACK.md is read: every
plotted value is parsed out of the pack's T1b table, so a figure cannot drift
from the pack. Output: paper/fig/<stem>.pdf (plus a .png preview) via
ieee_figs.save.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import matplotlib
import matplotlib.ticker
matplotlib.rcParams["pdf.fonttype"] = 42    # TrueType, not Type 3: IEEE PDF eXpress rejects Type 3
matplotlib.rcParams["ps.fonttype"] = 42
from ieee_figs import single, save, grouped_bars, trend, legend_above, INK, S

import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--pack", default="RESULTS_PACK.md", help="results pack to read, relative to the project root")
_ap.add_argument("--outdir", default="paper/fig", help="output directory, relative to the project root")
_ARGS = _ap.parse_args()
PACK = (ROOT / _ARGS.pack).read_text(encoding="utf-8")


def table(ident):
    """Rows of the first markdown table under '### <ident>.' as dicts."""
    m = re.search(rf"^### {re.escape(ident)}\. .*?$", PACK, flags=re.M)
    if not m:
        raise SystemExit(f"{ident} not found in {_ARGS.pack}")
    lines = PACK[m.end():].splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("|"))
    rows = []
    header = [c.strip() for c in lines[start].strip("|").split("|")]
    for l in lines[start + 2:]:
        if not l.startswith("|"):
            break
        rows.append(dict(zip(header, (c.strip() for c in l.strip("|").split("|")))))
    return rows


T1B = {r["group"]: r for r in table("T1b")}
COL = {"mk": {k: f"{k} mk (s)" for k in S}, "cost": {k: f"{k} cost ($)" for k in S}}
OUT = ROOT / _ARGS.outdir
made = []


def series(metric, groups):
    """{scheduler: [value per group]} from T1b."""
    return {k: [float(T1B[g][COL[metric][k]]) for g in groups] for k in S}


def from_zero(ax, vals, metric, headroom=1.06):
    """Zero-based y axis, with ticks printed the way the unit is read: money to
    two decimals, seconds with a thousands separator."""
    ax.set_ylim(0, max(v for vs in vals.values() for v in vs) * headroom)
    fmt = "${x:,.2f}" if metric == "cost" else "{x:,.0f}"
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter(fmt))


DFS = [0.25, 0.5, 1.0, 2.0]
NS = [50, 100, 200, 300]
SCS = ["sc1", "sc2", "sc3", "sc4", "sc5"]
KHKR = {"sc1": "(1, 0)", "sc2": "(5, 0)", "sc3": "(1, 5)", "sc4": "(5, 5)", "sc5": "(3, 2.5)"}
METRICS = {"cost": "Mean cost per run", "mk": "Mean makespan (s)"}

# ── Figs. 1, 2: cost / makespan against the deadline factor ─────────────────
for stem, metric in (("fig1_cost_vs_df", "cost"), ("fig2_makespan_vs_df", "mk")):
    fig, ax = single()
    vals = series(metric, [f"DF={d}" for d in DFS])
    trend(ax, DFS, vals, ylabel=METRICS[metric], xlabel="Deadline factor DF")
    ax.set_xscale("log", base=2)
    ax.set_xticks(DFS)
    ax.set_xticklabels([str(d) for d in DFS])
    ax.minorticks_off()
    from_zero(ax, vals, metric)
    legend_above(fig, ax)
    made.append(save(fig, stem, outdir=str(OUT)))

# ── Figs. 3, 4: cost / makespan by interruption scenario ────────────────────
for stem, metric in (("fig3_cost_vs_scenario", "cost"), ("fig4_makespan_vs_scenario", "mk")):
    fig, ax = single()
    vals = series(metric, SCS)
    grouped_bars(ax, [f"{s}\n{KHKR[s]}" for s in SCS], vals, ylabel=METRICS[metric])
    ax.set_xlabel("Scenario (kh, kr)", color=INK)
    from_zero(ax, vals, metric)
    legend_above(fig, ax)
    made.append(save(fig, stem, outdir=str(OUT)))

# ── Figs. 5, 6: cost / makespan against bag size ────────────────────────────
for stem, metric in (("fig5_cost_vs_n", "cost"), ("fig6_makespan_vs_n", "mk")):
    fig, ax = single()
    vals = series(metric, [f"n={n}" for n in NS])
    trend(ax, NS, vals, ylabel=METRICS[metric], xlabel="Tasks in the bag, n")
    ax.set_xticks(NS)
    from_zero(ax, vals, metric)
    legend_above(fig, ax)
    made.append(save(fig, stem, outdir=str(OUT)))

RECORD = [
    ("fig1_cost_vs_df.pdf", "cost", [f"DF={d}" for d in DFS], [f"DF {d}" for d in DFS], "Mean cost ($) against the deadline factor"),
    ("fig2_makespan_vs_df.pdf", "mk", [f"DF={d}" for d in DFS], [f"DF {d}" for d in DFS], "Mean makespan (s) against the deadline factor"),
    ("fig3_cost_vs_scenario.pdf", "cost", SCS, [f"{s} {KHKR[s]}" for s in SCS], "Mean cost ($) by hibernation scenario"),
    ("fig4_makespan_vs_scenario.pdf", "mk", SCS, [f"{s} {KHKR[s]}" for s in SCS], "Mean makespan (s) by hibernation scenario"),
    ("fig5_cost_vs_n.pdf", "cost", [f"n={n}" for n in NS], [f"n = {n}" for n in NS], "Mean cost ($) against bag size"),
    ("fig6_makespan_vs_n.pdf", "mk", [f"n={n}" for n in NS], [f"n = {n}" for n in NS], "Mean makespan (s) against bag size"),
]
rec = ["# Figures — record (not prose)", "",
       "Generated by `experiments/make_figures.py` from `RESULTS_PACK.md` table **T1b** only "
       "(values parsed from the table; nothing typed by hand), with `experiments/ieee_figs.py`, per "
       "`experiments/FIGURE_SPEC.md`. Single column, one graph each, Times New Roman embedded as TrueType "
       "(no Type 3).", "",
       "The set is orthogonal: cost and makespan, each against deadline factor, scenario and bag size. "
       "**Every figure plots absolute values** — three real series, seconds and dollars, y axis from zero. "
       "Percentage changes against HADS are in the tables (T1, T27), never in a chart; HADS is a plotted "
       "series, not a zero line.", "",
       "Cells: the 75 where every scheduler is feasible in every seed, launch limits on [T1b].", ""]
for stem, metric, groups, labels, title in RECORD:
    vals = series(metric, groups)
    fmt = (lambda v: f"{v:.4f}") if metric == "cost" else (lambda v: f"{v:.0f}")
    rec.append(f"## {stem}")
    rec.append(f"- {title}; source T1b, rows {', '.join(groups)}.")
    for k in S:
        rec.append(f"- {k}: " + ", ".join(f"{lab} {fmt(v)}" for lab, v in zip(labels, vals[k])))
    rec.append("")
(OUT / "FIGURES.md").write_text("\n".join(rec) + "\n", encoding="utf-8")
made.append(str(OUT / "FIGURES.md"))

print("\n".join(made))
