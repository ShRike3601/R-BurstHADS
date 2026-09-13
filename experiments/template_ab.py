"""
Diagnostic A/B: does R-BurstHADS's provisioning suffer because the
risk-aware tie-break now picks a SMALLER instance?

Fix 3 removed the instance-size double count, which left c5.large and
c5.xlarge tied at 130.7 units per dollar-hour. The survival term breaks
that tie toward c5.large (126.9 vs 125.6) on a 1% margin that comes
entirely from an illustrative lambda differential. Same price per unit
of throughput either way -- but c5.large has half the cores, so
R-BurstHADS must provision twice as many machines for the same capacity,
each paying its own STARTUP_LATENCY before it does any work, and
MAX_VMS_PER_EVENT is a count cap, so it now admits 10 x 4 = 40 units of
emergency capacity per event where it used to admit 10 x 16 = 160.

This runs a 2x2: forced instance type x count cap, on the two cells
where R-BurstHADS lost its makespan dominance over Burst-HADS
(DF=0.5, sc4 and sc5) plus a healthy control. It changes nothing
permanently; the overrides are applied inside the worker process.

    python experiments\\template_ab.py --workers 18 --seeds 5
"""

import sys, os, io, json, argparse, contextlib
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

# (n, kh, kr, df, label)
CELLS = [
    (300, 5.0, 5.0, 0.5, "sc4 DF=0.5  (dominance broke here)"),
    (300, 3.0, 2.5, 0.5, "sc5 DF=0.5  (dominance broke here)"),
    (300, 5.0, 0.0, 1.0, "sc2 DF=1.0  (control, still healthy)"),
]

# (forced instance type or None to leave the scheduler's own choice,
#  MAX_VMS_PER_EVENT override or None to leave it)
VARIANTS = [
    ("c5.large  cap=10", "c5.large", 10),
    ("c5.xlarge cap=10", "c5.xlarge", 10),
    ("c5.large  cap=40", "c5.large", 40),
    ("c5.xlarge cap=40", "c5.xlarge", 40),
]


def run_unit(args):
    n, kh, kr, df, label, vname, vtype, vcap, seed, sched = args

    import sys
    from pathlib import Path
    proj = Path(__file__).resolve().parent.parent
    if str(proj) not in sys.path:
        sys.path.insert(0, str(proj))

    import random
    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst)
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    import scheduler.r_burst_hads as rbh

    CLS = {"HADS": HADS, "BurstHADS": BurstHADS, "R-BurstHADS": rbh.RBurstHADS}

    try:
        # Apply the overrides in this worker only.
        if vcap is not None:
            rbh.MAX_VMS_PER_EVENT = vcap
        if vtype is not None and sched == "R-BurstHADS":
            def forced(self, _t=vtype):
                cands = [v for v in self.spot_vms
                         if v.cost_rate > 0 and v.vm_type == _t]
                if not cands:
                    return rbh.RBurstHADS._orig_resolve(self)
                b = cands[0]
                return dict(vm_type=b.vm_type, speed=b.speed,
                            cost_rate=b.cost_rate, mem_gb=b.memory_gb,
                            hib_rate=b.hibernation_rate, vcpu=b.vcpu_count)
            if not hasattr(rbh.RBurstHADS, "_orig_resolve"):
                rbh.RBurstHADS._orig_resolve = rbh.RBurstHADS._resolve_spot_template
            rbh.RBurstHADS._resolve_spot_template = forced

        D, _ = compute_deadlines(n, df, 1)
        random.seed(seed)
        tasks = generate_tasks(n)
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            m = run_simulation(CLS[sched], tasks, D,
                               vm_builder=build_vms_dburst,
                               kh=kh, kr=kr, spot_risk_seed=seed,
                               spot_risk_mode="declared")
        return dict(label=label, variant=vname, sched=sched, seed=seed,
                    ok=True, mk=m.makespan(), cost=m.total_cost(),
                    misses=m.deadline_misses(), error=None)
    except Exception as e:
        return dict(label=label, variant=vname, sched=sched, seed=seed,
                    ok=False, mk=None, cost=None, misses=None,
                    error=repr(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    units = []
    for (n, kh, kr, df, label) in CELLS:
        for (vname, vtype, vcap) in VARIANTS:
            for s in range(a.seeds):
                units.append((n, kh, kr, df, label, vname, vtype, vcap,
                              s, "R-BurstHADS"))
        # Burst-HADS reference: unaffected by the overrides, run once
        for s in range(a.seeds):
            units.append((n, kh, kr, df, label, "reference", None, None,
                          s, "BurstHADS"))

    print(f"template A/B: {len(units)} runs on {a.workers} workers",
          flush=True)
    from multiprocessing import Pool
    with Pool(processes=a.workers) as pool:
        rows = [r for r in pool.imap_unordered(run_unit, units, chunksize=1)]

    bad = [r for r in rows if not r["ok"]]
    if bad:
        print(f"!! {len(bad)} failed; first: {bad[0]['error']}")

    agg = {}
    for r in rows:
        if r["ok"]:
            agg.setdefault(r["label"], {}).setdefault(r["variant"], []).append(r)

    for (n, kh, kr, df, label) in CELLS:
        if label not in agg:
            continue
        print("=" * 74)
        print(label)
        ref = agg[label].get("reference", [])
        rmk = sum(x["mk"] for x in ref) / len(ref) if ref else None
        rco = sum(x["cost"] for x in ref) / len(ref) if ref else None
        if ref:
            print(f"  {'Burst-HADS ref':18s} {rmk:9.1f} {rco:9.4f}")
        print(f"  {'R-BurstHADS':18s} {'makespan':>9s} {'cost':>9s} "
              f"{'vs ref mk':>10s} {'vs ref cost':>12s}")
        for (vname, _t, _c) in VARIANTS:
            rs = agg[label].get(vname, [])
            if not rs:
                continue
            mk = sum(x["mk"] for x in rs) / len(rs)
            co = sum(x["cost"] for x in rs) / len(rs)
            dm = 100 * (mk - rmk) / rmk if rmk else float("nan")
            dc = 100 * (co - rco) / rco if rco else float("nan")
            print(f"  {vname:18s} {mk:9.1f} {co:9.4f} {dm:+9.1f}% "
                  f"{dc:+11.1f}%")

    json.dump(rows, open(_PROJ / "experiments" / "template_ab.json", "w"),
              indent=1)
    print(f"\nwrote {_PROJ / 'experiments' / 'template_ab.json'}")


if __name__ == "__main__":
    main()
