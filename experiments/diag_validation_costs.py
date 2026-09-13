"""
Where does the baselines' extra cost under hibernation come from, in the
paper-reproduction setting?

baseline_validation showed both HADS and Burst-HADS costing far more under
hibernation than without it (J60 Burst-HADS: +141% in sc1 in our simulator
against +6% in the paper's own Table 7 / Table 10 numbers), in every code
state from fixes 1-7 on. It also showed, with instance limits on, ED200
makespans in sc2 of 5,800-7,600 s against D = 2,700 s. This decomposes
each run instead of guessing:

  cost, billed seconds and number of billed VMs, by market
  (spot / burstable / on-demand), per (job, scenario, scheduler)
  makespan and deadline misses
  instances launched by type and forced overrides (code with limits only)

Uses baseline_validation's Table 6 workload generator and
paper_reproduction's catalogue (copies per spot type via --copies).

Usage (from the project root of any code state):
    python experiments\\diag_validation_costs.py --tag NAME --seeds 10
"""

import sys, os, io, json, time, argparse, contextlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PROJ = HERE.parent
for p in (str(_PROJ), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

JOBS = ["J60", "J100", "ED200"]
SCENARIOS = ["none", "sc1", "sc2", "sc5"]
KEYS = ("hads", "burst")
MARKETS = ("spot", "burstable", "ondemand")


def run_unit(args):
    job, sc, seed, key, copies = args
    for p in (str(_PROJ), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import baseline_validation as bv
    from experiments import paper_reproduction as pr
    from main import run_simulation
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    try:
        from models.limits import NoFeasibleSchedule
    except ImportError:
        class NoFeasibleSchedule(Exception):
            pass

    base = {"hads": HADS, "burst": BurstHADS}[key]
    holder = {}

    class Capture(base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["s"] = self

    tasks = bv.gen_table6(job, seed)
    kwargs = dict(vm_builder=lambda: pr.build_vms_paper(copies), spot_risk_seed=seed)
    if sc != "none":
        kwargs.update(kh=pr.SCENARIOS[sc]["kh"], kr=pr.SCENARIOS[sc]["kr"])
    row = dict(job=job, sc=sc, seed=seed, key=key, ok=False, infeasible=False, error=None)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(Capture, tasks, pr.DEADLINE, **kwargs)
    except NoFeasibleSchedule as e:
        row.update(infeasible=True, error=str(e))
        return row
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
        return row

    mk = m.makespan()
    closed = [e for vm in m.vms for _s, e in vm._billing_intervals if e is not None]
    sim_end = max(closed + [mk])
    by = {mkt: dict(cost=0.0, billed_s=0.0, vms=0) for mkt in MARKETS}
    for vm in m.vms:
        if not vm._billing_intervals:
            continue
        b = by[vm.market]
        s = vm.billed_seconds(sim_end)
        b["cost"] += vm.cost_rate * s
        b["billed_s"] += s
        b["vms"] += 1
    launches = getattr(holder.get("s"), "_launches", None)
    row.update(ok=True, mk=mk, misses=m.deadline_misses(), cost=m.total_cost(),
               by_market=by, sim_end=sim_end,
               launched=launches.launched() if launches else None,
               overrides=launches.overrides if launches else None)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--copies", type=int, default=3)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    units = [(j, sc, s, k, a.copies) for j in JOBS for sc in SCENARIOS
             for s in range(a.seeds) for k in KEYS]
    print(f"diag_validation_costs '{a.tag}': {len(units)} runs", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(a.workers) as pool:
        rows = list(pool.imap_unordered(run_unit, units, chunksize=2))
    bad = [r for r in rows if not r["ok"] and not r["infeasible"]]
    print(f"done in {time.time() - t0:.0f}s; infeasible {sum(r['infeasible'] for r in rows)}, "
          f"errors {len(bad)}" + (f"; first: {bad[0]['error']}" if bad else ""))

    print("\nmeans over feasible seeds. cost $ total and by market; billed VM count by market; "
          "makespan; misses; on-demand launches")
    print(f"{'cell':11s} {'sched':5s} | {'cost':>6s} {'spot$':>6s} {'burst$':>6s} {'od$':>6s} | "
          f"{'#spot':>5s} {'#burst':>6s} {'#od':>5s} | {'od billed h':>10s} | {'mk':>6s} {'miss':>5s} | "
          f"{'od launched (by type)':>22s} {'ovr':>4s}")
    out = {}
    for j in JOBS:
        for sc in SCENARIOS:
            for k in KEYS:
                rs = [r for r in rows if (r["job"], r["sc"], r["key"]) == (j, sc, k) and r["ok"]]
                if not rs:
                    print(f"{j+' '+sc:11s} {k:5s} | no feasible runs")
                    continue
                n = len(rs)
                mean = lambda fn: sum(fn(r) for r in rs) / n
                od_types = {}
                for r in rs:
                    for t, v in (r["launched"] or {}).items():
                        if t.startswith("ondemand:"):
                            od_types[t.split(":", 1)[1]] = od_types.get(t.split(":", 1)[1], 0) + v / n
                cell = dict(n=n, cost=mean(lambda r: r["cost"]),
                            **{f"{mkt}_cost": mean(lambda r, m=mkt: r["by_market"][m]["cost"]) for mkt in MARKETS},
                            **{f"{mkt}_vms": mean(lambda r, m=mkt: r["by_market"][m]["vms"]) for mkt in MARKETS},
                            od_billed_h=mean(lambda r: r["by_market"]["ondemand"]["billed_s"] / 3600),
                            mk=mean(lambda r: r["mk"]), misses=mean(lambda r: r["misses"]),
                            od_launched=od_types,
                            overrides=(mean(lambda r: r["overrides"] or 0)
                                       if rs[0]["overrides"] is not None else None))
                out[f"{j} {sc} {k}"] = cell
                odl = " ".join(f"{t}:{v:.1f}" for t, v in od_types.items()) or "-"
                print(f"{j+' '+sc:11s} {k:5s} | {cell['cost']:6.3f} {cell['spot_cost']:6.3f} "
                      f"{cell['burstable_cost']:6.3f} {cell['ondemand_cost']:6.3f} | "
                      f"{cell['spot_vms']:5.1f} {cell['burstable_vms']:6.1f} {cell['ondemand_vms']:5.1f} | "
                      f"{cell['od_billed_h']:10.2f} | {cell['mk']:6.0f} {cell['misses']:5.1f} | "
                      f"{odl:>22s} {('%.1f' % cell['overrides']) if cell['overrides'] is not None else '-':>4s}")
        print()
    path = HERE / f"diag_validation_costs_{a.tag}.json"
    json.dump(dict(tag=a.tag, seeds=a.seeds, copies=a.copies, cells=out, rows=rows),
              open(path, "w"), indent=1)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
