"""
One table across diag_cost_gap runs, against TCC23 Tables 7 and 9.

    python experiments\\diag_cost_gap_compare.py TAG [TAG ...]

reads experiments/diag_cost_gap_<TAG>.json. All numbers use rule R0 (our
billing) unless the column says PAPER. Definitions follow Table 9: per-cell
Burst-HADS vs HADS changes, then plain means over the 20 hibernation cells.
"""

import sys, json, math
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tcc23_tables as tt

JOBS, HIB = tt.JOBS, tt.SCENARIOS


def pct(x, y):
    return 100.0 * (x - y) / y


def load(tag):
    d = json.load(open(HERE / f"diag_cost_gap_{tag}.json"))
    by = {}
    for r in d["rows"]:
        if r["ok"]:
            by.setdefault((r["job"], r["sc"], r["key"]), []).append(r)
    return d, by


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


RULE = "R0"


def stats(by):
    c = lambda j, sc, k, rule=None: mean(r["cost"][rule or RULE] for r in by[(j, sc, k)])
    m = lambda j, sc, k: mean(r["mk"] for r in by[(j, sc, k)])
    h = lambda j, sc, k, f="hib": mean(r["counts"][f] for r in by[(j, sc, k)])
    s = {}
    cells = [(j, sc) for j in JOBS for sc in HIB]
    s["t9_cost"] = mean(pct(c(j, sc, "burst"), c(j, sc, "hads")) for j, sc in cells)
    s["t9_cost_paper"] = mean(pct(c(j, sc, "burst", "PAPER"), c(j, sc, "hads", "PAPER")) for j, sc in cells)
    s["t9_mk"] = mean(-pct(m(j, sc, "burst"), m(j, sc, "hads")) for j, sc in cells)
    s["t9_mk_j60"] = mean(-pct(m("J60", sc, "burst"), m("J60", sc, "hads")) for sc in HIB)
    s["t9_mk_ed200"] = mean(-pct(m("ED200", sc, "burst"), m("ED200", sc, "hads")) for sc in HIB)
    s["rms_cell_cost"] = math.sqrt(mean((pct(c(j, sc, "burst"), c(j, sc, "hads"))
                                         - tt.burst_cost_change_vs_hads(j, sc)) ** 2 for j, sc in cells))
    for k in ("hads", "burst"):
        s[f"prem_{k}"] = mean(pct(c(j, sc, k), c(j, "none", k)) for j, sc in cells)
        s[f"prem_sc_{k}"] = {sc: mean(pct(c(j, sc, k), c(j, "none", k)) for j in JOBS) for sc in HIB}
        s[f"hib_sc_{k}"] = {sc: mean(h(j, sc, k) for j in JOBS) for sc in HIB}
        s[f"hib_{k}"] = {j: mean(h(j, sc, k) for sc in HIB) for j in JOBS}
        s[f"spot_nohib_{k}"] = mean(mean(r["dec"].get("spot", {}).get("vms_billed", 0)
                                         for r in by[(j, "none", k)]) for j in JOBS)
        s[f"od_{k}"] = mean(mean(r["od_launched"] for r in by[(j, sc, k)]) for j, sc in cells)
    s["t7_mk"] = {j: pct(m(j, "none", "burst"), m(j, "none", "hads")) for j in JOBS}
    s["t7_cost"] = {j: pct(c(j, "none", "burst"), c(j, "none", "hads")) for j in JOBS}
    s["t7_burst_mk"] = {j: m(j, "none", "burst") for j in JOBS}
    s["t7_hads_mk"] = {j: m(j, "none", "hads") for j in JOBS}
    return s


def published():
    cells = [(j, sc) for j in JOBS for sc in HIB]
    T9, T7 = tt.T9, tt.T7
    s = dict(t9_cost=tt.T9_TEXT["avg_cost_increase"], t9_cost_paper=float("nan"),
             t9_mk=tt.T9_TEXT["avg_mk_reduction"], t9_mk_j60=tt.T9_TEXT["j60_mk_reduction"],
             t9_mk_ed200=tt.T9_TEXT["ed200_mk_reduction"], rms_cell_cost=0.0)
    for k in ("hads", "burst"):
        s[f"prem_{k}"] = mean(pct(T9[(j, sc)][f"{k}_cost"], T7[j][k][0]) for j, sc in cells)
        s[f"prem_sc_{k}"] = {sc: mean(pct(T9[(j, sc)][f"{k}_cost"], T7[j][k][0]) for j in JOBS) for sc in HIB}
        s[f"hib_sc_{k}"] = {sc: mean(T9[(j, sc)]["hib"] for j in JOBS) for sc in HIB}
        s[f"hib_{k}"] = {j: mean(T9[(j, sc)]["hib"] for sc in HIB) for j in JOBS}
        s[f"spot_nohib_{k}"] = float("nan")
        s[f"od_{k}"] = mean(T9[(j, sc)][f"od_{k}"] for j, sc in cells)
    s["t7_mk"] = {j: pct(T7[j]["burst"][1], T7[j]["hads"][1]) for j in JOBS}
    s["t7_cost"] = {j: pct(T7[j]["burst"][0], T7[j]["hads"][0]) for j in JOBS}
    s["t7_burst_mk"] = {j: T7[j]["burst"][1] for j in JOBS}
    s["t7_hads_mk"] = {j: T7[j]["hads"][1] for j in JOBS}
    return s


def main():
    global RULE
    tags = sys.argv[1:]
    if tags and tags[0].startswith("--rule="):
        RULE = tags.pop(0).split("=", 1)[1]
    print(f"cost rule: {RULE}  (R0 ours; LAUNCH billed from launch; PAPER = LAUNCH without VMs billed"
          f" only via resume, TCC23 section 3.1)\n")
    rows = [("TCC23", published())]
    for t in tags:
        d, by = load(t)
        rows.append((f"{t} (copies {d['copies']})", stats(by)))
    w = max(len(n) for n, _ in rows) + 1

    print("TABLE 9 AGGREGATES (hibernation, 20 cells). cost = Burst-HADS vs HADS, mean of per-cell changes;"
          " rms = per-cell cost change vs Table 9, root mean square")
    print(f"  {'state':{w}s} {'cost ' + RULE:>8s} {'cost PAPER':>10s} {'rms':>6s} | {'mk red':>7s} {'J60':>6s} {'ED200':>6s} |"
          f" {'HADS prem':>9s} {'Burst prem':>10s} | {'od H':>5s} {'od B':>5s}")
    for n, s in rows:
        print(f"  {n:{w}s} {s['t9_cost']:+7.1f}% {s['t9_cost_paper']:+9.1f}% {s['rms_cell_cost']:5.1f} |"
              f" {s['t9_mk']:6.1f}% {s['t9_mk_j60']:5.1f}% {s['t9_mk_ed200']:5.1f}% |"
              f" {s['prem_hads']:+8.0f}% {s['prem_burst']:+9.0f}% | {s['od_hads']:5.2f} {s['od_burst']:5.2f}")
    print("  (prem = cost under hibernation vs the same scheduler without, mean over the 20 cells;"
          " od = regular on-demand VMs launched per run)")

    print("\nHIBERNATION PREMIUM BY SCENARIO: cost under hibernation vs the same scheduler without, mean over jobs;"
          " and hibernations per run, mean over jobs (kh/kr: sc1 1/0, sc2 5/0, sc3 1/5, sc4 5/5, sc5 3/2.5)")
    for k, label in (("hads", "HADS"), ("burst", "Burst-HADS")):
        print(f"  {label}")
        print(f"  {'state':{w}s} " + " ".join(f"{sc:>13s}" for sc in HIB))
        for n, s in rows:
            print(f"  {n:{w}s} " + " ".join(
                f"{s[f'prem_sc_{k}'][sc]:+5.0f}% {s[f'hib_sc_{k}'][sc]:4.1f}h" for sc in HIB))

    print("\nHIBERNATIONS PER RUN, mean over sc1-sc5 (TCC23: one column; ours: HADS / Burst-HADS runs)")
    print(f"  {'state':{w}s} " + " ".join(f"{j:>13s}" for j in JOBS) + f" {'spot VMs billed w/o hib H/B':>28s}")
    for n, s in rows:
        print(f"  {n:{w}s} " + " ".join(f"{s['hib_hads'][j]:6.2f}/{s['hib_burst'][j]:<6.2f}" for j in JOBS)
              + f" {s['spot_nohib_hads']:13.1f}/{s['spot_nohib_burst']:<4.1f}")

    print("\nTABLE 7 (no hibernation). Burst-HADS vs HADS makespan change | cost change; Burst-HADS makespan s")
    print(f"  {'state':{w}s} " + " ".join(f"{j:>24s}" for j in JOBS))
    for n, s in rows:
        print(f"  {n:{w}s} " + " ".join(
            f"{s['t7_mk'][j]:+6.1f}|{s['t7_cost'][j]:+6.1f}% {s['t7_burst_mk'][j]:5.0f}s" for j in JOBS))


if __name__ == "__main__":
    main()
