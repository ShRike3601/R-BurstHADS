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

## Amendment, 2026-09-24: the substitution test

The first run refuted the amortisation reading it was written to test. Under
the faithful baseline, R-BurstHADS's provisioned capacity is 33.6% utilised at
n = 50; under the guard-kept baseline the same capacity in the same cells is
62.7% utilised. Utilisation of R-BurstHADS's own VMs cannot depend on the
baseline unless R-BurstHADS's own behaviour changed -- and it did, because it
inherits the guard through the shared primary schedule (owner, 2026-09-24).

**Hypothesis (substitution).** Without the guard both schedulers fill their
burstables unconditionally. At a loose deadline with a small bag, slow cheap
burstables are a perfectly good strategy, so the work goes there; R-BurstHADS
provisions spot capacity on top of that, which then sits idle and is billed.

**Predictions, fixed before the run.** At n = 50, DF 2.0:
1. R-BurstHADS places a materially larger share of its executed work on
   burstable instances under the faithful configuration than under the
   guard-kept one.
2. Within the faithful runs, provisioned capacity is idle in the same runs
   where burstables are busy: a negative correlation across runs between
   burstable work share and provisioned utilisation, and a population of runs
   in the "burstables busy, provisioned idle" quadrant.

**If either prediction fails, the reading is wrong** and the paper says the
mechanism is unexplained rather than substituting another story.

Reported by bag size and configuration: burstable share of executed
core-seconds, burstable share of cost, the correlation above, and the quadrant
counts.
