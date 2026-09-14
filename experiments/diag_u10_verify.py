"""
Independent check of the entry-route attributions in experiments/diag_u10.json
(frozen code 4f08f48ac35c; no simulator code changed).

diag_u10.py attributed each placement by inspecting the Python call stack from
a property setter on task.assigned_vm. This check uses different signals:

  - the raw placement event is VM.reserve_memory(task), which every placing
    routine calls when it puts a task in a VM's queue;
  - the placing routine is taken from an explicit context stack pushed and
    popped by wrappers around each routine (HibernationEvent.execute,
    RBurstHADS._respond_to_saturation, work_stealing._steal_task,
    ProvisioningEvent.execute, _apply_solution) -- innermost wins;
  - inside a hibernation event, the tier is the R-BurstHADS tier method that
    most recently returned a VM for that task, and it is checked to be the
    VM actually reserved;
  - the burstable's owner is checked by membership in the scheduler's
    provisioned_vms at the end of the run, not by an id range.

For every missed task last placed on a burstable it compares, against the
tracer: the final VM, the routine (and tier) of the first reservation on that
VM, whether work stealing ever placed it on a burstable, baseline mode at those
reservations, and ownership.

    python experiments\\diag_u10_verify.py  -> experiments/diag_u10_verify.txt
"""
import sys, json
from pathlib import Path
from collections import defaultdict, Counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
TIERS = {"_select_replacement_vm": "tier 0 (replacement VM)",
         "_attempt_paper_migration": "tiers 1-2 (Algorithm 4 Attempts 1-2)",
         "_provision_one_more": "tier 3 (provision one more)",
         "_attempt_ondemand_fallback": "tier 4 (on-demand fallback)"}


def run(unit):
    sc, n, df, seed = unit
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import dynamic_comparison as dc
    import policies.work_stealing as ws
    import simulation.events as ev
    import simulation.provisioning_event as pe
    from simulation.event_engine import EventEngine
    from models.vm import VM
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS

    CTX, LOG, LAST, H, orig = [], defaultdict(list), {}, dict(engine=None, sched=None), {}

    def patch(owner, name, fn):
        orig[(owner, name)] = getattr(owner, name)
        setattr(owner, name, fn)

    def ctx(owner, name, label):
        o = getattr(owner, name)

        def w(*a, **k):
            CTX.append(label)
            try:
                return o(*a, **k)
            finally:
                CTX.pop()
        patch(owner, name, w)

    ctx(ev.HibernationEvent, "execute", "hibernation event")
    ctx(RBurstHADS, "_respond_to_saturation", "saturation response")
    ctx(ws, "_steal_task", "work stealing")
    ctx(pe.ProvisioningEvent, "execute", "provisioning event")
    ctx(BurstHADS, "_apply_solution", "primary schedule")

    for owner, name in ((RBurstHADS, "_select_replacement_vm"), (BurstHADS, "_attempt_paper_migration"),
                        (RBurstHADS, "_provision_one_more"), (BurstHADS, "_attempt_ondemand_fallback")):
        o = getattr(owner, name)

        def w(self, task, current_time, *a, _o=o, _name=name, **k):
            vm = _o(self, task, current_time, *a, **k)
            if vm is not None:
                LAST[task.task_id] = (TIERS[_name], vm.id)
            return vm
        patch(owner, name, w)

    o_res = VM.reserve_memory

    def reserve(self, task):
        c = CTX[-1] if CTX else "none"
        tier = None
        if c == "hibernation event" and task.task_id in LAST:
            tname, tvm = LAST.pop(task.task_id)
            tier = tname if tvm == self.id else f"{tname} (reserved elsewhere)"
        eng = H["engine"]
        LOG[task.task_id].append(dict(t=float(eng.time) if eng else 0.0, vm=self.id, market=self.market,
                                      ctx=c, tier=tier, baseline=bool(getattr(task, "baseline_mode", False))))
        return o_res(self, task)
    patch(VM, "reserve_memory", reserve)

    o_run = EventEngine.run

    def erun(self):
        H["engine"] = self
        return o_run(self)
    patch(EventEngine, "run", erun)

    o_prim = BurstHADS._run_primary_scheduler

    def prim(self):
        H["sched"] = self
        return o_prim(self)
    patch(BurstHADS, "_run_primary_scheduler", prim)

    try:
        row = dc.run_one_unit((sc, n, df, seed, "rburst", "diag_u10_verify"))
    finally:
        for (owner, name), o in orig.items():
            setattr(owner, name, o)
    s = H["sched"]
    prov = {v.id for v in s.provisioned_vms}
    missed = {}
    for t in s.all_tasks:
        if t.finish_time is not None and t.finish_time > t.deadline:
            missed[t.task_id] = LOG.get(t.task_id, [])
    return dict(unit=list(unit), row={k: row.get(k) for k in ("mk", "cost", "misses")}, provisioned=sorted(prov),
                missed=missed)


def main():
    from multiprocessing import Pool
    trace = json.load(open(HERE / "diag_u10.json"))
    units = [tuple(x["unit"]) for x in trace]
    with Pool() as pool:
        res = {tuple(r["unit"]): r for r in pool.map(run, units, chunksize=1)}
    lab = lambda e: e["path"] + (f" / {e['tier']}" if e["tier"] else "")
    to_ctx = {"saturation redistribution": "saturation response", "hibernation rescue": "hibernation event",
              "work stealing": "work stealing", "provisioning queue": "provisioning event",
              "primary schedule": "primary schedule"}
    out = []
    P = out.append
    agree, disagree = Counter(), []
    checked = 0
    for x in trace:
        u = tuple(x["unit"])
        v = res[u]
        same_row = v["row"]["misses"] == x["row"]["misses"] and abs(v["row"]["mk"] - x["row"]["mk"]) < 1e-9
        for m in x["missed"]:
            h = m["history"]
            if h[-1]["market"] != "burstable":
                continue
            checked += 1
            log = v["missed"].get(m["task"])
            problems = []
            if not same_row:
                problems.append("run not reproduced")
            if log is None:
                problems.append("task not missed in the re-run")
                disagree.append((u, m["task"], problems))
                continue
            fid_t, fid_v = h[-1]["vm"], log[-1]["vm"]
            if fid_t != fid_v:
                problems.append(f"final VM {fid_t} vs {fid_v}")
            i_t = next(k for k, e in enumerate(h) if e["vm"] == fid_t)
            first_v = next(e for e in log if e["vm"] == fid_v)
            t_route = (to_ctx.get(h[i_t]["path"], h[i_t]["path"]), h[i_t]["tier"])
            v_route = (first_v["ctx"], first_v["tier"])
            if t_route != v_route:
                problems.append(f"entry route tracer {t_route} vs reservation log {v_route}")
            if abs(h[i_t]["t"] - first_v["t"]) > 1e-9:
                problems.append(f"entry time {h[i_t]['t']} vs {first_v['t']}")
            steal_v = any(e["ctx"] == "work stealing" and e["market"] == "burstable" for e in log)
            if steal_v:
                problems.append("reservation log shows work stealing onto a burstable")
            if any(e["baseline"] for e in log if e["vm"] == fid_v):
                problems.append("baseline mode at a reservation on the final burstable")
            if fid_v not in v["provisioned"]:
                problems.append("final burstable not in provisioned_vms")
            if problems:
                disagree.append((u, m["task"], problems))
            else:
                agree[lab(h[i_t])] += 1
    P("# Independent check of diag_u10 entry routes (reservation log with explicit context stack)")
    P("")
    P(f"Re-runs reproducing the traced row: {sum(1 for x in trace if res[tuple(x['unit'])]['row']['misses'] == x['row']['misses'] and abs(res[tuple(x['unit'])]['row']['mk'] - x['row']['mk']) < 1e-9)} / {len(trace)}")
    P(f"Missed tasks last placed on a burstable, checked: {checked} (all of them, not a sample)")
    P(f"Agreeing on final VM, entry routine and tier, entry time, no work stealing, burst mode, ownership: {sum(agree.values())}")
    for k, c in agree.most_common():
        P(f"  {c:4d}  {k}")
    P(f"Disagreeing: {len(disagree)}")
    for u, t, pr in disagree:
        P(f"  {u} task {t}: {'; '.join(pr)}")
    (HERE / "diag_u10_verify.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
