"""
Fixes 17a, 18, 19, 20: individual effects, the combined set, leave-one-out
attribution, the 18+20 interaction, and per-scheduler effects of 19.

    python experiments\\fix18_20_compare.py   -> stdout

Frozen base experiments/sweep_raw_4f08f48ac35c.jsonl (never written). A variant
file holding only R-BurstHADS rows takes the other schedulers from the file named
in its "fill" entry. Aggregates use results_pack.py's own functions.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import results_pack as rp

FP = "4f08f48ac35c"
KEYS = ("hads", "burst", "rburst")
LAB = {"hads": "HADS", "burst": "Burst-HADS", "rburst": "R-BurstHADS"}
# label -> (variant tag, fill tag for schedulers the file lacks)
SETS = {
    "frozen": (None, None),
    "17a": ("f17a", "frozen"),
    "18": ("boot_wait", "frozen"),
    "19": ("ckpt_exec", "frozen"),
    "20": ("u10_ovh", "frozen"),
    "18+20": ("boot_u10", "20"),
    "ALL (17a+18+19+20)": ("fx_all", "frozen"),
    "ALL - 17a": ("fx_no17a", "ALL (17a+18+19+20)"),
    "ALL - 18": ("fx_no18", "ALL (17a+18+19+20)"),
    "ALL - 19": ("fx_no19", "frozen"),
    "ALL - 20": ("fx_no20", "frozen"),
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


def same(a, b):
    if bool(a.get("infeasible")) != bool(b.get("infeasible")) or a.get("error") != b.get("error"):
        return False
    return a.get("infeasible") or (a["mk"] == b["mk"] and a["cost"] == b["cost"] and a["misses"] == b["misses"])


def metrics(label, cells_filter=lambda c: True):
    d = rows(label)
    cells = rp.cells_of(d)
    comp = [c for c in sorted(cells) if rp.complete(cells[c]) and cells_filter(c)]
    g = rp.group_row({c: rp.cell_stats(cells[c]) for c in comp}, comp)
    m = dict(g)
    for k in KEYS:
        fe = [r for u, r in d.items() if u[4] == k and rp.ok(r)]
        m[f"miss_{k}"] = sum(r["misses"] for r in fe)
        m[f"runs_{k}"] = sum(1 for r in fe if r["misses"] > 0)
    return m


COLS = [("R $ vs B", "rbc", "{:+.2f}%"), ("R mk vs B", "rbmk", "{:+.2f}%"), ("R $ vs H", "rc", "{:+.2f}%"),
        ("R mk vs H", "rmk", "{:+.2f}%"), ("B $ vs H", "bc", "{:+.2f}%"), ("B mk vs H", "bmk", "{:+.2f}%"),
        ("R dominates B", "dom", "{:d}"), ("R sig. cheaper", "cheap", "{:d}"), ("R sig. dearer", "dear", "{:d}"),
        ("R sig. faster", "fast", "{:d}"), ("R sig. slower", "slow", "{:d}"),
        ("missed H", "miss_hads", "{:d}"), ("missed B", "miss_burst", "{:d}"), ("missed R", "miss_rburst", "{:d}"),
        ("runs w/ miss R", "runs_rburst", "{:d}")]


def table(title, labels, ms):
    print(f"\n## {title}")
    print("| set | cells | " + " | ".join(c[0] for c in COLS) + " |")
    print("|---|---|" + "---|" * len(COLS))
    for lb in labels:
        m = ms[lb]
        print(f"| {lb} | {m['cells']} | " + " | ".join(f.format(m[k]) for _, k, f in COLS) + " |")


def deltas(title, pairs, ms):
    print(f"\n## {title}")
    print("| effect | computed as | " + " | ".join(c[0] for c in COLS) + " |")
    print("|---|---|" + "---|" * len(COLS))
    for name, a, b in pairs:
        cells = []
        for _, k, f in COLS:
            v = ms[a][k] - ms[b][k]
            cells.append(("{:+.2f}" if "%" in f else "{:+d}").format(v))
        print(f"| {name} | {a} minus {b} | " + " | ".join(cells) + " |")


def changed(a, b, key):
    da, db = rows(a), rows(b)
    us = [u for u in da if u[4] == key]
    return sum(1 for u in us if not same(da[u], db[u])), len(us)


def paired(a, b, key):
    da, db = rows(a), rows(b)
    us = [u for u in da if u[4] == key and rp.ok(da[u]) and rp.ok(db[u])]
    return mean(pct(da[u]["mk"], db[u]["mk"]) for u in us), mean(pct(da[u]["cost"], db[u]["cost"]) for u in us)


def main():
    labels = list(SETS)
    ms = {lb: metrics(lb) for lb in labels}
    print(f"Frozen base {FP}, limits on, 30 seeds. Cell aggregates over the cells where every scheduler is feasible in every seed.")
    table("Every set, full sweep", labels, ms)
    deltas("Individual effect (set against frozen)",
           [(f"fix {x}", x, "frozen") for x in ("17a", "18", "19", "20")] + [("18+20 together", "18+20", "frozen"),
            ("ALL together", "ALL (17a+18+19+20)", "frozen")], ms)
    deltas("Contribution within the combined set (ALL against ALL without the fix)",
           [(f"fix {x}", "ALL (17a+18+19+20)", f"ALL - {x}") for x in ("17a", "18", "19", "20")], ms)

    print("\n## U10 (fix 20): runs it changes, with and without fix 18 and within the set")
    print("| comparison | HADS runs changed | Burst-HADS runs changed | R-BurstHADS runs changed |")
    print("|---|---|---|---|")
    for name, a, b in (("20 alone vs frozen", "20", "frozen"), ("18+20 vs 18", "18+20", "18"),
                       ("ALL vs ALL - 20", "ALL (17a+18+19+20)", "ALL - 20")):
        print(f"| {name} | " + " | ".join("{}/{}".format(*changed(a, b, k)) for k in KEYS) + " |")

    print("\n## Per-scheduler effect of fix 19 (checkpoint credits executed progress)")
    print("| comparison | scheduler | runs changed | missed tasks (from -> to) | mean makespan change | mean cost change |")
    print("|---|---|---|---|---|---|")
    for name, a, b in (("19 alone vs frozen", "19", "frozen"), ("ALL vs ALL - 19", "ALL (17a+18+19+20)", "ALL - 19")):
        for k in KEYS:
            c, n = changed(a, b, k)
            dmk, dc = paired(a, b, k)
            print(f"| {name} | {LAB[k]} | {c}/{n} | {ms[b]['miss_' + k]} -> {ms[a]['miss_' + k]} | {dmk:+.2f}% | {dc:+.2f}% |")

    print("\n## Against frozen, per scheduler, combined set")
    print("| scheduler | runs changed | missed tasks | runs with a miss | mean makespan change | mean cost change |")
    print("|---|---|---|---|---|---|")
    for k in KEYS:
        c, n = changed("ALL (17a+18+19+20)", "frozen", k)
        dmk, dc = paired("ALL (17a+18+19+20)", "frozen", k)
        m = ms["ALL (17a+18+19+20)"]
        print(f"| {LAB[k]} | {c}/{n} | {ms['frozen']['miss_' + k]} -> {m['miss_' + k]} | "
              f"{ms['frozen']['runs_' + k]} -> {m['runs_' + k]} | {dmk:+.2f}% | {dc:+.2f}% |")


if __name__ == "__main__":
    main()
