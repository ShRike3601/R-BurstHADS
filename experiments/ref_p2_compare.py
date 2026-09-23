"""
The U5 sensitivity table (experiments/ref_p2_plan.md): as frozen, the guard
removed only, the missing §3.2 step alone, and §3.2 followed in full.
Reads committed sweep files only.

    python experiments\\ref_p2_compare.py > experiments\\ref_p2_compare.txt
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import results_pack as rp

FP = "2439a00d7f74"
BASE = {"on": f"experiments/sweep_raw_{FP}.jsonl", "off": f"experiments/sweep_variant_nocap_{FP}.jsonl"}
# label -> variant file stem per limit setting ("" = the baseline itself)
CONFIGS = [
    ("as frozen (the U5 guard, no step 2)", {"on": "", "off": ""}),
    ("guard removed only (neither ours nor TCC23's)", {"on": "burst_fill", "off": "nocap+burst_fill"}),
    ("the missing step alone (guard kept, maximal reading)", {"on": "p2_od", "off": "nocap+p2_od"}),
    ("reference-faithful: TCC23 §3.2 in full", {"on": "ref_p2", "off": "nocap+ref_p2"}),
]
COPIES = {"on": "p2_copy", "off": "nocap+p2_copy"}


def load(lim, stem):
    d = rp.load_jsonl(BASE[lim])
    if stem:
        d.update(rp.load_jsonl(f"experiments/sweep_variant_{stem}_{FP}.jsonl"))
    return d


SETS = {(lab, lim): load(lim, stems[lim]) for lab, stems in CONFIGS for lim in ("on", "off")}
CELLS = {k: (lambda c: ({x for x, s in c.items() if rp.complete(s)}, c))(rp.cells_of(d)) for k, d in SETS.items()}
MATCHED = set.intersection(*(s for s, _ in CELLS.values()))

print(f"# The U5 sensitivity table, freeze-fix21 `{FP}`, sweep catalogue, seeds 0–29\n")
print("Pre-registration `experiments/ref_p2_plan.md`. Burst-HADS and R-BurstHADS rows of a variant set come from "
      "its sweep file; HADS rows from the baselines. §3.2 step 2 sends Dspot violators the burstables did not take "
      "to the cheapest regular on-demand VMs.")

print("\n## Fidelity: the copy with step 2 switched off, against the baseline (exact)")
for lim, stem in COPIES.items():
    try:
        cp = rp.load_jsonl(f"experiments/sweep_variant_{stem}_{FP}.jsonl")
    except FileNotFoundError:
        print(f"- limits {lim} (`{stem}`): file missing")
        continue
    base = rp.load_jsonl(BASE[lim])
    print(f"- limits {lim} (`{stem}`): {sum(1 for u in cp if rp._same_row(cp[u], base[u], exact=True))}/{len(cp)} rows identical")

COLS = [("cells", "cells", "d"), ("R mk vs B", "rbmk", "%"), ("R $ vs B", "rbc", "%"), ("R dominates B", "dom", "d"),
        ("R sig. faster / slower", ("fast", "slow"), "p"), ("R sig. cheaper / dearer", ("cheap", "dear"), "p"),
        ("B mk vs H", "bmk", "%"), ("B $ vs H", "bc", "%"), ("R mk vs H", "rmk", "%"), ("R $ vs H", "rc", "%")]


def row(label, d, cells):
    cells = sorted(cells)
    if not cells:
        return f"| {label} | 0 |" + " — |" * (len(COLS) - 1)
    g = rp.group_row({k: rp.cell_stats(rp.cells_of(d)[k]) for k in cells}, cells)
    vals = [f"{g[k]:+.2f}%" if f == "%" else f"{g[k[0]]} / {g[k[1]]}" if f == "p" else str(g[k]) for _, k, f in COLS]
    return f"| {label} | " + " | ".join(vals) + " |"


for scope, title in (("own", "each set's own complete cells"), ("matched", f"the {len(MATCHED)} cells complete in every set")):
    for lim in ("on", "off"):
        print(f"\n## Limits {lim}, over {title}")
        print("| configuration | " + " | ".join(c[0] for c in COLS) + " |")
        print("|---|" + "---|" * len(COLS))
        for lab, _ in CONFIGS:
            d = SETS[(lab, lim)]
            print(row(lab, d, CELLS[(lab, lim)][0] if scope == "own" else MATCHED))

print("\n## Deadline behaviour per scheduler (all runs of the set, not only complete cells)")
print("| configuration | limits | scheduler | infeasible runs | runs with a miss | missed tasks | runs changed vs as frozen |")
print("|---|---|---|---|---|---|---|")
for lab, _ in CONFIGS:
    for lim in ("on", "off"):
        d, base = SETS[(lab, lim)], SETS[(CONFIGS[0][0], lim)]
        for k in rp.KEYS:
            rs = {u: r for u, r in d.items() if u[4] == k}
            fe = [r for r in rs.values() if rp.ok(r)]
            ch = "—" if lab == CONFIGS[0][0] else f"{sum(1 for u in rs if not rp._same_row(rs[u], base[u]))}/{len(rs)}"
            print(f"| {lab} | {lim} | {rp.LAB[k]} | {sum(1 for r in rs.values() if r.get('infeasible'))} | "
                  f"{sum(1 for r in fe if r['misses'])} | {sum(r['misses'] for r in fe)} | {ch} |")

print("\n## By DF, limits on, over each set's own complete cells")
print("| configuration | DF | " + " | ".join(c[0] for c in COLS) + " |")
print("|---|---|" + "---|" * len(COLS))
for lab, _ in CONFIGS:
    d, (comp, _) = SETS[(lab, "on")], CELLS[(lab, "on")]
    for df in (0.25, 0.5, 1.0, 2.0):
        print(row(f"{lab} | DF {df}", d, {c for c in comp if c[2] == df}))
