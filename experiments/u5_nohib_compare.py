"""
The U5 guard with and without hibernation (experiments/u5_nohib_plan.md §1).
Reads committed sweep files only.

    python experiments\\u5_nohib_compare.py > experiments\\u5_nohib_compare.txt
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import results_pack as rp

FP = "2439a00d7f74"


def merged(base_rel, var_rel):
    d = rp.load_jsonl(base_rel)
    d.update(rp.load_jsonl(var_rel))
    return d


SETS = {
    "Table 9 scenarios, guard kept": rp.load_jsonl(f"experiments/sweep_raw_{FP}.jsonl"),
    "Table 9 scenarios, guard removed": merged(f"experiments/sweep_raw_{FP}.jsonl", f"experiments/sweep_variant_burst_fill_{FP}.jsonl"),
    "no hibernation, guard kept": rp.load_jsonl(f"experiments/sweep_variant_u5nohib_kept_{FP}.jsonl"),
    "no hibernation, guard removed": rp.load_jsonl(f"experiments/sweep_variant_u5nohib_removed_{FP}.jsonl"),
}
DFS = (0.25, 0.5, 1.0, 2.0)

print(f"# The U5 guard with and without hibernation, freeze-fix21 `{FP}`, sweep catalogue, limits on, seeds 0–29\n")
print("Table 9 scenarios: sc1–sc5 (guard-removed Burst-HADS and R-BurstHADS rows from sweep_variant_burst_fill). "
      "No hibernation: scenario `none`, no hibernation or resumption events (sweep_variant_u5nohib_{kept,removed}).")

for k in rp.KEYS:
    print(f"\n## {rp.LAB[k]}")
    print("| set | runs | infeasible | runs with a miss | share | missed tasks | mean mk / D | runs with a miss by DF 0.25 / 0.5 / 1.0 / 2.0 (of runs per DF) |")
    print("|---|---|---|---|---|---|---|---|")
    for name, d in SETS.items():
        rs = [(u, r) for u, r in d.items() if u[4] == k]
        fe = [(u, r) for u, r in rs if rp.ok(r)]
        miss = [(u, r) for u, r in fe if r["misses"] > 0]
        bydf = " / ".join(f"{sum(1 for u, _ in miss if u[2] == df)}/{sum(1 for u, _ in rs if u[2] == df)}" for df in DFS)
        print(f"| {name} | {len(rs)} | {sum(1 for _, r in rs if r.get('infeasible'))} | {len(miss)} | "
              f"{100 * len(miss) / len(rs):.1f}% | {sum(r['misses'] for _, r in fe)} | "
              f"{rp.mean(r['mk_frac'] for _, r in fe):.3f} | {bydf} |")

COLS = [("cells", "cells", "d"), ("B mk vs H", "bmk", "%"), ("B $ vs H", "bc", "%"), ("R mk vs H", "rmk", "%"),
        ("R $ vs H", "rc", "%"), ("R mk vs B", "rbmk", "%"), ("R $ vs B", "rbc", "%"), ("R dominates B", "dom", "d")]
print("\n## Cell aggregates (cells where every scheduler is feasible in every seed of that set)")
print("| set | group | " + " | ".join(c[0] for c in COLS) + " |")
print("|---|---|" + "---|" * len(COLS))
for name, d in SETS.items():
    c = rp.cells_of(d)
    comp = sorted(x for x, s in c.items() if rp.complete(s))
    stats = {x: rp.cell_stats(c[x]) for x in comp}
    for label, sel in [("all", comp)] + [(f"DF {df}", [x for x in comp if x[2] == df]) for df in DFS]:
        if not sel:
            continue
        g = rp.group_row(stats, sel)
        vals = [f"{g[key]:+.2f}%" if f == "%" else str(g[key]) for _, key, f in COLS]
        print(f"| {name} | {label} | " + " | ".join(vals) + " |")
