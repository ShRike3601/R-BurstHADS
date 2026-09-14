"""
Round A closing grid on the main sweep: guard (U5) on/off x Allocation Cycle
boundaries (E10) off/on, all on the migration fix + billing from launch.

    python experiments\\grid_2x2_sweep.py FP

reads experiments/sweep_variant_grid_<cell>_<FP>.jsonl for cells g1e0, g0e0,
g1e1, g0e1 (g = guard, e = E10) and compares the cells with EACH OTHER on
the units feasible in all four. Decision rules are pre-registered in
experiments/round_a_grid_plan.md.
"""
import sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CELLS = ["g1e0", "g0e0", "g1e1", "g0e1"]
KEYS = ("hads", "burst", "rburst")


def load(fp, cell):
    rows = {}
    for line in open(HERE / f"sweep_variant_grid_{cell}_{fp}.jsonl"):
        r = json.loads(line)
        rows[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = r
    return rows


def ok(r):
    return r is not None and r.get("error") is None and not r.get("infeasible") and "mk" in r


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def transitions(pairs):
    """pairs: iterable of (misses with guard, misses without). Returns
    (guard-protected, guard-harmed): runs 0 -> >=1 and >=1 -> 0."""
    prot = harm = 0
    for on, off in pairs:
        prot += int(on == 0 and off > 0)
        harm += int(on > 0 and off == 0)
    return prot, harm


def validation(tag_on, tag_off):
    """Pre-registered guard rule on diag_cost_gap JSONs (HADS and Burst-HADS only)."""
    def rows(tag):
        d = json.load(open(HERE / f"diag_cost_gap_{tag}.json"))
        return {(r["job"], r["sc"], r["seed"], r["key"]): r for r in d["rows"] if r["ok"]}
    on, off = rows(tag_on), rows(tag_off)
    common = sorted(set(on) & set(off))
    print(f"VALIDATION guard rule: {tag_on} (guard on) vs {tag_off} (guard off), {len(common)} paired runs")
    for k in ("hads", "burst"):
        ks = [u for u in common if u[3] == k]
        p, h = transitions((on[u]["misses"], off[u]["misses"]) for u in ks)
        mt_on, mt_off = sum(on[u]["misses"] for u in ks), sum(off[u]["misses"] for u in ks)
        mk_on, mk_off = mean(on[u]["mk"] for u in ks), mean(off[u]["mk"] for u in ks)
        print(f"  {k:6s} guard-protected {p:4d}  guard-harmed {h:4d}  -> {'NEEDED' if p > h else 'not needed'}"
              f" | missed tasks on {mt_on} off {mt_off} | mean makespan on {mk_on:.0f} s off {mk_off:.0f} s"
              f" ({100 * (mk_off - mk_on) / mk_on:+.1f}%)")


def main():
    if sys.argv[1] == "--validation":
        return validation(sys.argv[2], sys.argv[3])
    fp = sys.argv[1]
    data = {c: load(fp, c) for c in CELLS}
    units = set.intersection(*(set(d) for d in data.values()))
    units = {u for u in units if all(ok(data[c][u]) for c in CELLS)}
    cellkeys = sorted({u[:3] for u in units})
    # a (scenario, n, df) cell counts only if every scheduler and seed is present in every grid cell
    complete = {ck for ck in cellkeys
                if all(all((ck + (s, k)) in units for k in KEYS)
                       for s in {u[3] for u in units if u[:3] == ck})}
    print(f"grid {fp}: {len(units)} feasible units common to all four cells, {len(complete)} complete sweep cells\n")

    groups = [("all", lambda u: True)] + [(f"DF={df}", (lambda d: lambda u: u[2] == d)(df))
                                          for df in sorted({u[2] for u in units})]
    for gname, gf in groups:
        print(f"== {gname}")
        print(f"  {'cell':5s} | {'missed tasks H/B/R':>20s} {'runs w/ miss H/B/R':>20s} | {'mean mk/D H/B/R':>20s} |"
              f" {'mean $ H/B/R':>24s} | {'B vs H $':>8s} {'R vs H $':>8s} {'R vs B $':>8s} {'R vs B mk':>9s} {'R dom B':>8s}")
        for c in CELLS:
            d = data[c]
            us = [u for u in units if gf(u)]
            miss = {k: sum(d[u]["misses"] for u in us if u[4] == k) for k in KEYS}
            runs = {k: sum(1 for u in us if u[4] == k and d[u]["misses"] > 0) for k in KEYS}
            mkd = {k: mean(d[u]["mk_frac"] for u in us if u[4] == k) for k in KEYS}
            cost = {k: mean(d[u]["cost"] for u in us if u[4] == k) for k in KEYS}
            cks = [ck for ck in complete if gf(ck + (0, "hads"))]
            pct = lambda a, b: 100.0 * (a - b) / b
            per = {}
            for ck in cks:
                seeds = sorted({u[3] for u in units if u[:3] == ck})
                m = lambda k, f: mean(d[ck + (s, k)][f] for s in seeds)
                per[ck] = {k: (m(k, "cost"), m(k, "mk")) for k in KEYS}
            bh = mean(pct(v["burst"][0], v["hads"][0]) for v in per.values())
            rh = mean(pct(v["rburst"][0], v["hads"][0]) for v in per.values())
            rb = mean(pct(v["rburst"][0], v["burst"][0]) for v in per.values())
            rbm = mean(pct(v["rburst"][1], v["burst"][1]) for v in per.values())
            dom = sum(1 for v in per.values() if v["rburst"][0] <= v["burst"][0] and v["rburst"][1] <= v["burst"][1])
            print(f"  {c:5s} | {miss['hads']:6d}/{miss['burst']:6d}/{miss['rburst']:6d} {runs['hads']:6d}/{runs['burst']:6d}/{runs['rburst']:6d} |"
                  f" {mkd['hads']:6.3f}/{mkd['burst']:6.3f}/{mkd['rburst']:6.3f} |"
                  f" {cost['hads']:7.4f}/{cost['burst']:7.4f}/{cost['rburst']:7.4f} |"
                  f" {bh:+7.1f}% {rh:+7.1f}% {rb:+7.1f}% {rbm:+8.1f}% {dom:3d}/{len(per):<3d}")
        print()

    print("SWEEP guard rule (pre-registered): g1e1 (guard on) vs g0e1 (guard off), paired by unit")
    for k in ("burst", "rburst", "hads"):
        ks = [u for u in units if u[4] == k]
        on, off = data["g1e1"], data["g0e1"]
        p, h = transitions((on[u]["misses"], off[u]["misses"]) for u in ks)
        mt_on, mt_off = sum(on[u]["misses"] for u in ks), sum(off[u]["misses"] for u in ks)
        mk_on, mk_off = mean(on[u]["mk"] for u in ks), mean(off[u]["mk"] for u in ks)
        verdict = ("NEEDED" if p > h else "not needed") if k != "hads" else "(HADS has no guard; control)"
        print(f"  {k:6s} guard-protected {p:4d}  guard-harmed {h:4d}  -> {verdict}"
              f" | missed tasks on {mt_on} off {mt_off} | mean makespan on {mk_on:.0f} s off {mk_off:.0f} s"
              f" ({100 * (mk_off - mk_on) / mk_on:+.1f}%)")


if __name__ == "__main__":
    main()
