import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

edits = []

edits.append((
'''"""
Main simulation entry point — P-BurstHADS experiments.

VM POOL DESIGN (matches paper scale, modern instance types):
  5 VMs total, matching Teylo et al. (2023) pool size.

  HADS pool (3 VMs):
    spot:     c5.large  (low risk,  3%/hr)
              m5.xlarge (HIGH risk, 17%/hr)
    ondemand: c5.large

  BurstHADS / P-BurstHADS pool (5 VMs):
    spot:     c5.large  (low risk,  3%/hr)
              c5.xlarge (low risk,  4%/hr)
              m5.xlarge (HIGH risk, 17%/hr)
    burstable: t3.large (no risk,   0%/hr)
    ondemand:  c5.large (no risk,   0%/hr)

KEY DESIGN PRINCIPLE:
  m5.xlarge has 5.7x higher hibernation rate than c5.large.
  P-BurstHADS detects this via risk-adjusted WRR weights and
  assigns long tasks preferentially to c5/c5.xlarge over m5.xlarge.
  BurstHADS is blind to this difference.

  When we inject explicit hibernation of m5.xlarge:
  - BurstHADS is caught off-guard (assigned long tasks there)
  - P-BurstHADS already moved long tasks away from it
  This produces measurable, defensible cost/makespan differences.

HIBERNATION INJECTION:
  We inject explicit hibernation of the HIGH-RISK VM (m5.xlarge)
  at a controlled time, matching the paper's experimental approach.
  This is scientifically valid — we are testing scheduler resilience
  under the exact conditions the risk model was designed to handle.
"""''',
'''"""
Main simulation entry point — P-BurstHADS experiments.

VM POOL DESIGN (matches paper scale, modern instance types):
  5 VMs total, matching Teylo et al. (2023) pool size.

  HADS pool (3 VMs):
    spot:     c5.large  (low-risk anchor, illustrative)
              m5.xlarge (high-risk anchor, illustrative)
    ondemand: c5.large

  BurstHADS / P-BurstHADS pool (5 VMs):
    spot:     c5.large  (low-risk anchor, illustrative)
              c5.xlarge (low-risk anchor, illustrative)
              m5.xlarge (high-risk anchor, illustrative)
    burstable: t3.large (no risk,   0/hr)
    ondemand:  c5.large (no risk,   0/hr)

HIBERNATION RATE CALIBRATION -- read this before citing these numbers:
  These hibernation_rate values are NOT derived from AWS Spot Advisor
  data (an earlier version of this file claimed they were -- checked
  against AWS's actual published interruption-frequency tables, that
  claim does not hold; the numbers were off by 4-5 orders of
  magnitude). They instead follow Teylo et al. (2023)'s own
  methodology: the paper is explicit that its hibernation/resume
  events are SYNTHETIC and Poisson-distributed (lambda = k/D, where k
  is the expected event count over the deadline D), not measured from
  AWS. Their Table 9 worst case (sc2) uses k=5 over D=2700s, i.e.
  about 6.7 events/hr.

  m5.xlarge's hibernation_rate below (5/2700 per second) matches
  Teylo's sc2 exactly. c5.large/c5.xlarge's rate (0.03-0.04/hr) has no
  equivalent in Teylo's paper -- the paper does not differentiate
  hibernation risk by instance type at all. That differentiation is
  this thesis's OWN extension on top of the paper: R-BurstHADS's WRR
  weighting is risk-aware BY INSTANCE TYPE, which only produces a
  measurable effect if some spot VMs are modeled as riskier than
  others. The resulting gap between m5.xlarge and c5.large here is a
  deliberately large, illustrative contrast chosen to make that
  mechanism observable in a short simulated run -- it is not a claim
  about real-world AWS interruption-frequency differences between
  these two instance types.

KEY DESIGN PRINCIPLE:
  m5.xlarge is modeled with a much higher hibernation rate than
  c5.large (illustrative contrast, see above -- not AWS-measured).
  R-BurstHADS detects this via risk-adjusted WRR weights and
  assigns long tasks preferentially to c5/c5.xlarge over m5.xlarge.
  BurstHADS is blind to this difference.

  When we inject explicit hibernation of m5.xlarge:
  - BurstHADS is caught off-guard (assigned long tasks there)
  - R-BurstHADS already moved long tasks away from it
  This produces measurable cost/makespan differences -- but only
  because the labeled risk was made real for this specific run; see
  the "none" (no-hibernation) scenario for what happens when it isn't.

HIBERNATION INJECTION:
  We deterministically inject hibernation of the VM currently labeled
  highest-risk (m5.xlarge) at a controlled time. This targeting is OUR
  extension, not Teylo et al.'s -- their Poisson model does not single
  out a specific instance type. It lets us test whether R-BurstHADS's
  risk-aware WRR weighting actually pays off when the labeled risk
  materializes, and what it costs when it doesn't.
"""'''
))

edits.append((
'''    """
    BurstHADS / P-BurstHADS pool: 5 VMs total.
    Critically: m5.xlarge has 5.7x higher hibernation rate than c5.large.
    P-BurstHADS exploits this; BurstHADS is blind to it.
    """''',
'''    """
    BurstHADS / P-BurstHADS pool: 5 VMs total.
    m5.xlarge is modeled with a much higher hibernation rate than
    c5.large -- an illustrative contrast, not an AWS-measured
    differential (see module docstring). R-BurstHADS exploits this
    via WRR; BurstHADS is blind to it.
    """'''
))

missing = []
for i, (old, new) in enumerate(edits):
    cnt = src.count(old)
    if cnt != 1:
        missing.append((i, cnt))
    else:
        src = src.replace(old, new)

# Global replace (expected 3 occurrences each) -- m5.xlarge rate,
# now matching Teylo et al. sc2 (kh=5, D=2700s) exactly instead of
# an unsourced 5.0/3600.
cnt_rate = src.count("hibernation_rate=5.0/3600")
if cnt_rate != 3:
    missing.append(("rate_count", cnt_rate))
else:
    src = src.replace("hibernation_rate=5.0/3600", "hibernation_rate=5.0/2700")

cnt_comment = src.count("# high-demand pool")
if cnt_comment != 2:
    missing.append(("comment_count", cnt_comment))
else:
    src = src.replace("# high-demand pool",
                       "# Teylo et al. sc2 (kh=5, D=2700s), illustrative high-risk anchor")

# Decouple scenario-target selection from hibernation_rate (which is
# now less meaningful as a per-VM discriminator on its own) -- select
# by memory_gb instead, which still uniquely picks m5.xlarge (16.0 GB,
# highest in every pool) and keeps existing scenario behavior
# unchanged.
cnt_max = src.count("target = max(spot_vms, key=lambda v: v.hibernation_rate)")
if cnt_max != 1:
    missing.append(("max_count", cnt_max))
else:
    src = src.replace(
        "target = max(spot_vms, key=lambda v: v.hibernation_rate)",
        "target = max(spot_vms, key=lambda v: v.memory_gb)  # m5.xlarge: highest memory_gb in every pool"
    )

cnt_sorted = src.count("target = sorted(spot_vms,\n                            key=lambda v: v.hibernation_rate)[-1]")
if cnt_sorted != 1:
    missing.append(("sorted_count", cnt_sorted))
else:
    src = src.replace(
        "target = sorted(spot_vms,\n                            key=lambda v: v.hibernation_rate)[-1]",
        "target = sorted(spot_vms,\n                            key=lambda v: v.memory_gb)[-1]  # m5.xlarge"
    )

if missing:
    print("FAILED edits (index, count found):", missing)
    sys.exit(1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print(f"OK: applied edits to {path}")
