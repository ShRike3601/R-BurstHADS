"""
Run the full-sweep grid (or a slice of it) under a counterfactual patch
from experiments/variants.py, and compare with a base sweep results file.

checkpoint.py measures a candidate fix on five fixed cells. Some effects
live elsewhere -- the residual Burst-HADS misses were at DF=0.25 and at
n=50/200, and instance limits bind mostly at small DF -- so this reuses
dynamic_comparison.run_one_unit unchanged, with the variant applied in the
worker first.

Output: experiments/sweep_variant_<variant>_<code fingerprint>.jsonl,
rewritten on every run (a variant file is a measurement, not a resumable
result); --report-only re-reads it instead. The comparison reads the base
rows for exactly the same units from sweep_raw_<base fingerprint>.jsonl;
with --variant base (or a faithful copy) every row must match.

A run whose primary schedule cannot meet D within the instance limits is
recorded as infeasible (models.limits.NoFeasibleSchedule). Cell means use
feasible runs only and exclude any cell where a scheduler was infeasible
in some seed; the infeasibility itself is reported separately.

Usage (from the project root):
    python experiments\\variant_sweep.py --variant b_order --seeds 0-9 --base-fp fb931f79c624
"""

import sys, os, json, time, argparse
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PROJ = HERE.parent
for p in (str(_PROJ), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import dynamic_comparison as dc

KEYS = ("hads", "burst", "rburst")


def run_unit(args):
    scenario, n, df, seed, key, fp, variant = args
    for p in (str(_PROJ), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import variants
    import dynamic_comparison as dcw
    t9 = dcw.TABLE9.get(scenario)
    variants.apply(variant, kh=t9["kh"] if t9 else None,
                   kr=t9["kr"] if t9 else None)
    row = dcw.run_one_unit((scenario, n, df, seed, key, fp))
    row["variant"] = variant
    return row


def _pct(x, y):
    return 100.0 * (x - y) / y


def _feasible(r):
    return r["error"] is None and not r.get("infeasible")


def summarize(rows, label):
    cells, blocked = {}, set()
    for r in rows:
        c = (r["scenario"], r["n"], r["df"])
        if r.get("infeasible"):
            blocked.add(c)
        elif r["error"] is None:
            cells.setdefault(c, {}).setdefault(r["key"], []).append(r)
    out = {}
    for c, g in cells.items():
        if c in blocked or not all(k in g for k in KEYS):
            continue
        out[c] = {k: dict(mk=sum(x["mk"] for x in g[k]) / len(g[k]),
                          cost=sum(x["cost"] for x in g[k]) / len(g[k]),
                          misses=sum(x["misses"] for x in g[k]) / len(g[k]))
                  for k in KEYS}
    return out


def report(base, var, title):
    print(f"\n{title}")
    print(f"  {'group':10s} {'':>7s} {'cells':>3s} | {'Burst mk':>8s} {'Burst $':>8s} | "
          f"{'R mk':>7s} {'R $':>7s} | {'R/B mk':>7s} {'R/B $':>7s} | {'dom':>5s} | "
          f"{'miss cells H/B/R':>16s} {'miss total H/B/R':>18s}")
    for name, sel in [("all", lambda c: True)] + [
            (f"DF={df}", (lambda d: lambda c: c[2] == d)(df))
            for df in sorted({c[2] for c in var})]:
        cs = [c for c in var if sel(c) and c in base]
        if not cs:
            continue
        for tag, src in (("base", base), ("variant", var)):
            m = lambda f: sum(f(src[c]) for c in cs) / len(cs)
            dom = sum(src[c]["rburst"]["mk"] <= src[c]["burst"]["mk"]
                      and src[c]["rburst"]["cost"] <= src[c]["burst"]["cost"]
                      for c in cs)
            mc = "/".join(str(sum(src[c][k]["misses"] > 0 for c in cs)) for k in KEYS)
            mt = "/".join(f"{sum(src[c][k]['misses'] for c in cs):.2f}" for k in KEYS)
            print(f"  {name:10s} {tag:>7s} {len(cs):3d} | "
                  f"{m(lambda x: _pct(x['burst']['mk'], x['hads']['mk'])):+8.1f} "
                  f"{m(lambda x: _pct(x['burst']['cost'], x['hads']['cost'])):+8.1f} | "
                  f"{m(lambda x: _pct(x['rburst']['mk'], x['hads']['mk'])):+7.1f} "
                  f"{m(lambda x: _pct(x['rburst']['cost'], x['hads']['cost'])):+7.1f} | "
                  f"{m(lambda x: _pct(x['rburst']['mk'], x['burst']['mk'])):+7.1f} "
                  f"{m(lambda x: _pct(x['rburst']['cost'], x['burst']['cost'])):+7.1f} | "
                  f"{dom:2d}/{len(cs):<2d} | {mc:>16s} {mt:>18s}")


def infeasible_table(rows):
    """Share of runs with no primary schedule within D and the instance
    limits, by scheduler, per DF and per n; the cells where schedulers
    differ; and mean deadline misses over FEASIBLE runs, by DF."""
    if not any(r.get("infeasible") for r in rows):
        return
    for dim in ("df", "n"):
        tot = Counter((r["key"], r[dim]) for r in rows)
        inf = Counter((r["key"], r[dim]) for r in rows if r.get("infeasible"))
        print(f"\ninfeasible runs by {dim} (share of runs per scheduler)")
        for v in sorted({r[dim] for r in rows}):
            print(f"  {dim}={v!s:<6} " + "  ".join(
                f"{k}:{inf[(k, v)]:4d}/{tot[(k, v)]:<4d} "
                f"({100 * inf[(k, v)] / max(1, tot[(k, v)]):3.0f}%)" for k in KEYS))
    cells = sorted({(r["scenario"], r["n"], r["df"]) for r in rows})
    tot = Counter((r["key"], r["scenario"], r["n"], r["df"]) for r in rows)
    inf = Counter((r["key"], r["scenario"], r["n"], r["df"]) for r in rows
                  if r.get("infeasible"))
    differ = [c for c in cells if len({inf[(k,) + c] for k in KEYS}) > 1]
    partial = [c for c in cells if any(0 < inf[(k,) + c] < tot[(k,) + c] for k in KEYS)]
    print(f"\ncells where schedulers differ in infeasible seeds: {len(differ)}; "
          f"cells with some but not all seeds infeasible: {len(partial)}")
    for c in sorted(set(differ) | set(partial)):
        print(f"  {c[0]} n={c[1]} DF={c[2]}: " + " ".join(
            f"{k}:{inf[(k,) + c]}/{tot[(k,) + c]}" for k in KEYS))
    print("\nmean deadline misses per FEASIBLE run, by DF")
    for v in sorted({r["df"] for r in rows}):
        parts = []
        for k in KEYS:
            fe = [r for r in rows if r["df"] == v and r["key"] == k and _feasible(r)]
            parts.append(f"{k}:{sum(r['misses'] for r in fe) / max(1, len(fe)):6.2f} "
                         f"(n={len(fe)})")
        print(f"  DF={v!s:<5} " + "  ".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--base-fp", required=True)
    ap.add_argument("--scenarios")
    ap.add_argument("--ns")
    ap.add_argument("--dfs")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--keys", default=",".join(KEYS),
                    help="comma list of schedulers to run (default all); a variant that "
                         "patches one scheduler only needs that one")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--report-only", action="store_true",
                    help="re-read the existing variant file instead of running")
    a = ap.parse_args()

    import variants
    if a.variant not in variants.VARIANTS:
        raise SystemExit(f"unknown variant; have {sorted(variants.VARIANTS)}")
    fp = dc.code_fingerprint()
    scenarios, ns, dfs, seeds = dc._grid(a)
    units = [(sc, n, df, s, k, fp, a.variant) for sc in scenarios for n in ns
             for df in dfs for s in seeds for k in a.keys.split(",")]
    path = HERE / f"sweep_variant_{a.variant}_{fp}.jsonl"
    print(f"variant {a.variant}: {len(units)} units on {a.workers} workers -> "
          f"{path.name}{' (report only)' if a.report_only else ''}", flush=True)
    t0 = time.time()
    if a.report_only:
        rows = dc._load_rows(path)
    else:
        from multiprocessing import Pool
        with Pool(a.workers) as pool:
            rows = list(pool.imap_unordered(run_unit, units, chunksize=2))
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    errors = [r for r in rows if r["error"] is not None]
    print(f"infeasible runs: {sum(1 for r in rows if r.get('infeasible'))}")
    print(f"done in {time.time() - t0:.0f}s, {len(errors)} errors"
          + (f"; first: {errors[0]['error']}" if errors else ""))

    base_rows = {dc._unit_key(r): r for r in dc._load_rows(dc.raw_path(a.base_fp))}
    wanted = {u[:5] for u in units}
    base_sel = [r for k, r in base_rows.items() if k in wanted]
    same = sum(1 for r in rows if (b := base_rows.get(dc._unit_key(r)))
               and _feasible(b) and _feasible(r)
               and abs(b["mk"] - r["mk"]) < 1e-9 and abs(b["cost"] - r["cost"]) < 1e-12
               and b["misses"] == r["misses"])
    print(f"identical to base {a.base_fp}: {same}/{len(rows)} units "
          f"(base rows found: {len(base_sel)})")
    if set(a.keys.split(",")) != set(KEYS):
        print("scheduler subset: cross-scheduler summary skipped")
        return
    report(summarize(base_sel, "base"), summarize(rows, a.variant),
           f"variant {a.variant} vs base, mean of cells (% vs HADS unless R/B); "
           f"cells with any infeasible run excluded")
    infeasible_table(rows)


if __name__ == "__main__":
    main()
