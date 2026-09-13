"""
Which stage of Burst-HADS's primary scheduler plans a task past D?

diag_ils_feasibility showed that at DF=0.25 (and at the floored n=50
cells) the ILS result's planned makespan exceeds D in every run and scores
exactly Eq 9's infeasibility sentinel, 1.0 -- but it measured makespan in
task-id order, the order BurstHADS._compute_vm_load uses, while the
greedy initial solution is built against D in memory-descending order,
which is also the execution order. This separates the stages and uses the
execution order throughout:

  greedy   _initial_solution (Algorithm 2 plus the on-demand Phase 3)
  ils      _iterated_local_search's result
  final    after _allocate_burstable_vms (proactive baseline-mode moves)

For each stage: tasks whose execution-order planned finish exceeds D,
planned makespan in execution order and in id order, and how many tasks
changed VM relative to the previous stage. Burstable placements are
predicted at the speed their mode runs at (baseline for proactive moves).

The primary schedule depends only on (n, DF, seed), so this runs the
primary scheduler alone over the sweep's n x DF x seeds.

Usage (from the project root):
    python experiments\\diag_primary_stages.py --fp fb931f79c624
"""

import sys, os, json, argparse, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PROJ = HERE.parent
for p in (str(_PROJ), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


def run_unit(args):
    n, df, seed = args
    import random
    for p in (str(_PROJ), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from main import (generate_tasks, compute_deadlines, build_vms_dburst,
                      build_single_stage_job)
    from models.utils import flatten_and_assign_deadlines
    from scheduler.burst_hads import BurstHADS

    snaps = {}

    class Probe(BurstHADS):
        def _iterated_local_search(self, initial, *a, **k):
            snaps["greedy"] = dict(initial.allocation)
            best = super()._iterated_local_search(initial, *a, **k)
            snaps["ils"] = dict(best.allocation)
            return best

        def _allocate_burstable_vms(self, solution):
            out = super()._allocate_burstable_vms(solution)
            snaps["final"] = dict(out.allocation)
            snaps["baseline"] = {t.task_id for t in self.all_tasks
                                 if t.baseline_mode}
            return out

    D, _ = compute_deadlines(n, df, 1)
    random.seed(seed)
    tasks = generate_tasks(n)
    vms = build_vms_dburst()
    job = build_single_stage_job(tasks, D)
    all_tasks = flatten_and_assign_deadlines([job])
    s = Probe(vms, all_tasks, [job], deadline=D)
    s.schedule(0)
    vm_map = {v.id: v for v in s.all_vms}
    task_map = {t.task_id: t for t in s.all_tasks}
    baseline = snaps.get("baseline", set())

    def plan(alloc, exec_order):
        buckets = {}
        for t in s.all_tasks:                       # id order
            vid = alloc.get(t.task_id)
            if vid is not None:
                buckets.setdefault(vid, []).append(t)
        fin = {}
        for vid, ts in buckets.items():
            vm = vm_map[vid]
            if exec_order:
                ts = sorted(ts, key=lambda t: t.memory_req, reverse=True)
            cores = [0.0] * vm.vcpu_count
            for t in ts:
                if vm.is_burstable:
                    sp = vm.effective_speed(burst_mode=t.task_id not in baseline)
                else:
                    sp = vm.speed
                i = cores.index(min(cores))
                cores[i] += (t.exec_time / sp) * (1.0 + t.checkpoint_overhead)
                fin[t.task_id] = cores[i]
        return fin

    out = dict(n=n, df=df, seed=seed, D=D, Dspot=s.Dspot)
    prev = None
    for stage in ("greedy", "ils", "final"):
        alloc = snaps[stage]
        fe, fi = plan(alloc, True), plan(alloc, False)
        late = [tid for tid, f in fe.items() if f > D + 1e-9]
        out[stage] = dict(
            late_exec=len(late),
            late_exec_burstable=sum(vm_map[alloc[tid]].is_burstable for tid in late),
            late_id=sum(1 for f in fi.values() if f > D + 1e-9),
            mk_exec=max(fe.values()), mk_id=max(fi.values()),
            moved_from_prev=(None if prev is None else
                             sum(1 for tid in alloc if alloc[tid] != prev.get(tid))),
            late_task_ids=sorted(late))
        prev = alloc
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp", required=True, help="sweep code fingerprint")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    import dynamic_comparison as dc
    sweep = [r for r in dc._load_rows(dc.raw_path(a.fp)) if r["error"] is None]
    ns    = sorted({r["n"] for r in sweep})
    dfs   = sorted({r["df"] for r in sweep})
    seeds = sorted({r["seed"] for r in sweep})
    units = [(n, df, s) for n in ns for df in dfs for s in seeds]
    print(f"{len(units)} primary schedules on {a.workers} workers", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(processes=a.workers) as pool:
        rows = list(pool.imap_unordered(run_unit, units, chunksize=1))
    print(f"done in {time.time() - t0:.0f}s\n")

    miss = {}
    for r in sweep:
        if r["key"] == "burst":
            miss.setdefault((r["n"], r["df"], r["seed"]), []).append(r["misses"])

    print("Mean per run. late = tasks planned to finish after D in EXECUTION order "
          "(id-order count in brackets); moved = tasks whose VM changed vs the "
          "previous stage; mk/D in execution order.")
    print(f"{'n':>4} {'DF':>5} | {'greedy late':>13} {'mk/D':>5} | "
          f"{'ils late':>13} {'moved':>6} {'mk/D':>5} | {'final late':>13} "
          f"{'(burst)':>7} {'moved':>6} {'mk/D':>5} | {'sweep B miss':>12}")
    for n in ns:
        for df in dfs:
            rs = [r for r in rows if r["n"] == n and r["df"] == df]
            k = len(rs)
            m = lambda st, key: sum(r[st][key] or 0 for r in rs) / k
            sw = sum(sum(miss.get((n, df, r["seed"]), [0])) / 5 for r in rs) / k
            print(f"{n:4d} {df:5.2f} | {m('greedy','late_exec'):5.2f} ({m('greedy','late_id'):5.2f}) "
                  f"{m('greedy','mk_exec')/rs[0]['D']:5.2f} | "
                  f"{m('ils','late_exec'):5.2f} ({m('ils','late_id'):5.2f}) {m('ils','moved_from_prev'):6.1f} "
                  f"{m('ils','mk_exec')/rs[0]['D']:5.2f} | "
                  f"{m('final','late_exec'):5.2f} ({m('final','late_id'):5.2f}) "
                  f"{m('final','late_exec_burstable'):7.2f} {m('final','moved_from_prev'):6.1f} "
                  f"{m('final','mk_exec')/rs[0]['D']:5.2f} | {sw:12.2f}")

    json.dump({"fp": a.fp, "rows": rows}, open(HERE / "diag_primary_stages.json", "w"),
              indent=1)
    print(f"\nwrote {HERE / 'diag_primary_stages.json'}")


if __name__ == "__main__":
    main()
