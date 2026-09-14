# Fixes 17a, 18, 19, 20 — design, attribution and new baseline (pre-registered)

Written and committed before any run of the variants below. Owner's decisions
(2026-09-15): adopt 17a; reject 17b and 17c (recorded as measured and
rejected); adopt fixes 18, 19 and 20 together with 17a, because they interact
through finish-time prediction.

## The four fixes (all as counterfactual variants in `experiments/variants.py`)

| fix | variant piece | change |
|---|---|---|
| 17a | `_sat17(True, False, False)` | saturation re-placement: `_check_migration` on every target, else Algorithm 4's on-demand attempt |
| 18 | `_boot(True)` | a VM R-BurstHADS provisions starts nothing before its `ready_time`; finish estimates on it count from `ready_time` |
| 19 | `_checkpoint(True)` | a checkpoint credits executed progress, elapsed × speed / (1 + ovh), in all three schedulers |
| 20 | `_u10(True)` | the on-demand fallback's new-VM deadline test charges (1 + ovh), in HADS and Burst-HADS (R-BurstHADS inherits it) |

Each piece already has a faithful copy mode that reproduced the frozen sweep
(`f17_copy` 2,400/2,400, `boot_copy` 800/800, `ckpt_copy` 2,400/2,400,
`u10_copy` 0 strict differences).

## Expectation stated before measuring, to be tested not assumed

The owner expects fix 18 to unmask U10. Read from the code, fix 18 enforces a
boot delay only on VMs R-BurstHADS provisions (`RBurstHADS._create_vm`); the ω in
the fallback test is the deploy time of a new on-demand VM
(`_launch_new_ondemand_vm`), which fix 18 does not delay. The test therefore
stays pessimistic by 45 s minus the omitted overhead after fix 18. This is a
prediction; the measurement decides.

## Runs (frozen code `4f08f48ac35c`, limits on, seeds 0–29)

Individual variants against frozen, already measured and reused as they are:
`f17a` (17a), `boot_wait` (18), `ckpt_exec` (19), `u10_ovh` (20).

New:
1. `boot_u10` — 18 + 20, R-BurstHADS only (HADS and Burst-HADS rows are those of
   `u10_ovh`, since 18 touches only R-BurstHADS): does 20 change runs once 18 is in?
2. `fx_all` — 17a + 18 + 19 + 20, all schedulers.
3. Leave-one-out sets for attribution: `fx_no17a`, `fx_no18` (R-BurstHADS only,
   HADS and Burst-HADS rows from `fx_all`), `fx_no19`, `fx_no20` (all schedulers).

Attribution (`experiments/fix18_20_compare.py`): for each fix X, its individual
effect is X against frozen, and its contribution within the set is `fx_all`
against `fx_all` without X. No additivity is assumed; the two are reported side
by side.

## Adoption and new baseline

1. Apply 17a (`experiments/fix17_adopt_patch.py --a`) and 18/19/20
   (`experiments/fix18_20_adopt_patch.py`) to a clean export; the adopted code must
   reproduce `fx_all` row for row on seeds 0–9, all three schedulers.
2. Apply the same patches to the project, commit.
3. New baseline on the adopted code: checkpoint harness (tag `fix20_df*`), full
   sweep limits on (must equal `fx_all` for all 30 seeds), limits off (`nocap`),
   validation runs on the paper catalogue, then tag `freeze-fix20`.
4. Regenerate the results pack (`RESULTS_PACK.md`) and the six figures in one pass.
   Figures go to `experiments/fig_fix20/`, not `paper/fig/`: nothing under
   `paper/` is touched.
