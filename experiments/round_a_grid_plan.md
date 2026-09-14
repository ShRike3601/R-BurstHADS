# Round A closing grid — pre-registered design and decision rules

Written and committed BEFORE any grid run (owner's instruction, 2026-09-14:
"Measure the 2x2 … DECIDE FROM THAT GRID AND THEN FREEZE, whatever it
shows. No further measurement in Round A after it."). No direction is
predicted here.

## Is E10 a defect? Settled from the sources, not from the grid

- TCC23 §3.3: "Burst-HADS has a termination policy where the allocation time
  is logically divided into units denoted Allocation Cycles (ACs). A vmj that
  reaches the end of its current AC, denoted AC curj, in idle state, is
  terminated." Cycles tile the VM's allocation time; nothing restarts a cycle
  when a VM becomes idle.
- Reference implementation (github.com/luanteylo/hads_):
  `Dispatcher.next_period_end` computes `ceil(uptime / ac_size_seconds) *
  ac_size_seconds` from `vm.start_time`, plus hibernated time (uptime excludes
  hibernation); `ScheduleManager` terminates an idle non-burstable dispatcher
  when `next_period_end - now < idle_slack_time`.
- Ours: `VM.start_ac` sets `ac_termination_time = now + 900` whenever a VM
  becomes idle.

Therefore E10 is a defect (code contradicts its specification) and is
adopted in Round B **whatever the grid shows**. The grid measures its effect
and settles the guard. The variant ends the cycle exactly at the period end;
the reference's `idle_slack_time` margin is not modelled (recorded).

## Grid

Base state = what Round B adopts regardless: migration restricted to launched
VMs (U6/H2) and billing from launch (B1, TCC23 §3.1). Variants in
`experiments/variants.py`:

| cell | guard (U5) | E10 |
|---|---|---|
| g1e0 | on (code on disk) | off (code on disk) |
| g0e0 | off (TCC23 text) | off |
| g1e1 | on | on (cycles over uptime) |
| g0e1 | off | on |

Catalogues:
- **Validation**: `diag_cost_gap.py --variant nocap+grid_<cell> --copies 3
  --seeds 30` (paper catalogue, Table 6 workload, uncapped — the Round A
  setting). Compared with `diag_cost_gap_compare.py`.
- **Sweep**: `variant_sweep.py --variant grid_<cell> --base-fp 519c868a99f9`
  (sweep catalogue, capped, seeds 0–9, full grid). Compared with
  `grid_2x2_sweep.py`.

Faithfulness checks run first; a failure stops the grid:
- `nocap+ac_copy` (the E10 patch in "idle" mode) must reproduce
  `diag_cost_gap_nocap_c3` run for run (cost and makespan).
- `nocap+mig_launched+launch_bill`'s cost must equal
  `diag_cost_gap_nocap_mig_launched_c3`'s post-hoc LAUNCH cost in every run
  whose decisions B1 cannot change; the number of runs that differ is
  reported (B1 makes a launched idle VM `is_deployed`, so it can now receive
  an Allocation Cycle — a faithful side effect).

## Decision rules

1. **E10**: adopted (above).
2. **B1, U6/H2**: adopted (settled before the grid).
3. **Guard (U5)**, decided on the E10-on cells, g1e1 against g0e1, paired
   by run (same job/scenario/seed or sweep unit):
   - For Burst-HADS and for R-BurstHADS separately, in each catalogue, count
     runs that go from 0 missed tasks with the guard to ≥ 1 without it
     ("guard-protected"), and runs that go the other way ("guard-harmed").
   - The guard is **needed for makespan** iff, for Burst-HADS or R-BurstHADS
     in either catalogue, guard-protected > guard-harmed.
   - Needed → keep it; disclose it in DEVIATIONS U5 as an addition to the
     published algorithm, with the protected / harmed counts, the missed
     tasks and the makespan change that justify it.
   - Not needed → drop it (Round B adopts `burst_fill` semantics).
   Symmetric by construction: it does not favour keeping or dropping.
4. Whatever the result, Round B then adopts, re-runs the sweep (with and
   without instance limits) and tags the freeze. Nothing in this grid
   reopens Round A.
