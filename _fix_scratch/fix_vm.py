import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

edits = []

edits.append((
'''        hibernation_rate : lambda in hibernations-per-second, derived from
                           AWS Spot Advisor interruption frequency.
                           0.0 for burstable and on-demand VMs.''',
'''        hibernation_rate : lambda in hibernations-per-second. NOTE: the
                           values wired up in main.py (0.03-0.04/hr for
                           c5.large/c5.xlarge, 5/2700/s ~= 6.7/hr for
                           m5.xlarge) are NOT derived from AWS Spot
                           Advisor data -- an earlier version of this
                           docstring claimed they were; that claim was
                           checked against AWS's published interruption
                           frequency tables and does not hold (off by
                           4-5 orders of magnitude). m5.xlarge's rate
                           instead matches Teylo et al. (2023) Table 9's
                           sc2 (worst case): lambda = k/D with k=5,
                           D=2700s. c5.large/c5.xlarge's lower rate has
                           no equivalent in that paper -- Teylo et al.
                           do not differentiate hibernation risk by
                           instance type. That per-type differentiation
                           is this thesis's own extension, used to make
                           R-BurstHADS's risk-aware WRR weighting
                           observable; it is not a claim about measured
                           real-world AWS interruption-rate differences
                           between these instance types.
                           0.0 for burstable and on-demand VMs.'''
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
