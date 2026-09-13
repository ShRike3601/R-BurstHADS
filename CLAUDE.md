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
experiments/sweep_analysis.py       sweep aggregates + check against checkpoints
experiments/sweep_*_<fp>.*    full-sweep results, one set per code fingerprint
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
losing the disk. Every checkpoint and sweep result file is committed; they
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
  In the sweep grid the floor binds at n=50 for DF ≤ 0.5 (so those two
  DF points are the same cell) and at n=100 for DF = 0.25.
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
  can be bought, and deadline misses are rare (Open items).

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
   hibernation at all HADS missed 7.5 and 7.2 per run. After the fix HADS
   misses no deadline anywhere in the full sweep. It removed the only
   deadline result the study had.
9. **Replacement hibernation parity** (`provisioning_event.py`,
   `main.py`; commit `d9d18c8`) — Table 9 hibernates every pool spot VM
   at `kh/D` and resumes it at `kr/D`, whatever its type. Spot VMs
   R-BurstHADS provisioned mid-run were drawn once at the declared
   c5.xlarge rate, 0.04/hr, with no resume: 12× to 750× safer than the
   identical c5.xlarge already in the pool. They now join the same
   process from their ready time. On the checkpoint cells it cost
   R-BurstHADS its whole average cost advantage over HADS (−5.4% → +2.4%)
   and 7 points of makespan.
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

**Full sweep** on commit `5a6266f` (code fingerprint `fb931f79c624`):
Table 9 sc1–sc5 × n 50/100/200/300 × DF 0.25/0.5/1.0/2.0 × 30 seeds,
7200 runs, 0 errors (`experiments/sweep_raw_fb931f79c624.jsonl`,
`sweep_summary_fb931f79c624.*`, `sweep_analysis_fb931f79c624.txt`).
Seeds 0–9 of the five checkpoint cells reproduce `checkpoint_fix10_df*`
bit-for-bit (450/450 runs). 80 cells, of which 15 have their deadline set
by the floor; at n=50, DF 0.25 and 0.5 are the same cell counted twice.
Percentages are ratios of cell means, averaged over cells.

Relative to HADS:

| cells | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ |
|---|---|---|---|---|---|---|
| all 80 | −12.1% | +34.6% | −26.3% | +5.9% | −17.9% | −19.9% |
| 65 not floor-bound | −14.4% | +38.5% | −31.3% | +4.1% | −21.5% | −23.7% |
| DF=0.25 (20) | −0.1% | +21.9% | −1.9% | +15.8% | −1.8% | −4.8% |
| DF=0.5 (20) | −1.4% | +29.9% | −7.9% | +7.5% | −6.6% | −17.1% |
| DF=1.0 (20) | −6.7% | +44.0% | −30.2% | +6.8% | −25.6% | −25.5% |
| DF=2.0 (20) | −40.4% | +42.7% | −65.1% | −6.5% | −37.8% | −32.1% |

By scenario, R-BurstHADS vs HADS (makespan / cost): sc1 −34.7% / +10.0%,
sc2 −19.2% / +3.5%, sc3 −33.2% / +4.3%, sc4 −20.8% / +5.5%,
sc5 −23.6% / +6.3%.

- R-BurstHADS dominates Burst-HADS on both axes (cell means) in **78 of
  80** cells, and in 81% of individual seeded runs. The two exceptions
  are both at DF=0.25 and marginal: sc3 n=100 (makespan −0.6%, cost
  +0.1%) and sc4 n=300 (makespan +0.1%, cost −10.7%).
- Burst-HADS costs more than HADS in every cell (+1.1% to +119.1%).
- R-BurstHADS's cost against HADS ranges from −33.8% (sc3 n=50 DF=2.0) to
  +37.3% (sc1 n=300 DF=2.0); it is cheaper than HADS in 37% of runs. Its
  premium shrinks with slack and reverses at DF=2.0.
- HADS misses no deadline in any cell. Burst-HADS and R-BurstHADS miss a
  few (Open items).

**The contribution statement this supports:** against Burst-HADS the
result is robust — R-BurstHADS is both faster and cheaper in 78 of 80
cells, by about 18% and 20% on average. Against HADS it is a trade:
about 26% shorter makespan for about 6% more cost on average, with the
cost gap at +16% under the tightest deadlines, closing as slack grows and
reversing (−6.5%) at DF=2.0. Burst-HADS's own premium over HADS (+35%) is
mostly, not entirely, handed back. The makespan gain grows with slack,
and because the baselines satisfice, part of it is slack HADS leaves
unused rather than work R-BurstHADS does faster.

The 15-cell checkpoint table used before the sweep (R-BurstHADS −34.7% /
+2.5% vs HADS, 15/15 dominance, no misses anywhere) was a favourable
subset. Quote the sweep.

Claims that are **dead** and must not reappear: "cheaper and faster than
everything"; **an average cost advantage over HADS**, or "roughly HADS's
cost" as a general statement (+5.9% over the sweep, +15.8% at DF=0.25);
the checkpoint headline (−34.7% / +2.5%, 15/15); "no scheduler misses a
deadline"; the −41.5% / −5.1% table; "HADS misses deadlines and the
others do not" (fix 8 artefact — the sweep shows the reverse, on a small
scale); HADS degrading with more slack; the ILS explanation for HADS's
misses (HADS has no ILS); sc1's premium being Theorem 1 not pricing idle
time; a ~33% Burst-HADS premium "in every cell" (+34.6% on average,
positive in every cell but as low as +1.1%); and the old −52%/−74% figures
(the speed artefact).

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
  n=200 and n=300, DF=2.0. The stated formula is arguably the consistent
  one (C_reactive prices all n_v tasks, so P should cover the time they
  are exposed, not one task), but adopting it moves the result in our
  favour on an illustrative constant crossing an arbitrary threshold.
  **Not adopted.** Decide; if adopted, re-run the sweep and disclose the
  threshold behaviour in the paper.
- **Deadline satisfaction — a small result against us, cause not
  diagnosed.** Over the sweep HADS misses nothing in any of the 80 cells.
  Burst-HADS misses in 22 cells and R-BurstHADS in 21, all at DF ≤ 0.5
  and mostly DF=0.25; the worst is sc2 n=300 DF=0.25, 1.80 and 1.63 tasks
  of 300 per run. R-BurstHADS never misses more than Burst-HADS in a cell.
  At n=200 DF=0.25 the count is 0.23 in all five scenarios, pointing at
  Burst-HADS's primary schedule; at n=300 DF=0.25 it varies by scenario
  (0.37–1.80), so hibernation handling contributes there. Diagnose with
  the same attribution approach as `diag_hads_misses.py` before the paper
  states a cause. More broadly, the on-demand pool is unlimited, so every
  deadline above the longest task can be bought and misses stay near
  zero. A genuinely infeasible region, where deadline satisfaction
  discriminates the way both source papers present it, needs a capacity
  constraint — CCScheduler caps on-demand per instance type
  (`limits_ondemand`, see the `hads.py` docstring). That is a model change
  and the **owner's decision**; it has not been made.
- **sc1 is the weakest regime against HADS, and its recorded cause was
  wrong.** Sweep: R-BurstHADS +10.0% cost vs HADS averaged over sc1
  (+25.8 / +9.6 / +16.6 / +37.3% at n=300, DF 0.25 → 2.0), while still
  cheaper than Burst-HADS in every sc1 cell. The claim that Theorem 1's
  failure to price the replacement's expected idle time causes this is
  **refuted** (`diag_rb_provisioning.*`, `diag_rb_replacement_use.*`,
  both run on the post-fix-9 code): the three replacements are 68–86%
  utilised in sc1 (busy / billed core-seconds), and switching Theorem 1
  off makes R-BurstHADS slower *and* more expensive in every sc1 cell
  (+12% to +78% cost). In sc1 the replacements are 12–21% of
  R-BurstHADS's bill (at n=300, $0.050–0.069 per run against a premium
  over HADS of $0.020–0.093); everything else it pays for is 29–56% below
  Burst-HADS's total. An idle-time term would provision less, toward the
  arm that measures worse on both axes, so it was **not implemented**.
  Report sc1 as a limitation: R-BurstHADS keeps Burst-HADS's
  spread-for-makespan cost structure and recovers most, not all, of its
  premium when interruptions are rare.
- **What Theorem 1's replacements actually do.** Framed as hibernation
  insurance, they are both insurance and early capacity. Hibernation
  rescue is 15–84% of their busy time and Algorithm 5 work stealing
  16–85%: rescue is the majority at DF=0.5 in every scenario except sc3,
  stealing the majority at DF=2.0 in every scenario, and at DF=1.0 it
  splits (stealing leads in sc1, sc3, sc5). Describe them that way in the
  paper.
- **The baselines satisfice.** HADS lands at 56–100% of D across the
  sweep, and at 85–100% at n=300, because it only escalates when D is
  threatened. Makespan percentages are therefore partly a statement about
  how much slack D granted. This is why results are reported across a DF
  span and why the `mk/D` column exists. State it in the paper; do not
  hide it.
- **Work stealing onto a baseline-mode burstable is not slack-checked**
  the way a burst-mode rescue is. On the n=40 trace it put the
  makespan-defining task on the slowest machine in the fleet.
- **`paper/` is entirely pre-fix.** `paper.tex` still claims 14.3–64.3%
  cost savings and a 26.0–39.8% makespan reduction for R-BurstHADS; all of
  it predates fixes 1–10. The sweep it should be rebuilt from now exists,
  but either owner decision above (Theorem 1 horizon, on-demand cap)
  changes the code and requires re-running the sweep (~8 minutes) first.
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

# the full sweep, 7200 runs, ~8 min on 20 workers. Bare command = plan
# (prints what would run, runs nothing). Results go to
# sweep_raw_<code fingerprint>.jsonl, so a code change can never resume
# into rows from older code. The 28 Aug results_dynamic_comparison*.json[l]
# are pre-fix and never read.
python experiments\dynamic_comparison.py
python experiments\dynamic_comparison.py run
python experiments\dynamic_comparison.py summarize
python experiments\sweep_analysis.py      # verifies against checkpoint_fix10 first
```

Always run all three DF points together. A single DF point is not
trustworthy on its own — that is the lesson of the deadline sweep.
