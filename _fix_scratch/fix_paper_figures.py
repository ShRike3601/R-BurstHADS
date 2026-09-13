import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

edits = []

edits.append((
'''    axes[0].set_title("Hibernation Event Count Distribution\\n"
                      "m5.xlarge hibernates frequently; c5.large rarely",
                      fontweight="bold")''',
'''    axes[0].set_title("Hibernation Event Count per Run (200 runs)",
                      fontweight="bold")'''
))

edits.append((
'''    plt.suptitle("Fig A — Poisson Hibernation Model: Pool Saturation is a Real AWS Scenario\\n"
                 "m5.xlarge generates 8-17 hibernation events per run at documented rates",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig A — Poisson Hibernation Model: Spot VM Interruption Frequency\\n"
                 "m5.xlarge vs c5.large, at documented AWS interruption rates",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    axes[0].axhline(100, color="#27ae60", ls="--", lw=1.5, alpha=0.7,
                    label="R-BurstHADS: 100%")''',
'''    axes[0].axhline(100, color="#27ae60", ls="--", lw=1.5, alpha=0.7,
                    label="100% reference line")'''
))

edits.append((
'''    plt.suptitle("Fig B — Task Completion Rate: Deterministic vs Stochastic Hibernation\\n"
                 "R-BurstHADS maintains near-100% in both conditions",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig B — Task Completion Rate: Deterministic vs Stochastic Hibernation",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    axes[0].set_title("Raw Cost\\n"
                      "BurstHADS appears cheaper — but completes fewer tasks",
                      fontweight="bold", color="#c0392b")
    axes[0].legend(fontsize=9); axes[0].grid(axis="y", alpha=0.3, ls=":")
    # Add completion % annotation
    for i, n in enumerate(TASK_COUNTS):
        bp = b_sat[i]["pct_avg"] if b_sat[i] else 0
        axes[0].text(xpos[i]-w/2, b_raw[i]*0.5, f"{bp:.0f}%\\ncomplete",
                     ha="center", fontsize=7.5, color="white", fontweight="bold")''',
'''    axes[0].set_title("Raw Total Cost (Not Normalized by Completions)",
                      fontweight="bold")
    axes[0].legend(fontsize=9); axes[0].grid(axis="y", alpha=0.3, ls=":")
    # Completion % annotation -- dark text on a light box so it stays
    # legible whether it lands on a colored bar or the white background.
    ymax_raw = max(max(b_raw), max(r_raw))
    for i, n in enumerate(TASK_COUNTS):
        bp = b_sat[i]["pct_avg"] if b_sat[i] else 0
        axes[0].text(xpos[i]-w/2, b_raw[i] + ymax_raw*0.03, f"{bp:.0f}% complete",
                     ha="center", va="bottom", fontsize=7.5, color="#333",
                     fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                               edgecolor="none", alpha=0.85))'''
))

edits.append((
'''    axes[1].set_title("Cost per Completed Task\\n"
                      "Valid comparison: normalized by work delivered",
                      fontweight="bold", color="#27ae60")''',
'''    axes[1].set_title("Cost per Completed Task (Normalized by Completions)",
                      fontweight="bold")'''
))

edits.append((
'''    plt.suptitle("Fig C — Cost Comparison: Raw (invalid) vs Normalized (valid)\\n"
                 "Pool Saturation | DF=1.0 | R-BurstHADS 58-64% cheaper per completed task",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig C — Total Cost: Raw vs Normalized by Completed Tasks\\n"
                 "Pool Saturation | DF=1.0",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''    axes[0].set_title("Task Completion vs Hibernation Rate\\n"
                      "BurstHADS fails above lambda > 1/hr",
                      fontweight="bold")''',
'''    axes[0].set_title("Task Completion Rate vs m5.xlarge Hibernation Rate",
                      fontweight="bold")'''
))

edits.append((
'''            axes[1].annotate("crossover:\\nBurstHADS spends more\\n(on tasks that fail)",
                             xy=(LAMBDA_VALUES[i+1], b_cst_lam[i+1]),
                             xytext=(LAMBDA_VALUES[i+1]*1.5,
                                     max(b_cst_lam)*0.7),
                             fontsize=8.5, color="#c0392b",
                             arrowprops=dict(arrowstyle="->",
                                             color="#c0392b", lw=1.2),
                             bbox=dict(boxstyle="round,pad=0.3",
                                       facecolor="white",
                                       edgecolor="#c0392b", alpha=0.9))''',
'''            axes[1].annotate("cost ordering flips here",
                             xy=(LAMBDA_VALUES[i+1], b_cst_lam[i+1]),
                             xytext=(LAMBDA_VALUES[i+1]*1.5,
                                     max(b_cst_lam)*0.7),
                             fontsize=8.5, color="#555",
                             arrowprops=dict(arrowstyle="->",
                                             color="#555", lw=1.2),
                             bbox=dict(boxstyle="round,pad=0.3",
                                       facecolor="white",
                                       edgecolor="#555", alpha=0.9))'''
))

edits.append((
'''    axes[1].set_title("Cost vs Hibernation Rate\\n"
                      "BurstHADS cost rises as it spends on doomed tasks",
                      fontweight="bold")''',
'''    axes[1].set_title("Average Total Cost vs m5.xlarge Hibernation Rate",
                      fontweight="bold")'''
))

edits.append((
'''    plt.suptitle("Fig F — Operating Envelope: Where R-BurstHADS Advantage Grows\\n"
                 "n=100 tasks | Poisson hibernation | 20 seeds per lambda value",
                 fontweight="bold", fontsize=13)''',
'''    plt.suptitle("Fig F — Cost and Completion vs m5.xlarge Hibernation Rate\\n"
                 "n=100 tasks | Poisson hibernation | 20 seeds per lambda value",
                 fontweight="bold", fontsize=13)'''
))

edits.append((
'''        axes[1].set_title("Recovery Time vs Workload Size\\n"
                          "O(1): constant regardless of task count (Theorem 2)",
                          fontweight="bold")''',
'''        axes[1].set_title("Recovery Time vs Workload Size",
                          fontweight="bold")'''
))

edits.append((
'''        plt.suptitle("Fig X — Recovery Time: R-BurstHADS Restores Parallel Execution\\n"
                     f"Mean T_recovery = {avg(rec_times):.1f}s | "
                     "Independent of workload size | Validates Theorem 2",
                     fontweight="bold", fontsize=13)''',
'''        plt.suptitle("Fig X — Recovery Time After Hibernation (R-BurstHADS)\\n"
                     f"Mean T_recovery = {avg(rec_times):.1f}s across all runs",
                     fontweight="bold", fontsize=13)'''
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
