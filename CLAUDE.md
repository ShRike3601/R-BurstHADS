# R-BurstHADS — project context

Read this before doing anything. It is the handoff from the session that
did the audit and the fixes, and it exists so you do not have to rebuild
the reasoning from scratch.

## What this is

A discrete-event simulator comparing three Bag-of-Tasks schedulers for
AWS spot / burstable / on-demand fleets under hibernation:

- **HADS** — Teylo et al., Cluster Computing 2021. Baseline. No concept
  of a burstable market at all; `scheduler/hads.py` structurally never
  places a task on one.
- **Burst-HADS** — Teylo et al., IEEE TCC 2023. Adds burstable rescue
  (Algorithm 4) and work stealing (Algorithm 5) on top of HADS.
- **R-BurstHADS** — our extension. Adds deadline-aware preemptive and
  reactive spot provisioning on top of an unmodified Burst-HADS.

Target output is a paper. Owner is a final-year student; the supervisor
wants many comparison figures and tables.

## Ground rules that have governed this work

1. **Do not sugarcoat.** Every number below was arrived at by finding a
   bug that made our result look better and removing it. Several of the
   fixes cost us the headline. That is the job.
2. **Fix specifications, not outcomes.** Every change must be defensible
   as restoring a stated formula, removing a dimensional error, or
   removing an asymmetry between our scheduler and the baselines — never
   as "this made the number better." Three separate fixes moved numbers
   in our favour; each one has a written justification in the code
   comments that does not reference the result.
3. **Measure before asserting.** Hypotheses about why something happened
   get tested with a diagnostic, not written up as findings. One
   hypothesis (`MAX_VMS_PER_EVENT` binding) was confidently stated and
   turned out to be flatly wrong — `cap=10` and `cap=40` are identical.
4. **Verify before reporting.** A stale staged copy of `metrics.py` once
   nearly produced a reported 31-point cost inflation that did not
   exist. Check the live file.

## Layout

```
main.py                       VM pools, task generation, deadline formula,
                              run_simulation(), PER_CORE_SPEED table
models/vm.py                  VM state, billing intervals, credits,
                              start_next_if_free (multi-core dispatch)
models/task.py                exec_time, checkpointing, baseline_mode
metrics/metrics.py            makespan, deadline_misses, total_cost
simulation/events.py          TaskComplete / Hibernation / Termination
simulation/resume_event.py    hibernated -> idle, restarts billing
simulation/allocation_cycle_event.py   900s idle shutdown
simulation/provisioning_event.py       boot latency + spot risk exposure
policies/work_stealing.py     Algorithm 5
scheduler/hads.py             baseline 1
scheduler/burst_hads.py       baseline 2 (ILS, Algorithm 4, Dspot)
scheduler/r_burst_hads.py     ours (Theorem 1/2, select_vm tiers)
experiments/checkpoint.py     small parallel sweep, --df, --seeds, --tag
experiments/billing_audit.py  3 billing policies on one config
experiments/template_ab.py    forced instance type x VM-count cap A/B
experiments/dynamic_comparison.py   the full 30-seed sweep
_fix_scratch/                 pre-fix backups, one per change
paper/                        IEEE paper, technical report, trace report
```

## Key mechanics you will need

- `speed` is **per core**. Whole-machine throughput is
  `speed * vcpu_count`. Anything dividing a rate by `speed` alone is a
  bug — that exact error has now been found and fixed in three places
  (Equation 8's WRR weight, `spot_pool_throughput`, Theorem 1's
  `c_reactive`).
- `PER_CORE_SPEED` in `main.py` is the single source for speeds. Do not
  hardcode a speed anywhere.
- Deadline: `D = DF * DEADLINE_SLACK * ideal_makespan(n)`, floored at
  `min_feasible_deadline()`. `DEADLINE_SLACK = 3.0`. Since DF and
  DEADLINE_SLACK only ever appear as a product, sweeping DF makes the
  constant non-load-bearing — **report across DF, do not recalibrate.**
- Billing is one rule: launch to genuine shutdown. `total_cost()`
  measures the true simulation end;
  `TaskCompleteEvent._release_fleet_if_done()` terminates every surviving
  VM (hibernated ones included, or they resume post-makespan and restart
  the meter) when the last task completes.
- A burstable VM holds **exactly one task at a time**, in both baseline
  and burst mode. Verified against the paper's pseudocode.
- Table 9 scenarios: `lambda_h = kh/D`, `lambda_r = kr/D`.
  sc1(1,0) sc2(5,0) sc3(1,5) sc4(5,5) sc5(3,2.5).

## Fix history, and why each one mattered

Each has a backup in `_fix_scratch/`.

1. **Fairness** (`r_burst_hads.py`) — tiers 1 and 4 of `select_vm` tested
   only `can_fit_task` plus a flat deadline check, bypassing
   `_check_migration` and therefore the Section 3.4 spot spare-time rule
   that Burst-HADS enforces on every spot target. Our own provisioned
   machines were exempt from a rule the baseline obeyed. Now routed
   through `_check_migration`; tier 4 writes the rule out explicitly
   because the VM has not booted and `estimate_finish_time` has no notion
   of boot delay.
2. **Billing** (`metrics.py`, `events.py`) — `total_cost` passed
   `sim_end = makespan()`, which only clamps **open** intervals. A VM
   killed by the 900s idle timer kept its real end, well past the job.
   One number, three rules. On the n=40 trace the post-makespan tail was
   ~75% of every reported cost.
3. **Post-makespan resume** (`events.py`) — hibernated VMs were skipped
   at fleet release, stayed resumable, and `ResumeEvent` restarts billing
   unconditionally. Machines woke after the job ended and were billed for
   another 900s. It penalised finishing early in exact proportion: HADS
   6.1%, R-BurstHADS 21.4%.
4. **Per-core speed** (`main.py`) — `speed` scaled with instance size
   *and* `vcpu_count` did too, so a c5.xlarge was modelled as retiring 4x
   a c5.large's work for 2x the price. This was the single largest
   artefact in the study: it was most of the cost advantage over HADS.
5. **Instance selection tie-break** (`r_burst_hads.py`) — with the double
   count gone, c5.large and c5.xlarge tie at 130.7 units/$ as they should
   (same silicon, 2x size, 2x price). A survival-weighted score separated
   them by 1% using a lambda the module docstring itself calls
   illustrative, and picked the smaller machine — costing up to 36%
   makespan, measured. Survival is now a **filter** (drop anything below
   even odds of surviving to D, which correctly annihilates m5.xlarge at
   0.0013), then rank on capacity per dollar, ties to the larger machine.
6. **Theorem 1 normalisation** — `c_reactive` divided rates by `speed`
   not `speed*vcpu_count`, and the on-demand side had a hardcoded `/2`.
   Switching the template to c5.xlarge therefore halved the benefit and
   doubled the cost at once, making the test ~4x harder; preemptive
   provisioning silently switched off and R-BurstHADS went bit-identical
   to Burst-HADS at n=60.
7. **Theorem 1 epsilon** — the docstring states
   `C_proactive = T_startup * r_s + epsilon`; the code substituted the
   full cost of running one average task for epsilon, 2.6x the startup
   term, dominating every decision. An absolute compared against a
   differential. Restored to the stated form.

## Where the result stands

Five cells (sc1/sc2/sc4/sc5 at n=300, sc2 at n=100) x three deadline
factors (0.5, 1.0, 2.0) x 10 seeds. All billing policies agree, so cost
is unambiguous.

Relative to HADS, averaged over all 15 cells:

| | makespan | cost |
|---|---|---|
| Burst-HADS | −24.4% | **+32.4%** |
| R-BurstHADS | **−41.5%** | −5.1% |

R-BurstHADS dominates Burst-HADS on **both** axes in **14 of 15** cells.

**The contribution statement this supports:** Burst-HADS buys makespan by
paying a ~32% cost premium over HADS, in every cell without exception,
which is the trade its own paper describes. R-BurstHADS delivers a larger
makespan improvement and hands the premium back.

Claims that are **dead** and must not reappear: "cheaper and faster than
everything", any cost advantage over HADS above ~5% on average, and the
old −52%/−74% figures (those were the speed artefact).

## Open items

- **sc1 is the weak regime.** kh=1, low interruption rate:
  R-BurstHADS costs +24.9% against HADS on average, worsening with more
  deadline slack (+7.6 / +22.6 / +44.4). Cause is known and stated in a
  code comment: Theorem 1 does not price the replacement's **expected
  idle time**. It is billed from boot whether or not the hibernation it
  anticipates ever arrives, and at kh=1 it usually does not. Fixing this
  is the single highest-value remaining change.
- **DF=0.5 sc4** is the one dominance break: +3.5% makespan against
  Burst-HADS, though −23.2% on cost. Tight deadline with resumes.
- **The baselines satisfice.** HADS lands at 90–100% of D in nearly every
  cell because it only escalates when D is threatened. Makespan
  percentages are therefore partly a statement about how much slack D
  granted. This is why results are reported across a DF span and why the
  `mk/D` column exists. State it in the paper; do not hide it.
- **HADS misses deadlines at DF=2.0 and not at DF=1.0** (3.7 and 2.2
  misses in sc1). A baseline degrading with *more* slack reads as broken.
  Explanation — Burst-HADS's ILS fitness normalises makespan by `Dspot`,
  so slack makes makespan cheap to spend and the optimiser packs onto
  fewer machines — is **asserted, not yet measured.** Instrument the ILS
  and confirm before it goes in the paper.
- **Work stealing onto a baseline-mode burstable is not slack-checked**
  the way a burst-mode rescue is. On the n=40 trace it put the
  makespan-defining task on the slowest machine in the fleet.
- **Fix 1's isolated effect was never measured** — the pre-fix baseline
  was not captured before the first checkpoint. Recoverable by restoring
  `_fix_scratch/r_burst_hads.py.pre_migcheck` and re-running.
- Figures: the owner has a separate unresolved issue with graph
  generation. **Do not generate figures until they raise it.**

## Commands

```powershell
# small sweep, ~8 min on 18 cores; diffs against previous tags
python experiments\checkpoint.py --tag NAME --workers 18
python experiments\checkpoint.py --tag NAME_df050 --workers 18 --df 0.5
python experiments\checkpoint.py --tag NAME_df200 --workers 18 --df 2.0

# one config, three billing policies, fast
python experiments\billing_audit.py --n 300 --seed 0 --kh 5 --kr 0

# forced instance type x VM-count cap
python experiments\template_ab.py --workers 18 --seeds 5

# the full 30-seed sweep — only when the fixes are settled
python experiments\dynamic_comparison.py
```

Always run all three DF points together. A single DF point is not
trustworthy on its own — that is the lesson of the deadline sweep.
