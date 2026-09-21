"""
DEVIATIONS U3 (Burst-HADS Phase 3, inherited by R-BurstHADS) on freeze-fix21,
from existing data only (experiments/u5_nohib_plan.md §2).

The reference IPDPS.py raises "THERE IS NO SOLUTION WITH THAT DEADLINE" where
our _initial_solution reaches Phase 3. The initial solution is a deterministic
greedy pass that runs first, so a REF-faithful Burst-HADS (and R-BurstHADS,
which shares the primary schedule) would be infeasible in exactly the runs
whose primary schedule placed a task through Phase 3. The evaluation drops a
cell with any infeasible seed, so the REF-faithful comparison is the frozen
comparison over the cells with no such run.

Phase-3 runs come from the launch probe diag_launch21_adopted.json (limits on).
Limits off was not probed; the limits-on units are applied as a proxy there.

    python experiments\\u3_exposure.py > experiments\\u3_exposure.txt
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import results_pack as rp

FP = "2439a00d7f74"
d = json.load(open(HERE / "diag_launch21_adopted.json"))


def phase3(e):
    return sum(c[0] for s, c in e["sites"]
               if s[1] == "primary" and s[3] == "ondemand" and "Phase" in s[4]) > 0


ph3 = {tuple(e["unit"]) for e in d if phase3(e)}
print(f"# U3 exposure and its REF-faithful counterfactual, freeze-fix21 `{FP}`\n")
for k in rp.KEYS:
    us = [u for u in ph3 if u[4] == k]
    bydf = " / ".join(str(sum(1 for u in us if u[2] == df)) for df in (0.25, 0.5, 1.0, 2.0))
    note = " (HADS's Phase (c) follows CCScheduler.create_primary_map; shown for comparison)" if k == "hads" else ""
    print(f"- {rp.LAB[k]}: primary schedule uses its on-demand phase in {len(us)} of 2400 runs; by DF 0.25 / 0.5 / 1.0 / 2.0: {bydf}{note}")
b = {u[:4] for u in ph3 if u[4] == "burst"}
r = {u[:4] for u in ph3 if u[4] == "rburst"}
print(f"- Burst-HADS and R-BurstHADS use it in the same units: {b == r}")
floor = [u for u in ph3 if u[4] == "burst" and u[1] == 100 and u[2] == 0.25]
print(f"- floor cells (n = 100, DF = 0.25): Burst-HADS uses it in {len(floor)} of 150 runs")

ph3cells = {u[:3] for u in ph3 if u[4] in ("burst", "rburst")}
print("\n| limits | comparison | cells | cells by DF 0.25 / 0.5 / 1.0 / 2.0 | B mk vs H | B $ vs H | R mk vs H | R $ vs H | "
      "R mk vs B | R $ vs B | R dominates B | R sig. faster / slower | R sig. cheaper / dearer |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for label, path in (("on", f"experiments/sweep_raw_{FP}.jsonl"), ("off (proxy)", f"experiments/sweep_variant_nocap_{FP}.jsonl")):
    base = rp.load_jsonl(path)
    cells = rp.cells_of(base)
    comp = {k for k, s in cells.items() if rp.complete(s)}
    stats = {k: rp.cell_stats(cells[k]) for k in comp}
    for name, sel in (("as frozen (U3 kept)", sorted(comp)), ("REF-faithful: cells with a Phase-3 run dropped", sorted(comp - ph3cells))):
        g = rp.group_row(stats, sel)
        bydf = " / ".join(str(sum(1 for c in sel if c[2] == df)) for df in (0.25, 0.5, 1.0, 2.0))
        print(f"| {label} | {name} | {g['cells']} | {bydf} | {g['bmk']:+.2f}% | {g['bc']:+.2f}% | {g['rmk']:+.2f}% | {g['rc']:+.2f}% | "
              f"{g['rbmk']:+.2f}% | {g['rbc']:+.2f}% | {g['dom']} | {g['fast']} / {g['slow']} | {g['cheap']} / {g['dear']} |")
