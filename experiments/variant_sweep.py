"""
Run the full-sweep grid (or a slice of it) under a counterfactual patch
from experiments/variants.py, and compare with a base sweep results file.

checkpoint.py measures a candidate fix on five fixed cells. Some effects
live elsewhere -- the residual Burst-HADS misses are at DF=0.25 and at
n=50/200 -- so this reuses dynamic_comparison.run_one_unit unchanged, with
the variant applied in the worker first.

Output: experiments/sweep_variant_<variant>_<code fingerprint>.jsonl,
rewritten on every run (a variant file is a measurement, not a resumable
result). The comparison reads the base rows for exactly the same units
from sweep_raw_<base fingerprint>.jsonl; with --variant base (or a
faithful copy) every row must match.

Usage (from the project root):
    python experiments\\variant_sweep.py --variant b_order --seeds 0-9 --base-fp fb931f79c624
"""

import sys, os, json, time, argparse
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


def summarize(rows, label):
    cells = {}
    for r in rows:
        if r["error"] is None and not r.get("infeasible"):
            cells.setdefault((r["scenario"], r["n"], r["df"]), {}) \
                 .setdefault(r["key"], []).append(r)
    out = {}
    for c, g in cells.items():
        if all(k in g for k in KEYS):
            out[c] = {k: dict(mk=sum(x["mk"] for x in g[k]) / len(g[k]),
                              cost=sum(x["cost"] for x in g[k]) / len(g[k]),
                              misses=sum(x["misses"] for x in g[k]) / len(g[k]))
                      for k in KEYS}
    return out


def report(base, var, title):
    print(f"\n{title}")
    print(f"  {'group':10s} {'cells':>5s} | {'Burst mk':>8s} {'Burst $':>8s} | "
          f"{'R mk':>7s} {'R $':>7s} | {'R/B mk':>7s} {'R/B $':>7s} | {'dom':>5s} | "
          f"{'miss cells H/B/R':>16s} {'miss total H/B/R':>18s}")
    for name, sel in [("all", lambda c: True)] + [
            (f"DF={df}", (lambda d: lambda c: c[2] == d)(df))
            for df in sorted({c[2] for c in var})]:
        for tag, src in (("base", base), ("variant", var)):
            cs = [c for c in var if sel(c) and c in base]
            if not cs:
                continue
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--base-fp", required=True)
    ap.add_argument("--scenarios")
    ap.add_argument("--ns")
    ap.add_argument("--dfs")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    import variants
    if a.variant not in variants.VARIANTS:
        raise SystemExit(f"unknown variant; have {sorted(variants.VARIANTS)}")
    fp = dc.code_fingerprint()
    scenarios, ns, dfs, seeds = dc._grid(a)
    units = [(sc, n, df, s, k, fp, a.variant) for sc in scenarios for n in ns
             for df in dfs for s in seeds for k in KEYS]
    path = HERE / f"sweep_variant_{a.variant}_{fp}.jsonl"
    print(f"variant {a.variant}: {len(units)} units on {a.workers} workers -> "
          f"{path.name}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
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
               and b["error"] is None and r["error"] is None
               and abs(b["mk"] - r["mk"]) < 1e-9 and abs(b["cost"] - r["cost"]) < 1e-12
               and b["misses"] == r["misses"])
    print(f"identical to base {a.base_fp}: {same}/{len(rows)} units "
          f"(base rows found: {len(base_sel)})")
    report(summarize(base_sel, "base"), summarize(rows, a.variant),
           f"variant {a.variant} vs base, mean of cells (% vs HADS unless R/B)")


if __name__ == "__main__":
    main()
