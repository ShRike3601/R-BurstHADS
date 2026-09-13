"""
Does Burst-HADS's primary schedule plan tasks to finish after D?

diag_burst_misses found every late Burst-HADS / R-BurstHADS task in the
sweep was never moved and sat on a VM that was never hibernated, and every
late task on a non-burstable VM had been planned by the primary schedule
to finish after D. This measures that directly.

Hypothesis under test, not a finding: Equation 9 scores an infeasible
candidate (makespan > Dspot) at exactly 1.0, which is an upper bound on
every feasible score only while normalised cost <= 1. The normaliser is
the most expensive SPOT rate x Dspot x |spot VMs|, but the initial
solution's Phase 3 places tasks on on-demand VMs, whose cost enters
_evaluate. If a feasible solution can score above 1.0, the ILS prefers an
infeasible one, and nothing downstream re-checks D.

The primary schedule depends only on (n, DF, seed) -- Table 9 events are
drawn after it, from their own RNG -- so this runs the primary scheduler
alone over the sweep's n x DF x seeds, and compares planned-late tasks
with the sweep's actual Burst-HADS misses for the same (n, DF, seed) in
every scenario.

Per run it records: D, Dspot; the initial solution's makespan and number
of on-demand VMs; the ILS result's makespan and its Eq 9 score at Dspot;
the largest feasible score computed during the search and how many
feasible scores exceeded 1.0; and, after proactive burstable allocation,
how many tasks the final plan has finishing after D.

Usage (from the project root):
    python experiments\\diag_ils_feasibility.py --fp fb931f79c624
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
    from models.vm import VM
    from scheduler.burst_hads import BurstHADS

    st = dict(max_feasible=0.0, n_feasible=0, n_feasible_over1=0,
              n_infeasible=0)

    class Probe(BurstHADS):
        def _fitness(self, solution, dspot):
            f = super()._fitness(solution, dspot)
            mk, _ = self._evaluate(solution)
            if mk > dspot:
                st["n_infeasible"] += 1
            else:
                st["n_feasible"] += 1
                st["max_feasible"] = max(st["max_feasible"], f)
                st["n_feasible_over1"] += f > 1.0
            return f

        def _iterated_local_search(self, initial, *a, **k):
            mk0, _ = self._evaluate(initial)
            vm_map = {v.id: v for v in self.all_vms}
            st["init_mk"] = mk0
            st["init_fit"] = BurstHADS._fitness(self, initial, self.Dspot)
            st["init_od_vms"] = sum(1 for v in initial.selected_vms
                                    if v.market == VM.ONDEMAND)
            best = super()._iterated_local_search(initial, *a, **k)
            mkb, cb = self._evaluate(best)
            max_cost = (max(v.cost_rate for v in self.spot_vms)
                        * self.Dspot * len(self.spot_vms))
            st["best_mk"] = mkb
            st["best_fit_at_dspot"] = BurstHADS._fitness(self, best, self.Dspot)
            st["best_norm_cost"] = cb / max_cost if max_cost else None
            st["best_od_vms"] = sum(1 for vid in set(best.allocation.values())
                                    if vm_map[vid].market == VM.ONDEMAND)
            return best

    D, _ = compute_deadlines(n, df, 1)
    random.seed(seed)
    tasks = generate_tasks(n)
    vms = build_vms_dburst()
    job = build_single_stage_job(tasks, D)
    all_tasks = flatten_and_assign_deadlines([job])
    s = Probe(vms, all_tasks, [job], deadline=D)
    s.schedule(0)

    finish = s._solution_task_finish_times(s.solution)
    vm_map = {v.id: v for v in s.all_vms}
    planned_late = 0
    planned_late_burst = 0
    for t in s.all_tasks:
        vm = vm_map.get(s.solution.allocation.get(t.task_id))
        if vm is None:
            continue
        if vm.is_burstable:
            f = s._baseline_finish(t, vm) if t.baseline_mode else \
                (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
            if f > D:
                planned_late += 1
                planned_late_burst += 1
        elif finish[t] > D:
            planned_late += 1
    return dict(n=n, df=df, seed=seed, D=D, Dspot=s.Dspot,
                planned_late=planned_late,
                planned_late_burstable=planned_late_burst, **st)


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

    misses = {}
    for r in sweep:
        misses.setdefault((r["key"], r["n"], r["df"], r["seed"]), []).append(r["misses"])

    print(f"{'n':>4} {'DF':>5} | {'best>D':>6} {'feas>1':>6} {'maxfeas':>7} "
          f"{'bestfit':>7} {'normC':>6} {'odVMs':>5} | {'plan late':>9} "
          f"{'(burst)':>7} | {'sweep miss B':>12} {'R':>6}")
    tot_plan = tot_b = tot_r = 0.0
    agree = []
    for n in ns:
        for df in dfs:
            rs = [r for r in rows if r["n"] == n and r["df"] == df]
            k = len(rs)
            f = lambda key: sum(r[key] for r in rs) / k
            mb = sum(sum(misses.get(("burst", n, df, r["seed"]), [0])) / 5 for r in rs) / k
            mr = sum(sum(misses.get(("rburst", n, df, r["seed"]), [0])) / 5 for r in rs) / k
            tot_plan += f("planned_late"); tot_b += mb; tot_r += mr
            for r in rs:
                sw = misses.get(("burst", n, df, r["seed"]), [])
                if sw:
                    agree.append((r["planned_late"] > 0, max(sw) > 0))
            print(f"{n:4d} {df:5.2f} | {sum(r['best_mk'] > r['D'] for r in rs):3d}/{k:<2d} "
                  f"{sum(r['n_feasible_over1'] > 0 for r in rs):3d}/{k:<2d} "
                  f"{f('max_feasible'):7.3f} {f('best_fit_at_dspot'):7.3f} "
                  f"{f('best_norm_cost'):6.2f} {f('best_od_vms'):5.1f} | "
                  f"{f('planned_late'):9.2f} {f('planned_late_burstable'):7.2f} | "
                  f"{mb:12.2f} {mr:6.2f}")
    both = sum(1 for p, s in agree if p and s)
    only_plan = sum(1 for p, s in agree if p and not s)
    only_sweep = sum(1 for p, s in agree if s and not p)
    print(f"\n(n, DF, seed) units: planned-late AND a sweep miss in some scenario: {both}; "
          f"planned-late but no sweep miss: {only_plan}; sweep miss but nothing planned late: {only_sweep}")
    print("columns: best>D = ILS result's planned makespan exceeds D; feas>1 = a feasible "
          "Eq 9 score above 1.0 occurred; maxfeas = largest feasible score; bestfit = "
          "result's score at Dspot; normC = result's normalised cost; odVMs = on-demand "
          "VMs in the result; plan late = tasks the final plan finishes after D "
          "(burst = of which on a burstable); sweep miss = mean over the 5 scenarios")

    json.dump({"fp": a.fp, "rows": rows}, open(HERE / "diag_ils_feasibility.json", "w"),
              indent=1)
    print(f"wrote {HERE / 'diag_ils_feasibility.json'}")


if __name__ == "__main__":
    main()
