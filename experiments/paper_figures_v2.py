"""
Complete figure set for the three-way comparison. Driven entirely by
experiments/results_dynamic_comparison.json -- no simulation is re-run.
"""
import json, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import compute_deadlines

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "figures_v2"; OUT.mkdir(exist_ok=True)

C  = {"hads": "#2a78d6", "burst": "#eb6834", "rburst": "#1baf7a"}
MK = {"hads": "o", "burst": "s", "rburst": "^"}
LS = {"hads": "-", "burst": "--", "rburst": "-"}
LW = {"hads": 2.0, "burst": 2.0, "rburst": 2.6}
LABEL = {"hads": "HADS", "burst": "Burst-HADS", "rburst": "R-BurstHADS"}
KEYS = ["hads", "burst", "rburst"]

INK, INK2, MUTED, GRID, BASE, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
KH = {"sc1": 1.0, "sc2": 5.0, "sc3": 1.0, "sc4": 5.0, "sc5": 3.0}
KR = {"sc1": 0.0, "sc2": 0.0, "sc3": 5.0, "sc4": 5.0, "sc5": 2.5}
SC_TITLE = {s: f"{s}  $k_h$={KH[s]:g}, $k_r$={KR[s]:g}" for s in KH}
SCEN = ["sc1", "sc2", "sc3", "sc4", "sc5"]

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 9,
    "axes.titlesize": 9.5, "axes.labelsize": 9,
    "axes.edgecolor": BASE, "axes.linewidth": 0.8,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.labelcolor": INK2, "text.color": INK,
    "figure.facecolor": SURF, "axes.facecolor": SURF,
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False,
})

rows = json.load(open(ROOT / "results_dynamic_comparison.json"))
D = {(r["scenario"], r["n"]): r for r in rows}
NS = sorted({r["n"] for r in rows if r["scenario"] in SCEN})
X  = np.arange(len(NS))
DL = {n: compute_deadlines(n, 1.0, 1)[0] for n in NS}

def S(sc, k, f): return np.array([D[(sc, n)][f"{k}_{f}"] for n in NS], float)
def ax_base(a):
    a.grid(axis="y", color=GRID, lw=0.7); a.set_axisbelow(True)
    a.set_xticks(X); a.set_xticklabels([str(n) for n in NS])
def save(fig, name):
    fig.savefig(OUT / name, dpi=300, bbox_inches="tight"); plt.close(fig); print("  " + name)
def legend_top(fig, ax, ncol=3):
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=ncol, bbox_to_anchor=(0.5, 1.005),
               fontsize=9.5, columnspacing=2.2)

def grid5(rowspecs, fname, ylabels, ylog=False, share_row=True):
    """rowspecs: list of fn(sc,key)->array, one per row."""
    nr = len(rowspecs)
    fig, axes = plt.subplots(nr, 5, figsize=(14.5, 2.9 * nr), sharex=True,
                             squeeze=False)
    for i, fn in enumerate(rowspecs):
        hi = 0
        for j, sc in enumerate(SCEN):
            for k in KEYS:
                y = fn(sc, k)
                hi = max(hi, np.nanmax(y))
                axes[i, j].plot(X, y, color=C[k], marker=MK[k], ls=LS[k],
                                lw=LW[k], ms=5, mec="white", mew=1.0, label=LABEL[k])
            ax_base(axes[i, j])
            if i == 0: axes[i, j].set_title(SC_TITLE[sc], color=INK, pad=7)
            if j: axes[i, j].tick_params(labelleft=False)
            if i == nr - 1: axes[i, j].set_xlabel("Tasks", color=INK2)
            if ylog: axes[i, j].set_yscale("log")
        if share_row and not ylog:
            for j in range(5): axes[i, j].set_ylim(0, hi * 1.08)
        axes[i, 0].set_ylabel(ylabels[i], color=INK2, fontweight="bold")
    legend_top(fig, axes[0, 0])
    fig.tight_layout(rect=[0, 0, 1, 1 - 0.055 / nr * 2])
    save(fig, fname)

# 1 ── makespan + cost
grid5([lambda sc,k: S(sc,k,"mk_avg"), lambda sc,k: S(sc,k,"co_avg")],
      "fig1_makespan_cost.png", ["Makespan (s)", "Cost (USD)"])

# 3 ── cost per task
grid5([lambda sc,k: S(sc,k,"co_avg") / np.array(NS) * 1000],
      "fig3_cost_per_task.png", [r"Cost per task ($10^{-3}$ USD)"])

# 4 ── speedup relative to HADS
grid5([lambda sc,k: S(sc,"hads","mk_avg") / S(sc,k,"mk_avg")],
      "fig4_speedup.png", [r"Speedup vs HADS ($\times$)"], share_row=True)

# 9 ── deadline utilisation
dl = np.array([DL[n] for n in NS])
grid5([lambda sc,k: S(sc,k,"mk_avg") / dl],
      "fig9_deadline_utilisation.png", ["Makespan / deadline"], share_row=True)

# 6 ── makespan with +-1 SD
fig, axes = plt.subplots(1, 5, figsize=(14.5, 3.1), sharex=True)
for j, sc in enumerate(SCEN):
    for k in KEYS:
        axes[j].errorbar(X, S(sc,k,"mk_avg"), yerr=S(sc,k,"mk_std"), color=C[k],
                         marker=MK[k], ls=LS[k], lw=LW[k], ms=5, capsize=3,
                         mec="white", mew=1.0, label=LABEL[k])
    ax_base(axes[j]); axes[j].set_title(SC_TITLE[sc], color=INK, pad=7)
    axes[j].set_xlabel("Tasks", color=INK2)
    if j: axes[j].tick_params(labelleft=False)
axes[0].set_ylabel("Makespan (s)", color=INK2, fontweight="bold")
legend_top(fig, axes[0]); fig.tight_layout(rect=[0,0,1,0.90])
save(fig, "fig6_makespan_variability.png")

# 2 ── advantage bars (mean over n>=100)
big = [i for i, n in enumerate(NS) if n >= 100]
def adv(sc, f):
    b = S(sc,"burst",f)[big].mean(); r = S(sc,"rburst",f)[big].mean()
    return (b - r) / b * 100
cost_adv = [adv(sc,"co_avg") for sc in SCEN]; mk_adv = [adv(sc,"mk_avg") for sc in SCEN]
order = np.argsort(cost_adv)
fig, ax = plt.subplots(figsize=(8.4, 4.0)); y = np.arange(5); h = 0.36
for off, vals, col, lab in ((h/2+0.01, cost_adv, "#1baf7a", "Cost reduction"),
                            (-h/2-0.01, mk_adv, "#4a3aa7", "Makespan reduction")):
    bars = ax.barh(y + off, [vals[i] for i in order], height=h, color=col, label=lab)
    for r_ in bars:
        w = r_.get_width()
        ax.text(w + 1.2, r_.get_y() + r_.get_height()/2, f"{w:+.1f}%",
                va="center", fontsize=8.5, color=INK2)
ax.axvline(0, color=BASE, lw=1.2)
ax.set_yticks(y); ax.set_yticklabels([SC_TITLE[SCEN[i]] for i in order], color=INK)
ax.set_xlabel(r"R-BurstHADS advantage over Burst-HADS (%),  mean over $n\geq100$", color=INK2)
ax.grid(axis="x", color=GRID, lw=0.7); ax.set_axisbelow(True)
ax.set_xlim(min(0, min(cost_adv+mk_adv))-8, max(cost_adv+mk_adv)+12)
ax.legend(loc="lower right", fontsize=9); fig.tight_layout()
save(fig, "fig2_rburst_advantage.png")

# 7 ── diverging heatmaps
fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.2))
for a, f, t in ((axes[0], "co_avg", "Cost reduction (%)"),
                (axes[1], "mk_avg", "Makespan reduction (%)")):
    M = np.array([[(D[(sc,n)][f"burst_{f}"] - D[(sc,n)][f"rburst_{f}"]) /
                   D[(sc,n)][f"burst_{f}"] * 100 for n in NS] for sc in SCEN])
    v = np.abs(M).max()
    im = a.imshow(M, cmap="RdBu", vmin=-v, vmax=v, aspect="auto")
    a.set_xticks(X); a.set_xticklabels([str(n) for n in NS])
    a.set_yticks(range(5)); a.set_yticklabels([SC_TITLE[s] for s in SCEN], fontsize=8.5)
    a.set_xlabel("Tasks", color=INK2); a.set_title(t, color=INK, fontweight="bold")
    for i in range(5):
        for j in range(len(NS)):
            a.text(j, i, f"{M[i,j]:.0f}", ha="center", va="center", fontsize=8,
                   color="white" if abs(M[i,j]) > v*0.55 else INK)
    plt.colorbar(im, ax=a, shrink=0.85)
fig.suptitle("R-BurstHADS relative to Burst-HADS. Blue = R-BurstHADS better.",
             color=INK2, fontsize=9.5, y=1.03)
fig.tight_layout(); save(fig, "fig7_heatmap.png")

# 8 ── cost advantage vs kh
fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.4))
for a, f, t in ((axes[0], "co_avg", "Cost reduction (%)"),
                (axes[1], "mk_avg", "Makespan reduction (%)")):
    xs = [KH[s] for s in SCEN]; ys = [adv(s, f) for s in SCEN]
    for s, xv, yv in zip(SCEN, xs, ys):
        a.scatter(xv, yv, s=110, color="#1baf7a" if KR[s] == 0 else "#4a3aa7",
                  edgecolor="white", lw=1.4, zorder=3)
        a.annotate(s, (xv, yv), xytext=(7, -3), textcoords="offset points",
                   fontsize=8.5, color=INK2)
    a.axhline(0, color=BASE, lw=1.2)
    a.set_xlabel(r"Expected interruptions per instance, $k_h$", color=INK2)
    a.set_ylabel(t, color=INK2, fontweight="bold")
    a.set_xticks([1, 3, 5]); a.grid(color=GRID, lw=0.7); a.set_axisbelow(True)
from matplotlib.lines import Line2D
fig.legend(handles=[Line2D([],[],marker='o',ls='',color="#1baf7a",ms=9,label="$k_r=0$ (no resumption)"),
                    Line2D([],[],marker='o',ls='',color="#4a3aa7",ms=9,label="$k_r>0$")],
           loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.06), fontsize=9)
fig.tight_layout(rect=[0,0,1,0.93]); save(fig, "fig8_kh_sensitivity.png")

# 5 ── cost-makespan tradeoff scatter
fig, ax = plt.subplots(figsize=(6.6, 4.6))
for k in ("burst", "rburst"):
    xs, ys = [], []
    for sc in SCEN:
        for i, n in enumerate(NS):
            if n < 100: continue
            xs.append(D[(sc,n)][f"{k}_mk_avg"] / D[(sc,n)]["hads_mk_avg"])
            ys.append(D[(sc,n)][f"{k}_co_avg"] / D[(sc,n)]["hads_co_avg"])
    ax.scatter(xs, ys, s=64, color=C[k], marker=MK[k], edgecolor="white",
               lw=1.2, alpha=0.9, label=LABEL[k], zorder=3)
ax.axhline(1, color=BASE, lw=1.2); ax.axvline(1, color=BASE, lw=1.2)
ax.text(1.005, ax.get_ylim()[1], " HADS baseline", va="top", fontsize=8, color=MUTED)
ax.set_xlabel("Makespan relative to HADS  (<1 is faster)", color=INK2, fontweight="bold")
ax.set_ylabel("Cost relative to HADS  (<1 is cheaper)", color=INK2, fontweight="bold")
ax.grid(color=GRID, lw=0.7); ax.set_axisbelow(True); ax.legend(fontsize=9)
fig.tight_layout(); save(fig, "fig5_tradeoff.png")

# 10 ── validation vs published
PUB = {"J60": (2620, 1274), "J80": (2581, 1419), "J100": (2518, 1900), "ED200": (2680, 2327)}
OURS = {"J60": (2475.9, 1635.7), "J80": (2500.8, 1600.0), "J100": (2540.5, 2327.5),
        "ED200": (2693.6, 2619.8)}
jobs = list(PUB); xj = np.arange(len(jobs)); w = 0.2
fig, ax = plt.subplots(figsize=(7.6, 3.6))
for off, vals, col, lab in (
        (-1.5*w, [OURS[j][0] for j in jobs], "#2a78d6", "HADS (ours)"),
        (-0.5*w, [PUB[j][0]  for j in jobs], "#86b6ef", "HADS (published)"),
        ( 0.5*w, [OURS[j][1] for j in jobs], "#eb6834", "Burst-HADS (ours)"),
        ( 1.5*w, [PUB[j][1]  for j in jobs], "#f5b08e", "Burst-HADS (published)")):
    ax.bar(xj + off, vals, width=w, color=col, label=lab, edgecolor=SURF, lw=1.2)
ax.axhline(2700, color="#e34948", ls="--", lw=1.5)
ax.text(len(jobs)-0.45, 2760, "deadline $D$ = 2700 s", fontsize=8, color="#e34948", ha="right")
ax.set_xticks(xj); ax.set_xticklabels(jobs)
ax.set_ylabel("Makespan (s)", color=INK2, fontweight="bold")
ax.set_xlabel("Reference job", color=INK2)
ax.grid(axis="y", color=GRID, lw=0.7); ax.set_axisbelow(True)
ax.legend(fontsize=8.5, ncol=2); fig.tight_layout()
save(fig, "fig10_validation.png")

print("\nAll figures ->", OUT)
