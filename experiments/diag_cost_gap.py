"""
Round A: why do both baselines cost so much more under hibernation than the
paper reports?

baseline_validation shows Burst-HADS's average cost increase over HADS in
the hibernation scenarios at +38-44% against TCC23's +1.92%, and both
schedulers getting 50-190% dearer under hibernation than without it. Both
schedulers show it, so it is not in either scheduler. This checks the
candidates in order of cost, and decides nothing on its own.

  (a) AGGREGATION. TCC23's +1.92% is "considering all executions" of
      Table 9: 4 jobs x 5 scenarios (sc3-sc5 have kr > 0). Our aggregate is
      reported under several weightings -- mean of per-cell changes, change
      of pooled totals, mean of per-run paired changes, median -- and per
      scenario, and compared cell by cell where TCC23's values are in the
      text (Table 10's J60 Burst-HADS column; the five paper_reproduction
      cells, flagged unverified).

  (b) BILLING RULE. TCC23 section 3.1: "When a new vmj is launched, the user
      is charged cj for each period of time. When the VM terminates or
      hibernates, the user's charge for this VM immediately stops", with
      periods T = {1..D} -- seconds. Costs are recomputed post hoc from each
      VM's billing intervals under:
        R0      ours: per second, first dispatch to shutdown or hibernation
        AC      every billing interval rounded up to whole 900 s cycles
        PRE2    fix 2's predecessor: open intervals clamped at makespan
                (meaningful in the no_release variant, which also undoes
                fix 3's end-of-run release)
        LAUNCH  + every launched VM also charged from its launch (the
                engine clock at its first LaunchCounter.commit) to its
                first dispatch, or to the end of the run if it never ran a
                task (Burst-HADS's proactive burstables): B1 in
                DEVIATIONS.md, TCC23's "charged ... when launched"
        NOPHANT - VMs billed without ever being launched by the scheduler:
                never-launched pool VMs that a Table 8 resume set billing
                (B5). Removes their whole cost, an upper bound.
        PAPER   LAUNCH and NOPHANT together: TCC23 section 3.1's rule

  (c) EBS WHILE HIBERNATED. TCC23 section 1 says hibernated instances are
      charged for EBS storage; its formulation charges nothing. Priced at
      $0.10 per GB-month (gp2, us-east-1) on a root volume of 8 GB plus the
      instance's RAM, 730 h per month:
        EBSHIB  R0 + EBS for hibernated seconds
        EBSALL  R0 + EBS for billed and hibernated seconds

DECOMPOSITION, per scheduler and scenario: billed seconds by market;
hibernated seconds; billed seconds of never-launched VMs; launched
burstables never billed.

Usage (from the project root):
    python experiments\\diag_cost_gap.py --tag NAME --variant nocap
"""

import sys, os, io, json, math, time, argparse, contextlib
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
_PROJ = HERE.parent
for p in (str(_PROJ), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

JOBS = ["J60", "J80", "J100", "ED200"]
SCENARIOS = ["none", "sc1", "sc2", "sc3", "sc4", "sc5"]
HIB = SCENARIOS[1:]
KEYS = ("hads", "burst")
AC = 900.0
EBS_PER_GB_S = 0.10 / (730 * 3600)
ROOT_GB = 8.0
RULES = ["R0", "AC", "PRE2", "LAUNCH", "NOPHANT", "PAPER", "EBSHIB", "EBSALL"]


def run_unit(args):
    job, sc, seed, key, copies, variant = args
    for p in (str(_PROJ), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import baseline_validation as bv
    from experiments import paper_reproduction as pr
    if variant != "base":
        from experiments import variants
        s_ = pr.SCENARIOS.get(sc)
        variants.apply(variant, kh=s_["kh"] if s_ else None,
                       kr=s_["kr"] if s_ else None, seed=seed)
    from main import run_simulation
    from models.vm import VM
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    import simulation.events as ev
    import simulation.resume_event as rev
    import models.limits as lim

    holder, hib, busy, launch_t = {}, {}, {}, {}

    class Capture({"hads": HADS, "burst": BurstHADS}[key]):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["s"] = self

    o_hib, o_res, o_done = (ev.HibernationEvent.execute, rev.ResumeEvent.execute,
                            ev.TaskCompleteEvent.execute)

    counts = dict(hib=0, hib_busy=0, hib_launched=0, res=0)

    def hib_probe(self):
        if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
            counts["hib"] += 1
            counts["hib_busy"] += int(bool(self.vm.tasks))
            lc = getattr(holder.get("s"), "_launches", None)
            counts["hib_launched"] += int(bool(lc) and self.vm.id in lc._ids)
            hib.setdefault(self.vm.id, []).append([self.time, None])
            for t in list(self.vm.running):
                if t.exec_start_on_current_vm is not None:
                    busy.setdefault(self.vm.id, []).append((t.exec_start_on_current_vm, self.time))
        return o_hib(self)

    def res_probe(self):
        if self.vm.state == VM.HIBERNATED and hib.get(self.vm.id) and hib[self.vm.id][-1][1] is None:
            hib[self.vm.id][-1][1] = self.time
            counts["res"] += 1
        return o_res(self)

    def done_probe(self):
        t = self.task
        if t.current_event is self and not t.completed and t.exec_start_on_current_vm is not None:
            busy.setdefault(self.vm.id, []).append((t.exec_start_on_current_vm, self.time))
        return o_done(self)

    o_commit = lim.LaunchCounter.commit

    def commit_probe(self, vm):
        if vm.id not in self._ids:
            eng = getattr(holder.get("s"), "event_engine", None)
            launch_t[vm.id] = float(getattr(eng, "time", 0.0) or 0.0)
        return o_commit(self, vm)

    ev.HibernationEvent.execute, rev.ResumeEvent.execute, ev.TaskCompleteEvent.execute = \
        hib_probe, res_probe, done_probe
    lim.LaunchCounter.commit = commit_probe
    tasks = bv.gen_table6(job, seed)
    kwargs = dict(vm_builder=lambda: pr.build_vms_paper(copies), spot_risk_seed=seed)
    if sc != "none":
        kwargs.update(kh=pr.SCENARIOS[sc]["kh"], kr=pr.SCENARIOS[sc]["kr"])
    row = dict(job=job, sc=sc, seed=seed, key=key, ok=False, error=None)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(Capture, tasks, pr.DEADLINE, **kwargs)
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
        return row
    finally:
        ev.HibernationEvent.execute, rev.ResumeEvent.execute, ev.TaskCompleteEvent.execute = \
            o_hib, o_res, o_done
        lim.LaunchCounter.commit = o_commit

    s = holder["s"]
    launched = set(getattr(getattr(s, "_launches", None), "_ids", {}) or {})
    mk = m.makespan()
    closed = [e for vm in m.vms for _s, e in vm._billing_intervals if e is not None]
    sim_end = max(closed + [mk])

    def union_len(iv):
        tot, cur_s, cur_e = 0.0, None, None
        for a, b in sorted(iv):
            if cur_e is None or a > cur_e:
                if cur_e is not None:
                    tot += cur_e - cur_s
                cur_s, cur_e = a, b
            else:
                cur_e = max(cur_e, b)
        return tot + ((cur_e - cur_s) if cur_e is not None else 0.0)

    cost = {r: 0.0 for r in RULES}
    dec = {}
    for vm in m.vms:
        billed = vm.billed_seconds(sim_end)
        hib_s = sum((b if b is not None else sim_end) - a for a, b in hib.get(vm.id, []))
        was_launched = vm.id in launched
        executed = union_len(busy.get(vm.id, []))
        r = vm.cost_rate
        ebs = EBS_PER_GB_S * (ROOT_GB + vm.memory_gb)
        c0 = r * billed
        ac = sum(r * AC * math.ceil(((e if e is not None else sim_end) - a) / AC)
                 for a, e in vm._billing_intervals if (e if e is not None else sim_end) > a)
        pre2 = r * sum((e if e is not None else mk) - a for a, e in vm._billing_intervals)
        unbilled_launched = (was_launched and not vm._billing_intervals)
        lt = launch_t.get(vm.id, 0.0)
        if not was_launched:
            launch_extra = 0.0
        elif vm._billing_intervals:
            launch_extra = r * max(0.0, vm._billing_intervals[0][0] - lt)
        else:
            launch_extra = r * max(0.0, sim_end - lt)
        phantom = (not was_launched) and billed > 0
        cost["R0"] += c0
        cost["AC"] += ac
        cost["PRE2"] += pre2
        cost["LAUNCH"] += c0 + launch_extra
        cost["NOPHANT"] += 0.0 if phantom else c0
        cost["PAPER"] += (0.0 if phantom else c0) + launch_extra
        cost["EBSHIB"] += c0 + ebs * hib_s
        cost["EBSALL"] += c0 + ebs * (billed + hib_s)
        d = dec.setdefault(vm.market, dict(billed_s=0.0, busy_s=0.0, hib_s=0.0, vms_billed=0,
                                           phantom_s=0.0, phantom_busy_s=0.0, phantom_vms=0,
                                           phantom_cost=0.0, unbilled_launched=0,
                                           launch_gap_cost=0.0, cost=0.0))
        d["billed_s"] += billed
        d["busy_s"] += executed
        d["hib_s"] += hib_s
        d["vms_billed"] += int(billed > 0)
        d["cost"] += c0
        if phantom:
            d["phantom_s"] += billed
            d["phantom_busy_s"] += executed
            d["phantom_vms"] += 1
            d["phantom_cost"] += c0
        d["unbilled_launched"] += int(unbilled_launched)
        d["launch_gap_cost"] += launch_extra
    row.update(ok=True, mk=mk, misses=m.deadline_misses(), sim_end=sim_end,
               cost=cost, dec=dec, metric_cost=m.total_cost(), counts=counts,
               od_launched=sum(1 for v in m.vms if v.id in launched and v.market == VM.ONDEMAND))
    return row


def pct(x, y):
    return 100.0 * (x - y) / y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--variant", default="nocap")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--copies", type=int, default=3)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    import baseline_validation as bv
    from experiments import paper_reproduction as pr

    units = [(j, sc, s, k, a.copies, a.variant) for j in JOBS for sc in SCENARIOS
             for s in range(a.seeds) for k in KEYS]
    print(f"diag_cost_gap '{a.tag}': variant={a.variant}, {len(units)} runs", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(a.workers) as pool:
        rows = list(pool.imap_unordered(run_unit, units, chunksize=2))
    bad = [r for r in rows if not r["ok"]]
    print(f"done in {time.time() - t0:.0f}s; errors {len(bad)}"
          + (f"; first: {bad[0]['error']}" if bad else ""))
    ok = [r for r in rows if r["ok"]]
    mism = sum(1 for r in ok if abs(r["cost"]["R0"] - r["metric_cost"]) > 1e-9)
    print(f"check: R0 equals Metrics.total_cost in {len(ok) - mism}/{len(ok)} runs")

    by = {}
    for r in ok:
        by.setdefault((r["job"], r["sc"], r["key"]), {})[r["seed"]] = r

    def mean_cost(j, sc, k, rule):
        rs = list(by[(j, sc, k)].values())
        return sum(r["cost"][rule] for r in rs) / len(rs)

    def cell_change(j, sc, rule):
        return pct(mean_cost(j, sc, "burst", rule), mean_cost(j, sc, "hads", rule))

    print("\n(a) AGGREGATION under R0 -- Burst-HADS cost change vs HADS over the 20 hibernation cells")
    cells = [cell_change(j, sc, "R0") for j in JOBS for sc in HIB]
    pooled_b = sum(mean_cost(j, sc, "burst", "R0") for j in JOBS for sc in HIB)
    pooled_h = sum(mean_cost(j, sc, "hads", "R0") for j in JOBS for sc in HIB)
    paired = [pct(by[(j, sc, "burst")][s]["cost"]["R0"], by[(j, sc, "hads")][s]["cost"]["R0"])
              for j in JOBS for sc in HIB for s in by[(j, sc, "hads")] if s in by[(j, sc, "burst")]]
    print(f"  mean of per-cell changes   {sum(cells)/len(cells):+7.2f}%   (TCC23 +{bv.T9_TEXT['avg_cost_increase']:.2f}%)")
    print(f"  change of pooled totals    {pct(pooled_b, pooled_h):+7.2f}%")
    print(f"  mean of per-run changes    {sum(paired)/len(paired):+7.2f}%")
    print(f"  median of per-cell changes {median(cells):+7.2f}%")
    print("  per scenario (mean over jobs): " + "  ".join(
        f"{sc} {sum(cell_change(j, sc, 'R0') for j in JOBS)/len(JOBS):+.1f}%" for sc in HIB))
    print("  per job (mean over scenarios): " + "  ".join(
        f"{j} {sum(cell_change(j, sc, 'R0') for sc in HIB)/len(HIB):+.1f}%" for j in JOBS))
    import tcc23_tables as tt

    def mk_red(j, sc):
        mb = sum(r["mk"] for r in by[(j, sc, "burst")].values()) / len(by[(j, sc, "burst")])
        mh = sum(r["mk"] for r in by[(j, sc, "hads")].values()) / len(by[(j, sc, "hads")])
        return 100.0 * (mh - mb) / mh
    print("  makespan reduction vs HADS (Table 9 Diff definition), ours | TCC23: "
          f"avg {sum(mk_red(j, sc) for j in JOBS for sc in HIB) / 20:.2f}|{tt.T9_TEXT['avg_mk_reduction']:.2f}%  "
          f"J60 {sum(mk_red('J60', sc) for sc in HIB) / 5:.2f}|{tt.T9_TEXT['j60_mk_reduction']:.2f}%  "
          f"ED200 {sum(mk_red('ED200', sc) for sc in HIB) / 5:.2f}|{tt.T9_TEXT['ed200_mk_reduction']:.2f}%")
    print("  published, same definition (mean of 20 per-cell changes, from Table 9's printed Diff): "
          f"{-sum(r['diff_hads_cost'] for r in tt.T9.values()) / 20:+.2f}%")
    print("  published per scenario: " + "  ".join(
        f"{sc} {sum(tt.burst_cost_change_vs_hads(j, sc) for j in JOBS) / 4:+.1f}%" for sc in HIB))

    print("\nTABLE 9 CELL BY CELL, R0. cost $ and makespan s, ours (mean of seeds) | TCC23; hib/res per run,"
          " od = on-demand VMs launched")
    print(f"  {'cell':9s} | {'Burst $':>13s} {'Burst mk':>11s} | {'HADS $':>13s} {'HADS mk':>11s} |"
          f" {'B vs H $':>15s} | {'hib (H/B) | T9':>19s} {'res (H/B) | T9':>19s} | {'od B | T9':>11s} {'od H | T9':>11s}")
    for j in JOBS:
        for sc in HIB:
            p = tt.T9[(j, sc)]
            rb, rh = list(by[(j, sc, "burst")].values()), list(by[(j, sc, "hads")].values())
            mm = lambda rs, f: sum(f(r) for r in rs) / len(rs)
            print(f"  {j:5s} {sc} | {mean_cost(j, sc, 'burst', 'R0'):5.3f} | {p['burst_cost']:5.3f}"
                  f" {mm(rb, lambda r: r['mk']):5.0f}|{p['burst_mk']:4d} |"
                  f" {mean_cost(j, sc, 'hads', 'R0'):5.3f} | {p['hads_cost']:5.3f}"
                  f" {mm(rh, lambda r: r['mk']):5.0f}|{p['hads_mk']:4d} |"
                  f" {cell_change(j, sc, 'R0'):+6.1f}|{tt.burst_cost_change_vs_hads(j, sc):+6.1f}% |"
                  f" {mm(rh, lambda r: r['counts']['hib']):4.1f}/{mm(rb, lambda r: r['counts']['hib']):4.1f} | {p['hib']:5.2f}"
                  f"   {mm(rh, lambda r: r['counts']['res']):4.1f}/{mm(rb, lambda r: r['counts']['res']):4.1f} | {p['res']:5.2f} |"
                  f" {mm(rb, lambda r: r['od_launched']):4.2f}|{p['od_burst']:4.2f}"
                  f" {mm(rh, lambda r: r['od_launched']):4.2f}|{p['od_hads']:4.2f}")

    print("\nTABLE 7 (no hibernation), R0: ours | TCC23")
    for j in JOBS:
        rb, rh = list(by[(j, "none", "burst")].values()), list(by[(j, "none", "hads")].values())
        mkb, mkh = sum(r["mk"] for r in rb) / len(rb), sum(r["mk"] for r in rh) / len(rh)
        p = tt.T7[j]
        spot = lambda rs: sum(r["dec"].get("spot", {}).get("vms_billed", 0) for r in rs) / len(rs)
        print(f"  {j:5s} Burst ${mean_cost(j, 'none', 'burst', 'R0'):.3f}|{p['burst'][0]:.3f} mk {mkb:5.0f}|{p['burst'][1]:4d}"
              f"   HADS ${mean_cost(j, 'none', 'hads', 'R0'):.3f}|{p['hads'][0]:.3f} mk {mkh:5.0f}|{p['hads'][1]:4d}"
              f"   mk change {pct(mkb, mkh):+6.1f}|{pct(p['burst'][1], p['hads'][1]):+6.1f}%"
              f"   cost change {cell_change(j, 'none', 'R0'):+6.1f}|{pct(p['burst'][0], p['hads'][0]):+6.1f}%"
              f"   spot VMs billed B {spot(rb):.1f} H {spot(rh):.1f}")

    print("\n  cost under hibernation vs the same scheduler without, mean over jobs, R0 | TCC23 (Table 9 vs Table 7)")
    for k in KEYS:
        print(f"    {k:5s} " + "  ".join(
            f"{sc} {sum(pct(mean_cost(j, sc, k, 'R0'), mean_cost(j, 'none', k, 'R0')) for j in JOBS) / 4:+5.0f}"
            f"|{sum(pct(tt.T9[(j, sc)][k + '_cost'], tt.T7[j][k][0]) for j in JOBS) / 4:+4.0f}%"
            for sc in HIB))

    print("\n(b)(c) BILLING RULES -- Burst-HADS cost change vs HADS, mean of per-cell changes")
    print(f"  {'rule':8s} {'all 20':>8s} " + " ".join(f"{sc:>8s}" for sc in HIB)
          + f" | {'no hib':>8s}   | J60 Burst cost sc/none: " + " ".join(f"{sc:>5s}" for sc in HIB))
    pub_j60 = " ".join(f"{pct(bv.T10_J60_BURST[sc][0], bv.T10_J60_BURST['none'][0]):+4.0f}%" for sc in HIB)
    print(f"  {'TCC23':8s} {'+1.92%':>8s} " + " ".join(f"{'':>8s}" for _ in HIB)
          + f" | {'':>8s}   |                         {pub_j60}")
    summary = {}
    for rule in RULES:
        allc = [cell_change(j, sc, rule) for j in JOBS for sc in HIB]
        per_sc = {sc: sum(cell_change(j, sc, rule) for j in JOBS) / len(JOBS) for sc in HIB}
        nohib = sum(cell_change(j, "none", rule) for j in JOBS) / len(JOBS)
        j60 = {sc: pct(mean_cost("J60", sc, "burst", rule), mean_cost("J60", "none", "burst", rule)) for sc in HIB}
        summary[rule] = dict(avg=sum(allc) / len(allc), per_scenario=per_sc, no_hib=nohib, j60_burst_vs_none=j60)
        print(f"  {rule:8s} {summary[rule]['avg']:+7.2f}% " + " ".join(f"{per_sc[sc]:+7.1f}%" for sc in HIB)
              + f" | {nohib:+7.1f}%   |                         " + " ".join(f"{j60[sc]:+4.0f}%" for sc in HIB))

    print("\n   J60 Burst-HADS absolute cost ($) per scenario, against Table 10 'w/o Fluctuation':")
    print(f"     {'rule':8s} " + " ".join(f"{sc:>7s}" for sc in SCENARIOS))
    print(f"     {'TCC23':8s} " + " ".join(f"{bv.T10_J60_BURST[sc][0]:7.3f}" for sc in SCENARIOS))
    for rule in RULES:
        print(f"     {rule:8s} " + " ".join(f"{mean_cost('J60', sc, 'burst', rule):7.3f}" for sc in SCENARIOS))

    print("\n   HADS cost under hibernation vs HADS without, mean over jobs (rule R0 | PAPER):")
    for sc in HIB:
        r0 = sum(pct(mean_cost(j, sc, "hads", "R0"), mean_cost(j, "none", "hads", "R0")) for j in JOBS) / 4
        pp = sum(pct(mean_cost(j, sc, "hads", "PAPER"), mean_cost(j, "none", "hads", "PAPER")) for j in JOBS) / 4
        print(f"     {sc}: {r0:+6.0f}% | {pp:+6.0f}%")

    print("\nHIBERNATION EVENTS per run (Table 9 reports one '# hibernations' and one '# resumes' column per"
          " job and scenario, and '# used regular on-demand VMs' per framework)")
    print(f"  {'job':5s} {'scen':5s} | {'sched':5s} {'hib':>6s} {'on launched':>11s} {'on busy':>8s} {'resumes':>8s}"
          f" {'od VMs':>7s} | {'sched':5s} {'hib':>6s} {'on launched':>11s} {'on busy':>8s} {'resumes':>8s} {'od VMs':>7s}")
    for j in JOBS:
        for sc in HIB:
            cells = []
            for k in KEYS:
                rs = list(by[(j, sc, k)].values())
                cm = lambda f: sum(r["counts"][f] for r in rs) / len(rs)
                od = sum(r["od_launched"] for r in rs) / len(rs)
                cells.append(f"{k:5s} {cm('hib'):6.2f} {cm('hib_launched'):11.2f} {cm('hib_busy'):8.2f}"
                             f" {cm('res'):8.2f} {od:7.2f}")
            print(f"  {j:5s} {sc:5s} | " + " | ".join(cells))

    print("\nDECOMPOSITION, pooled over jobs and seeds, per run: billed seconds by market; "
          "busy (executing) seconds; hibernated seconds; never-launched VMs billed")
    print(f"  {'sched':5s} {'scen':5s} | {'spot bill':>9s} {'spot busy':>9s} {'spot hib':>9s} | "
          f"{'burst bill':>10s} {'burst busy':>10s} {'unbilled launched':>17s} | {'od bill':>8s} | "
          f"{'phantom VMs':>11s} {'phantom s':>9s} {'ph. busy s':>10s} {'phantom $ share':>15s} "
          f"{'launch-gap $ share':>18s}")
    decomp = {}
    for k in KEYS:
        for sc in SCENARIOS:
            rs = [r for r in ok if r["key"] == k and r["sc"] == sc]
            n = len(rs)
            g = lambda mkt, f: sum(r["dec"].get(mkt, {}).get(f, 0.0) for r in rs) / n
            ph_cost = sum(sum(d["phantom_cost"] for d in r["dec"].values()) for r in rs)
            lg_cost = sum(sum(d["launch_gap_cost"] for d in r["dec"].values()) for r in rs)
            tot = sum(r["cost"]["R0"] for r in rs)
            row = dict(spot_bill=g("spot", "billed_s"), spot_busy=g("spot", "busy_s"), spot_hib=g("spot", "hib_s"),
                       burst_bill=g("burstable", "billed_s"), burst_busy=g("burstable", "busy_s"),
                       unbilled_launched=g("burstable", "unbilled_launched"),
                       od_bill=g("ondemand", "billed_s"),
                       phantom_vms=sum(g(mk_, "phantom_vms") for mk_ in ("spot", "burstable", "ondemand")),
                       phantom_s=sum(g(mk_, "phantom_s") for mk_ in ("spot", "burstable", "ondemand")),
                       phantom_busy_s=sum(g(mk_, "phantom_busy_s") for mk_ in ("spot", "burstable", "ondemand")),
                       phantom_share=100 * ph_cost / tot if tot else 0.0,
                       launch_gap_share=100 * lg_cost / tot if tot else 0.0)
            decomp[f"{k} {sc}"] = row
            print(f"  {k:5s} {sc:5s} | {row['spot_bill']:9.0f} {row['spot_busy']:9.0f} {row['spot_hib']:9.0f} | "
                  f"{row['burst_bill']:10.0f} {row['burst_busy']:10.0f} {row['unbilled_launched']:17.1f} | "
                  f"{row['od_bill']:8.0f} | {row['phantom_vms']:11.2f} {row['phantom_s']:9.0f} "
                  f"{row['phantom_busy_s']:10.0f} {row['phantom_share']:14.1f}% {row['launch_gap_share']:17.1f}%")

    out = HERE / f"diag_cost_gap_{a.tag}.json"
    json.dump(dict(tag=a.tag, variant=a.variant, seeds=a.seeds, copies=a.copies,
                   summary=summary, decomposition=decomp, rows=rows), open(out, "w"), indent=1)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
