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

## Two things the toolkit now enforces

**Legend placement.** Three 8 pt legend entries do not fit across 3.4 in, so
they used to sit on top of the plot. `legend_above()` now lays the legend
out in two columns at 6.5 pt in a reserved strip above the axes, sized from
the number of rows it actually needs.

**HADS is the zero line, not a series.** On any "change vs HADS" chart,
plotting HADS gives a flat line at zero: an invisible set of bars and a
wasted legend slot. Plot the other two schedulers and call `zero_line(ax)`,
which draws and labels the baseline. HADS appears as a real series only in
Fig. 6, where the quantity is absolute.

## Placement

```latex
\begin{figure}[!t]
  \centering
  \includegraphics{fig/fig1_headline.pdf}   % NO width= — already 3.40in
  \caption{...}
  \label{fig:headline}
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

All numbers come from `RESULTS_PACK.md` only. Each figure names its table.

**Fig. 1 — headline trade-off.** Grouped bars, two groups (makespan, cost),
two series. Limits on. Source T1. This is what the abstract points at.
Caption must state that these are the 75 cells feasible for every scheduler
in every seed, and give the all-80-cell figures (26.4 % and 11.9 %) too.

**Fig. 2 — cost against deadline slack.** Two lines over
DF ∈ {0.25, 0.5, 1.0, 2.0}. Source T1/T3. Shows R-BurstHADS crossing from
dearer to cheaper as slack grows. Set `ax.set_xticks(x)` explicitly.

**Fig. 3 — makespan against deadline slack.** Two lines, same x axis.
Source T1/T3. Separate from Fig. 2 because four lines on one axis at this
width is unreadable, and because the two quantities move in opposite
directions — which is the point.

**Fig. 4 — cost by interruption scenario.** Grouped bars over sc1–sc5, two
series. Source T5/T1. This is where sc3 appears and where the sc1 weakness
is visible instead of buried in an average.

**Fig. 5 — cost against bag size.** Two lines over n ∈ {50, 100, 200, 300}.
Source T1/T3. Include this specifically because the advantage *reverses*:
at n = 300 R-BurstHADS is 1.1 % more expensive than Burst-HADS. A figure
that shows its own limit is worth more than one that doesn't.

**Fig. 6 — missed tasks.** Grouped bars, two groups (limits on, limits off),
three series — here HADS is a real series. Source T5/T7. Under limits:
HADS 0, Burst-HADS 1 task in 1 run, R-BurstHADS 109 tasks in 104 runs.
Without limits all three miss nothing.

## Wording the figures and captions must respect

Claude Code's audit of the results pack found three lead claims that do not
match the data. Use the corrected forms everywhere, including captions:

- The cost premium falls from 21.3 % to 12.9 %, an **8.4-point cut — 39 % of
  the premium**. Not "roughly half".
- R-BurstHADS is **not the only scheduler that misses**: Burst-HADS misses
  1 task in 1 run under limits. HADS misses none.
- The misses are **not demonstrably "caused by the cap"**. Every missing run
  had hit a launch limit, but so had 93.5 % of its clean runs, so hitting a
  limit does not single out the misses. The evidence is the matched
  counterfactual: the same 7,200 runs without limits miss nothing.
- 27.9 % and 12.7 % are over the 75 fully feasible cells; over all 80 they
  are 26.4 % and 11.9 %. State which is which.
- Under limits R-BurstHADS is significantly **slower** than Burst-HADS in 9
  cells and **dearer** in 7. This belongs in Fig. 4's or Fig. 5's caption.

## Everything else is a table

The results pack already holds them. Map straight across:

| paper table | pack source |
|---|---|
| instance catalogue | T15 |
| experiment grid | T2 |
| headline results, limits on / off, ± 95 % CI | T1, T2 |
| per-cell means ± CI | T3, T4 |
| both miss measures, infeasible runs | T5, T6, T7 |
| validation against TCC23, incl. what fails | T8–T11, T14 |
| deviation register (appendix) | T12, T13, T16, T17 |

T6 (validation failures) and the deviation register are not padding. They
turn "our baselines do not reproduce TCC23's hibernation cost" from a hole
into a disclosed, quantified limitation, and they are what makes the rest
of the paper credible.

Six figures, seven tables. That satisfies "many comparisons" without a
single float landing in the wrong place.
