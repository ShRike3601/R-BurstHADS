# U5 re-measured at freeze-fix21 (pre-registration)

Parent: tag `freeze-fix21`, code fingerprint `2439a00d7f74`. Written and
committed before the runs. This is a measurement for the owner's decision on
U5, not a candidate fix. It carries no decision rule and adopts nothing.

## Why

The figure disclosed with U5 dates from the Round A closing grid (RESULTS_PACK
T12; `grid_2x2_sweep.txt`). With the guard R-BurstHADS was −5.3% cost against
Burst-HADS, dominating it in 34 of 55 cells; without it, +5.8% and 14 of 55.

That was measured on:
- code `519c868a99f9`;
- the sweep catalogue, limits on, seeds 0–9;
- the 55 cells where every scheduler was feasible.

That state predates the three-type on-demand catalogue (E1/E3) and fixes 17a
to 21. E1/E3 alone took Burst-HADS's missed tasks from 1,981 to 0 [T13], and
those misses were the evidence the pre-registered rule used to keep the guard.

Nothing since has re-measured the guard, so whether either figure holds at
freeze-fix21 is unknown.

**No direction is predicted.**

## Variants (`experiments/variants.py`)

- **`fill_copy`, `nocap+fill_copy`:** `_burst_fill(True)`, a copy of
  `BurstHADS._allocate_burstable_vms`.
  - At freeze-fix21 its body matches the frozen method line for line.
  - It calls `_launch_burstable_vms`, `_solution_task_finish_times` and
    `_baseline_finish` through `self`, so fix 21's versions are used.
  - It must reproduce the baseline sweeps exactly (makespan, cost, misses,
    infeasibility) for Burst-HADS and R-BurstHADS.
  - A failure stops the batch.
- **`burst_fill`, `nocap+burst_fill`:** `_burst_fill(False)`, the guard
  removed as TCC23 §3.2's text describes.
  - Dspot violators move to the burstables.
  - An idle burstable takes the latest-finishing task.

Both patch the shared method, so the guard is on or off for Burst-HADS and
R-BurstHADS together, as in the grid. HADS has no such step, so its rows come
from the baselines.

Runs:
- the sweep catalogue, Burst-HADS and R-BurstHADS, seeds 0–29, limits on
  (`sweep_raw_2439a00d7f74`) and off (`sweep_variant_nocap_2439a00d7f74`);
- the validation catalogue (`diag_cost_gap.py`, 3 copies, 30 seeds):
  - `nocap+fill_copy`, which must reproduce `diag_cost_gap_fix21_nocap_c3`;
  - `nocap+burst_fill` and `burst_fill`.

## Reported

For each limit setting, guard kept against removed.

1. **Fidelity:** rows identical between each copy and its baseline.
2. **Per scheduler (Burst-HADS, R-BurstHADS), on its own runs:**
   - missed tasks, and runs with a miss;
   - infeasible runs;
   - runs changed;
   - mean paired makespan and cost change;
   - the grid rule's two counts: runs that go from no missed task with the
     guard to at least one without it, and the reverse.

   The counts are reported, not applied.
3. **Over the cells where every scheduler is feasible in every seed:**
   - Burst-HADS vs HADS, R-BurstHADS vs HADS and R-BurstHADS vs Burst-HADS,
     on cost and makespan;
   - dominance;
   - significantly faster, slower, cheaper and dearer.

   Reported for all cells and by DF, stating whether the cell set moves.
   Repeated over the matched cells feasible in all four sets.
4. **Continuity with T12:** the same comparison over the grid's 55 cells,
   limits on, seeds 0–29.
5. **Validation catalogue, limits off and on:**
   - Burst-HADS vs HADS cost change and makespan reduction;
   - Burst-HADS's hibernation premium, against TCC23 (+1.92%, 25.87%, +25%).
