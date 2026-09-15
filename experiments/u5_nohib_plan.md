# Two diagnostics before the limitation text and the register check (pre-registration)

Parent: tag `freeze-fix21`, code fingerprint `2439a00d7f74`. Written and
committed before the runs. Both are measurements only; neither changes code
or carries a decision rule.

## 1. The U5 guard without hibernation

**Owner's proposed reading, to be tested before it is written.** Without the
guard, Burst-HADS reproduces TCC23's no-hibernation makespan and "collapses
under hibernation". That would point to a defect in the hibernation rescue
path that the guard masks.

**Facts already recorded:**
- On the validation catalogue the guard-free Burst-HADS misses 0 tasks with
  and without hibernation, limits on and off (`diag_cost_gap_u5off_*_c3`).
- The collapse (980 of 2,400 runs with a miss) is on the sweep catalogue
  (`u5_remeasure_compare.txt`), where every scenario hibernates and deadlines
  come from DF.
- Whether hibernation is needed for that collapse is therefore not known.

**Run:**
- Sweep catalogue, scenario `none`: no hibernation or resumption events.
- Every n and DF, seeds 0–29, limits on.
- HADS, Burst-HADS and R-BurstHADS.
- Variants `u5nohib_kept` (the frozen code) and `u5nohib_removed` (guard
  removed, `_burst_fill(False)`).

**Reading, fixed in advance.** Compare the guard-free Burst-HADS's runs with a
miss without hibernation against the 980 of 2,400 with hibernation:
- If it misses in a comparable share of runs without hibernation, the
  collapse does not come from the hibernation rescue path.
- If it misses in almost none, hibernation is necessary for it.

**Also reported, by DF:**
- missed tasks and runs with a miss;
- mean makespan and cost against HADS;
- the guard-kept values.

## 2. How often the two remaining additions fire

The register check for a second added or departed baseline behaviour, like
U5, names two rows whose exposure is unrecorded.

- **U3, Burst-HADS Phase 3.** The reference `IPDPS.py` raises "no solution"
  when no spot VM takes a task; ours places it on an on-demand VM.
  - Measured from the existing launch probe `diag_launch21_adopted.json`, no
    new run.
  - Reported: runs per scheduler whose primary schedule launches an on-demand
    VM, overall, by DF, and within the 75 fully feasible cells.
  - HADS's Phase (c) is in the reference (`CCScheduler.create_primary_map`)
    and is reported for comparison only.
- **E2, `_capped_fallback`.** The reference `backup_heuristic` leaves a task
  unallocated when the on-demand limits are spent; ours waits it on the
  active VM that would finish it soonest.
  - Record-only probe `experiments/diag_capped.py`, sweep catalogue, limits
    on, seeds 0–29, all three schedulers.
  - Every probed row must equal the baseline sweep row exactly.
  - Reported: placements and runs with one, by scheduler and DF; overrides
    past the limit; misses in those runs; exposure within the 75 cells.
  - With limits off every type always has room, so it cannot fire.
