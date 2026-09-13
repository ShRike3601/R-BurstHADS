"""
Where do Burst-HADS's and R-BurstHADS's residual deadline misses come from?

The full sweep on fixes 1-10 (fingerprint fb931f79c624) shows HADS missing
no deadline in any cell, while Burst-HADS misses in 22 cells and
R-BurstHADS in 21, all at DF <= 0.5, at most 1.8 tasks of 300 per run.
Fix 8 showed that the last unexplained misses were a planner bug, so these
get the same treatment: every late task's placement history is recorded
and the misses are attributed, not explained.

Per run and task it logs
  plan    the VM the primary schedule put it on (baseline mode flagged for
          a proactive burstable placement)
  select  a select_vm placement after a hibernation, with the destination's
          estimated finish at that moment
  steal   an Algorithm 5 move, with the destination's estimated finish
  rebal   an R-BurstHADS Theorem 2 redistribution
  start   each time it starts executing: VM, speed, scheduled finish

and, for every VM the primary schedule planned, each task's predicted
finish list-scheduled (with checkpoint overhead, as the post-fix-8
planner does) in two orders:
  plan_id    task-id order: how BurstHADS._compute_vm_load and
             _solution_task_finish_times bucket tasks, i.e. what the ILS
             fitness and the proactive burstable step see
  plan_exec  memory-descending: how _apply_solution queues them and
             start_next_if_free runs them

Cells: every cell of the given sweep where Burst-HADS or R-BurstHADS
missed, all seeds. The per-run miss counts must reproduce the sweep's; if
they do not, the probe is perturbing the run and nothing here is usable.

Usage (from the project root):
    python experiments\\diag_burst_misses.py --fp fb931f79c624
"""

import sys, os, json, argparse, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PROJ = HERE.parent
for p in (str(_PROJ), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

TABLE9 = {"sc1": (1.0, 0.0), "sc2": (5.0, 0.0), "sc3": (1.0, 5.0),
          "sc4": (5.0, 5.0), "sc5": (3.0, 2.5)}


def run_unit(args):
    sc, n, df, seed, sched = args
    import io, contextlib, random, traceback
    for p in (str(_PROJ), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst)
    from models.vm import VM
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS
    import simulation.events as ev
    import policies.work_stealing as ws

    hist, hib = {}, []
    holder = {}

    def log(task, *e):
        hist.setdefault(task.task_id, []).append(e)

    base = {"burst": BurstHADS, "rburst": RBurstHADS}[sched]

    class Probe(base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["s"] = self

        def _apply_solution(self, solution):
            super()._apply_solution(solution)
            for vm in self.all_vms:
                for t in vm.tasks:
                    log(t, "plan", 0.0, vm.id, vm.market,
                        bool(vm.is_burstable and t.baseline_mode), None, None)

        def select_vm(self, task, job, current_time):
            vm = super().select_vm(task, job, current_time)
            if vm is not None:
                sp = (vm.effective_speed(burst_mode=True) if vm.is_burstable
                      else vm.speed)
                est = vm.estimate_finish_time(task, current_time, task_speed=sp)
                log(task, "select", current_time, vm.id, vm.market, False,
                    est, sp)
            return vm

        # Only RBurstHADS ever calls this; on BurstHADS it is inert.
        def _respond_to_saturation(self, current_time):
            snap = {v.id: {x.task_id for x in v.tasks}
                    for v in self.provisioned_vms}
            super()._respond_to_saturation(current_time)
            for v in self.provisioned_vms:
                for x in v.tasks:
                    if x.task_id not in snap.get(v.id, set()):
                        log(x, "rebal", current_time, v.id, v.market,
                            bool(x.baseline_mode), None, None)

    orig_steal = ws._steal_task
    orig_start = VM.start_next_if_free
    orig_hib   = ev.HibernationEvent.execute

    def steal_probe(task, src_vm, dst_vm, current_time, scheduler,
                    baseline_mode):
        sp = (dst_vm.effective_speed(burst_mode=not baseline_mode)
              if dst_vm.is_burstable else dst_vm.speed)
        est = dst_vm.estimate_finish_time(task, current_time, task_speed=sp)
        orig_steal(task, src_vm, dst_vm, current_time, scheduler,
                   baseline_mode)
        log(task, "steal", current_time, dst_vm.id, dst_vm.market,
            bool(baseline_mode), est, sp)

    def start_probe(self, current_time, engine):
        before = {id(x) for x in self.running}
        out = orig_start(self, current_time, engine)
        for x in self.running:
            if id(x) not in before:
                base_mode = bool(self.is_burstable
                                 and getattr(x, "baseline_mode", False))
                sp = (self.effective_speed(burst_mode=not base_mode)
                      if self.is_burstable else self.speed)
                log(x, "start", current_time, self.id, self.market, base_mode,
                    x.current_event.time, sp)
        return out

    def hib_probe(self):
        if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            hib.append((self.time, self.vm.id))
        return orig_hib(self)

    ws._steal_task = steal_probe
    VM.start_next_if_free = start_probe
    ev.HibernationEvent.execute = hib_probe
    kh, kr = TABLE9[sc]
    try:
        D, _ = compute_deadlines(n, df, 1)
        random.seed(seed)
        tasks = generate_tasks(n)
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(Probe, tasks, D, vm_builder=build_vms_dburst,
                               kh=kh, kr=kr, spot_risk_seed=seed,
                               spot_risk_mode="declared")
    except Exception:
        return dict(sc=sc, n=n, df=df, seed=seed, sched=sched, ok=False,
                    error=traceback.format_exc())
    finally:
        ws._steal_task = orig_steal
        VM.start_next_if_free = orig_start
        ev.HibernationEvent.execute = orig_hib

    s = holder["s"]
    vm_by_id = {v.id: v for v in s.all_vms}
    alloc = s.solution.allocation
    # log tuples are (kind, time, vm_id, market, baseline, est_or_finish, speed)
    planned_base = {tid: e[0][4] for tid, e in hist.items()
                    if e and e[0][0] == "plan"}

    buckets = {}
    for t in s.all_tasks:                     # task-id order, as the ILS
        vid = alloc.get(t.task_id)
        if vid is not None:
            buckets.setdefault(vid, []).append(t)

    def ls(ts, vm):
        cores, fin = [0.0] * vm.vcpu_count, {}
        for t in ts:
            i = cores.index(min(cores))
            cores[i] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
            fin[t.task_id] = cores[i]
        return fin

    plan_id, plan_exec = {}, {}
    vm_rows = []
    for vid, ts in buckets.items():
        vm = vm_by_id.get(vid)
        if vm is None:
            continue
        if vm.is_burstable:
            for t in ts:
                sp = vm.effective_speed(burst_mode=not planned_base.get(t.task_id, False))
                f = (t.exec_time / sp) * (1.0 + t.checkpoint_overhead)
                plan_id[t.task_id] = plan_exec[t.task_id] = f
            continue
        a = ls(ts, vm)
        b = ls(sorted(ts, key=lambda t: t.memory_req, reverse=True), vm)
        plan_id.update(a)
        plan_exec.update(b)
        vm_rows.append(dict(vm=vid, market=vm.market, n_tasks=len(ts),
                            end_id=max(a.values()), end_exec=max(b.values())))

    hib_vms = {v for _, v in hib}
    all_t = [t for job in m.jobs for st in job.stages for t in st.tasks]
    late = []
    for t in all_t:
        if not (t.finish_time and t.finish_time > t.deadline):
            continue
        ev_ = hist.get(t.task_id, [])
        placements = [e for e in ev_ if e[0] in ("plan", "select", "steal", "rebal")]
        starts = [e for e in ev_ if e[0] == "start"]
        planned_vm = placements[0][2] if placements and placements[0][0] == "plan" else None
        last = placements[-1] if placements else None
        late.append(dict(
            task=t.task_id, exec=t.exec_time, mem=t.memory_req,
            finish=t.finish_time, late_by=t.finish_time - D,
            planned_vm=planned_vm,
            planned_market=vm_by_id[planned_vm].market if planned_vm in vm_by_id else None,
            planned_vm_hibernated=planned_vm in hib_vms,
            plan_id=plan_id.get(t.task_id), plan_exec=plan_exec.get(t.task_id),
            moves=[e[0] for e in placements[1:]],
            last_kind=last[0] if last else None,
            last_market=last[3] if last else None,
            last_baseline=last[4] if last else None,
            last_time=last[1] if last else None,
            last_est=last[5] if last else None,
            n_starts=len(starts),
            final_start=starts[-1][1] if starts else None,
            final_start_market=starts[-1][3] if starts else None,
            final_start_baseline=starts[-1][4] if starts else None,
            final_sched_finish=starts[-1][5] if starts else None,
            history=ev_))

    return dict(sc=sc, n=n, df=df, seed=seed, sched=sched, ok=True,
                error=None, D=D, Dspot=s.Dspot, mk=m.makespan(),
                misses=m.deadline_misses(), n_hib=len(hib),
                vm_rows=vm_rows,
                plan_end_id=max((r["end_id"] for r in vm_rows), default=0.0),
                plan_end_exec=max((r["end_exec"] for r in vm_rows), default=0.0),
                late=late)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp", required=True, help="sweep code fingerprint")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    import dynamic_comparison as dc
    sweep = {}
    for r in dc._load_rows(dc.raw_path(a.fp)):
        sweep[dc._unit_key(r)] = r
    cells = sorted({(r["scenario"], r["n"], r["df"]) for r in sweep.values()
                    if r["key"] in ("burst", "rburst") and r["error"] is None
                    and r["misses"] > 0})
    seeds = sorted({r["seed"] for r in sweep.values()})
    units = [(sc, n, df, s, k) for (sc, n, df) in cells for s in seeds
             for k in ("burst", "rburst")]
    print(f"{len(cells)} cells with Burst-HADS/R-BurstHADS misses; "
          f"{len(units)} runs on {a.workers} workers", flush=True)

    from multiprocessing import Pool
    t0 = time.time()
    with Pool(processes=a.workers) as pool:
        rows = list(pool.imap_unordered(run_unit, units, chunksize=2))
    print(f"done in {time.time() - t0:.0f}s\n")
    bad = [r for r in rows if not r["ok"]]
    if bad:
        print(f"!! {len(bad)} FAILED. First:\n{bad[0]['error']}")
    ok = [r for r in rows if r["ok"]]

    differ = [r for r in ok if sweep[(r["sc"], r["n"], r["df"], r["seed"],
                                      r["sched"])]["misses"] != r["misses"]]
    print(f"VERIFY: {len(ok)} runs, {len(differ)} with a miss count that "
          f"differs from sweep {a.fp}")

    for sched in ("burst", "rburst"):
        rs = [r for r in ok if r["sched"] == sched]
        late = [x for r in rs for x in r["late"]]
        name = {"burst": "Burst-HADS", "rburst": "R-BurstHADS"}[sched]
        print(f"\n=== {name}: {len(late)} late tasks in "
              f"{sum(1 for r in rs if r['late'])} of {len(rs)} runs")
        if not late:
            continue
        never = [x for x in late if not x["moves"]]
        moved = [x for x in late if x["moves"]]
        order = [x for x in never if x["plan_id"] is not None
                 and x["plan_id"] <= x["finish"] - x["late_by"] + 1e-9
                 and x["plan_exec"] > x["finish"] - x["late_by"]]
        print(f"  never moved off planned VM: {len(never)}  "
              f"(planned market {dict(Counter(x['planned_market'] for x in never))}, "
              f"planned VM hibernated {sum(x['planned_vm_hibernated'] for x in never)})")
        if never:
            print(f"    plan_id <= D < plan_exec (queue order mismatch): "
                  f"{len(order)}/{len(never)}")
            print(f"    plan_exec > D: {sum(1 for x in never if x['plan_exec'] and x['plan_exec'] > x['finish'] - x['late_by'])}"
                  f"   finish / plan_exec: "
                  f"{sum(x['finish'] / x['plan_exec'] for x in never if x['plan_exec']) / max(1, sum(1 for x in never if x['plan_exec'])):.3f}")
        print(f"  moved: {len(moved)}")
        kinds = Counter((x["last_kind"], x["last_market"], x["last_baseline"])
                        for x in moved)
        for (kind, mkt, basem), c in kinds.most_common():
            grp = [x for x in moved if (x["last_kind"], x["last_market"],
                                        x["last_baseline"]) == (kind, mkt, basem)]
            est_over = sum(1 for x in grp if x["last_est"] is not None
                           and x["last_est"] > x["finish"] - x["late_by"])
            print(f"    last move {kind:6s} -> {mkt:9s}{' baseline' if basem else '':9s}: "
                  f"{c:3d}  est>D at placement {est_over}/{c}  "
                  f"mean late_by {sum(x['late_by'] for x in grp)/c:.1f}s  "
                  f"mean exec {sum(x['exec'] for x in grp)/c:.0f}")
        runs_order = sum(1 for r in rs if r["plan_end_id"] <= r["D"] < r["plan_end_exec"])
        print(f"  runs whose planned queues end <= D in id order but > D in "
              f"execution order: {runs_order}/{len(rs)}")
        print("  first late tasks (history: kind, t, vm, market, baseline, est/finish, speed):")
        for x in late[:4]:
            print(f"    task {x['task']} exec={x['exec']} finish={x['finish']:.1f} "
                  f"late_by={x['late_by']:.1f} plan_id={x['plan_id']} plan_exec={x['plan_exec']}")
            for e in x["history"]:
                print("       ", tuple(round(v, 1) if isinstance(v, float) else v for v in e))

    path = HERE / "diag_burst_misses.json"
    json.dump({"fp": a.fp, "rows": rows}, open(path, "w"), indent=1)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
