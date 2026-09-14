"""
Fix 17 and the two side measurements, against the frozen sweep (limits on).

    python experiments\\fix17_compare.py TAG [TAG ...]   -> stdout

Reads experiments/sweep_raw_4f08f48ac35c.jsonl (frozen, never written) and
experiments/sweep_variant_<TAG>_4f08f48ac35c.jsonl. A variant file may hold only
some schedulers (variant_sweep --keys); the others are taken from the frozen
file. Aggregates use results_pack.py's own functions (ratio of cell means,
averaged over the cells where every scheduler is feasible in every seed).
"""
import sys
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import results_pack as rp

FP = "4f08f48ac35c"
KEYS = ("hads", "burst", "rburst")
LAB = {"hads": "HADS", "burst": "Burst-HADS", "rburst": "R-BurstHADS"}


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def pct(a, b):
    return 100.0 * (a - b) / b


def load(tag):
    base = rp.load_jsonl(f"experiments/sweep_raw_{FP}.jsonl")
    if tag == "frozen":
        return base, {}
    var = rp.load_jsonl(f"experiments/sweep_variant_{tag}_{FP}.jsonl")
    d = dict(base)
    d.update(var)
    return d, var


def same(a, b):
    if bool(a.get("infeasible")) != bool(b.get("infeasible")) or a.get("error") != b.get("error"):
        return False
    if a.get("infeasible"):
        return True
    return (abs(a["mk"] - b["mk"]) < 1e-9 and abs(a["cost"] - b["cost"]) < 1e-12 and a["misses"] == b["misses"])


def main():
    tags = ["frozen"] + sys.argv[1:]
    base = rp.load_jsonl(f"experiments/sweep_raw_{FP}.jsonl")
    miss_cells = sorted({u[:3] for u, r in base.items() if u[4] == "rburst" and rp.ok(r) and r["misses"] > 0})
    data = {t: load(t) for t in tags}

    def lead(sel_cells, title):
        print(f"\n## {title}")
        print("| variant | cells | R $ vs B | R mk vs B | R dominates B | R $ vs H | B $ vs H | R mk vs H | R sig. cheaper / dearer than B |")
        print("|---|---|---|---|---|---|---|---|---|")
        for t in tags:
            d, _ = data[t]
            cells = rp.cells_of(d)
            comp = [c for c in sorted(cells) if rp.complete(cells[c]) and sel_cells(c)]
            g = rp.group_row({c: rp.cell_stats(cells[c]) for c in comp}, comp)
            print(f"| {t} | {g['cells']} | {g['rbc']:+.1f}% | {g['rbmk']:+.1f}% | {g['dom']}/{g['cells']} | {g['rc']:+.1f}% | "
                  f"{g['bc']:+.1f}% | {g['rmk']:+.1f}% | {g['cheap']} / {g['dear']} |")

    def paired(sel_units, title):
        print(f"\n## {title}")
        print("| variant | scheduler | runs changed | missed tasks | runs with a miss | mean makespan change | mean cost change | R provisioned VMs / run | t3.large / c5.xlarge-spot launches / run |")
        print("|---|---|---|---|---|---|---|---|---|")
        for t in tags:
            d, var = data[t]
            for k in KEYS:
                us = [u for u in base if u[4] == k and sel_units(u)]
                if t != "frozen" and not any(u in var for u in us):
                    continue
                both = [u for u in us if rp.ok(base[u]) and rp.ok(d[u])]
                changed = sum(1 for u in us if not same(base[u], d[u]))
                mt = sum(d[u]["misses"] for u in us if rp.ok(d[u]))
                rm = sum(1 for u in us if rp.ok(d[u]) and d[u]["misses"] > 0)
                dmk = mean(pct(d[u]["mk"], base[u]["mk"]) for u in both)
                dc = mean(pct(d[u]["cost"], base[u]["cost"]) for u in both)
                prov = mean((d[u].get("n_provisioned") or 0) for u in us if rp.ok(d[u]))
                t3 = mean((d[u].get("launched") or {}).get("ondemand:t3.large", 0) for u in us if rp.ok(d[u]))
                c5 = mean((d[u].get("launched") or {}).get("spot:c5.xlarge", 0) for u in us if rp.ok(d[u]))
                print(f"| {t} | {LAB[k]} | {changed}/{len(us)} | {mt} | {rm} | {dmk:+.2f}% | {dc:+.2f}% | "
                      f"{prov:.2f} | {t3:.2f} / {c5:.2f} |")

    in_miss = lambda c: c in set(miss_cells)
    print(f"Frozen sweep {FP}; miss-producing cells (frozen R-BurstHADS missed a task): {len(miss_cells)}")
    lead(in_miss, "LEAD — R-BurstHADS vs Burst-HADS, miss-producing cells (limits on)")
    paired(lambda u: in_miss(u[:3]), "Against frozen, miss-producing cells")
    lead(lambda c: True, "LEAD — R-BurstHADS vs Burst-HADS, full sweep (limits on)")
    paired(lambda u: True, "Against frozen, full sweep")


if __name__ == "__main__":
    main()
