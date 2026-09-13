"""
What do R-BurstHADS's provisioned machines actually do, per scenario?

Measurement for the sc1 open item, taken BEFORE modelling any change to
Theorem 1. For every VM R-BurstHADS launches mid-run it records which
mechanism created it, its billed seconds, the core-seconds it spent
executing tasks, and its cost:

  preempt    Theorem 1, _preemptive_provision (t=0, ready at T_startup)
  saturate   Theorem 2, _respond_to_saturation
  one_more   tier 3, _provision_one_more

Arms, applied through a subclass in the worker (nothing on disk changes):
  current      R-BurstHADS as on disk
  no_preempt   _preemptive_provision is a no-op; the other two
               mechanisms are unchanged

`current` and `no_preempt` are the two ends of Theorem 1's decision: one
provisions wherever the test passes, the other never does. Their gap per
cell is what the preemptive step is worth there, in makespan and cost,
and is the reference any repricing of Theorem 1 has to be judged against.
HADS and Burst-HADS run alongside for the same cells so every comparison
shares seeds.

Usage (from the project root):
    python experiments\\diag_rb_provisioning.py --seeds 10
"""

import sys, os, json, argparse, time
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

TABLE9 = {"sc1": (1.0, 0.0), "sc2": (5.0, 0.0), "sc3": (1.0, 5.0),
          "sc4": (5.0, 5.0), "sc5": (3.0, 2.5)}
NS  = [100, 300]
DFS = [0.5, 1.0, 2.0]
# (scheduler, arm)
RUNS = [("HADS", "-"), ("BurstHADS", "-"),
        ("R-BurstHADS", "current"), ("R-BurstHADS", "no_preempt")]


def run_unit(args):
    sc, n, df, seed, sched, arm = args
    import io, contextlib, random, traceback
    if str(_PROJ) not in sys.path:
        sys.path.insert(0, str(_PROJ))
    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst)
    from models.vm import VM
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS
    import simulation.events as ev

    holder, origin = {}, {}

    class ProbeR(RBurstHADS):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["s"] = self

        def _tag(self, before, tag):
            for v in self.provisioned_vms:
                if v.id not in before:
                    origin.setdefault(v.id, tag)

        def _preemptive_provision(self):
            if arm == "no_preempt":
                return
            before = {v.id for v in self.provisioned_vms}
            super()._preemptive_provision()
            self._tag(before, "preempt")

        def _respond_to_saturation(self, current_time):
            before = {v.id for v in self.provisioned_vms}
            super()._respond_to_saturation(current_time)
            self._tag(before, "saturate")

        def _provision_one_more(self, task, current_time):
            before = {v.id for v in self.provisioned_vms}
            out = super()._provision_one_more(task, current_time)
            self._tag(before, "one_more")
            return out

    cls = {"HADS": HADS, "BurstHADS": BurstHADS,
           "R-BurstHADS": ProbeR}[sched]

    busy = {}   # vm id -> core-seconds spent executing tasks
    orig_complete = ev.TaskCompleteEvent.execute
    orig_hib      = ev.HibernationEvent.execute

    def complete_probe(self):
        t = self.task
        if (t.current_event is self and not t.completed
                and t.exec_start_on_current_vm is not None):
            busy[self.vm.id] = (busy.get(self.vm.id, 0.0)
                                + self.time - t.exec_start_on_current_vm)
        return orig_complete(self)

    def hib_probe(self):
        if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            for t in self.vm.running:
                if t.exec_start_on_current_vm is not None:
                    busy[self.vm.id] = (busy.get(self.vm.id, 0.0)
                                        + self.time - t.exec_start_on_current_vm)
        return orig_hib(self)

    ev.TaskCompleteEvent.execute = complete_probe
    ev.HibernationEvent.execute  = hib_probe
    kh, kr = TABLE9[sc]
    try:
        D, _ = compute_deadlines(n, df, 1)
        random.seed(seed)
        tasks = generate_tasks(n)
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(cls, tasks, D, vm_builder=build_vms_dburst,
                               kh=kh, kr=kr, spot_risk_seed=seed,
                               spot_risk_mode="declared")
    except Exception:
        return dict(sc=sc, n=n, df=df, seed=seed, sched=sched, arm=arm,
                    ok=False, error=traceback.format_exc())
    finally:
        ev.TaskCompleteEvent.execute = orig_complete
        ev.HibernationEvent.execute  = orig_hib

    mk = m.makespan()
    closed  = [e for vm in m.vms for _s, e in vm._billing_intervals
               if e is not None]
    sim_end = max(closed + [mk])
    row = dict(sc=sc, n=n, df=df, seed=seed, sched=sched, arm=arm, ok=True,
               error=None, D=D, mk=mk, mk_frac=mk / D,
               misses=m.deadline_misses(), cost=m.total_cost(), prov={})
    if sched == "R-BurstHADS":
        for v in holder["s"].provisioned_vms:
            tag = origin.get(v.id, "untagged")
            billed = v.billed_seconds(sim_end)
            agg = row["prov"].setdefault(tag, dict(count=0, used=0,
                                                   billed_s=0.0, busy_s=0.0,
                                                   cost=0.0, vcpu_billed_s=0.0))
            agg["count"]    += 1
            agg["used"]     += int(busy.get(v.id, 0.0) > 0)
            agg["billed_s"] += billed
            agg["vcpu_billed_s"] += billed * v.vcpu_count
            agg["busy_s"]   += busy.get(v.id, 0.0)
            agg["cost"]     += v.cost_rate * billed
    return row


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    units = [(sc, n, df, s, sched, arm) for sc in TABLE9 for n in NS
             for df in DFS for s in range(a.seeds) for sched, arm in RUNS]
    print(f"{len(units)} runs on {a.workers} workers", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(processes=a.workers) as pool:
        rows = list(pool.imap_unordered(run_unit, units, chunksize=2))
    print(f"done in {time.time() - t0:.0f}s\n")
    bad = [r for r in rows if not r["ok"]]
    if bad:
        print(f"!! {len(bad)} FAILED. First:\n{bad[0]['error']}")
    ok = [r for r in rows if r["ok"]]

    def pick(sc, n, df, sched, arm):
        return [r for r in ok if (r["sc"], r["n"], r["df"], r["sched"],
                                  r["arm"]) == (sc, n, df, sched, arm)]

    pct = lambda x, y: 100.0 * (x - y) / y
    print("Per cell, means over seeds. Costs in $; R = R-BurstHADS.")
    print("preempt: VMs/run, share of R's cost, busy core-s / billed core-s")
    print(f"{'cell':12s} {'DF':>4s} | {'R mk vs H':>9s} {'R $ vs H':>9s} | "
          f"{'preempt n':>9s} {'$share':>7s} {'util':>6s} | "
          f"{'noP mk vs R':>11s} {'noP $ vs R':>10s} | {'noP $ vs H':>10s} "
          f"{'misses R/noP':>12s}")
    for sc in TABLE9:
        for n in NS:
            for df in DFS:
                h  = pick(sc, n, df, "HADS", "-")
                rc = pick(sc, n, df, "R-BurstHADS", "current")
                rn = pick(sc, n, df, "R-BurstHADS", "no_preempt")
                if not (h and rc and rn):
                    continue
                hmk, hc = _mean(r["mk"] for r in h), _mean(r["cost"] for r in h)
                cmk, cc = _mean(r["mk"] for r in rc), _mean(r["cost"] for r in rc)
                nmk, nc = _mean(r["mk"] for r in rn), _mean(r["cost"] for r in rn)
                pre = [r["prov"].get("preempt") for r in rc]
                pre_n = _mean((p["count"] if p else 0) for p in pre)
                share = _mean(((p["cost"] if p else 0.0) / r["cost"])
                              for p, r in zip(pre, rc))
                billed = sum(p["vcpu_billed_s"] for p in pre if p)
                util = (sum(p["busy_s"] for p in pre if p) / billed
                        if billed else float("nan"))
                print(f"{sc} n={n:<4d}  {df:4.1f} | {pct(cmk, hmk):+9.1f} "
                      f"{pct(cc, hc):+9.1f} | {pre_n:9.1f} {share*100:6.1f}% "
                      f"{util:6.2f} | {pct(nmk, cmk):+11.1f} "
                      f"{pct(nc, cc):+10.1f} | {pct(nc, hc):+10.1f} "
                      f"{_mean(r['misses'] for r in rc):5.1f}/"
                      f"{_mean(r['misses'] for r in rn):.1f}")
        print()

    path = _PROJ / "experiments" / "diag_rb_provisioning.json"
    json.dump({"seeds": a.seeds, "rows": rows}, open(path, "w"), indent=1)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
