= Why R-BurstHADS is dearer at small bags: measuring the mechanism (pre-registration)

Parent: tag `freeze-fix21`, code fingerprint `2439a00d7f74`. Written and
committed before the runs. Record-only: no code changes, no decision rule.

## Why

Against a reference-faithful Burst-HADS at DF 2.0, R-BurstHADS is dearer at
small bags and cheaper at n = 200 (T12c). The explanation offered in draft --
"an instance launched for a rescue is paid for whether or not the rescue was
needed" -- is the unpriced-idle-time hypothesis, which was already **refuted**
once in this project: the sc1 diagnostic found R-BurstHADS's replacements 68
to 86% busy (`diag_rb_provisioning.*`, pre-freeze). It may hold in this
different regime, but it is not written until it is measured (ground rule 3).

The pattern it has to explain is not a gradient. By bag size the cost gap runs
+12.7% (n = 50), +9.6% (100), -8.8% (200), -2.0% (300): worst at the smallest
bag, best at 200, back toward zero at 300.

## Measurement (`experiments/diag_provisioned.py`)

Record-only probe, R-BurstHADS runs only, the five DF = 2.0 cells at each bag
size, 30 seeds = 600 runs per configuration:

- **faithful**: variant `ref_p2` (TCC23 §3.2 in full), the configuration the
  finding comes from;
- **guard kept**: variant `base`, where the gap runs the other way, as a
  control.

Every probed run must reproduce its committed sweep row exactly.

Per run it records, for the VMs R-BurstHADS provisions at runtime
(`scheduler.provisioned_vms`: Theorem 1 replacements, tier 3, and the
saturation response) and for the whole fleet:

- billed seconds and cost, per VM, from the same billing intervals the metric
  uses;
- **executed core-seconds**, accumulated over every interval in which a task
  was running on the VM: opened where `exec_start_on_current_vm` is set
  (`VM.start_next_if_free`) and closed where it is cleared, at task completion
  and at a checkpoint (hibernation);
- **utilisation** = executed core-seconds / (billed seconds x vcpu count);
- **cost share** = cost of provisioned VMs / total cost;
- fleet size, in VMs billed.

## Reading, fixed in advance

- If utilisation of provisioned capacity **falls as the bag gets smaller**,
  the idle-capacity reading is supported and may be written.
- If utilisation is flat or high at every bag size while the **cost share**
  rises at small bags, the mechanism is not idle waste but the relative weight
  of one extra instance in a small fleet, and the text must say that instead.
- If neither moves with bag size, no mechanism is established and the paper
  reports the observation without an explanation.

Whatever the outcome, the bag-size split itself is reported as a **post-hoc
subgroup observation** (owner, 2026-09-23): 5 cells per bag size, not
pre-registered, and non-monotone in n.
