"""
IEEE two-column figure toolkit for the R-BurstHADS paper.

The whole point of this module is that figures are built AT THEIR FINAL
PRINTED SIZE. Never draw a wide figure and shrink it in LaTeX with
[width=\\columnwidth] -- that is what produces 4pt axis labels and is the
reason the current figures are unreadable. Pick the right helper, draw
into it, save, and place it at its natural size.

    from ieee_figs import single, save, S, C, HATCH, MARK

    fig, ax = single()                 # 3.40 x 2.35 in, ONE graph
    save(fig, "fig4_scenarios")        # writes .pdf and .png

This paper is single column only: every figure is 3.40in and holds exactly
one graph. double() is retained so older scripts still import; do not use
it here.

Palette
-------
Validated with the dataviz skill's checker (all six checks pass on a light
surface, --pairs all):

    #1d4aa3  R-BurstHADS   L 0.43  darkest  -> reads as the focus of the paper
    #0f9d96  Burst-HADS    L 0.60
    #c47e12  HADS          L 0.68  lightest

CVD separation worst pair dE 14.2 (protan), normal-vision floor 21.2, all
three clear 3:1 contrast against white. Colour alone is NOT enough in
greyscale, though: teal and amber sit only 0.08 apart in lightness. Every
bar therefore carries a hatch and every line a distinct marker + dash, so
the figures survive a photocopier and a monochrome printer. That is not
optional decoration -- it is the secondary encoding the palette check
requires.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ── canvas sizes (inches) ────────────────────────────────────────────────
# IEEEtran, US Letter, two columns: \columnwidth = 3.487in,
# \textwidth = 7.16in. Leave a hair of slack so nothing overfulls.
W_SINGLE = 3.40
W_DOUBLE = 7.00
H_1PANEL = 2.35
H_ROW    = 2.30
H_SHORT  = 1.95

# ── type ─────────────────────────────────────────────────────────────────
# Serif, to sit with IEEEtran's Times body text. Caption text in the paper
# is 8pt, so nothing inside a figure should be larger than that.
RC = {
    "font.family":       "serif",
    "font.serif":        ["Times New Roman", "Nimbus Roman",
                          "DejaVu Serif", "serif"],
    "font.size":          8,
    "axes.titlesize":     8,
    "axes.labelsize":     8,
    "xtick.labelsize":    7,
    "ytick.labelsize":    7,
    "legend.fontsize":    7,
    "figure.dpi":         150,
    "savefig.dpi":        600,
    "axes.linewidth":     0.6,
    "xtick.major.width":  0.6,
    "ytick.major.width":  0.6,
    "xtick.major.size":   2.5,
    "ytick.major.size":   2.5,
    "lines.linewidth":    1.4,
    "lines.markersize":   4.0,
    "patch.linewidth":    0.5,
    "legend.frameon":     False,
    "legend.handlelength": 1.6,
    "legend.handletextpad": 0.5,
    "legend.columnspacing": 1.2,
    "axes.grid":          True,
    "grid.color":         "#d9dde2",
    "grid.linewidth":     0.4,
    "axes.axisbelow":     True,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.01,
}
plt.rcParams.update(RC)

# ── identity: colour + hatch + marker, assigned in fixed order ───────────
S = ["HADS", "Burst-HADS", "R-BurstHADS"]

C = {
    "HADS":        "#c47e12",
    "Burst-HADS":  "#0f9d96",
    "R-BurstHADS": "#1d4aa3",
}
HATCH = {                      # bars: greyscale + forced-colors fallback
    "HADS":        "///",
    "Burst-HADS":  "\\\\\\",
    "R-BurstHADS": "",
}
MARK = {                       # lines: greyscale fallback
    "HADS":        ("o", (0, (4, 2))),
    "Burst-HADS":  ("s", (0, (1.5, 1.5))),
    "R-BurstHADS": ("^", "-"),
}

INK      = "#1c1f24"
INK_SOFT = "#5b636e"
ZERO     = "#9aa2ad"           # the y=0 reference line on delta charts


def _dress(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd7")
    ax.tick_params(colors=INK_SOFT)
    return ax


def single(h=H_1PANEL, nrows=1, **kw):
    """One column wide. ONE panel, or two stacked at most."""
    fig, axes = plt.subplots(nrows, 1, figsize=(W_SINGLE, h), **kw)
    for ax in ([axes] if nrows == 1 else axes):
        _dress(ax)
    return fig, axes


def double(ncols=3, h=H_ROW, nrows=1, **kw):
    """DEPRECATED for this paper -- single column, one graph per figure.
    Kept only so older scripts still import."""
    fig, axes = plt.subplots(nrows, ncols, figsize=(W_DOUBLE, h), **kw)
    flat = axes.ravel() if hasattr(axes, "ravel") else [axes]
    for ax in flat:
        _dress(ax)
    return fig, axes


def grouped_bars(ax, categories, values_by_series, ylabel=None,
                 series=None, width=0.26, gap=0.02):
    """Grouped bars with a 2px surface gap between adjacent bars, hatched
    for greyscale. values_by_series maps series name -> list over
    categories."""
    series = series or [s for s in S if s in values_by_series]
    n = len(series)
    idx = range(len(categories))
    for k, name in enumerate(series):
        off = (k - (n - 1) / 2) * (width + gap)
        ax.bar([i + off for i in idx], values_by_series[name],
               width=width, label=name, color=C[name],
               hatch=HATCH[name], edgecolor="white", linewidth=0.6,
               zorder=3)
    ax.set_xticks(list(idx))
    ax.set_xticklabels(categories)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK)
    ax.grid(axis="x", visible=False)
    return ax


def trend(ax, x, values_by_series, ylabel=None, xlabel=None, series=None):
    """Line chart with per-series marker + dash, so identity survives
    greyscale."""
    series = series or [s for s in S if s in values_by_series]
    for name in series:
        m, ls = MARK[name]
        ax.plot(x, values_by_series[name], marker=m, linestyle=ls,
                color=C[name], label=name, markeredgecolor="white",
                markeredgewidth=0.5, zorder=3)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    return ax


def zero_line(ax, label="HADS baseline"):
    """Reference line for any chart whose y axis is a percentage change.

    On a "change vs HADS" chart, HADS IS the zero line -- it must not also
    appear as a flat series, which wastes a legend slot and draws invisible
    bars. Plot the two other schedulers and label the line instead."""
    ax.axhline(0, color=ZERO, linewidth=0.7, zorder=2)
    if label:
        ax.annotate(label, xy=(0.995, 0), xycoords=("axes fraction", "data"),
                    xytext=(0, 2), textcoords="offset points",
                    ha="right", va="bottom", fontsize=6, color=INK_SOFT)
    return ax


def legend_above(fig, ax, ncol=None):
    """One legend for the whole figure, in a reserved strip above the axes.

    ncol defaults by canvas width: three across fits the 7.0in canvas, but
    at 3.4in three 8pt entries collide with the plot, so a single-column
    figure gets two columns and a taller reserved strip. That collision is
    what made the first draft of these figures unreadable."""
    h, l = ax.get_legend_handles_labels()
    wide = fig.get_size_inches()[0] > 5.0
    if ncol is None:
        ncol = 3 if wide else 2
    rows = -(-len(l) // ncol)
    fig.legend(h, l, loc="lower center", ncol=ncol,
               bbox_to_anchor=(0.5, 1.0), frameon=False,
               fontsize=7 if wide else 6.5,
               handlelength=1.6 if wide else 1.3,
               columnspacing=1.2 if wide else 0.9)
    fig._legend_rows = rows
    return fig


def save(fig, stem, outdir="paper/fig"):
    """PDF for LaTeX (vector, never resampled) and PNG for previewing."""
    import os
    os.makedirs(outdir, exist_ok=True)
    rows = getattr(fig, "_legend_rows", 0)
    h_in = fig.get_size_inches()[1]
    top = 1.0 - (rows * 0.13 + 0.02) / h_in if rows else 1.0
    fig.tight_layout(pad=0.3, rect=[0, 0, 1, top])
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(outdir, f"{stem}.{ext}"))
    plt.close(fig)
    return os.path.join(outdir, stem + ".pdf")
