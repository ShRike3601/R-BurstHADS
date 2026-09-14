"""
Record-only probe over the frozen sweep (limits on, all 7,200 runs):

  1. Checkpoint over-credit per scheduler. At every hibernation, for each task
     running on the hibernated VM: progress credited by Task.save_checkpoint
     (elapsed * speed) and progress execution actually made
     (elapsed * speed / (1 + ovh)), plus displaced queued tasks.
  2. Starts before ready. Tasks started on a VM R-BurstHADS provisioned
     (RBurstHADS._create_vm) before that VM's ready_time, by market, with the
     head start in seconds.

Every run must reproduce its frozen row (makespan, cost, misses).

    python experiments\\diag_overcredit_boot.py -> experiments/diag_overcredit_boot.json, .txt
"""
import sys, json, random
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
FP = "4f08f48ac35c"
KEYS = ("hads", "burst", "rburst")


def probe_unit(u):
    sc, n, df, seed, key = u
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import dynamic_comparison as dc
    import simulation.events as ev
    from models.vm import VM
    from scheduler.r_burst_hads import RBurstHADS
    acc = dict(disp_running=0, disp_queued=0, credited=0.0, executed=0.0,
               early_starts_spot=0, early_starts_burstable=0, early_seconds=0.0)
    o_hib, o_create, o_start = ev.HibernationEvent.execute, RBurstHADS._create_vm, VM.start_next_if_free

    def hib(self):
        vm = self.vm
        if vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            for t in vm.tasks:
                if t.completed:
                    continue
                if t in vm.running and t.exec_start_on_current_vm is not None:
                    el = self.time - t.exec_start_on_current_vm
                    acc["disp_running"] += 1
                    acc["credited"] += el * vm.speed
                    acc["executed"] += el * vm.speed / (1.0 + t.checkpoint_overhead)
                else:
                    acc["disp_queued"] += 1
        return o_hib(self)

    def create(self, *args, **kw):
        vm = o_create(self, *args, **kw)
        vm._probe_ready_at = kw["ready_time"] if "ready_time" in kw else args[6]
        return vm

    def start(self, current_time, engine):
        before = set(map(id, self.running))
        r = o_start(self, current_time, engine)
        ra = getattr(self, "_probe_ready_at", None)
        if ra is not None and current_time < ra:
            for t in self.running:
                if id(t) not in before:
                    acc["early_starts_spot" if self.is_spot else "early_starts_burstable"] += 1
                    acc["early_seconds"] += ra - current_time
        return r

    ev.HibernationEvent.execute, RBurstHADS._create_vm, VM.start_next_if_free = hib, create, start
    try:
        row = dc.run_one_unit((sc, n, df, seed, key, "diag_overcredit_boot"))
    finally:
        ev.HibernationEvent.execute, RBurstHADS._create_vm, VM.start_next_if_free = o_hib, o_create, o_start
    from main import generate_tasks
    random.seed(seed)
    work = sum(t.exec_time for t in generate_tasks(n))
    return dict(unit=list(u), row={k: row.get(k) for k in ("mk", "cost", "misses", "infeasible", "error")},
                work=work, **acc)


def main():
    from multiprocessing import Pool
    raw = {}
    for l in open(HERE / f"sweep_raw_{FP}.jsonl"):
        r = json.loads(l)
        raw[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = r
    units = sorted(raw)
    with Pool() as pool:
        res = pool.map(probe_unit, units, chunksize=4)
    json.dump(res, open(HERE / "diag_overcredit_boot.json", "w"))
    ok = lambda r: r.get("error") is None and not r.get("infeasible")
    rep = [f"# Checkpoint over-credit and starts before ready (frozen code {FP}, limits on)", ""]
    repro = 0
    for x in res:
        b = raw[tuple(x["unit"])]
        if (bool(b.get("infeasible")) == bool(x["row"].get("infeasible")) and
                (b.get("infeasible") or (abs(b["mk"] - x["row"]["mk"]) < 1e-9 and abs(b["cost"] - x["row"]["cost"]) < 1e-12
                                         and b["misses"] == x["row"]["misses"]))):
            repro += 1
    rep.append(f"Probed runs reproducing their frozen row: {repro} / {len(res)}")
    rep.append("")
    miss_cells = {u[:3] for u, r in raw.items() if u[4] == "rburst" and ok(r) and r["misses"] > 0}
    for title, sel in (("all cells", lambda u: True), ("the 22 miss-producing cells", lambda u: tuple(u[:3]) in miss_cells)):
        rep.append(f"## Checkpoint over-credit per scheduler, {title}")
        rep.append("")
        rep.append("| scheduler | feasible runs | displaced running tasks / run | displaced queued tasks / run | progress credited / run | executed / run | over-credit / run (work units) | over-credit, % of workload | runs with any over-credit |")
        rep.append("|---|---|---|---|---|---|---|---|---|")
        for k in KEYS:
            xs = [x for x in res if x["unit"][4] == k and ok(x["row"]) and sel(x["unit"])]
            m = lambda f: sum(x[f] for x in xs) / len(xs)
            oc = [x["credited"] - x["executed"] for x in xs]
            share = 100.0 * sum(oc) / sum(x["work"] for x in xs)
            rep.append(f"| {k} | {len(xs)} | {m('disp_running'):.2f} | {m('disp_queued'):.2f} | {m('credited'):.1f} | "
                       f"{m('executed'):.1f} | {sum(oc) / len(xs):.1f} | {share:.3f}% | {sum(1 for v in oc if v > 0)} |")
        rep.append("")
    rep.append("## Tasks started before their R-BurstHADS-provisioned VM was ready")
    rep.append("")
    xs = [x for x in res if x["unit"][4] == "rburst" and ok(x["row"])]
    es = sum(x["early_starts_spot"] for x in xs)
    eb = sum(x["early_starts_burstable"] for x in xs)
    rep.append(f"R-BurstHADS, {len(xs)} feasible runs: early starts on spot VMs {es} (in {sum(1 for x in xs if x['early_starts_spot'])} runs), "
               f"on burstables {eb}; total head start {sum(x['early_seconds'] for x in xs):.0f} s "
               f"(mean {sum(x['early_seconds'] for x in xs) / max(1, es + eb):.1f} s per early start). "
               f"HADS and Burst-HADS provision no such VMs.")
    (HERE / "diag_overcredit_boot.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
