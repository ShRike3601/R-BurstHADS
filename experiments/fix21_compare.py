"""
Fix 21 (experiments/fix21_plan.md): the fidelity check, each sub-fix alone,
the combined set, leave-one-out contributions, per-scheduler effects, and fix
20 once VMs wait for boot.

    python experiments\\fix21_compare.py   -> stdout

Base experiments/sweep_raw_d40a1c917c63.jsonl (freeze-fix20). A variant file
holding only R-BurstHADS rows (f21b, f21_no_b) takes the other schedulers from
the set named in its "fill" entry; sub-fix b touches R-BurstHADS only.
Runs changed: makespan within 1e-9 s, cost within 1e-12 $, same missed tasks;
the fidelity check is exact.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import results_pack as rp

FP = "d40a1c917c63"
KEYS = ("hads", "burst", "rburst")
LAB = {"hads": "HADS", "burst": "Burst-HADS", "rburst": "R-BurstHADS"}
SETS = {
    "base": (None, None),
    "copy": ("f21_copy", "base"),
    "21a": ("f21a", "base"),
    "21b": ("f21b", "base"),
    "21c": ("f21c", "base"),
    "ALL": ("f21", "base"),
    "ALL-21a": ("f21_no_a", "base"),
    "ALL-21b": ("f21_no_b", "ALL"),
    "ALL-21c": ("f21_no_c", "base"),
    "ALL-20": ("f21_no20", "base"),
}
_cache = {}


def rows(label):
    if label in _cache:
        return _cache[label]
    tag, fill = SETS[label]
    if tag is None:
        d = rp.load_jsonl(f"experiments/sweep_raw_{FP}.jsonl")
    else:
        d = dict(rows(fill))
        d.update(rp.load_jsonl(f"experiments/sweep_variant_{tag}_{FP}.jsonl"))
    _cache[label] = d
    return d


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def pct(a, b):
    return 100.0 * (a - b) / b


def same(a, b, exact=False):
    if bool(a.get("infeasible")) != bool(b.get("infeasible")) or a.get("error") != b.get("error"):
        return False
    if a.get("infeasible"):
        return True
    if exact:
        return a["mk"] == b["mk"] and a["cost"] == b["cost"] and a["misses"] == b["misses"]
    return abs(a["mk"] - b["mk"]) < 1e-9 and abs(a["cost"] - b["cost"]) < 1e-12 and a["misses"] == b["misses"]


def metrics(label):
    d = rows(label)
    cells = rp.cells_of(d)
    comp = [c for c in sorted(cells) if rp.complete(cells[c])]
    m = dict(rp.group_row({c: rp.cell_stats(cells[c]) for c in comp}, comp))
    for k in KEYS:
        fe = [r for u, r in d.items() if u[4] == k and rp.ok(r)]
        m[f"miss_{k}"] = sum(r["misses"] for r in fe)
        m[f"runs_{k}"] = sum(1 for r in fe if r["misses"] > 0)
        m[f"inf_{k}"] = sum(1 for u, r in d.items() if u[4] == k and r.get("infeasible"))
    return m


COLS = [("R $ vs H", "rc", "{:+.2f}%"), ("R mk vs H", "rmk", "{:+.2f}%"), ("R $ vs B", "rbc", "{:+.2f}%"),
        ("R mk vs B", "rbmk", "{:+.2f}%"), ("B $ vs H", "bc", "{:+.2f}%"), ("B mk vs H", "bmk", "{:+.2f}%"),
        ("R dominates B", "dom", "{:d}"), ("R sig. cheaper", "cheap", "{:d}"), ("R sig. dearer", "dear", "{:d}"),
        ("R sig. faster", "fast", "{:d}"), ("R sig. slower", "slow", "{:d}"),
        ("missed H", "miss_hads", "{:d}"), ("missed B", "miss_burst", "{:d}"), ("missed R", "miss_rburst", "{:d}"),
        ("infeasible H", "inf_hads", "{:d}")]


def changed(a, b, key, exact=False):
    da, db = rows(a), rows(b)
    us = [u for u in da if u[4] == key]
    return sum(1 for u in us if not same(da[u], db[u], exact)), len(us)


def paired(a, b, key):
    da, db = rows(a), rows(b)
    us = [u for u in da if u[4] == key and rp.ok(da[u]) and rp.ok(db[u])]
    return mean(pct(da[u]["mk"], db[u]["mk"]) for u in us), mean(pct(da[u]["cost"], db[u]["cost"]) for u in us)


def main():
    print(f"Base freeze-fix20 {FP}, limits on, 30 seeds. Cell aggregates over the cells where every scheduler "
          "is feasible in every seed (count in 'cells').")
    print("\n## Fidelity: f21_copy (every copy installed, T_start = 0) against base, exact")
    print("| scheduler | rows differing |")
    print("|---|---|")
    for k in KEYS:
        print(f"| {LAB[k]} | {'{}/{}'.format(*changed('copy', 'base', k, exact=True))} |")

    labels = [x for x in SETS if x != "copy"]
    ms = {lb: metrics(lb) for lb in labels}
    print("\n## Every set")
    print("| set | cells | " + " | ".join(c[0] for c in COLS) + " |")
    print("|---|---|" + "---|" * len(COLS))
    for lb in labels:
        print(f"| {lb} | {ms[lb]['cells']} | " + " | ".join(f.format(ms[lb][k]) for _, k, f in COLS) + " |")

    def delta_rows(title, pairs):
        print(f"\n## {title}")
        print("| effect | computed as | cells | " + " | ".join(c[0] for c in COLS) + " |")
        print("|---|---|---|" + "---|" * len(COLS))
        for name, a, b in pairs:
            cells = [("{:+.2f}" if "%" in f else "{:+d}").format(ms[a][k] - ms[b][k]) for _, k, f in COLS]
            print(f"| {name} | {a} minus {b} | {ms[a]['cells']} vs {ms[b]['cells']} | " + " | ".join(cells) + " |")

    delta_rows("Individual effect (set against base)",
               [(f"fix {x}", x, "base") for x in ("21a", "21b", "21c")] + [("fix 21 (all)", "ALL", "base")])
    delta_rows("Contribution within the combined set (ALL against ALL without the sub-fix)",
               [(f"fix {x}", "ALL", f"ALL-{x}") for x in ("21a", "21b", "21c")])

    print("\n## Per scheduler (runs changed use the tolerance above)")
    print("| comparison | scheduler | runs changed | missed tasks (from -> to) | runs with a miss (from -> to) | "
          "infeasible runs (from -> to) | mean makespan change | mean cost change |")
    print("|---|---|---|---|---|---|---|---|")
    for name, a, b in (("21a alone vs base", "21a", "base"), ("21b alone vs base", "21b", "base"),
                       ("21c alone vs base", "21c", "base"), ("fix 21 vs base", "ALL", "base"),
                       ("ALL vs ALL-21a", "ALL", "ALL-21a"), ("ALL vs ALL-21b", "ALL", "ALL-21b"),
                       ("ALL vs ALL-21c", "ALL", "ALL-21c")):
        for k in KEYS:
            c, n = changed(a, b, k)
            dmk, dc = paired(a, b, k)
            print(f"| {name} | {LAB[k]} | {c}/{n} | {ms[b]['miss_' + k]} -> {ms[a]['miss_' + k]} | "
                  f"{ms[b]['runs_' + k]} -> {ms[a]['runs_' + k]} | {ms[b]['inf_' + k]} -> {ms[a]['inf_' + k]} | "
                  f"{dmk:+.2f}% | {dc:+.2f}% |")

    print("\n## Fix 20 once VMs wait for boot: ALL against ALL with fix 20 reverted")
    print("| scheduler | runs changed (tolerance) | rows differing (exact) |")
    print("|---|---|---|")
    for k in KEYS:
        print(f"| {LAB[k]} | {'{}/{}'.format(*changed('ALL', 'ALL-20', k))} | "
              f"{'{}/{}'.format(*changed('ALL', 'ALL-20', k, exact=True))} |")


if __name__ == "__main__":
    main()
