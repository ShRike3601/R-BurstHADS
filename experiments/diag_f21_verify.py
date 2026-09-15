"""
Verification on existing data after freeze-fix21 (no simulation):

  1. Are the fully feasible cells identical, cell by cell, between freeze-fix20
     and freeze-fix21, and across every set in the fix 21 comparison (T23)?
  2. Dominance 42 -> 49: the criterion, the cells that entered and left, and
     whether threshold crossing or variance accounts for it; the same for the
     significantly cheaper / dearer / faster / slower counts.
  3. R-BurstHADS's burstable branch with limits on and off, from launch counts:
     R-BurstHADS's t3.large launches minus Burst-HADS's in the same unit
     (identical primary schedules launch identical proactive burstables),
     checked against the probe's firing count with limits on.
  4. The five n = 100, DF = 0.25 floor cells at freeze-round-b, freeze-fix20
     and freeze-fix21, limits on and off.
  5. The "80 cells" label on CLAUDE.md's per-scenario values (freeze-round-b):
     the values recomputed over the 15 fully feasible cells per scenario and
     over all 16 cells with their feasible seeds.

    python experiments\\diag_f21_verify.py -> experiments/diag_f21_verify.txt
"""
import sys, json
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import results_pack as rp

FPB, FP20, FP21 = "4f08f48ac35c", "d40a1c917c63", "2439a00d7f74"
out = []
P = out.append
L = lambda rel: rp.load_jsonl(rel)
m = lambda st, k, f: st[k][f][0]
avg = lambda xs: sum(xs) / len(xs) if xs else float("nan")


def complete_cells(d):
    c = rp.cells_of(d)
    return {k for k, s in c.items() if rp.complete(s)}, c


# ── 1. cell sets ─────────────────────────────────────────────────────────────
on20, on21 = L(f"experiments/sweep_raw_{FP20}.jsonl"), L(f"experiments/sweep_raw_{FP21}.jsonl")
off20, off21 = L(f"experiments/sweep_variant_nocap_{FP20}.jsonl"), L(f"experiments/sweep_variant_nocap_{FP21}.jsonl")
onB = L(f"experiments/sweep_raw_{FPB}.jsonl")
set20, c20 = complete_cells(on20)
set21, c21 = complete_cells(on21)
setB, cB = complete_cells(onB)
P("# Verification on existing data after freeze-fix21")
P("")
P("## 1. Fully feasible cells, compared cell by cell")
P("")
P(f"- freeze-fix20 limits on: {len(set20)} cells; freeze-fix21 limits on: {len(set21)} cells; identical: {set20 == set21}; "
  f"only in freeze-fix20: {sorted(set20 - set21)}; only in freeze-fix21: {sorted(set21 - set20)}")
P(f"- freeze-round-b limits on: {len(setB)} cells; identical to freeze-fix21: {setB == set21}")
P(f"- cells excluded at freeze-fix21: {sorted(set(rp.cells_of(on21)) - set21)}")
s_off20, _ = complete_cells(off20)
s_off21, _ = complete_cells(off21)
P(f"- limits off: freeze-fix20 {len(s_off20)} cells, freeze-fix21 {len(s_off21)} cells, identical: {s_off20 == s_off21}")
f21 = dict(on20)
f21.update(L(f"experiments/sweep_variant_f21_{FP20}.jsonl"))
for name, fill, tag in (("21a", on20, "f21a"), ("21b", on20, "f21b"), ("21c", on20, "f21c"), ("fix 21", on20, "f21"),
                        ("fix 21 - 21a", on20, "f21_no_a"), ("fix 21 - 21b", f21, "f21_no_b"),
                        ("fix 21 - 21c", on20, "f21_no_c"), ("fix 21, fix 20 reverted", on20, "f21_no20")):
    d = dict(fill)
    d.update(L(f"experiments/sweep_variant_{tag}_{FP20}.jsonl"))
    s, _ = complete_cells(d)
    P(f"- T23 set {name}: {len(s)} cells, identical to freeze-fix20's: {s == set20}")
P("")

# ── 2. dominance and significance ────────────────────────────────────────────
S = sorted(set20 & set21)
rows = []
for c in S:
    a, b = rp.cell_stats(c20[c]), rp.cell_stats(c21[c])
    r = dict(cell=c)
    for tag, st in (("20", a), ("21", b)):
        r["rbmk" + tag] = rp.pct(m(st, "rburst", "mk"), m(st, "burst", "mk"))
        r["rbc" + tag] = rp.pct(m(st, "rburst", "cost"), m(st, "burst", "cost"))
        r["dom" + tag] = m(st, "rburst", "mk") <= m(st, "burst", "mk") and m(st, "rburst", "cost") <= m(st, "burst", "cost")
        r["cm" + tag], r["ch" + tag] = st["rb_cost"][0], st["rb_cost"][1]
        r["mm" + tag], r["mh" + tag] = st["rb_mk"][0], st["rb_mk"][1]
        r["cheap" + tag] = st["rb_cost"][0] + st["rb_cost"][1] < 0
        r["dear" + tag] = st["rb_cost"][0] - st["rb_cost"][1] > 0
        r["fast" + tag] = st["rb_mk"][0] + st["rb_mk"][1] < 0
        r["slow" + tag] = st["rb_mk"][0] - st["rb_mk"][1] > 0
    r["dR_c"] = rp.pct(m(b, "rburst", "cost"), m(a, "rburst", "cost"))
    r["dB_c"] = rp.pct(m(b, "burst", "cost"), m(a, "burst", "cost"))
    r["dR_m"] = rp.pct(m(b, "rburst", "mk"), m(a, "rburst", "mk"))
    r["dB_m"] = rp.pct(m(b, "burst", "mk"), m(a, "burst", "mk"))
    rows.append(r)
P("## 2. Dominance 42 -> 49 and the significance counts")
P("")
P("Criterion (results_pack.group_row): R-BurstHADS dominates Burst-HADS in a cell when its mean makespan over the "
  "cell's 30 seeds is <= Burst-HADS's AND its mean cost is <= Burst-HADS's. Means only: no test, no margin, ties count. "
  "Significance: the paired per-seed 95% CI of R - B excludes 0.")
P("")
enter = [r for r in rows if r["dom21"] and not r["dom20"]]
leave = [r for r in rows if r["dom20"] and not r["dom21"]]
P(f"Cells dominated: {sum(r['dom20'] for r in rows)} -> {sum(r['dom21'] for r in rows)}; entered {len(enter)}, left {len(leave)}.")
P("")
P("| cell | change | R mk vs B before -> after | R $ vs B before -> after | axis failing when not dominated | R mean cost change | B mean cost change | R mean mk change | B mean mk change |")
P("|---|---|---|---|---|---|---|---|---|")


def failing(mk, c):
    return "+".join(x for x, v in (("mk", mk), ("cost", c)) if v > 0)


for r in enter + leave:
    fl = failing(r["rbmk20"], r["rbc20"]) if r in enter else failing(r["rbmk21"], r["rbc21"])
    P(f"| {r['cell']} | {'entered' if r in enter else 'left'} | {r['rbmk20']:+.2f}% -> {r['rbmk21']:+.2f}% | "
      f"{r['rbc20']:+.2f}% -> {r['rbc21']:+.2f}% | {fl} | {r['dR_c']:+.2f}% | {r['dB_c']:+.2f}% | "
      f"{r['dR_m']:+.2f}% | {r['dB_m']:+.2f}% |")
P("")
gap = lambda r, t: max(v for v in (r["rbmk" + t], r["rbc" + t]))
P(f"Failing-axis gap of the cells that entered, at freeze-fix20: largest {max((gap(r, '20') for r in enter), default=0):+.2f}%, "
  f"median {sorted(gap(r, '20') for r in enter)[len(enter) // 2] if enter else 0:+.2f}%. "
  f"Non-dominated cells at freeze-fix20 within 2 points on their failing axis: "
  f"{sum(1 for r in rows if not r['dom20'] and 0 < gap(r, '20') <= 2)}.")
P(f"Mean change in R $ vs B: entering cells {avg([r['rbc21'] - r['rbc20'] for r in enter]):+.2f} pts, all other cells "
  f"{avg([r['rbc21'] - r['rbc20'] for r in rows if r not in enter]):+.2f} pts; in R mk vs B: "
  f"{avg([r['rbmk21'] - r['rbmk20'] for r in enter]):+.2f} / {avg([r['rbmk21'] - r['rbmk20'] for r in rows if r not in enter]):+.2f} pts.")
P("")
for flag, meanf, hwf, name, unit in (("cheap", "cm", "ch", "significantly cheaper", "$"), ("dear", "cm", "ch", "significantly dearer", "$"),
                                     ("fast", "mm", "mh", "significantly faster", "s"), ("slow", "mm", "mh", "significantly slower", "s")):
    gained = [r for r in rows if r[flag + "21"] and not r[flag + "20"]]
    lost = [r for r in rows if r[flag + "20"] and not r[flag + "21"]]
    P(f"### {name}: {sum(r[flag + '20'] for r in rows)} -> {sum(r[flag + '21'] for r in rows)} (gained {len(gained)}, lost {len(lost)})")
    P("")
    P("| cell | change | mean R - B before -> after | CI half-width before -> after | edge crossed 0 because |")
    P("|---|---|---|---|---|")
    for r in gained + lost:
        m0, m1, h0, h1 = r[meanf + "20"], r[meanf + "21"], r[hwf + "20"], r[hwf + "21"]
        # margin = |mean| - half-width; attribute its change to the mean or to the half-width
        dmean, dhw = abs(m1) - abs(m0), h1 - h0
        why = ("the mean moved toward 0" if -dmean >= dhw else "the half-width widened") if r in lost else \
              ("the mean moved away from 0" if dmean >= -dhw else "the half-width narrowed")
        P(f"| {r['cell']} | {'gained' if r in gained else 'lost'} | {m0:+.4g} -> {m1:+.4g} {unit} | {h0:.4g} -> {h1:.4g} | {why} |")
    P("")
P(f"Mean ratio of paired-CI half-widths, freeze-fix21 / freeze-fix20, over the 75 cells: cost "
  f"{avg([r['ch21'] / r['ch20'] for r in rows if r['ch20'] > 0]):.3f}, makespan {avg([r['mh21'] / r['mh20'] for r in rows if r['mh20'] > 0]):.3f}.")
P("")

# ── 3. burstable branch, limits on and off ───────────────────────────────────
def t3(r):
    return sum(v for k, v in (r.get("launched") or {}).items() if k.endswith("t3.large"))


def branch(d):
    tot, runs = 0, 0
    for u, r in d.items():
        if u[4] != "rburst" or not rp.ok(r):
            continue
        b = d.get(u[:4] + ("burst",))
        if b is None or not rp.ok(b):
            continue
        tot += t3(r) - t3(b)
        runs += 1
    return tot, runs


probe = json.load(open(HERE / "diag_launch21_adopted.json", encoding="utf-8"))
fires = sum(x["branch"].get("tier3 burstable", 0) + x["branch"].get("saturation burstable", 0)
            for x in probe if x["unit"][4] == "rburst")
t_on, n_on = branch(on21)
t_off, n_off = branch(off21)
P("## 3. R-BurstHADS's burstable branch, limits on and off (freeze-fix21)")
P("")
P(f"Estimator check, limits on: R-BurstHADS t3.large launches minus Burst-HADS's = {t_on} over {n_on} paired runs; "
  f"the probe counts {fires} branch firings (tier 3 + saturation response).")
P(f"Limits off: {t_off} over {n_off} paired runs ({t_off / max(1, n_off):.3f} per run), against {t_on / max(1, n_on):.3f} per run with limits on.")
P("")

# ── 4. floor cells ───────────────────────────────────────────────────────────
P("## 4. The five n = 100, DF = 0.25 cells (deadline floor, D = 339.7 s)")
P("")
P("| state | limits | scheduler | feasible runs of 150 | runs with a miss | missed tasks |")
P("|---|---|---|---|---|---|")
for state, lim, f in (("freeze-round-b", "on", f"sweep_raw_{FPB}"), ("freeze-round-b", "off", f"sweep_variant_nocap_{FPB}"),
                      ("freeze-fix20", "on", f"sweep_raw_{FP20}"), ("freeze-fix20", "off", f"sweep_variant_nocap_{FP20}"),
                      ("freeze-fix21", "on", f"sweep_raw_{FP21}"), ("freeze-fix21", "off", f"sweep_variant_nocap_{FP21}")):
    d = L(f"experiments/{f}.jsonl")
    for k in rp.KEYS:
        fe = [r for u, r in d.items() if u[1] == 100 and u[2] == 0.25 and u[4] == k and rp.ok(r)]
        P(f"| {state} | {lim} | {rp.LAB[k]} | {len(fe)} | {sum(1 for r in fe if r['misses'])} | {sum(r['misses'] for r in fe)} |")
P("")

# ── 5. the "80 cells" label ──────────────────────────────────────────────────
P("## 5. CLAUDE.md's per-scenario values, labelled \"80 cells\" (freeze-round-b, limits on)")
P("")
statsB = {c: rp.cell_stats(s) for c, s in cB.items()}
P("| scenario | 15 fully feasible cells: R mk / R $ vs HADS | 16 cells, feasible seeds: R mk / R $ vs HADS | CLAUDE.md |")
P("|---|---|---|---|")
claude = {"sc1": "−37.1% / +18.9%", "sc2": "−17.0% / +17.6%", "sc3": "−35.6% / +9.9%", "sc4": "−17.7% / +9.4%", "sc5": "−24.3% / +5.1%"}
for sc in ("sc1", "sc2", "sc3", "sc4", "sc5"):
    g15 = rp.group_row(statsB, [c for c in sorted(setB) if c[0] == sc])
    g16 = rp.group_row(statsB, [c for c in sorted(cB) if c[0] == sc])
    P(f"| {sc} | {g15['rmk']:+.1f}% / {g15['rc']:+.1f}% | {g16['rmk']:+.1f}% / {g16['rc']:+.1f}% | {claude[sc]} |")
bcheap80 = sum(1 for c in cB if m(statsB[c], "burst", "cost") < m(statsB[c], "hads", "cost"))
bcheap75 = sum(1 for c in setB if m(statsB[c], "burst", "cost") < m(statsB[c], "hads", "cost"))
P("")
P(f"\"Burst-HADS is cheaper than HADS in 15 of 80 cells\" (CLAUDE.md 349): over all 80 cells {bcheap80}; over the 75, {bcheap75}.")
(HERE / "diag_f21_verify.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
