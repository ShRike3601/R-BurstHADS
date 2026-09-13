"""
Where do HADS's deadline misses come from? Measured, not asserted.

Written against the pre-fix-8 code (commit b7e3662), where the post-fix
checkpoints showed HADS missing deadlines in sc1 n=300 at DF 1.0 (3.7)
and DF 2.0 (2.2) and in sc2 n=100 at DF 0.5 (0.9), and Burst-HADS /
R-BurstHADS missing none. Its output, experiments/diag_hads_misses.json
and .txt, is the evidence for fix 8. On code after fix 8 the "base"
variant already includes the planner correction, so re-running it
reproduces the plan_ovh column, not the original misses.

For every task that finishes after D it records:
  planned VM    where the primary scheduler's allocation put it
  final VM      where it actually finished
  planned_hib   whether the planned VM was ever hibernated
  plan_nominal  the planner's predicted finish for that task, list-
                scheduled without checkpoint overhead (the pre-fix-8
                _vm_makespan_static)
  plan_ovh      the same with (1 + checkpoint_overhead), which is what
                execution actually charges
  finish        the task's real finish time

Configs: the Table 9 cells above, plus the same sizes and DFs with NO
hibernation at all, which judges the primary scheduler on its own. Each
config runs under every requested variant (experiments/variants.py), with
a fresh worker pool per variant. The "base" variant must reproduce the
checkpoint's miss counts exactly; if it does not, the probe is perturbing
the run and nothing else here can be trusted.

Usage (from the project root):
    python experiments\\diag_hads_misses.py --workers 18 --seeds 10
"""

import sys, os, json, argparse, time
from collections import Counter
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

# (label, n, df, kh, kr); kh=None means no hibernation events at all.
CONFIGS = [
    ("sc1 n=300",   300, 0.5, 1.0, 0.0),
    ("sc1 n=300",   300, 1.0, 1.0, 0.0),
    ("sc1 n=300",   300, 2.0, 1.0, 0.0),
    ("sc2 n=100",   100, 0.5, 5.0, 0.0),
    ("nohib n=300", 300, 0.5, None, None),
    ("nohib n=300", 300, 1.0, None, None),
    ("nohib n=300", 300, 2.0, None, None),
    ("nohib n=100", 100, 0.5, None, None),
    ("nohib n=100", 100, 1.0, None, None),
    ("nohib n=100", 100, 2.0, None, None),
]

SCHEDULERS = ["HADS", "BurstHADS", "R-BurstHADS"]


def run_unit(args):
    label, n, df, kh, kr, seed, sched, variant = args

    import io, contextlib, random, traceback
    if str(_PROJ) not in sys.path:
        sys.path.insert(0, str(_PROJ))

    from experiments import variants
    variants.apply(variant, kh=kh, kr=kr)

    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst)
    from models.vm import VM
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS
    import simulation.events as ev

    base_cls = {"HADS": HADS, "BurstHADS": BurstHADS,
                "R-BurstHADS": RBurstHADS}[sched]
    holder = {}

    class Probe(base_cls):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["s"] = self

    hib = {}   # vm id -> time of its first hibernation
    orig_execute = ev.HibernationEvent.execute

    def execute_probe(self):
        if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            hib.setdefault(self.vm.id, self.time)
        return orig_execute(self)

    ev.HibernationEvent.execute = execute_probe
    try:
        D, _ = compute_deadlines(n, df, 1)
        random.seed(seed)
        tasks = generate_tasks(n)
        kwargs = dict(vm_builder=build_vms_dburst, spot_risk_seed=seed,
                      spot_risk_mode="declared")
        if kh is not None:
            kwargs.update(kh=kh, kr=kr)
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(Probe, tasks, D, **kwargs)
    except Exception:
        return dict(label=label, n=n, df=df, seed=seed, sched=sched,
                    variant=variant, ok=False, error=traceback.format_exc())
    finally:
        ev.HibernationEvent.execute = orig_execute

    s        = holder["s"]
    alloc    = s.solution.allocation
    vm_by_id = {v.id: v for v in s.all_vms}
    all_t    = [t for job in m.jobs for st in job.stages for t in st.tasks]

    # The planner's predicted finish per task. _apply_solution orders each
    # queue by memory descending, and start_next_if_free starts waiting[0]
    # on whichever core frees first, so list scheduling in that order is
    # exactly the execution order.
    plan_nom, plan_ovh, buckets = {}, {}, {}
    for t in all_t:
        vid = alloc.get(t.task_id)
        if vid is not None:
            buckets.setdefault(vid, []).append(t)
    plan_end = {}
    for vid, ts in buckets.items():
        vm = vm_by_id.get(vid)
        if vm is None or vm.is_burstable:
            continue
        ts = sorted(ts, key=lambda t: t.memory_req, reverse=True)
        c_nom = [0.0] * vm.vcpu_count
        c_ovh = [0.0] * vm.vcpu_count
        for t in ts:
            i = c_nom.index(min(c_nom))
            c_nom[i] += t.exec_time / vm.speed
            plan_nom[t.task_id] = c_nom[i]
            j = c_ovh.index(min(c_ovh))
            c_ovh[j] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
            plan_ovh[t.task_id] = c_ovh[j]
        plan_end[vid] = (vm.market, max(c_nom))

    late = []
    for t in all_t:
        if t.finish_time and t.finish_time > t.deadline:
            pv = vm_by_id.get(alloc.get(t.task_id))
            fv = t.assigned_vm
            late.append(dict(
                task=t.task_id, exec=t.exec_time, D=D, Dspot=s.Dspot,
                planned_vm=pv.id if pv else None,
                planned_type=pv.vm_type if pv else None,
                planned_market=pv.market if pv else None,
                planned_hib=(pv.id in hib) if pv else None,
                planned_hib_time=hib.get(pv.id) if pv else None,
                final_vm=fv.id if fv else None,
                final_market=fv.market if fv else None,
                moved=(pv is not fv),
                plan_nominal=plan_nom.get(t.task_id),
                plan_ovh=plan_ovh.get(t.task_id),
                finish=t.finish_time,
                late_by=t.finish_time - t.deadline))

    spot_ends = [e for mkt, e in plan_end.values() if mkt == VM.SPOT]
    od_ends   = [e for mkt, e in plan_end.values() if mkt == VM.ONDEMAND]
    mk = m.makespan()
    return dict(label=label, n=n, df=df, kh=kh, kr=kr, seed=seed,
                sched=sched, variant=variant, ok=True, error=None,
                D=D, Dspot=s.Dspot, mk=mk, mk_frac=mk / D,
                misses=m.deadline_misses(), n_hib_vms=len(hib),
                n_planned_spot=len(spot_ends), n_planned_od=len(od_ends),
                max_plan_spot=max(spot_ends, default=None),
                max_plan_od=max(od_ends, default=None),
                late=late)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--variants", default="base,plan_ovh")
    a = ap.parse_args()
    variant_names = a.variants.split(",")

    from multiprocessing import Pool
    rows = []
    t0 = time.time()
    for v in variant_names:
        units = [(label, n, df, kh, kr, s, sched, v)
                 for (label, n, df, kh, kr) in CONFIGS
                 for s in range(a.seeds)
                 for sched in SCHEDULERS]
        print(f"variant {v}: {len(units)} runs on {a.workers} workers",
              flush=True)
        with Pool(processes=a.workers) as pool:
            rows.extend(pool.imap_unordered(run_unit, units, chunksize=1))
    print(f"all runs done in {time.time() - t0:.0f}s\n")

    bad = [r for r in rows if not r["ok"]]
    if bad:
        print(f"!! {len(bad)} runs FAILED. First:\n{bad[0]['error']}")
    ok = [r for r in rows if r["ok"]]

    def pick(label, df, sched, v):
        return [r for r in ok if r["label"] == label and r["df"] == df
                and r["sched"] == sched and r["variant"] == v]

    print("MEAN DEADLINE MISSES  (mean makespan / D)")
    print(f"{'config':12s} {'DF':>4s} {'scheduler':12s} "
          + "".join(f"{v:>22s}" for v in variant_names))
    for (label, n, df, kh, kr) in CONFIGS:
        for sched in SCHEDULERS:
            cells = []
            for v in variant_names:
                rs = pick(label, df, sched, v)
                if rs:
                    cells.append(f"{_mean([r['misses'] for r in rs]):8.1f} "
                                 f"({_mean([r['mk_frac'] for r in rs])*100:6.1f}%)")
                else:
                    cells.append("n/a")
            print(f"{label:12s} {df:4.1f} {sched:12s} "
                  + "".join(f"{c:>22s}" for c in cells))
        print()

    print("LATE-TASK ATTRIBUTION")
    for v in variant_names:
        for (label, n, df, kh, kr) in CONFIGS:
            for sched in SCHEDULERS:
                rs   = pick(label, df, sched, v)
                late = [x for r in rs for x in r["late"]]
                if not late:
                    continue
                undisturbed = [x for x in late
                               if not x["moved"] and not x["planned_hib"]]
                stayed_hib  = [x for x in late
                               if not x["moved"] and x["planned_hib"]]
                moved       = [x for x in late if x["moved"]]
                explained   = [x for x in undisturbed
                               if x["plan_nominal"] is not None
                               and x["plan_nominal"] <= x["Dspot"] + 1e-6
                               and x["plan_ovh"] > x["D"]]
                print(f"[{v}] {label} DF={df} {sched}: {len(late)} late "
                      f"tasks over {len(rs)} runs")
                print(f"    stayed on planned, never-hibernated VM: "
                      f"{len(undisturbed)}  by planned market "
                      f"{dict(Counter(x['planned_market'] for x in undisturbed))}")
                if undisturbed:
                    print(f"      plan_nominal <= Dspot and plan_ovh > D: "
                          f"{len(explained)}/{len(undisturbed)}")
                    print(f"      mean plan_nominal/Dspot "
                          f"{_mean([x['plan_nominal']/x['Dspot'] for x in undisturbed if x['plan_nominal']]):.3f}"
                          f"   mean finish/plan_ovh "
                          f"{_mean([x['finish']/x['plan_ovh'] for x in undisturbed if x['plan_ovh']]):.3f}"
                          f"   mean late_by {_mean([x['late_by'] for x in undisturbed]):.1f}s")
                print(f"    stayed on planned VM that was hibernated: "
                      f"{len(stayed_hib)}")
                print(f"    moved off planned VM: {len(moved)}  by final "
                      f"market {dict(Counter(x['final_market'] for x in moved))}"
                      + (f"  mean late_by {_mean([x['late_by'] for x in moved]):.1f}s"
                         if moved else ""))
        print()

    print("PLANNED QUEUE ENDS, HADS, first variant (nominal, no overhead)")
    for (label, n, df, kh, kr) in CONFIGS:
        rs = pick(label, df, "HADS", variant_names[0])
        if not rs:
            continue
        r0 = rs[0]
        ms = _mean([r['max_plan_spot'] for r in rs])
        print(f"  {label:12s} DF={df}: D={r0['D']:.0f} Dspot={r0['Dspot']:.0f} "
              f"max spot queue {ms:.0f} (x1.1 = {ms*1.1:.0f})  "
              f"spot VMs {_mean([r['n_planned_spot'] for r in rs]):.1f}  "
              f"od VMs {_mean([r['n_planned_od'] for r in rs]):.1f}")

    path = _PROJ / "experiments" / "diag_hads_misses.json"
    json.dump({"seeds": a.seeds, "variants": variant_names, "rows": rows},
              open(path, "w"), indent=1)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
