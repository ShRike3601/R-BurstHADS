"""
Record-only probe (experiments/u5_nohib_plan.md §2): how often each baseline's
`_capped_fallback` places a task (DEVIATIONS E2) on freeze-fix21, limits on.
R-BurstHADS inherits Burst-HADS's. Every probed row must equal the sweep row.

    python experiments\\diag_capped.py > experiments\\diag_capped.txt
"""
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE.parent), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

FP = "2439a00d7f74"


def probe(unit):
    for p in (str(HERE.parent), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import variants
    import dynamic_comparison as dcw
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS
    t9 = dcw.TABLE9.get(unit[0])
    variants.apply("base", kh=t9["kh"] if t9 else None, kr=t9["kr"] if t9 else None)
    counts = {"placements": 0, "overrides": 0}
    saved = []
    for cls in (HADS, BurstHADS):
        orig = cls.__dict__["_capped_fallback"]

        def wrapped(self, task, current_time, _orig=orig):
            before = self._launches.overrides
            counts["placements"] += 1
            vm = _orig(self, task, current_time)
            counts["overrides"] += self._launches.overrides - before
            return vm
        saved.append((cls, orig))
        setattr(cls, "_capped_fallback", wrapped)
    try:
        row = dcw.run_one_unit((*unit, FP))
    finally:
        for cls, orig in saved:
            setattr(cls, "_capped_fallback", orig)
    return unit, row, counts


def main():
    import dynamic_comparison as dc
    import results_pack as rp
    base = rp.load_jsonl(f"experiments/sweep_raw_{FP}.jsonl")
    units = sorted(base)
    with Pool() as pool:
        out = list(pool.imap_unordered(probe, units, chunksize=4))
    same = sum(1 for u, r, _ in out if rp._same_row(r, base[u], exact=True))
    print(f"diag_capped on {FP}, limits on: {len(out)} units probed; rows identical to sweep_raw: {same}/{len(out)}")
    cells = rp.cells_of(base)
    full = {k for k, s in cells.items() if rp.complete(s)}
    agg = defaultdict(lambda: defaultdict(int))
    for u, r, c in out:
        a = agg[u[4]]
        a["runs"] += 1
        a["placements"] += c["placements"]
        a["overrides"] += c["overrides"]
        if c["placements"]:
            a["runs_with"] += 1
            a[f"runs_with_df{u[2]}"] += 1
            a["runs_with_in75"] += (u[:3] in full)
            a["runs_with_and_miss"] += (rp.ok(r) and r["misses"] > 0)
    print("\n| scheduler | runs | placements | runs with a placement | in the 75 cells | by DF 0.25 / 0.5 / 1.0 / 2.0 | with a miss | overrides past the limit |")
    print("|---|---|---|---|---|---|---|---|")
    for k in ("hads", "burst", "rburst"):
        a = agg[k]
        dfs = " / ".join(str(a[f"runs_with_df{df}"]) for df in (0.25, 0.5, 1.0, 2.0))
        print(f"| {rp.LAB[k]} | {a['runs']} | {a['placements']} | {a['runs_with']} | {a['runs_with_in75']} | {dfs} | {a['runs_with_and_miss']} | {a['overrides']} |")


if __name__ == "__main__":
    main()
