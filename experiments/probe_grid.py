"""
Where does the deadline start to bind? A coarse probe used to choose the
full sweep's cell grid, not a result in itself (5 seeds).

All five Table 9 scenarios x n x DF, below and around the DF=0.5 point
where the post-fix-7 checkpoints first showed a miss. Records, per run:
D, whether the min_feasible_deadline floor set it, misses, makespan / D,
cost, and any exception (a Dspot ValueError or a "no feasible placement"
RuntimeError would be an infeasible cell, which the sweep must report,
not drop).

The committed output, probe_grid.json / .txt, was produced at commit
b7e3662, before fix 8, under variants base and plan_ovh. On code after
fix 8 both variants are the same simulator.

Usage (from the project root):
    python experiments\\probe_grid.py --seeds 5 --variants base
"""

import sys, os, json, argparse, time
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

TABLE9 = {"sc1": (1.0, 0.0), "sc2": (5.0, 0.0), "sc3": (1.0, 5.0),
          "sc4": (5.0, 5.0), "sc5": (3.0, 2.5)}
NS  = [20, 50, 100, 200, 300]
DFS = [0.25, 0.35, 0.5, 0.75, 1.0]
SCHEDULERS = ["HADS", "BurstHADS", "R-BurstHADS"]


def run_unit(args):
    sc, n, df, seed, sched, variant = args
    import io, contextlib, random
    if str(_PROJ) not in sys.path:
        sys.path.insert(0, str(_PROJ))
    from experiments import variants
    kh, kr = TABLE9[sc]
    variants.apply(variant, kh=kh, kr=kr)
    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst, min_feasible_deadline,
                      DEADLINE_SLACK, ideal_makespan)
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS
    CLS = {"HADS": HADS, "BurstHADS": BurstHADS, "R-BurstHADS": RBurstHADS}

    D, _ = compute_deadlines(n, df, 1)
    floored = df * DEADLINE_SLACK * ideal_makespan(n) < min_feasible_deadline()
    base = dict(sc=sc, n=n, df=df, seed=seed, sched=sched, variant=variant,
                D=D, floored=floored)
    try:
        random.seed(seed)
        tasks = generate_tasks(n)
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(CLS[sched], tasks, D,
                               vm_builder=build_vms_dburst, kh=kh, kr=kr,
                               spot_risk_seed=seed, spot_risk_mode="declared")
        mk = m.makespan()
        all_t = [t for job in m.jobs for st in job.stages for t in st.tasks]
        base.update(ok=True, error=None, mk=mk, mk_frac=mk / D,
                    misses=m.deadline_misses(), cost=m.total_cost(),
                    pct=100.0 * sum(t.completed for t in all_t) / len(all_t))
    except Exception as e:
        base.update(ok=False, error=repr(e))
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--variants", default="base")
    a = ap.parse_args()
    vnames = a.variants.split(",")

    from multiprocessing import Pool
    rows, t0 = [], time.time()
    for v in vnames:
        units = [(sc, n, df, s, sched, v) for sc in TABLE9 for n in NS
                 for df in DFS for s in range(a.seeds) for sched in SCHEDULERS]
        print(f"variant {v}: {len(units)} runs", flush=True)
        with Pool(processes=a.workers) as pool:
            rows.extend(pool.imap_unordered(run_unit, units, chunksize=2))
    print(f"done in {time.time() - t0:.0f}s\n")

    for v in vnames:
        print(f"=== variant {v}: mean misses HADS / Burst / R  "
              f"(E = runs that raised)")
        for sc in TABLE9:
            print(f"  {sc}")
            print("    n\\DF  " + "".join(f"{df:>20}" for df in DFS))
            for n in NS:
                cells = []
                for df in DFS:
                    parts = []
                    for sched in SCHEDULERS:
                        rs = [r for r in rows if r["variant"] == v
                              and r["sc"] == sc and r["n"] == n
                              and r["df"] == df and r["sched"] == sched]
                        errs = sum(not r["ok"] for r in rs)
                        good = [r["misses"] for r in rs if r["ok"]]
                        mean = sum(good) / len(good) if good else float("nan")
                        parts.append(f"{mean:.1f}" + (f"E{errs}" if errs else ""))
                    fl = any(r["floored"] for r in rows if r["n"] == n
                             and r["df"] == df)
                    cells.append(("*" if fl else " ") + "/".join(parts))
                print(f"    {n:<5} " + "".join(f"{c:>20}" for c in cells))
        print("  (* = D set by min_feasible_deadline floor)\n")

    errs = [r for r in rows if not r["ok"]]
    if errs:
        from collections import Counter
        print("exceptions:", Counter(r["error"][:90] for r in errs).most_common(5))

    json.dump(rows, open(_PROJ / "experiments" / "probe_grid.json", "w"), indent=1)
    print("wrote experiments/probe_grid.json")


if __name__ == "__main__":
    main()
