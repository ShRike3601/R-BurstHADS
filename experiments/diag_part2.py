"""
Record-only probe (experiments/part2_plan.md): Burst-HADS's burst allocation
(Algorithm 1 Part 2) on freeze-fix21, limits on, Burst-HADS and R-BurstHADS,
with the U5 guard kept (`base`) and removed (`burst_fill`). Every probed row
must equal its sweep row exactly.

    python experiments\\diag_part2.py > experiments\\diag_part2.txt
"""
import math
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE.parent), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

FP = "2439a00d7f74"
REF = {"base": f"experiments/sweep_raw_{FP}.jsonl",
       "burst_fill": f"experiments/sweep_variant_burst_fill_{FP}.jsonl"}


def probe(arg):
    variant, unit = arg
    for p in (str(HERE.parent), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import variants
    import dynamic_comparison as dcw
    from scheduler.burst_hads import BurstHADS
    t9 = dcw.TABLE9.get(unit[0])
    variants.apply(variant, kh=t9["kh"] if t9 else None, kr=t9["kr"] if t9 else None)
    current = BurstHADS._allocate_burstable_vms
    rec = {}

    def spot_violators(self, sol):
        vm_map = {vm.id: vm for vm in self.all_vms}
        ft = self._solution_task_finish_times(sol)
        out = []
        for t, f in ft.items():
            vm = vm_map.get(sol.allocation.get(t.task_id))
            if vm is not None and vm.is_spot and f > self.Dspot:
                out.append((t, f))
        return out

    def wrapped(self, solution):
        n_burst = math.ceil(self.burst_rate * max(1, len(solution.selected_vms)))
        before = spot_violators(self, solution)
        out = current(self, solution)
        after = spot_violators(self, out)
        vm_map = {vm.id: vm for vm in self.all_vms}
        moved = sum(1 for t in self.all_tasks
                    if (v := vm_map.get(out.allocation.get(t.task_id))) is not None and v.is_burstable)
        rec.update(n_burst=n_burst, before=len(before), after=len(after),
                   after_past_D=sum(1 for _, f in after if f > self.D), moved=moved)
        return out

    setattr(BurstHADS, "_allocate_burstable_vms", wrapped)
    try:
        row = dcw.run_one_unit((*unit, FP))
    finally:
        setattr(BurstHADS, "_allocate_burstable_vms", current)
    return variant, unit, row, rec


def main():
    import results_pack as rp
    refs = {v: rp.load_jsonl(p) for v, p in REF.items()}
    base = refs["base"]
    full = {k for k, s in rp.cells_of(base).items() if rp.complete(s)}
    jobs = [(v, u) for v in REF for u in sorted(base) if u[4] in ("burst", "rburst")]
    with Pool() as pool:
        out = list(pool.imap_unordered(probe, jobs, chunksize=4))
    print(f"diag_part2 on {FP}, limits on, seeds 0-29")
    for v in REF:
        rows = [(u, r) for vv, u, r, _ in out if vv == v]
        same = sum(1 for u, r in rows if rp._same_row(r, refs[v][u], exact=True))
        print(f"- {v}: rows identical to {REF[v]}: {same}/{len(rows)}")

    print("\n| guard | scheduler | runs | Part 2 ran | runs with a violator before | violators before | "
          "burstables launched | tasks moved to burstables | runs leaving a violator on spot | violators left on spot | "
          "left and planned past D | those runs in the 75 cells | missed tasks in those runs | by DF 0.25 / 0.5 / 1.0 / 2.0 (runs leaving one) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v in REF:
        for k in ("burst", "rburst"):
            sel = [(u, r, c) for vv, u, r, c in out if vv == v and u[4] == k]
            ran = [(u, r, c) for u, r, c in sel if c]
            left = [(u, r, c) for u, r, c in ran if c["after"] > 0]
            dfs = " / ".join(str(sum(1 for u, _, _ in left if u[2] == df)) for df in (0.25, 0.5, 1.0, 2.0))
            print(f"| {'kept' if v == 'base' else 'removed'} | {rp.LAB[k]} | {len(sel)} | {len(ran)} | "
                  f"{sum(1 for *_, c in ran if c['before'] > 0)} | {sum(c['before'] for *_, c in ran)} | "
                  f"{sum(c['n_burst'] for *_, c in ran)} | {sum(c['moved'] for *_, c in ran)} | {len(left)} | "
                  f"{sum(c['after'] for *_, c in left)} | {sum(c['after_past_D'] for *_, c in left)} | "
                  f"{sum(1 for u, _, _ in left if u[:3] in full)} | "
                  f"{sum(r['misses'] for _, r, _ in left if rp.ok(r))} | {dfs} |")


if __name__ == "__main__":
    main()
