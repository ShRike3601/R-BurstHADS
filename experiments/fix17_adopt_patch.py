"""
Fix 17 adoption patch for scheduler/r_burst_hads.py, three separable
sub-fixes, mirroring variants._sat17 statement for statement so the adopted
code can reproduce its variant row for row.

Usage: python rb17_patch.py PROJECT_ROOT [--a] [--b] [--c]
Every replacement must match exactly once; on any mismatch nothing is written.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
flags = set(sys.argv[2:])
A, B, C = "--a" in flags, "--b" in flags, "--c" in flags
if not (A or B or C):
    raise SystemExit("choose at least one of --a --b --c")
path = root / "scheduler" / "r_burst_hads.py"
text = path.read_text(encoding="utf-8")
reps = []

if C:
    reps.append((
        """        # Only act when pool is actually saturated (all spot VMs down)
        active_spot = [v for v in self.spot_vms
                       if v.state not in (VM.HIBERNATED, VM.TERMINATED)]
        if len(active_spot) >= len(self.spot_vms):
            return
""",
        """        # Only act when pool is actually saturated (all spot VMs down).
        # Fix 17c: the test used to be len(active_spot) >= len(spot_vms),
        # which returns only when EVERY spot VM is active, so the response
        # fired whenever a single spot VM was down -- the opposite of the
        # condition stated here.
        active_spot = [v for v in self.spot_vms
                       if v.state not in (VM.HIBERNATED, VM.TERMINATED)]
        if active_spot:
            return
"""))

if B:
    reps.append((
        """        if n_extra <= 0:
            return

        # Collect queued (non-running) tasks to redistribute -- a
""",
        """        if n_extra <= 0:
            return

        # Fix 17b: redistribution exists to spread queued work onto newly
        # provisioned capacity. If not even one VM of the kind this response
        # launches is within its instance limit, there is nothing to spread
        # onto, so leave the queues as they are. (Measured on the frozen code:
        # 252 of the 253 responses that moved tasks in the 104 missing runs
        # launched nothing; experiments/diag_u10.txt.)
        room = (self._launches.can_launch_type("spot", self._spot_tpl["vm_type"])
                if use_spot else
                self._launches.can_launch_type("ondemand", BURST_TYPE))
        if not room:
            return

        # Collect queued (non-running) tasks to redistribute -- a
"""))

if A:
    reps.append((
        """                if not vm.can_fit_task(task):
                    continue
                finish = vm.estimate_finish_time(task, current_time)
                if finish < best_finish:
                    best_finish = finish
                    best_vm     = vm
            if best_vm is None:
                best_vm = all_targets[0]
""",
        """                if not vm.can_fit_task(task):
                    continue
                # Fix 17a: the same test tier 0 (_select_replacement_vm) and
                # Burst-HADS's migration apply -- memory, finish by D, CPU
                # credits for a burst-mode burstable, and the Section 3.4
                # spare-time margin for a spot target. The frozen code took
                # the earliest finish even when it lay past D; in the 104
                # runs that missed a deadline that placed 108 of the 109
                # missed tasks (experiments/diag_u10.txt).
                if not self._check_migration(task, vm, current_time, self.D,
                                             burst_mode=vm.is_burstable):
                    continue
                finish = vm.estimate_finish_time(task, current_time)
                if finish < best_finish:
                    best_finish = finish
                    best_vm     = vm
            if best_vm is None:
                # No provisioned target makes D: Algorithm 4's on-demand
                # attempt, as every other placement path ends, instead of a
                # placement known to be late.
                best_vm = self._attempt_ondemand_fallback(task, current_time)
"""))

for old, new in reps:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"MISMATCH ({n} matches):\n{old[:200]}")
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print(f"fix 17 applied: {'a' if A else ''}{'b' if B else ''}{'c' if C else ''} ({len(reps)} hunks)")
