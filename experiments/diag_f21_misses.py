"""
Record-only trace of the deadline misses and infeasible runs that fix 21's
variants add over freeze-fix20 (d40a1c917c63). Changes no simulator code;
every traced run must reproduce its variant row.

For every missed task in a run where the variant misses more tasks than the
base, it records each placement of the task -- simulated time, the routine
that placed it (primary schedule, hibernation rescue, work stealing,
saturation response, provisioning), the target VM (id, market, type, launch
time, ready_time), and the finish predicted for the task on that VM when it
was placed (the planner's list-scheduled finish for the primary schedule, the
migration test's estimate for a rescue or a steal) -- plus the task's actual
start and finish and whether its VM hibernated. For HADS runs the variant
makes infeasible, it re-runs the unit with instance limits off.

    python experiments\\diag_f21_misses.py  -> experiments/diag_f21_misses.txt
"""
import sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
FP = "d40a1c917c63"
VARS = ("f21a", "f21c", "f21")


def load(p):
    d = {}
    for l in open(p):
        r = json.loads(l)
        d[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = r
    return d


def trace(arg):
    variant, (sc, n, df, seed, key) = arg
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import dynamic_comparison as dc
    import variants
    import main as mainmod
    import models.limits as lim
    import simulation.events as ev
    import policies.work_stealing as ws
    import simulation.provisioning_event as pe
    from models.vm import VM
    from scheduler.burst_hads import BurstHADS
    import scheduler.r_burst_hads as rb
    t9 = dc.TABLE9.get(sc)
    variants.apply(variant, kh=t9["kh"] if t9 else None, kr=t9["kr"] if t9 else None)
    H = dict(sched=None, ctx=[], planned={}, launch={}, hib={}, pred={})
    PL = {}
    orig = []

    def patch(owner, name, fn):
        orig.append((owner, name, getattr(owner, name)))
        setattr(owner, name, fn)

    def ctx(owner, name, label):
        o = getattr(owner, name)

        def w(*a, **k):
            H["ctx"].append(label)
            try:
                return o(*a, **k)
            finally:
                H["ctx"].pop()
        patch(owner, name, w)

    o_init = BurstHADS.__init__

    def init(self, *a, **k):
        H["sched"] = H["sched"] or self
        return o_init(self, *a, **k)
    patch(BurstHADS, "__init__", init)
    ctx(mainmod, "start_execution", "start_execution")
    ctx(ev.HibernationEvent, "execute", "hibernation rescue")
    ctx(ws, "_steal_task", "work stealing")
    ctx(rb.RBurstHADS, "_respond_to_saturation", "saturation response")
    ctx(pe.ProvisioningEvent, "execute", "provisioning event")

    o_prim = BurstHADS._run_primary_scheduler

    def prim(self):
        r = o_prim(self)
        ft = self._solution_task_finish_times(self.solution)
        H["planned"] = {t.task_id: f for t, f in ft.items()}
        return r
    patch(BurstHADS, "_run_primary_scheduler", prim)

    o_commit = lim.LaunchCounter.commit

    def commit(self, vm):
        if vm.id not in self._ids:
            eng = getattr(H["sched"], "event_engine", None)
            H["launch"][vm.id] = float(eng.time) if eng is not None else 0.0
        return o_commit(self, vm)
    patch(lim.LaunchCounter, "commit", commit)

    o_hib = ev.HibernationEvent.execute

    def hib(self):
        if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            H["hib"].setdefault(self.vm.id, []).append(round(self.time, 1))
        return o_hib(self)
    patch(ev.HibernationEvent, "execute", hib)

    o_cm = BurstHADS._check_migration

    def check(self, task, vm, current_time, deadline, burst_mode=False):
        okv = o_cm(self, task, vm, current_time, deadline, burst_mode=burst_mode)
        if okv:
            speed = vm.effective_speed(burst_mode=burst_mode) if vm.is_burstable else vm.speed
            H["pred"][task.task_id] = (vm.id, vm.estimate_finish_time(task, current_time, task_speed=speed))
        return okv
    patch(BurstHADS, "_check_migration", check)

    from models.catalogue import make_vm
    from simulation.provisioning_event import STARTUP_LATENCY
    o_fb = BurstHADS._attempt_ondemand_fallback
    H["fallback"] = {}

    def fallback(self, task, current_time):
        # Read-only: the Attempt 3 test on the same state, before the call.
        cands = [v for v in self.ondemand_vms if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                 and self._launches.can_launch(v)]
        est = []
        for v in cands:
            fresh = not self._launches.is_launched(v)
            est.append((v.id, v.vm_type, "not launched" if fresh else "launched",
                        round(max(current_time, v.ready_time or 0.0, current_time + (STARTUP_LATENCY if fresh else 0.0))
                              - current_time, 1)))
        types = []
        for tpl in self._od_catalogue:
            probe = make_vm(tpl, -1)
            fin = current_time + STARTUP_LATENCY + task.remaining_time / probe.speed * (1.0 + task.checkpoint_overhead)
            types.append((tpl["vm_type"], self._launches.can_launch_type("ondemand", tpl["vm_type"]), round(fin, 1)))
        vm = o_fb(self, task, current_time)
        H["fallback"][task.task_id] = dict(t=round(current_time, 1), D=round(self.D, 1),
                                           remaining=round(task.remaining_time, 1),
                                           types=types, candidates=len(cands), chose=vm.vm_type if vm else None)
        return vm
    patch(BurstHADS, "_attempt_ondemand_fallback", fallback)

    o_res = VM.reserve_memory

    def reserve(self, task):
        c = H["ctx"][-1] if H["ctx"] else "primary schedule"
        if c != "start_execution":
            eng = getattr(H["sched"], "event_engine", None)
            t = float(eng.time) if eng is not None else 0.0
            if c == "primary schedule":
                pred = H["planned"].get(task.task_id)
            else:
                pv = H["pred"].get(task.task_id)
                pred = pv[1] if pv and pv[0] == self.id else None
            PL.setdefault(task.task_id, []).append(
                dict(t=round(t, 1), ctx=c, vm=self.id, market=self.market, type=self.vm_type,
                     ready=None if self.ready_time is None else round(self.ready_time, 1),
                     pred=None if pred is None else round(pred, 1)))
        return o_res(self, task)
    patch(VM, "reserve_memory", reserve)

    try:
        row = dc.run_one_unit((sc, n, df, seed, key, "diag_f21_misses"))
    finally:
        for owner, name, fn in reversed(orig):
            setattr(owner, name, fn)
        variants._restore_all()
    s = H["sched"]
    out = []
    for t in s.all_tasks:
        if t.finish_time is not None and t.finish_time > t.deadline:
            vm = t.assigned_vm
            out.append(dict(task=t.task_id, exec=t.exec_time, D=round(t.deadline, 1), start=round(t.start_time, 1),
                            finish=round(t.finish_time, 1), late=round(t.finish_time - t.deadline, 1),
                            final_vm=vm.id if vm else None,
                            final_launch=None if vm is None else H["launch"].get(vm.id),
                            final_hibernations=H["hib"].get(vm.id, []) if vm else [],
                            placements=PL.get(t.task_id, []),
                            fallback=H["fallback"].get(t.task_id)))
    return dict(variant=variant, unit=[sc, n, df, seed, key],
                row={k: row.get(k) for k in ("mk", "cost", "misses", "infeasible")},
                hibernations={str(k): v for k, v in H["hib"].items()}, missed=out)


def nocap_row(arg):
    variant, (sc, n, df, seed, key) = arg
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import variant_sweep as vs
    r = vs.run_unit((sc, n, df, seed, key, FP, "nocap+" + variant))
    return dict(variant=variant, unit=[sc, n, df, seed, key], infeasible=r.get("infeasible"),
                reason=r.get("infeasible_reason"), mk=r.get("mk"), misses=r.get("misses"))


def main():
    from multiprocessing import Pool
    base = load(HERE / f"sweep_raw_{FP}.jsonl")
    units, infs = [], []
    ref = {}
    for v in VARS:
        d = load(HERE / f"sweep_variant_{v}_{FP}.jsonl")
        for u, r in d.items():
            ref[(v, u)] = r
            if not r.get("infeasible") and r.get("misses", 0) > (base[u].get("misses") or 0):
                units.append((v, u))
            if u[4] == "hads" and r.get("infeasible") and not base[u].get("infeasible"):
                infs.append((v, u))
    units.sort()
    infs = sorted(infs)[:5]
    with Pool() as pool:
        res = pool.map(trace, units, chunksize=1)
        nc = pool.map(nocap_row, infs, chunksize=1)
    json.dump(dict(traces=res, nocap=nc), open(HERE / "diag_f21_misses.json", "w"))
    rep = ["# Fix 21: the added misses and infeasible runs, traced (record-only)", ""]
    same = sum(1 for x in res if x["row"]["misses"] == ref[(x["variant"], tuple(x["unit"]))]["misses"]
               and x["row"]["mk"] == ref[(x["variant"], tuple(x["unit"]))]["mk"])
    rep.append(f"Traced runs reproducing their variant row: {same} / {len(res)}")
    rep.append("")
    for x in res:
        rep.append(f"## {x['variant']} {tuple(x['unit'])}: makespan {x['row']['mk']:.1f}, misses {x['row']['misses']}")
        for m in x["missed"]:
            rep.append(f"- task {m['task']} (exec {m['exec']} s): D {m['D']}, started {m['start']}, finished {m['finish']} "
                       f"({m['late']} s late) on VM {m['final_vm']} launched at {m['final_launch']}, "
                       f"its hibernations {m['final_hibernations']}")
            for p in m["placements"]:
                rep.append(f"    - t={p['t']} {p['ctx']} -> VM {p['vm']} {p['market']} {p['type']} ready {p['ready']} "
                           f"predicted finish {p['pred']}")
            fb = m.get("fallback")
            if fb:
                rep.append(f"    - Attempt 3 at t={fb['t']} (D {fb['D']}, remaining {fb['remaining']} s): "
                           f"{fb['candidates']} existing on-demand candidates; fresh-VM test t + omega + remaining/speed x 1.1 "
                           f"per type (type, within limit, finish): {fb['types']}; launched {fb['chose']}")
        rep.append("")
    rep.append("## HADS runs made infeasible, re-run with instance limits off")
    rep.append("")
    for y in nc:
        rep.append(f"- {y['variant']} {tuple(y['unit'])}: infeasible {y['infeasible']} ({y['reason']}); "
                   f"makespan {y['mk']}, misses {y['misses']}")
    (HERE / "diag_f21_misses.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
