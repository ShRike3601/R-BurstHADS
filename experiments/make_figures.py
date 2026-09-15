"""
The six single-column figures of FIGURE_SPEC.md, from RESULTS_PACK.md only.

    python experiments\\make_figures.py      (from the project root)

No simulation and no result file other than RESULTS_PACK.md is read: every
plotted value is parsed out of the pack's markdown tables (T1, T5), so a
figure cannot drift from the pack. Output: paper/fig/<stem>.pdf (plus a .png
preview) via ieee_figs.save.
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
from ieee_figs import single, save, grouped_bars, trend, zero_line, legend_above, C, INK, INK_SOFT, MARK, ZERO

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
        raise SystemExit(f"{ident} not found in RESULTS_PACK.md")
    lines = PACK[m.end():].splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("|"))
    rows = []
    header = [c.strip() for c in lines[start].strip("|").split("|")]
    for l in lines[start + 2:]:
        if not l.startswith("|"):
            break
        rows.append(dict(zip(header, (c.strip() for c in l.strip("|").split("|")))))
    return rows


def pct(s):
    return float(s.replace("%", "").replace("−", "-"))


T1 = {r["group"]: r for r in table("T1")}
T5 = table("T5")

B, R = "Burst-HADS", "R-BurstHADS"
OUT = ROOT / _ARGS.outdir
made = []


def label_bars(ax, xs, vals, fmt, dy=2):
    for x, v in zip(xs, vals):
        ax.annotate(fmt.format(v).replace("-", "−"), xy=(x, v), xytext=(0, dy if v >= 0 else -dy),
                    textcoords="offset points", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=6, color=INK)


def baseline_below(ax):
    """zero_line, with its label under the line instead of over the right-most bar."""
    zero_line(ax, label=None)
    ax.annotate("HADS baseline", xy=(0.995, 0), xycoords=("axes fraction", "data"),
                xytext=(0, -2), textcoords="offset points", ha="right", va="top",
                fontsize=6, color=INK_SOFT)


# ── Fig. 1: headline trade-off, limits on, 75 fully feasible cells ─────────
row = T1["all"]
fig, ax = single()
vals = {B: [pct(row["B mk vs H"]), pct(row["B $ vs H"])],
        R: [pct(row["R mk vs H"]), pct(row["R $ vs H"])]}
grouped_bars(ax, ["Makespan", "Cost"], vals, ylabel="Change vs HADS (%)")
baseline_below(ax)
w, g = 0.26, 0.02
for k, name in enumerate((B, R)):
    off = (k - 0.5) * (w + g)
    label_bars(ax, [0 + off, 1 + off], vals[name], "{:+.1f}%")
ax.set_ylim(-36, 30)
legend_above(fig, ax)
made.append(save(fig, "fig1_headline", outdir=str(OUT)))

# ── Figs. 2, 3: cost / makespan against deadline slack ──────────────────────
dfs = [0.25, 0.5, 1.0, 2.0]
for stem, bcol, rcol, ylabel in (("fig2_cost_vs_df", "B $ vs H", "R $ vs H", "Cost change vs HADS (%)"),
                                 ("fig3_makespan_vs_df", "B mk vs H", "R mk vs H", "Makespan change vs HADS (%)")):
    fig, ax = single()
    vals = {B: [pct(T1[f"DF={d}"][bcol]) for d in dfs], R: [pct(T1[f"DF={d}"][rcol]) for d in dfs]}
    trend(ax, dfs, vals, ylabel=ylabel, xlabel="Deadline factor DF")
    ax.set_xscale("log", base=2)
    ax.set_xticks(dfs)
    ax.set_xticklabels([str(d) for d in dfs])
    ax.minorticks_off()
    zero_line(ax)
    legend_above(fig, ax)
    made.append(save(fig, stem, outdir=str(OUT)))

# ── Fig. 4: cost by interruption scenario ───────────────────────────────────
scs = ["sc1", "sc2", "sc3", "sc4", "sc5"]
khkr = {"sc1": "(1, 0)", "sc2": "(5, 0)", "sc3": "(1, 5)", "sc4": "(5, 5)", "sc5": "(3, 2.5)"}
fig, ax = single()
vals = {B: [pct(T1[s]["B $ vs H"]) for s in scs], R: [pct(T1[s]["R $ vs H"]) for s in scs]}
grouped_bars(ax, [f"{s}\n{khkr[s]}" for s in scs], vals, ylabel="Cost change vs HADS (%)")
ax.set_xlabel("Scenario (kh, kr)", color=INK)
ax.set_ylim(-4, None)
baseline_below(ax)
legend_above(fig, ax)
made.append(save(fig, "fig4_scenarios", outdir=str(OUT)))

# ── Fig. 5: cost against bag size ───────────────────────────────────────────
ns = [50, 100, 200, 300]
fig, ax = single()
vals = {B: [pct(T1[f"n={n}"]["B $ vs H"]) for n in ns], R: [pct(T1[f"n={n}"]["R $ vs H"]) for n in ns]}
trend(ax, ns, vals, ylabel="Cost change vs HADS (%)", xlabel="Tasks in the bag, n")
ax.set_xticks(ns)
zero_line(ax)
rb300 = T1["n=300"]["R $ vs B"]
ax.annotate(f"n = 300: R-BurstHADS {rb300.replace('-', chr(0x2212))} vs Burst-HADS",
            xy=(300, min(vals[B][-1], vals[R][-1])), xytext=(0, -7),
            textcoords="offset points", ha="right", va="top", fontsize=6, color=INK_SOFT)
legend_above(fig, ax)
made.append(save(fig, "fig5_cost_vs_n", outdir=str(OUT)))

# ── Fig. 6: limits on against limits off, both axes, the same cells ─────────
# T2b holds both settings over identical cells (T1's and T2's "all" rows do not).
T2B = {r["limits"]: r for r in table("T2b")}
fig, ax = single()
ax.axhline(0, color=ZERO, linewidth=0.7, zorder=1)
ax.axvline(0, color=ZERO, linewidth=0.7, zorder=1)
ax.annotate("HADS", xy=(0, 0), xytext=(3, 3), textcoords="offset points", fontsize=6, color=INK_SOFT)
xs, ys = [0.0], [0.0]
P6 = {name: [(pct(T2B[s][c_col]), pct(T2B[s][mk_col])) for s in ("on", "off")]
      for name, mk_col, c_col in ((B, "B mk vs H", "B $ vs H"), (R, "R mk vs H", "R $ vs H"))}
for (x_, y_) in [p for v in P6.values() for p in v]:
    xs.append(x_)
    ys.append(y_)
x_mid = (min(xs) + max(xs)) / 2
for name in (B, R):
    marker, _ = MARK[name]
    (x0, y0), (x1, y1) = P6[name]
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), zorder=2,
                arrowprops=dict(arrowstyle="-|>", color=C[name], lw=0.8, shrinkA=4, shrinkB=4, mutation_scale=7))
    ax.plot([x0], [y0], marker=marker, linestyle="none", color=C[name], markeredgecolor="white",
            markeredgewidth=0.5, markersize=6, label=f"{name}, limits on", zorder=3)
    ax.plot([x1], [y1], marker=marker, linestyle="none", markerfacecolor="white", markeredgecolor=C[name],
            markeredgewidth=1.0, markersize=6, label=f"{name}, limits off", zorder=3)
    # Shift when limits are lifted, in points (off minus on over the same cells, T2b).
    right = (x0 + x1) / 2 > x_mid          # keep the label inside the axes
    ax.annotate(f"limits off: cost {x1 - x0:+.1f} pts, makespan {y1 - y0:+.1f} pts".replace("-", "−"),
                xy=(max(x0, x1) if right else min(x0, x1), min(y0, y1)), xytext=(0, -8),
                textcoords="offset points", ha="right" if right else "left", va="top",
                fontsize=6, color=C[name])
ax.set_xlabel("Cost change vs HADS (%)", color=INK)
ax.set_ylabel("Makespan change vs HADS (%)", color=INK)
ax.set_xlim(min(xs) - 3, max(xs) + 3)
ax.set_ylim(min(ys) - 8, max(ys) + 4)
legend_above(fig, ax)
made.append(save(fig, "fig6_limits_on_off", outdir=str(OUT)))

print("\n".join(made))
