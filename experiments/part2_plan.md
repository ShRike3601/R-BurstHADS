# Algorithm 1 Part 2: what happens to Dspot violators (pre-registration)

Parent: tag `freeze-fix21`, code fingerprint `2439a00d7f74`. Written and
committed before the run. A record-only measurement: no code change and no
decision rule.

## Why

TCC23 §3.2 describes Part 2 of Algorithm 1 (burst allocation) in three
steps:
1. Tasks violating Dspot move to the burstable instances, one task each, in
   baseline mode.
2. "However, if there still exist tasks violating Dspot and no available
   burstable VM, the procedure allocates them to the cheapest regular
   on-demand VMs."
3. "On the other hand, if a burstable VM remains idle, the task with the
   latest finishing time in the scheduling map is moved to it."

`BurstHADS._allocate_burstable_vms` implements steps 1 and 3, step 1 under
the U5 guard, and **not step 2**. Violators the guard declines, or those
beyond the burstable count, stay on spot VMs past Dspot. There they lack the
migration reserve that Dspot exists to keep.

Step 2 appears in neither DEVIATIONS.md nor `paper.tex` Algorithm 1.
R-BurstHADS inherits the procedure.

## Measurement (`experiments/diag_part2.py`)

The probe wraps `_allocate_burstable_vms` and records, per run:
- the Dspot violators on spot VMs before Part 2;
- the burstables Part 2 launches;
- the tasks it moves onto them;
- the violators still on spot after it, and how many of those are planned to
  finish past D.

It runs on the sweep catalogue, limits on, seeds 0–29, for Burst-HADS and
R-BurstHADS, in two configurations:
- the frozen code (`base`), whose rows must equal `sweep_raw_2439a00d7f74`
  exactly;
- the guard removed (`burst_fill`), whose rows must equal
  `sweep_variant_burst_fill_2439a00d7f74` exactly.

## Reported

Each count is reported overall, by DF, and within the 75 fully feasible
cells:
- runs with a violator before and after Part 2;
- violators left on spot, and those planned past D;
- missed tasks in runs that left a violator on spot.

Under TCC23's text, every violator left on spot would instead go to the
cheapest on-demand VM. The left-behind count is therefore the exposure of
the missing step.
