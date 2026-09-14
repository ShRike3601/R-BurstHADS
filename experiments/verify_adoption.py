"""
Adopted code must reproduce the variant it adopts, row for row.

    python experiments\\verify_adoption.py diag   ADOPTED_TAG  VARIANT_TAG
    python experiments\\verify_adoption.py sweep  ADOPTED.jsonl VARIANT.jsonl

diag: experiments/diag_cost_gap_<tag>.json rows keyed by (job, scenario,
seed, scheduler), compared on R0 cost, makespan and missed tasks.
sweep: sweep jsonl rows keyed by (scenario, n, df, seed, scheduler),
compared on infeasibility, error, makespan, cost and missed tasks.
Exit status 0 only if every row matches.
"""
import sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOL = 1e-9


def diag_rows(tag):
    d = json.load(open(HERE / f"diag_cost_gap_{tag}.json"))
    return {(r["job"], r["sc"], r["seed"], r["key"]):
            (r["ok"], r.get("error"), r.get("mk"), r.get("cost", {}).get("R0"), r.get("misses"))
            for r in d["rows"]}


def sweep_rows(path):
    out = {}
    for line in open(HERE / path if not Path(path).is_absolute() else path):
        r = json.loads(line)
        out[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = (
            bool(r.get("infeasible")), r.get("error"), r.get("mk"), r.get("cost"), r.get("misses"))
    return out


def same(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if isinstance(x, float) or isinstance(y, float):
            if x is None or y is None or abs(x - y) > TOL:
                return False
        elif x != y:
            return False
    return True


def main():
    mode, adopted, variant = sys.argv[1:4]
    a, v = (diag_rows(adopted), diag_rows(variant)) if mode == "diag" else (sweep_rows(adopted), sweep_rows(variant))
    missing = sorted(set(v) - set(a))
    diff = [k for k in v if k in a and not same(a[k], v[k])]
    print(f"{mode}: {len(v) - len(missing) - len(diff)}/{len(v)} rows identical"
          f" ({len(missing)} missing, {len(diff)} differ)")
    for k in diff[:5]:
        print("  differs:", k, "adopted", a[k], "variant", v[k])
    raise SystemExit(0 if not missing and not diff else 1)


if __name__ == "__main__":
    main()
