"""
How do Theorem 1's preemptive replacements get their work?

diag_rb_provisioning showed the replacements are 54-100% utilised in
every Table 9 cell, sc1 included, and that switching Theorem 1 off makes
R-BurstHADS slower and more expensive almost everywhere. Theorem 1 is
framed as insurance against hibernation. This measures whether that is
what the replacements are used for, by attributing every task that lands
on a preemptive replacement to the path that put it there:

  rescue     select_vm after a hibernation (tier 0, _select_replacement_vm)
  steal      Algorithm 5 work stealing (policies.work_stealing._steal_task),
             whatever triggered it: the replacement becoming ready, a task
             completing, or a VM resuming
  rebalance  Theorem 2's _respond_to_saturation redistribution

It reports, per cell: task arrivals per run by path, the share of the
replacements' busy core-seconds each path accounts for, and the share
spent on tasks that started BEFORE the first hibernation anywhere in the
run (capacity use that no hibernation could have motivated).

Usage (from the project root):
    python experiments\\diag_rb_replacement_use.py --seeds 10
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
PATHS = ["rescue", "steal", "rebalance", "untagged"]


def run_unit(args):
    sc, n, df, seed = args
    import io, contextlib, random, traceback
    if str(_PROJ) not in sys.path:
        sys.path.insert(0, str(_PROJ))
    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst)
    from models.vm import VM
    from scheduler.r_burst_hads import RBurstHADS
    import simulation.events as ev
    import policies.work_stealing as ws

    preempt  = set()                        # ids of Theorem 1 replacements
    tag      = {}                           # task id -> path of last arrival
    arrivals = {p: 0 for p in PATHS}
    busy     = {p: 0.0 for p in PATHS}
    busy_pre_hib = [0.0]
    first_hib = [None]

    class ProbeR(RBurstHADS):
        def _preemptive_provision(self):
            before = {v.id for v in self.provisioned_vms}
            super()._preemptive_provision()
            preempt.update(v.id for v in self.provisioned_vms
                           if v.id not in before)

        def select_vm(self, task, job, current_time):
            vm = super().select_vm(task, job, current_time)
            if vm is not None and vm.id in preempt:
                tag[task.task_id] = "rescue"
                arrivals["rescue"] += 1
            return vm

        def _respond_to_saturation(self, current_time):
            snap = {v.id: {t.task_id for t in v.tasks}
                    for v in self.provisioned_vms if v.id in preempt}
            super()._respond_to_saturation(current_time)
            for v in self.provisioned_vms:
                if v.id in preempt:
                    for t in v.tasks:
                        if t.task_id not in snap.get(v.id, set()):
                            tag[t.task_id] = "rebalance"
                            arrivals["rebalance"] += 1

    def record(vm, task, now):
        if vm.id in preempt and task.exec_start_on_current_vm is not None:
            dt = now - task.exec_start_on_current_vm
            busy[tag.get(task.task_id, "untagged")] += dt
            if first_hib[0] is None or task.exec_start_on_current_vm < first_hib[0]:
                busy_pre_hib[0] += dt

    orig_steal    = ws._steal_task
    orig_complete = ev.TaskCompleteEvent.execute
    orig_hib      = ev.HibernationEvent.execute

    def steal_probe(task, src_vm, dst_vm, current_time, scheduler, baseline_mode):
        if dst_vm.id in preempt:
            tag[task.task_id] = "steal"
            arrivals["steal"] += 1
        return orig_steal(task, src_vm, dst_vm, current_time, scheduler,
                          baseline_mode)

    def complete_probe(self):
        t = self.task
        if t.current_event is self and not t.completed:
            record(self.vm, t, self.time)
        return orig_complete(self)

    def hib_probe(self):
        if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            if first_hib[0] is None:
                first_hib[0] = self.time
            for t in list(self.vm.running):
                record(self.vm, t, self.time)
        return orig_hib(self)

    ws._steal_task                = steal_probe
    ev.TaskCompleteEvent.execute  = complete_probe
    ev.HibernationEvent.execute   = hib_probe
    kh, kr = TABLE9[sc]
    try:
        D, _ = compute_deadlines(n, df, 1)
        random.seed(seed)
        tasks = generate_tasks(n)
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(ProbeR, tasks, D, vm_builder=build_vms_dburst,
                               kh=kh, kr=kr, spot_risk_seed=seed,
                               spot_risk_mode="declared")
    except Exception:
        return dict(sc=sc, n=n, df=df, seed=seed, ok=False,
                    error=traceback.format_exc())
    finally:
        ws._steal_task               = orig_steal
        ev.TaskCompleteEvent.execute = orig_complete
        ev.HibernationEvent.execute  = orig_hib

    return dict(sc=sc, n=n, df=df, seed=seed, ok=True, error=None, D=D,
                mk=m.makespan(), n_preempt=len(preempt), arrivals=arrivals,
                busy=busy, busy_pre_hib=busy_pre_hib[0],
                first_hib=first_hib[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    units = [(sc, n, df, s) for sc in TABLE9 for n in NS for df in DFS
             for s in range(a.seeds)]
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

    print("Theorem 1 replacements: task arrivals per run by path, and share "
          "of their busy core-seconds")
    print(f"{'cell':12s} {'DF':>4s} | {'rescue':>6s} {'steal':>6s} "
          f"{'rebal':>6s} {'untag':>6s} | {'busy%rescue':>11s} "
          f"{'busy%steal':>10s} {'busy%rebal':>10s} | "
          f"{'busy%before 1st hib':>19s} {'1st hib/D':>9s}")
    for sc in TABLE9:
        for n in NS:
            for df in DFS:
                rs = [r for r in ok if (r["sc"], r["n"], r["df"]) == (sc, n, df)]
                if not rs:
                    continue
                arr = {p: sum(r["arrivals"][p] for r in rs) / len(rs)
                       for p in PATHS}
                tot = sum(sum(r["busy"].values()) for r in rs)
                share = {p: (100.0 * sum(r["busy"][p] for r in rs) / tot
                             if tot else float("nan")) for p in PATHS}
                pre = (100.0 * sum(r["busy_pre_hib"] for r in rs) / tot
                       if tot else float("nan"))
                fh = [r["first_hib"] / r["D"] for r in rs
                      if r["first_hib"] is not None]
                fh_s = f"{sum(fh)/len(fh):9.2f}" if fh else "     none"
                print(f"{sc} n={n:<4d}  {df:4.1f} | {arr['rescue']:6.1f} "
                      f"{arr['steal']:6.1f} {arr['rebalance']:6.1f} "
                      f"{arr['untagged']:6.1f} | {share['rescue']:10.1f}% "
                      f"{share['steal']:9.1f}% {share['rebalance']:9.1f}% | "
                      f"{pre:18.1f}% {fh_s}")
        print()

    path = _PROJ / "experiments" / "diag_rb_replacement_use.json"
    json.dump({"seeds": a.seeds, "rows": rows}, open(path, "w"), indent=1)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
