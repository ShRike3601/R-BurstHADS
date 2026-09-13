"""
Full comparison experiment:
  MinMin, MaxMin, Greedy, ILS On-Demand, HADS, BurstHADS, MR-BurstHADS

Progression story:
  Tier 1 (no ILS, no spot awareness): MinMin, MaxMin, Greedy
  Tier 2 (ILS, no spot):              ILS On-Demand
  Tier 3 (ILS + spot, no burstable):  HADS
  Tier 4 (ILS + spot + burstable):    BurstHADS
  Tier 5 (per-stage ILS):             MR-BurstHADS
"""

import sys
import random
import io
import contextlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import run_simulation, generate_tasks, compute_deadlines
from scheduler.heuristics  import MinMin, MaxMin, Greedy
from scheduler.ils_ondemand import ILSOnDemand
from scheduler.hads         import HADS
from scheduler.burst_hads   import BurstHADS
from scheduler.mr_burst_hads import MRBurstHADS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

TASK_COUNTS      = [10, 20, 50, 100]
DEADLINE_FACTORS = [0.5, 1.0, 2.0]
RUNS_PER_CONFIG  = 5
N_STAGES         = 2
HIB_SCENARIOS    = ["none", "early", "late"]

# Scheduler registry
# (class, needs_stages)
SCHEDULERS = [
    (MinMin,      False),
    (MaxMin,      False),
    (Greedy,      False),
    (ILSOnDemand, False),
    (HADS,        False),
    (BurstHADS,   False),
    (MRBurstHADS, True),
]

SCHEDULER_NAMES = [s[0].__name__ for s in SCHEDULERS]

# Colours for plots — one per scheduler
COLOURS = {
    "MinMin":      "#e41a1c",
    "MaxMin":      "#ff7f00",
    "Greedy":      "#984ea3",
    "ILSOnDemand": "#4daf4a",
    "HADS":        "#377eb8",
    "BurstHADS":   "#a65628",
    "MRBurstHADS": "#000000",
}

MARKERS = {
    "MinMin":      "v",
    "MaxMin":      "^",
    "Greedy":      "D",
    "ILSOnDemand": "s",
    "HADS":        "p",
    "BurstHADS":   "o",
    "MRBurstHADS": "*",
}


def get_hibernation_time(scenario, n_tasks, deadline_factor):
    avg_runtime  = 8.5
    est_makespan = (n_tasks * avg_runtime) / 3 * deadline_factor
    if scenario == "none":
        return None
    elif scenario == "early":
        return max(1, est_makespan * 0.20)
    elif scenario == "late":
        return max(1, est_makespan * 0.60)
    return None


def run_one(scheduler_class, needs_stages, tasks,
            global_deadline, stage_deadlines, hib_time):
    """Run one simulation silently. Returns (makespan, misses, cost)."""
    f = io.StringIO()
    try:
        with contextlib.redirect_stdout(f):
            m = run_simulation(
                scheduler_class,
                tasks,
                global_deadline,
                stage_deadlines=stage_deadlines if needs_stages else None,
                hibernation_time=hib_time,
            )
        s = m.summary()
        return s["makespan"], s["deadline_misses"], s["total_cost"]
    except Exception as e:
        print(f"  [ERROR] {scheduler_class.__name__}: {e}")
        return None, None, None


# ------------------------------------------------------------------
# RESULTS STRUCTURE
# results[df][hib][n][scheduler_name] = {makespan, misses, cost}
# ------------------------------------------------------------------

results = {}
total  = len(DEADLINE_FACTORS) * len(HIB_SCENARIOS) * len(TASK_COUNTS)
config = 0

for df in DEADLINE_FACTORS:
    results[df] = {}
    for hib in HIB_SCENARIOS:
        results[df][hib] = {}
        for n in TASK_COUNTS:
            config += 1
            print(f"\n[{config}/{total}] tasks={n}, df={df}, hib={hib}")

            global_deadline, stage_deadlines = compute_deadlines(
                n, df, N_STAGES
            )
            hib_time = get_hibernation_time(hib, n, df)

            # Initialise accumulators
            acc = {name: {"mk": [], "ms": [], "co": []}
                   for name in SCHEDULER_NAMES}

            for run in range(RUNS_PER_CONFIG):
                seed = 1000 * config + run
                random.seed(seed)
                tasks = generate_tasks(n)

                for cls, needs_stages in SCHEDULERS:
                    mk, ms, co = run_one(
                        cls, needs_stages, tasks,
                        global_deadline, stage_deadlines, hib_time
                    )
                    if mk is not None:
                        acc[cls.__name__]["mk"].append(mk)
                        acc[cls.__name__]["ms"].append(ms)
                        acc[cls.__name__]["co"].append(co)

            def avg(lst):
                return round(sum(lst) / len(lst), 4) if lst else 0

            results[df][hib][n] = {
                name: {
                    "makespan": avg(acc[name]["mk"]),
                    "misses":   avg(acc[name]["ms"]),
                    "cost":     avg(acc[name]["co"]),
                }
                for name in SCHEDULER_NAMES
            }

            # Print summary row
            for name in SCHEDULER_NAMES:
                r = results[df][hib][n][name]
                print(f"  {name:<14} mk={r['makespan']:8.2f}  "
                      f"miss={r['misses']:.1f}  "
                      f"cost={r['cost']:.6f}")

# ------------------------------------------------------------------
# PLOTTING
# ------------------------------------------------------------------

OUTPUT_DIR = PROJECT_ROOT / "experiments" / "plots"
OUTPUT_DIR.mkdir(exist_ok=True)

METRIC_CONFIGS = [
    ("makespan", "Avg Makespan (s)"),
    ("misses",   "Avg Deadline Misses"),
    ("cost",     "Avg Total Cost (USD)"),
]

for metric_key, ylabel in METRIC_CONFIGS:
    for df in DEADLINE_FACTORS:
        for hib in HIB_SCENARIOS:
            fig, ax = plt.subplots(figsize=(9, 5))

            for name in SCHEDULER_NAMES:
                vals = [results[df][hib][n][name][metric_key]
                        for n in TASK_COUNTS]
                ax.plot(
                    TASK_COUNTS, vals,
                    marker=MARKERS[name],
                    color=COLOURS[name],
                    label=name,
                    linewidth=1.8,
                    markersize=7,
                )

            ax.set_xlabel("Number of Tasks")
            ax.set_ylabel(ylabel)
            ax.set_title(
                f"{ylabel}\ndeadline_factor={df}, hibernation={hib}"
            )
            ax.legend(fontsize=8, loc="upper left")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

            fname = (OUTPUT_DIR
                     / f"{metric_key}_df{df}_hib{hib}.png")
            plt.savefig(fname, dpi=130)
            plt.close()

print(f"\nAll experiments complete. Plots -> {OUTPUT_DIR}")