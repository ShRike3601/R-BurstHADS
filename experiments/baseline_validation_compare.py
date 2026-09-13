"""
Side-by-side view of baseline_validation_<tag>.json files: how the
validation against Teylo et al. (IEEE TCC 2023) moves across code states,
workload generators and pool sizes.

Usage:
    python baseline_validation_compare.py label1=path1.json label2=path2.json ...
"""

import sys, json


def f(x, d=1, sign=False):
    if x is None or x != x:
        return "n/a"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def main():
    states = []
    for arg in sys.argv[1:]:
        label, path = arg.split("=", 1)
        states.append((label, json.load(open(path))))
    if not states:
        raise SystemExit(__doc__)
    W = max(len(l) for l, _ in states) + 2

    print("T7  NO HIBERNATION. Burst-HADS vs HADS, paired per seed (mean +/- 95% CI), and makespans")
    for job in ("J60", "J80", "J100", "ED200"):
        p = states[0][1]["summary"]["T7"][job]
        print(f"\n{job}: published HADS {p['hads_mk_pub']} s ${p['hads_cost_pub']:.3f} | "
              f"Burst {p['burst_mk_pub']} s ${p['burst_cost_pub']:.3f} | makespan "
              f"{p['mk_change_pub']:+.2f}% | cost {p['cost_change_pub']:+.2f}%")
        print(f"  {'state':{W}s} {'HADS mk':>8s} {'HADS $':>7s} {'Burst mk':>9s} {'Burst $':>8s} "
              f"{'mk change':>16s} {'cost change':>17s}")
        for label, st in states:
            t = st["summary"]["T7"][job]
            print(f"  {label:{W}s} {f(t['hads_mk'],0):>8s} {f(t['hads_cost'],3):>7s} "
                  f"{f(t['burst_mk'],0):>9s} {f(t['burst_cost'],3):>8s} "
                  f"{f(t['mk_change'],1,True):>7s} +/-{f(t['mk_change_ci']):>5s}% "
                  f"{f(t['cost_change'],1,True):>7s} +/-{f(t['cost_change_ci']):>5s}%")

    print("\nT10 J60 BURST-HADS makespan / cost, 'w/o Fluctuation'")
    scs = ["none", "sc1", "sc2", "sc3", "sc4", "sc5"]
    pub = states[0][1]["summary"]["T10_J60_burst"]
    print(f"  {'state':{W}s} " + " ".join(f"{sc:>14s}" for sc in scs))
    print(f"  {'published':{W}s} " + " ".join(
        f"{pub[sc]['mk_pub']:>7d}/{pub[sc]['cost_pub']:.3f}" for sc in scs))
    for label, st in states:
        t = st["summary"]["T10_J60_burst"]
        print(f"  {label:{W}s} " + " ".join(
            f"{f(t[sc]['mk'],0):>7s}/{f(t[sc]['cost'],3)}" for sc in scs))

    print("\nT9  HIBERNATION AGGREGATES (Section 4 text)")
    keys = [("avg_mk_reduction", "avg mk red.", 25.87), ("j60_mk_reduction", "J60 mk red.", 40.10),
            ("ed200_mk_reduction", "ED200 mk red.", 10.24), ("avg_cost_increase", "avg cost incr.", 1.92)]
    print(f"  {'state':{W}s} " + " ".join(f"{k[1]:>15s}" for k in keys))
    print(f"  {'published':{W}s} " + " ".join(f"{k[2]:>14.2f}%" for k in keys))
    for label, st in states:
        t = st["summary"]["T9_text"]
        print(f"  {label:{W}s} " + " ".join(f"{f(t[k[0]],2):>14s}%" for k in keys))

    print("\nRUNS")
    for label, st in states:
        rows = st["rows"]
        mr = st["summary"]["mean_runtime"]
        print(f"  {label:{W}s} workload {st['workload']:7s} copies {st['copies']} seeds {st['seeds']} "
              f"infeasible {sum(r['infeasible'] for r in rows)} errors "
              f"{sum(1 for r in rows if not r['ok'] and not r['infeasible'])} | mean runtime "
              + " ".join(f"{j} {mr[j]:.0f}" for j in ("J60", "J80", "J100", "ED200")))


if __name__ == "__main__":
    main()
