"""Build the PROPOSED corrected deviation register from DEVIATIONS.md without
editing it. Usage: python dev_proposal.py PROJECT_ROOT OUT_PATH KEY=VALUE...
Placeholders <<KEY>> are filled from the arguments; any left unfilled aborts."""
import re, sys
from pathlib import Path

root, out = Path(sys.argv[1]), Path(sys.argv[2])
fill = dict(a.split("=", 1) for a in sys.argv[3:])
text = (root / "DEVIATIONS.md").read_text(encoding="utf-8")


def rep(old, new):
    global text
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"MISMATCH ({n}): {old[:120]}")
    text = text.replace(old, new)


# ── header: the freeze was lifted once and re-set ──
rep("""**FROZEN.** The simulator was frozen at tag `freeze-round-b` (code
fingerprint `4f08f48ac35c`). From then on a newly found defect is added to
this table as a limitation, with its measured effect where one exists, and
the code is not changed.""",
    """**FROZEN.** The simulator is frozen at tag `<<TAG>>` (code fingerprint
`<<FP2>>`). It was first frozen at `freeze-round-b` (`4f08f48ac35c`); the
owner lifted that freeze once, after the U10 diagnostic showed R-BurstHADS's
misses came from its own saturation response, for fixes 17a, 18, 19 and 20,
each pre-registered (`experiments/fix17_plan.md`, `experiments/fix18_20_plan.md`),
measured as a variant against `4f08f48ac35c`, and adopted only as code that
reproduces the combined variant row for row. From now on a newly found
defect is added to this table as a limitation, with its measured effect
where one exists, and the code is not changed.""")

# ── U10: measured, corrected ──
rep("""Found while writing Round B part 2, after the grid had closed Round A | Unmeasured. Nothing in the freeze sweep points at it: HADS and Burst-HADS miss 0 and 1 tasks in 7,200 runs | open — limitation (freeze) |""",
    """Found while writing Round B part 2, after the grid had closed Round A | Not the cause of R-BurstHADS's 109 misses at `freeze-round-b` (0 of 109; see R1). Fix 20 (the test charges (1 + ovh)) changes 0 of 7,200 runs alone, 0 on top of fix 18 and 0 within the combined set, in every scheduler (`fix18_20_compare.txt`). Why (`diag_u10_window.txt`, 14,400 probed runs, all reproduced): the walk takes the first memory-fitting type that passes, else the cheapest in-limit type, and in both catalogues no dearer on-demand type runs a task faster than a cheaper one (sweep c5.large 2.0, c5.xlarge 2.0, m5.xlarge 1.7 per core; validation one speed). So when the first fitting type fails the test every later type fails too, and adding the overhead can change the launched type only when that type passes without it, fails with it, and is not the cheapest in-limit type (a task too big for the cheapest type's memory). Of 8,078 / 8,289 fresh-VM walks (frozen code + fix 20 / all four fixes), 33 / 34 had a type passing only without the overhead; in 0 did the launched type change. The harm the row describes (a cheaper type chosen that finishes past D) cannot arise in these catalogues | inert — fix 20 (`<<COMMIT>>`) is in the code because the test should charge what execution charges, but it changes no run: 0 of 7,200 in the sweep catalogue (measured), and by the argument above it can bind only through memory in the validation catalogue (not measured separately). It fixed nothing |""")

# ── new environment rows: checkpoint credit, boot time ──
e10_end = re.search(r"^\| E10 \|.*\|$", text, flags=re.M)
new_env = """
| E11 | Progress credited at a checkpoint | Execution runs a task at speed / (1 + ovh): `VM.start_next_if_free` charges the overhead on the whole remaining time (fixes 8, 10) | `Task.save_checkpoint` credited elapsed × speed, so a task hibernated while running kept progress it had not made: 0.490 / 0.705 / 0.788% of the workload for HADS / Burst-HADS / R-BurstHADS (17.4 / 25.2 / 27.9 displaced running tasks per run; `diag_overcredit_boot.txt`) | Unintended. Favours the scheduler that displaces the most running work, R-BurstHADS most | Fix 19 (credit elapsed × speed / (1 + ovh)) alone, against `4f08f48ac35c`: runs changed 1,472 / 1,769 / 1,531 of 2,400; mean cost +0.61 / +0.99 / +1.00%, makespan +0.14 / +0.79 / +0.71%; Burst-HADS vs HADS cost +21.34 → +21.16%; R-BurstHADS vs Burst-HADS cost −5.39 → −5.30%, dominance 44 → 43 of 75, significantly dearer 7 → 9; R-BurstHADS missed tasks 109 → 131. Within the combined set (all four fixes against all but 19): R-BurstHADS cost +1.22%, makespan +0.97%; R vs Burst-HADS cost +0.29 points, dominance −2, missed tasks ±0 (`fix18_20_compare.txt`). Validation catalogue: <<VAL19>> | corrected (fix 19, `<<COMMIT>>`) |
| E12 | Boot time of VMs launched mid-run | TCC23: ω is the time to deploy a new VM; Algorithm 4 Attempt 3 tests start + e + ω < D | Only the spot VMs R-BurstHADS provisions mid-run wait (ready_time = t + 45 s, enforced since fix 18). Every on-demand and burstable VM launched mid-run — Algorithm 4 Attempt 3 in all three schedulers, and R-BurstHADS's own on-demand and burstable provisions (ready_time = t) — runs tasks at once, although Attempt 3's test charges ω = 45 s (U9) | Fix 18 enforced the delay where the code already modelled one (`ProvisioningEvent`) and nowhere else | Unmeasured. Since fix 18 the asymmetry runs against R-BurstHADS: its spot replacements wait 45 s, the baselines' fresh on-demand VMs do not | open — limitation (<<TAG>>) |"""
text = text[:e10_end.end()] + new_env + text[e10_end.end():]

# ── new section: R-BurstHADS ──
text = text.rstrip("\n") + """

## R-BurstHADS (this study's scheduler)

These rows compare the code with R-BurstHADS's own specification: the module
docstring and Theorems 1–2 of `scheduler/r_burst_hads.py`, and its description
in the committed paper draft.

| # | Deviation | Specification says | Ours | Why | Measured effect | Status |
|---|---|---|---|---|---|---|
| R1 | Deadline test in the saturation re-placement | A rescued task goes where it meets D: the migration test of Algorithm 4 (`_check_migration`), otherwise Algorithm 4's on-demand attempt | `_respond_to_saturation` re-placed every queued task on the target with the earliest predicted finish, taking `all_targets[0]` when none met D, without testing D | Unintended | **Caused R-BurstHADS's misses at `freeze-round-b`, not the instance limit.** 108 of the 109 missed tasks (in 104 runs) were last placed by this redistribution on a t3.large R-BurstHADS provisioned, with the response's own predicted finish already past D, when a fresh on-demand VM within the limits could still have finished 108 of them by D; the first placement onto that burstable was this redistribution for 71 and a hibernation rescue through tier 0 for 37 (`diag_u10.txt`; all 108 re-derived from an independent reservation log, 0 disagreements, `diag_u10_verify.txt`). The limit is the trigger, not the cause: with no launch room the response reshuffles the queue instead of launching (253 responses in the missing runs launched 1 VM between them), and every missing run had reached a limit, as had 93.5% of runs without a miss. Fix 17a (`_check_migration` on each target, otherwise `_attempt_ondemand_fallback`) alone: missed tasks 109 → 1 (runs 104 → 1), 162 of 2,400 R-BurstHADS runs changed, mean cost −0.05%, makespan −0.07%; R vs Burst-HADS cost −5.39 → −5.45%, makespan −12.70 → −12.78%, dominance 44 of 75 unchanged (`fix17_compare.txt`). Within the combined set: missed tasks −126. The remaining miss (sc2, n = 100, DF = 0.25, seed 25) no in-limit VM could have saved | corrected (fix 17a, `<<COMMIT>>`) |
| R2 | Saturation response with no launch room | Theorem 2 sizes a replacement fleet of ceil(n_rescued / TASKS_PER_VM_CAP) VMs | When no VM of the needed type can be launched, the response still redistributes the queue over the existing targets | Unintended; kept | Fix 17b (return when the needed type cannot be launched), measured, not adopted: alone missed tasks 109 → 1, but 337 of 2,400 runs changed (175 more than 17a for the same miss count), dominance 44 → 43 of 75, mean makespan +0.02% and cost +0.01% against the baseline (17a: −0.07 / −0.05%), R vs Burst-HADS cost −5.4%. With 17a it changes the same 337 runs as alone and leaves 1 missed task: it subsumes 17a rather than complementing it (`fix17_compare.txt`) | open — measured and rejected (owner): subsumes 17a, changes more runs, worse on dominance and makespan |
| R3 | When the saturation response fires | Theorem 2 is stated per hibernation event ("at hibernation time t with n_rescued tasks"), and the paper sizes replacement capacity "when spot capacity is lost" as a deficit against the surviving fleet, provisioning nothing when that fleet can already retire the queue by D. The module docstring's motivating scenario, a comment ("Only act when pool is actually saturated (all spot VMs down)") and the names `_respond_to_saturation` / `_saturation_handled` describe total loss | The trigger returns only when every pool spot VM is active (`len(active_spot) >= len(self.spot_vms)`), so the response fires whenever any spot VM is down | The code follows the specification: re-planning on lost capacity, sized against what survives, is what Theorem 2 and the paper state. Total loss is the motivating case, not the condition; the comment, docstring scenario and names are stale | Fix 17c (fire only when no spot VM is active), measured, not adopted: missed tasks 109 → 73 (71 runs, 31 of them newly missing, 57 of the 71 in sc2), 282 of 2,400 runs changed, mean makespan +0.07%, cost +0.05%, R vs Burst-HADS cost −5.4 → −5.3%, dominance 44 → 43, significantly cheaper 29 → 27 (`fix17_compare.txt`) | design — code kept (owner); comment, docstring and names stale |
| R4 | Boot delay of VMs R-BurstHADS provisions | A VM provisioned at t is usable from its ready_time, when its `ProvisioningEvent` fires (spot: t + 45 s) | A task placed on a spot VM still booting started at once: 6,661 early starts in 1,276 of 2,400 runs, 26.9 s early on average, 178,906 s in total; none on burstables (`diag_overcredit_boot.txt`) | Unintended. In R-BurstHADS's favour | Fix 18 (no task starts, and no finish is predicted, before ready_time) alone: 927 of 2,400 R-BurstHADS runs changed; R vs Burst-HADS cost −5.39 → −4.96%, makespan −12.70 → −12.56%; R vs HADS cost +12.94 → +13.47%; significantly cheaper 29 → 28, dearer 7 → 9, faster 45 → 42, slower 9 → 11; missed tasks 109 → 120. Within the combined set: R vs Burst-HADS cost +0.65 points, makespan +0.41, dominance −1, significantly dearer +3, missed tasks ±0 (`fix18_20_compare.txt`). See E12 for the VMs it does not cover | corrected (fix 18, `<<COMMIT>>`) |
"""

for k, v in fill.items():
    text = text.replace(f"<<{k}>>", v)
left = sorted(set(re.findall(r"<<([A-Z0-9]+)>>", text)))
if left:
    raise SystemExit(f"unfilled: {left}")
out.write_text(text, encoding="utf-8")
print(f"wrote {out}")
