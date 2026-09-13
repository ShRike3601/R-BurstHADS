"""
MR-BurstHADS Boundary Sweep Experiment

Uses the ORIGINAL 5-VM pool that produced valid MR-BurstHADS results.
Compares: HADS vs BurstHADS vs MR-BurstHADS

Sweeps exec_time_max: 15, 30, 50, 75, 100, 150, 200 seconds
"""

import sys
import random
import io
import contextlib
import math
from pathlib import Path
from multiprocessing import Pool, cpu_count
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

EXEC_TIME_RANGES = [
    (2,  15),
    (2,  30),
    (2,  50),
    (2,  75),
    (2, 100),
    (2, 150),
    (2, 200),
]

TASK_COUNTS      = [10, 20, 50, 100, 200, 300]
DEADLINE_FACTORS = [0.5, 1.0, 2.0]
HIB_SCENARIOS    = ["none", "early", "late"]
RUNS_PER_CONFIG  = 20
N_STAGES         = 2


def build_original_vms():
    """
    ORIGINAL 5-VM pool used when MR-BurstHADS showed cost reduction.
    Two instances of each type, matching old experiments.
    No hibernation_rate field needed — uses base VM constructor.
    """
    from models.vm import VM
    return [
        VM(0, "c3.large",  VM.SPOT,      speed=2, cost_rate=0.0299/3600,
           memory_gb=3.75),
        VM(1, "c3.large",  VM.SPOT,      speed=2, cost_rate=0.0299/3600,
           memory_gb=3.75),
        VM(2, "c4.large",  VM.SPOT,      speed=2, cost_rate=0.0366/3600,
           memory_gb=3.75),
        VM(3, "c4.large",  VM.SPOT,      speed=2, cost_rate=0.0366/3600,
           memory_gb=3.75),
        VM(4, "c3.xlarge", VM.SPOT,      speed=4, cost_rate=0.0634/3600,
           memory_gb=7.50),
        VM(5, "c3.xlarge", VM.SPOT,      speed=4, cost_rate=0.0634/3600,
           memory_gb=7.50),
        VM(6, "t3.large",  VM.BURSTABLE, speed=2, cost_rate=0.0832/3600,
           memory_gb=8.0, baseline_fraction=0.20),
        VM(7, "t3.large",  VM.BURSTABLE, speed=2, cost_rate=0.0832/3600,
           memory_gb=8.0, baseline_fraction=0.20),
        VM(8, "c5.large",  VM.ONDEMAND,  speed=2, cost_rate=0.085/3600,
           memory_gb=4.0),
        VM(9, "c5.large",  VM.ONDEMAND,  speed=2, cost_rate=0.085/3600,
           memory_gb=4.0),
    ]


def run_one(args):
    config_id, exec_min, exec_max, n, df, scenario = args

    import sys, random, io, contextlib, math, copy
    from pathlib import Path

    proj = Path(__file__).resolve().parent.parent
    if str(proj) not in sys.path:
        sys.path.insert(0, str(proj))

    from models.task  import Task
    from models.job   import Job
    from models.stage import Stage
    from models.vm    import VM
    from models.utils import flatten_and_assign_deadlines
    from simulation.event_engine     import EventEngine
    from simulation.execution_engine import start_execution
    from simulation.events           import HibernationEvent
    from metrics.metrics             import Metrics
    from scheduler.hads              import HADS
    from scheduler.burst_hads        import BurstHADS
    from scheduler.mr_burst_hads     import MRBurstHADS

    def build_vms_local():
        return [
            VM(0, "c3.large",  VM.SPOT,      speed=2, cost_rate=0.0299/3600, memory_gb=3.75),
            VM(1, "c3.large",  VM.SPOT,      speed=2, cost_rate=0.0299/3600, memory_gb=3.75),
            VM(2, "c4.large",  VM.SPOT,      speed=2, cost_rate=0.0366/3600, memory_gb=3.75),
            VM(3, "c4.large",  VM.SPOT,      speed=2, cost_rate=0.0366/3600, memory_gb=3.75),
            VM(4, "c3.xlarge", VM.SPOT,      speed=4, cost_rate=0.0634/3600, memory_gb=7.50),
            VM(5, "c3.xlarge", VM.SPOT,      speed=4, cost_rate=0.0634/3600, memory_gb=7.50),
            VM(6, "t3.large",  VM.BURSTABLE, speed=2, cost_rate=0.0832/3600, memory_gb=8.0, baseline_fraction=0.20),
            VM(7, "t3.large",  VM.BURSTABLE, speed=2, cost_rate=0.0832/3600, memory_gb=8.0, baseline_fraction=0.20),
            VM(8, "c5.large",  VM.ONDEMAND,  speed=2, cost_rate=0.085/3600,  memory_gb=4.0),
            VM(9, "c5.large",  VM.ONDEMAND,  speed=2, cost_rate=0.085/3600,  memory_gb=4.0),
        ]

    def local_std(lst):
        if len(lst) < 2: return 0.0
        mean = sum(lst) / len(lst)
        return math.sqrt(sum((x - mean)**2 for x in lst) / len(lst))

    avg_rt          = (exec_min + exec_max) / 2.0
    n_vms_parallel  = 5
    base            = (n * avg_rt) / n_vms_parallel
    global_deadline = base * df
    stage_deadlines = [global_deadline * (i+1) / N_STAGES
                       for i in range(N_STAGES)]

    est      = base * df
    hib_time = None
    if scenario == "early": hib_time = max(1, est * 0.20)
    elif scenario == "late": hib_time = max(1, est * 0.60)

    results = {k: {"cost": [], "mk": []}
               for k in ("hads", "burst", "md")}

    for run in range(RUNS_PER_CONFIG):
        seed = 777 * config_id + run
        random.seed(seed)

        tasks_raw = [
            Task(i, job_id=0, stage_id=0,
                 exec_time=random.randint(exec_min, exec_max),
                 memory_req=random.uniform(2.85, 13.19))
            for i in range(n)
        ]

        for key, cls, needs_stages in [
            ("hads",  HADS,        False),
            ("burst", BurstHADS,   False),
            ("md",    MRBurstHADS, True),
        ]:
            tc = copy.deepcopy(tasks_raw)
            for t in tc:
                t.assigned_vm = None; t.start_time = None
                t.finish_time = None; t.completed = False
                t.current_event = None
                t.exec_start_on_current_vm = None
                t.checkpointed_remaining   = None
                t.remaining_time = t.exec_time

            if needs_stages:
                tps = len(tc) // N_STAGES
                stages = []
                for s, dl in enumerate(stage_deadlines):
                    start = s * tps
                    end   = start + tps if s < N_STAGES-1 else len(tc)
                    for t in tc[start:end]: t.stage_id = s
                    stages.append(Stage(stage_id=s, deadline=dl,
                                        tasks=tc[start:end]))
                job = Job(job_id=0, stages=stages)
            else:
                for t in tc: t.stage_id = 0
                job = Job(job_id=0, stages=[
                    Stage(stage_id=0, deadline=global_deadline, tasks=tc)
                ])

            jobs      = [job]
            all_tasks = flatten_and_assign_deadlines(jobs)
            vms       = build_vms_local()

            f = io.StringIO()
            try:
                with contextlib.redirect_stdout(f):
                    sched = cls(vms, all_tasks, jobs,
                                deadline=global_deadline)
                    sched.schedule(0)
                    engine = EventEngine(sched)
                    sched.event_engine = engine
                    start_execution(vms, 0, engine)
                    if hib_time is not None:
                        spot = [v for v in vms if v.is_spot]
                        if spot:
                            engine.add_event(
                                HibernationEvent(hib_time, spot[0], sched))
                    engine.run()
                    m = Metrics(jobs, vms)
                    s = m.summary()
                results[key]["cost"].append(s["total_cost"])
                results[key]["mk"].append(s["makespan"])
            except Exception:
                pass

    def avg(lst): return sum(lst)/len(lst) if lst else 0

    return {
        "exec_max":   exec_max,
        "n": n, "df": df, "scenario": scenario,
        "hads_cost":  avg(results["hads"]["cost"]),
        "burst_cost": avg(results["burst"]["cost"]),
        "md_cost":    avg(results["md"]["cost"]),
        "hads_mk":    avg(results["hads"]["mk"]),
        "burst_mk":   avg(results["burst"]["mk"]),
        "md_mk":      avg(results["md"]["mk"]),
        "burst_cost_std": local_std(results["burst"]["cost"]),
        "md_cost_std":    local_std(results["md"]["cost"]),
    }


if __name__ == "__main__":
    configs = []
    config_id = 0
    for exec_min, exec_max in EXEC_TIME_RANGES:
        for df in DEADLINE_FACTORS:
            for scenario in HIB_SCENARIOS:
                for n in TASK_COUNTS:
                    config_id += 1
                    configs.append(
                        (config_id, exec_min, exec_max, n, df, scenario)
                    )

    n_workers = min(18, cpu_count())
    print(f"Running {len(configs)} configs x {RUNS_PER_CONFIG} runs "
          f"across {n_workers} cores...\n")
    print("Using original c3/c4/c3.xlarge/t3/c5 VM pool (10 VMs)\n")

    with Pool(processes=n_workers) as pool:
        raw = pool.map(run_one, configs)

    raw.sort(key=lambda r: (r["exec_max"], r["df"], r["scenario"], r["n"]))

    # ------------------------------------------------------------------
    # SUMMARY TABLE
    # ------------------------------------------------------------------
    print("=" * 80)
    print("MR-BurstHADS vs BurstHADS BOUNDARY SWEEP")
    print("(averaged across all task counts, deadline factors, scenarios)")
    print("=" * 80)
    print(f"{'ExecMax':>8}  {'MD_Avg':>8}  {'MD_Min':>8}  "
          f"{'MD_Max':>8}  {'WinRate':>8}  {'Signal':>8}  {'Verdict'}") 
    print("-" * 80)

    by_exec_md   = defaultdict(list)
    by_exec_hads = defaultdict(list)
    by_exec_sig  = defaultdict(list)

    for r in raw:
        bc = r["burst_cost"]; mc = r["md_cost"]; hc = r["hads_cost"]
        if bc > 0 and mc > 0:
            red = (bc - mc) / bc * 100
            std = (r["md_cost_std"] / bc) * 100
            sig = abs(red / std) if std > 0 else 999.0
            by_exec_md[r["exec_max"]].append(red)
            by_exec_sig[r["exec_max"]].append(sig)
        if bc > 0 and hc > 0:
            by_exec_hads[r["exec_max"]].append((hc - bc) / hc * 100)

    boundary = None
    for exec_max in sorted(by_exec_md.keys()):
        reds = by_exec_md[exec_max]
        sigs = [s for s in by_exec_sig[exec_max] if s < 900]
        avg_red  = sum(reds) / len(reds)
        avg_sig  = sum(sigs) / len(sigs) if sigs else 0
        win_rate = len([r for r in reds if r > 0]) / len(reds) * 100

        if avg_red > 2.0 and win_rate > 60:
            verdict = "GOOD - MD better"
        elif avg_red > 0 and win_rate > 50:
            verdict = "MARGINAL"
        else:
            verdict = "BOUNDARY - BurstHADS better"
            if boundary is None:
                boundary = exec_max

        print(f"{exec_max:>8}  {avg_red:>7.1f}%  "
              f"{min(reds):>7.1f}%  {max(reds):>7.1f}%  "
              f"{win_rate:>7.0f}%  {avg_sig:>7.2f}x  {verdict}")

    print("-" * 80)
    if boundary:
        prev_idx = [r[1] for r in EXEC_TIME_RANGES].index(boundary) - 1
        if prev_idx >= 0:
            prev_max = EXEC_TIME_RANGES[prev_idx][1]
            print(f"\nBOUNDARY: MR-BurstHADS is cost-effective for "
                  f"exec_time_max <= {prev_max}s")
        else:
            print(f"\nBOUNDARY: MR-BurstHADS is NOT cost-effective "
                  f"at any tested range")
    else:
        print(f"\nMR-BurstHADS remains cost-effective across all tested ranges")

    # ------------------------------------------------------------------
    # HADS vs BurstHADS context
    # ------------------------------------------------------------------
    print()
    print("=" * 80)
    print("HADS vs BurstHADS (BurstHADS cost reduction over HADS)")
    print("=" * 80)
    for exec_max in sorted(by_exec_hads.keys()):
        reds = by_exec_hads[exec_max]
        print(f"  exec_max={exec_max:>4}s: "
              f"BurstHADS avg {sum(reds)/len(reds):.1f}% cheaper than HADS")

    # ------------------------------------------------------------------
    # BREAKDOWN BY TASK COUNT (df=1.0, no hibernation)
    # ------------------------------------------------------------------
    print()
    print("=" * 80)
    print("MD vs BurstHADS BREAKDOWN BY TASK COUNT (df=1.0, no hibernation)")
    print("=" * 80)
    print(f"{'ExecMax':>8}", end="")
    for n in TASK_COUNTS:
        print(f"  {n:>5}t", end="")
    print()
    print("-" * 80)

    for exec_max in sorted(by_exec_md.keys()):
        print(f"{exec_max:>8}", end="")
        for n in TASK_COUNTS:
            m = next((r for r in raw
                      if r["exec_max"] == exec_max and r["n"] == n
                      and r["df"] == 1.0 and r["scenario"] == "none"), None)
            if m:
                bc = m["burst_cost"]; mc = m["md_cost"]
                red = (bc - mc) / bc * 100 if bc > 0 and mc > 0 else 0
                print(f"  {red:>5.1f}%", end="")
            else:
                print(f"  {'N/A':>5}", end="")
        print()

    # ------------------------------------------------------------------
    # PLOTS
    # ------------------------------------------------------------------
    OUTPUT_DIR = PROJECT_ROOT / "experiments" / "plots_boundary"
    OUTPUT_DIR.mkdir(exist_ok=True)

    COLOURS = ["#e41a1c","#ff7f00","#4daf4a","#377eb8","#984ea3","#a65628"]

    # Plot 1: Cost reduction vs exec_max per task count
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, n in enumerate(TASK_COUNTS):
        xs, ys = [], []
        for exec_max in sorted(by_exec_md.keys()):
            m = next((r for r in raw
                      if r["exec_max"] == exec_max and r["n"] == n
                      and r["df"] == 1.0 and r["scenario"] == "none"), None)
            if m:
                bc = m["burst_cost"]; mc = m["md_cost"]
                if bc > 0 and mc > 0:
                    xs.append(exec_max)
                    ys.append((bc - mc) / bc * 100)
        ax.plot(xs, ys, marker="o", label=f"{n} tasks",
                color=COLOURS[i], linewidth=1.8)

    ax.axhline(0, color="gray", linestyle="--", linewidth=1.2,
               label="Break-even")
    ax.set_xlabel("Maximum Task Execution Time (seconds)")
    ax.set_ylabel("Cost Reduction % (MR-BurstHADS vs BurstHADS)")
    ax.set_title(
        "MR-BurstHADS Operating Boundary\n"
        "Cost Reduction vs Task Execution Time (DF=1.0, No Hibernation)"
    )
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fig_boundary_by_task_count.png", dpi=300)
    plt.close()

    # Plot 2: Average reduction bar chart
    fig, ax = plt.subplots(figsize=(9, 5))
    xs   = sorted(by_exec_md.keys())
    ys   = [sum(by_exec_md[x])/len(by_exec_md[x]) for x in xs]
    cols = ["#4daf4a" if y > 0 else "#e41a1c" for y in ys]
    ax.bar([str(x) for x in xs], ys, color=cols,
           alpha=0.85, edgecolor="black", linewidth=0.5)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Maximum Task Execution Time (seconds)")
    ax.set_ylabel("Avg Cost Reduction % (MD vs BurstHADS)")
    ax.set_title(
        "MR-BurstHADS Operating Boundary\n"
        "Average Cost Reduction by Task Duration Range"
    )
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fig_boundary_avg_reduction.png", dpi=300)
    plt.close()

    # Plot 3: Three-way comparison at best exec_max (df=1.0, no hib)
    best_exec = sorted(by_exec_md.keys())[0]  # 15s — original range
    fig, ax   = plt.subplots(figsize=(9, 5))
    for sched_key, label, col in [
        ("hads_cost",  "HADS",         "#377eb8"),
        ("burst_cost", "BurstHADS",    "#a65628"),
        ("md_cost",    "MR-BurstHADS", "#000000"),
    ]:
        pts = sorted([
            (r["n"], r[sched_key])
            for r in raw
            if r["exec_max"] == best_exec
            and r["df"] == 1.0
            and r["scenario"] == "none"
        ])
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    marker="o", label=label, color=col, linewidth=1.8)
    ax.set_xlabel("Number of Tasks")
    ax.set_ylabel("Avg Total Cost (USD)")
    ax.set_title(f"Three-Way Cost Comparison at exec_time=[2,{best_exec}]s\n"
                 f"(DF=1.0, No Hibernation)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fig_three_way_comparison.png", dpi=300)
    plt.close()

    print(f"\nPlots saved to: {OUTPUT_DIR}")
    print("Boundary sweep complete.")