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
   get tested with a diagnostic, not written up as findings. Two
   confidently stated hypotheses have turned out flatly wrong:
   `MAX_VMS_PER_EVENT` binding (`cap=10` and `cap=40` are identical), and
   sc1's cost premium being Theorem 1 not pricing idle time (Open items).
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
metrics/metrics.py            makespan, deadline_misses, total_cost
simulation/events.py          TaskComplete / Hibernation / Termination
simulation/resume_event.py    hibernated -> idle, restarts billing
simulation/allocation_cycle_event.py   900s idle shutdown
simulation/provisioning_event.py       boot latency + spot risk exposure
policies/work_stealing.py     Algorithm 5
scheduler/hads.py             baseline 1 (greedy, no ILS)
scheduler/burst_hads.py       baseline 2 (ILS, Algorithm 4, Dspot)
scheduler/r_burst_hads.py     ours (Theorem 1/2, select_vm tiers)
experiments/checkpoint.py     small parallel sweep: --df --seeds --tag --variant
experiments/variants.py       counterfactual patches: measure a fix before making it
experiments/dynamic_comparison.py   the full sweep: plan / run / summarize
experiments/diag_*.py         diagnostics behind fixes 8-10 and the sc1 decision
experiments/probe_grid.py     deadline-tightness probe used to choose the sweep grid
experiments/billing_audit.py  3 billing policies on one config
experiments/template_ab.py    forced instance type x VM-count cap A/B
_fix_scratch/                 pre-change backups for fixes 1-7 (git from fix 8)
paper/                        IEEE paper, technical report, trace report -- ALL PRE-FIX
```

**Version control.** This folder is its own git repo (branch `main`,
first commit 2026-09-13), separate from the parent `C:\my folder\projects`
repo, which tracks the old MD_Burst_HADS and pushes to `MD_Burst_Hads`.
There is **no remote**: history protects against overwrites, not against
losing the disk. Every `experiments/checkpoint_*.json` is committed; they
are the evidence trail for every number below.

A Claude Code desktop session started from the parent folder runs in a
worktree of the parent repo, where Write/Edit refuse every file in this
folder. Start sessions in this folder.

## Key mechanics you will need

- `speed` is **per core**. Whole-machine throughput is
  `speed * vcpu_count`. Anything dividing a rate by `speed` alone is a
  bug — that exact error has now been found and fixed in three places
  (Equation 8's WRR weight, `spot_pool_throughput`, Theorem 1's
  `c_reactive`).
- Every finish-time **prediction** must carry `(1 + checkpoint_overhead)`,
  because execution (`VM.start_next_if_free`) always charges it. Planners
  that left it out produced every HADS deadline miss (fix 8); R-BurstHADS's
  own predictors had the same omission (fix 10). The only predictions
  still without it are the HADS and Burst-HADS `_attempt_ondemand_fallback`
  deadline tests, where both branches return the same new VM, so it has no
  effect. The Section 3.4 spare-time margin deliberately uses
  `exec_time / speed`, as the paper states it.
- `PER_CORE_SPEED` in `main.py` is the single source for speeds. Do not
  hardcode a speed anywhere.
- Deadline: `D = DF * DEADLINE_SLACK * ideal_makespan(n)`, floored at
  `min_feasible_deadline()` (339.7 s). `DEADLINE_SLACK = 3.0`. Since DF
  and DEADLINE_SLACK only ever appear as a product, sweeping DF makes the
  constant non-load-bearing — **report across DF, do not recalibrate.**
  In the sweep grid the floor binds at n=50 for DF ≤ 0.5 and at n=100 for
  DF = 0.25.
- Billing is one rule: launch to genuine shutdown. `total_cost()`
  measures the true simulation end;
  `TaskCompleteEvent._release_fleet_if_done()` terminates every surviving
  VM (hibernated ones included, or they resume post-makespan and restart
  the meter) when the last task completes.
- A burstable VM holds **exactly one task at a time**, in both baseline
  and burst mode. Verified against the paper's pseudocode.
- Table 9 scenarios: `lambda_h = kh/D`, `lambda_r = kr/D`, for **every**
  spot VM, including those launched mid-run (fix 9).
  sc1(1,0) sc2(5,0) sc3(1,5) sc4(5,5) sc5(3,2.5).
- Theorem 1 reads each VM's **declared** per-type λ (`main.py`), not the
  scenario's kh/D, so it makes the same decision in every scenario: one
  replacement per m5.xlarge, three in all.
- The on-demand pool is unlimited, so any deadline above the longest task
  can be bought. After fix 8 deadline misses barely occur (Open items).

## Fix history, and why each one mattered

Backups. Fixes 1–4 each have a pre-change copy in `_fix_scratch/`:
`r_burst_hads.py.pre_migcheck` (1); `metrics.py.pre_billfix` and
`events.py.pre_release` (2); `events.py.pre_resumefix` (3);
`main.py.pre_speedfix` and `r_burst_hads.py.pre_speedfix` (4).
**Fixes 5, 6 and 7 went in as one edit against one backup**,
`r_burst_hads.py.pre_tiebreak`, which still holds the pre-6/pre-7
Theorem 1 code. Their individual effects were never measured and cannot
be separated in the one checkpoint taken after them. From fix 8 on the
pre-change state is the parent git commit.

Checkpoint tags do not follow fix numbers: `fix1_migcheck` = fix 1,
`fix2_billing` = fix 2, `fix2b_resume` = fix 3, `checkpoint_df050` /
`checkpoint_df200` = DF sweep of the post-fix-3 state, `fix3_speed*` =
fix 4, `fix3b*` = fixes 5–7 together, then `fix8_df*`, `fix9_df*`,
`fix10_df*` (the current state).

1. **Fairness** (`r_burst_hads.py`) — `_select_replacement_vm` (tier 0)
   and `_provision_one_more` (tier 3) tested only `can_fit_task` plus a
   flat deadline check, bypassing `_check_migration` and therefore the
   Section 3.4 spot spare-time rule that Burst-HADS enforces on every
   spot target. Our own provisioned machines were exempt from a rule the
   baseline obeyed. Tier 0 now routes through `_check_migration`;
   `_provision_one_more` writes the rule out explicitly because the VM has
   not booted and `estimate_finish_time` has no notion of boot delay.
   **Isolated effect**, measured later on the post-fix-9 code by reverting
   only these two tests (variant `pre_fix1`,
   `experiments/fix1_isolation.txt`): R-BurstHADS −0.4% makespan and
   +0.9% cost on average, 0.0% at DF=2.0 (to one decimal), at most +9.8%
   cost in one DF=0.5 cell; dominance over Burst-HADS 15/15 either way.
   The relaxation was worth under 1% on average.
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
8. **Planner checkpoint overhead** (`hads.py`, `burst_hads.py`; commit
   `042d1a9`) — both static planners predicted a task at
   `exec_time / speed`, but execution always charges
   `× (1 + checkpoint_overhead)` and `estimate_finish_time` already
   mirrored that. HADS packs spot queues to `Dspot` and on-demand queues
   to `D`, so each queue ran 10% past its plan, and wherever 10% of the
   planned end exceeds the `D − Dspot` margin (226.5 s) the tail finished
   after D on a VM that was never interrupted. This was **all** of HADS's
   deadline misses (`experiments/diag_hads_misses.*`): at n=300, 55 of 59
   late tasks never left their planned, never-hibernated spot VM, and
   their finish equals the overhead-free plan × 1.1 exactly; with no
   hibernation at all HADS missed 7.5 and 7.2 per run. After the fix no
   scheduler misses a deadline in any of the 15 checkpoint cells. It
   removed the only deadline result the study had.
9. **Replacement hibernation parity** (`provisioning_event.py`,
   `main.py`; commit `d9d18c8`) — Table 9 hibernates every pool spot VM
   at `kh/D` and resumes it at `kr/D`, whatever its type. Spot VMs
   R-BurstHADS provisioned mid-run were drawn once at the declared
   c5.xlarge rate, 0.04/hr, with no resume: 12× to 750× safer than the
   identical c5.xlarge already in the pool. They now join the same
   process from their ready time. It cost R-BurstHADS its whole average
   cost advantage over HADS (−5.4% → +2.4%) and 7 points of makespan.
10. **R-BurstHADS predictor overhead** (`r_burst_hads.py`; commit
    `5a6266f`) — `_provision_one_more` and `_vms_needed_for_deadline`
    predicted without the checkpoint overhead: fix 8's error, in the one
    scheduler fix 8 did not touch. +0.0% makespan, +0.1% cost on average.
    The same commit corrected the Theorem 1 comment that recorded unpriced
    idle time as the cause of the sc1 premium.

Fixes 8, 9 and 10 were each measured first as a counterfactual
(`experiments/variants.py`: `plan_ovh`, `repl_t9`, `rb_ovh`), and the
adopted code reproduces those checkpoints bit-for-bit.

## Where the result stands

Five cells (sc1/sc2/sc4/sc5 at n=300, sc2 at n=100) x three deadline
factors (0.5, 1.0, 2.0) x 10 seeds, after fixes 1–10
(`checkpoint_fix10_df*`). All three billing policies agree exactly, so
cost is unambiguous. **These are checkpoints, not the full sweep.** The
sweep (`dynamic_comparison.py`: 7200 units, adds sc3, n=50/200, DF=0.25)
was started on this code (fingerprint `fb931f79c624`); check
`experiments/sweep_summary_fb931f79c624.json` and update this section
from it.

Relative to HADS, averaged over all 15 cells:

| | makespan | cost |
|---|---|---|
| Burst-HADS | −23.5% | **+33.3%** |
| R-BurstHADS | **−34.7%** | +2.5% |

By deadline factor (mean of the five cells):

| DF | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ |
|---|---|---|---|---|---|---|
| 0.5 | −1.3% | +32.4% | −4.4% | −1.0% | −3.1% | −25.4% |
| 1.0 | −16.5% | +35.7% | −31.9% | +5.9% | −19.4% | −21.6% |
| 2.0 | −52.5% | +31.9% | −67.7% | +2.6% | −30.3% | −22.1% |

R-BurstHADS dominates Burst-HADS on **both** axes in **15 of 15** cells.
Burst-HADS costs more than HADS in every cell (+0.9% to +55.9%).
R-BurstHADS's cost against HADS ranges from −20.1% (sc2 n=300 DF=0.5) to
+38.7% (sc1 n=300 DF=2.0). No scheduler misses a deadline in any cell.

**The contribution statement this supports:** Burst-HADS buys makespan by
paying a cost premium over HADS in every cell, +33% on average, which is
the trade its own paper describes. R-BurstHADS delivers a larger makespan
improvement and hands the premium back, landing at roughly HADS's cost on
average. The makespan gain grows with slack (−4% at DF=0.5, −68% at
DF=2.0); because the baselines satisfice (Open items), part of that is
slack HADS leaves unused rather than work R-BurstHADS does faster.

Claims that are **dead** and must not reappear: "cheaper and faster than
everything"; **any average cost advantage over HADS** (the −5.1% that
stood before fixes 8–10 rested on the replacement-risk asymmetry); the
−41.5% / −5.1% table; "HADS misses deadlines and the others do not"
(fix 8 artefact); HADS degrading with more slack; the ILS explanation for
HADS's misses (HADS has no ILS); sc1's premium being Theorem 1 not
pricing idle time; a ~33% Burst-HADS premium "in every cell" (it is +33%
on average and positive in every cell, but as low as +0.9%); and the old
−52%/−74% figures (the speed artefact).

## Open items

- **Theorem 1's horizon — owner's decision.** The docstring states
  `P(v hibernates) = 1 − exp(−λ_v D)`; the code computes it over one
  average task, `e_avg / speed`. Measured as variant `thm1_D` on the
  post-fix-9 code (`experiments/thm1_rb_variants.txt`): no change at
  DF 0.5 / 1.0 or at n=100; at DF=2.0 n=300 R-BurstHADS becomes 27–51%
  faster and 2–25% cheaper (15-cell average −37.6% makespan, −0.5% cost vs
  HADS). The effect comes from c5's declared 0.04/hr rate — which
  `main.py` calls illustrative — crossing the 5% threshold once
  D > 4616 s (c5.large: 6155 s), after which Theorem 1 can also buy
  replacements for c5 VMs. In the sweep grid D exceeds 4616 s only at
  n=200 and n=300, DF=2.0. The stated formula is
  arguably the consistent one (C_reactive prices all n_v tasks, so P
  should cover the time they are exposed, not one task), but adopting it
  moves the result in our favour on an illustrative constant crossing an
  arbitrary threshold. **Not adopted.** Decide, and if adopted, disclose
  the threshold behaviour in the paper.
- **sc1 is the weak regime, and its recorded cause was wrong.** sc1 n=300:
  R-BurstHADS costs +7.8 / +15.8 / +38.7% against HADS at DF 0.5 / 1.0 /
  2.0, while 21 / 18 / 11% cheaper than Burst-HADS. The claim that
  Theorem 1's failure to price the replacement's expected idle time
  causes this is **refuted** (`diag_rb_provisioning.*`,
  `diag_rb_replacement_use.*`, both run on the post-fix-9 code): the three
  replacements are 68–86% utilised in sc1 (busy / billed core-seconds),
  and switching Theorem 1 off makes R-BurstHADS slower *and* more
  expensive in every sc1 cell (+12% to +78% cost). In sc1 the
  replacements are 12–21% of R-BurstHADS's bill (at n=300, $0.050–0.069
  per run against a premium over HADS of $0.020–0.093); everything else it
  pays for is 29–56% below Burst-HADS's total. An idle-time term would
  provision less, toward the arm that measures worse on both axes, so it
  was **not implemented**. Report sc1 as a limitation: R-BurstHADS keeps
  Burst-HADS's spread-for-makespan cost structure and recovers most, not
  all, of its premium when interruptions are rare. sc3 (kh=1, kr=5)
  behaves similarly in the diagnostics; the sweep is the first grid that
  includes it.
- **What Theorem 1's replacements actually do.** Framed as hibernation
  insurance, they are both insurance and early capacity. Hibernation
  rescue is 15–84% of their busy time and Algorithm 5 work stealing
  16–85%: rescue is the majority at DF=0.5 in every scenario except sc3,
  stealing the majority at DF=2.0 in every scenario, and at DF=1.0 it
  splits (stealing leads in sc1, sc3, sc5). Describe them that way in the
  paper.
- **Deadline satisfaction does not discriminate in this model.** After
  fix 8 the probe (`probe_grid.*`, 5 seeds) finds HADS missing nothing
  from n=20 to 300 down to DF=0.25; Burst-HADS and R-BurstHADS miss
  0.2–0.6 tasks per run in a few cells, with identical counts for both
  schedulers and across all five scenarios, which points at Burst-HADS's
  primary schedule rather than hibernation handling (not yet diagnosed).
  Both source papers lead with deadline satisfaction, but with an
  unlimited on-demand pool every deadline above the longest task can be
  bought, so pushing DF lower only raises cost. A genuinely infeasible
  region needs a capacity constraint — CCScheduler caps on-demand per
  instance type (`limits_ondemand`, see the `hads.py` docstring). That is
  a model change and the **owner's decision**; it has not been made.
- **The baselines satisfice.** HADS lands at 86–100% of D in every cell
  because it only escalates when D is threatened. Makespan percentages
  are therefore partly a statement about how much slack D granted. This
  is why results are reported across a DF span and why the `mk/D` column
  exists. State it in the paper; do not hide it.
- **Work stealing onto a baseline-mode burstable is not slack-checked**
  the way a burst-mode rescue is. On the n=40 trace it put the
  makespan-defining task on the slowest machine in the fleet.
- **`paper/` is entirely pre-fix.** `paper.tex` still claims 14.3–64.3%
  cost savings and a 26.0–39.8% makespan reduction for R-BurstHADS; all of
  it predates fixes 1–10. Do not touch it until the sweep has been run.
- Figures: the owner has a separate unresolved issue with graph
  generation. **Do not generate figures until they raise it.**

## Commands

```powershell
# small sweep, 150 runs, ~13 s on 20 workers (measured 2026-09-13)
python experiments\checkpoint.py --tag NAME_df0.5 --df 0.5
python experiments\checkpoint.py --tag NAME_df1.0 --df 1.0
python experiments\checkpoint.py --tag NAME_df2.0 --df 2.0

# the same with a counterfactual patch from experiments\variants.py --
# measure a candidate fix BEFORE editing the simulator, then check the
# adopted code reproduces the variant checkpoint bit-for-bit
python experiments\checkpoint.py --tag NAME_df1.0 --df 1.0 --variant thm1_D

# one config, three billing policies, fast
python experiments\billing_audit.py --n 300 --seed 0 --kh 5 --kr 0

# forced instance type x VM-count cap
python experiments\template_ab.py --workers 18 --seeds 5

# the full sweep. Bare command = plan (prints what would run, runs nothing).
# Results go to sweep_raw_<code fingerprint>.jsonl, so a code change can
# never resume into rows from older code. The 28 Aug
# results_dynamic_comparison*.json[l] are pre-fix and never read.
python experiments\dynamic_comparison.py
python experiments\dynamic_comparison.py run
python experiments\dynamic_comparison.py summarize
```

Always run all three DF points together. A single DF point is not
trustworthy on its own — that is the lesson of the deadline sweep.
