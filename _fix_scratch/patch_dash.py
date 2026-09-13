path = '_fix_scratch/fix_analyze.py'
src = open(path, encoding='utf-8').read()
old = "'''    # ── FIG 13: TASK COMPLETION RATE (PRIMARY RESULT) ───────────────────────\n"
new = "'''    # ── FIG 13: TASK COMPLETION RATE (PRIMARY RESULT) ────────────────────────\n"
cnt = src.count(old)
print('count found:', cnt)
assert cnt == 1, cnt
src = src.replace(old, new, 1)
open(path, 'w', encoding='utf-8').write(src)
print('patched')
