import re, sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()
orig = src

# 1) 8x "ns = [r["n"] for r in d]" (fig01,02,03,04,05,06,07,09) currently holds
#    raw TASK_COUNTS values used directly as x-axis data on a linear axis.
#    Remap to each value's index in TASK_COUNTS so the axis becomes categorical.
#    (\bns\b excludes the unrelated "ns_" variables used by fig10/fig11.)
pattern = re.compile(r'\bns\b\s*=\s*\[r\["n"\] for r in d\]')
src, n1 = pattern.subn('ns = [TASK_COUNTS.index(r["n"]) for r in d]', src)
assert n1 == 8, f"expected 8 'ns = [r[\"n\"]...]' matches, got {n1}"

# 2) Same 8 figures each end their per-axes loop with this identical tick line
#    that pins ticks at the raw TASK_COUNTS values. Switch to index positions
#    (xpos, defined once near the top of the __main__ block) with the actual
#    task-count numbers as labels.
old_ticks = 'ax.set_xticks(TASK_COUNTS); ax.grid(alpha=0.3, ls=":")'
new_ticks = ('ax.set_xticks(xpos); '
             'ax.set_xticklabels([str(n) for n in TASK_COUNTS]); '
             'ax.grid(alpha=0.3, ls=":")')
n2 = src.count(old_ticks)
assert n2 == 8, f"expected 8 tick-line matches, got {n2}"
src = src.replace(old_ticks, new_ticks)

assert src != orig, "no changes applied"
with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print(f"OK: analyze_parallel.py -- patched {n1} ns-assignments and {n2} tick lines")
