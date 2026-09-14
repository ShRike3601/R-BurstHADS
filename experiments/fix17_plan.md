# Fix 17 — pre-registered interpretations and measurement plan

Written and committed before any fix-17 run. Owner's instruction
(2026-09-15): the three defects in `RBurstHADS._respond_to_saturation` found
by the U10 diagnostic (`experiments/diag_u10.txt`, commit 3772258) are
fidelity bugs of the class of fixes 1–16; the freeze is lifted for this work;
each sub-fix is a counterfactual variant first, measured alone and in
combination, and adopted into the scheduler only after the adopted code
reproduces its variant bit for bit on a fixed seed set. The adoption decision
per sub-fix is the owner's.

## Interpretations (fixed now, before seeing results)

All three are switches on one copy of the frozen method (`_sat17(a, b, c)` in
`experiments/variants.py`); all off (`f17_copy`) must reproduce the frozen
sweep row for row.

- **17a — deadline test and fallback.** In the re-placement loop a target is
  eligible only if it passes `_check_migration(task, vm, t, D,
  burst_mode=vm.is_burstable)`: memory, finish by D, CPU credits for a
  burst-mode burstable, and the Section 3.4 spare-time margin for a spot
  target — the test tier 0 (`_select_replacement_vm`) applies to the same
  provisioned VMs, and the test Burst-HADS's migration applies. Among eligible
  targets the earliest estimated finish wins, as before. If no target is
  eligible the task goes through Algorithm 4's on-demand attempt
  (`_attempt_ondemand_fallback`: a running on-demand VM that passes
  `_check_migration`, else a new on-demand VM of the cheapest type within its
  limit, else the capped fallback) instead of the late placement. The late
  `all_targets[0]` fallback is not used when 17a is on.
- **17b — no reshuffle without capacity.** After the frozen `n_extra <= 0`
  return, and before any queued task is removed: if not even one VM of the
  kind the response would launch is within its instance limit (the spot
  template when `use_spot`, else t3.large), return. When at least one VM can be
  launched the frozen behaviour is unchanged.
- **17c — trigger on real saturation.** Replace `if len(active_spot) >=
  len(self.spot_vms): return` (acts when any one spot VM is down) with `if
  active_spot: return` (acts only when no spot VM in `spot_vms` is active), the
  condition the code's own comment states ("Only act when pool is actually
  saturated (all spot VMs down)"). `spot_vms` is taken as the code holds it:
  pool spot VMs (launched or not) plus R-BurstHADS's provisioned spot VMs.

## Measurement

Base: frozen sweep `experiments/sweep_raw_4f08f48ac35c.jsonl` (limits on), never
overwritten. Variants run through `experiments/variant_sweep.py`; fix-17 and
boot variants patch R-BurstHADS only and run with `--keys rburst`, HADS and
Burst-HADS taken from the frozen file.

1. `f17_copy` (all 30 seeds) must reproduce the frozen R-BurstHADS rows; else stop.
2. `f17a`, `f17b`, `f17c` alone; `f17ab`, `f17abc` in combination; all 30 seeds.
3. Report (`experiments/fix17_compare.py`), leading with R-BurstHADS's cost vs
   Burst-HADS: first on the 22 cells where the frozen R-BurstHADS missed a task,
   then on the full sweep; missed tasks, makespan and cost against frozen;
   provisioning and launches, to flag behaviour change breadth (17c).
4. Adoption (only for sub-fixes the owner chooses): the adopted code must
   reproduce its variant row for row on seeds 0–9 of the full grid.

## Two measurements requested alongside

- **Checkpoint over-credit per scheduler.** Record-only probe over all 7,200
  frozen runs (`experiments/diag_overcredit_boot.py`): displaced running tasks,
  progress credited (elapsed × speed) and executed (elapsed × speed / (1 + ovh))
  per scheduler. Effect: `ckpt_exec` (credits executed progress) vs `ckpt_copy`,
  all schedulers.
- **Tasks starting on VMs before they are ready.** Same probe: starts on
  R-BurstHADS-provisioned VMs before `ready_time`, by VM market, with the head
  start in seconds. Effect: `boot_wait` (no start before `ready_time`, finish
  estimates from `ready_time`) vs `boot_copy`.
