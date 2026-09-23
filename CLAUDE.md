# R-BurstHADS — project context

Read this before doing anything. It is the handoff from the sessions that
did the audit and the fixes, and it exists so you do not have to rebuild
the reasoning from scratch. It has also been wrong before: verify a claim
against the live code and the evidence files before building on it, and
correct this file when it is wrong.

## What this is

A discrete-event simulator comparing three Bag-of-Tasks schedulers for
AWS spot / burstable / on-demand fleets under hibernation:

- **HADS** — Teylo et al., Cluster Computing 2021. Baseline. No concept
  of a burstable market at all; `scheduler/hads.py` structurally never
  places a task on one. Its primary scheduler is the single-pass greedy
  ported from CCScheduler — **no ILS**.
- **Burst-HADS** — Teylo et al., IEEE TCC 2023. Adds the ILS primary
  scheduler, burstable rescue (Algorithm 4) and work stealing
  (Algorithm 5) on top of HADS.
- **R-BurstHADS** — our extension. Adds deadline-aware preemptive and
  reactive spot provisioning on top of an unmodified Burst-HADS.

Reference implementation for both baselines: github.com/luanteylo/hads_
(`control/scheduler/CCScheduler.py`, `IPDPS.py`, `input/*/env.json`).

Target output is a paper. Owner is a final-year student; the supervisor
wants many comparison figures and tables.

## Ground rules that have governed this work

1. **Do not sugarcoat.** Every number below was arrived at by finding a
   bug that made our result look better and removing it. Several of the
   fixes cost us the headline. That is the job.
2. **Fix specifications, not outcomes.** Every change must be defensible
   as restoring a stated formula, removing a dimensional error, or
   removing an asymmetry between our scheduler and the baselines — never
   as "this made the number better." When two principled fixes exist,
   choose between them before seeing their results (fixes 11 and 12 were
   decided that way) and keep the other as a recorded sensitivity.
3. **Measure before asserting.** Hypotheses about why something happened
   get tested with a diagnostic, not written up as findings. Confidently
   stated hypotheses that turned out wrong: `MAX_VMS_PER_EVENT` binding;
   sc1's premium being unpriced idle time; HADS's misses being a result
   (fix 8); Burst-HADS's residual misses being a property (fix 11).
   Unexplained misses have been a bug every time so far.
4. **Verify before reporting.** A stale staged copy of `metrics.py` once
   nearly produced a reported 31-point cost inflation that did not
   exist. This file once pinned post-fix numbers to a pre-fix
   observation. Check the live file.
5. **Stopping rule (owner, 2026-09-14).** Round A: diagnose the shared
   hibernation cost gap, adopting nothing until its cause is named.
   Round B: adopt the settled fidelity fixes, rerun the sweep with and
   without instance limits, then FREEZE the simulator and tag the commit.
   Round C: final sweep, confidence intervals, write-up — no code changes.
   After `freeze-round-b` the owner lifted the freeze twice, for fixes
   17a–20 and for fix 21, each pre-registered. From `freeze-fix21` a newly
   found defect goes into DEVIATIONS.md as a limitation, not into the code;
   measurement runs (pre-registered counterfactuals and diagnostics)
   continue. While a freeze is lifted, a baseline
   change is allowed only for (a) an asymmetry, (b) a dimensional error,
   (c) code contradicting its own specification, or (d) a defect that
   makes a baseline worse than published — never because the baseline's
   design is merely suboptimal. Every baseline change is recorded in
   `DEVIATIONS.md` with its measured effect.

## Layout

```
main.py                       VM pools, task generation, deadline formula,
                              run_simulation(), PER_CORE_SPEED table
models/vm.py                  VM state, billing intervals, credits,
                              start_next_if_free (multi-core dispatch)
models/task.py                exec_time, checkpointing, baseline_mode
models/limits.py              instance limits (fix 12), LaunchCounter,
                              NoFeasibleSchedule
metrics/metrics.py            makespan, deadline_misses, total_cost
simulation/events.py          TaskComplete / Hibernation / Termination
simulation/resume_event.py    hibernated -> idle, restarts billing
simulation/allocation_cycle_event.py   900s idle shutdown
simulation/provisioning_event.py       boot latency + spot risk exposure
policies/work_stealing.py     Algorithm 5
scheduler/hads.py             baseline 1 (greedy, no ILS)
scheduler/burst_hads.py       baseline 2 (ILS, Algorithm 4, Dspot)
scheduler/r_burst_hads.py     ours (Theorem 1/2, select_vm tiers)
experiments/checkpoint.py     5-cell parallel sweep: --df --seeds --tag --variant
experiments/variants.py       counterfactual patches: measure a fix before making it
experiments/variant_sweep.py  the full grid under a variant, vs a base sweep file
experiments/dynamic_comparison.py   the full sweep: plan / run / summarize
experiments/sweep_analysis.py       sweep aggregates + check against checkpoints
experiments/sweep_*_<fp>.*    full-sweep results, one set per code fingerprint
experiments/diag_*.py         diagnostics behind fixes 8-11 and the sc1 decision
experiments/probe_grid.py     deadline-tightness probe (pre-fix-8)
experiments/billing_audit.py  3 billing policies on one config
experiments/template_ab.py    forced instance type x VM-count cap A/B
_fix_scratch/                 pre-change backups for fixes 1-7 (git from fix 8)
paper/                        IEEE paper, technical report, trace report -- ALL PRE-FIX
```

**Version control.** This folder is its own git repo (branch `main`),
separate from the parent `C:\my folder\projects` repo, and is pushed to
the **private** GitHub repo `ShRike3601/R-BurstHADS`. Every checkpoint and
sweep result file is committed. Pushing needs GitHub's "block command line
pushes that expose my email" setting off, because commits carry the
owner's address.

A Claude Code desktop session started from the parent folder runs in a
worktree of the parent repo, where Write/Edit refuse every file in this
folder. Start sessions in this folder.

## Key mechanics you will need

- `speed` is **per core**. Whole-machine throughput is
  `speed * vcpu_count`. Anything dividing a rate by `speed` alone is a
  bug — found and fixed in three places (Equation 8's WRR weight,
  `spot_pool_throughput`, Theorem 1's `c_reactive`).
- Every finish-time **prediction** must carry `(1 + checkpoint_overhead)`,
  because execution (`VM.start_next_if_free`) always charges it (fixes 8,
  10), and must list-schedule a queue in **execution order**, memory
  descending, because multi-core list scheduling is order-dependent
  (fix 11). The HADS / Burst-HADS `_attempt_ondemand_fallback` deadline
  test is start + omega + remaining / speed × (1 + ovh) (fix 20). It
  changes no run in either catalogue, because no dearer on-demand type
  runs a task faster than a cheaper one (DEVIATIONS U10). The Section
  3.4 spare-time margin deliberately uses `exec_time / speed`, as the paper
  states it.
- **Deploy time.** Every VM a scheduler launches, at t = 0 or mid-run, runs
  no task before launch + `STARTUP_LATENCY` (45 s, `VM.ready_time`), and
  every finish predicted on it charges that, as execution does (fixes 18,
  21). Only the builder's initial fleet, deployed by a primary schedule at
  t = 0, is exempt.
- Eq 9: an infeasible candidate scores 1.0, which is only an upper bound
  on feasible scores if normalised cost is <= 1, so the normaliser covers
  every VM the search can use — the spot pool plus the initial solution's
  on-demand VMs (fix 11).
- **Instance limits** (fix 12, `models/limits.py`), from the reference:
  5 on-demand and 5 preemptible instances per type, global 20 / 20;
  burstable instances count as on-demand; counts are of launches and
  never decrease. Each catalogue has three on-demand types (fix 16), walked
  cheapest first within their limits, so the ceiling is 15 regular
  on-demand VMs and 20 on-demand launches including burstables. At a limit
  the primary schedule skips the type and, if no type can take a task,
  raises `NoFeasibleSchedule` — recorded by the sweep as an **infeasible
  run**, not an error. Migration at a spent limit places the task on the
  active VM that would finish it soonest (the reference leaves it
  unallocated, which would drop it from every metric; launches forced past
  a limit are counted in `limit_overrides`: 0 in all 7,200 runs of the
  freeze-fix21 sweep; the fallback itself placed a task on an active VM in
  only 12 Burst-HADS and 11 R-BurstHADS runs, all at DF 0.25,
  `diag_capped.txt`). R-BurstHADS's own provisioning is limited too. The
  pool holds `SPOT_COPIES = 3` spot VMs per type, under the limit of 5, so
  the spot limit binds only on R-BurstHADS's launches: at freeze-fix21 it
  reaches a launch limit in 2,281 of its 2,400 runs [T7], and the spot
  limit is what selects 1,401 of its 1,453 mid-run burstables [T24].
- Feasibility is decided by the primary schedule. At freeze-fix21 only HADS
  is ever infeasible: 110 runs, all in the five n = 100, DF = 0.25 cells at
  the deadline floor [T6], so cross-scheduler cell means exclude a cell
  with an infeasible HADS seed. Its t = 0 on-demand VMs now wait their
  deploy time; with limits off every one of those runs is feasible
  (DEVIATIONS E14). Burst-HADS and R-BurstHADS are feasible everywhere only
  because of our Phase 3 addition (DEVIATIONS U3): the reference raises
  "no solution" where Phase 3 places a task, which it does in all 150 runs
  of those cells and in 905 of 2,400 runs overall (`u3_exposure.txt`).
- `PER_CORE_SPEED` in `main.py` is the single source for speeds. Do not
  hardcode a speed anywhere.
- Deadline: `D = DF * DEADLINE_SLACK * ideal_makespan(n)`, floored at
  `min_feasible_deadline()` (339.7 s). `DEADLINE_SLACK = 3.0`. Since DF
  and DEADLINE_SLACK only ever appear as a product, sweeping DF makes the
  constant non-load-bearing — **report across DF, do not recalibrate.**
  In the sweep grid the floor binds at n=50 for DF ≤ 0.5 (so those two
  DF points are the same cell) and at n=100 for DF = 0.25. The floor has
  no deploy-time term; since fix 21 it binds HADS's feasibility in the
  n = 100, DF = 0.25 cells (DEVIATIONS E14).
- Billing is one rule: launch to genuine shutdown (TCC23 §3.1). A VM's
  meter opens when a scheduler launches it (`LaunchCounter.commit`, fix
  13), used or not, and stops on hibernation or termination.
  `total_cost()` measures the true simulation end;
  `TaskCompleteEvent._release_fleet_if_done()` terminates every surviving
  VM (hibernated ones included) when the last task completes. Burstable
  VMs are never idle-terminated, so they are billed from launch to the end.
- Idle termination: a non-burstable VM idle at the end of its CURRENT
  900 s Allocation Cycle is terminated, cycles counted over its billed
  uptime (`VM.start_ac`, fix 14; TCC23 §3.3, reference
  `Dispatcher.next_period_end`).
- Migration (HADS stages 1–2, Burst-HADS Attempts 1–2) takes only VMs the
  run has launched (fix 15); stage / Attempt 3 launches on-demand capacity:
  Burst-HADS's first takes any on-demand pool VM with launch room, launched
  or not (DEVIATIONS U11), then a fresh VM from M^o.
- **Our Burst-HADS departs from TCC23's Algorithm 1 Part 2 in two ways, and
  from Algorithm 2 in one.** §3.2 has three steps: Dspot violators to the
  burstables, the violators left over to the cheapest regular on-demand
  VMs, and an idle burstable takes the latest-finishing task. Ours adds the
  improvement guard to step 1 (DEVIATIONS U5, kept by the pre-registered
  Round A grid) and has no step 2 at all (DEVIATIONS U12), so violators the
  guard declines stay on spot past Dspot: 12,150 of them in 575 of 2,400
  runs, all at DF ≤ 0.5 (`diag_part2.txt`). Algorithm 2 has only spot
  phases and the reference raises "no solution" where ours falls back to
  on-demand (DEVIATIONS U3). All three are disclosed in the paper body and
  measured; none is adopted or removed.
- A burstable VM holds **exactly one task at a time**, in both baseline
  and burst mode. Verified against the paper's pseudocode.
- Table 9 scenarios: `lambda_h = kh/D`, `lambda_r = kr/D`, for **every**
  spot VM, of every type, including those launched mid-run (fix 9).
  sc1(1,0) sc2(5,0) sc3(1,5) sc4(5,5) sc5(3,2.5).
- **Declared per-type hibernation rates** (`main.py`) are not used by any
  Table 9 hibernation process and by no WRR weight (Eq 8 has no risk
  term). Only R-BurstHADS reads them: Theorem 1 fires for the three
  m5.xlarge and no c5 VM (P ~0.22 vs ~0.001 over one task), and the
  template survival filter excludes m5.xlarge but never changes the pick
  (c5.xlarge leads on capacity per dollar, 130.7 vs 97.1, with or without
  it). See Open items.

## Fix history, and why each one mattered

Backups. Fixes 1–4 each have a pre-change copy in `_fix_scratch/`:
`r_burst_hads.py.pre_migcheck` (1); `metrics.py.pre_billfix` and
`events.py.pre_release` (2); `events.py.pre_resumefix` (3);
`main.py.pre_speedfix` and `r_burst_hads.py.pre_speedfix` (4).
**Fixes 5, 6 and 7 went in as one edit against one backup**,
`r_burst_hads.py.pre_tiebreak`, which still holds the pre-6/pre-7
Theorem 1 code. Their individual effects were never measured and cannot
be separated in the one checkpoint taken after them. From fix 8 on the
pre-change state is the parent git commit, and every fix from 8 on was
measured first as a counterfactual in `experiments/variants.py` and
adopted only when the adopted code reproduced it bit-for-bit.

Checkpoint tags do not follow fix numbers: `fix1_migcheck` = fix 1,
`fix2_billing` = fix 2, `fix2b_resume` = fix 3, `checkpoint_df050` /
`checkpoint_df200` = DF sweep of the post-fix-3 state, `fix3_speed*` =
fix 4, `fix3b*` = fixes 5–7 together, then `fix8_df*` … `fix12_df*`.

1. **Fairness** (`r_burst_hads.py`) — `_select_replacement_vm` (tier 0)
   and `_provision_one_more` (tier 3) tested only `can_fit_task` plus a
   flat deadline check, bypassing `_check_migration` and therefore the
   Section 3.4 spot spare-time rule that Burst-HADS enforces on every
   spot target. Tier 0 now routes through `_check_migration`;
   `_provision_one_more` writes the rule out explicitly because the VM has
   not booted. **Isolated effect**, measured on the post-fix-9 code
   (variant `pre_fix1`, `experiments/fix1_isolation.txt`): −0.4% makespan,
   +0.9% cost for R-BurstHADS on average; under 1%.
2. **Billing** (`metrics.py`, `events.py`) — `total_cost` passed
   `sim_end = makespan()`, which only clamps **open** intervals. One
   number, three rules. On the n=40 trace the post-makespan tail was ~75%
   of every reported cost.
3. **Post-makespan resume** (`events.py`) — hibernated VMs stayed
   resumable after the job ended and were billed another 900s. It
   penalised finishing early: HADS 6.1%, R-BurstHADS 21.4%.
4. **Per-core speed** (`main.py`) — `speed` scaled with instance size
   *and* `vcpu_count` did too, so a c5.xlarge retired 4x a c5.large's work
   for 2x the price. The single largest artefact in the study.
5. **Instance selection tie-break** (`r_burst_hads.py`) — survival is a
   filter, then rank on capacity per dollar, ties to the larger machine.
   (In this catalogue the filter never binds; see Key mechanics.)
6. **Theorem 1 normalisation** — `c_reactive` divided by `speed` not
   `speed*vcpu_count`, plus a hardcoded `/2`; preemptive provisioning
   silently switched off.
7. **Theorem 1 epsilon** — the code substituted the cost of a whole task
   for epsilon, 2.6x the startup term. Restored to the stated form.
8. **Planner checkpoint overhead** (`hads.py`, `burst_hads.py`; `042d1a9`)
   — both static planners left out the overhead execution charges. This
   was **all** of HADS's deadline misses (`diag_hads_misses.*`: 55 of 59
   late tasks never left a never-hibernated VM; 7.5 misses per run with
   no hibernation at all).
9. **Replacement hibernation parity** (`provisioning_event.py`,
   `main.py`; `d9d18c8`) — spot VMs R-BurstHADS provisioned mid-run were
   drawn at the declared c5.xlarge rate, 12× to 750× safer than identical
   instances in the pool. They now join the same Table 9 process. The
   owner's own `SPOT_RISK_MODE="declared"` choice; the most important
   fairness hole found.
10. **R-BurstHADS predictor overhead** (`r_burst_hads.py`; `5a6266f`) —
    fix 8's omission in `_provision_one_more` / `_vms_needed_for_deadline`.
    Negligible (+0.1% cost).
11. **Burst-HADS primary schedule** (`burst_hads.py`; `9292a93`) — every
    residual Burst-HADS / R-BurstHADS deadline miss in the fixes-1–10
    sweep came from two defects (`diag_burst_misses.*`,
    `diag_primary_stages.*`, `diag_ils_feasibility.*`): (a)
    `_compute_vm_load` / `_solution_task_finish_times` list-scheduled in
    task-id order while execution runs memory-descending, so the ILS
    scored, and the proactive burstable step picked "violators" from, a
    schedule that never runs; (b) Eq 9's normaliser covered spot VMs only
    while Phase 3 puts on-demand VMs in the solution, so feasible scores
    exceeded the 1.0 infeasibility sentinel and the ILS chose schedules
    past D. Fixed by sorting to execution order and normalising over every
    usable VM. Screened (`sweep_variant_b_*`): order alone is far worse
    (the broken sentinel then decides everything); either sentinel fix
    alone halves the misses; both together remove all of them. `norm` was
    chosen over the reference code's `+inf` on principle before the
    combined results; `b_order_inf` gives near-identical numbers.
12. **Instance limits** (`models/limits.py` and all three schedulers;
    code `93d3b03`, enabled `024ce5b`) — the reference never
    launches past its per-type limits; an uncapped pool let every
    deadline be bought and flattened deadline satisfaction into a
    non-metric. Both markets limited, decided before the screening:
    on-demand only would have left R-BurstHADS at +4.2% cost vs HADS and
    0.01 misses per feasible run at DF=0.5, instead of +18.7% and 8.00
    (`sweep_variant_cap_*`, seeds 0–9). Much of R-BurstHADS's advantage in
    tight cells came from launching spot capacity past the reference
    limit.
13. **Billing from launch** (`models/limits.py`, `main.py`; Round B part 1,
    `42bff94`) — billing opened at a VM's first task, so a launched VM that
    never ran one was free. TCC23 §3.1 charges from launch, which makes
    Burst-HADS's proactive burstables a sunk cost. DEVIATIONS B1.
14. **Allocation Cycles over uptime** (`models/vm.py`; `42bff94`) — an
    idle VM restarted a full 900 s timer each time it went idle.
    DEVIATIONS E10.
15. **Launched-only migration** (`hads.py`, `burst_hads.py`; `42bff94`) —
    migration took never-launched pool VMs. DEVIATIONS U6 / H2.
    Fixes 13–15 were adopted together after the pre-registered Round A grid
    (`experiments/round_a_grid_plan.md`, `ec52967`), which also kept the U5
    guard. The adopted code reproduces grid cell g1e1 row for row on both
    catalogues (`experiments/rb1_verify.txt`: 1440/1440, 2400/2400).
16. **On-demand catalogue** (`models/catalogue.py`, all three schedulers,
    both catalogue builders; Round B part 2, `685d80d`) — one on-demand
    type made the per-type limit a total of 5, and launch templates were
    read from live pool lists that could empty, falling back to a
    hardcoded c5.large. Three types per catalogue now, walked by price.
    Alone on the main sweep (seeds 0–9) it removes every baseline miss
    (HADS 2,533 → 0, Burst-HADS 1,981 → 0 missed tasks) and nearly all
    infeasibility (250 runs each → 5 HADS runs); R-BurstHADS 1,090 → 43.
    DEVIATIONS E1 / E3.

17a. **Saturation re-placement deadline test** (`r_burst_hads.py`;
    `34558bc`) — `_respond_to_saturation` re-placed every queued task on the
    earliest-finishing target without testing D. It caused 108 of
    R-BurstHADS's 109 misses at `freeze-round-b`; the launch limit was only
    the trigger. DEVIATIONS R1.
18. **Boot delay of R-BurstHADS's provisioned spot VMs** (`34558bc`) — a
    task placed on a still-booting VM started at once: 6,661 early starts
    in 1,276 of 2,400 runs. DEVIATIONS R4.
19. **Checkpoint credits executed progress** (`34558bc`) — `save_checkpoint`
    credited elapsed × speed, ignoring the overhead execution charges.
    DEVIATIONS E11.
20. **Overhead in the fallback deadline test** (`34558bc`) — adopted because
    the test should charge what execution charges; it changes no run.
    DEVIATIONS U10 (inert).
21. **Deploy time for every VM a scheduler launches** (`467b438`) — 21a
    mid-run launches, 21b R-BurstHADS's mid-run burstables, 21c the t = 0
    launches of a primary schedule. Before it, 36,574 of 42,249 launches
    that should pay ω started a task early; after it, 0 of 42,623.
    DEVIATIONS E12, R5.

**FROZEN at tag `freeze-fix21` (code fingerprint `2439a00d7f74`).** The
freeze of `freeze-round-b` (`4f08f48ac35c`) was lifted twice by the owner,
for fixes 17a–20 (`freeze-fix20`, `d40a1c917c63`) and for fix 21, each
pre-registered (`experiments/fix17_plan.md`, `fix18_20_plan.md`,
`fix21_plan.md`) and adopted only when the adopted code reproduced its
variant row for row. From here a newly found defect goes into DEVIATIONS.md
as a limitation, with its measured effect where one exists.

Documentation-only corrections (`042bef7`): main.py's claim that
R-BurstHADS "detects risk via risk-adjusted WRR weights" (no such
mechanism), the matching lines in `build_vms_burst` and `vm.py`, and
Theorem 1's docstring horizon (now states what the code computes).

## Where the result stands

**Freeze sweep** (tag `freeze-fix21`, fingerprint `2439a00d7f74`): Table 9
sc1–sc5 × n 50/100/200/300 × DF 0.25/0.5/1.0/2.0 × 30 seeds, 7,200 runs,
0 errors, instance limits on (`sweep_raw_2439a00d7f74.jsonl`,
`sweep_summary_2439a00d7f74.*`, `sweep_analysis_2439a00d7f74.txt`); the
same 7,200 units with limits off (`sweep_variant_nocap_2439a00d7f74.*`).
The checkpoint harness check: 450 runs compared, 0 differ, 0 not in the
sweep (`checkpoint_fix21_df*`). No launch was forced past a limit.

**Feasibility.** 110 runs are infeasible, all HADS (22 of 30 seeds in each
sc1–sc5 n = 100, DF = 0.25 cell, the deadline floor). The tables are over
the 75 cells where every scheduler is feasible in every seed (ratios of
cell means, averaged over cells); over all 80 cells with their feasible
seeds: Burst −18.4% / +18.2%, R −26.0% / +11.5%, R vs Burst −11.3% /
−4.3%, dominance 49/80 [T1 last row].

Relative to HADS, **limits on** (the reference's account):

| cells | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ | R dominates Burst |
|---|---|---|---|---|---|---|---|
| all 75 | −19.6% | +19.0% | −27.7% | +11.8% | −12.0% | −4.6% | 49/75 |
| DF=0.25 (15) | −7.4% | +8.3% | −8.4% | +7.4% | −1.2% | −0.8% | 9/15 |
| DF=0.5 (20) | −6.1% | +17.4% | −7.0% | +18.1% | −1.0% | +0.7% | 9/20 |
| DF=1.0 (20) | −14.8% | +19.6% | −26.8% | +14.7% | −14.7% | −3.1% | 12/20 |
| DF=2.0 (20) | −47.0% | +27.9% | −63.7% | +6.1% | −28.5% | −14.3% | 19/20 |

**Limits off** (all 80 cells feasible):

| cells | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ | R dominates Burst |
|---|---|---|---|---|---|---|---|
| all 80 | −18.4% | +19.5% | −30.1% | +2.4% | −16.5% | −13.2% | 67/80 |
| DF=0.25 (20) | −5.6% | +10.5% | −7.1% | +7.5% | −1.6% | −2.6% | 11/20 |
| DF=0.5 (20) | −6.1% | +18.8% | −12.0% | −1.7% | −6.2% | −16.6% | 18/20 |
| DF=1.0 (20) | −14.8% | +20.8% | −33.3% | +2.1% | −22.2% | −14.9% | 19/20 |
| DF=2.0 (20) | −47.0% | +27.9% | −67.9% | +1.5% | −35.9% | −18.6% | 19/20 |

By scenario, limits on, R-BurstHADS vs HADS (makespan / cost, 80 cells with
their feasible seeds; `sweep_analysis_2439a00d7f74.txt`): sc1 −36.5% /
+18.1%, sc2 −16.3% / +17.6%, sc3 −34.5% / +10.3%, sc4 −18.4% / +7.5%,
sc5 −24.4% / +4.0%.

- The instance limit binds on R-BurstHADS's own launches (spot c5.xlarge
  reaches the limit of 5; the baselines cannot exceed the pool's 3).
  Lifting it changes mainly R-BurstHADS. Over the same 75 cells [T2b], its
  cost change vs Burst-HADS goes from −4.6% to −14.1% and its makespan
  change from −12.0% to −17.6%; Burst-HADS vs HADS moves from +19.0% to
  +20.3% cost. With limits off Burst-HADS and R-BurstHADS still miss 5
  tasks between them, in the same floor cells [T5]. **Report both; lead
  with limits on.**
- Burst-HADS is cheaper than HADS in 16 of 80 cells. R-BurstHADS ranges
  from −23.5% (sc4 n=300 DF=2.0) to +41.6% (sc4 n=50 DF=1.0) and is no
  more expensive than HADS in 18 of 75 cells [T3].
- HADS's makespan is 63–100% of D (cell means; 47–100% per run); it never
  exceeds D.

**Deadline misses** (feasible runs, limits on): HADS 0; Burst-HADS 6 tasks
in 6 runs; R-BurstHADS 5 tasks in 5 runs [T5]. With limits off, Burst-HADS
2 and R-BurstHADS 3. Every one is in the n = 100, DF = 0.25 floor cells: a
hibernation rescue that no on-demand VM the fallback was allowed to launch
could finish by D after its 45 s deploy time. With limits on the faster
types were at their launch limits; with limits off every type failed the
fallback's own deadline test (`diag_f21_misses.txt`,
`diag_f21_misses_nocap.txt`). At `freeze-round-b`, R-BurstHADS's 109 misses
came from its own saturation response re-placing tasks without a deadline
test, with the launch limit only as the trigger (DEVIATIONS R1; fix 17a
removed 108 of them).

**The contribution statement this supports** (limits on): Burst-HADS buys
−19.6% makespan for +19.0% cost over HADS. R-BurstHADS delivers −27.7% for
+11.8%. It is 12.0% faster and 4.6% cheaper than Burst-HADS on average and
dominates it on both axes in 49 of 75 cells [T1 all]. The advantage lives
at DF ≥ 1.0 (−14.7% / −3.1% and −28.5% / −14.3%). At DF 0.25 and 0.5 the
two are within about a point (−1.2% / −0.8% and −1.0% / +0.7%); at DF 0.5
R-BurstHADS is significantly slower than Burst-HADS in 7 cells and dearer
in 6 [T1 DF rows].

**Makespan is the unconditional claim; cost is scale-dependent** (owner,
2026-09-24). Makespan holds in every configuration and regime measured:
limits on and off, the burstable branch disabled, no hibernation, the cell
set a reference-faithful Burst-HADS could solve, and against that faithful
baseline itself. One qualification travels with it: at DF 0.5 the advantage
over Burst-HADS is roughly a wash.

**The anchor for cost is the faithful DF 2.0 comparison, not the full
sweep.** At DF ≥ 1.0 neither U3 nor U12 applies, and at DF 2.0 the guard-free
baseline also misses nothing, so that regime needs no repair from us. There
the cost result turns on bag size [T12c]:

| DF 2.0, faithful | n=50 | n=100 | n=200 | n=300 |
|---|---|---|---|---|
| R vs B cost | +12.7% | +9.6% | −8.8% | −2.0% |
| R vs B makespan | +0.6% | −7.2% | −19.3% | −18.2% |
| dominance | 0/5 | 1/5 | 5/5 | 4/5 |

**There is no n ≥ 200 operating point and it must not be written as one**
(owner, 2026-09-24): two replications of a threshold with no mechanism for why
200 and not 300 is an artefact. What replicates is the **small-bag penalty**:
R-BurstHADS is dearer at n = 50 and n = 100 against a faithful baseline in
every configuration measured — +12.7 / +9.6% at DF 2.0, +9.3 / +13.4% at
DF 1.0, +13.6 / +12.6% at DF 2.0 with limits off. State it as our own negative
finding. The n = 300 narrowing is **partly** a launch-limit effect (post-hoc
check, labelled because it helps us: limits off moves n = 300 to −7.1% and
n = 200 to −11.5%, closing 2.4 of the 6.8-point discrepancy).

**Never cite the sweep-wide faithful comparison** (+2.45% over 75 cells): it
averages over DF 0.25 and 0.5, where that baseline misses 91% and 48% of its
runs, and it is milder than DF 2.0's +2.9%, so it flatters us. DF 2.0, 20
cells, is the only legitimate faithful comparison in the study.

**Mechanism: measured, and NOT established** [T30, `diag_provisioned.txt`,
`experiments/util_plan.md` and its amendment]. What is measured: provisioned
capacity is 33.6% utilised at n = 50 faithful, 77.8% at n = 200, and 62.7% at
n = 50 guard-kept, at a flat 13–15% share of cost with the same fleet size, so
the penalty is idle capacity rather than a bigger fleet, and the idleness
belongs to the faithful configuration (R-BurstHADS inherits the guard through
the shared primary schedule). What failed: the pre-registered **substitution**
reading predicted (1) a larger burstable work share — holds, 24.1% against
2.8% at n = 50 — and (2) provisioned capacity idle in the same runs where
burstables are busy — **fails**, r = +0.17 and 37 of 150 runs in the quadrant,
no more than chance. By the rule fixed in advance the mechanism is open, and
the paper says so. Do not fit a third story to these numbers without measuring
it; a hypothesis of this shape was already refuted for sc1 (replacements
68–86% busy).

**The cost claim is conditional, and the conditions travel with it:**
- It depends on the U5 guard, an addition of ours to the baselines. Following TCC23 §3.2 in
  full (the guard removed and the leftover violators sent to on-demand, the
  step we never implemented) R-BurstHADS is +2.45% cost and −4.50% makespan
  against Burst-HADS with limits on, dominating 35 of 75 cells, against
  −4.62% / −12.00% and 49 of 75 as frozen [T12]. That configuration is not a
  usable baseline (981 of 2,400 runs miss a deadline; 980 with the guard removed alone), so it bounds what the
  cost claim owes to the departure rather than replacing the comparison. The
  guard is almost all of the swing: +2.57% with the guard removed alone.
- It depends on launch headroom: −4.6% with limits, −14.1% without, over
  the same cells [T2b].
- **Against a faithful baseline it is dearer overall and cheaper only at
  n ≥ 200** (see the anchor above): −11.0% makespan but +2.9% cost over the
  20 DF 2.0 cells, dominating 10 of 20, significantly dearer in 9 and cheaper
  in 3 [T12c]. At DF 1.0 the same comparison is −6.4% / +5.0%, but there the
  guard-free baseline misses in 145 of 600 runs and is not a functioning
  scheduler.
- It reverses without hibernation: R-BurstHADS is 3.4% dearer than
  Burst-HADS and 8.9% faster over the 15 cells of the no-hibernation runs
  (`u5_nohib_compare.txt`). That is the expected behaviour of a scheduler
  that provisions in anticipation of interruptions, and it is reported as
  a sanity check on the method, not as a weakness.
- Our Burst-HADS still does not reproduce TCC23's hibernation costs (Open
  items), and departs from its published Algorithm 1 and Algorithm 2 in
  three measured, disclosed ways (U5, U12, U3).

Claims that are **dead** and must not reappear: the pre-freeze sweep
headline (`519c868a99f9`: −34.0% / +15.4% vs HADS, −20.3% / −17.5% vs
Burst-HADS, dominance 48/55) and everything built on it ("about 1.9× the
makespan benefit at about 37% of the premium"; "misses the fewest deadline
tasks" — at the freeze it is the only scheduler that misses); the 25-cell
infeasible region and the DF=0.5 baseline misses (fix 16 artefact);
"cheaper and faster than everything"; any average cost advantage over HADS,
or "roughly HADS's cost"; the uncapped pre-fix-11 headline (−26.3% / +5.9%,
dominance 78/80, sweep `fb931f79c624`) and "2.2× the makespan benefit at
about a sixth of the premium"; every checkpoint headline (−41.5% / −5.1%,
−34.7% / +2.5%, 15/15); "no scheduler misses a deadline"; "HADS misses
deadlines and the others do not" (fix 8 artefact); Burst-HADS's residual
misses as a property (fix 11 artefact); risk-aware WRR weighting;
risk-awareness as a source of benefit; the ILS explanation for HADS's
misses (HADS has no ILS); sc1's premium being unpriced idle time; and the
old −52% / −74% figures (the speed artefact). Dead since fix 21: the
`freeze-round-b` headline (−27.9% / +12.9% vs HADS, −12.7% / −5.4% vs
Burst-HADS, 44/75) and the `freeze-fix20` one (−27.6% / +13.7%, −12.4% /
−4.7%, 42/75); "109 missed tasks in 4.3% of runs"; "the misses are caused
by the launch cap"; "R-BurstHADS is the only scheduler that misses";
"−5.4% → −14.6% when limits are lifted" (mixed cell sets — use T2b);
"about 1.5× the makespan benefit at about 60% of the premium" (a ratio of
two averaged percentages); and "R-BurstHADS's advantage reverses at
n = 300" (it no longer does: −0.2% at n = 300 [T1 n rows]).

## Open items

- **THE BASELINES ARE NOT A VALIDATED REPRODUCTION OF TEYLO ET AL. (IEEE
  TCC 2023). Everything in "Where the result stands" is a comparison against
  our variant of Burst-HADS until this is resolved.** Measured with
  `experiments/baseline_validation.py` (30 seeds, 95% CIs, paired per seed),
  at fixes 1–7, fix 8, fixes 1–11 and fixes 1–12
  (`baseline_validation_compare.txt`, commit `a0b3dfc`):
  - **What the old validation got wrong.** The per-job makespan reductions
    44.37/42.09/28.82/11.82% are the paper's **Table 7, without
    hibernation** (paired cost increases +66/+45/+58/+34%), not a
    hibernation average. +1.92% is the hibernation-run average (Table 9).
    The paper's Table 10 is a 20% runtime-fluctuation experiment on J60.
    `paper_reproduction.py`'s table numbers are wrong (catalogue = Table 3,
    jobs = Table 6, scenarios = Table 8), and its job generator draws
    runtimes uniformly, so mean runtimes exceed Table 6's stated averages
    by 6/6/14/22% (J60/J80/J100/ED200). The earlier "matched" result also
    never covered Burst-HADS: `paper.tex` already showed its makespan
    reduction short of published.
  - **HADS reproduces**, without hibernation, after fix 8: makespan within
    1–2% of Table 7 for J60/J80/J100 (2330/2350/2356 s vs 2290/2295/2332),
    −8% for ED200; cost 10–18% below published.
  - **Burst-HADS does not.** Without hibernation (Table 6 generator,
    3 copies): makespan change vs HADS −71/−60/−51/−0% against published
    −44/−42/−29/−12%; cost change +29/+47/+79/+66% against +66/+45/+58/+34%.
    Highly sensitive to the unstated spot pool size (5–6 copies: J60 −78%)
    and to the job generator (uniform draw: J80/J100 makespans within 1–7%
    of published, J60 still −44%, ED200 +14%).
  - **Under hibernation (sc1–sc5) neither matches the paper's aggregates.**
    Average Burst-HADS makespan reduction vs HADS 10–16% against 25.87%
    (J60 21–27% vs 40.10%, ED200 1–3% vs 10.24%); average cost increase
    +38–44% against +1.92%. Both baselines get 50–190% dearer under
    hibernation than without it; the paper's own J60 Burst-HADS numbers
    (Table 7 vs Table 10) show +6/+82/+13/+27/+34% for sc1–sc5.
  - **Not caused by fixes 8–12.** The hibernation aggregates move by under
    two points across all four code states for a given workload; the gap
    is present at fixes 1–7.
  - **Cost decomposition** (`diag_validation_costs_*`, paper catalogue,
    Table 6 workload, 10 seeds, fixes 1–11 uncapped and fixes 1–12):
    - *Measured — fix 12 is stricter than the reference.* Both our
      catalogues hold one on-demand type (paper: c4.large; sweep: c5.large),
      so the per-type limit of 5 is a total of 5, while the paper's Table 3
      prices three on-demand types and CCScheduler's fallback walks every
      one. ED200 sc2 with limits on launches exactly 5 on-demand VMs and
      reaches makespan ~5,900 s with ~40 misses per run; uncapped it uses
      8.1–8.5 and finishes near D. The capped sweep's DF=0.5 misses and
      DF=0.25 infeasibility are therefore at least partly this artefact.
    - *Measured — a hardcoded on-demand fallback.* `_launch_new_ondemand_vm`
      (HADS and Burst-HADS) falls back to c5.large, speed 2, $0.085 when
      `ondemand_vms` has emptied (every on-demand VM terminated): the wrong
      catalogue in the paper setting, and a type the per-type limit does not
      count. Seen at 0.1 launches per run (HADS J60 sc1).
    - *Measured - migration onto never-launched pool VMs* (variant
      `nocap+mig_launched` restricts HADS stages 1-2 and Burst-HADS Attempts
      1-2 to VMs the run has launched, per Algorithm 4's inputs "idle, busy,
      and non-launched regular on-demand VMs (IR, BR and Mo)"). No effect
      without hibernation. Under hibernation it moves every aggregate toward
      the paper: average makespan reduction 14.7% -> 21.5% (published
      25.87%), J60 25.8% -> 35.0% (40.10%), ED200 1.2% -> 5.1% (10.24%),
      average cost increase +38.7% -> +16.0% (+1.92%); J60 Burst-HADS sc1
      cost $0.183 -> $0.150 (published $0.119).
    - *Measured - the improvement guard in `_allocate_burstable_vms`*
      (variant `nocap+burst_fill` removes it, following the paper's text).
      Without hibernation Burst-HADS's makespan then matches Table 7 almost
      exactly for J60 and J80 (1,305 s vs 1,274; 1,332 s vs 1,329; change vs
      HADS -43.9% vs -44.37%, -43.3% vs -42.09%) and moves toward it for J100
      (1,381 s vs 1,660); ED200 unchanged. Its cost overshoots badly:
      +254/+124/+115% against +66/+45/+58% -- consistent with the spot fleet
      staying billed while baseline-mode tasks finish, not yet measured. So
      the guard is not the published algorithm, and our cost for
      deployed-but-idle capacity is not the reference's.
    - Both together (`nocap+mig_launched+burst_fill`): hibernation aggregates
      22.4% / 35.3% / 5.1% / +18.2% against 25.87% / 40.10% / 10.24% / +1.92%.
      Neither closes the cost gap. Faithful copies of both reproduce the
      current code on 1440/1440 runs. Not adopted: both restore the
      baselines' stated algorithm and both change the baselines -- owner's
      decision. `baseline_validation_variants_compare.txt`.
  - Table 9 has no text layer (the PDF draws it as glyph outlines). It is
    now transcribed in `experiments/tcc23_tables.py` from a raster of the
    page's vector paths, with a check: the 20 cells reproduce all four
    section 4 aggregates to two decimals (25.87 / 40.10 / 10.24 / 1.92), and
    every printed Diff matches its recomputation within 0.6 points of cost
    rounding. The five `paper_reproduction.PAPER` cells agree with it.
    Definitions, now verified: Diff HADS = (HADS − Burst-HADS)/HADS per
    cell; the published aggregates are plain means over the 20 cells —
    the same definition our harnesses use.
  - **Round A outcome (2026-09-14): the hibernation cost gap is not
    aggregation, not the billing rule and not EBS.**
    `experiments/diag_cost_gap.py` (paper catalogue, Table 6 workload,
    uncapped, 30 seeds; costs recomputed post hoc per VM under several
    rules), summary in `diag_cost_gap_compare.txt`.
    - *(a) Aggregation* — ruled out by Table 9 itself (above). Other
      weightings of our runs: pooled totals +36.6%, per-run +41.8%, median
      +42.4%, against mean-of-cells +38.7% (TCC23 +1.92%).
    - *(b) Billing* — no rule closes it. 900 s quantised +30.1%; billed
      from launch (TCC23 §3.1) +40.5%; the pre-fix-2/3 billing (variant
      `nocap+no_release`, open intervals clamped at makespan) +22.9%, but it
      wrecks Table 7 (J60 Burst-HADS $0.165 vs $0.112). Never-launched VMs
      billed on resume are ≤ 2.9% of cost; removing them widens the gap.
    - *(c) EBS while hibernated* — +38.7 → +37.5%.
    - *What it is.* The gap is not shared. Hibernation cost premium vs the
      same scheduler without hibernation, mean of 20 cells: HADS +111%
      (TCC23 +95%), Burst-HADS +94% (TCC23 +25%). The no-hibernation cost
      ratio is also near published on average (+55 vs +51%). Burst-HADS's
      premium is the gap. Two measured contributors: migration onto
      never-launched pool VMs (U6; fixed, +94 → +60%) and hibernation
      exposure, which tracks the deployed spot pool (E8: our runs suffer
      1.3–3.6× Table 9's hibernations per run, flat across jobs; at 2
      copies with the migration fix Burst-HADS's premium is +24%). Pool size
      is unstated in TCC23 and no value reproduces Tables 7 and 9 together
      (E4) — owner's decision, not a fix.
    - *Consequence for the paper.* At 3 copies, even with the migration fix,
      Burst-HADS pays about 2.4× its published hibernation premium, so
      R-BurstHADS's cost lead over Burst-HADS under hibernation is
      flattered by an amount this study has not bounded. Pool size: 3 kept
      (owner; chosen before these results), 1 / 2 / 3 reported as a
      sensitivity, and "TCC23 underspecifies the pool" is a finding.
  - **Round A closing checks (2026-09-14; Round A is now CLOSED).**
    `catalogue_economics.txt`, `diag_cost_gap_compare.txt` (our billing),
    `diag_cost_gap_compare_PAPER.txt` (TCC23 §3.1 billing).
    1. *Catalogue.* The validation catalogue is TCC23's Table 3 exactly, so
       it is not the Round A defect: a burst-mode task on t3.large costs
       0.83× the same task alone on a fresh c4.large on-demand, 1.66× a
       core of one. In the SWEEP catalogue it costs 1.15× a lone task on a
       fresh c5.large (0.98× at the pre-fix-4 speed 2.0) and 2.30× a core.
       Note `VM` gives every burstable ONE slot (TCC23's one-task rule), so
       t3.large delivers 1.7 units, not 3.4.
    2. *t3.large speed.* TCC23 publishes none (Gflops, unpublished). AWS:
       T3 and M5 share the Xeon Platinum 8000 at up to 3.1 GHz; C5 3.4 /
       3.6 GHz. t3 = m5 = 1.7 is supported; the old 2.0 was c5's clock.
       Kept (DEVIATIONS E7; baseline 20% vs AWS's current 30%, E9).
    3. *Sunk-cost burstables — confirmed.* TCC23 bills burstables from
       launch and never AC-terminates them; ours bill from first task and
       the guard leaves some idle. §3.1 billing: Burst-HADS premium +60 →
       +42% (TCC23 +25%). Guard removed as well: +8%, but its
       no-hibernation cost then overshoots (J60 $0.210 vs $0.112) through
       idle-billed spot VMs, which points at a new, unmeasured deviation
       in Allocation Cycle boundaries (DEVIATIONS E10). Closed by the
       pre-registered grid and Round B: E10 adopted (fix 14), guard kept (U5).
  - **At freeze-fix21** (`diag_cost_gap_fix21_nocap_c3`, `_capped_c3`,
    validation catalogue, 3 copies, 30 seeds) [T9]: Table 9 cost change vs
    HADS +17.9% limits off and +17.7% on (TCC23 +1.92%); makespan reduction
    21.8% (25.87%), J60 34.5% (40.10%), ED200 4.8% (10.24%); hibernation
    premium HADS +110% (+95%), Burst-HADS +43% (+25%). Without hibernation
    Burst-HADS's makespan change is −70.9% vs HADS (−44.4%) and its J60
    cost change +87% (+67%) [T8]. Limits on and off agree within 0.15
    points. **The baselines still do not reproduce TCC23. That is a
    limitation the paper states, not a code task.**
  - **The U5 guard is what separates our no-hibernation Burst-HADS from
    the published one.** Removing it takes the no-hibernation makespan
    change vs HADS from −70.9% to −42.0% for J60 (published −44.4%) and to
    −42.0% for J80 (−42.1%), while the cost overshoots further (J60 +190%
    against the published +67%). Under hibernation it changes the cost gap
    hardly at all (+17.9% → +18.1%), so the gap is not the guard's doing.
    TCC23 evaluates at D = 2,700 s, far looser than our sweep's deadlines;
    the guard is our adaptation to a harder experiment, not a patch over a
    defect in the rescue path. The unconditional move the paper describes
    costs deadlines here in a way it cannot at D = 2,700 s, and that holds
    with hibernation switched off (`u5_nohib_compare.txt`).
- **Declared per-type risk is untested in every Table 9 cell — a
  limitation to state, not a benefit to claim.** Table 9 hibernates every
  spot VM at kh/D, so the c5 / m5.xlarge risk differential R-BurstHADS
  reasons about is never instantiated. Theorem 1's three replacements
  exist because of m5.xlarge's illustrative declared rate, and the
  template survival filter never changes the choice. Nothing in the
  results may be attributed to risk-awareness.
- **Theorem 1's horizon — resolved in the docs, sensitivity recorded.**
  The code takes P(hibernation) over one average task; the principled
  exposure is v's planned busy period, between one task and D. One task is
  the lower bound and is kept, because any longer horizon only adds
  provisioning, through the illustrative c5 rate. Measured on the
  post-fix-9 code (`thm1_rb_variants.txt`): with horizon D, R-BurstHADS at
  DF=2.0 n=300 becomes 27–51% faster and 2–25% cheaper, once D > 4616 s
  pushes c5's P over the 5% threshold. **Behaviour at DF=2.0, n ≥ 200
  depends on c5's illustrative 0.04/hr rate and on this choice.** Not
  re-measured under fixes 11–12.
- **Pool size against the limit.** The baselines' pool holds 3 spot VMs
  per type; the limit allows 5, and R-BurstHADS can launch up to it, so it
  can still use 2 c5.xlarge per type the baselines' planners never see.
  `SPOT_COPIES = 3` was chosen to reproduce the paper's reported gap and is
  kept (owner, 2026-09-14). At freeze-fix21 R-BurstHADS misses 5 tasks with
  limits on and 3 with limits off, and Burst-HADS 6 and 2; all are
  floor-cell rescues that no on-demand VM the fallback could launch would
  finish by D after its deploy time [T5, `diag_f21_misses.txt`,
  `diag_f21_misses_nocap.txt`]. Pool-size sensitivity was cut from Round C
  and is future work.
- **Migration at a spent limit deviates from the reference** (task placed
  on the soonest-finishing active VM instead of left unallocated).
  `limit_overrides` is 0 in all 7,200 freeze-fix21 runs, and the fallback
  placed a task at all in only 12 Burst-HADS and 11 R-BurstHADS runs, all
  at DF 0.25, one of them in a headline cell (`diag_capped.txt`).
- **sc1 and replacement-use diagnostics predate the freeze**
  (`diag_rb_provisioning.*`, `diag_rb_replacement_use.*`, run on the
  post-fix-9 uncapped code). Their conclusions — replacements 68–86%
  utilised in sc1, switching Theorem 1 off costs more, rescue vs work
  stealing split — are not cited in the paper; re-running them is future
  work.
- **Round C began as analysis only; the owner then reopened the simulator
  twice** (fixes 17a–20 and fix 21), under pre-registration, and re-froze it
  at `freeze-fix21`. Measurement runs continue (counterfactuals and
  diagnostics, each pre-registered); the code does not change. Done: `RESULTS_PACK.md` (every table and number the paper
  needs, generated by `experiments/results_pack.py` from committed result
  files, with file hashes) and `PAPER_SKELETON.md` (sections, claims, and
  the pack cell behind each). Cut to one future-work sentence each:
  pool-size sensitivity; re-running the sc1 and replacement-use
  diagnostics. Framing: a controlled comparison of re-implementations with
  a documented fidelity audit, not a reproduction; DEVIATIONS.md is an
  appendix. Anything found from now on is a DEVIATIONS entry.
- **The baselines satisfice.** HADS lands close to D wherever it can buy
  its way there. Report across DF and keep the `mk/D` column.
- **Work stealing onto a baseline-mode burstable is not slack-checked**
  the way a burst-mode rescue is.
- **`paper/` is entirely pre-fix.** Rebuild from the freeze-fix21 sweep,
  leading with it, with DEVIATIONS.md as its deviations section.
- Figures: six single-column figures, built from RESULTS_PACK.md by
  `experiments/make_figures.py` per `experiments/FIGURE_SPEC.md`. Since
  2026-09-23 they are the orthogonal set — cost and makespan against
  deadline factor, scenario and bag size — plotting **absolute** values,
  three series, y axis from zero, with every percentage in the tables. The
  displaced headline trade-off is T27 and the limits-on-against-off figure
  is T2b. The paper's set lives in `paper/fig/` (regenerate with
  `python experiments\make_figures.py`); `experiments/fig_fix20/` and
  `fig_fix21/` are records of earlier states.

## Commands

```powershell
# 5-cell sweep, 150 runs, ~13 s on 20 workers
python experiments\checkpoint.py --tag NAME_df0.5 --df 0.5
python experiments\checkpoint.py --tag NAME_df1.0 --df 1.0
python experiments\checkpoint.py --tag NAME_df2.0 --df 2.0

# measure a candidate fix BEFORE editing the simulator:
python experiments\checkpoint.py --tag NAME_df1.0 --df 1.0 --variant thm1_D
python experiments\variant_sweep.py --variant cap_od --seeds 0-9 --base-fp <fp>
# then check the adopted code reproduces the variant bit-for-bit

# the full sweep, 7200 runs. Bare command = plan (runs nothing). Results go
# to sweep_raw_<code fingerprint>.jsonl, so a code change can never resume
# into rows from older code.
python experiments\dynamic_comparison.py
python experiments\dynamic_comparison.py run
python experiments\dynamic_comparison.py summarize
python experiments\sweep_analysis.py --checkpoint-tag fix21   # verifies first
# the same units with instance limits off
python experiments\variant_sweep.py --variant nocap --seeds 0-29 --base-fp 2439a00d7f74
# validation against TCC23 (paper catalogue); compare several tags
python experiments\diag_cost_gap.py --tag NAME --variant nocap --copies 3
python experiments\diag_cost_gap_compare.py --rule=R0 TAG [TAG ...]
```

Always run all DF points together. A single DF point is not trustworthy on
its own — that is the lesson of the deadline sweep.
