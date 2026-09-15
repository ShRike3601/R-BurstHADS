"""
Counterfactuals on freeze-fix21, limits on and off. Reads committed sweep files only.

    python experiments\\counterfactual_compare.py tier > experiments\\tier_off_compare.txt
        R-BurstHADS with its burstable branch disabled (experiments/tier_off_plan.md)
    python experiments\\counterfactual_compare.py u5   > experiments\\u5_remeasure_compare.txt
        the U5 guard removed from Burst-HADS and R-BurstHADS (experiments/u5_remeasure_plan.md)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import results_pack as rp

FP = "2439a00d7f74"
BASE = {"limits on": f"experiments/sweep_raw_{FP}.jsonl", "limits off": f"experiments/sweep_variant_nocap_{FP}.jsonl"}
SPECS = {
    "tier": dict(title="R-BurstHADS with its burstable branch disabled", plan="experiments/tier_off_plan.md",
                 keys=("rburst",), ref="with branch", alt="branch disabled",
                 var={"limits on": "no_burst_branch", "limits off": "nocap+no_burst_branch"}),
    "u5": dict(title="The U5 guard removed (Burst-HADS and R-BurstHADS)", plan="experiments/u5_remeasure_plan.md",
               keys=("burst", "rburst"), ref="guard kept", alt="guard removed",
               var={"limits on": "burst_fill", "limits off": "nocap+burst_fill"},
               copy={"limits on": "fill_copy", "limits off": "nocap+fill_copy"}),
}
LIMS = ("limits on", "limits off")
mean = rp.mean


def merged(lim, variant):
    d = rp.load_jsonl(BASE[lim])
    if variant:
        d.update(rp.load_jsonl(f"experiments/sweep_variant_{variant}_{FP}.jsonl"))
    return d


def t3(r):
    return sum(v for k, v in (r.get("launched") or {}).items() if k.endswith("t3.large"))


def firings(d):
    diffs = [t3(r) - t3(d[u[:4] + ("burst",)]) for u, r in d.items()
             if u[4] == "rburst" and rp.ok(r) and rp.ok(d.get(u[:4] + ("burst",)))]
    return sum(diffs), sum(1 for x in diffs if x != 0), sum(1 for x in diffs if x < 0), len(diffs)


def complete_cells(d):
    c = rp.cells_of(d)
    return {k for k, s in c.items() if rp.complete(s)}, c


COLS = [("cells", "cells", "d"), ("B mk vs H", "bmk", "%"), ("B $ vs H", "bc", "%"), ("R mk vs H", "rmk", "%"),
        ("R $ vs H", "rc", "%"), ("R mk vs B", "rbmk", "%"), ("R $ vs B", "rbc", "%"), ("R dominates B", "dom", "d"),
        ("R sig. faster / slower", ("fast", "slow"), "p"), ("R sig. cheaper / dearer", ("cheap", "dear"), "p")]


def agg_row(label, d, cells):
    c = rp.cells_of(d)
    cells = sorted(cells)
    if not cells:
        return f"| {label} | 0 |" + " — |" * (len(COLS) - 1)
    g = rp.group_row({k: rp.cell_stats(c[k]) for k in cells}, cells)
    vals = [f"{g[k]:+.2f}%" if f == "%" else f"{g[k[0]]} / {g[k[1]]}" if f == "p" else str(g[k]) for _, k, f in COLS]
    return f"| {label} | " + " | ".join(vals) + " |"


def agg_header(first):
    return f"| {first} | " + " | ".join(c[0] for c in COLS) + " |\n|---|" + "---|" * len(COLS)


def main(which):
    sp = SPECS[which]
    S = {}
    for lim in LIMS:
        S[(lim, sp["ref"])] = merged(lim, None)
        S[(lim, sp["alt"])] = merged(lim, sp["var"][lim])
    name = lambda key: f"{key[0]}, {key[1]}"

    print(f"# {sp['title']}\n")
    print(f"Parent freeze-fix21 `{FP}`; pre-registration `{sp['plan']}`. Rows for "
          f"{', '.join(rp.LAB[k] for k in sp['keys'])} in the '{sp['alt']}' sets come from "
          f"{', '.join('sweep_variant_' + v + '_' + FP + '.jsonl' for v in sp['var'].values())}; "
          "every other row from the baselines. Seeds 0–29. Runs changed: makespan within 1e-9 s, cost within 1e-12 $, same misses.")

    if "copy" in sp:
        print("\n## Fidelity: copy variant against the baseline (exact)")
        for lim in LIMS:
            cp = rp.load_jsonl(f"experiments/sweep_variant_{sp['copy'][lim]}_{FP}.jsonl")
            base = S[(lim, sp["ref"])]
            same = sum(1 for u in cp if rp._same_row(cp[u], base[u], exact=True))
            print(f"- {lim} (`{sp['copy'][lim]}`): {same}/{len(cp)} rows identical")

    print("\n## Burstable branch firings (R-BurstHADS t3.large launches minus Burst-HADS's in the same unit)")
    print("| set | sum over runs | per run | units with a difference | units with a negative difference | paired units |")
    print("|---|---|---|---|---|---|")
    for key, d in S.items():
        s, nz, neg, n = firings(d)
        print(f"| {name(key)} | {s} | {s / n:.3f} | {nz} | {neg} | {n} |")

    for k in sp["keys"]:
        print(f"\n## {rp.LAB[k]} on its own runs")
        print(f"| set | feasible runs | infeasible runs | runs with a miss | missed tasks | runs changed vs '{sp['ref']}' "
              "| mean makespan change | mean cost change | no miss → miss | miss → no miss |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for lim in LIMS:
            a = S[(lim, sp["ref"])]
            for lab in (sp["ref"], sp["alt"]):
                d = S[(lim, lab)]
                rs = {u: r for u, r in d.items() if u[4] == k}
                fe = [r for r in rs.values() if rp.ok(r)]
                inf = sum(1 for r in rs.values() if r.get("infeasible"))
                if lab == sp["ref"]:
                    extra = "— | — | — | — | —"
                else:
                    ch = sum(1 for u in rs if not rp._same_row(rs[u], a[u]))
                    both = [u for u in rs if rp.ok(rs[u]) and rp.ok(a[u])]
                    dmk = mean(rp.pct(rs[u]["mk"], a[u]["mk"]) for u in both)
                    dc = mean(rp.pct(rs[u]["cost"], a[u]["cost"]) for u in both)
                    prot = sum(1 for u in both if a[u]["misses"] == 0 and rs[u]["misses"] > 0)
                    harm = sum(1 for u in both if a[u]["misses"] > 0 and rs[u]["misses"] == 0)
                    extra = f"{ch}/{len(rs)} | {dmk:+.2f}% | {dc:+.2f}% | {prot} | {harm}"
                print(f"| {lim}, {lab} | {len(fe)} | {inf} | {sum(1 for r in fe if r['misses'])} | "
                      f"{sum(r['misses'] for r in fe)} | {extra} |")

    print("\n## Cell aggregates over each set's own complete cells (every scheduler feasible in every seed)")
    print(agg_header("set"))
    cellsets = {}
    for key, d in S.items():
        cellsets[key], _ = complete_cells(d)
        print(agg_row(name(key), d, cellsets[key]))
    for lim in LIMS:
        a, b = cellsets[(lim, sp["ref"])], cellsets[(lim, sp["alt"])]
        print(f"\n{lim}: cell sets identical: {a == b}" + ("" if a == b else
              f" (only '{sp['ref']}': {sorted(a - b)}; only '{sp['alt']}': {sorted(b - a)})"))

    print("\n### By DF")
    print(agg_header("set, DF"))
    for key, d in S.items():
        for df in sorted({c[2] for c in cellsets[key]}):
            print(agg_row(f"{name(key)}, DF {df}", d, {c for c in cellsets[key] if c[2] == df}))

    common = set.intersection(*cellsets.values())
    print(f"\n## Matched: the {len(common)} cells complete in all four sets")
    print(agg_header("set"))
    for key, d in S.items():
        print(agg_row(name(key), d, common))

    if which == "u5":
        g1 = rp.load_jsonl("experiments/sweep_variant_grid_g1e1_519c868a99f9.jsonl")
        g0 = rp.load_jsonl("experiments/sweep_variant_grid_g0e1_519c868a99f9.jsonl")
        grid = complete_cells(g1)[0] & complete_cells(g0)[0]
        print(f"\n## Continuity with T12: the grid's {len(grid)} cells (complete in both grid files, 519c868a99f9, seeds 0–9)")
        print(agg_header("set"))
        print(agg_row("grid g1e1, guard kept (519c868a99f9, seeds 0–9)", g1, grid))
        print(agg_row("grid g0e1, guard removed (519c868a99f9, seeds 0–9)", g0, grid))
        for key, d in S.items():
            if key[0] == "limits on":
                cs = grid & cellsets[key]
                print(agg_row(f"freeze-fix21, {name(key)} ({len(cs)} of the {len(grid)} complete)", d, cs))

    print("\n## Runs changed by DF")
    for k in sp["keys"]:
        for lim in LIMS:
            a, b = S[(lim, sp["ref"])], S[(lim, sp["alt"])]
            parts = []
            for df in (0.25, 0.5, 1.0, 2.0):
                us = [u for u in b if u[4] == k and u[2] == df]
                parts.append(f"DF {df}: {sum(1 for u in us if not rp._same_row(b[u], a[u]))}/{len(us)}")
            print(f"- {rp.LAB[k]}, {lim}: " + "; ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1])
