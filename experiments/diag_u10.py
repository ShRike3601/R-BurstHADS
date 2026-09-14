"""
Does U10 cause R-BurstHADS's 109 missed tasks? (owner-authorised diagnostic
on the frozen simulator, freeze-round-b; no simulator code is changed.)

Re-runs the 104 R-BurstHADS units (limits on) that missed a deadline in
experiments/sweep_raw_4f08f48ac35c.jsonl, with record-only wrappers:

  - every change of task.assigned_vm (and every re-queue onto the same VM by
    the saturation response), with the code path that made it: primary
    schedule, hibernation rescue and the R-BurstHADS tier that chose the VM,
    saturation redistribution (Theorem 2), work stealing, provisioning queue;
    the time, slack D - t, remaining work, the placer's predicted finish
    (VM.estimate_finish_time as the placer saw it), and the best finish any
    fresh on-demand VM within the instance limits could reach from that moment
    (t + remaining/speed * (1 + ovh); execution starts a new VM's first task at
    once, with no boot delay);
  - every start of execution (VM, speed, baseline mode);
  - every hibernation that displaced the task, with progress credited
    (elapsed * speed) and progress executed (elapsed * speed / (1 + ovh));
  - every tier-4 call (_attempt_ondemand_fallback): existing on-demand VMs that
    pass _check_migration, in-limit types, and per type the frozen test's finish
    (t + omega + remaining/speed), the overhead-corrected test
    (t + omega + remaining/speed * (1 + ovh)) and the real execution finish;
  - every saturation response that moved tasks: launch room, VMs launched, and
    each moved task's destination and predicted finish.

Each traced run must reproduce its sweep row (makespan, cost, misses).

    python experiments\\diag_u10.py   -> experiments/diag_u10.json, diag_u10.txt
"""
import sys, json
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

FP = "4f08f48ac35c"
RAW = HERE / f"sweep_raw_{FP}.jsonl"
SAT_PATH = "saturation redistribution"
PATHS = [("_steal_task", None, "work stealing"),
         ("_respond_to_saturation", None, SAT_PATH),
         ("_apply_solution", None, "primary schedule"),
         ("_preemptive_provision", None, "preemptive provisioning"),
         ("execute", "ProvisioningEvent", "provisioning queue"),
         ("execute", "HibernationEvent", "hibernation rescue"),
         ("execute", "TerminationEvent", "termination rescue")]
TIER_NAMES = {"_select_replacement_vm": "tier 0 (replacement VM)",
              "_attempt_paper_migration": "tiers 1-2 (Algorithm 4 Attempts 1-2)",
              "_provision_one_more": "tier 3 (provision one more)",
              "_attempt_ondemand_fallback": "tier 4 (on-demand fallback)"}
EPS = 1e-6


def trace_unit(unit):
    sc, n, df, seed = unit
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import dynamic_comparison as dc
    from models.task import Task
    from models.vm import VM
    from models.catalogue import make_vm
    from simulation.event_engine import EventEngine
    import simulation.events as ev
    from simulation.provisioning_event import STARTUP_LATENCY
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS

    H = dict(engine=None, sched=None, capped=False)
    ASSIGN, DISPL, TIER4, DISPATCH, LAST, SAT = (defaultdict(list), defaultdict(list), defaultdict(list),
                                                 defaultdict(list), {}, [])
    orig = {}

    def now():
        e = H["engine"]
        return float(e.time) if e is not None else 0.0

    def est_excl(vm, task, t):
        free = [x.current_event.time if x.current_event is not None else t
                for x in vm.running if x is not task]
        while len(free) < vm.vcpu_count:
            free.append(t)
        free.sort()
        for x in [y for y in vm.tasks if y not in vm.running and y is not task]:
            i = free.index(min(free))
            sp = (vm.effective_speed(burst_mode=not getattr(x, "baseline_mode", False))
                  if vm.is_burstable else vm.speed)
            free[i] = max(free[i], t) + x.remaining_time / sp * (1.0 + x.checkpoint_overhead)
        i = free.index(min(free))
        return max(t, free[i]) + task.remaining_time / vm.speed * (1.0 + task.checkpoint_overhead)

    def best_fresh(task, t):
        s = H["sched"]
        ovh = 1.0 + task.checkpoint_overhead
        lim_ok, any_ok = [], []
        for tpl in s._od_catalogue:
            probe = make_vm(tpl, -1)
            if not probe.can_fit_task(task):
                continue
            f = t + task.remaining_time / probe.speed * ovh
            any_ok.append(f)
            if s._launches.can_launch_type("ondemand", tpl["vm_type"]):
                lim_ok.append(f)
        return (min(lim_ok) if lim_ok else None), (min(any_ok) if any_ok else None)

    def path_of():
        f = sys._getframe(2)
        for _ in range(14):
            if f is None:
                break
            name = f.f_code.co_name
            cls = type(f.f_locals.get("self")).__name__ if "self" in f.f_locals else None
            for fn, cl, label in PATHS:
                if name == fn and (cl is None or cls == cl):
                    return label
            f = f.f_back
        return "other"

    def g(self):
        return self.__dict__.get("_avm")

    def s(self, vm):
        prev = self.__dict__.get("_avm")
        self.__dict__["_avm"] = vm
        if vm is None or H["sched"] is None:
            return
        path = path_of()
        if vm is prev and path != SAT_PATH:
            return
        t = now()
        tier = LAST.pop(self.task_id, None) if path == "hibernation rescue" else None
        bl, bu = best_fresh(self, t)
        if tier:
            pred = tier["predicted"]
        elif path in (SAT_PATH, "work stealing"):
            pred = est_excl(vm, self, t)
        else:
            pred = None
        rec = dict(t=t, path=path, tier=tier["tier"] if tier else None, same_vm=vm is prev, predicted=pred,
                   vm=vm.id, market=vm.market, type=vm.vm_type, slots=vm.vcpu_count,
                   ready=vm in H["sched"].vms, remaining=self.remaining_time, slack=H["sched"].D - t,
                   best_fresh_in_limit=bl, best_fresh_unlimited=bu,
                   memory_fallback=bool(tier) and tier["vm"] != vm.id)
        ASSIGN[self.task_id].append(rec)
        if path == SAT_PATH and SAT:
            SAT[-1]["moved"].append(dict(task=self.task_id, market=vm.market, type=vm.vm_type,
                                         same_vm=vm is prev, predicted=pred, fresh_od=bl))

    def ge(self):
        return self.__dict__.get("_esv")

    def se(self, value):
        self.__dict__["_esv"] = value
        if value is None or H["sched"] is None:
            return
        caller = sys._getframe(1).f_locals.get("self")
        if isinstance(caller, VM):
            sp = (caller.effective_speed(burst_mode=not getattr(self, "baseline_mode", False))
                  if caller.is_burstable else caller.speed)
            DISPATCH[self.task_id].append(dict(t=value, vm=caller.id, market=caller.market, type=caller.vm_type,
                                               speed=sp, full_speed=caller.speed,
                                               baseline=bool(getattr(self, "baseline_mode", False)),
                                               remaining=self.remaining_time))

    def tier4_pre(self, task, t):
        D = self.D
        ovh = 1.0 + task.checkpoint_overhead
        existing = [v for v in self.ondemand_vms if v.state not in (VM.HIBERNATED, VM.TERMINATED)]
        ex_ok = [v.id for v in sorted(existing, key=lambda v: v.cost_rate)
                 if self._launches.can_launch(v) and self._check_migration(task, v, t, D)]
        types = []
        for tpl in self._od_catalogue:
            probe = make_vm(tpl, -1)
            types.append(dict(type=tpl["vm_type"], speed=probe.speed,
                              in_limit=self._launches.can_launch_type("ondemand", tpl["vm_type"]),
                              fits=probe.can_fit_task(task),
                              f_test=t + STARTUP_LATENCY + task.remaining_time / probe.speed,
                              f_ovh=t + STARTUP_LATENCY + task.remaining_time / probe.speed * ovh,
                              f_exec=t + task.remaining_time / probe.speed * ovh))
        il = [x for x in types if x["in_limit"]]
        pick = lambda key: next((x["type"] for x in il if x["fits"] and x[key] <= D), None)
        return dict(t=t, slack=D - t, remaining=task.remaining_time, existing_ids=set(v.id for v in existing),
                    existing_ok=ex_ok, types=types, test_choice=pick("f_test"), ovh_choice=pick("f_ovh"),
                    exec_ok=[x["type"] for x in il if x["fits"] and x["f_exec"] <= D],
                    in_limit=[x["type"] for x in il])

    def wrap_tier(cls, name):
        o = getattr(cls, name)
        orig[(cls, name)] = o

        def w(self, task, current_time, *a, **k):
            pre = tier4_pre(self, task, current_time) if name == "_attempt_ondemand_fallback" else None
            H["capped"] = False
            vm = o(self, task, current_time, *a, **k)
            if vm is not None:
                LAST[task.task_id] = dict(tier=TIER_NAMES[name], vm=vm.id,
                                          predicted=vm.estimate_finish_time(task, current_time))
                if pre is not None:
                    pre.update(chosen_vm=vm.id, chosen_type=vm.vm_type,
                               branch=("existing on-demand" if vm.id in pre["existing_ids"] else
                                       "capped fallback" if H["capped"] else "new on-demand"))
                    pre.pop("existing_ids")
                    TIER4[task.task_id].append(pre)
            return vm
        setattr(cls, name, w)

    o_capped = BurstHADS._capped_fallback
    orig[(BurstHADS, "_capped_fallback")] = o_capped

    def capped(self, task, current_time):
        H["capped"] = True
        return o_capped(self, task, current_time)

    o_run = EventEngine.run
    orig[(EventEngine, "run")] = o_run

    def run(self):
        H["engine"] = self
        return o_run(self)

    o_prim = BurstHADS._run_primary_scheduler
    orig[(BurstHADS, "_run_primary_scheduler")] = o_prim

    def prim(self):
        H["sched"] = self
        return o_prim(self)

    o_hib = ev.HibernationEvent.execute
    orig[(ev.HibernationEvent, "execute")] = o_hib

    def hib(self):
        vm = self.vm
        if vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            t = self.time
            for task in vm.tasks:
                if task.completed:
                    continue
                running = task in vm.running and task.exec_start_on_current_vm is not None
                el = (t - task.exec_start_on_current_vm) if running else 0.0
                DISPL[task.task_id].append(dict(
                    t=t, vm=vm.id, type=vm.vm_type, market=vm.market, running=running,
                    credited=el * vm.speed if running else 0.0,
                    executed=(el * vm.speed / (1.0 + task.checkpoint_overhead)) if running else 0.0,
                    remaining_before=task.remaining_time))
        return o_hib(self)

    o_sat = RBurstHADS._respond_to_saturation
    orig[(RBurstHADS, "_respond_to_saturation")] = o_sat

    def sat(self, current_time):
        before = len(self.provisioned_vms)
        SAT.append(dict(t=current_time, moved=[], D=self.D,
                        spot_room=self._launches.can_launch_type("spot", self._spot_tpl["vm_type"]),
                        burst_room=self._launches.can_launch_type("ondemand", "t3.large")))
        r = o_sat(self, current_time)
        SAT[-1]["launched"] = len(self.provisioned_vms) - before
        if not SAT[-1]["moved"]:
            SAT.pop()
        return r

    Task.assigned_vm = property(g, s)
    Task.exec_start_on_current_vm = property(ge, se)
    for cls, name in ((RBurstHADS, "_select_replacement_vm"), (BurstHADS, "_attempt_paper_migration"),
                      (RBurstHADS, "_provision_one_more"), (BurstHADS, "_attempt_ondemand_fallback")):
        wrap_tier(cls, name)
    BurstHADS._capped_fallback = capped
    EventEngine.run = run
    BurstHADS._run_primary_scheduler = prim
    ev.HibernationEvent.execute = hib
    RBurstHADS._respond_to_saturation = sat
    try:
        row = dc.run_one_unit((sc, n, df, seed, "rburst", "diag_u10"))
        sched = H["sched"]
        out = dict(unit=[sc, n, df, seed], row={k: row.get(k) for k in ("mk", "cost", "misses", "error", "infeasible")},
                   D=sched.D if sched else None, missed=[], saturation=SAT)
        if sched is not None:
            for t in sched.all_tasks:
                if t.finish_time is not None and t.finish_time > t.deadline:
                    out["missed"].append(dict(task=t.task_id, exec_time=t.exec_time, finish=t.finish_time,
                                              deadline=t.deadline, late=t.finish_time - t.deadline,
                                              history=ASSIGN.get(t.task_id, []),
                                              displacements=DISPL.get(t.task_id, []),
                                              dispatches=DISPATCH.get(t.task_id, []),
                                              tier4=TIER4.get(t.task_id, [])))
        return out
    finally:
        del Task.assigned_vm
        del Task.exec_start_on_current_vm
        for (cls, name), o in orig.items():
            setattr(cls, name, o)


def analyse(unit, D, m):
    h = m["history"]
    final = h[-1] if h else None
    fdisp = [d for d in m["dispatches"] if final is None or d["t"] >= final["t"] - EPS]
    d_last = fdisp[-1] if fdisp else (m["dispatches"][-1] if m["dispatches"] else None)
    t4 = m["tier4"][-1] if m["tier4"] else None
    u10 = False
    if t4 and t4["branch"] == "new on-demand":
        chosen = next(x for x in t4["types"] if x["type"] == t4["chosen_type"])
        corr = next((x for x in t4["types"] if x["type"] == t4["ovh_choice"]), None)
        u10 = chosen["f_exec"] > D + EPS and corr is not None and corr["f_exec"] <= D + EPS
    bl = final["best_fresh_in_limit"] if final else None
    fresh_ok = bl is not None and bl <= D + EPS
    if u10:
        split = "(a) U10: the overhead-corrected fallback test would have picked a type that makes D"
    elif not fresh_ok:
        split = "(b) no in-limit fresh on-demand VM could finish by D from its last placement"
    else:
        split = "(c) not U10, and a fresh in-limit on-demand VM could still have finished by D from its last placement"
    pred = final["predicted"] if final else None
    if pred is None:
        mech = f"no placer prediction ({final['path'] if final else 'never placed'})"
    elif pred > D + EPS:
        mech = "placed with the placer's own predicted finish already past D"
    elif m["finish"] > pred + EPS:
        if d_last and d_last["baseline"]:
            mech = "predicted on time; ran in baseline mode, slower than predicted"
        else:
            mech = "predicted on time; started later than predicted (work queued or re-queued ahead of it)"
    else:
        mech = "ran as predicted"
    sat_moves = sum(1 for x in h if x["path"] == SAT_PATH)
    over = sum(d["credited"] - d["executed"] for d in m["displacements"])
    before = [d for d in m["displacements"] if final is None or d["t"] <= final["t"] + EPS]
    return dict(final=final, d_last=d_last, t4=t4, split=split, mech=mech, sat_moves=sat_moves,
                overcredit=over, displaced_before=len(before), fresh_ok=fresh_ok)


def main():
    from multiprocessing import Pool
    raw = {}
    for l in open(RAW):
        r = json.loads(l)
        raw[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = r
    units = sorted([k[:4] for k, r in raw.items() if k[4] == "rburst" and r.get("error") is None
                    and not r.get("infeasible") and r["misses"] > 0])
    with Pool() as pool:
        res = pool.map(trace_unit, units, chunksize=1)
    rep = []
    P = rep.append
    base = lambda x: raw[tuple(x["unit"]) + ("rburst",)]
    same = sum(1 for x in res if x["row"]["mk"] is not None and abs(x["row"]["mk"] - base(x)["mk"]) < 1e-9
               and abs(x["row"]["cost"] - base(x)["cost"]) < 1e-12 and x["row"]["misses"] == base(x)["misses"])
    P(f"# U10 diagnostic: R-BurstHADS's missed tasks under limits (frozen code {FP})")
    P("")
    P(f"Traced runs reproducing their sweep row (makespan, cost, misses): {same} / {len(res)}")
    errs = [x for x in res if x["row"].get("error")]
    if errs:
        P(f"RUNS WITH AN ERROR: {len(errs)}; first: {errs[0]['unit']} {errs[0]['row']['error']}")
    rows = [(tuple(x["unit"]), x["D"], m, analyse(tuple(x["unit"]), x["D"], m)) for x in res for m in x["missed"]]
    P(f"Missed tasks traced: {len(rows)} in {len(res)} runs")
    P("")

    def counts(key, title):
        c = defaultdict(int)
        for r in rows:
            c[key(r)] += 1
        P(f"## {title}")
        P("")
        P("| | missed tasks |")
        P("|---|---|")
        for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
            P(f"| {k} | {v} |")
        P("")

    counts(lambda r: r[3]["split"], "Split requested: (a) U10 / (b) no machine could make D / (c) neither")
    counts(lambda r: (f"{r[3]['final']['path']}" + (f" / {r[3]['final']['tier']}" if r[3]['final']['tier'] else "")
                      + f" -> {r[3]['final']['market']}:{r[3]['final']['type']} ({r[3]['final']['slots']} slot)")
           if r[3]["final"] else "never placed", "Last placement: path, tier and VM")
    counts(lambda r: r[3]["mech"], "Mechanism at the last placement")
    counts(lambda r: f"{r[3]['displaced_before']} hibernation displacement(s) before the last placement",
           "Displacements before the last placement")
    counts(lambda r: f"{r[3]['sat_moves']} saturation move(s)", "Times the saturation response moved or re-queued the task")

    reached = [r for r in rows if r[3]["t4"] is not None]
    P(f"Missed tasks that ever reached tier 4: {len(reached)} of {len(rows)}.")
    for r in reached:
        t4 = r[3]["t4"]
        P(f"- {r[0]} task {r[2]['task']}: slack {t4['slack']:.0f} s, remaining {t4['remaining']:.0f}, branch {t4['branch']}, "
          f"chosen {t4['chosen_type']}, frozen-test choice {t4['test_choice']}, overhead-corrected choice {t4['ovh_choice']}, "
          f"in-limit types {t4['in_limit']}, types whose execution meets D {t4['exec_ok'] or 'none'}; per type "
          + "; ".join(f"{x['type']}: test {x['f_test']:.0f}, corrected {x['f_ovh']:.0f}, execution {x['f_exec']:.0f} (D {r[1]:.0f})"
                      for x in t4["types"]))
    P("")
    over = [r[3]["overcredit"] for r in rows]
    P(f"Re-done work at checkpoint restarts: 0 by construction (a checkpoint credits elapsed * speed). Progress credited "
      f"minus progress executed, summed per missed task: min {min(over):.1f}, max {max(over):.1f}, mean {sum(over) / len(over):.1f} work units (over-credit).")
    P("")

    ev_all = [(tuple(x["unit"]), e) for x in res for e in x["saturation"]]
    moved = [(u, e, mv) for u, e in ev_all for mv in e["moved"]]
    P("## Saturation responses (Theorem 2) in the 104 runs")
    P("")
    P(f"Responses that moved tasks: {len(ev_all)}; tasks moved or re-queued: {len(moved)}; of them onto burstables "
      f"{sum(1 for _, _, mv in moved if mv['market'] == 'burstable')}, re-queued onto the same VM "
      f"{sum(1 for _, _, mv in moved if mv['same_vm'])}, with the response's own predicted finish past D "
      f"{sum(1 for _, e, mv in moved if mv['predicted'] is not None and mv['predicted'] > e['D'] + EPS)}; "
      f"of those, a fresh in-limit on-demand VM could have made D for "
      f"{sum(1 for _, e, mv in moved if mv['predicted'] is not None and mv['predicted'] > e['D'] + EPS and mv['fresh_od'] is not None and mv['fresh_od'] <= e['D'] + EPS)}.")
    P(f"Launch room at those responses: spot template {sum(1 for _, e in ev_all if e['spot_room'])} / {len(ev_all)}, "
      f"t3.large {sum(1 for _, e in ev_all if e['burst_room'])} / {len(ev_all)}; VMs launched by them: {sum(e['launched'] for _, e in ev_all)}.")
    P("")

    P("## Per missed task")
    P("")
    P("| unit (sc n DF seed) | task | late s | displ. before last | over-credit | sat. moves | last placement | slack s | remaining | last VM | predicted / actual finish | last start: wait s, speed | fresh in-limit od finish (D) | tier 4 | split | mechanism |")
    P("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for unit, D, m, a in sorted(rows, key=lambda r: (r[0], r[2]["task"])):
        f = a["final"]
        dl = a["d_last"]
        lp = (f["path"] + (f" / {f['tier']}" if f["tier"] else "") + (" (same VM)" if f["same_vm"] else "")) if f else "—"
        lv = (f"{f['market']}:{f['type']}" + ("" if f["ready"] else " (not yet ready)")) if f else "—"
        pf = (f"{f['predicted']:.0f} / {m['finish']:.0f}" if f and f["predicted"] is not None else f"— / {m['finish']:.0f}")
        ws = f"{dl['t'] - f['t']:.0f}, {dl['speed']:.2f}{' baseline' if dl['baseline'] else ''}" if (dl and f) else "—"
        bf = (f"{f['best_fresh_in_limit']:.0f} ({D:.0f})" if f and f["best_fresh_in_limit"] is not None else f"none ({D:.0f})")
        t4 = a["t4"]
        t4s = (f"slack {t4['slack']:.0f}, {t4['branch']}, chose {t4['chosen_type']}, test {t4['test_choice']}, "
               f"corrected {t4['ovh_choice']}, meets D: {', '.join(t4['exec_ok']) or 'none'}") if t4 else "not reached"
        P(f"| {unit[0]} {unit[1]} {unit[2]} {unit[3]} | {m['task']} | {m['late']:.1f} | {a['displaced_before']} | "
          f"{a['overcredit']:.1f} | {a['sat_moves']} | {lp} | {f['slack']:.0f} | {f['remaining']:.0f} | {lv} | {pf} | {ws} | "
          f"{bf} | {t4s} | {a['split'][:3]} | {a['mech']} |")
    (HERE / "diag_u10.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    json.dump(res, open(HERE / "diag_u10.json", "w"), indent=1, default=str)
    cut = next(i for i, l in enumerate(rep) if l.startswith("## Per missed task"))
    print("\n".join(rep[:cut]))


if __name__ == "__main__":
    main()
