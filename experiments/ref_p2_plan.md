# TCC23 §3.2 in full: the reference-faithful Part 2 (pre-registration)

Parent: tag `freeze-fix21`, code fingerprint `2439a00d7f74`. Written and
committed before the runs. A measurement: the code on disk does not change,
and the missing step is disclosed, not adopted (owner, 2026-09-23).

## Why

The U5 counterfactual measured so far — the guard removed, violators left on
spot — is neither our behaviour nor TCC23's. TCC23 §3.2 sends those violators
to the cheapest regular on-demand VMs, and we never implemented that step
(`diag_part2.txt`: 575 of 2,400 runs leave 12,150 violators on spot). So
+2.57% is a sensitivity to half-following the reference, and it flatters our
choice (owner, 2026-09-23).

## Variants (`experiments/variants.py`, `_burst_fill2(guard, od_step)`)

A copy of `BurstHADS._allocate_burstable_vms` with §3.2's three steps:
1. violators to the burstables, one task each, in baseline mode (under the
   U5 guard when `guard`);
2. **new:** violators still on spot to the cheapest regular on-demand VMs;
3. an idle burstable takes the latest-finishing task.

Step 2 places as `_initial_solution`'s Phase 3 does: running on-demand VMs
cheapest first, then a fresh VM of the cheapest on-demand type within its
instance limit, each judged against D by `_check_schedule`. A violator that
no on-demand VM can take by D within the limits stays where it is.

| variant | guard | step 2 | what it is |
|---|---|---|---|
| `p2_copy` | kept | no | faithful copy of the frozen method; must reproduce it exactly |
| `p2_od` | kept | yes | the missing step alone: DEVIATIONS' measured effect for the new row |
| `ref_p2` | removed | yes | **reference-faithful**: §3.2 as published |

`nocap+` forms of all three run with the launch limits off.

**Reading of step 2 when the guard is kept.** §3.2 conditions step 2 on there
being "no available burstable VM". With the guard, violators can remain while
burstables are still idle, a state §3.2 never reaches. `p2_od` applies step 2
to every remaining violator, the maximal reading, and is therefore an upper
bound on the missing step's effect in the frozen configuration. `ref_p2` is
unambiguous: without the guard the burstables fill first.

Both patch the shared method, so Burst-HADS and R-BurstHADS change together;
HADS is unaffected and its rows come from the baselines.

## Runs

- Sweep catalogue, Burst-HADS and R-BurstHADS, seeds 0–29, limits on and off:
  all three variants. `p2_copy` and `nocap+p2_copy` must reproduce their
  baselines exactly; a failure stops the batch.
- Validation catalogue (`diag_cost_gap.py`, 3 copies, 30 seeds, limits off):
  `nocap+p2_copy` (must reproduce `diag_cost_gap_fix21_nocap_c3`),
  `nocap+p2_od` and `nocap+ref_p2`.

## Reported

**The U5 sensitivity table the paper cites**, limits on and off, over each
set's complete cells and over the matched cells:

| row | configuration |
|---|---|
| as frozen | the guard, no step 2 |
| guard removed only | neither our behaviour nor TCC23's |
| reference-faithful | §3.2 in full |

with R-BurstHADS against Burst-HADS on cost and makespan, dominance, the
significance counts, and, for each scheduler, missed tasks, runs with a miss
and infeasible runs. The missing step alone (`p2_od`) is reported in the same
tables as the register row's measured effect.

Validation catalogue: Burst-HADS's cost change against HADS, the makespan
reduction and the hibernation premium, against TCC23's +1.92%, 25.87% and
+25%.

**No direction is predicted.** A smoke test on three sc1 n = 50 DF 0.25 runs
showed step 2 moving about 22 tasks per run and changing both cost and
makespan materially in both directions, so the effect is reported by
configuration rather than summarised in advance.
