"""
Fix checkpoint: a small parallel sweep used to see the DIRECTION of one
code change before committing to the full 30-seed run.

Reports, per (n, kh, kr) cell and per scheduler: mean makespan, mean
deadline misses, and mean cost under all three billing policies

  A  as-shipped   closed intervals billed to their real end, open ones
                  capped at the makespan (the current, inconsistent rule)
  B  to-makespan  every interval truncated at the makespan
  C  to-shutdown  every interval billed to its real end, open ones to
                  the true end of the simulation

Nothing here changes the simulator. Run it, then hand the JSON back so
successive checkpoints can be diffed against each other.

Usage (Windows PowerShell, from the project root):

    python experiments\\checkpoint.py --tag fix1_migcheck --workers 18

    python experiments\\checkpoint.py --tag fix1_migcheck --workers 18 --seeds 20

    python experiments\\checkpoint.py --tag repl_t9 --variant repl_t9

--variant names a counterfactual patch from experiments/variants.py,
applied in each worker before it simulates. The default, "base", is the
simulator exactly as it is on disk.
"""

import sys, os, json, argparse, random, io, contextlib, time
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

from experiments import variants as _variants

# (n, kh, kr, label) -- Table 9 scenarios at paper scale, plus one
# smaller cell so a regression that only shows up at low n is visible.
CELLS = [
    (300, 5.0, 0.0,  "sc2  n=300  kh=5 kr=0"),
    (300, 1.0, 0.0,  "sc1  n=300  kh=1 kr=0"),
    (300, 5.0, 5.0,  "sc4  n=300  kh=5 kr=5"),
    (300, 3.0, 2.5,  "sc5  n=300  kh=3 kr=2.5"),
    (100, 5.0, 0.0,  "sc2  n=100  kh=5 kr=0"),
]

SCHEDULERS = ["HADS", "BurstHADS", "R-BurstHADS"]


def _policies(vms, mk, sim_end):
    a = b = c = 0.0
    for vm in vms:
        r = vm.cost_rate
        for s, e in vm._billing_intervals:
            a += r * ((e if e is not None else mk) - s)
            b += r * max(0.0, min(e if e is not None else mk, mk) - s)
            c += r * ((e if e is not None else sim_end) - s)
    return a, b, c


def run_unit(args):
    """One (cell, seed, scheduler) -> one simulation. Top level so the
    Windows spawn-based Pool can pickle it."""
    n, kh, kr, label, seed, sched, df, variant = args

    import sys
    from pathlib import Path
    proj = Path(__file__).resolve().parent.parent
    if str(proj) not in sys.path:
        sys.path.insert(0, str(proj))

    from experiments import variants
    variants.apply(variant, kh=kh, kr=kr)

    import random
    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst)
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS

    CLS = {"HADS": HADS, "BurstHADS": BurstHADS, "R-BurstHADS": RBurstHADS}

    try:
        D, _ = compute_deadlines(n, df, 1)
        random.seed(seed)
        tasks = generate_tasks(n)

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            m = run_simulation(CLS[sched], tasks, D,
                               vm_builder=build_vms_dburst,
                               kh=kh, kr=kr,
                               spot_risk_seed=seed,
                               spot_risk_mode="declared")

        mk = m.makespan()
        ends = [e for vm in m.vms for s, e in vm._billing_intervals
                if e is not None]
        sim_end = max(ends + [mk])
        a, b, c = _policies(m.vms, mk, sim_end)

        all_t = [t for job in m.jobs for st in job.stages for t in st.tasks]
        return dict(label=label, seed=seed, sched=sched, ok=True,
                    mk=mk, A=a, B=b, C=c,
                    misses=m.deadline_misses(),
                    mk_frac=(mk / D if D else None),
                    pct=100.0 * sum(1 for t in all_t if t.completed) / len(all_t),
                    D=D, error=None)
    except Exception as e:
        return dict(label=label, seed=seed, sched=sched, ok=False,
                    mk=None, A=None, B=None, C=None, misses=None,
                    mk_frac=None, pct=None, D=None, error=repr(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True,
                    help="name for this checkpoint, e.g. fix1_migcheck")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--df", type=float, default=1.0,
                    help="deadline factor; D = df * DEADLINE_SLACK * "
                         "ideal_makespan(n). Use 0.5 / 1.0 / 2.0 to test "
                         "whether the result depends on how much slack the "
                         "deadline grants, since HADS and Burst-HADS only "
                         "escalate when D is threatened and therefore "
                         "finish just under it.")
    ap.add_argument("--variant", default="base",
                    choices=sorted(_variants.VARIANTS),
                    help="counterfactual patch from experiments/variants.py")
    a = ap.parse_args()

    units = [(n, kh, kr, label, s, sched, a.df, a.variant)
             for (n, kh, kr, label) in CELLS
             for s in range(a.seeds)
             for sched in SCHEDULERS]

    print(f"checkpoint '{a.tag}' (DF={a.df}, variant={a.variant}): "
          f"{len(units)} runs "
          f"({len(CELLS)} cells x {a.seeds} seeds x {len(SCHEDULERS)} "
          f"schedulers) on {a.workers} workers", flush=True)

    t0 = time.time()
    from multiprocessing import Pool
    with Pool(processes=a.workers) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(run_unit, units, chunksize=1)):
            rows.append(r)
            if (i + 1) % 25 == 0 or i + 1 == len(units):
                print(f"  {i+1}/{len(units)} done", flush=True)
    print(f"  wall time {time.time() - t0:.0f}s", flush=True)

    bad = [r for r in rows if not r["ok"]]
    if bad:
        print(f"\n!! {len(bad)} runs FAILED. First error:")
        print("   ", bad[0]["label"], bad[0]["sched"],
              "seed", bad[0]["seed"], "->", bad[0]["error"])

    agg = {}
    for r in rows:
        if not r["ok"]:
            continue
        agg.setdefault(r["label"], {}).setdefault(r["sched"], []).append(r)

    print()
    out = {}
    for (n, kh, kr, label) in CELLS:
        if label not in agg:
            continue
        print("=" * 78)
        print(label)
        print(f"  {'scheduler':13s} {'makespan':>9s} {'mk/D':>7s} "
              f"{'cost A':>9s} {'cost B':>9s} {'cost C':>9s} "
              f"{'miss':>6s} {'done%':>7s}")
        base = {}
        cell = {}
        for sched in SCHEDULERS:
            rs = agg[label].get(sched, [])
            if not rs:
                continue
            k = len(rs)
            mean = lambda key: sum(r[key] for r in rs) / k
            row = dict(mk=mean("mk"), A=mean("A"), B=mean("B"), C=mean("C"),
                       mk_frac=mean("mk_frac"),
                       misses=mean("misses"), pct=mean("pct"), n=k)
            cell[sched] = row
            if sched == "HADS":
                base = row
            print(f"  {sched:13s} {row['mk']:9.1f} "
                  f"{row['mk_frac']*100:6.1f}% {row['A']:9.4f} "
                  f"{row['B']:9.4f} {row['C']:9.4f} {row['misses']:6.2f} "
                  f"{row['pct']:7.2f}")
        if base:
            print("  vs HADS:")
            for sched in ("BurstHADS", "R-BurstHADS"):
                if sched not in cell:
                    continue
                r = cell[sched]
                dmk = 100.0 * (r["mk"] - base["mk"]) / base["mk"]
                cost = "  ".join(
                    f"{p}:{100.0*(r[p]-base[p])/base[p]:+7.1f}%"
                    for p in ("A", "B", "C"))
                print(f"    {sched:13s} makespan {dmk:+7.1f}%   cost {cost}")
        out[label] = cell

    path = _PROJ / "experiments" / f"checkpoint_{a.tag}.json"
    json.dump({"tag": a.tag, "seeds": a.seeds, "df": a.df,
               "variant": a.variant,
               "cells": out, "raw": rows}, open(path, "w"), indent=1)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
