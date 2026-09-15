# R-BurstHADS without its burstable branch: a diagnostic (pre-registration)

Parent: tag `freeze-fix21`, code fingerprint `2439a00d7f74`. Written and
committed before the runs. This is a measurement, not a candidate fix:
nothing it finds is adopted.

## Question

What does R-BurstHADS's burstable branch do? The branch is where a burstable
is created mid-run: tier 3 (`_provision_one_more`) and the saturation
response. It is measured by disabling it, with launch limits on and off.

**Hypothesis under test (owner):** the tier protects feasibility rather than
cost. It pays a 1.15× premium over the on-demand alternative [RESULTS_PACK
T15]. That premium is part of why R-BurstHADS's cost advantage over
Burst-HADS falls from 14.1% (limits off) to 4.6% (limits on) over the same 75
cells [T2b].

The tier's description is written from what comes back, not from the
hypothesis.

Facts already established:
- **Limits on:** the branch fires 0.61 times per run, and 96% of firings are
  the spot type at its launch limit [T24].
- **Limits off:** it fires 0.36 times per run (`diag_f21_verify.txt` §3).

## Variant

`experiments/variants.py`, `_no_burst_branch`:
- Both routines test `can_launch_type("ondemand", BURST_TYPE)` before creating
  a burstable; that test answers False when called from either routine.
- Tier 3 therefore returns nothing, and the task goes to Algorithm 4 Attempt 3
  (an on-demand VM, under its own launch limits).
- The saturation response creates no burstable.
- Every other launch test is untouched, including Burst-HADS's and
  R-BurstHADS's proactive burstables at t = 0.

Variants, R-BurstHADS rows only, 30 seeds:
- `no_burst_branch` (limits on);
- `nocap+no_burst_branch` (limits off).

HADS and Burst-HADS rows come from the baseline sweeps, which the branch
cannot affect.

**Built-in check:** in both variant sweeps, R-BurstHADS's t3.large launches
equal Burst-HADS's in every unit, i.e. zero branch firings.

## Reported, for each limit setting, with and without the branch

- **R-BurstHADS on its own runs:**
  - missed tasks and runs with a miss;
  - infeasible runs;
  - mean makespan and cost change, paired per run;
  - runs changed (tolerance as in the pack).
- **Over the cells where every scheduler is feasible in every seed:**
  - R-BurstHADS vs HADS and vs Burst-HADS, on cost and makespan;
  - dominance;
  - significantly cheaper, dearer, faster and slower.

  Whether that cell set moves is stated.
- **Matched limits-on against limits-off contrast, as T2b:** R-BurstHADS vs
  Burst-HADS cost and makespan, with and without the branch, over the cells
  feasible in all four sets.

## Reading, fixed in advance

- **"Protects feasibility":** disabling the branch raises R-BurstHADS's missed
  tasks or infeasible runs with limits on.
- **"Pays for it in cost":** disabling it lowers R-BurstHADS's mean cost with
  limits on.
- **"The premium is part of the on/off gap":** R-BurstHADS vs Burst-HADS cost
  with limits on moves toward the limits-off value once the branch is
  disabled.

Each is reported as found or not found. The numbers themselves are reported
either way.
