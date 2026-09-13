"""
Diagnostic: recompute total cost under three billing policies to size
the post-makespan idle tail.

  A  as-shipped   metrics.total_cost(): an interval that was CLOSED is
                  billed to its real end (for an AC-terminated VM that
                  is makespan + 900s); an interval still OPEN at the
                  end is capped at the makespan.
  B  to-makespan  every interval truncated at the makespan.
  C  to-shutdown  every interval billed to its real end; still-open
                  ones to the true end of the simulation.

Nothing here changes the simulator; it only re-reads the billing
intervals each VM recorded.
"""
import sys, os, json, argparse, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import (run_simulation, generate_tasks, compute_deadlines,
                  build_vms_dburst)
from scheduler.hads import HADS
from scheduler.burst_hads import BurstHADS
from scheduler.r_burst_hads import RBurstHADS

CLASS_MAP = {"HADS": HADS, "BurstHADS": BurstHADS, "R-BurstHADS": RBurstHADS}


def policies(vms, mk, sim_end):
    a = b = c = 0.0
    for vm in vms:
        r = vm.cost_rate
        for s, e in vm._billing_intervals:
            a += r * ((e if e is not None else mk) - s)
            b += r * max(0.0, min(e if e is not None else mk, mk) - s)
            c += r * ((e if e is not None else sim_end) - s)
    return a, b, c


def one(n, seed, kh, kr, df):
    D, _ = compute_deadlines(n, df, 1)
    out = {}
    for name, cls in CLASS_MAP.items():
        random.seed(seed)
        tasks = generate_tasks(n)
        m = run_simulation(cls, tasks, D, vm_builder=build_vms_dburst,
                           kh=kh, kr=kr, spot_risk_seed=seed,
                           spot_risk_mode="declared")
        mk = m.makespan()
        ends = [e for vm in m.vms for s, e in vm._billing_intervals
                if e is not None]
        sim_end = max(ends + [mk])
        pa, pb, pc = policies(m.vms, mk, sim_end)
        out[name] = dict(makespan=round(mk, 1), reported=round(m.total_cost(), 6),
                         A=round(pa, 6), B=round(pb, 6), C=round(pc, 6),
                         tail=round(sim_end - mk, 1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--kh", type=float, default=5.0)
    ap.add_argument("--kr", type=float, default=0.0)
    ap.add_argument("--df", type=float, default=1.0)
    a = ap.parse_args()
    o = one(a.n, a.seed, a.kh, a.kr, a.df)
    for k, v in o.items():
        print(f"{k:12s} mk={v['makespan']:8.1f} tail={v['tail']:6.1f} "
              f"reported={v['reported']:.4f}  A={v['A']:.4f} "
              f"B={v['B']:.4f} C={v['C']:.4f}", flush=True)
    base = o["HADS"]
    for s in ("BurstHADS", "R-BurstHADS"):
        row = " ".join(f"{p}:{100.0*(o[s][p]-base[p])/base[p]:+6.1f}%"
                       for p in ("A", "B", "C"))
        print(f"  {s:12s} cost vs HADS -> {row}")
    json.dump(o, open("experiments/billing_audit.json", "w"), indent=1)
