# Figures — record (not prose)

Built by `experiments/make_figures.py` from `RESULTS_PACK.md` only (values parsed
from its tables; nothing typed by hand), with `experiments/ieee_figs.py`, per
`experiments/FIGURE_SPEC.md`. Single column, one graph each, 3.35 in wide,
Times New Roman embedded as TrueType (no Type 3). Simulator untouched
(`freeze-round-b`, fingerprint `4f08f48ac35c`).

Cell sets: **Figs. 1–5 = limits on, the 75 cells where every scheduler is feasible in
every seed** (T1). **Fig. 6 = all feasible runs**, not a cell subset (T5).

## Fig. 1 — `fig1_headline.pdf`
- Source: T1, row `all` (75 cells).
- Plotted, change vs HADS: Burst-HADS makespan −19.1%, cost +21.3%; R-BurstHADS makespan −27.9%, cost +12.9%.
- Caption facts:
  - 75 fully feasible cells; over all 80 cells (T1 last row): R-BurstHADS makespan −26.4% vs HADS and −11.9% vs Burst-HADS; cost +12.2% vs HADS against Burst-HADS's +20.0%.
  - Cost premium over HADS 21.3% → 12.9%: an 8.4-point cut, 39% of the premium (Key numbers).
  - R-BurstHADS vs Burst-HADS: makespan −12.7%, cost −5.4%, dominates in 44/75 cells (T1 all).

## Fig. 2 — `fig2_cost_vs_df.pdf`
- Source: T1, rows `DF=0.25` (15 cells), `DF=0.5`, `DF=1.0`, `DF=2.0` (20 cells each).
- Plotted, cost change vs HADS: Burst-HADS +9.7 / +18.6 / +24.2 / +30.0%; R-BurstHADS +8.4 / +18.6 / +16.6 / +7.1%.
- Caption facts:
  - R-BurstHADS vs Burst-HADS cost −1.3 / −0.0 / −4.3 / −14.9% (T1 DF rows). The two are equal at DF 0.5; R-BurstHADS's premium over HADS falls as slack grows while Burst-HADS's rises.
  - **No dearer-to-cheaper crossing** (see conflicts below).

## Fig. 3 — `fig3_makespan_vs_df.pdf`
- Source: T1, DF rows as Fig. 2.
- Plotted, makespan change vs HADS: Burst-HADS −7.3 / −6.2 / −13.1 / −46.6%; R-BurstHADS −8.9 / −7.4 / −27.0 / −63.6%.
- Caption facts: R-BurstHADS vs Burst-HADS makespan −1.8 / −1.4 / −15.9 / −28.9% (T1 DF rows).

## Fig. 4 — `fig4_scenarios.pdf`
- Source: T1, rows `sc1`–`sc5` (15 cells each).
- Plotted, cost change vs HADS: Burst-HADS +36.3 / +20.2 / +24.8 / +12.6 / +12.8%; R-BurstHADS +19.8 / +18.8 / +10.4 / +10.2 / +5.5%.
- Caption facts:
  - R-BurstHADS vs Burst-HADS cost −9.8 / −1.3 / −9.5 / −1.0 / −5.3%; cells significantly cheaper / dearer: sc1 11/0, sc2 5/3, sc3 7/0, sc4 3/3, sc5 3/1 (T1 scenario rows).
  - Over all 75 cells R-BurstHADS is significantly slower than Burst-HADS in 9 cells and dearer in 7 (T1 all).

## Fig. 5 — `fig5_cost_vs_n.pdf`
- Source: T1, rows `n=50` (20 cells), `n=100` (15), `n=200` (20), `n=300` (20).
- Plotted, cost change vs HADS: Burst-HADS +32.4 / +28.1 / +14.5 / +12.1%; R-BurstHADS +11.5 / +16.5 / +11.4 / +13.2%.
- Caption facts:
  - **Reversal confirmed in the pack:** at n = 300 R-BurstHADS is +1.1% vs Burst-HADS (T1 `n=300`, R $ vs B); R vs B by n: −12.3 / −8.6 / −2.6 / +1.1%.
  - At n = 300 it dominates Burst-HADS in 5/20 cells; significantly cheaper in 3, dearer in 2 (T1 `n=300`).
  - Without limits there is no reversal: n = 300 R vs B −12.8% (T2 `n=300`).

## Fig. 6 — `fig6_missed_tasks.pdf`
- Source: T5 (missed tasks, feasible runs).
- Plotted: limits on HADS 0, Burst-HADS 1, R-BurstHADS 109; limits off 0, 0, 0.
- Caption facts:
  - Limits on: HADS 0 in 2,390 feasible runs; Burst-HADS 1 task in 1 of 2,400 runs; R-BurstHADS 109 tasks in 104 of 2,400 runs (4.3%) (T5).
  - The same 7,200 runs without limits miss nothing (T5 off). This matched counterfactual is the evidence linking the misses to the limits.
  - Hitting a limit does not single out the misses: 104/104 missing R-BurstHADS runs had reached a launch limit, and so had 2,146/2,296 (93.5%) of its clean runs (T7).

## Conflicts between FIGURE_SPEC.md and the pack (pack used)

1. **Fig. 2** "R-BurstHADS crossing from dearer to cheaper as slack grows": not in the pack. On T1's DF rows R-BurstHADS is never dearer than Burst-HADS (−1.3, −0.0, −4.3, −14.9%) and never cheaper than HADS (+8.4 to +18.6%). What the data show: the two coincide at DF 0.5, then diverge.
2. **Fig. 4** source "T5/T1": scenario costs are in T1 only; T5 is deadline misses. And "the sc1 weakness": sc1 is where R-BurstHADS's premium over HADS is highest (+19.8%), but also where its cost lead over Burst-HADS is largest (−9.8%). Its weakest scenarios against Burst-HADS are sc4 (−1.0%) and sc2 (−1.3%), with 3 significantly dearer cells each.
3. **Fig. 5** reversal: present (+1.1%, T1 `n=300`). No change needed.
4. **Table map** "headline results, limits on / off, ± 95% CI | T1, T2": T1/T2 carry no CIs on the aggregates, only significance counts. Per-cell CIs are T3/T4.
5. **Table map** "experiment grid | T2": T2 is the limits-off results; the grid is in the pack header.
6. **Spec text** "T6 (validation failures)": T6 is the infeasible runs; the validation failures are T8–T11 and T14.
7. **Spec text** "Six figures, seven tables": the table map lists seven rows that draw on 15 pack tables; no conflict in the numbers, noted only.
