import re, sys

path = "/root/mnt/analyze_parallel.py"  # placeholder, real path passed via argv
path = sys.argv[1]

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

edits = []

edits.append((
'    axes[0].set_title("Cost — No Hibernation\\nExpected: both schedulers identical (~0%)")',
'    axes[0].set_title("Cost Reduction % — No Hibernation Scenario")'
))

edits.append((
'''    plt.suptitle("Fig 1 — Baseline: No Hibernation\\n"
                 "R-BurstHADS should match BurstHADS — red dashed = BurstHADS baseline",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig 1 — No Hibernation Scenario | DF=1.0 and DF=2.0\\n"
                 "Red dashed = BurstHADS reference (0%)",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'    axes[0].set_title("Cost Reduction — Primary Result\\nPositive = R-BurstHADS cheaper")',
'    axes[0].set_title("Cost Reduction — Pool Saturation (Early)\\nPositive = R-BurstHADS cheaper")'
))

edits.append((
'''    plt.suptitle("Fig 2 — Pool Saturation (Early): Both Spot VMs Hibernate at t=90s\\n"
                 "Core contribution | DF=1.0 and DF=2.0 | 20 runs per config",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig 2 — Pool Saturation (Early): Both Spot VMs Hibernate at t=90s\\n"
                 "DF=1.0 and DF=2.0 | 20 runs per config",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    for ax in axes:
        ax.axhline(0, color="#1a1a2e", ls="--", lw=2.2, alpha=0.8,
                   label="BurstHADS reference (0%)")
        ax.set_xticks(TASK_COUNTS); ax.grid(alpha=0.3, ls=":")
        ax.set_xlabel("Number of Tasks", fontweight="bold")
        ax.legend(loc="lower left", fontsize=8.5)
    axes[0].set_ylabel("Cost Reduction % over BurstHADS", fontweight="bold")
    axes[0].set_title("Cost Reduction: All Scenarios\\nRed dashed = BurstHADS baseline")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan: All Scenarios\\nNegative = R-BurstHADS faster")
    plt.suptitle("Fig 3 — All Scenarios | DF=1.0 | 20 runs per config\\n"
                 "Bold dashed line = BurstHADS. Above = R-BurstHADS better.",
                 fontweight="bold", fontsize=13)''',
'''    for ax in axes:
        ax.axhline(0, color="#1a1a2e", ls="--", lw=2.2, alpha=0.8,
                   label="BurstHADS reference (0%)")
        ax.set_xticks(TASK_COUNTS); ax.grid(alpha=0.3, ls=":")
        ax.set_xlabel("Number of Tasks", fontweight="bold")
    axes[0].set_ylabel("Cost Reduction % over BurstHADS", fontweight="bold")
    axes[0].set_title("Cost Reduction: All Scenarios\\nRed dashed = BurstHADS baseline")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan: All Scenarios\\nNegative = R-BurstHADS faster")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8.5,
               bbox_to_anchor=(0.5, -0.08), frameon=True)
    plt.suptitle("Fig 3 — All Scenarios | DF=1.0 | 20 runs per config\\n"
                 "Bold dashed line = BurstHADS. Above = R-BurstHADS better.",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    axes[0].set_title("Cost — DF=0.5 (Tight Deadline)\\n"
                      "Does 45s startup latency break our model?")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan — DF=0.5")
    plt.suptitle("Fig 4 — BOUNDARY TEST: DF=0.5 (Tight Deadline)\\n"
                 "Model limit: startup latency may not fit within deadline slack",
                 fontweight="bold", fontsize=13, color="#c0392b")''',
'''    axes[0].set_title("Cost — DF=0.5 (Tight Deadline Boundary)")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan — DF=0.5")
    plt.suptitle("Fig 4 — Boundary Test: DF=0.5 (Tight Deadline)\\n"
                 "45s VM startup latency relative to deadline slack",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    plt.suptitle("Fig 6 — Single VM vs Full Pool Saturation\\n"
                 "Does R-BurstHADS help even when only ONE spot VM hibernates? | DF=1.0",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig 6 — Single-VM vs Full Pool Saturation | DF=1.0\\n"
                 "Comparing hibernation of one spot VM vs both",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    axes[0].set_ylabel("Cost Reduction %", fontweight="bold")
    axes[0].set_title("Cost vs Hibernation Rate\\nHigher risk → larger advantage")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan vs Hibernation Rate")
    plt.suptitle("Fig 8 — Lambda Sweep: Varying m5.xlarge Hibernation Risk\\n"
                 "DF=1.0 | Poisson-sampled | Where does R-BurstHADS advantage appear?",
                 fontweight="bold", fontsize=13)''',
'''    axes[0].set_ylabel("Cost Reduction %", fontweight="bold")
    axes[0].set_title("Cost Reduction % vs Hibernation Rate")
    axes[1].set_ylabel("Makespan Overhead %", fontweight="bold")
    axes[1].set_title("Makespan Overhead % vs Hibernation Rate")
    plt.suptitle("Fig 8 — Lambda Sweep: Varying m5.xlarge Hibernation Rate\\n"
                 "DF=1.0 | Poisson-sampled",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    ax.axhline(0, color="#888", ls="--", lw=1.2, alpha=0.6)
    ax.axvline(0, color="#888", ls="--", lw=1.2, alpha=0.6)
    xmin = min(mks) - 15
    ax.text(xmin, max(reds)+5,
            "Lower cost AND\\nFaster makespan\\n(Best region)",
            ha="left", va="top", fontsize=9.5, color="#27ae60",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#eafaf1",
                      edgecolor="#27ae60", alpha=0.9))
    plt.colorbar(sc_, ax=ax, label="Cost Reduction %", shrink=0.8)''',
'''    ax.axhline(0, color="#888", ls="--", lw=1.2, alpha=0.6)
    ax.axvline(0, color="#888", ls="--", lw=1.2, alpha=0.6)
    plt.colorbar(sc_, ax=ax, label="Cost Reduction %", shrink=0.8)'''
))

edits.append((
'''    # ── FIG 13: TASK COMPLETION RATE (PRIMARY RESULT) ────────────────────────
    # This is the headline figure. Raw cost reduction is invalid when
    # completion rates differ. Completion rate is the correct primary metric.
    fig, ax = plt.subplots(figsize=(10, 6))
    w = 0.35
    data_sat = get("saturated_early", 1.0)
    ns_  = [r["n"] for r in data_sat]
    xp   = np.arange(len(ns_))
    b_pct = [r["burst_pct_avg"]  for r in data_sat]
    d_pct = [r["rburst_pct_avg"] for r in data_sat]
    b_std = [r["burst_pct_std"]  for r in data_sat]
    d_std = [r["rburst_pct_std"] for r in data_sat]

    ax.bar(xp-w/2, b_pct, width=w, color="#c0392b", alpha=0.85,
           label="BurstHADS", edgecolor="white", yerr=b_std, capsize=5)
    ax.bar(xp+w/2, d_pct, width=w, color="#27ae60", alpha=0.85,
           label="R-BurstHADS", edgecolor="white", yerr=d_std, capsize=5)

    for i, (bp, dp) in enumerate(zip(b_pct, d_pct)):
        ax.text(xp[i]-w/2, bp+2, f"{bp:.0f}%", ha="center",
                fontsize=9.5, fontweight="bold", color="#c0392b")
        ax.text(xp[i]+w/2, dp+2, f"{dp:.0f}%", ha="center",
                fontsize=9.5, fontweight="bold", color="#27ae60")

    ax.axhline(100, color="#27ae60", ls="--", lw=1.2, alpha=0.5)
    ax.annotate(
        "BurstHADS routes all rescued\\ntasks to 1 on-demand VM.\\nQueue exceeds deadline.",
        xy=(xp[3]-w/2, b_pct[3]), xytext=(2.5, 55),
        fontsize=9, color="#c0392b",
        arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.2),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="#c0392b", alpha=0.9))

    ax.set_xticks(xp); ax.set_xticklabels([str(n) for n in ns_])
    ax.set_xlabel("Number of Tasks", fontweight="bold")
    ax.set_ylabel("% Tasks Completed Within Deadline", fontweight="bold")
    ax.set_title("Fig 13 — Task Completion Rate: Pool Saturation\\n"
                 "PRIMARY RESULT: R-BurstHADS completes 100% | BurstHADS fails at scale",
                 fontweight="bold", pad=12)
    ax.set_ylim(0, 115)
    ax.legend(framealpha=0.95)
    ax.grid(axis="y", alpha=0.3, ls=":")
    plt.tight_layout()
    save(fig, "fig13_task_completion_rate.png")''',
'''    # ── TASK COMPLETION RATE: reported as text, not a figure ────────────────
    # Every task count in this scenario lands at ~100% completion for both
    # schedulers (see the per-n table printed below). Two flat bars pinned
    # at 100% carry no information a sentence doesn't, so this is reported
    # in the summary table instead of a chart.
    data_sat = get("saturated_early", 1.0)
    ns_  = [r["n"] for r in data_sat]
    xp   = np.arange(len(ns_))
    both_100 = all(r["burst_pct_avg"] >= 99.5 and r["rburst_pct_avg"] >= 99.5
                   for r in data_sat)
    print("Task completion (Pool Saturation Early, DF=1.0): "
          + ("both schedulers complete ~100% of tasks at every task count "
             "(see table below)" if both_100
             else "completion rates differ by task count -- see table below"))'''
))

edits.append((
'''    axes[1].set_title("BurstHADS Task Outcomes\\n"
                      "Red = tasks that never finish (silently abandoned)",
                      fontweight="bold")
    axes[1].legend(); axes[1].grid(axis="y", alpha=0.3, ls=":")

    plt.suptitle("Fig 14 — Cost per Completed Task + BurstHADS Failure Breakdown\\n"
                 "Pool Saturation | DF=1.0 | 20 runs | R-BurstHADS ~57% cheaper per task",
                 fontweight="bold", fontsize=13)''',
'''    axes[1].set_title("BurstHADS Task Outcomes\\n"
                      "Red = tasks not completed before deadline",
                      fontweight="bold")
    axes[1].legend(); axes[1].grid(axis="y", alpha=0.3, ls=":")

    plt.suptitle("Fig 14 — Cost per Completed Task and Task Outcomes (BurstHADS)\\n"
                 "Pool Saturation | DF=1.0 | 20 runs",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    axes[0].set_title("Cost per Completed Task\\n"
                      "Valid comparison: same denominator for both schedulers",
                      fontweight="bold")''',
'''    axes[0].set_title("Cost per Completed Task\\n"
                      "Same denominator for both schedulers",
                      fontweight="bold")'''
))

edits.append((
'''    print("\\n" + "="*75)
    print("PRIMARY RESULT: SATURATED EARLY | DF=1.0")
    print("(corrected: completion rate + cost-per-task are the valid metrics)")
    print("="*75)''',
'''    print("\\n" + "="*75)
    print("SATURATED EARLY | DF=1.0 -- SUMMARY")
    print("(completion rate and cost-per-completed-task, both schedulers)")
    print("="*75)'''
))

edits.append((
'    print(f"\\nAll 12 graphs saved to: {OUTPUT_DIR}")',
'    print(f"\\nAll figures saved to: {OUTPUT_DIR}")'
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
