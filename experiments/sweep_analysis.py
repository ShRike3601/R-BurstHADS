"""
Aggregate one full-sweep results file for CLAUDE.md and the paper.

Reads experiments/sweep_raw_<fingerprint>.jsonl directly (one code
version, a retried unit's last row wins) and reports:

  0. VERIFICATION: seeds 0-9 of the five checkpoint cells at DF 0.5/1.0/2.0
     must reproduce checkpoint_fix10_df* bit-for-bit (same seeding, same
     cost rule). If they do not, the sweep harness disagrees with the
     checkpoint harness and nothing below should be reported.
  1. Means over cells, relative to HADS, and R-BurstHADS vs Burst-HADS,
     overall and by DF, by scenario, by n.
  2. Deadline misses per scheduler: cells with any miss, worst cell.
  3. Per-seed rates: how often R-BurstHADS dominates Burst-HADS on both
     axes, and beats HADS on cost, within a cell.
  4. Ranges and extremes.

Percentages are ratios of cell means, the convention checkpoint.py uses.

Usage (from the project root):
    python experiments\\sweep_analysis.py                # current code
    python experiments\\sweep_analysis.py --fp fb931f79c624
"""

import sys, json, argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dynamic_comparison as dc

KEYS = ("hads", "burst", "rburst")
CHECKPOINT_CELLS = {  # checkpoint.py label -> (scenario, n)
    "sc2  n=300  kh=5 kr=0":   ("sc2", 300),
    "sc1  n=300  kh=1 kr=0":   ("sc1", 300),
    "sc4  n=300  kh=5 kr=5":   ("sc4", 300),
    "sc5  n=300  kh=3 kr=2.5": ("sc5", 300),
    "sc2  n=100  kh=5 kr=0":   ("sc2", 100),
}
CP_SCHED = {"HADS": "hads", "BurstHADS": "burst", "R-BurstHADS": "rburst"}


def pct(x, y):
    return 100.0 * (x - y) / y


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp", help="code fingerprint; default: current code")
    ap.add_argument("--checkpoint-tag", default="fix10",
                    help="checkpoint_<tag>_df*.json to verify against")
    a = ap.parse_args()
    fp = a.fp or dc.code_fingerprint()

    latest = {}
    for r in dc._load_rows(dc.raw_path(fp)):
        latest[dc._unit_key(r)] = r
    rows = list(latest.values())
    errors = [r for r in rows if r["error"] is not None]
    ok = [r for r in rows if r["error"] is None]
    print(f"fingerprint {fp}: {len(rows)} units, {len(errors)} errors")
    if errors:
        print("  first error:", errors[0]["error"])

    # ── 0. verification against the checkpoint harness ──────────────────
    by_unit = {dc._unit_key(r): r for r in ok}
    checked = differ = missing = 0
    for df in (0.5, 1.0, 2.0):
        path = HERE / f"checkpoint_{a.checkpoint_tag}_df{df}.json"
        if not path.exists():
            print(f"  [verify] {path.name} not found")
            continue
        for cr in json.load(open(path))["raw"]:
            sc, n = CHECKPOINT_CELLS[cr["label"]]
            sr = by_unit.get((sc, n, df, cr["seed"], CP_SCHED[cr["sched"]]))
            if sr is None:
                missing += 1
                continue
            checked += 1
            if (abs(sr["mk"] - cr["mk"]) > 1e-9 or abs(sr["cost"] - cr["C"]) > 1e-12
                    or sr["misses"] != cr["misses"]):
                differ += 1
    print(f"0. VERIFY vs checkpoint_{a.checkpoint_tag}_df*: {checked} runs "
          f"compared, {differ} differ, {missing} not in sweep")
    if differ:
        print("   !! sweep and checkpoint harnesses disagree -- stop here")

    # ── per-cell means ───────────────────────────────────────────────────
    cells = {}
    for r in ok:
        cells.setdefault((r["scenario"], r["n"], r["df"]), {}) \
             .setdefault(r["key"], []).append(r)
    C = []
    for (sc, n, df), g in cells.items():
        if not all(k in g for k in KEYS):
            continue
        m = {k: {f: mean(x[f] for x in g[k])
                 for f in ("mk", "cost", "misses", "mk_frac")} for k in KEYS}
        seeds = {k: {x["seed"]: x for x in g[k]} for k in KEYS}
        common = set(seeds["hads"]) & set(seeds["burst"]) & set(seeds["rburst"])
        dom_seed = mean((seeds["rburst"][s]["mk"] <= seeds["burst"][s]["mk"]
                         and seeds["rburst"][s]["cost"] <= seeds["burst"][s]["cost"])
                        for s in common)
        cheaper_seed = mean(seeds["rburst"][s]["cost"] <= seeds["hads"][s]["cost"]
                            for s in common)
        C.append(dict(sc=sc, n=n, df=df, seeds=len(common),
                      floored=g["hads"][0]["floored"], m=m,
                      b_mk=pct(m["burst"]["mk"], m["hads"]["mk"]),
                      b_c=pct(m["burst"]["cost"], m["hads"]["cost"]),
                      r_mk=pct(m["rburst"]["mk"], m["hads"]["mk"]),
                      r_c=pct(m["rburst"]["cost"], m["hads"]["cost"]),
                      rb_mk=pct(m["rburst"]["mk"], m["burst"]["mk"]),
                      rb_c=pct(m["rburst"]["cost"], m["burst"]["cost"]),
                      dom=(m["rburst"]["mk"] <= m["burst"]["mk"]
                           and m["rburst"]["cost"] <= m["burst"]["cost"]),
                      dom_seed=dom_seed, cheaper_seed=cheaper_seed))
    C.sort(key=lambda c: (dc.ALL_SCENARIOS.index(c["sc"]), c["n"], c["df"]))
    print(f"   {len(C)} complete cells, seeds per cell "
          f"{min(c['seeds'] for c in C)}-{max(c['seeds'] for c in C)}")

    def block(title, groups):
        print(f"\n{title}")
        print(f"  {'group':14s} {'cells':>5s} | {'Burst mk':>8s} {'Burst $':>8s} | "
              f"{'R mk':>7s} {'R $':>7s} | {'R/B mk':>7s} {'R/B $':>7s} | "
              f"{'dom':>5s} {'dom/seed':>8s} {'R<=H $/seed':>11s}")
        for name, cs in groups:
            if not cs:
                continue
            f = lambda k: mean(c[k] for c in cs)
            print(f"  {name:14s} {len(cs):5d} | {f('b_mk'):+8.1f} {f('b_c'):+8.1f} | "
                  f"{f('r_mk'):+7.1f} {f('r_c'):+7.1f} | {f('rb_mk'):+7.1f} "
                  f"{f('rb_c'):+7.1f} | {sum(c['dom'] for c in cs):2d}/{len(cs):<2d} "
                  f"{100*f('dom_seed'):7.0f}% {100*f('cheaper_seed'):10.0f}%")

    # ── 1. aggregates ────────────────────────────────────────────────────
    block("1. MEAN OF CELLS, % vs HADS (R/B = R-BurstHADS vs Burst-HADS)",
          [("all", C)])
    block("   by DF", [(f"DF={df}", [c for c in C if c["df"] == df])
                       for df in sorted({c["df"] for c in C})])
    block("   by scenario", [(sc, [c for c in C if c["sc"] == sc])
                             for sc in dc.ALL_SCENARIOS])
    block("   by n", [(f"n={n}", [c for c in C if c["n"] == n])
                      for n in sorted({c["n"] for c in C})])
    block("   excluding floor-bound cells", [("not floored",
                                             [c for c in C if not c["floored"]])])

    # ── 2. deadline misses ───────────────────────────────────────────────
    print("\n2. DEADLINE MISSES (mean per run)")
    for k in KEYS:
        hit = [c for c in C if c["m"][k]["misses"] > 0]
        worst = max(C, key=lambda c: c["m"][k]["misses"])
        print(f"  {dc.SCHEDULER_LABELS[k]:12s} cells with any miss: {len(hit):2d}/{len(C)}; "
              f"worst {worst['sc']} n={worst['n']} DF={worst['df']}: "
              f"{worst['m'][k]['misses']:.2f} of {worst['n']} tasks")
        for c in hit:
            print(f"      {c['sc']} n={c['n']} DF={c['df']}{' (floored)' if c['floored'] else ''}: "
                  f"{c['m'][k]['misses']:.2f}")

    # ── 3/4. extremes and every cell ─────────────────────────────────────
    lo = min(C, key=lambda c: c["r_c"]); hi = max(C, key=lambda c: c["r_c"])
    print(f"\n3. R-BurstHADS cost vs HADS: {lo['r_c']:+.1f}% ({lo['sc']} n={lo['n']} "
          f"DF={lo['df']}) to {hi['r_c']:+.1f}% ({hi['sc']} n={hi['n']} DF={hi['df']})")
    blo = min(C, key=lambda c: c["b_c"]); bhi = max(C, key=lambda c: c["b_c"])
    print(f"   Burst-HADS cost vs HADS: {blo['b_c']:+.1f}% to {bhi['b_c']:+.1f}%; "
          f"cells where Burst-HADS is cheaper than HADS: "
          f"{sum(c['b_c'] < 0 for c in C)}")
    nd = [c for c in C if not c["dom"]]
    print(f"   cells where R-BurstHADS does NOT dominate Burst-HADS: {len(nd)}")
    for c in nd:
        print(f"      {c['sc']} n={c['n']} DF={c['df']}: R/B mk {c['rb_mk']:+.1f}% "
              f"cost {c['rb_c']:+.1f}%")

    print("\n4. EVERY CELL  (* = deadline set by the floor)")
    print(f"  {'cell':16s} {'DF':>5s} | {'H mk/D':>6s} | {'B mk%':>6s} {'B $%':>6s} | "
          f"{'R mk%':>6s} {'R $%':>6s} | {'R/B mk':>6s} {'R/B $':>6s} | dom/seed")
    for c in C:
        print(f"  {c['sc']+' n='+str(c['n'])+('*' if c['floored'] else ''):16s} "
              f"{c['df']:5.2f} | {100*c['m']['hads']['mk_frac']:5.0f}% | "
              f"{c['b_mk']:+6.1f} {c['b_c']:+6.1f} | {c['r_mk']:+6.1f} {c['r_c']:+6.1f} | "
              f"{c['rb_mk']:+6.1f} {c['rb_c']:+6.1f} | {100*c['dom_seed']:5.0f}%")


if __name__ == "__main__":
    main()
