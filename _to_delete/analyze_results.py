"""
Analysis: MR-BurstHADS cost reduction over BurstHADS and HADS.
Run this after run_experiments.py to get a clean summary.
"""

import sys
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import run_simulation, generate_tasks, compute_deadlines
from scheduler.hads        import HADS
from scheduler.burst_hads  import BurstHADS
from scheduler.mr_burst_hads import MRBurstHADS

import io
import contextlib

TASK_COUNTS      = [10, 20, 50, 100]
DEADLINE_FACTORS = [0.5, 1.0, 2.0]
RUNS_PER_CONFIG  = 10       # more runs for stable averages
N_STAGES         = 2
HIB_SCENARIOS    = ["none", "early", "late"]


def run_one_silent(scheduler_class, needs_stages, tasks,
                   global_deadline, stage_deadlines, hib_time):
    f = io.StringIO()
    try:
        with contextlib.redirect_stdout(f):
            m = run_simulation(
                scheduler_class, tasks, global_deadline,
                stage_deadlines=stage_deadlines if needs_stages else None,
                hibernation_time=hib_time,
            )
        s = m.summary()
        return s["makespan"], s["deadline_misses"], s["total_cost"]
    except Exception:
        return None, None, None


def get_hibernation_time(scenario, n_tasks, deadline_factor):
    est = (n_tasks * 8.5) / 5 * deadline_factor
    if scenario == "none":  return None
    if scenario == "early": return max(1, est * 0.20)
    if scenario == "late":  return max(1, est * 0.60)
    return None


# ------------------------------------------------------------------
# COLLECT RESULTS
# ------------------------------------------------------------------

print("Running analysis (this may take a few minutes)...\n")

# Store per-config reductions
reductions_vs_burst  = []  # MD cost reduction % over BurstHADS
reductions_vs_hads   = []  # MD cost reduction % over HADS
makespan_overhead    = []  # MD makespan increase % over BurstHADS

config = 0
for df in DEADLINE_FACTORS:
    for hib in HIB_SCENARIOS:
        for n in TASK_COUNTS:
            config += 1

            global_deadline, stage_deadlines = compute_deadlines(
                n, df, N_STAGES
            )
            hib_time = get_hibernation_time(hib, n, df)

            hads_costs, burst_costs, md_costs = [], [], []
            burst_mks, md_mks = [], []

            for run in range(RUNS_PER_CONFIG):
                seed = 999 * config + run
                random.seed(seed)
                tasks = generate_tasks(n)

                _, _, co = run_one_silent(
                    HADS, False, tasks,
                    global_deadline, stage_deadlines, hib_time
                )
                if co: hads_costs.append(co)

                mk, _, co = run_one_silent(
                    BurstHADS, False, tasks,
                    global_deadline, stage_deadlines, hib_time
                )
                if co:
                    burst_costs.append(co)
                    burst_mks.append(mk)

                mk, _, co = run_one_silent(
                    MRBurstHADS, True, tasks,
                    global_deadline, stage_deadlines, hib_time
                )
                if co:
                    md_costs.append(co)
                    md_mks.append(mk)

            def avg(lst): return sum(lst)/len(lst) if lst else 0

            ac = avg(hads_costs)
            bc = avg(burst_costs)
            mc = avg(md_costs)
            bm = avg(burst_mks)
            mm = avg(md_mks)

            if bc > 0 and mc > 0:
                rer_burst = (bc - mc) / bc * 100
                reductions_vs_burst.append((n, df, hib, rer_burst))

            if ac > 0 and mc > 0:
                red_hads = (ac - mc) / ac * 100
                reductions_vs_hads.append((n, df, hib, red_hads))

            if bm > 0 and mm > 0:
                mk_oh = (mm - bm) / bm * 100
                makespan_overhead.append((n, df, hib, mk_oh))

# ------------------------------------------------------------------
# REPORT
# ------------------------------------------------------------------

print("=" * 65)
print("MR-BurstHADS COST REDUCTION vs BurstHADS")
print("=" * 65)
print(f"{'Tasks':>6} {'DF':>5} {'Hib':>6}  {'Cost Reduction %':>16}")
print("-" * 65)
for n, df, hib, red in reductions_vs_burst:
    marker = " <--" if red > 15 else ""
    print(f"{n:>6} {df:>5} {hib:>6}  {red:>15.1f}%{marker}")

all_reds = [r for _, _, _, r in reductions_vs_burst]
print("-" * 65)
print(f"  Average cost reduction: {sum(all_reds)/len(all_reds):.1f}%")
print(f"  Min reduction:          {min(all_reds):.1f}%")
print(f"  Max reduction:          {max(all_reds):.1f}%")
positive = [r for r in all_reds if r > 0]
print(f"  Configs where MD wins:  {len(positive)}/{len(all_reds)}")

print()
print("=" * 65)
print("MR-BurstHADS COST REDUCTION vs HADS")
print("=" * 65)
all_hads_reds = [r for _, _, _, r in reductions_vs_hads]
print(f"  Average cost reduction: {sum(all_hads_reds)/len(all_hads_reds):.1f}%")
print(f"  Min reduction:          {min(all_hads_reds):.1f}%")
print(f"  Max reduction:          {max(all_hads_reds):.1f}%")

print()
print("=" * 65)
print("MR-BurstHADS MAKESPAN OVERHEAD vs BurstHADS")
print("(positive = MD is slower, negative = MD is faster)")
print("=" * 65)
all_oh = [r for _, _, _, r in makespan_overhead]
print(f"  Average overhead: {sum(all_oh)/len(all_oh):.1f}%")
print(f"  Min overhead:     {min(all_oh):.1f}%")
print(f"  Max overhead:     {max(all_oh):.1f}%")
faster = [r for r in all_oh if r < 0]
print(f"  Configs where MD is faster: {len(faster)}/{len(all_oh)}")

print()
print("=" * 65)
print("BREAKDOWN BY TASK COUNT (cost reduction vs BurstHADS)")
print("=" * 65)
for n in TASK_COUNTS:
    reds = [r for tn, _, _, r in reductions_vs_burst if tn == n]
    if reds:
        print(f"  {n:>4} tasks: avg={sum(reds)/len(reds):.1f}%  "
              f"min={min(reds):.1f}%  max={max(reds):.1f}%")

print()
print("=" * 65)
print("BREAKDOWN BY HIBERNATION SCENARIO (cost reduction vs BurstHADS)")
print("=" * 65)
for hib in HIB_SCENARIOS:
    reds = [r for _, _, h, r in reductions_vs_burst if h == hib]
    if reds:
        print(f"  {hib:>6}: avg={sum(reds)/len(reds):.1f}%  "
              f"min={min(reds):.1f}%  max={max(reds):.1f}%")

print()
print("Analysis complete.")
