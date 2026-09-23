# Figure plan — single column, one graph per figure

## The constraint

**Every figure is single column (3.40 in) and contains exactly one graph.**
No `figure*`, no multi-panel figures, no subplots. Anything that would need
a second panel becomes a table instead.

This is a hard rule, not a preference. It removes the float-placement
problem entirely: a single-column `figure` can sit at the top or bottom of
either column on its own page, so nothing gets pushed to the end of the
paper.

Use `single()` from `ieee_figs.py`. Do not use `double()` — it is left in
the module only so old scripts still import, and it must not appear in this
paper.

## Two things the toolkit enforces

**Legend placement.** Three 8 pt legend entries do not fit across 3.4 in, so
they used to sit on top of the plot. `legend_above()` lays the legend out in
two columns at 6.5 pt in a reserved strip above the axes, sized from the
number of rows it actually needs.

**Absolute values, three real series, y axis from zero** (owner,
2026-09-23). Every figure plots seconds or dollars, with HADS, Burst-HADS
and R-BurstHADS all drawn. Percentage changes against HADS live in the
tables and never in a chart.

This reverses the earlier rule that HADS was the zero line and must not be
plotted. `zero_line()` stays in `ieee_figs.py` for older scripts but is not
used by any figure in this paper, and `make_figures.py` no longer imports
it. A chart of changes hides the quantities being traded: at DF 0.25 a
7 percentage-point difference is a few cents, at DF 2.0 the same difference
is not, and the reader cannot see that from a bar of percentages.

## Placement

```latex
\begin{figure}[!t]
  \centering
  \includegraphics{fig/fig1_cost_vs_df.pdf}   % NO width= — already 3.40in
  \caption{...}
  \label{fig:cost-df}
\end{figure}
```

Omitting `width=` is deliberate. The PDF is already correct; passing a width
rescales it and drops the type to 4 pt, which is what made the old figures
unreadable.

## Colour

Validated with the dataviz checker — all six checks pass on a light surface
under `--pairs all`.

| series | hex | L |
|---|---|---|
| HADS | `#c47e12` | 0.68 |
| Burst-HADS | `#0f9d96` | 0.60 |
| R-BurstHADS | `#1d4aa3` | 0.43 — darkest, so it reads as the paper's focus |

Teal and amber sit only 0.08 apart in lightness, so colour alone fails on a
monochrome printer. Every bar carries a hatch and every line a distinct
marker and dash. That is the required secondary encoding — do not strip it.

## The six figures

The set is orthogonal: **cost and makespan, each against deadline factor,
interruption scenario and bag size.** All six read one table, **T1b**
(absolute cell-mean makespan and cost, limits on, the 75 cells where every
scheduler is feasible in every seed). `make_figures.py` parses T1b out of
`RESULTS_PACK.md`, so a figure cannot drift from the pack.

| figure | file | chart | x axis |
|---|---|---|---|
| 1 | `fig1_cost_vs_df.pdf` | three lines | DF ∈ {0.25, 0.5, 1.0, 2.0}, log₂ |
| 2 | `fig2_makespan_vs_df.pdf` | three lines | the same |
| 3 | `fig3_cost_vs_scenario.pdf` | grouped bars | sc1–sc5, labelled with (kh, kr) |
| 4 | `fig4_makespan_vs_scenario.pdf` | grouped bars | the same |
| 5 | `fig5_cost_vs_n.pdf` | three lines | n ∈ {50, 100, 200, 300} |
| 6 | `fig6_makespan_vs_n.pdf` | three lines | the same |

Lines for DF and n because both are ordered magnitudes; bars for scenarios
because they are categories. Cost figures are in dollars, makespan figures
in seconds, both axes starting at zero.

## What the captions must say

Each caption names the cell set (75 cells, limits on, every scheduler
feasible in every seed) and points at the table holding the percentage
changes for the same cells (T1, and T27 for the headline pair). Cite pack
cells rather than repeating numbers here, so this file cannot go stale
against the pack.

- **Makespan is the primary claim, qualified** (owner, 2026-09-23). It holds
  in every working configuration measured. The qualification travels with
  it: at DF 0.5 the advantage over Burst-HADS is roughly a wash, with more
  cells significantly slower than faster [T1 DF=0.5]. Figs. 2, 4 and 6
  carry it.
- **Cost is conditional**, and the condition belongs in the cost captions:
  the cost advantage over Burst-HADS depends on the retained U5 guard and on
  launch headroom [T12, T2b], and it reverses without hibernation
  [`u5_nohib_compare.txt`], which is expected of a scheduler that provisions
  in anticipation of interruptions.
- **Dominance** means both cell means no greater, means only [T1 caption].
- **Misses** are floor-cell rescues, and the floor cells are excluded from
  the averages: state which figure covers which cells [T5, T6].
- Never present a composed percentage (a ratio of two averaged changes) as
  measured; the pack marks the premium share as derived.

## Everything else is a table

The results pack holds them. Map straight across:

| paper table | pack source |
|---|---|
| instance catalogue | T15 |
| experiment grid | pack header |
| headline trade-off against HADS (the former Fig. 1) | T27, with T1 |
| headline results, limits on and off | T1, T2, T2b |
| limits on against limits off (the former Fig. 6) | T2b |
| absolute makespan and cost behind the figures | T1b |
| per-cell means ± 95 % CI | T3, T4 |
| both miss measures, infeasible runs | T5, T6, T7 |
| validation against TCC23, including what fails | T8–T11, T14 |
| the U5 sensitivity, the guard and the reference-faithful Part 2 | T12 |
| deviation register and adoption checks | T16, T17 |
| post-freeze fixes and the deploy-time invariant | T18–T26 |

T8–T11 and T14 (the validation failures) and the deviation register are not
padding. They turn "our baselines do not reproduce TCC23's hibernation cost"
from a hole into a disclosed, quantified limitation, and they are what makes
the rest of the paper credible.

**The limits result gets its own called-out paragraph in the results text**
(owner, 2026-09-23), not only a table row: it is the strongest finding in
the work, and as a row in T2b it disappears.
