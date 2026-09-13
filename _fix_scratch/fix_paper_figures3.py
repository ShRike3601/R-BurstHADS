import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()
orig = src

# All edits below are single-line, unique substrings (verified by exact count)
# that switch fig B's right (Poisson) panel and fig C's right (cost-per-task)
# panel from plotting against raw TASK_COUNTS values to index positions
# (xpos = np.arange(len(TASK_COUNTS)), already defined earlier in each figure's
# block for its left/bar panel) -- fixing the "10"/"20" tick-label overlap.
edits = [
    # Fig B right panel: two errorbar series plotted against raw task counts.
    ('axes[1].errorbar(TASK_COUNTS, bp_pct, yerr=bp_std, marker="o", lw=2.5,',
     'axes[1].errorbar(xpos, bp_pct, yerr=bp_std, marker="o", lw=2.5,'),
    ('axes[1].errorbar(TASK_COUNTS, rp_pct, yerr=rp_std, marker="o", lw=2.5,',
     'axes[1].errorbar(xpos, rp_pct, yerr=rp_std, marker="o", lw=2.5,'),
    # Fig B right panel: n=300 annotation anchored at the raw task-count value.
    ('xy=(TASK_COUNTS[-1], rp_pct[-1]),',
     'xy=(xpos[-1], rp_pct[-1]),'),
    # Fig C right panel: two line series plotted against raw task counts.
    ('axes[1].plot(TASK_COUNTS, b_cpt, marker="o", lw=2.5, color="#c0392b",',
     'axes[1].plot(xpos, b_cpt, marker="o", lw=2.5, color="#c0392b",'),
    ('axes[1].plot(TASK_COUNTS, r_cpt, marker="o", lw=2.5, color="#2c3e50",',
     'axes[1].plot(xpos, r_cpt, marker="o", lw=2.5, color="#2c3e50",'),
    # Fig C right panel: per-point cost-savings annotation anchored at n.
    ('xy=(TASK_COUNTS[i], dc),',
     'xy=(xpos[i], dc),'),
]

for old, new in edits:
    cnt = src.count(old)
    assert cnt == 1, f"expected exactly 1 occurrence, got {cnt}: {old!r}"
    src = src.replace(old, new, 1)

# Both fig B and fig C right panels end with this identical tick-setting line
# (2 occurrences) -- switch both to index-based ticks with real labels.
old_ticks = 'axes[1].set_xticks(TASK_COUNTS)'
new_ticks = 'axes[1].set_xticks(xpos); axes[1].set_xticklabels([str(n) for n in TASK_COUNTS])'
n_ticks = src.count(old_ticks)
assert n_ticks == 2, f"expected 2 tick-line matches, got {n_ticks}"
src = src.replace(old_ticks, new_ticks)

assert src != orig, "no changes applied"
with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print(f"OK: paper_figures.py -- patched {len(edits)} line edits and {n_ticks} tick lines")
