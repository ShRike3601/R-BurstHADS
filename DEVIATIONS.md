# Deviations from the published algorithms

Every place this simulator's HADS and Burst-HADS differ from what Teylo et
al. publish, what the difference is, why it exists, and its measured
effect. It is a section of the paper, and it is the honest answer to the
fact that the baselines do not validate (CLAUDE.md, first open item): we
disclose and quantify rather than claim fidelity we do not have.

Sources, cited by the name used in this file:

- **TCC23** — L. Teylo, L. Arantes, P. Sens, L. M. A. Drummond, "Scheduling
  Bag-of-Tasks in Clouds Using Spot and Burstable Virtual Machines", IEEE
  Trans. Cloud Comput. 11(1), 2023 (Burst-HADS). Table numbers as printed:
  Table 3 VM catalogue, Table 6 jobs, Table 7 no-hibernation comparison,
  Table 8 scenarios, Table 9 hibernation comparison, Table 10 J60 runtime
  fluctuation.
- **CC21** — the Cluster Computing 2021 HADS paper.
- **REF** — the reference implementation, github.com/luanteylo/hads_
  (`control/scheduler/CCScheduler.py` for HADS, `IPDPS.py` for Burst-HADS,
  `input/{example,masa}/env.json`).

Status: **open** (the code still differs), **corrected** (the code now
follows the source; kept here because earlier results used the deviation),
**design** (a deliberate modelling choice this study keeps).

"Measured effect" cites the evidence file. "Unmeasured" means exactly that.

## Cost and billing model

| # | Deviation | Source says | Ours | Why | Measured effect | Status |
|---|---|---|---|---|---|---|
| B1 | When billing starts | TCC23 §3.1: "When a new vmj is launched, the user is charged cj for each period of time" | Billing starts at a VM's first task dispatch (`VM.start_next_if_free`), not at launch. A launched VM that never receives a task costs nothing. | Inherited modelling choice | Affects Burst-HADS's proactive burstables most: on J60 without hibernation it launches 2.5 t3.large and bills none (`diag_validation_costs_*`). Cost effect under TCC23's rule: measured in Round A | open |
| B2 | Charges while hibernated | TCC23 §1: during hibernation "the user is only charged for the EBS storage use"; its formulation (§3.1) stops the charge on hibernation | No charge at all while hibernated | Follows §3.1's formulation | Round A (EBS sensitivity) | open |
| B3 | Billing granularity | TCC23 §3.1: charged per period of T = {1..D}; D = 2,700 with runtimes in seconds, i.e. per second | Per second from first dispatch to shutdown or hibernation (fix 2) | — | Matches the stated formulation; an allocation-cycle-quantised rule is measured in Round A as a sensitivity, not as the paper's model | design |
| B4 | End of run | TCC23 does not say | Every surviving VM is terminated when the last task completes (fix 3, `_release_fleet_if_done`) | Otherwise VMs idle past the job and are billed another 900 s | Fix 3 recorded in CLAUDE.md; effect on validation measured in Round A (pre-fix-2 billing variant) | design |
| B5 | Resumed VMs that were never launched | TCC23: only launched VMs run, hibernate and resume | Table 8 events hibernate and resume every pool spot VM, launched or not, and `ResumeEvent` starts billing unconditionally, so a never-launched pool VM can start billing on "resume" | Unintended | Round A | open |

## Burst-HADS (TCC23, REF `IPDPS.py`)

| # | Deviation | Source says | Ours | Why | Measured effect | Status |
|---|---|---|---|---|---|---|
| U1 | Planner prediction order | Execution order is implied: a queue runs in the order it is scheduled | `_compute_vm_load` / `_solution_task_finish_times` list-scheduled in task-id order; execution runs memory-descending | Unintended | Produced every residual deadline miss in the fixes-1–10 sweep (`diag_primary_stages.*`) | corrected (fix 11) |
| U2 | Eq 9 normaliser | TCC23 §3.1: cost divided by the dearest spot VM's cost over Dspot times the maximum number of deployable VMs; infeasible scores 1 | Normaliser covered spot VMs only, but the initial solution's Phase 3 adds on-demand VMs, so feasible scores exceeded 1 and infeasible schedules won | U3 introduced on-demand VMs into the search space | With U1 fixed, removed all misses (`sweep_variant_b_*`). Now normalised over spot pool + the initial solution's on-demand VMs | corrected (fix 11) |
| U3 | On-demand fallback inside the primary schedule | REF `IPDPS.py` static scheduler raises "THERE IS NO SOLUTION WITH THAT DEADLINE" when spot capacity is exhausted | `_initial_solution` Phase 3 places the task on an on-demand VM judged against D | Otherwise tasks were silently dropped from the allocation | Unmeasured | design |
| U4 | Planner checkpoint overhead | Execution charges (1 + ovh) | Planner predicted without it | Unintended | All HADS deadline misses (`diag_hads_misses.*`) | corrected (fix 8) |
| U5 | Proactive burstable allocation guard | TCC23 §3.2: Dspot violators move to the burstables; "if a burstable VM remains idle, the task with the latest finishing time in the scheduling map is moved to it" | A task moves only if its baseline-mode finish beats its planned finish, so burstables can stay idle | Added by an earlier session after a baseline-mode task set a makespan past D | Removing it (variant `nocap+burst_fill`): no-hibernation makespan matches Table 7 for J60/J80 (1,305 / 1,332 s vs 1,274 / 1,329) but cost change overshoots (+254 / +124% vs +66 / +45%) (`baseline_validation_variants_compare.txt`) | open — revisit after Round A |
| U6 | Migration candidates | TCC23 Alg. 4 inputs: "the sets of idle, busy, and non-launched regular on-demand VMs (IR, BR and Mo)" | Attempts 1–2 accept never-launched pool VMs as well | Unintended | Restricting to launched VMs (variant `nocap+mig_launched`): hibernation aggregates 14.7 → 21.5% makespan reduction (published 25.87%), +38.7 → +16.0% cost (+1.92%) | open — adopt in Round B |
| U7 | ILS relaxation | TCC23 Alg. 1 lines 11–13: RDspot grows by relaxed_rate when stalled | Grows at most once per max_failed stall window and never past D | A per-iteration reading compounded Dspot to 3.45e18 | Unmeasured against the literal reading | design |
| U8 | Infeasibility score | TCC23 Eq 9: 1 | 1, with U2's normaliser; REF `IPDPS.py` uses +inf | Follows the paper | +inf variant (`b_order_inf`) gives near-identical results | design |
| U9 | Deployment overhead ω | TCC23: time to deploy a new VM | `STARTUP_LATENCY = 45 s` for new on-demand VMs in the migration deadline test | Not stated numerically in TCC23 | Unmeasured | design |

## HADS (CC21, REF `CCScheduler.py`)

| # | Deviation | Source says | Ours | Why | Measured effect | Status |
|---|---|---|---|---|---|---|
| H1 | Queue packing | REF `Queue`: interval-based multi-core slot search with memory overlap | "Least-loaded core" list scheduling, shared with Burst-HADS | Same packing model for all schedulers | Unmeasured | design |
| H2 | Migration candidates | REF `CCScheduler.migrate`: idle and working dispatchers are running instances; `backup_heuristic` opens only on-demand queues | Stages 1–2 accept never-launched pool VMs (so HADS launches fresh spot VMs to recover) | Unintended; contradicts `hads.py`'s own docstring | Part of U6's variant: HADS bills 3.1 spot VMs on J60 without hibernation, 7.7 in sc1 (`diag_validation_costs_*`) | open — adopt in Round B |
| H3 | Work stealing | Not part of HADS (Algorithm 5 is Burst-HADS's contribution) | Disabled | Follows the source | Earlier measurement recorded in `hads.py` | design |
| H4 | Planner checkpoint overhead | as U4 | as U4 | as U4 | as U4 | corrected (fix 8) |

## Environment, catalogue and workload

| # | Deviation | Source says | Ours | Why | Measured effect | Status |
|---|---|---|---|---|---|---|
| E1 | Instance limits | REF `env.json`: 5 on-demand and 5 preemptible per instance type, global 20 / 20; `backup_heuristic` walks every on-demand type | Implemented (fix 12), but each of our catalogues holds ONE on-demand type, so the on-demand ceiling is 5 instead of min(5 × 3, 20) = 15 | Catalogue construction | ED200 sc2 stalls at 5 on-demand VMs: makespan ~5,900 s vs D = 2,700, ~40 misses per run; uncapped it uses 8.1–8.5 (`diag_validation_costs_*`) | open — Round B: TCC23 Table 3's three on-demand types for both catalogues |
| E2 | Migration at a spent limit | REF `backup_heuristic`: task left unallocated | Placed on the active VM that would finish it soonest | Unallocated tasks would vanish from every metric | Forced overrides: 0 in the capped sweep | design |
| E3 | On-demand template when all on-demand VMs have terminated | — | `_launch_new_ondemand_vm` falls back to a hardcoded c5.large (speed 2, $0.085) | Bug | Seen at 0.1 launches per run (HADS J60 sc1, paper catalogue) | open — Round B fix |
| E4 | Spot pool size | TCC23 does not state it; REF limit 5 per type | `SPOT_COPIES = 3` (sweep), `copies = 3` (validation) | Chosen to reproduce the paper's reported gap | Burst-HADS no-hibernation makespan is highly sensitive: J60 change vs HADS −71% at 3 copies, −78% at 5, −79% at 6 (`baseline_validation_compare.txt`) | design |
| E5 | Job generator (validation) | TCC23 Table 6: runtime and memory min / average / max | `paper_reproduction.gen_job`: uniform over [min, max], mean runtime 6 / 6 / 14 / 22% above Table 6's averages | Harness shortcut | Two generators reported side by side (`baseline_validation_compare.txt`); `table6` generator matches the averages | design (both reported) |
| E6 | Hibernation process | TCC23 §4: Poisson, λh = kh/D, λr = kr/D per spot VM | Same, applied to every pool spot VM including never-launched ones (see B5), and to VMs launched mid-run (fix 9) | — | See B5 | open (B5) |
| E7 | Per-core speed | TCC23: GFlops from LINPACK per instance | `PER_CORE_SPEED`, one value per family, whole-machine = speed × vCPUs (fix 4) | GFlops per type not published | Fix 4 recorded in CLAUDE.md | design |
