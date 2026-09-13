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
  tests still omit the overhead, harmlessly: both branches return the same
  VM. The Section 3.4 spare-time margin deliberately uses
  `exec_time / speed`, as the paper states it.
- Eq 9: an infeasible candidate scores 1.0, which is only an upper bound
  on feasible scores if normalised cost is <= 1, so the normaliser covers
  every VM the search can use — the spot pool plus the initial solution's
  on-demand VMs (fix 11).
- **Instance limits** (fix 12, `models/limits.py`), from the reference:
  5 on-demand and 5 preemptible instances per type, global 20 / 20;
  burstable instances count as on-demand; counts are of launches and
  never decrease. At a limit the primary schedule skips the type and, if
  no type can take a task, raises `NoFeasibleSchedule` — recorded by the
  sweep as an **infeasible run**, not an error. Migration at a spent limit
  places the task on the active VM that would finish it soonest (the
  reference leaves it unallocated, which would drop it from every metric;
  launches forced past a limit are counted in `limit_overrides`).
  R-BurstHADS's own provisioning is limited too. The pool holds
  `SPOT_COPIES = 3` spot VMs per type, under the limit of 5, so the spot
  limit binds only on R-BurstHADS's launches.
- Feasibility is decided by the primary schedule, and the three
  schedulers' primary schedules hit the limits in exactly the same runs:
  infeasibility does not separate them. Deadline misses in feasible runs
  do.
- `PER_CORE_SPEED` in `main.py` is the single source for speeds. Do not
  hardcode a speed anywhere.
- Deadline: `D = DF * DEADLINE_SLACK * ideal_makespan(n)`, floored at
  `min_feasible_deadline()` (339.7 s). `DEADLINE_SLACK = 3.0`. Since DF
  and DEADLINE_SLACK only ever appear as a product, sweeping DF makes the
  constant non-load-bearing — **report across DF, do not recalibrate.**
  In the sweep grid the floor binds at n=50 for DF ≤ 0.5 (so those two
  DF points are the same cell) and at n=100 for DF = 0.25.
- Billing is one rule: launch to genuine shutdown. `total_cost()`
  measures the true simulation end;
  `TaskCompleteEvent._release_fleet_if_done()` terminates every surviving
  VM (hibernated ones included) when the last task completes.
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

Documentation-only corrections (`042bef7`): main.py's claim that
R-BurstHADS "detects risk via risk-adjusted WRR weights" (no such
mechanism), the matching lines in `build_vms_burst` and `vm.py`, and
Theorem 1's docstring horizon (now states what the code computes).

## Where the result stands

**Full sweep on fixes 1–12** (code `024ce5b`, fingerprint `519c868a99f9`,
results `58a5a9d`): Table 9 sc1–sc5 × n 50/100/200/300 × DF
0.25/0.5/1.0/2.0 × 30 seeds, 7200 runs, 0 errors
(`experiments/sweep_raw_519c868a99f9.jsonl`, `sweep_summary_519c868a99f9.*`,
`sweep_analysis_519c868a99f9.txt`). Seeds 0–9 reproduce the `cap_all`
screening rows and the checkpoint cells reproduce `checkpoint_fix12_df*`,
both bit-for-bit. No launch was forced past a limit (`limit_overrides` 0
in every run).

**Feasibility.** 25 of 80 cells — all of DF=0.25, and n=50 at DF=0.5 —
have no primary schedule within D and the instance limits, for all three
schedulers in exactly the same runs (750 infeasible runs each). Every
figure below is over the **55 feasible cells**: ratios of cell means,
averaged over cells.

Relative to HADS:

| cells | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ | R dominates Burst |
|---|---|---|---|---|---|---|---|
| all 55 | −18.2% | +42.1% | −34.0% | +15.4% | −20.3% | −17.5% | 48/55 |
| DF=0.5 (15) | −3.8% | +38.3% | −10.5% | +33.8% | −6.9% | −3.0% | 9/15 |
| DF=1.0 (20) | −6.8% | +44.0% | −23.5% | +20.9% | −17.7% | −15.4% | 19/20 |
| DF=2.0 (20) | −40.5% | +43.0% | −62.2% | −3.8% | −32.9% | −30.6% | 20/20 |

By scenario, R-BurstHADS vs HADS (makespan / cost): sc1 −45.3% / +9.6%,
sc2 −28.0% / +29.1%, sc3 −43.7% / −1.3%, sc4 −23.6% / +22.7%,
sc5 −29.5% / +17.1%.

- R-BurstHADS dominates Burst-HADS on both axes in 48 of 55 cells and in
  66% of seeded runs. The 7 exceptions are six DF=0.5 cells and one DF=1.0
  cell, all at n ≥ 200 in sc2, sc4 and sc5; in the two sc2 cells it is 14%
  faster but 2% dearer.
- Burst-HADS costs more than HADS in every cell (+2.9% to +113.5%).
  R-BurstHADS ranges from −41.8% (sc3 n=50 DF=2.0) to +60.4% (sc4 n=50
  DF=1.0), and is no more expensive than HADS in 34% of runs.
- HADS's makespan is 56–164% of D; it exceeds D in 11 cells, all at
  DF ≤ 1.0.

**Deadline misses** (feasible runs):

| | runs with a miss | missed tasks (share of all tasks) | misses per run at DF=0.5 |
|---|---|---|---|
| HADS | 11.0% | 7629 (2.68%) | 16.91 |
| Burst-HADS | 7.8% | 5545 (1.95%) | 12.32 |
| R-BurstHADS | 8.3% | 3425 (1.20%) | 7.58 |

Misses are concentrated at DF=0.5 and worst in sc2 (kh=5, no resume): at
n=300 HADS misses 98.5 tasks per run (makespan 164% of D), Burst-HADS
88.0, R-BurstHADS 57.1. At DF=1.0 HADS misses in 4 runs, R-BurstHADS in 12
(never more than 0.13 per run in a cell), Burst-HADS in none; nobody
misses at DF=2.0.

**The contribution statement this supports:** Burst-HADS buys −18.2%
makespan for +42.1% cost over HADS. R-BurstHADS delivers −34.0% for
+15.4% — about 1.9× the makespan benefit at about 37% of the premium —
dominates Burst-HADS on both axes in 48 of 55 feasible cells, and misses
the fewest deadline tasks (1.20% against 1.95% and 2.68%), though it
misses in slightly more runs than Burst-HADS. Its cost against HADS
depends on slack: +33.8% at DF=0.5, +20.9% at DF=1.0, −3.8% at DF=2.0. It
does not make any infeasible cell feasible; within the reference's
limits no scheduler can. Lead with the sweep.

**Subset vs full grid — one honest sentence for the methodology.** The
five checkpoint cells have misled in both directions: before fixes 11–12
they gave R-BurstHADS −34.7% / +2.5% against HADS where the full uncapped
grid gave −26.3% / +5.9%, and on the current code they give −32.6% /
+26.9% (dominance 11/15) where the 55 feasible cells give −34.0% / +15.4%
(48/55).

Claims that are **dead** and must not reappear: "cheaper and faster than
everything"; any average cost advantage over HADS, or "roughly HADS's
cost"; the uncapped sweep headline (−26.3% / +5.9%, dominance 78/80, sweep
`fb931f79c624`) and the framing built on it ("2.2× the makespan benefit at
about a sixth of the premium"); every checkpoint headline (−41.5% / −5.1%,
−34.7% / +2.5%, 15/15); "no scheduler misses a deadline"; "HADS misses
deadlines and the others do not" (fix 8 artefact); Burst-HADS's residual
misses as a property (fix 11 artefact); risk-aware WRR weighting;
risk-awareness as a source of benefit; the ILS explanation for HADS's
misses (HADS has no ILS); sc1's premium being unpriced idle time; and the
old −52% / −74% figures (the speed artefact).

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
  - Table 9's body is an image; the HADS values in
    `paper_reproduction.PAPER` cannot be re-verified from the text.
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
  `SPOT_COPIES = 3` was chosen to reproduce the paper's reported gap.
  Setting it to 5 would equalise access; that is a model change and the
  owner's decision.
- **Migration at a spent limit deviates from the reference** (task placed
  on the soonest-finishing active VM instead of left unallocated). Check
  `limit_overrides` stays 0 in the sweep.
- **sc1 and replacement-use diagnostics predate fixes 11–12**
  (`diag_rb_provisioning.*`, `diag_rb_replacement_use.*`, run on the
  post-fix-9 uncapped code). Their conclusions — replacements 68–86%
  utilised in sc1, switching Theorem 1 off costs more, rescue vs work
  stealing split — must be re-run before they are cited.
- **The baselines satisfice.** HADS lands close to D wherever it can buy
  its way there. Report across DF and keep the `mk/D` column.
- **Work stealing onto a baseline-mode burstable is not slack-checked**
  the way a burst-mode rescue is.
- **`paper/` is entirely pre-fix.** Rebuild from the sweep below, leading
  with it, and state in the methodology that the 15-cell checkpoint grid
  and the full grid disagree (see Where the result stands).
- Figures: the owner has a separate unresolved issue with graph
  generation. **Do not generate figures until they raise it.**

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
python experiments\sweep_analysis.py --checkpoint-tag fix12   # verifies first
```

Always run all DF points together. A single DF point is not trustworthy on
its own — that is the lesson of the deadline sweep.
