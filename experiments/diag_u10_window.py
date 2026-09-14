"""
Why fix 20 (U10) changes no run: record-only probe of the on-demand fallback's
fresh-VM deadline test (HADS and Burst-HADS; R-BurstHADS inherits Burst-HADS's).

Runs variants u10_ovh (frozen code + fix 20) and fx_all (fixes 17a, 18, 19, 20),
all three schedulers, 30 seeds, limits on. Around every call of the installed
_attempt_ondemand_fallback it reads, before the call, the in-limit on-demand
types and the task's remaining time, and after the call whether a fresh VM was
drawn from M^o (the type walk ran). For every walk it evaluates both tests on
the same state:

    without overhead: t + omega + remaining / speed          <= D
    with overhead:    t + omega + remaining / speed * (1+ovh) <= D

and classifies it: a type passes both tests; no type passes either
(unsavable); or a type passes without the overhead but not with it (the only
case in which fix 20 can change a decision). It checks that the type actually
launched is the one the with-overhead walk picks, and that every run
reproduces its variant row.

    python experiments\\diag_u10_window.py -> experiments/diag_u10_window.json, .txt
"""
import sys, json
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
FP = "4f08f48ac35c"
KEYS = ("hads", "burst", "rburst")
VARS = ("u10_ovh", "fx_all")


def probe_unit(arg):
    variant, (sc, n, df, seed, key) = arg
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import dynamic_comparison as dc
    import variants
    from models.catalogue import make_vm
    from simulation.provisioning_event import STARTUP_LATENCY
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    t9 = dc.TABLE9.get(sc)     # as experiments/variant_sweep.py applies a variant
    variants.apply(variant, kh=t9["kh"] if t9 else None, kr=t9["kr"] if t9 else None)
    acc = Counter()
    ratios = []           # (D - f0) / (remaining/speed * ovh) for the type picked, walks where a type passes
    installed = {c: c.__dict__["_attempt_ondemand_fallback"] for c in (HADS, BurstHADS)}

    def wrap(o):
        def fb(self, task, current_time):
            in_limit = [t for t in self._od_catalogue
                        if self._launches.can_launch_type("ondemand", t["vm_type"])]
            pre_id = self._next_new_vm_id
            rem, ovh, D = task.remaining_time, task.checkpoint_overhead, self.D
            vm = o(self, task, current_time)
            acc["calls"] += 1
            if not in_limit:
                acc["capped"] += 1
                return vm
            if self._next_new_vm_id == pre_id:
                acc["running on-demand VM"] += 1
                return vm
            acc["walks"] += 1
            pick0 = pick1 = None
            window = False
            for tpl in in_limit:
                probe = make_vm(tpl, -1)
                e = rem / probe.speed
                fits = probe.can_fit_task(task)
                p0 = fits and current_time + STARTUP_LATENCY + e <= D
                p1 = fits and current_time + STARTUP_LATENCY + e * (1.0 + ovh) <= D
                window |= p0 and not p1
                if p0 and pick0 is None:
                    pick0 = (tpl["vm_type"], D - current_time - STARTUP_LATENCY - e, e * ovh)
                if p1 and pick1 is None:
                    pick1 = tpl["vm_type"]
            launched = vm.vm_type if hasattr(vm, "vm_type") else None
            expect = pick1 if pick1 is not None else in_limit[0]["vm_type"]
            if launched is not None and launched != expect:
                acc["launched type differs from the with-overhead walk"] += 1
            if pick0 is None:
                acc["no type passes either test (unsavable)"] += 1
            elif window:
                acc["a type passes only without the overhead"] += 1
                if (pick0[0] if pick0 else in_limit[0]["vm_type"]) != expect:
                    acc["picked type differs between the tests"] += 1
            else:
                acc["picked type passes both tests"] += 1
            if pick0 is not None:
                ratios.append(pick0[1] / pick0[2] if pick0[2] > 0 else float("inf"))
            return vm
        return fb

    for c, o in installed.items():
        setattr(c, "_attempt_ondemand_fallback", wrap(o))
    try:
        row = dc.run_one_unit((sc, n, df, seed, key, f"diag_u10_window_{variant}"))
    finally:
        for c, o in installed.items():
            setattr(c, "_attempt_ondemand_fallback", o)
        variants._restore_all()
    return dict(variant=variant, unit=[sc, n, df, seed, key],
                row={k: row.get(k) for k in ("mk", "cost", "misses", "infeasible", "error")},
                counts=dict(acc), min_ratio=min(ratios) if ratios else None,
                ratios_lt_2=sum(1 for r in ratios if r < 2.0))


def main():
    from multiprocessing import Pool
    ref, units = {}, []
    for v in VARS:
        for l in open(HERE / f"sweep_variant_{v}_{FP}.jsonl"):
            r = json.loads(l)
            u = (r["scenario"], r["n"], r["df"], r["seed"], r["key"])
            ref[(v, u)] = r
            units.append((v, u))
    units.sort()
    with Pool() as pool:
        res = pool.map(probe_unit, units, chunksize=4)
    json.dump(res, open(HERE / "diag_u10_window.json", "w"))
    same = lambda a, b: (bool(a.get("infeasible")) == bool(b.get("infeasible")) and a.get("error") == b.get("error")
                         and (a.get("infeasible") or (a["mk"] == b["mk"] and a["cost"] == b["cost"]
                                                      and a["misses"] == b["misses"])))
    rep = ["# Fix 20 (U10): the fresh-VM deadline test with and without the overhead, on the same state", ""]
    rep.append(f"Probed runs reproducing their variant row: {sum(1 for x in res if same(x['row'], ref[(x['variant'], tuple(x['unit']))]))} / {len(res)}")
    rep.append("")
    cols = ["calls", "capped", "running on-demand VM", "walks", "picked type passes both tests",
            "no type passes either test (unsavable)", "a type passes only without the overhead",
            "picked type differs between the tests", "launched type differs from the with-overhead walk"]
    rep.append("| variant | scheduler | runs with a walk | " + " | ".join(cols) + " | smallest (D - finish) / (exec x ovh) | walks with that ratio < 2 |")
    rep.append("|---|---|---|" + "---|" * len(cols) + "---|---|")
    for v in VARS:
        for k in KEYS:
            xs = [x for x in res if x["variant"] == v and x["unit"][4] == k]
            tot = Counter()
            for x in xs:
                tot.update(x["counts"])
            mr = [x["min_ratio"] for x in xs if x["min_ratio"] is not None]
            tail = f"{min(mr):.2f} | {sum(x['ratios_lt_2'] for x in xs)}" if mr else "- | 0"
            rep.append(f"| {v} | {k} | {sum(1 for x in xs if x['counts'].get('walks'))} | "
                       + " | ".join(str(tot.get(c, 0)) for c in cols) + f" | {tail} |")
    (HERE / "diag_u10_window.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
