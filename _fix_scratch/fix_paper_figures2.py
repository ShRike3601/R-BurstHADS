import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

edits = []

# 1. LAMBDA_VALUES definition -> KH_VALUES
edits.append((
'LAMBDA_VALUES = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]',
'KH_VALUES     = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0]  # Teylo et al. Table 9: sc1 kh=1, sc5 kh=3, sc2 kh=5 (worst case)'
))

# 2. worker() poisson event generation: kh/D parameterization instead of a
#    fixed hourly rate (Teylo et al. 2023, Table 9)
edits.append((
'''        lam_m5 = extra.get("lambda_m5", 5.0) / 3600.0
        lam_c5 = 0.03 / 3600.0''',
'''        # Teylo et al. (2023) Table 9 parameterization: lambda = kh / D,
        # where kh is the EXPECTED NUMBER of hibernation events over the
        # job's deadline D (not a fixed hourly rate). sc2 (kh=5, worst
        # case) is used as m5.xlarge's default here. c5.large keeps a
        # fixed low background rate -- illustrative only; Teylo et al.
        # do not differentiate hibernation risk by instance type.
        kh_m5  = extra.get("kh_m5", 5.0)
        lam_m5 = kh_m5 / gdl
        lam_c5 = 0.03 / 3600.0'''
))

# 3. poisson_def job list entry
edits.append((
'''                jobs.append(("poisson_def", cls, n, seed, 1.0,
                             "poisson", {"lambda_m5": 5.0}))''',
'''                jobs.append(("poisson_def", cls, n, seed, 1.0,
                             "poisson", {"kh_m5": 5.0}))'''
))

# 4. kh sweep job list loop (was "Lambda sweep")
edits.append((
'''    # Lambda sweep across all LAMBDA_VALUES, n=100 (Fig F)
    for lam in LAMBDA_VALUES:
        for seed in SEEDS:
            for cls in ["BurstHADS", "RBurstHADS"]:
                jobs.append((f"lam_{lam}", cls, 100, seed, 1.0,
                             "poisson", {"lambda_m5": lam}))''',
'''    # kh sweep across all KH_VALUES, n=100 (Fig F) -- Teylo et al. Table 9
    for kh in KH_VALUES:
        for seed in SEEDS:
            for cls in ["BurstHADS", "RBurstHADS"]:
                jobs.append((f"kh_{kh}", cls, 100, seed, 1.0,
                             "poisson", {"kh_m5": kh}))'''
))

# 5. Fig A characterization jobs: convert c5.large's fixed 0.03/hr rate to
#    an equivalent kh over n=100's own deadline
edits.append((
'''    # Poisson model characterization for Fig A
    # Need counts of hibernation events per run for m5.xlarge and c5.large
    for seed in range(200):   # 200 seeds for clean histogram
        jobs.append(("hib_count_m5", "BurstHADS", 100, seed, 1.0,
                     "poisson", {"lambda_m5": 5.0}))
        jobs.append(("hib_count_low", "BurstHADS", 100, seed, 1.0,
                     "poisson", {"lambda_m5": 0.03}))''',
'''    # Poisson model characterization for Fig A
    # Need counts of hibernation events per run for m5.xlarge and c5.large.
    # c5.large's fixed low background rate (0.03/hr) is expressed as an
    # equivalent kh over n=100's own deadline so it flows through the
    # same kh/D worker logic as m5.xlarge's Teylo sc2 parameterization.
    _gdl100_ch, _ = __import__('main').compute_deadlines(100, 1.0)
    _kh_low_equiv = 0.03 / 3600.0 * _gdl100_ch
    for seed in range(200):   # 200 seeds for clean histogram
        jobs.append(("hib_count_m5", "BurstHADS", 100, seed, 1.0,
                     "poisson", {"kh_m5": 5.0}))
        jobs.append(("hib_count_low", "BurstHADS", 100, seed, 1.0,
                     "poisson", {"kh_m5": _kh_low_equiv}))'''
))

# 6. agg() signature: lam= was a dead parameter, never called with it --
#    rename for terminology consistency now that the extra-dict key changed
edits.append((
'    def agg(label, cls, n=None, df=None, lam=None):',
'    def agg(label, cls, n=None, df=None, kh=None):'
))

# 7. agg() body: filter on the renamed extra-dict key
edits.append((
'''        if lam is not None:
            rows = [r for r in rows
                    if abs(r.get("extra", {}).get("lambda_m5", -1) - lam) < 0.01
                    if "extra" in r]''',
'''        if kh is not None:
            rows = [r for r in rows
                    if abs(r.get("extra", {}).get("kh_m5", -1) - kh) < 0.01
                    if "extra" in r]'''
))

# 8. Fig A legend labels
edits.append((
'                 label=f"m5.xlarge (lambda=5/hr)\\nmean={avg(m5_counts):.1f} events/run",',
'                 label=f"m5.xlarge (kh=5, Teylo sc2)\\nmean={avg(m5_counts):.1f} events/run",'
))
edits.append((
'                 label=f"c5.large (lambda=0.03/hr)\\nmean={avg(c5_counts):.2f} events/run",',
'                 label=f"c5.large (0.03/hr, illustrative)\\nmean={avg(c5_counts):.2f} events/run",'
))

# 9. Fig A right panel: hoist gdl_100/lam out of the loop, use kh/D
edits.append((
'''    first_times = []
    for seed in range(200):
        rng = np.random.default_rng(seed + 10000)
        lam = 5.0 / 3600.0
        gdl_100, _ = __import__('main').compute_deadlines(100, 1.0)
        t_first = float(rng.exponential(1.0 / lam))
        if t_first < gdl_100:
            first_times.append(t_first)''',
'''    first_times = []
    gdl_100, _ = __import__('main').compute_deadlines(100, 1.0)
    lam = 5.0 / gdl_100   # Teylo et al. sc2: kh=5 over deadline D
    for seed in range(200):
        rng = np.random.default_rng(seed + 10000)
        t_first = float(rng.exponential(1.0 / lam))
        if t_first < gdl_100:
            first_times.append(t_first)'''
))

# 10. axvline using the now-shared `lam` variable instead of a hardcoded rate
edits.append((
'''    axes[1].axvline(1.0/( 5.0/3600.0), color="#e67e22", ls=":", lw=2,
                    label=f"1/lambda = {1.0/(5.0/3600.0):.0f}s (expected)")''',
'''    axes[1].axvline(1.0/lam, color="#e67e22", ls=":", lw=2,
                    label=f"1/lambda = {1.0/lam:.0f}s (expected)")'''
))

# 11. Fig A suptitle -- was a false AWS-derivation claim
edits.append((
'''    plt.suptitle("Fig A — Poisson Hibernation Model: Spot VM Interruption Frequency\\n"
                 "m5.xlarge vs c5.large, at documented AWS interruption rates",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig A — Synthetic Poisson Hibernation Model (Teylo et al. sc2)\\n"
                 "m5.xlarge: kh=5 over deadline D; c5.large: fixed low background rate",
                 fontweight="bold", fontsize=13)'''
))

# 12. Fig B right-panel title
edits.append((
'''    axes[1].set_title("Poisson Natural Hibernation (lambda=5/hr)\\n"
                      "Stochastic timing — each run different",
                      fontweight="bold")''',
'''    axes[1].set_title("Poisson Natural Hibernation (kh=5, Teylo et al. sc2)\\n"
                      "Stochastic timing — each run different",
                      fontweight="bold")'''
))

missing = []
for i, (old, new) in enumerate(edits):
    cnt = src.count(old)
    if cnt != 1:
        missing.append((i, cnt))
    else:
        src = src.replace(old, new)

if missing:
    print("FAILED top-level edits (index, count found):", missing)
    sys.exit(1)

# ── Fig F block: whole-section rewrite (many LAMBDA_VALUES usages) ─────────
start_marker = '    # ── FIG F: LAMBDA SWEEP'
end_marker   = '    save(fig, "figF_lambda_sweep.png")\n'

s_idx = src.find(start_marker)
if s_idx == -1:
    print("FAILED: Fig F start marker not found")
    sys.exit(1)
e_idx = src.find(end_marker, s_idx)
if e_idx == -1:
    print("FAILED: Fig F end marker not found")
    sys.exit(1)
e_idx += len(end_marker)

old_block = src[s_idx:e_idx]
new_block = old_block

# Blanket rename first (16 occurrences expected) -- everything after this
# assumes LAMBDA_VALUES is already gone from new_block.
_lv_count = new_block.count('LAMBDA_VALUES')
if _lv_count < 1:
    print("FAILED: no LAMBDA_VALUES occurrences found in Fig F block")
    sys.exit(1)
new_block = new_block.replace('LAMBDA_VALUES', 'KH_VALUES')

block_edits = [
    ('# ── FIG F: LAMBDA SWEEP — OPERATING ENVELOPE ─────────────────────────────',
     '# ── FIG F: kh SWEEP — OPERATING ENVELOPE (Teylo et al. parameterization) ──'),
    ('for lam in KH_VALUES:\n        lbl = f"lam_{lam}"',
     'for kh in KH_VALUES:\n        lbl = f"kh_{kh}"'),
    ('# Left: completion rate vs lambda', '# Left: completion rate vs kh'),
    ('for i, (lam, bp) in enumerate(zip(KH_VALUES, b_pct_lam)):',
     'for i, (kh, bp) in enumerate(zip(KH_VALUES, b_pct_lam)):'),
    ('xy=(lam, bp), xytext=(0, -16),', 'xy=(kh, bp), xytext=(0, -16),'),
    ('label="m5.xlarge real rate (lambda=5/hr)")',
     'label="Teylo et al. sc2 (kh=5, worst case)")'),
    ('axes[0].set_xlabel("m5.xlarge Hibernation Rate lambda (events/hr)",',
     'axes[0].set_xlabel("m5.xlarge Expected Hibernations over Deadline (kh)",'),
    ('axes[0].set_title("Task Completion Rate vs m5.xlarge Hibernation Rate",',
     'axes[0].set_title("Task Completion Rate vs Expected Hibernation Count (kh)",'),
    ('# Right: cost vs lambda — the counterintuitive crossover',
     '# Right: cost vs kh — the counterintuitive crossover'),
    ('label="m5.xlarge real rate")', 'label="Teylo et al. sc2 (kh=5)")'),
    ('axes[1].set_xlabel("m5.xlarge Hibernation Rate lambda (events/hr)",',
     'axes[1].set_xlabel("m5.xlarge Expected Hibernations over Deadline (kh)",'),
    ('axes[1].set_title("Average Total Cost vs m5.xlarge Hibernation Rate",',
     'axes[1].set_title("Average Total Cost vs Expected Hibernation Count (kh)",'),
    ('''plt.suptitle("Fig F — Cost and Completion vs m5.xlarge Hibernation Rate\\n"
                 "n=100 tasks | Poisson hibernation | 20 seeds per lambda value",''',
     '''plt.suptitle("Fig F — Cost and Completion vs Expected Hibernation Count (kh)\\n"
                 "n=100 tasks | Poisson hibernation, Teylo et al. sc2 parameterization | 20 seeds per kh value",'''),
]

block_missing = []
for i, (old, new) in enumerate(block_edits):
    cnt = new_block.count(old)
    if cnt != 1:
        block_missing.append((i, cnt, old[:60]))
    else:
        new_block = new_block.replace(old, new)

if block_missing:
    print("FAILED Fig F block edits (index, count found, old-snippet):", block_missing)
    sys.exit(1)

src = src[:s_idx] + new_block + src[e_idx:]

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print(f"OK: applied {len(edits)} top-level edits + {len(block_edits)} Fig F block edits to {path}")
