import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

edits = []

edits.append((
'  poisson_natural  -- Poisson-sampled hibernation using actual lambda values',
'  poisson_natural  -- Poisson-sampled hibernation, kh/D synthetic (Teylo et al. sc2)'
))

edits.append((
'LAMBDA_VALUES    = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]',
'KH_VALUES        = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0]  # Teylo et al. Table 9: sc1 kh=1, sc5 kh=3, sc2 kh=5 (worst case)'
))

edits.append((
'    "poisson_natural": "Poisson Natural (AWS lambda rates)",',
'    "poisson_natural": "Poisson Natural (Teylo et al. sc2, kh=5)",'
))

edits.append((
'''        elif scenario == "poisson_natural":
            lam_m5   = extra.get("lambda_m5", 5.0) / 3600.0
            lam_c5   = 0.03 / 3600.0
            evts     = []
            t = float(np_rng.exponential(1.0 / lam_m5))
            while t < global_deadline:
                evts.append(t)
                t += float(np_rng.exponential(1.0 / lam_m5))
            t = float(np_rng.exponential(1.0 / lam_c5))
            while t < global_deadline:
                evts.append(t)
                t += float(np_rng.exponential(1.0 / lam_c5))
            hib_time = sorted(evts)[:6] if evts else None''',
'''        elif scenario == "poisson_natural":
            # Teylo et al. (2023) Table 9: lambda_h = kh / D, where kh is
            # the EXPECTED NUMBER of hibernation events over this run's
            # own deadline D. This is synthetic (the paper is explicit
            # these are not AWS-measured), so kh stays fixed across n
            # instead of a fixed events/hour rate that would silently
            # generate more events at larger n just because D is longer.
            kh_m5    = extra.get("kh_m5", 5.0)
            lam_m5   = kh_m5 / global_deadline
            lam_c5   = 0.03 / 3600.0  # fixed low background rate, illustrative only
            evts     = []
            t = float(np_rng.exponential(1.0 / lam_m5))
            while t < global_deadline:
                evts.append(t)
                t += float(np_rng.exponential(1.0 / lam_m5))
            t = float(np_rng.exponential(1.0 / lam_c5))
            while t < global_deadline:
                evts.append(t)
                t += float(np_rng.exponential(1.0 / lam_c5))
            hib_time = sorted(evts)[:6] if evts else None'''
))

edits.append((
'''        elif scenario == "lambda_sweep":
            lam_hr  = extra.get("lambda_val", 5.0)
            lam_sec = lam_hr / 3600.0
            evts    = []
            t = float(np_rng.exponential(1.0 / lam_sec))
            while t < global_deadline:
                evts.append(t)
                t += float(np_rng.exponential(1.0 / lam_sec))
            hib_time = sorted(evts)[:6] if evts else None''',
'''        elif scenario == "lambda_sweep":
            # Same kh/D formula as poisson_natural above -- kh is the
            # swept quantity (expected event count over this run's own
            # deadline), not an AWS-measured rate.
            kh      = extra.get("kh_val", 5.0)
            lam_sec = kh / global_deadline
            evts    = []
            t = float(np_rng.exponential(1.0 / lam_sec))
            while t < global_deadline:
                evts.append(t)
                t += float(np_rng.exponential(1.0 / lam_sec))
            hib_time = sorted(evts)[:6] if evts else None'''
))

edits.append((
'''    # Lambda sweep
    for lam in LAMBDA_VALUES:
        for n in [50, 100, 200]:
            cid += 1
            configs.append((cid, n, 1.0, "lambda_sweep", {"lambda_val": lam}))

    # Poisson with varying lambda
    for lam in LAMBDA_VALUES:
        for n in TASK_COUNTS:
            cid += 1
            configs.append((cid, n, 1.0, "poisson_natural", {"lambda_m5": lam}))''',
'''    # kh sweep (Teylo et al. Table 9 parameterization)
    for kh in KH_VALUES:
        for n in [50, 100, 200]:
            cid += 1
            configs.append((cid, n, 1.0, "lambda_sweep", {"kh_val": kh}))

    # Poisson with varying kh
    for kh in KH_VALUES:
        for n in TASK_COUNTS:
            cid += 1
            configs.append((cid, n, 1.0, "poisson_natural", {"kh_m5": kh}))'''
))

edits.append((
'''    def get(scenario, df, n=None, lam5=None, lam_val=None):
        out = [r for r in raw
               if r["scenario"] == scenario and r["df"] == df]
        if n is not None:
            out = [r for r in out if r["n"] == n]
        if lam5 is not None:
            out = [r for r in out
                   if abs(r["extra"].get("lambda_m5", -99) - lam5) < 0.01]
        if lam_val is not None:
            out = [r for r in out
                   if abs(r["extra"].get("lambda_val", -99) - lam_val) < 0.01]
        return sorted(out, key=lambda r: r["n"])''',
'''    def get(scenario, df, n=None, kh5=None, kh_val=None):
        out = [r for r in raw
               if r["scenario"] == scenario and r["df"] == df]
        if n is not None:
            out = [r for r in out if r["n"] == n]
        if kh5 is not None:
            out = [r for r in out
                   if abs(r["extra"].get("kh_m5", -99) - kh5) < 0.01]
        if kh_val is not None:
            out = [r for r in out
                   if abs(r["extra"].get("kh_val", -99) - kh_val) < 0.01]
        return sorted(out, key=lambda r: r["n"])'''
))

edits.append((
'        d = get(sc, 1.0) if sc != "poisson_natural" else get(sc, 1.0, lam5=5.0)',
'        d = get(sc, 1.0) if sc != "poisson_natural" else get(sc, 1.0, kh5=5.0)'
))

edits.append((
'        d = get("poisson_natural", df, lam5=5.0)',
'        d = get("poisson_natural", df, kh5=5.0)'
))

edits.append((
'    axes[0].set_title("Cost — Poisson Natural (λ=5/hr)\\nStochastic hibernation times")',
'    axes[0].set_title("Cost — Poisson Natural (kh=5)\\nStochastic hibernation times")'
))

edits.append((
'''    plt.suptitle("Fig 7 — Poisson Natural Hibernation (λ=5/hr)\\n"
                 "Each run: different hibernation times drawn from Exponential distribution",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig 7 — Poisson Natural Hibernation (kh=5, Teylo et al. sc2)\\n"
                 "Each run: different hibernation times drawn from Exponential distribution",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    for n_t, col, mk in [(50, "#2980b9", "o"),
                          (100, "#c0392b", "s"),
                          (200, "#27ae60", "^")]:
        reds, mks = [], []
        for lam in LAMBDA_VALUES:
            d = get("lambda_sweep", 1.0, n=n_t, lam_val=lam)
            reds.append(cost_red(d[0]) if d else np.nan)
            mks.append(mk_overhead(d[0]) if d else np.nan)
        axes[0].plot(LAMBDA_VALUES, reds, marker=mk, lw=2.2, color=col,
                     markersize=8, markeredgecolor="white", markeredgewidth=1.5,
                     label=f"n={n_t} tasks")
        axes[1].plot(LAMBDA_VALUES, mks, marker=mk, lw=2.2, color=col,
                     markersize=8, markeredgecolor="white", markeredgewidth=1.5,
                     label=f"n={n_t} tasks")
    for ax in axes:
        ax.axhline(0, color="#888", ls="--", lw=1.5, alpha=0.7,
                   label="BurstHADS baseline")
        ax.axvline(5, color="#e67e22", ls=":", lw=1.5, alpha=0.8,
                   label="Our default λ=5/hr")
        ax.set_xlabel("m5.xlarge Hibernation Rate λ (events/hr)",
                      fontweight="bold")
        ax.legend(fontsize=9); ax.grid(alpha=0.3, ls=":")
        ax.set_xscale("log")
        ax.set_xticks(LAMBDA_VALUES)
        ax.set_xticklabels([str(l) for l in LAMBDA_VALUES])
    axes[0].set_ylabel("Cost Reduction %", fontweight="bold")
    axes[0].set_title("Cost Reduction % vs Hibernation Rate")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan Overhead % vs Hibernation Rate")
    plt.suptitle("Fig 8 — Lambda Sweep: Varying m5.xlarge Hibernation Rate\\n"
                 "DF=1.0 | Poisson-sampled",
                 fontweight="bold", fontsize=13)''',
'''    for n_t, col, mk in [(50, "#2980b9", "o"),
                          (100, "#c0392b", "s"),
                          (200, "#27ae60", "^")]:
        reds, mks = [], []
        for kh in KH_VALUES:
            d = get("lambda_sweep", 1.0, n=n_t, kh_val=kh)
            reds.append(cost_red(d[0]) if d else np.nan)
            mks.append(mk_overhead(d[0]) if d else np.nan)
        axes[0].plot(KH_VALUES, reds, marker=mk, lw=2.2, color=col,
                     markersize=8, markeredgecolor="white", markeredgewidth=1.5,
                     label=f"n={n_t} tasks")
        axes[1].plot(KH_VALUES, mks, marker=mk, lw=2.2, color=col,
                     markersize=8, markeredgecolor="white", markeredgewidth=1.5,
                     label=f"n={n_t} tasks")
    for ax in axes:
        ax.axhline(0, color="#888", ls="--", lw=1.5, alpha=0.7,
                   label="BurstHADS baseline")
        ax.axvline(5, color="#e67e22", ls=":", lw=1.5, alpha=0.8,
                   label="Teylo et al. sc2 (kh=5, worst case)")
        ax.set_xlabel("m5.xlarge Expected Hibernations over Deadline (kh)",
                      fontweight="bold")
        ax.legend(fontsize=9); ax.grid(alpha=0.3, ls=":")
        ax.set_xscale("log")
        ax.set_xticks(KH_VALUES)
        ax.set_xticklabels([str(l) for l in KH_VALUES])
    axes[0].set_ylabel("Cost Reduction %", fontweight="bold")
    axes[0].set_title("Cost Reduction % vs Expected Hibernation Count (kh)")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan Overhead % vs Expected Hibernation Count (kh)")
    plt.suptitle("Fig 8 — kh Sweep: Expected Hibernation Count (Teylo et al. parameterization)\\n"
                 "DF=1.0 | Poisson-sampled, kh/D",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    lam_colors = {0.5: "#27ae60", 1.0: "#2ecc71", 2.0: "#f39c12",
                  5.0: "#e67e22", 10.0: "#e74c3c", 20.0: "#c0392b"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for lam in LAMBDA_VALUES:
        d = get("poisson_natural", 1.0, lam5=lam)
        if not d: continue
        ns  = [r["n"] for r in d]
        col = lam_colors.get(lam, "#888")
        lw  = 2.5 if lam == 5.0 else 1.8
        axes[0].plot(ns, [cost_red(r) for r in d], marker="o", lw=lw,
                     color=col, markersize=7, markeredgecolor="white",
                     markeredgewidth=1.2, label=f"λ={lam}/hr", alpha=0.9)
        axes[1].plot(ns, [mk_overhead(r) for r in d], marker="o", lw=lw,
                     color=col, markersize=7, markeredgecolor="white",
                     markeredgewidth=1.2, label=f"λ={lam}/hr", alpha=0.9)
    for ax in axes:
        ax.axhline(0, color="#1a1a2e", ls="--", lw=2.2, alpha=0.8,
                   label="BurstHADS baseline (0%)")
        ax.set_xticks(TASK_COUNTS); ax.grid(alpha=0.3, ls=":")
        ax.set_xlabel("Number of Tasks", fontweight="bold")
        ax.legend(ncol=2, fontsize=8.5)
    axes[0].set_ylabel("Cost Reduction %", fontweight="bold")
    axes[0].set_title("Cost — All Lambda Values\\nHigher λ = more frequent hibernation")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan — All Lambda Values")''',
'''    kh_colors = {0.5: "#27ae60", 1.0: "#2ecc71", 2.0: "#f39c12",
                 3.0: "#f1c40f", 5.0: "#e67e22", 8.0: "#c0392b"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for kh in KH_VALUES:
        d = get("poisson_natural", 1.0, kh5=kh)
        if not d: continue
        ns  = [r["n"] for r in d]
        col = kh_colors.get(kh, "#888")
        lw  = 2.5 if kh == 5.0 else 1.8
        axes[0].plot(ns, [cost_red(r) for r in d], marker="o", lw=lw,
                     color=col, markersize=7, markeredgecolor="white",
                     markeredgewidth=1.2, label=f"kh={kh}", alpha=0.9)
        axes[1].plot(ns, [mk_overhead(r) for r in d], marker="o", lw=lw,
                     color=col, markersize=7, markeredgecolor="white",
                     markeredgewidth=1.2, label=f"kh={kh}", alpha=0.9)
    for ax in axes:
        ax.axhline(0, color="#1a1a2e", ls="--", lw=2.2, alpha=0.8,
                   label="BurstHADS baseline (0%)")
        ax.set_xticks(TASK_COUNTS); ax.grid(alpha=0.3, ls=":")
        ax.set_xlabel("Number of Tasks", fontweight="bold")
        ax.legend(ncol=2, fontsize=8.5)
    axes[0].set_ylabel("Cost Reduction %", fontweight="bold")
    axes[0].set_title("Cost — All kh Values\\nHigher kh = more frequent hibernation")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan — All kh Values")'''
))

edits.append((
'                "Poisson Natural\\n(λ=5/hr)", "Single VM\\nHibernation",',
'                "Poisson Natural\\n(kh=5)", "Single VM\\nHibernation",'
))

edits.append((
'''            d = (get(sc, 1.0, n=n, lam5=5.0) if sc == "poisson_natural"
                 else get(sc, 1.0, n=n))''',
'''            d = (get(sc, 1.0, n=n, kh5=5.0) if sc == "poisson_natural"
                 else get(sc, 1.0, n=n))'''
))

edits.append((
'''    print("\\n" + "="*75)
    print("LAMBDA SWEEP: n=100 | DF=1.0")
    print("="*75)
    print(f"{'Lambda/hr':>10} {'CostRed%':>10} {'MkChg%':>9} {'Notes':>25}")
    print("-"*55)
    for lam in LAMBDA_VALUES:
        d = get("lambda_sweep", 1.0, n=100, lam_val=lam)
        if d:
            cr = cost_red(d[0])
            mk = mk_overhead(d[0])
            note = " (our default)" if lam == 5.0 else ""
            print(f"{lam:>8}/hr  {cr:>9.1f}%  {mk:>8.1f}%{note}")''',
'''    print("\\n" + "="*75)
    print("kh SWEEP: n=100 | DF=1.0 (Teylo et al. Table 9 parameterization)")
    print("="*75)
    print(f"{'kh':>10} {'CostRed%':>10} {'MkChg%':>9} {'Notes':>25}")
    print("-"*55)
    for kh in KH_VALUES:
        d = get("lambda_sweep", 1.0, n=100, kh_val=kh)
        if d:
            cr = cost_red(d[0])
            mk = mk_overhead(d[0])
            note = " (Teylo sc2, worst case)" if kh == 5.0 else ""
            print(f"{kh:>10}  {cr:>9.1f}%  {mk:>8.1f}%{note}")'''
))

missing = []
for i, (old, new) in enumerate(edits):
    cnt = src.count(old)
    if cnt != 1:
        missing.append((i, cnt))
    else:
        src = src.replace(old, new)

if missing:
    print("FAILED edits (index, count found):", missing)
    sys.exit(1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print(f"OK: applied {len(edits)} edits to {path}")
