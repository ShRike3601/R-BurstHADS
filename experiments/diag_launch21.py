"""
Record-only probe for fix 21 (experiments/fix21_plan.md). Changes no simulator
code; every probed run must reproduce its row in the reference sweep file.

Per run it logs:
  - every VM's launch (its first LaunchCounter.commit): simulated time, phase
    (primary schedule, before the event engine exists, or run), whether the VM
    builder built the VM, market, and the scheduling routine that launched it;
  - every VM's first task start (VM.start_next_if_free);
  - R-BurstHADS's burstable branch: burstables created by _provision_one_more
    (tier 3) and by _respond_to_saturation, and for each tier-3 firing what
    selected the burstable;
  - placements: every VM.reserve_memory call except start_execution's
    re-reservation at t = 0, and how many landed on a branch burstable.

Invariant: a VM that is not exempt -- exempt means built by the builder AND
launched in the primary schedule -- starts no task before launch + T_start.

    python experiments\\diag_launch21.py --variant base --ref experiments/sweep_raw_d40a1c917c63.jsonl --tag base
      -> experiments/diag_launch21_<tag>.json, .txt
"""
import sys, json, argparse
from pathlib import Path
from collections import Counter, defaultdict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
KEYS = ("hads", "burst", "rburst")
ROUTINES = {  # stack frame name -> routine reported
    "_initial_solution": "Burst-HADS primary: Phase 1-3 (_initial_solution)",
    "_greedy_construct": "HADS primary: Phase (a)-(c) (_greedy_construct)",
    "_allocate_burstable_vms": "Burst-HADS primary: proactive burstables (_allocate_burstable_vms)",
    "_apply_solution": "primary: _apply_solution",
    "_preemptive_provision": "R-BurstHADS primary: Theorem 1 replacement (_preemptive_provision)",
    "_capped_fallback": "run: _capped_fallback", "capped": "run: _capped_fallback",
    "_attempt_ondemand_fallback": "run: Attempt 3 / stage 3 (_attempt_ondemand_fallback)",
    "burst_fallback": "run: Attempt 3 / stage 3 (_attempt_ondemand_fallback)",
    "hads_fallback": "run: Attempt 3 / stage 3 (_attempt_ondemand_fallback)",
    "walk": "run: Attempt 3 / stage 3 (_attempt_ondemand_fallback)",
    "_attempt_paper_migration": "run: Attempts 1-2 (_attempt_paper_migration)",
    "_select_replacement_vm": "run: tier 0 (_select_replacement_vm)",
    "_provision_one_more": "run: tier 3 (_provision_one_more)",
    "_respond_to_saturation": "run: saturation response (_respond_to_saturation)",
    "select_vm": "run: HADS stages 1-2 (select_vm)",
}
HELPERS = ("_launch_new_ondemand_vm", "_launch_burstable_vms", "_create_vm")


def _site():
    f, helper = sys._getframe(2), None
    for _ in range(14):
        if f is None:
            break
        name = f.f_code.co_name
        if name in HELPERS and helper is None:
            helper = name
        if name in ROUTINES:
            return ROUTINES[name], helper or "existing VM object"
        f = f.f_back
    return "unrecognised", helper or "existing VM object"


def probe_unit(arg):
    variant, (sc, n, df, seed, key) = arg
    for p in (str(ROOT), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import dynamic_comparison as dc
    import main as mainmod
    import variants
    import models.limits as lim
    from models.vm import VM
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    import scheduler.r_burst_hads as rb
    from simulation.provisioning_event import STARTUP_LATENCY

    # Always apply, "base" included: apply() first restores anything an earlier
    # variant left patched in this worker process.
    t9 = dc.TABLE9.get(sc)
    variants.apply(variant, kh=t9["kh"] if t9 else None, kr=t9["kr"] if t9 else None)
    H = dict(sched=None, builder=set(), in_start=False)
    L, S, BRANCH = {}, {}, set()
    br, reasons, place = Counter(), Counter(), Counter()
    orig = []

    def patch(owner, name, fn):
        orig.append((owner, name, getattr(owner, name)))
        setattr(owner, name, fn)

    def init_wrap(o):
        def __init__(self, vms, *a, **k):
            if H["sched"] is None:
                H["builder"] = {id(v) for v in vms}
                H["sched"] = self
            return o(self, vms, *a, **k)
        return __init__

    patch(HADS, "__init__", init_wrap(HADS.__init__))
    patch(BurstHADS, "__init__", init_wrap(BurstHADS.__init__))

    o_commit = lim.LaunchCounter.commit

    def commit(self, vm):
        if vm.id not in self._ids and id(vm) not in L:
            eng = getattr(H["sched"], "event_engine", None)
            site, helper = _site()
            L[id(vm)] = dict(t=float(eng.time) if eng is not None else 0.0, primary=eng is None,
                             builder=id(vm) in H["builder"], market=vm.market, site=site, helper=helper)
        return o_commit(self, vm)
    patch(lim.LaunchCounter, "commit", commit)

    o_start = VM.start_next_if_free

    def start_next_if_free(self, current_time, engine):
        before = len(self.running)
        r = o_start(self, current_time, engine)
        if id(self) not in S and len(self.running) > before:
            S[id(self)] = float(current_time)
        return r
    patch(VM, "start_next_if_free", start_next_if_free)

    o_res = VM.reserve_memory

    def reserve_memory(self, task):
        if not H["in_start"]:
            place["all"] += 1
            if id(self) in BRANCH:
                place["branch"] += 1
        return o_res(self, task)
    patch(VM, "reserve_memory", reserve_memory)

    o_se = mainmod.start_execution

    def start_execution(vms, t, eng):
        H["in_start"] = True
        try:
            return o_se(vms, t, eng)
        finally:
            H["in_start"] = False
    patch(mainmod, "start_execution", start_execution)

    o_om = rb.RBurstHADS._provision_one_more

    def _provision_one_more(self, task, current_time):
        slack = self.D - current_time
        if not slack > rb.STARTUP_LATENCY * rb.SLACK_MULTIPLIER:
            why = "slack <= 2 x T_start (spot not tried)"
        else:
            sp = self._spot_tpl["speed"]
            fin = current_time + rb.STARTUP_LATENCY + task.remaining_time / sp * (1.0 + task.checkpoint_overhead)
            if fin > self.D:
                why = "spot finish past D"
            elif self.D - fin <= task.exec_time / sp:
                why = "spot spare-time rule"
            elif not self._launches.can_launch_type("spot", self._spot_tpl["vm_type"]):
                why = "spot launch limit"
            else:
                why = "spot chosen"
        vm = o_om(self, task, current_time)
        if vm is None:
            br["tier3 returned nothing"] += 1
        elif vm.is_burstable:
            br["tier3 burstable"] += 1
            reasons[why] += 1
            BRANCH.add(id(vm))
        else:
            br["tier3 spot"] += 1
        return vm
    patch(rb.RBurstHADS, "_provision_one_more", _provision_one_more)

    o_create = rb.RBurstHADS._create_vm

    def _create_vm(self, *a, **kw):
        vm = o_create(self, *a, **kw)
        if vm.is_burstable:
            f, sat = sys._getframe(1), False
            for _ in range(6):
                if f is None:
                    break
                if f.f_code.co_name == "_respond_to_saturation":
                    sat = True
                    break
                f = f.f_back
            if sat:
                br["saturation burstable"] += 1
                BRANCH.add(id(vm))
        return vm
    patch(rb.RBurstHADS, "_create_vm", _create_vm)

    try:
        row = dc.run_one_unit((sc, n, df, seed, key, f"diag_launch21_{variant}"))
    finally:
        for owner, name, fn in reversed(orig):
            setattr(owner, name, fn)
        variants._restore_all()

    sites = defaultdict(lambda: [0, 0, 0, 0.0])      # launches, ran a task, violations, early seconds
    for k, rec in L.items():
        exempt = rec["builder"] and rec["primary"]
        first = S.get(k)
        s = sites[(key, "primary" if rec["primary"] else "run", "builder" if rec["builder"] else "created",
                   rec["market"], rec["site"], rec["helper"], "exempt" if exempt else "pays")]
        s[0] += 1
        if first is not None:
            s[1] += 1
            need = rec["t"] + STARTUP_LATENCY
            if not exempt and first < need - 1e-6:
                s[2] += 1
                s[3] += need - first
    return dict(unit=[sc, n, df, seed, key],
                row={k: row.get(k) for k in ("mk", "cost", "misses", "infeasible", "error")},
                sites=[[list(k), v] for k, v in sites.items()], branch=dict(br), reasons=dict(reasons),
                placements=dict(place))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="base")
    ap.add_argument("--ref", required=True, help="sweep jsonl the probed rows must reproduce")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--keys", default="hads,burst,rburst")
    ap.add_argument("--seeds", default="0-29")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.seeds.split("-"))
    keys = a.keys.split(",")
    ref = {}
    for l in open(ROOT / a.ref):
        r = json.loads(l)
        u = (r["scenario"], r["n"], r["df"], r["seed"], r["key"])
        if u[4] in keys and lo <= u[3] <= hi:
            ref[u] = r
    units = sorted(ref)
    from multiprocessing import Pool
    with Pool() as pool:
        res = pool.map(probe_unit, [(a.variant, u) for u in units], chunksize=4)
    json.dump(res, open(HERE / f"diag_launch21_{a.tag}.json", "w"))

    def same(x, r):
        if bool(x.get("infeasible")) != bool(r.get("infeasible")) or x.get("error") != r.get("error"):
            return False
        return x.get("infeasible") or (x["mk"] == r["mk"] and x["cost"] == r["cost"] and x["misses"] == r["misses"])
    rep = [f"# Fix 21 launch census, invariant and burstable branch: variant {a.variant} (reference {a.ref})", ""]
    rep.append(f"Probed runs reproducing their reference row exactly: "
               f"{sum(1 for x in res if same(x['row'], ref[tuple(x['unit'])]))} / {len(res)}")
    rep.append("")
    agg = defaultdict(lambda: [0, 0, 0, 0.0])
    for x in res:
        for k, v in x["sites"]:
            s = agg[tuple(k)]
            for i in range(4):
                s[i] += v[i]
    rep.append("## Launch sites (a launch = a VM's first LaunchCounter.commit)")
    rep.append("")
    rep.append("| scheduler | phase | VM from | market | routine | via | deploy time | launches | ran a task | "
               "task started before launch + T_start | mean seconds early |")
    rep.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(agg, key=lambda k: (KEYS.index(k[0]), k[1] != "primary", k[4], k[3])):
        v = agg[k]
        rep.append(f"| {' | '.join(k)} | {v[0]} | {v[1]} | {v[2]} | {v[3] / v[2]:.1f} |" if v[2] else
                   f"| {' | '.join(k)} | {v[0]} | {v[1]} | 0 | - |")
    rep.append("")
    tot_pay = sum(v[1] for k, v in agg.items() if k[6] == "pays")
    tot_bad = sum(v[2] for k, v in agg.items() if k[6] == "pays")
    unrec = sum(v[0] for k, v in agg.items() if k[4] == "unrecognised")
    rep.append(f"Invariant: non-exempt launches that ran a task {tot_pay}; of them started a task before launch + T_start: "
               f"{tot_bad}. Launches from an unrecognised routine: {unrec}.")
    rep.append("")
    rb_ = [x for x in res if x["unit"][4] == "rburst"]
    if rb_:
        nr = len(rb_)
        t3 = sum(x["branch"].get("tier3 burstable", 0) for x in rb_)
        sat = sum(x["branch"].get("saturation burstable", 0) for x in rb_)
        pa = sum(x["placements"].get("all", 0) for x in rb_)
        pb = sum(x["placements"].get("branch", 0) for x in rb_)
        rep.append("## R-BurstHADS's burstable branch")
        rep.append("")
        rep.append("| path | firings | per run | runs with a firing | firings as share of all placements |")
        rep.append("|---|---|---|---|---|")
        for name, cnt, fld in (("tier 3 (_provision_one_more)", t3, "tier3 burstable"),
                               ("saturation response", sat, "saturation burstable")):
            rep.append(f"| {name} | {cnt} | {cnt / nr:.3f} | {sum(1 for x in rb_ if x['branch'].get(fld, 0))} / {nr} | "
                       f"{100.0 * cnt / pa:.3f}% |")
        rep.append(f"| both | {t3 + sat} | {(t3 + sat) / nr:.3f} | "
                   f"{sum(1 for x in rb_ if x['branch'].get('tier3 burstable', 0) or x['branch'].get('saturation burstable', 0))} / {nr} | "
                   f"{100.0 * (t3 + sat) / pa:.3f}% |")
        rep.append("")
        rep.append(f"Placements (VM.reserve_memory calls, start_execution's re-reservation excluded): {pa} "
                   f"({pa / nr:.1f} per run); placed on a branch burstable: {pb} ({100.0 * pb / pa:.3f}%).")
        rep.append(f"Tier 3 calls: burstable {t3}, spot {sum(x['branch'].get('tier3 spot', 0) for x in rb_)}, "
                   f"nothing {sum(x['branch'].get('tier3 returned nothing', 0) for x in rb_)}.")
        rep.append("")
        rep.append("| what selected the burstable, tier 3 | firings |")
        rep.append("|---|---|")
        rs = Counter()
        for x in rb_:
            rs.update(x["reasons"])
        for k, v in rs.most_common():
            rep.append(f"| {k} | {v} |")
        rep.append("")
    (HERE / f"diag_launch21_{a.tag}.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
