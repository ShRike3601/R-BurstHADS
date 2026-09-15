# Fix 21: deploy time for every VM a scheduler launches (pre-registration)

Parent: tag `freeze-fix20`, code fingerprint `d40a1c917c63`. Written and
committed before any fix-21 run. Nothing below is conditional on a result
except the stop rules.

## Justification (the register entry; it cites no result)

The model says a newly launched VM takes time to deploy. TCC23 defines ω as
"Time overhead to deploy a new VM" and charges it in Algorithm 4 Attempt 3's
deadline test. The committed paper defines T_start as "instance start-up
latency", says on-demand instances "carry a start-up latency", and launches
replacement instances "ready at t + T_start". The simulator's
`STARTUP_LATENCY = 45 s` stands for both.

**21a: on-demand VMs launched mid-run, every scheduler.** The fallback's
deadline test charges ω, but execution does not: a VM launched mid-run runs
its first task at once. Fix 18 corrected this for the spot VMs R-BurstHADS
provisions. 21a corrects it for every VM launched mid-run by any scheduler.
Charging boot latency to the class of VM our method provisions, while
exempting the class the baselines rely on, would be an asymmetry in the
published model, whichever direction it moves the numbers.

**21b: burstables R-BurstHADS launches mid-run.** Zero start-up latency is
correct for burstables present from t = 0. Those are deployed during setup,
before the clock starts, which is the exemption every scheduler's initial
fleet receives. It is not correct for a burstable launched mid-run: a t3 is
an EC2 instance, and nothing makes it boot faster than a c5.
- TCC23 never launches a burstable mid-run, so its zero-latency treatment was
  never exercised in that regime.
- Its Section 3 availability statement ("availability is ensured during the
  whole execution") is about revocation, not readiness, so it does not license
  carrying the assumption across.
- R-BurstHADS applied an assumption valid for a standing fleet to a context
  it was never tested in. Its code states that assumption in three places:
  - module docstring: "Burstable VMs if: deadline too tight for spot startup";
  - `select_vm`: "a burstable, which is ready at once";
  - ProvisioningEvent: "zero for burstable VMs, which paper Section 3 treats as
    always on-demand-available".

In this branch the deadline tests and execution already agree with each
other, so 21b changes both:
- the burstable waits T_start;
- the tier-3 burstable deadline test (`_provision_one_more`) charges T_start;
- the saturation response's sizing (`_vms_needed_for_deadline`, the startup
  argument for the burstable choice) charges T_start.

**21c: decisions at t = 0.** Under the invariant below, three launches at
t = 0 are scheduling decisions and must pay deploy time.
- **Proactive burstables.** Burst-HADS creates new t3.large VMs from the
  template during primary scheduling (Algorithm 1 Part 2:
  `_allocate_burstable_vms` → `_launch_burstable_vms`). The builder's pool
  seeds only one burstable, which is never launched.
- **New on-demand VMs in the primary schedules.** HADS Phase (c) and
  Burst-HADS Phase 3 call `_launch_new_ondemand_vm(0.0, tpl)`.
- **The precedent.** R-BurstHADS already pays for its own t = 0 replacement:
  `_preemptive_provision` creates it with `ready_time=STARTUP_LATENCY`.

R-BurstHADS inherits both of Burst-HADS's primary-schedule steps. The static
planners that judge these VMs start those VMs' cores at the boot offset, so
test and execution agree. The planners concerned:
- `_vm_makespan_static` in HADS and Burst-HADS;
- `_solution_task_finish_times` and `_baseline_finish`;
- the Phase-3 probe VM.

## Expected direction (recorded; not a criterion)

- **21a** is expected to move results in R-BurstHADS's favour. HADS and
  Burst-HADS escalate to on-demand far more often: at freeze-fix20 there were
  8,289 fresh-VM draws over 7,200 runs (HADS 5,767, Burst-HADS 1,589,
  R-BurstHADS 933; `diag_u10_window.txt`). Under 21a they begin paying deploy
  time they now get free.
- **21b** is expected to move results against R-BurstHADS: its mid-run
  burstables start waiting.
- **21c** is expected to be small and of unclear direction. All three
  schedulers' primary schedules make these launches, and R-BurstHADS inherits
  the proactive burstables from Burst-HADS.
- **21a and 21b are adopted together for that reason.** They rest on the same
  model statement and are expected to move results in opposite directions.
  21c goes in with the same justification. No sub-fix is adopted without the
  others.

## Invariant (stated, enforced, verified)

> Capacity built by the VM builder before the simulation starts is exempt from
> deploy time. Anything a scheduler launches as a scheduling decision, at any
> simulated time including t = 0, pays it: the VM runs no task before its launch
> time + T_start, and every test that predicts a finish on it charges T_start.

The two clauses meet where a builder-built VM is launched by a decision.
Resolved in advance as follows:

- **At t = 0, inside the primary schedule: exempt.** This covers the pool spot
  VMs the primary schedule selects, and the builder's one on-demand VM per type
  that Phase 3 / Phase (c) use before creating new ones. They are the initial
  fleet, as the first clause states. Charging them would extend the fix in
  R-BurstHADS's favour on a reading the owner did not state. The consequence,
  identical for all three schedulers: the first on-demand VM of each type a
  primary schedule uses is free, and later ones pay.
- **Mid-run: pays; this is part of 21a.** Burst-HADS's Attempt 3 candidate loop
  runs over every non-hibernated on-demand VM, launched or not. `can_launch`
  admits a never-launched pool VM whenever its type has room, so the loop can
  launch one mid-run. `_capped_fallback`, in HADS and Burst-HADS, can do the
  same. Such a VM waits T_start, and the candidate test charges it while the VM
  is not yet launched.
- **Not a launch:** a hibernated VM resuming.

**Enforcement.**
- A launched VM that is not exempt carries `ready_time = launch + T_start`.
- `VM.start_next_if_free` and `VM.estimate_finish_time` already honour
  `ready_time` (fix 18).
- R-BurstHADS's VMs keep their ProvisioningEvent.
- Every other VM that is handed a task while booting gets a ready event at
  `ready_time`. It only calls `start_next_if_free`: no scheduler call, no
  work stealing, no Allocation Cycle arming. So the only thing it changes is
  the start time.

**Verification: `experiments/diag_launch21.py`, record-only.**
- **What it logs.** Every VM's first `LaunchCounter.commit`: time, phase
  (primary schedule or run), whether the builder built it, market, and calling
  routine. Also every VM's first task start.
- **Pass condition.** The invariant holds if and only if no non-exempt VM starts
  a task before launch + T_start.
- **Runs.**
  - freeze-fix20: a census that gives the complete launch-site map; violations
    are expected here.
  - variant f21: must show 0 violations.
  - the adopted code: must show 0 violations.

Found while reading, not part of fix 21: Burst-HADS's Attempt 3 candidate loop
takes never-launched pool on-demand VMs as though they were running, without
Attempt 3's ω test. This parallels U6. The census counts it, and it goes to the
register as open.

## Variants (`experiments/variants.py`, `_f21`)

| variant | contents |
|---|---|
| `f21_copy` | every copied routine installed, T_start = 0; must reproduce freeze-fix20 exactly on all 7,200 rows |
| `f21a`, `f21b`, `f21c` | each sub-fix alone |
| `f21` | 21a + 21b + 21c |
| `f21_no_a`, `f21_no_b`, `f21_no_c` | f21 without one sub-fix |
| `f21_no20` | f21 with fix 20 reverted in the fallback walks |

Validation catalogue variants: `nocap+f21a`, `nocap+f21c`, `nocap+f21`,
`nocap+f21_copy` (limits off), and `f21` (limits on). The validation runs
contain HADS and Burst-HADS only, so 21b does not apply.

## Measurements

**Main sweep.** Against `sweep_raw_d40a1c917c63.jsonl`, limits on, 30 seeds,
all schedulers.
- **Per scheduler, for every set:**
  - runs changed. Tolerance: makespan within 1e-9 s, cost within 1e-12 $,
    same missed tasks. Reproduction checks are exact.
  - missed tasks;
  - mean makespan change and mean cost change.
- **Cell aggregates, over the cells where every scheduler is feasible in every
  seed:**
  - the four headline pairs: R-BurstHADS vs HADS and vs Burst-HADS, on cost
    and makespan;
  - Burst-HADS vs HADS on cost and makespan, as its own number, computed from
    the runs;
  - dominance;
  - significantly cheaper, dearer, faster and slower.
- **Attribution.** Individual effect = set − base. Contribution within the
  set = f21 − f21_no_x. No additivity is assumed.
- **Fix 20 once VMs wait for boot.** Runs changed, f21 against f21_no20, per
  scheduler. This is stated from measurement.

**Validation catalogue** (`diag_cost_gap`, paper catalogue, 3 copies,
30 seeds).
- **Limits off:** nocap+f21a, nocap+f21c and nocap+f21 against
  `fix20_nocap_c3`. The T9 quantities go against TCC23: Burst-HADS cost change
  vs HADS, makespan reduction, and both hibernation premiums.
- **Limits on:** f21 against `fix20_capped_c3`.

**R-BurstHADS's burstable branch.**
- **Paths:** tier 3 (`_provision_one_more`) and the saturation response.
- **When:** before 21b (freeze-fix20) and after it (f21b, f21).
- **Rates:**
  - firings per run;
  - firings as a share of all placements;
  - tasks placed on burstables that branch launched, as a share of all
    placements.

  A placement is every `VM.reserve_memory` call except `start_execution`'s
  re-reservation at t = 0.
- **What selects the burstable, for each tier-3 firing:** one of
  - slack ≤ 2·T_start, so spot is not tried;
  - the spot finish is past D;
  - the spot spare-time rule;
  - the spot launch limit.

  The saturation response chooses a burstable only when slack ≤ 2·T_start.

## Stop rules

1. If, after 21b, the burstable branch fires in no run on either path (f21b
   and f21), stop before adopting and report. That would make part of the
   published contribution dead code.
2. If the invariant is violated on f21 or on the adopted code, or the census
   finds a launch site outside the map above, stop and amend this plan before
   adopting.
3. If a part of the fix that moves results in R-BurstHADS's favour turns out to
   rest on a contestable reading of the model, stop.

## Adoption and new baseline

1. **Adoption patch.** `experiments/fix21_adopt_patch.py` mirrors `_f21`
   statement for statement.
2. **Export check.** Applied to a clean export, the adopted code must
   reproduce f21 row for row on seeds 0–9, all schedulers.
3. **Adopt,** then re-run the baseline:
   - checkpoint runs (tag fix21);
   - the full sweep, which must equal f21 for all 30 seeds;
   - `sweep_analysis`;
   - the limits-off sweep;
   - validation runs, limits off and on.
4. **Verify the adopted code** with `diag_launch21`: 0 violations, and branch
   firings equal to f21's.
5. **Re-tag** `freeze-fix21`.
6. **Regenerate** RESULTS_PACK.md and the six figures in one pass. Figures go
   to `experiments/fig_fix21/`; nothing under `paper/` changes.

**In that pass:**
- a stated tolerance for runs-changed counts;
- Burst-HADS vs HADS as its own key number;
- Fig. 6 replaced by limits on against limits off, on both axes, over the 75
  cells fully feasible in both sweeps. A matched table is added to the pack,
  because T1's 75 cells and T2's 80 cells are not comparable.
- new tables for sub-fix accounting, branch firings and invariant
  verification.

## Prose audit (after the numbers settle)

One consolidated list of every prose claim that is now false, with corrected
wording, across:
- CLAUDE.md;
- PAPER_SKELETON.md;
- RESULTS_PACK.md (strings in `results_pack.py`);
- FIGURE_SPEC.md;
- `paper/paper.tex`.

It also flags every composed or derived percentage that was not computed
directly from the runs, including the percentages the pack derives itself.
