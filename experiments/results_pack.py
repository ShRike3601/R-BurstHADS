"""
Round C results pack. Reads committed result files only; runs no simulation.

    python experiments\\results_pack.py          -> writes RESULTS_PACK.md

Every table names its source files; the Sources table gives each file's
SHA-256 and the commit that last changed it. Conventions: a cell is
(scenario, n, DF); cell values are means over seeds; "% vs X" is the ratio
of cell means, averaged over cells (the convention of sweep_analysis.py);
95% CIs use Student's t over seeds; R vs Burst-HADS significance is a paired
per-seed CI (same seed = same tasks and hibernation draws).
"""
import sys, json, math, hashlib, subprocess
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import tcc23_tables as tt
import models.limits as lim

FP = "4f08f48ac35c"
SRC = {
    "on":        f"experiments/sweep_raw_{FP}.jsonl",
    "off":       f"experiments/sweep_variant_nocap_{FP}.jsonl",
    "val_off":   "experiments/diag_cost_gap_freeze_nocap_c3.json",
    "val_on":    "experiments/diag_cost_gap_freeze_capped_c3.json",
    "grid_g1e1": "experiments/sweep_variant_grid_g1e1_519c868a99f9.jsonl",
    "grid_g0e1": "experiments/sweep_variant_grid_g0e1_519c868a99f9.jsonl",
    "vgrid_g1e1": "experiments/diag_cost_gap_nocap_grid_g1e1_c3.json",
    "vgrid_g0e1": "experiments/diag_cost_gap_nocap_grid_g0e1_c3.json",
    "a_pre":     "experiments/diag_cost_gap_nocap_c3.json",
    "a_mig":     "experiments/diag_cost_gap_nocap_mig_launched_c3.json",
    "a_bill":    "experiments/diag_cost_gap_nocap_mig_launched_launch_bill_c3.json",
    "a_norel":   "experiments/diag_cost_gap_nocap_no_release_c3.json",
    "adopt_val": "experiments/diag_cost_gap_rb1_verify_c3.json",
    "adopt_sweep": "experiments/sweep_variant_base_2c6576897779.jsonl",
    # Round B-era frozen baseline (freeze-round-b), used by historical tables
    "raw_rb":    "experiments/sweep_raw_4f08f48ac35c.jsonl",
    "val_rb":    "experiments/diag_cost_gap_freeze_nocap_c3.json",
    # U10 diagnostic, fix 17 and fixes 18-20 (post-freeze round)
    "u10_trace": "experiments/diag_u10.json",
    "u10_window": "experiments/diag_u10_window.txt",
    "adopt2_verify": "experiments/fix17a_18_20_adoption_verify.txt",
    "u10_verify": "experiments/diag_u10_verify.txt",
    "overcredit": "experiments/diag_overcredit_boot.json",
    "f17a": "experiments/sweep_variant_f17a_4f08f48ac35c.jsonl",
    "f17b": "experiments/sweep_variant_f17b_4f08f48ac35c.jsonl",
    "f17c": "experiments/sweep_variant_f17c_4f08f48ac35c.jsonl",
    "f17ab": "experiments/sweep_variant_f17ab_4f08f48ac35c.jsonl",
    "f17abc": "experiments/sweep_variant_f17abc_4f08f48ac35c.jsonl",
    "boot_wait": "experiments/sweep_variant_boot_wait_4f08f48ac35c.jsonl",
    "ckpt_exec": "experiments/sweep_variant_ckpt_exec_4f08f48ac35c.jsonl",
    "u10_ovh": "experiments/sweep_variant_u10_ovh_4f08f48ac35c.jsonl",
    "boot_u10": "experiments/sweep_variant_boot_u10_4f08f48ac35c.jsonl",
    "fx_all": "experiments/sweep_variant_fx_all_4f08f48ac35c.jsonl",
    "fx_no17a": "experiments/sweep_variant_fx_no17a_4f08f48ac35c.jsonl",
    "fx_no18": "experiments/sweep_variant_fx_no18_4f08f48ac35c.jsonl",
    "fx_no19": "experiments/sweep_variant_fx_no19_4f08f48ac35c.jsonl",
    "fx_no20": "experiments/sweep_variant_fx_no20_4f08f48ac35c.jsonl",
    "tcc23":     "experiments/tcc23_tables.py",
    "devs":      "DEVIATIONS.md",
    "cat_sweep": "main.py",
    "cat_val":   "experiments/paper_reproduction.py",
}
KEYS = ("hads", "burst", "rburst")
LAB = {"hads": "HADS", "burst": "Burst-HADS", "rburst": "R-BurstHADS"}
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
       9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
       17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
       25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}
OUT = []


def w(s=""):
    OUT.append(s)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def ci(xs):
    xs = list(xs)
    n = len(xs)
    m = mean(xs)
    if n < 2:
        return m, float("nan"), n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, T95[n - 1] * sd / math.sqrt(n), n


def pct(a, b):
    return 100.0 * (a - b) / b


def ok(r):
    return r is not None and r.get("error") is None and not r.get("infeasible")


def load_jsonl(rel):
    d = {}
    for line in open(ROOT / rel, encoding="utf-8"):
        r = json.loads(line)
        d[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = r   # a retried unit's last row wins
    return d


def cells_of(d):
    c = defaultdict(lambda: defaultdict(dict))
    for (sc, n, df, seed, k), r in d.items():
        c[(sc, n, df)][seed][k] = r
    return c


def complete(seeds):
    return all(ok(s.get(k)) for s in seeds.values() for k in KEYS)


def cell_stats(seeds):
    st = {}
    for k in KEYS:
        rs = [s[k] for s in seeds.values() if ok(s.get(k))]
        st[k] = dict(mk=ci(r["mk"] for r in rs), cost=ci(r["cost"] for r in rs),
                     mkd=mean(r["mk_frac"] for r in rs), n=len(rs))
    pairs = [(s["rburst"], s["burst"]) for s in seeds.values() if ok(s.get("rburst")) and ok(s.get("burst"))]
    st["rb_mk"] = ci(a["mk"] - b["mk"] for a, b in pairs)
    st["rb_cost"] = ci(a["cost"] - b["cost"] for a, b in pairs)
    one = next(iter(seeds.values()))
    anyrow = next(iter(one.values()))
    st["D"], st["floored"] = anyrow["D"], anyrow.get("floored")
    return st


def group_row(stats, cells):
    S = [stats[c] for c in cells]
    m = lambda s, k, f: s[k][f][0]
    return dict(
        cells=len(S),
        hmkd=100 * mean(s["hads"]["mkd"] for s in S),
        bmk=mean(pct(m(s, "burst", "mk"), m(s, "hads", "mk")) for s in S),
        bc=mean(pct(m(s, "burst", "cost"), m(s, "hads", "cost")) for s in S),
        rmk=mean(pct(m(s, "rburst", "mk"), m(s, "hads", "mk")) for s in S),
        rc=mean(pct(m(s, "rburst", "cost"), m(s, "hads", "cost")) for s in S),
        rbmk=mean(pct(m(s, "rburst", "mk"), m(s, "burst", "mk")) for s in S),
        rbc=mean(pct(m(s, "rburst", "cost"), m(s, "burst", "cost")) for s in S),
        dom=sum(1 for s in S if m(s, "rburst", "mk") <= m(s, "burst", "mk") and m(s, "rburst", "cost") <= m(s, "burst", "cost")),
        fast=sum(1 for s in S if s["rb_mk"][0] + s["rb_mk"][1] < 0),
        slow=sum(1 for s in S if s["rb_mk"][0] - s["rb_mk"][1] > 0),
        cheap=sum(1 for s in S if s["rb_cost"][0] + s["rb_cost"][1] < 0),
        dear=sum(1 for s in S if s["rb_cost"][0] - s["rb_cost"][1] > 0),
    )


def summary_table(d, title, ident, source):
    cells = cells_of(d)
    stats = {c: cell_stats(s) for c, s in cells.items()}
    comp = sorted(c for c, s in cells.items() if complete(s))
    w(f"### {ident}. {title}")
    w()
    w(f"Source: `{source}`. Cells where every scheduler is feasible in every seed: **{len(comp)} of {len(cells)}**. "
      "Columns: HADS makespan as % of D; Burst-HADS (B) and R-BurstHADS (R) vs HADS; R vs B; "
      "cells where R dominates B on both means; cells where the paired per-seed 95% CI of R − B excludes 0 "
      "(faster / slower, cheaper / dearer).")
    w()
    w("| group | cells | HADS mk/D | B mk vs H | B $ vs H | R mk vs H | R $ vs H | R mk vs B | R $ vs B | R dominates B | R sig. faster / slower | R sig. cheaper / dearer |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    groups = [("all", lambda c: True)]
    groups += [(f"DF={x}", (lambda x: lambda c: c[2] == x)(x)) for x in sorted({c[2] for c in comp})]
    groups += [(sc, (lambda x: lambda c: c[0] == x)(sc)) for sc in sorted({c[0] for c in comp})]
    groups += [(f"n={x}", (lambda x: lambda c: c[1] == x)(x)) for x in sorted({c[1] for c in comp})]
    rows = {}
    for name, sel in groups:
        g = group_row(stats, [c for c in comp if sel(c)])
        rows[name] = g
        w(f"| {name} | {g['cells']} | {g['hmkd']:.0f}% | {g['bmk']:+.1f}% | {g['bc']:+.1f}% | {g['rmk']:+.1f}% | {g['rc']:+.1f}% | "
          f"{g['rbmk']:+.1f}% | {g['rbc']:+.1f}% | {g['dom']}/{g['cells']} | {g['fast']} / {g['slow']} | {g['cheap']} / {g['dear']} |")
    if len(comp) < len(cells):
        g = group_row(stats, sorted(cells))
        rows["all cells, available seeds"] = g
        w(f"| all {len(cells)} cells, feasible seeds only | {g['cells']} | {g['hmkd']:.0f}% | {g['bmk']:+.1f}% | {g['bc']:+.1f}% | "
          f"{g['rmk']:+.1f}% | {g['rc']:+.1f}% | {g['rbmk']:+.1f}% | {g['rbc']:+.1f}% | {g['dom']}/{g['cells']} | "
          f"{g['fast']} / {g['slow']} | {g['cheap']} / {g['dear']} |")
    w()
    return stats, rows


def cell_ci_table(d, ident, title, source):
    cells = cells_of(d)
    stats = {c: cell_stats(s) for c, s in cells.items()}
    w(f"### {ident}. {title}")
    w()
    w(f"Source: `{source}`. Mean ± 95% CI half-width over seeds (n = 30 unless marked). "
      "Makespan in seconds, cost in US$. `*` = deadline set by the floor.")
    w()
    w("| scenario | n | DF | D (s) | HADS mk | Burst-HADS mk | R-BurstHADS mk | HADS $ | Burst-HADS $ | R-BurstHADS $ |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    sc_order = sorted({c[0] for c in cells})
    for c in sorted(cells, key=lambda c: (sc_order.index(c[0]), c[1], c[2])):
        s = stats[c]
        cellf = lambda k, f, fmt: (f"{s[k][f][0]:{fmt}} ± {s[k][f][1]:{fmt}}" + (f" (n={s[k]['n']})" if s[k]["n"] != 30 else ""))
        w(f"| {c[0]} | {c[1]} | {c[2]} | {s['D']:.1f}{'*' if s['floored'] else ''} | "
          f"{cellf('hads', 'mk', '.0f')} | {cellf('burst', 'mk', '.0f')} | {cellf('rburst', 'mk', '.0f')} | "
          f"{cellf('hads', 'cost', '.4f')} | {cellf('burst', 'cost', '.4f')} | {cellf('rburst', 'cost', '.4f')} |")
    w()


def misses_table(d_on, d_off):
    w("### T5. Deadline misses, both measures")
    w()
    w(f"Sources: `{SRC['on']}` (limits on), `{SRC['off']}` (limits off). Feasible runs only. "
      "Missed tasks = tasks finishing after D, summed; share of tasks is over all tasks in feasible runs.")
    w()
    w("| limits | scheduler | feasible runs | runs with ≥1 miss | share of runs | missed tasks | share of tasks | missed tasks at DF 0.25 / 0.5 / 1.0 / 2.0 |")
    w("|---|---|---|---|---|---|---|---|")
    res = {}
    for label, d in (("on", d_on), ("off", d_off)):
        for k in KEYS:
            rs = [(u, r) for u, r in d.items() if u[4] == k and ok(r)]
            runs = len(rs)
            wm = sum(1 for _, r in rs if r["misses"] > 0)
            mt = sum(r["misses"] for _, r in rs)
            tasks = sum(u[1] for u, _ in rs)
            bydf = [sum(r["misses"] for u, r in rs if u[2] == x) for x in (0.25, 0.5, 1.0, 2.0)]
            res[(label, k)] = dict(runs=runs, with_miss=wm, tasks_missed=mt, tasks=tasks)
            w(f"| {label} | {LAB[k]} | {runs} | {wm} | {100 * wm / runs:.1f}% | {mt} | {100 * mt / tasks:.3f}% | {' / '.join(map(str, bydf))} |")
    w()
    w("R-BurstHADS, limits on — every cell with a missed task:")
    w()
    w("| scenario | n | DF | runs with a miss (of 30) | missed tasks | mean per run | limits off: missed tasks |")
    w("|---|---|---|---|---|---|---|")
    cells = defaultdict(list)
    for u, r in d_on.items():
        if u[4] == "rburst" and ok(r):
            cells[u[:3]].append((u, r))
    for c in sorted(cells):
        rs = cells[c]
        mt = sum(r["misses"] for _, r in rs)
        if mt == 0:
            continue
        off = sum(d_off[u]["misses"] for u, _ in rs if ok(d_off.get(u)))
        w(f"| {c[0]} | {c[1]} | {c[2]} | {sum(1 for _, r in rs if r['misses'])} | {mt} | {mt / len(rs):.2f} | {off} |")
    w()
    return res


def infeasible_table(d_on, d_off):
    w("### T6. Infeasible runs, with cause")
    w()
    w(f"Sources: `{SRC['on']}`, `{SRC['off']}`. An infeasible run is one whose primary scheduler found no placement "
      "within D and the instance limits (`NoFeasibleSchedule`, the reference raises the same). They are excluded from "
      "cell means that compare schedulers and are reported here.")
    w()
    for label, d in (("limits on", d_on), ("limits off", d_off)):
        inf = sorted(((u, r) for u, r in d.items() if r.get("infeasible")), key=lambda x: x[0])
        w(f"**{label}: {len(inf)} infeasible runs** of {len(d)}.")
        w()
        if inf:
            w("| scheduler | scenario | n | DF | seed | D (s) | cause |")
            w("|---|---|---|---|---|---|---|")
            for u, r in inf:
                w(f"| {LAB[u[4]]} | {u[0]} | {u[1]} | {u[2]} | {u[3]} | {r['D']:.1f}{' (floor)' if r.get('floored') else ''} | {r.get('infeasible_reason')} |")
            w()
    return sum(1 for r in d_on.values() if r.get("infeasible")), sum(1 for r in d_off.values() if r.get("infeasible"))


def limit_reached(r):
    counts = r.get("launched") or {}
    tot = defaultdict(int)
    hit = []
    for key, c in counts.items():
        mkt, typ = key.split(":", 1)
        tot[mkt] += c
        if c >= lim.PER_TYPE.get(mkt, 10 ** 9):
            hit.append(key)
    for mkt, t in tot.items():
        if t >= lim.GLOBAL.get(mkt, 10 ** 9):
            hit.append(f"{mkt}:GLOBAL")
    return hit


def attribution_table(d_on, d_off):
    w("### T7. Launch limits reached, in runs with and without a missed task")
    w()
    w("Reaching a launch limit does not identify the cause of a miss. At `freeze-round-b` (`4f08f48ac35c`) the placement "
      "trace attributes R-BurstHADS's 109 misses to its own saturation response, which reaching a limit triggers (T21); "
      "fix 17a removes 108 of them (T18).")
    w()
    w(f"Sources: `{SRC['on']}`, `{SRC['off']}`. A run 'reached a limit' if some instance type hit its per-type launch "
      f"limit ({lim.PER_TYPE}) or a market hit its global limit ({lim.GLOBAL}); launches are counted per run in the "
      "`launched` field. Burstables count as on-demand.")
    w()
    w("| scheduler | runs | reached a limit | of runs with a miss: reached a limit | of runs without a miss: reached a limit | same units, limits off: missed tasks | most frequent limits reached in missing runs |")
    w("|---|---|---|---|---|---|---|")
    res = {}
    for k in KEYS:
        rs = [(u, r) for u, r in d_on.items() if u[4] == k and ok(r)]
        miss = [(u, r) for u, r in rs if r["misses"] > 0]
        clean = [(u, r) for u, r in rs if r["misses"] == 0]
        hm = sum(1 for _, r in miss if limit_reached(r))
        hc = sum(1 for _, r in clean if limit_reached(r))
        off = sum(d_off[u]["misses"] for u, _ in miss if ok(d_off.get(u)))
        freq = defaultdict(int)
        for _, r in miss:
            for h in limit_reached(r):
                freq[h] += 1
        top = ", ".join(f"{h} ({c})" for h, c in sorted(freq.items(), key=lambda x: -x[1])[:4]) or "—"
        hr = sum(1 for _, r in rs if limit_reached(r))
        res[k] = dict(miss_runs=len(miss), miss_hit=hm, clean_runs=len(clean), clean_hit=hc, off=off)
        w(f"| {LAB[k]} | {len(rs)} | {hr} ({100 * hr / len(rs):.1f}%) | {hm} of {len(miss)} | "
          f"{hc} of {len(clean)} ({100 * hc / max(1, len(clean)):.1f}%) | {off} | {top} |")
    w()
    return res


# ------------------------------------------------------------------ validation
def diag_by(rel):
    d = json.load(open(ROOT / rel, encoding="utf-8"))
    by = defaultdict(list)
    for r in d["rows"]:
        if r["ok"]:
            by[(r["job"], r["sc"], r["key"])].append(r)
    return by


def vstats(by, rule="R0"):
    J, S = tt.JOBS, tt.SCENARIOS
    c = lambda j, sc, k: mean(r["cost"][rule] for r in by[(j, sc, k)])
    m = lambda j, sc, k: mean(r["mk"] for r in by[(j, sc, k)])
    h = lambda j, sc, k: mean(r["counts"]["hib"] for r in by[(j, sc, k)])
    cells = [(j, sc) for j in J for sc in S]
    return dict(
        cost_change=mean(pct(c(j, sc, "burst"), c(j, sc, "hads")) for j, sc in cells),
        mk_red=mean(-pct(m(j, sc, "burst"), m(j, sc, "hads")) for j, sc in cells),
        mk_red_j60=mean(-pct(m("J60", sc, "burst"), m("J60", sc, "hads")) for sc in S),
        mk_red_ed200=mean(-pct(m("ED200", sc, "burst"), m("ED200", sc, "hads")) for sc in S),
        prem_h=mean(pct(c(j, sc, "hads"), c(j, "none", "hads")) for j, sc in cells),
        prem_b=mean(pct(c(j, sc, "burst"), c(j, "none", "burst")) for j, sc in cells),
        prem_sc={k: {sc: mean(pct(c(j, sc, k), c(j, "none", k)) for j in J) for sc in S} for k in ("hads", "burst")},
        hib_sc={k: {sc: mean(h(j, sc, k) for j in J) for sc in S} for k in ("hads", "burst")},
        t7={j: dict(mk_h=ci(r["mk"] for r in by[(j, "none", "hads")]), mk_b=ci(r["mk"] for r in by[(j, "none", "burst")]),
                    c_h=ci(r["cost"]["R0"] for r in by[(j, "none", "hads")]), c_b=ci(r["cost"]["R0"] for r in by[(j, "none", "burst")]))
            for j in J},
        cell=lambda j, sc, k, f: ci((r["cost"]["R0"] if f == "cost" else r["mk"]) for r in by[(j, sc, k)]),
        misses={k: sum(r["misses"] for (j, sc, kk), rs in by.items() if kk == k for r in rs) for k in ("hads", "burst")},
    )


def tcc23_published():
    J, S = tt.JOBS, tt.SCENARIOS
    cells = [(j, sc) for j in J for sc in S]
    return dict(
        cost_change=-mean(tt.T9[x]["diff_hads_cost"] for x in cells),
        mk_red=mean(tt.T9[x]["diff_hads_mk"] for x in cells),
        mk_red_j60=mean(tt.T9[("J60", sc)]["diff_hads_mk"] for sc in S),
        mk_red_ed200=mean(tt.T9[("ED200", sc)]["diff_hads_mk"] for sc in S),
        prem_h=mean(pct(tt.T9[x]["hads_cost"], tt.T7[x[0]]["hads"][0]) for x in cells),
        prem_b=mean(pct(tt.T9[x]["burst_cost"], tt.T7[x[0]]["burst"][0]) for x in cells),
        prem_sc={k: {sc: mean(pct(tt.T9[(j, sc)][f"{k}_cost"], tt.T7[j][k][0]) for j in J) for sc in S} for k in ("hads", "burst")},
        hib_sc={sc: mean(tt.T9[(j, sc)]["hib"] for j in J) for sc in S},
    )


def validation_tables():
    off, on = vstats(diag_by(SRC["val_off"])), vstats(diag_by(SRC["val_on"]))
    pub = tcc23_published()
    w("### T8. Validation against TCC23 Table 7 (no hibernation)")
    w()
    w(f"Sources: `{SRC['val_off']}` (paper catalogue = TCC23 Table 3, Table 6 workload, 3 spot copies per type, 30 seeds, "
      f"limits off, the paper's setting), `{SRC['tcc23']}` (Table 7 as printed). Mean ± 95% CI.")
    w()
    w("| job | HADS mk ours | TCC23 | Burst-HADS mk ours | TCC23 | mk change ours | TCC23 | HADS $ ours | TCC23 | Burst-HADS $ ours | TCC23 | cost change ours | TCC23 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for j in tt.JOBS:
        t = off["t7"][j]
        p = tt.T7[j]
        w(f"| {j} | {t['mk_h'][0]:.0f} ± {t['mk_h'][1]:.0f} | {p['hads'][1]} | {t['mk_b'][0]:.0f} ± {t['mk_b'][1]:.0f} | {p['burst'][1]} | "
          f"{pct(t['mk_b'][0], t['mk_h'][0]):+.1f}% | {pct(p['burst'][1], p['hads'][1]):+.1f}% | "
          f"{t['c_h'][0]:.3f} ± {t['c_h'][1]:.3f} | {p['hads'][0]:.3f} | {t['c_b'][0]:.3f} ± {t['c_b'][1]:.3f} | {p['burst'][0]:.3f} | "
          f"{pct(t['c_b'][0], t['c_h'][0]):+.1f}% | {pct(p['burst'][0], p['hads'][0]):+.1f}% |")
    w()
    w("### T9. Validation against TCC23 Table 9 (hibernation, sc1–sc5, 20 cells)")
    w()
    w(f"Sources: `{SRC['val_off']}`, `{SRC['val_on']}`, `{SRC['tcc23']}` (Table 9 transcribed; its 20 cells reproduce the "
      "four aggregates in TCC23's text to two decimals). Same definition for ours and TCC23: per-cell change, plain mean "
      "over the 20 cells. Premium = cost under hibernation vs the same scheduler without.")
    w()
    w("| quantity | ours, limits off | ours, limits on | TCC23 |")
    w("|---|---|---|---|")
    for name, key, fmt in (("Burst-HADS cost change vs HADS", "cost_change", "+.2f"),
                           ("Burst-HADS makespan reduction vs HADS", "mk_red", ".2f"),
                           ("  J60 only", "mk_red_j60", ".2f"), ("  ED200 only", "mk_red_ed200", ".2f"),
                           ("HADS hibernation premium", "prem_h", "+.0f"), ("Burst-HADS hibernation premium", "prem_b", "+.0f")):
        w(f"| {name} | {off[key]:{fmt}}% | {on[key]:{fmt}}% | {pub[key]:{fmt}}% |")
    w()
    w("By scenario (limits off): hibernation premium and hibernations per run, mean over jobs.")
    w()
    w("| scenario (kh, kr) | HADS premium ours | TCC23 | Burst-HADS premium ours | TCC23 | hibernations/run ours (HADS / Burst-HADS runs) | TCC23 |")
    w("|---|---|---|---|---|---|---|")
    khkr = {"sc1": "1, 0", "sc2": "5, 0", "sc3": "1, 5", "sc4": "5, 5", "sc5": "3, 2.5"}
    for sc in tt.SCENARIOS:
        w(f"| {sc} ({khkr[sc]}) | {off['prem_sc']['hads'][sc]:+.0f}% | {pub['prem_sc']['hads'][sc]:+.0f}% | "
          f"{off['prem_sc']['burst'][sc]:+.0f}% | {pub['prem_sc']['burst'][sc]:+.0f}% | "
          f"{off['hib_sc']['hads'][sc]:.1f} / {off['hib_sc']['burst'][sc]:.1f} | {pub['hib_sc'][sc]:.2f} |")
    w()
    w(f"Missed tasks in the validation runs (limits off): HADS {off['misses']['hads']}, Burst-HADS {off['misses']['burst']}.")
    w()
    w("### T10. Validation, cell by cell against TCC23 Table 9 (limits off)")
    w()
    w(f"Sources: `{SRC['val_off']}`, `{SRC['tcc23']}`. Ours: mean ± 95% CI over 30 seeds; TCC23: mean of three executions.")
    w()
    w("| job | scenario | Burst-HADS $ ours | TCC23 | HADS $ ours | TCC23 | Burst-HADS mk ours | TCC23 | HADS mk ours | TCC23 | B vs H cost ours | TCC23 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for j in tt.JOBS:
        for sc in tt.SCENARIOS:
            p = tt.T9[(j, sc)]
            bc, hc = off["cell"](j, sc, "burst", "cost"), off["cell"](j, sc, "hads", "cost")
            bm, hm = off["cell"](j, sc, "burst", "mk"), off["cell"](j, sc, "hads", "mk")
            w(f"| {j} | {sc} | {bc[0]:.3f} ± {bc[1]:.3f} | {p['burst_cost']:.3f} | {hc[0]:.3f} ± {hc[1]:.3f} | {p['hads_cost']:.3f} | "
              f"{bm[0]:.0f} ± {bm[1]:.0f} | {p['burst_mk']} | {hm[0]:.0f} ± {hm[1]:.0f} | {p['hads_mk']} | "
              f"{pct(bc[0], hc[0]):+.1f}% | {-p['diff_hads_cost']:+.1f}% |")
    w()
    return off, on, pub


def audit_trajectory(pub):
    w("### T11. Fidelity audit trajectory on the validation catalogue (limits off)")
    w()
    w("How the baseline changes adopted in Rounds A–B moved the validation numbers. Each row is a committed run of the "
      "same 1,440 units (4 jobs × 6 scenarios × 30 seeds × 2 schedulers). Fix numbers and deviation IDs refer to "
      "CLAUDE.md and DEVIATIONS.md.")
    w()
    w("| state | source | B vs H cost (Table 9) | makespan reduction | HADS premium | Burst-HADS premium | J60 no-hib mk change | J60 no-hib cost change |")
    w("|---|---|---|---|---|---|---|---|")
    rows = [("before Round B (fixes 1–12)", "a_pre"), ("+ launched-only migration (U6/H2)", "a_mig"),
            ("+ billing from launch (B1)", "a_bill"), ("+ Allocation Cycles over uptime (E10) = Round B part 1", "vgrid_g1e1"),
            ("+ on-demand catalogue (E1/E3) = freeze-round-b", "val_rb")]
    if SRC["val_off"] != SRC["val_rb"]:
        rows.append(("+ fixes 17a, 18, 19, 20 = current baseline", "val_off"))
    out = {}
    for name, key in rows:
        s = vstats(diag_by(SRC[key]))
        t = s["t7"]["J60"]
        out[key] = s
        w(f"| {name} | `{SRC[key]}` | {s['cost_change']:+.1f}% | {s['mk_red']:.1f}% | {s['prem_h']:+.0f}% | {s['prem_b']:+.0f}% | "
          f"{pct(t['mk_b'][0], t['mk_h'][0]):+.1f}% | {pct(t['c_b'][0], t['c_h'][0]):+.1f}% |")
    p7 = tt.T7["J60"]
    w(f"| TCC23 | `{SRC['tcc23']}` | {pub['cost_change']:+.1f}% | {pub['mk_red']:.1f}% | {pub['prem_h']:+.0f}% | {pub['prem_b']:+.0f}% | "
      f"{pct(p7['burst'][1], p7['hads'][1]):+.1f}% | {pct(p7['burst'][0], p7['hads'][0]):+.1f}% |")
    w()
    return out


def guard_tables():
    w("### T12. Disclosure: the retained proactive-burstable guard (DEVIATIONS U5)")
    w()
    w(f"Sources: `{SRC['grid_g1e1']}` (guard on) and `{SRC['grid_g0e1']}` (guard off), both with billing from launch, "
      "Allocation Cycles over uptime and launched-only migration, sweep catalogue, limits on, seeds 0–9; "
      f"`{SRC['vgrid_g1e1']}` and `{SRC['vgrid_g0e1']}` (validation catalogue, limits off). Decision rule pre-registered "
      "in `experiments/round_a_grid_plan.md` (commit ec52967): the guard is kept iff removing it turns more runs "
      "with no missed task into runs with one than the reverse, for Burst-HADS or R-BurstHADS, in either catalogue.")
    w()
    on, off = load_jsonl(SRC["grid_g1e1"]), load_jsonl(SRC["grid_g0e1"])
    units = [u for u in on if ok(on[u]) and ok(off.get(u))]
    w("| catalogue | scheduler | paired runs | 0 → ≥1 missed (guard protects) | ≥1 → 0 (guard harms) | missed tasks with / without | mean makespan with / without |")
    w("|---|---|---|---|---|---|---|")
    res = {}
    for k in ("burst", "rburst"):
        us = [u for u in units if u[4] == k]
        prot = sum(1 for u in us if on[u]["misses"] == 0 and off[u]["misses"] > 0)
        harm = sum(1 for u in us if on[u]["misses"] > 0 and off[u]["misses"] == 0)
        mon, moff = mean(on[u]["mk"] for u in us), mean(off[u]["mk"] for u in us)
        res[k] = dict(prot=prot, harm=harm)
        w(f"| sweep | {LAB[k]} | {len(us)} | {prot} | {harm} | {sum(on[u]['misses'] for u in us)} / {sum(off[u]['misses'] for u in us)} | "
          f"{mon:.0f} / {moff:.0f} s ({pct(moff, mon):+.1f}%) |")
    von, voff = diag_by(SRC["vgrid_g1e1"]), diag_by(SRC["vgrid_g0e1"])
    vr_on = {(j, sc, r["seed"]): r for (j, sc, k), rs in von.items() if k == "burst" for r in rs}
    vr_off = {(j, sc, r["seed"]): r for (j, sc, k), rs in voff.items() if k == "burst" for r in rs}
    vu = [u for u in vr_on if u in vr_off]
    vp = sum(1 for u in vu if vr_on[u]["misses"] == 0 and vr_off[u]["misses"] > 0)
    vh = sum(1 for u in vu if vr_on[u]["misses"] > 0 and vr_off[u]["misses"] == 0)
    vmon, vmoff = mean(vr_on[u]["mk"] for u in vu), mean(vr_off[u]["mk"] for u in vu)
    w(f"| validation | Burst-HADS | {len(vu)} | {vp} | {vh} | {sum(vr_on[u]['misses'] for u in vu)} / {sum(vr_off[u]['misses'] for u in vu)} | "
      f"{vmon:.0f} / {vmoff:.0f} s ({pct(vmoff, vmon):+.1f}%) |")
    w()
    w("What the guard does to the comparison (sweep catalogue, cells where every scheduler is feasible in every seed of both files):")
    w()
    w("| guard | cells | R vs B makespan | R vs B cost | R dominates B | Burst-HADS hibernation premium, validation catalogue |")
    w("|---|---|---|---|---|---|")
    cells_on, cells_off = cells_of(on), cells_of(off)
    comp = sorted(c for c in cells_on if complete(cells_on[c]) and c in cells_off and complete(cells_off[c]))
    vprem = {"on": vstats(von)["prem_b"], "off": vstats(voff)["prem_b"]}
    for label, cells, key in (("kept (frozen code)", cells_on, "on"), ("removed", cells_off, "off")):
        g = group_row({c: cell_stats(cells[c]) for c in comp}, comp)
        w(f"| {label} | {g['cells']} | {g['rbmk']:+.1f}% | {g['rbc']:+.1f}% | {g['dom']}/{g['cells']} | {vprem[key]:+.0f}% |")
    w()
    return res


def part2_table(d_on):
    w("### T13. Effect of the three-type on-demand catalogue alone (DEVIATIONS E1/E3), main sweep, limits on, seeds 0–9")
    w()
    w(f"Sources: `{SRC['grid_g1e1']}` (Round B part 1 only) and `{SRC['raw_rb']}` restricted to seeds 0–9 (part 1 + part 2 = freeze-round-b code). Historical.")
    w()
    a = load_jsonl(SRC["grid_g1e1"])
    b = {u: r for u, r in load_jsonl(SRC["raw_rb"]).items() if u[3] <= 9}
    keys = sorted(set(a) & set(b))
    w("| state | infeasible runs H / B / R | missed tasks H / B / R | missed tasks at DF=0.5 H / B / R |")
    w("|---|---|---|---|")
    for label, rows in (("part 1 only (one on-demand type)", a), ("frozen code (three on-demand types)", b)):
        inf = [sum(1 for u in keys if u[4] == k and rows[u].get("infeasible")) for k in KEYS]
        mt = [sum(rows[u]["misses"] for u in keys if u[4] == k and ok(rows[u])) for k in KEYS]
        m5 = [sum(rows[u]["misses"] for u in keys if u[4] == k and u[2] == 0.5 and ok(rows[u])) for k in KEYS]
        w(f"| {label} | {' / '.join(map(str, inf))} | {' / '.join(map(str, mt))} | {' / '.join(map(str, m5))} |")
    w()


def cause_tables(pub):
    w("### T14. Round A: what the hibernation cost gap is NOT (aggregation, billing rule, EBS)")
    w()
    w(f"Sources: `{SRC['a_pre']}` (state before Round B: fixes 1–12, limits off; every run's cost recomputed per VM under "
      f"each rule by `experiments/diag_cost_gap.py` and stored in the file), `{SRC['a_norel']}` (the pre-fix-2/3 billing: "
      "no end-of-run release, open intervals clamped at makespan), `tcc23_tables.py`. "
      "Rules: R0 = the simulator's billing at that state (first task to shutdown or hibernation); AC = every billing "
      "interval rounded up to 900 s; LAUNCH = also charged from launch; NOPHANT = without VMs billed only through a "
      "resume; PAPER = LAUNCH and NOPHANT (TCC23 §3.1); EBSHIB / EBSALL = R0 plus $0.10/GB-month on 8 GB + RAM while "
      "hibernated / while billed or hibernated; PRE2 = pre-fix-2 rule.")
    w()
    by = diag_by(SRC["a_pre"])
    w("| aggregation of Burst-HADS vs HADS cost change (rule R0) | value |")
    w("|---|---|")
    cells = [(j, sc) for j in tt.JOBS for sc in tt.SCENARIOS]
    cm = lambda j, sc, k: mean(r["cost"]["R0"] for r in by[(j, sc, k)])
    per_cell = [pct(cm(j, sc, "burst"), cm(j, sc, "hads")) for j, sc in cells]
    pooled = pct(sum(cm(j, sc, "burst") for j, sc in cells), sum(cm(j, sc, "hads") for j, sc in cells))
    bseed = {(r["job"], r["sc"], r["seed"]): r for (j, sc, k), rs in by.items() if k == "burst" for r in rs}
    hseed = {(r["job"], r["sc"], r["seed"]): r for (j, sc, k), rs in by.items() if k == "hads" for r in rs}
    per_run = [pct(bseed[u]["cost"]["R0"], hseed[u]["cost"]["R0"]) for u in bseed if u in hseed and u[1] != "none"]
    srt = sorted(per_cell)
    med = (srt[9] + srt[10]) / 2
    for name, v in (("mean of 20 per-cell changes (TCC23's definition)", mean(per_cell)), ("change of pooled totals", pooled),
                    ("mean of per-run paired changes", mean(per_run)), ("median of per-cell changes", med),
                    ("TCC23", pub["cost_change"])):
        w(f"| {name} | {v:+.1f}% |")
    w()
    w("| billing rule | Burst-HADS vs HADS cost change (20 cells) | HADS premium | Burst-HADS premium | no-hibernation cost change, mean of 4 jobs |")
    w("|---|---|---|---|---|")
    def nohib(bb, rule):
        cc = lambda j, k: mean(r["cost"][rule] for r in bb[(j, "none", k)])
        return mean(pct(cc(j, "burst"), cc(j, "hads")) for j in tt.JOBS)
    for rule in ("R0", "AC", "LAUNCH", "NOPHANT", "PAPER", "EBSHIB", "EBSALL"):
        s = vstats(by, rule)
        w(f"| {rule} | {s['cost_change']:+.1f}% | {s['prem_h']:+.0f}% | {s['prem_b']:+.0f}% | {nohib(by, rule):+.1f}% |")
    bn = diag_by(SRC["a_norel"])
    s = vstats(bn, "PRE2")
    w(f"| PRE2 (no end-of-run release) | {s['cost_change']:+.1f}% | {s['prem_h']:+.0f}% | {s['prem_b']:+.0f}% | {nohib(bn, 'PRE2'):+.1f}% |")
    tb = mean(pct(tt.T7[j]["burst"][0], tt.T7[j]["hads"][0]) for j in tt.JOBS)
    w(f"| TCC23 | {pub['cost_change']:+.1f}% | {pub['prem_h']:+.0f}% | {pub['prem_b']:+.0f}% | {tb:+.1f}% |")
    w()


def economics_table():
    import main as m
    from experiments import paper_reproduction as pr
    from models.vm import VM
    w("### T15. Price per unit of work in each catalogue (frozen code)")
    w()
    w(f"Sources: `{SRC['cat_sweep']}` (`build_vms_dburst`, the sweep catalogue) and `{SRC['cat_val']}` (`build_vms_paper`, "
      "the validation catalogue = TCC23 Table 3), read by constructing the VM lists — no simulation. Units/h = per-core "
      "speed × usable slots; the VM model gives a burstable one slot (TCC23's one-task rule). "
      "$/unit (1 task) = what a task pays running alone on the VM.")
    w()
    w("| catalogue | type | market | speed | slots | $/h | $/unit, full | $/unit, 1 task |")
    w("|---|---|---|---|---|---|---|---|")
    ratios = {}
    for name, vms in (("sweep", m.build_vms_dburst()), ("validation", pr.build_vms_paper(1))):
        seen = set()
        rows = []
        for v in vms:
            if (v.vm_type, v.market) in seen:
                continue
            seen.add((v.vm_type, v.market))
            rate = v.cost_rate * 3600
            rows.append((v, rate, rate / (v.speed * v.vcpu_count), rate / v.speed))
        for v, rate, full, one in sorted(rows, key=lambda x: x[2]):
            w(f"| {name} | {v.vm_type} | {v.market} | {v.speed:g} | {v.vcpu_count} | {rate:.4f} | {full:.5f} | {one:.5f} |")
        b = next(x for x in rows if x[0].market == VM.BURSTABLE)
        od = min((x for x in rows if x[0].market == VM.ONDEMAND), key=lambda x: x[3])
        ratios[name] = (b[2] / od[3], od[0].vm_type)
    w()
    for name, (r, t) in ratios.items():
        w(f"- {name}: a burst-mode task on the burstable pays {r:.2f}× what it pays alone on a new {t} on-demand VM "
          "(Algorithm 4 Attempt 3's alternative).")
    w()


def adoption_table():
    w("### T17. Adopted code reproduces the pre-registered variant, row for row (Round B part 1; fixes 17a–20)")
    w()
    w(f"Sources: `{SRC['adopt_val']}` (adopted code, commit 42bff94's code, validation catalogue) against "
      f"`{SRC['vgrid_g1e1']}` (the variant it adopts); `{SRC['adopt_sweep']}` (adopted code, sweep catalogue, seeds 0–9) "
      f"against `{SRC['grid_g1e1']}`. Compared on makespan, cost and missed tasks (and infeasibility for the sweep), "
      "tolerance 1e-9.")
    w()
    close = lambda a, b: (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= 1e-9)
    va = {(r["job"], r["sc"], r["seed"], r["key"]): r for r in json.load(open(ROOT / SRC["adopt_val"], encoding="utf-8"))["rows"]}
    vb = {(r["job"], r["sc"], r["seed"], r["key"]): r for r in json.load(open(ROOT / SRC["vgrid_g1e1"], encoding="utf-8"))["rows"]}
    vsame = sum(1 for k in vb if k in va and va[k]["ok"] == vb[k]["ok"] and close(va[k].get("mk"), vb[k].get("mk"))
                and close(va[k]["cost"]["R0"], vb[k]["cost"]["R0"]) and va[k].get("misses") == vb[k].get("misses"))
    sa, sb = load_jsonl(SRC["adopt_sweep"]), load_jsonl(SRC["grid_g1e1"])
    ssame = sum(1 for k in sb if k in sa and bool(sa[k].get("infeasible")) == bool(sb[k].get("infeasible"))
                and close(sa[k].get("mk"), sb[k].get("mk")) and close(sa[k].get("cost"), sb[k].get("cost"))
                and sa[k].get("misses") == sb[k].get("misses"))
    w("| catalogue | rows identical |")
    w("|---|---|")
    w(f"| validation | {vsame} / {len(vb)} |")
    w(f"| sweep | {ssame} / {len(sb)} |")
    w()
    if not (ROOT / SRC["adopt2_verify"]).exists():
        return
    w("Fixes 17a, 18, 19, 20 (post-freeze round): the adoption patches `experiments/fix17_adopt_patch.py --a` and "
      "`experiments/fix18_20_adopt_patch.py` applied to a clean export reproduce the combined variant, and the full "
      f"baseline sweep on the adopted code reproduces it for every seed. Sources: `{SRC['adopt2_verify']}`; `{SRC['on']}` "
      f"against `{SRC['fx_all']}`.")
    w()
    tv = [l.strip() for l in (ROOT / SRC["adopt2_verify"]).read_text(encoding="utf-8").splitlines() if "rows identical" in l]
    base, var = load_jsonl(SRC["on"]), load_jsonl(SRC["fx_all"])
    same = sum(1 for u in var if u in base and _same_row(base[u], var[u]))
    w("| check | rows identical |")
    w("|---|---|")
    w(f"| adopted code in a clean export, seeds 0–9, all schedulers | {tv[0].split(' rows')[0] if tv else 'n/a'} |")
    w(f"| baseline sweep `{FP}`, seeds 0–29, all schedulers | {same} / {len(var)} |")
    w()


def deviations_table():
    import re
    w("### T16. The deviation register (Appendix: DEVIATIONS.md)")
    w()
    w(f"Source: `{SRC['devs']}`. Rows counted by section and by the first word of their Status cell.")
    w()
    text = (ROOT / SRC["devs"]).read_text(encoding="utf-8")
    section, counts, ids = None, defaultdict(lambda: defaultdict(int)), defaultdict(list)
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        mm = re.match(r"^\| ([A-Z]\d+) \|", line)
        if mm and section:
            status = line.rstrip().rstrip("|").rsplit("|", 1)[-1].strip()
            first = re.split(r"[\s—(-]", status, maxsplit=1)[0].lower()
            counts[section][first] += 1
            ids[(section, first)].append(mm.group(1))
    cats = sorted({c for s in counts.values() for c in s})
    w("| section | " + " | ".join(cats) + " | total |")
    w("|---|" + "---|" * (len(cats) + 1))
    tot = defaultdict(int)
    for s in counts:
        w(f"| {s} | " + " | ".join(str(counts[s][c]) for c in cats) + f" | {sum(counts[s].values())} |")
        for c in cats:
            tot[c] += counts[s][c]
    w("| **all** | " + " | ".join(str(tot[c]) for c in cats) + f" | {sum(tot.values())} |")
    w()
    for c in cats:
        w(f"- {c}: " + ", ".join(i for (s, cc), l in ids.items() if cc == c for i in l))
    w()


def _merged(label, sets, cache):
    """Rows of a variant set, filling schedulers the variant file lacks."""
    if label in cache:
        return cache[label]
    src, fill = sets[label]
    d = dict(_merged(fill, sets, cache)) if fill else {}
    d.update(load_jsonl(SRC[src]))
    cache[label] = d
    return d


def _set_metrics(d):
    cells = cells_of(d)
    comp = [c for c in sorted(cells) if complete(cells[c])]
    g = group_row({c: cell_stats(cells[c]) for c in comp}, comp)
    for k in KEYS:
        fe = [r for u, r in d.items() if u[4] == k and ok(r)]
        g[f"miss_{k}"] = sum(r["misses"] for r in fe)
        g[f"runs_{k}"] = sum(1 for r in fe if r["misses"] > 0)
    return g


def _same_row(a, b, exact=False):
    """Runs changed: makespan within 1e-9 s, cost within 1e-12 $, same misses (the
    convention of experiments/fix17_compare.py; a few runs differ only in float
    rounding). exact=True for reproduction checks."""
    if bool(a.get("infeasible")) != bool(b.get("infeasible")) or a.get("error") != b.get("error"):
        return False
    if a.get("infeasible"):
        return True
    if exact:
        return a["mk"] == b["mk"] and a["cost"] == b["cost"] and a["misses"] == b["misses"]
    return abs(a["mk"] - b["mk"]) < 1e-9 and abs(a["cost"] - b["cost"]) < 1e-12 and a["misses"] == b["misses"]


def fix17_table():
    w("### T18. Fix 17 sub-fixes (R-BurstHADS saturation response), each measured against the freeze-round-b baseline")
    w()
    w(f"Sources: `{SRC['raw_rb']}` (baseline) and the R-BurstHADS-only variant files `{SRC['f17a']}`, `{SRC['f17b']}`, "
      f"`{SRC['f17c']}`, `{SRC['f17ab']}`, `{SRC['f17abc']}` (HADS and Burst-HADS rows from the baseline). Interpretations "
      "pre-registered in `experiments/fix17_plan.md` (commit 12e6749). Limits on, 30 seeds; cell aggregates over the cells "
      "where every scheduler is feasible in every seed.")
    w()
    base = load_jsonl(SRC["raw_rb"])
    sets = {"baseline": ("raw_rb", None), "17a": ("f17a", "baseline"), "17b": ("f17b", "baseline"),
            "17c": ("f17c", "baseline"), "17a+17b": ("f17ab", "baseline"), "17a+17b+17c": ("f17abc", "baseline")}
    decision = {"baseline": "—", "17a": "adopted", "17b": "rejected", "17c": "rejected",
                "17a+17b": "rejected (contains 17b)", "17a+17b+17c": "rejected (contains 17b, 17c)"}
    cache = {}
    w("| set | R-BurstHADS runs changed | R missed tasks | R runs with a miss | R $ vs B | R mk vs B | R dominates B | R sig. cheaper / dearer than B | R sig. faster / slower than B | decision |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for lb in sets:
        d = _merged(lb, sets, cache)
        g = _set_metrics(d)
        ch = sum(1 for u in d if u[4] == "rburst" and not _same_row(d[u], base[u]))
        w(f"| {lb} | {ch}/2400 | {g['miss_rburst']} | {g['runs_rburst']} | {g['rbc']:+.1f}% | {g['rbmk']:+.1f}% | "
          f"{g['dom']}/{g['cells']} | {g['cheap']} / {g['dear']} | {g['fast']} / {g['slow']} | {decision[lb]} |")
    w()


def fix18_20_table():
    w("### T19. Fixes 17a, 18, 19, 20: individual effects and contributions within the combined set")
    w()
    w(f"Sources: `{SRC['raw_rb']}` (freeze-round-b baseline) and variant files `{SRC['f17a']}` (17a), `{SRC['boot_wait']}` (18), "
      f"`{SRC['ckpt_exec']}` (19), `{SRC['u10_ovh']}` (20), `{SRC['boot_u10']}` (18+20), `{SRC['fx_all']}` (all four), "
      f"`{SRC['fx_no17a']}`, `{SRC['fx_no18']}`, `{SRC['fx_no19']}`, `{SRC['fx_no20']}` (all four without one). Files holding "
      "only R-BurstHADS rows take HADS and Burst-HADS from the set they extend. Design pre-registered in "
      "`experiments/fix18_20_plan.md` (commit af467a6). Individual effect = set minus baseline; contribution = all four minus "
      "all four without the fix. No additivity assumed.")
    w()
    sets = {"baseline": ("raw_rb", None), "17a": ("f17a", "baseline"), "18": ("boot_wait", "baseline"),
            "19": ("ckpt_exec", "baseline"), "20": ("u10_ovh", "baseline"), "18+20": ("boot_u10", "20"),
            "ALL": ("fx_all", "baseline"), "ALL-17a": ("fx_no17a", "ALL"), "ALL-18": ("fx_no18", "ALL"),
            "ALL-19": ("fx_no19", "baseline"), "ALL-20": ("fx_no20", "baseline")}
    cache = {}
    M = {lb: _set_metrics(_merged(lb, sets, cache)) for lb in sets}
    cols = [("R $ vs B", "rbc", "%"), ("R mk vs B", "rbmk", "%"), ("R $ vs H", "rc", "%"), ("R mk vs H", "rmk", "%"),
            ("B $ vs H", "bc", "%"), ("R dominates B", "dom", "n"), ("R sig. cheaper", "cheap", "n"),
            ("R sig. dearer", "dear", "n"), ("R sig. faster", "fast", "n"), ("R sig. slower", "slow", "n"),
            ("missed H", "miss_hads", "n"), ("missed B", "miss_burst", "n"), ("missed R", "miss_rburst", "n"),
            ("runs w/ miss R", "runs_rburst", "n")]
    fmt = lambda v, t: f"{v:+.1f}%" if t == "%" else f"{v:d}"
    dfm = lambda v, t: f"{v:+.2f}" if t == "%" else f"{v:+d}"
    w("Levels:")
    w()
    w("| set | cells | " + " | ".join(c[0] for c in cols) + " |")
    w("|---|---|" + "---|" * len(cols))
    for lb in sets:
        w(f"| {lb} | {M[lb]['cells']} | " + " | ".join(fmt(M[lb][k], t) for _, k, t in cols) + " |")
    w()
    w("Individual effects (points / counts) and contributions within the combined set:")
    w()
    w("| fix | effect | " + " | ".join(c[0] for c in cols) + " |")
    w("|---|---|" + "---|" * len(cols))
    for x in ("17a", "18", "19", "20"):
        w(f"| {x} | alone vs baseline | " + " | ".join(dfm(M[x][k] - M['baseline'][k], t) for _, k, t in cols) + " |")
        w(f"| {x} | ALL vs ALL-{x} | " + " | ".join(dfm(M['ALL'][k] - M['ALL-' + x][k], t) for _, k, t in cols) + " |")
    w(f"| all four | ALL vs baseline | " + " | ".join(dfm(M['ALL'][k] - M['baseline'][k], t) for _, k, t in cols) + " |")
    w()
    w("Runs changed by fix 20 (U10), per scheduler:")
    w()
    w("| comparison | HADS | Burst-HADS | R-BurstHADS |")
    w("|---|---|---|---|")
    for name, a, b in (("20 alone vs baseline", "20", "baseline"), ("18+20 vs 18", "18+20", "18"), ("ALL vs ALL-20", "ALL", "ALL-20")):
        da, db = _merged(a, sets, cache), _merged(b, sets, cache)
        w(f"| {name} | " + " | ".join(f"{sum(1 for u in da if u[4] == k and not _same_row(da[u], db[u]))}/2400" for k in KEYS) + " |")
    w()
    w("Per-scheduler effect of fix 19 (checkpoint credits executed progress):")
    w()
    w("| comparison | scheduler | runs changed | missed tasks | mean makespan change | mean cost change |")
    w("|---|---|---|---|---|---|")
    for name, a, b in (("19 alone vs baseline", "19", "baseline"), ("ALL vs ALL-19", "ALL", "ALL-19")):
        da, db = _merged(a, sets, cache), _merged(b, sets, cache)
        for k in KEYS:
            us = [u for u in da if u[4] == k]
            both = [u for u in us if ok(da[u]) and ok(db[u])]
            ch = sum(1 for u in us if not _same_row(da[u], db[u]))
            w(f"| {name} | {LAB[k]} | {ch}/{len(us)} | {M[b]['miss_' + k]} -> {M[a]['miss_' + k]} | "
              f"{mean(pct(da[u]['mk'], db[u]['mk']) for u in both):+.2f}% | {mean(pct(da[u]['cost'], db[u]['cost']) for u in both):+.2f}% |")
    w()


def overcredit_table():
    w("### T20. Checkpoint over-credit per scheduler and early starts, freeze-round-b code (before fixes 18, 19)")
    w()
    w(f"Source: `{SRC['overcredit']}` (record-only probe over all 7,200 limits-on runs; every run reproduced its baseline row). "
      "Credited = elapsed × speed at each hibernation of a running task; executed = elapsed × speed / (1 + overhead).")
    w()
    res = json.load(open(ROOT / SRC["overcredit"], encoding="utf-8"))
    fe = lambda x: x["row"].get("error") is None and not x["row"].get("infeasible")
    w("| scheduler | feasible runs | displaced running tasks / run | over-credit / run (work units) | over-credit, % of workload |")
    w("|---|---|---|---|---|")
    for k in KEYS:
        xs = [x for x in res if x["unit"][4] == k and fe(x)]
        oc = sum(x["credited"] - x["executed"] for x in xs)
        w(f"| {LAB[k]} | {len(xs)} | {mean(x['disp_running'] for x in xs):.2f} | {oc / len(xs):.1f} | "
          f"{100 * oc / sum(x['work'] for x in xs):.3f}% |")
    xs = [x for x in res if x["unit"][4] == "rburst" and fe(x)]
    es, eb = sum(x["early_starts_spot"] for x in xs), sum(x["early_starts_burstable"] for x in xs)
    w()
    w(f"Tasks started on an R-BurstHADS-provisioned VM before its ready time: {es} on spot VMs "
      f"(in {sum(1 for x in xs if x['early_starts_spot'])} of {len(xs)} runs), {eb} on burstables; mean head start "
      f"{sum(x['early_seconds'] for x in xs) / max(1, es + eb):.1f} s.")
    w()


def entry_route_table():
    w("### T21. How the freeze-round-b baseline's missed R-BurstHADS tasks were placed")
    w()
    w(f"Sources: `{SRC['u10_trace']}` (placement trace of the 104 missing runs; every traced run reproduced its baseline row) "
      f"and `{SRC['u10_verify']}` (independent re-check of every attribution from a reservation log with an explicit context "
      "stack).")
    w()
    res = json.load(open(ROOT / SRC["u10_trace"], encoding="utf-8"))
    rows = [m for x in res for m in x["missed"]]
    lab = lambda e: e["path"] + (f" / {e['tier']}" if e["tier"] else "")
    last = defaultdict(int)
    entry = defaultdict(int)
    late_pred = 0
    fresh_ok = 0
    steal = 0
    for m in rows:
        h = m["history"]
        f = h[-1]
        last[f"{lab(f)} -> {f['market']}:{f['type']}"] += 1
        if f["market"] == "burstable":
            i = next(k for k, e in enumerate(h) if e["vm"] == f["vm"])
            entry[lab(h[i])] += 1
            steal += any(e["path"] == "work stealing" and e["market"] == "burstable" for e in h)
        late_pred += int(f["predicted"] is not None and f["predicted"] > m["deadline"] + 1e-6)
        fresh_ok += int(f["best_fresh_in_limit"] is not None and f["best_fresh_in_limit"] <= m["deadline"] + 1e-6)
    w(f"Missed tasks: {len(rows)}. Last placement placed with the placer's own predicted finish already past D: {late_pred}. "
      f"A fresh on-demand VM within the launch limits could still have finished by D from that moment: {fresh_ok}. "
      f"Moved onto a burstable by work stealing (Algorithm 5): {steal}.")
    w()
    w("| last placement | missed tasks |")
    w("|---|---|")
    for k, v in sorted(last.items(), key=lambda kv: -kv[1]):
        w(f"| {k} | {v} |")
    w()
    w("| first placement onto the burstable the task missed on | missed tasks |")
    w("|---|---|")
    for k, v in sorted(entry.items(), key=lambda kv: -kv[1]):
        w(f"| {k} | {v} |")
    w()
    vt = (ROOT / SRC["u10_verify"]).read_text(encoding="utf-8").splitlines()
    for l in vt:
        if l.startswith(("Re-runs", "Missed tasks last", "Agreeing", "Disagreeing")):
            w(f"- {l}")
    w()


def u10_window_table():
    w("### T22. Why fix 20 (U10) changes no run: the fresh-VM deadline test with and without the overhead")
    w()
    w(f"Source: `{SRC['u10_window']}` (record-only probe, `experiments/diag_u10_window.py`, variants u10_ovh and fx_all, "
      "7,200 runs each). A walk is a call of the on-demand fallback that draws a fresh VM from M^o; for each, both tests "
      "are evaluated on the same state. Fix 20 can change a decision only in the column 'a type passes only without the overhead'.")
    w()
    prev_table = False
    for l in (ROOT / SRC["u10_window"]).read_text(encoding="utf-8").splitlines()[1:]:
        if not l.strip():
            continue
        is_table = l.startswith("|")
        if is_table != prev_table:
            w()               # markdown needs a blank line between a paragraph and a table
        w(l)
        prev_table = is_table
    w()


def sources_table():
    w("## Sources")
    w()
    w("Every number above is computed by `experiments/results_pack.py` from these committed files and nothing else. "
      "No simulation was run to produce this pack.")
    w()
    w("| file | SHA-256 (first 16) | last changed in commit |")
    w("|---|---|---|")
    for rel in sorted(set(SRC.values())):
        h = hashlib.sha256((ROOT / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
        commit = subprocess.run(["git", "log", "-1", "--format=%h", "--", rel], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip() or "UNCOMMITTED"
        w(f"| `{rel}` | `{h}` | `{commit}` |")
    w()


def main():
    import argparse
    global FP
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp", default=FP, help="code fingerprint of the baseline sweep")
    ap.add_argument("--tag", default="freeze-round-b", help="git tag of that baseline")
    ap.add_argument("--val", default="freeze", help="validation run tag: diag_cost_gap_<val>_{nocap,capped}_c3.json")
    ap.add_argument("--out", default="RESULTS_PACK.md")
    args = ap.parse_args()
    FP = args.fp
    SRC.update(on=f"experiments/sweep_raw_{FP}.jsonl", off=f"experiments/sweep_variant_nocap_{FP}.jsonl",
               val_off=f"experiments/diag_cost_gap_{args.val}_nocap_c3.json",
               val_on=f"experiments/diag_cost_gap_{args.val}_capped_c3.json")
    d_on, d_off = load_jsonl(SRC["on"]), load_jsonl(SRC["off"])
    assert len(d_on) == 7200 and len(d_off) == 7200, (len(d_on), len(d_off))
    body = OUT
    w("# R-BurstHADS results pack")
    w()
    w(f"Frozen simulator: tag `{args.tag}`, code fingerprint `{FP}`. Generated by `experiments/results_pack.py` "
      "from committed result files only (see Sources at the end). Table 9 scenarios sc1–sc5 × n 50/100/200/300 × "
      "DF 0.25/0.5/1.0/2.0 × 30 seeds × 3 schedulers = 7,200 runs per limit setting. Instance limits = the reference "
      f"implementation's account limits: {lim.PER_TYPE['ondemand']} on-demand and {lim.PER_TYPE['spot']} spot launches per "
      f"instance type, {lim.GLOBAL['ondemand']} on-demand and {lim.GLOBAL['spot']} spot per market (burstables count as on-demand).")
    w()
    w("## Headline tables")
    w()
    st_on, g_on = summary_table(d_on, "Results, instance limits ON (provider limits)", "T1", SRC["on"])
    st_off, g_off = summary_table(d_off, "Results, instance limits OFF", "T2", SRC["off"])
    w("## Misses and feasibility")
    w()
    miss = misses_table(d_on, d_off)
    inf_on, inf_off = infeasible_table(d_on, d_off)
    attr = attribution_table(d_on, d_off)
    w("## Validation against TCC23 (Teylo et al., IEEE TCC 2023)")
    w()
    voff, von, pub = validation_tables()
    traj = audit_trajectory(pub)
    cause_tables(pub)
    w("## Disclosures")
    w()
    guard = guard_tables()
    part2_table(d_on)
    economics_table()
    deviations_table()
    adoption_table()
    w("## Post-freeze round: the saturation response, fixes 17a–20, checkpoint credit and boot delay")
    w()
    fix17_table()
    fix18_20_table()
    overcredit_table()
    entry_route_table()
    u10_window_table()
    w("## Per-cell means and 95% confidence intervals")
    w()
    cell_ci_table(d_on, "T3", "Per cell, instance limits ON", SRC["on"])
    cell_ci_table(d_off, "T4", "Per cell, instance limits OFF", SRC["off"])
    sources_table()

    # key numbers block, placed right after the title
    a_on, a_off = g_on["all"], g_off["all"]
    ro, mo = miss[("on", "rburst")], miss[("on", "burst")]
    key = [
        "",
        "## Key numbers (each is a cell of the table named in brackets)",
        "",
        f"- Limits on, {a_on['cells']} cells [T1 all]: R-BurstHADS makespan {a_on['rmk']:+.1f}% vs HADS and {a_on['rbmk']:+.1f}% vs Burst-HADS; "
        f"cost {a_on['rc']:+.1f}% vs HADS against Burst-HADS's {a_on['bc']:+.1f}% (premium reduced by {a_on['bc'] - a_on['rc']:.1f} points, "
        f"{100 * (a_on['bc'] - a_on['rc']) / a_on['bc']:.0f}% of it); {a_on['rbc']:+.1f}% cost vs Burst-HADS; dominates Burst-HADS in {a_on['dom']}/{a_on['cells']} cells.",
        f"- Limits off, {a_off['cells']} cells [T2 all]: R-BurstHADS {a_off['rbmk']:+.1f}% makespan and {a_off['rbc']:+.1f}% cost vs Burst-HADS, "
        f"dominating {a_off['dom']}/{a_off['cells']}; {a_off['rmk']:+.1f}% / {a_off['rc']:+.1f}% vs HADS.",
        f"- Misses, limits on [T5]: HADS {miss[('on', 'hads')]['tasks_missed']} tasks, Burst-HADS {mo['tasks_missed']} task(s) in {mo['with_miss']} run(s), "
        f"R-BurstHADS {ro['tasks_missed']} tasks in {ro['with_miss']} of {ro['runs']} runs ({100 * ro['with_miss'] / ro['runs']:.1f}%). "
        f"Limits off: {sum(miss[('off', k)]['tasks_missed'] for k in KEYS)} missed tasks in total.",
        f"- R-BurstHADS runs with a miss that had reached a launch limit [T7]: {attr['rburst']['miss_hit']} of {attr['rburst']['miss_runs']}; "
        f"runs without a miss that had: {attr['rburst']['clean_hit']} of {attr['rburst']['clean_runs']}. Same units with limits off: {attr['rburst']['off']} missed tasks.",
        f"- Infeasible runs [T6]: {inf_on} with limits on, {inf_off} with limits off.",
        f"- Validation [T9]: Burst-HADS cost change vs HADS under hibernation {voff['cost_change']:+.1f}% against TCC23's {pub['cost_change']:+.2f}%; "
        f"makespan reduction {voff['mk_red']:.1f}% against {pub['mk_red']:.2f}%; Burst-HADS hibernation premium {voff['prem_b']:+.0f}% against {pub['prem_b']:+.0f}%, "
        f"HADS {voff['prem_h']:+.0f}% against {pub['prem_h']:+.0f}%.",
        f"- Guard disclosure [T12]: removing it turns {guard['burst']['prot']} Burst-HADS and {guard['rburst']['prot']} R-BurstHADS clean runs into missing runs "
        f"(reverse: {guard['burst']['harm']} and {guard['rburst']['harm']}).",
        "",
    ]
    final = OUT[:3] + key + OUT[3:]
    (ROOT / args.out).write_text("\n".join(final) + "\n", encoding="utf-8")
    print("\n".join(key))
    print(f"wrote {args.out} ({len(final)} lines)")


if __name__ == "__main__":
    main()
