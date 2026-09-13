"""
Baseline validation against Teylo et al., "Scheduling Bag-of-Tasks in
Clouds Using Spot and Burstable Virtual Machines", IEEE TCC 11(1), 2023.

WHY THIS REPLACES table10_validation.py. Reading the paper's text showed the
earlier validation compared against a mislabelled target set:
  - the per-job makespan reductions 44.37 / 42.09 / 28.82 / 11.82 % come from
    the paper's Table 7, WITHOUT hibernation (their paired cost increases
    are +66.34 / +44.54 / +57.55 / +33.71 %), but were compared against an
    average over the hibernation scenarios sc1-sc5;
  - the +1.92 % average cost increase is over the hibernation runs (Table 9);
  - the paper's Table 10 is a 20 % runtime-fluctuation experiment on J60;
    its "w/o Fluctuation" Burst-HADS column is the source of two of the old
    cells;
  - paper_reproduction.py's table numbers are wrong: the VM catalogue is
    Table 3, the jobs Table 6, the scenarios Table 8.

PUBLISHED TARGETS (read from the paper's text; table numbers as printed):
  T7   no hibernation, cost and makespan, Burst-HADS and HADS, all four jobs
  T10  "w/o Fluctuation", Burst-HADS on J60: no hibernation and sc1-sc5
  T9   Section 4's text on the hibernation comparison: Burst-HADS makespan
       reduction vs HADS averages 25.87 % over all executions, 40.10 % for
       J60 and 10.24 % for ED200; Burst-HADS cost increase averages 1.92 %
  OLD  paper_reproduction.PAPER's HADS values (e.g. J60 sc1 $0.091 / 2620 s)
       are said to come from Table 9, whose body did not survive text
       extraction. Reported, flagged as not re-verified.

PROTOCOL. Catalogue (Table 3), D = 2700 s, scenarios (Table 8) and Alg. 1
parameters come from experiments/paper_reproduction.py. Seed s generates
the task set and the Table 8 event stream, identically for both schedulers.
--workload chooses the job generator:
  uniform  paper_reproduction.gen_job: runtime and memory uniform over
           Table 6's [min, max]. Its means exceed Table 6's stated averages:
           runtime +7 % (J60), +7 % (J80), +15 % (J100), +22 % (ED200).
  table6   runtime and memory from a Beta(2, b) scaled to Table 6's
           [min, max], with b chosen so the mean equals Table 6's stated
           average (ED200 memory bounds 153.74-177.77 MB, as in Table 6).

Usage (from the project root):
    python experiments\\baseline_validation.py --tag NAME --workload table6
"""

import sys, os, io, json, math, time, random, argparse, contextlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PROJ = HERE.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

KEYS = ("hads", "burst")
SCENARIOS = ["none", "sc1", "sc2", "sc3", "sc4", "sc5"]
JOB_ORDER = ["J60", "J80", "J100", "ED200"]

# Table 6: (n, runtime min/avg/max s, memory min/avg/max MB)
TABLE6 = {
    "J60":   (60,  (102, 198, 323), (2.85, 4.69, 12.20)),
    "J80":   (80,  (103, 199, 322), (2.91, 4.71, 13.19)),
    "J100":  (100, (107, 190, 330), (2.81, 4.49, 10.86)),
    "ED200": (200, (161, 211, 354), (153.74, 168.68, 177.77)),
}
# Table 7, no hibernation: (cost $, makespan s)
T7 = {
    "J60":   dict(burst=(0.112, 1274), hads=(0.067, 2290)),
    "J80":   dict(burst=(0.151, 1329), hads=(0.104, 2295)),
    "J100":  dict(burst=(0.176, 1660), hads=(0.112, 2332)),
    "ED200": dict(burst=(0.357, 2275), hads=(0.267, 2580)),
}
T7_TEXT_MK_REDUCTION = {"J60": 44.37, "J80": 42.09, "J100": 28.82, "ED200": 11.82}
T7_TEXT_COST_INCREASE = {"J60": 66.34, "J80": 44.54, "J100": 57.55, "ED200": 33.71}
# Table 10, "w/o Fluctuation", Burst-HADS on J60
T10_J60_BURST = {"none": (0.112, 1274), "sc1": (0.119, 1274), "sc2": (0.204, 1277),
                 "sc3": (0.127, 1752), "sc4": (0.142, 1857), "sc5": (0.150, 1445)}
# Section 4 text on Table 9
T9_TEXT = dict(avg_mk_reduction=25.87, j60_mk_reduction=40.10,
               ed200_mk_reduction=10.24, avg_cost_increase=1.92)

_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
         7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131,
         20: 2.086, 25: 2.060, 29: 2.045, 30: 2.042, 40: 2.021, 60: 2.000}


def t975(df):
    for k in sorted(_T975):
        if df <= k:
            return _T975[k]
    return 1.96


def mean_ci(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n == 0:
        return None, None, 0
    m = sum(xs) / n
    if n == 1:
        return m, float("nan"), 1
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, t975(n - 1) * sd / math.sqrt(n), n


def _beta_b(lo, avg, hi, a=2.0):
    f = (avg - lo) / (hi - lo)
    return a * (1.0 - f) / f


def gen_table6(job, seed):
    """Task set whose runtime and memory means equal Table 6's averages."""
    from models.task import Task
    n, (rlo, ravg, rhi), (mlo, mavg, mhi) = TABLE6[job]
    br, bm = _beta_b(rlo, ravg, rhi), _beta_b(mlo, mavg, mhi)
    random.seed(seed)
    tasks = []
    for i in range(n):
        rt = int(round(rlo + (rhi - rlo) * random.betavariate(2.0, br)))
        mem = mlo + (mhi - mlo) * random.betavariate(2.0, bm)
        tasks.append(Task(i, job_id=0, stage_id=0, exec_time=rt, memory_req=mem))
    return tasks


def run_unit(args):
    job, sc, seed, key, copies, workload = args
    if str(_PROJ) not in sys.path:
        sys.path.insert(0, str(_PROJ))
    from experiments import paper_reproduction as pr
    from main import run_simulation
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    try:
        from models.limits import NoFeasibleSchedule
    except ImportError:
        class NoFeasibleSchedule(Exception):
            pass

    cls = {"hads": HADS, "burst": BurstHADS}[key]
    tasks = (gen_table6(job, seed) if workload == "table6"
             else pr.gen_job(pr.JOBS[job], seed))
    kwargs = dict(vm_builder=lambda: pr.build_vms_paper(copies), spot_risk_seed=seed)
    if sc != "none":
        kwargs.update(kh=pr.SCENARIOS[sc]["kh"], kr=pr.SCENARIOS[sc]["kr"])
    row = dict(job=job, sc=sc, seed=seed, key=key, ok=False, infeasible=False,
               error=None, mean_runtime=sum(t.exec_time for t in tasks) / len(tasks))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(cls, tasks, pr.DEADLINE, **kwargs)
        r = m.summary()
        row.update(ok=True, cost=r["total_cost"], mk=r["makespan"],
                   misses=r["deadline_misses"])
    except NoFeasibleSchedule as e:
        row.update(infeasible=True, error=str(e))
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
    return row


def pct(x, y):
    return 100.0 * (x - y) / y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--workload", choices=("uniform", "table6"), required=True)
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--copies", type=int, default=3)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    units = [(j, sc, s, k, a.copies, a.workload) for j in JOB_ORDER
             for sc in SCENARIOS for s in range(a.seeds) for k in KEYS]
    print(f"baseline validation '{a.tag}': workload={a.workload}, {a.seeds} seeds, "
          f"{a.copies} copies per spot type, {len(units)} runs", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(a.workers) as pool:
        rows = list(pool.imap_unordered(run_unit, units, chunksize=2))
    bad = [r for r in rows if not r["ok"] and not r["infeasible"]]
    print(f"done in {time.time() - t0:.0f}s; infeasible {sum(r['infeasible'] for r in rows)}, "
          f"errors {len(bad)}" + (f"; first: {bad[0]['error']}" if bad else ""))

    by = {}
    for r in rows:
        by.setdefault((r["job"], r["sc"], r["key"]), {})[r["seed"]] = r

    cells = {}
    for j in JOB_ORDER:
        for sc in SCENARIOS:
            c = {}
            for k in KEYS:
                rs = [r for r in by[(j, sc, k)].values() if r["ok"]]
                mk, mk_ci, n = mean_ci([r["mk"] for r in rs])
                co, co_ci, _ = mean_ci([r["cost"] for r in rs])
                c[k] = dict(mk=mk, mk_ci=mk_ci, cost=co, cost_ci=co_ci, n=n,
                            misses=(sum(r["misses"] for r in rs) / n) if n else None,
                            infeasible=sum(r["infeasible"] for r in by[(j, sc, k)].values()))
            h, b = by[(j, sc, "hads")], by[(j, sc, "burst")]
            common = [s for s in h if h[s]["ok"] and b[s]["ok"]]
            m_, ci_, _ = mean_ci([pct(b[s]["mk"], h[s]["mk"]) for s in common])
            cm_, cci_, _ = mean_ci([pct(b[s]["cost"], h[s]["cost"]) for s in common])
            c["paired_mk_change"] = (m_, ci_)
            c["paired_cost_change"] = (cm_, cci_)
            if c["hads"]["n"] and c["burst"]["n"]:
                c["mk_change"] = pct(c["burst"]["mk"], c["hads"]["mk"])
                c["cost_change"] = pct(c["burst"]["cost"], c["hads"]["cost"])
            cells[f"{j} {sc}"] = c

    f = lambda x, d=1: "n/a" if x is None or x != x else f"{x:.{d}f}"
    summary = {}

    print("\nT7  NO HIBERNATION vs paper Table 7 (ours mean +/- 95% CI | published)")
    print(f"  {'job':6s} | {'HADS mk':>18s} {'HADS $':>18s} | {'Burst mk':>18s} {'Burst $':>18s} | "
          f"{'mk change (paired)':>26s} | {'cost change (paired)':>28s}")
    t7 = {}
    for j in JOB_ORDER:
        c = cells[f"{j} none"]
        h, b = c["hads"], c["burst"]
        pm, pc = c["paired_mk_change"], c["paired_cost_change"]
        t7[j] = dict(hads_mk=h["mk"], hads_mk_pub=T7[j]["hads"][1],
                     hads_cost=h["cost"], hads_cost_pub=T7[j]["hads"][0],
                     burst_mk=b["mk"], burst_mk_pub=T7[j]["burst"][1],
                     burst_cost=b["cost"], burst_cost_pub=T7[j]["burst"][0],
                     mk_change=pm[0], mk_change_ci=pm[1], mk_change_pub=-T7_TEXT_MK_REDUCTION[j],
                     cost_change=pc[0], cost_change_ci=pc[1], cost_change_pub=T7_TEXT_COST_INCREASE[j])
        print(f"  {j:6s} | {f(h['mk'],0):>6s}+/-{f(h['mk_ci'],0):>4s} |{T7[j]['hads'][1]:5d} "
              f"{f(h['cost'],3):>6s}+/-{f(h['cost_ci'],3):>5s}|{T7[j]['hads'][0]:.3f} | "
              f"{f(b['mk'],0):>6s}+/-{f(b['mk_ci'],0):>4s} |{T7[j]['burst'][1]:5d} "
              f"{f(b['cost'],3):>6s}+/-{f(b['cost_ci'],3):>5s}|{T7[j]['burst'][0]:.3f} | "
              f"{f(pm[0]):>7s}+/-{f(pm[1]):>5s}% | {-T7_TEXT_MK_REDUCTION[j]:+7.2f}% | "
              f"{f(pc[0]):>7s}+/-{f(pc[1]):>5s}% | {T7_TEXT_COST_INCREASE[j]:+7.2f}%")
    summary["T7"] = t7

    print("\nT10 J60 BURST-HADS, 'w/o Fluctuation' (ours mean +/- 95% CI | published)")
    t10 = {}
    for sc in SCENARIOS:
        b = cells[f"J60 {sc}"]["burst"]
        pc_, pm_ = T10_J60_BURST[sc]
        t10[sc] = dict(mk=b["mk"], mk_ci=b["mk_ci"], mk_pub=pm_,
                       cost=b["cost"], cost_ci=b["cost_ci"], cost_pub=pc_)
        print(f"  {sc:5s} makespan {f(b['mk'],0):>6s} +/-{f(b['mk_ci'],0):>4s} | {pm_:5d}   "
              f"cost {f(b['cost'],3):>6s} +/-{f(b['cost_ci'],3):>5s} | {pc_:.3f}")
    summary["T10_J60_burst"] = t10

    print("\nT9  HIBERNATION AGGREGATES vs Section 4 text (sc1-sc5)")
    hib = [cells[f"{j} {sc}"] for j in JOB_ORDER for sc in SCENARIOS[1:]]
    avg_red = -sum(c["mk_change"] for c in hib if "mk_change" in c) / len(hib)
    j60_red = -sum(cells[f"J60 {sc}"]["mk_change"] for sc in SCENARIOS[1:]) / 5
    ed_red = -sum(cells[f"ED200 {sc}"]["mk_change"] for sc in SCENARIOS[1:]) / 5
    avg_cost = sum(c["cost_change"] for c in hib if "cost_change" in c) / len(hib)
    summary["T9_text"] = dict(avg_mk_reduction=avg_red, j60_mk_reduction=j60_red,
                              ed200_mk_reduction=ed_red, avg_cost_increase=avg_cost)
    print(f"  average makespan reduction  ours {avg_red:6.2f}%  published {T9_TEXT['avg_mk_reduction']:.2f}%")
    print(f"  J60 makespan reduction      ours {j60_red:6.2f}%  published {T9_TEXT['j60_mk_reduction']:.2f}%")
    print(f"  ED200 makespan reduction    ours {ed_red:6.2f}%  published {T9_TEXT['ed200_mk_reduction']:.2f}%")
    print(f"  average cost increase       ours {avg_cost:+6.2f}%  published +{T9_TEXT['avg_cost_increase']:.2f}%")

    print("\nOLD cells (HADS values from Table 9's image, NOT re-verified from text)")
    from experiments import paper_reproduction as pr
    old = {}
    for (j, sc), pk in pr.PAPER.items():
        c = cells[f"{j} {sc}"]
        old[f"{j} {sc}"] = dict(hads_mk=c["hads"]["mk"], hads_mk_pub=pk["hads"][1],
                                burst_mk=c["burst"]["mk"], burst_mk_pub=pk["burst"][1],
                                mk_change=c.get("mk_change"),
                                mk_change_pub=pct(pk["burst"][1], pk["hads"][1]),
                                cost_change=c.get("cost_change"),
                                cost_change_pub=pct(pk["burst"][0], pk["hads"][0]))
        o = old[f"{j} {sc}"]
        print(f"  {j+' '+sc:10s} HADS mk {f(o['hads_mk'],0):>5s}|{o['hads_mk_pub']}  Burst mk "
              f"{f(o['burst_mk'],0):>5s}|{o['burst_mk_pub']}  mk change {f(o['mk_change'])}%|"
              f"{o['mk_change_pub']:+.1f}%  cost change {f(o['cost_change'])}%|{o['cost_change_pub']:+.1f}%")
    summary["OLD"] = old

    mr = {j: sum(r["mean_runtime"] for r in rows if r["job"] == j) /
             sum(1 for r in rows if r["job"] == j) for j in JOB_ORDER}
    print("\nmean task runtime generated vs Table 6: " + ", ".join(
        f"{j} {mr[j]:.0f}|{TABLE6[j][1][1]}" for j in JOB_ORDER))
    summary["mean_runtime"] = mr

    out = HERE / f"baseline_validation_{a.tag}.json"
    json.dump(dict(tag=a.tag, workload=a.workload, seeds=a.seeds, copies=a.copies,
                   summary=summary, cells=cells, rows=rows), open(out, "w"), indent=1)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
